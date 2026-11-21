"""V6 learning events: ``card_graded`` and ``clip_opened``.

Progress answers "where was I". Events answer "what did I do". They are kept in
their own SQLite file so the frozen v5 progress store (``server/progress.py``)
is not touched: V6 is additive, and the existing progress payload keeps its
exact shape.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ..config import ROOT

DEFAULT_DB = ROOT / "user" / "events.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id  TEXT NOT NULL,
    kind       TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_lesson ON events (lesson_id, id DESC);
"""


class EventStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or DEFAULT_DB)
        if self.path.parent != Path("."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def add(self, lesson_id: str, kind: str, detail: dict | None = None) -> dict:
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        payload = json.dumps(detail or {}, ensure_ascii=False)
        cur = self._conn.execute(
            "INSERT INTO events (lesson_id, kind, detail, created_at) VALUES (?, ?, ?, ?)",
            (lesson_id, kind, payload, stamp),
        )
        self._conn.commit()
        row = self._conn.execute("SELECT * FROM events WHERE id = ?", (cur.lastrowid,)).fetchone()
        return self._row(row)

    def recent(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (max(1, int(limit)),)
        ).fetchall()
        return [self._row(row) for row in rows]

    def counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT kind, COUNT(*) AS n FROM events GROUP BY kind ORDER BY kind"
        ).fetchall()
        return {row["kind"]: row["n"] for row in rows}

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        data = dict(row)
        try:
            data["detail"] = json.loads(data.get("detail") or "{}")
        except ValueError:
            data["detail"] = {}
        return data
