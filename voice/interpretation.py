"""Transcript quality assessment and interpretation for speech input."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Sequence


class TranscriptQuality(str, Enum):
	HIGH = "high"
	MEDIUM = "medium"
	LOW = "low"
	VERY_LOW = "very_low"


@dataclass
class InterpretationResult:
	meaning: str
	confidence: float
	needs_clarification: bool
	quality: TranscriptQuality | None = None


@dataclass
class TranscriptAssessment:
	label: TranscriptQuality
	confidence: float
	reason: str = ""


class TranscriptInterpreter:
	"""Interpret imperfect STT output using confidence + context."""

	_COMMON_SUBSTITUTIONS = {
		"your": "your",
		"you're": "you're",
		"there": "there",
		"their": "their",
		"they're": "they're",
		"to": "to",
		"too": "too",
		"two": "two",
		"hear": "hear",
		"here": "here",
		"ai": "AI",
		"a.i.": "AI",
		"jarvis": "Jarvis",
		"j arvis": "Jarvis",
		"x": "X",
		"see": "see",
		"why": "why",
		"y": "Y",
		"o": "oh",
		"i": "I",
		"eye": "I",
		"are": "are",
		"r": "R",
	}

	_SUSPICIOUS_PATTERNS = (
		"missing my eggs",
		"tell you that i am",
		"wi-fi tell",
		"im missing",
	)

	def assess_quality(self, transcript: str) -> TranscriptAssessment:
		text = self._normalize(transcript)
		if not text:
			return TranscriptAssessment(TranscriptQuality.VERY_LOW, 0.0, "empty transcript")
		if self._looks_like_noise(text):
			return TranscriptAssessment(TranscriptQuality.LOW, 0.32, "unlikely phrase")
		if self._looks_like_common_mistake(text):
			return TranscriptAssessment(TranscriptQuality.MEDIUM, 0.7, "possible transcription error")
		if len(text.split()) <= 2:
			return TranscriptAssessment(TranscriptQuality.MEDIUM, 0.64, "short utterance")
		return TranscriptAssessment(TranscriptQuality.HIGH, 0.9, "clear transcript")

	def interpret(self, transcript: str, context: Sequence[str] | None = None) -> InterpretationResult:
		clean = self._strip_filler(transcript)
		if not clean:
			return InterpretationResult("Sorry, I didn't catch that. Could you repeat it?", 0.12, True, TranscriptQuality.VERY_LOW)

		assessment = self.assess_quality(clean)
		context_text = " ".join(context or [])
		if assessment.label == TranscriptQuality.HIGH:
			return InterpretationResult(clean, 0.9, False, assessment.label)

		corrected = self._apply_targeted_corrections(clean)
		if assessment.label == TranscriptQuality.MEDIUM:
			if corrected and corrected != clean:
				return InterpretationResult(corrected, 0.75, False, assessment.label)
			return InterpretationResult(clean, max(0.55, assessment.confidence), False, assessment.label)

		if assessment.label in {TranscriptQuality.LOW, TranscriptQuality.VERY_LOW}:
			clarification = self._clarification_message(clean, context_text)
			return InterpretationResult(clarification, max(0.25, assessment.confidence), True, assessment.label)

		return InterpretationResult(clean, max(0.55, assessment.confidence), False, assessment.label)

	# Filler words and wake-word prefixes STT often inserts or the speaker
	# habitually says; they distort intent matching ("jarvis what time..."
	# parsed as a statement about Jarvis, "um" as the whole utterance).
	_FILLER_PATTERN = re.compile(
		r"\b(um+|uh+|erm+|hmm+|ah+|eh+|huh)\b[,\s]*|"
		r"\b(like i mean|i mean like|you know|i guess|basically|actually|literally|honestly|seriously)\b[,\s]*",
		re.IGNORECASE,
	)
	# Leading discourse markers that precede a real command ("so can you...",
	# "well what time...", "like tell me...", "just play some music", "i said click...").
	_LEAD_FILLER_PATTERN = re.compile(
		r"^\s*\b(like|just|so|well|yeah|right|okay|ok|hey|listen|i said|i told you to|please|i meant|go ahead and|proceed to|now)\b[,\s:\-]+",
		re.IGNORECASE,
	)
	_WAKE_PREFIX_PATTERN = re.compile(
		r"^\s*(?:hey\s+|ok\s+|okay\s+|yo\s+|hello\s+|hi\s+)?"
		r"(?:jarvis|javis|jarvik|service|jervis|roses?|travis|harvest|drivers?|surface|chavez|charvis|starbucks|office|artists?|ravish|rabish|davis|clovis|jayveer|trevor|tarvis)[,\s:\-]+",
		re.IGNORECASE,
	)

	def _strip_filler(self, text: str) -> str:
		cleaned = self._WAKE_PREFIX_PATTERN.sub("", text)
		cleaned = self._LEAD_FILLER_PATTERN.sub("", cleaned)
		cleaned = self._FILLER_PATTERN.sub(" ", cleaned)
		cleaned = self._WAKE_PREFIX_PATTERN.sub("", cleaned)
		cleaned = self._LEAD_FILLER_PATTERN.sub("", cleaned)
		return re.sub(r"\s+", " ", cleaned).strip(" ,.")

	def normalize_speech_input(self, text: str) -> str:
		"""Clean spoken utterances: remove acoustic wake-word prefixes and filler markers."""
		if not text:
			return ""
		return self._strip_filler(text)

	def _normalize(self, text: str) -> str:
		return re.sub(r"\s+", " ", text.strip()).lower()

	def _looks_like_noise(self, text: str) -> bool:
		lower = text.lower()
		if any(pattern in lower for pattern in self._SUSPICIOUS_PATTERNS):
			return True
		if lower.count("egg") or lower.count("eggs"):
			return "wi-fi" in lower or "missing" in lower or "tell" in lower
		return False

	def _looks_like_common_mistake(self, text: str) -> bool:
		lower = text.lower()
		if "what is you" in lower:
			return True
		if "can you here" in lower:
			return True
		if "jarvis" in lower and "j a r v i s" in lower:
			return True
		if any(phrase in lower for phrase in ("your processing", "can you here me", "what is your", "there they", "they are", "to too", "too two")):
			return True
		return False

	def _apply_targeted_corrections(self, text: str) -> str:
		cleaned = text.strip()
		cleaned = re.sub(r"\bwhat is you\b", "what is your", cleaned, flags=re.IGNORECASE)
		cleaned = re.sub(r"\bcan you here\b", "can you hear", cleaned, flags=re.IGNORECASE)
		cleaned = re.sub(r"\bcan you hear me\b", "can you hear me", cleaned, flags=re.IGNORECASE)
		for mistake, correct in self._COMMON_SUBSTITUTIONS.items():
			pattern = rf"\b{re.escape(mistake)}\b"
			cleaned = re.sub(pattern, correct, cleaned, flags=re.IGNORECASE)
		cleaned = re.sub(r"\s+", " ", cleaned).strip()
		if cleaned.lower() == text.lower():
			return ""
		if cleaned.lower().startswith("what is your processing time"):
			return "what is your processing time?"
		if cleaned.lower().startswith("can you hear me"):
			return "Can you hear me?"
		return cleaned

	def _clarification_message(self, transcript: str, context_text: str) -> str:
		text = transcript.strip()
		context_hint = self._extract_context_hint(context_text)
		if context_hint:
			return f"Sorry, I didn't quite catch that. Did you say something about {context_hint}?"
		if "wi-fi" in text.lower() or "missing" in text.lower():
			return "Sorry, I didn't quite catch that. Did you say something about Wi-Fi or recognition?"
		return "Sorry, I didn't quite catch that. Could you say that a little more clearly?"

	def _extract_context_hint(self, context_text: str) -> str:
		text = context_text.lower()
		if "recognize" in text and "letter" in text:
			return "recognizing letters"
		if "python" in text:
			return "Python"
		if "java" in text:
			return "Java"
		if "weather" in text:
			return "the weather"
		if "process" in text and "time" in text:
			return "processing time"
		return ""
