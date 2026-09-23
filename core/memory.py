"""Local preference and context storage for companion-style reasoning."""

from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from typing import Any


DEFAULT_PREFERENCES = {
	"user_facts": {},
	"interests": {},
	"content_preferences": {},
	"avoidances": {},
	"behavioral_signals": {"accepted_recommendations": 0, "rejected_recommendations": 0},
}


class PreferenceStore:
	"""Persist modest preference evidence locally; never treat one turn as fact."""

	_TOPIC_ALIASES = {
		"ai": ("ai", "artificial intelligence", "machine learning", "neural network"),
		"robotics": ("robotics", "robot", "humanoid"),
		"programming": ("programming", "coding", "code", "python", "javascript"),
		"science": ("science", "physics", "quantum", "engineering"),
		"music": ("music", "song", "listen"),
		"gaming": ("gaming", "game", "games"),
	}

	def __init__(self, path: str | Path | None = None) -> None:
		self.path = Path(path) if path else Path(__file__).resolve().parent.parent / "memory" / "preferences.json"
		self.data = self._load()

	def _load(self) -> dict[str, Any]:
		try:
			loaded = json.loads(self.path.read_text(encoding="utf-8"))
		except (FileNotFoundError, json.JSONDecodeError):
			loaded = {}
		return self._merge_defaults(loaded)

	def _merge_defaults(self, loaded: dict[str, Any]) -> dict[str, Any]:
		merged = json.loads(json.dumps(DEFAULT_PREFERENCES))
		for key, value in loaded.items():
			if isinstance(value, dict) and isinstance(merged.get(key), dict):
				merged[key].update(value)
			else:
				merged[key] = value
		return merged

	def save(self) -> None:
		self.path.parent.mkdir(parents=True, exist_ok=True)
		self.path.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")

	def snapshot(self) -> dict[str, Any]:
		return json.loads(json.dumps(self.data))

	def learn_from_text(self, text: str, explicit: bool = False) -> list[str]:
		lower = text.lower()
		changed: list[str] = []
		name_match = re.search(r"\bmy name is\s+([A-Za-z][A-Za-z '-]{1,60})", text, re.IGNORECASE)
		if name_match:
			self.data["user_facts"]["name"] = name_match.group(1).strip(" .,!?")
			changed.append("name")
		project_match = re.search(r"\b(?:my )?project is called\s+([A-Za-z0-9][A-Za-z0-9 _-]{1,60})", text, re.IGNORECASE)
		if project_match:
			self.data["user_facts"]["current_project"] = project_match.group(1).strip(" .,!?")
			changed.append("current_project")
		positive = any(marker in lower for marker in ("i like", "i love", "i enjoy", "interested in", "prefer"))
		negative = any(marker in lower for marker in ("i dislike", "i hate", "don't like", "do not like", "avoid"))
		if not positive and not negative:
			if changed:
				self.save()
			return changed
		for topic, aliases in self._TOPIC_ALIASES.items():
			if not any(alias in lower for alias in aliases):
				continue
			bucket = self.data["interests"] if not negative else self.data["avoidances"]
			entry = bucket.setdefault(topic, {"confidence": 0.0, "explicit_evidence": 0, "inferred_evidence": 0})
			amount = 0.16 if explicit else 0.08
			entry["confidence"] = round(min(1.0, entry["confidence"] + amount), 2)
			entry["explicit_evidence" if explicit else "inferred_evidence"] += 1
			changed.append(topic)
		if changed:
			self.save()
		return changed

	def record_feedback(self, accepted: bool) -> None:
		key = "accepted_recommendations" if accepted else "rejected_recommendations"
		self.data["behavioral_signals"][key] += 1
		self.save()

	def top_interests(self, limit: int = 3) -> list[tuple[str, float]]:
		items = ((topic, float(entry.get("confidence", 0))) for topic, entry in self.data["interests"].items())
		return sorted(items, key=lambda item: item[1], reverse=True)[:limit]


class ShortTermMemory:
	"""Bounded short-term memory for resolving references in conversation.

	Stores the most recent exchanges (deque(maxlen=10)) each holding the user
	transcript, inferred intent, capability, arguments, result, entities and
	any draft/action context. Used to answer "what did you just do?", "send
	it", "open that", "do that again", and to recover details like an email
	subject or recipient that were given a few turns earlier.
	"""

	def __init__(self, capacity: int = 10) -> None:
		self.capacity = capacity
		self.records: "deque[dict[str, Any]]" = deque(maxlen=capacity)
		self.active_draft: dict[str, Any] | None = None

	def record(self, *, transcript: str, intent: str = "", sub_intent: str = "",
			   capability: str = "", arguments: dict[str, Any] | None = None,
			   result: str = "", status: str = "", entities: dict[str, Any] | None = None,
			   extra: dict[str, Any] | None = None) -> None:
		self.records.append({
			"transcript": transcript,
			"intent": intent,
			"sub_intent": sub_intent,
			"capability": capability,
			"arguments": dict(arguments or {}),
			"result": result,
			"status": status,
			"entities": dict(entities or {}),
			"extra": dict(extra or {}),
		})

	def last(self, *, kind: str | None = None) -> dict[str, Any] | None:
		if not self.records:
			return None
		if kind is None:
			return self.records[-1]
		for record in reversed(self.records):
			if record.get("capability", "").startswith(kind) or record.get("intent") == kind:
				return record
		return None

	def last_action_record(self) -> dict[str, Any] | None:
		"""Most recent record that actually did something (capability ran)."""
		if not self.records:
			return None
		for record in reversed(self.records):
			if record.get("capability"):
				return record
		return None

	def find(self, capability_prefix: str) -> dict[str, Any] | None:
		return self.last(kind=capability_prefix)

	def set_active_draft(self, draft: dict[str, Any] | None) -> None:
		self.active_draft = draft

	def describe_last_action(self) -> str:
		record = self.last_action_record()
		if not record:
			return "I haven't performed any action yet."
		cap = record.get("capability") or "general response"
		result = record.get("result")
		status = record.get("status")
		base = f"My last action was '{cap}' for \"{record.get('transcript', '')}\"."
		if status:
			base += f" Status: {status}."
		if result:
			base += f" {result}"
		return base

	def describe_recent(self) -> str:
		if not self.records:
			return "I have no short-term memory yet."
		summaries = []
		for record in list(self.records)[-5:]:
			summaries.append(
				f"You said \"{record.get('transcript', '')}\" "
				f"[{record.get('intent', '?')}/{record.get('sub_intent', '?')}]"
			)
		return "Recent context:\n" + "\n".join(summaries)

	def resolve_action_target(self, phrase: str) -> dict[str, Any] | None:
		"""Resolve an anaphoric target like 'that file' / 'that folder' / 'that app'."""
		if not self.records:
			return None
		lower = phrase.lower()
		want_file = any(w in lower for w in ("file", "folder", "document", "note"))
		for record in reversed(self.records):
			entities = record.get("entities") or {}
			if want_file and (record.get("capability", "").startswith("file.") or entities.get("file_reference")):
				return record
			if not want_file and record.get("capability", "").startswith(("app.", "screen.", "browser.")):
				return record
		return None


_short_term_memory = ShortTermMemory()


def get_short_term_memory() -> ShortTermMemory:
	return _short_term_memory
