"""Small local knowledge graph for explicit, user-approved memory.

Inspired by isair/jarvis' self-organising memory, but deliberately conservative:
only explicit memory/preferences and clearly stated project facts are persisted.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any


class KnowledgeGraph:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else Path(__file__).resolve().parent.parent / "database" / "memory.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS kg_nodes (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, label TEXT NOT NULL UNIQUE, value TEXT, confidence REAL DEFAULT 1.0, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            db.execute("CREATE TABLE IF NOT EXISTS kg_edges (source_id INTEGER NOT NULL, relation TEXT NOT NULL, target_id INTEGER NOT NULL, UNIQUE(source_id, relation, target_id))")
            db.commit()

    def upsert(self, kind: str, label: str, value: str = "", confidence: float = 1.0) -> int:
        label = re.sub(r"\s+", " ", label.strip())
        if not label:
            raise ValueError("empty graph label")
        with self._connect() as db:
            db.execute("INSERT INTO kg_nodes(kind,label,value,confidence) VALUES(?,?,?,?) ON CONFLICT(label) DO UPDATE SET kind=excluded.kind,value=excluded.value,confidence=max(kg_nodes.confidence,excluded.confidence),updated_at=CURRENT_TIMESTAMP", (kind, label, value, float(confidence)))
            row = db.execute("SELECT id FROM kg_nodes WHERE label=?", (label,)).fetchone()
            db.commit()
            return int(row[0])

    def link(self, source_label: str, relation: str, target_label: str, source_kind: str = "concept", target_kind: str = "concept") -> None:
        s = self.upsert(source_kind, source_label)
        t = self.upsert(target_kind, target_label)
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO kg_edges(source_id,relation,target_id) VALUES(?,?,?)", (s, relation, t))
            db.commit()

    def remember_text(self, text: str, *, explicit: bool = False) -> list[str]:
        if not explicit:
            return []
        lower = text.lower().strip()
        labels: list[str] = []
        patterns = [
            (r"\bmy project(?: is| is called)\s+(.+?)(?:[.!?]|$)", "project"),
            (r"\bremember (?:that )?(.+?)(?:[.!?]|$)", "fact"),
            (r"\bi prefer\s+(.+?)(?:[.!?]|$)", "preference"),
            (r"\bi like\s+(.+?)(?:[.!?]|$)", "interest"),
        ]
        for pattern, kind in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).strip(" \t.,!?\"")
                if value:
                    label = f"{kind}: {value[:200]}"
                    self.upsert(kind, label, value, 1.0)
                    labels.append(label)
        # Also link obvious project/technology pairs.
        if labels and any(x in lower for x in ("esp32", "arduino", "python", "ollama", "openjarvis", "robotics", "ai")):
            tech = next((x for x in ("esp32", "arduino", "python", "ollama", "openjarvis", "robotics", "ai") if x in lower), None)
            if tech:
                self.link(labels[0], "uses", tech)
        return labels

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        terms = [t for t in re.findall(r"[a-zA-Z0-9_+-]{3,}", (query or "").lower()) if t not in {"what", "about", "the", "and", "you"}]
        if not terms:
            return []
        with self._connect() as db:
            rows = db.execute("SELECT id,kind,label,value,confidence FROM kg_nodes ORDER BY confidence DESC, updated_at DESC LIMIT 500").fetchall()
        scored = []
        for row in rows:
            hay = f"{row['label']} {row['value']}".lower()
            score = sum(1 for term in terms if term in hay)
            if score:
                scored.append((score, dict(row)))
        scored.sort(key=lambda x: (-x[0], -float(x[1].get("confidence", 0))))
        return [item for _, item in scored[:limit]]

    def context_for(self, query: str, limit: int = 4) -> str:
        rows = self.search(query, limit)
        if not rows:
            return "No relevant long-term graph memory."
        return "Relevant long-term graph memory: " + "; ".join(r["value"] or r["label"] for r in rows)

    def stats(self) -> dict[str, int]:
        with self._connect() as db:
            nodes = db.execute("SELECT COUNT(*) FROM kg_nodes").fetchone()[0]
            edges = db.execute("SELECT COUNT(*) FROM kg_edges").fetchone()[0]
        return {"nodes": int(nodes), "edges": int(edges)}
