"""SQLite progress store.

`user/progress.sqlite` is the only state that cannot be regenerated, so it is
kept out of git and never rebuilt from the catalogue. Resume targets the
**segment**, not the lesson — that is an ADHD requirement, not a nicety.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..config import ROOT

DEFAULT_DB = ROOT / "user" / "progress.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS progress (
    lesson_id   TEXT PRIMARY KEY,
    seg_id      TEXT NOT NULL,
    position_ms INTEGER NOT NULL DEFAULT 0,
    completed   INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS session (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    minutes    REAL NOT NULL DEFAULT 0,
    lessons    TEXT NOT NULL DEFAULT '[]'
);
"""


class ProgressStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or DEFAULT_DB)
        if self.path.parent != Path("."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return self._conn

    # ---- progress --------------------------------------------------------

    def upsert(
        self,
        lesson_id: str,
        seg_id: str,
        position_ms: int,
        *,
        completed: bool = False,
        updated_at: str | None = None,
    ) -> dict:
        stamp = updated_at or _now()
        self._conn.execute(
            """
            INSERT INTO progress (lesson_id, seg_id, position_ms, completed, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(lesson_id) DO UPDATE SET
                seg_id      = excluded.seg_id,
                position_ms = excluded.position_ms,
                completed   = MAX(progress.completed, excluded.completed),
                updated_at  = excluded.updated_at
            """,
            (lesson_id, seg_id, max(0, int(position_ms)), int(completed), stamp),
        )
        self._conn.commit()
        return self.for_lesson(lesson_id) or {}

    def for_lesson(self, lesson_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM progress WHERE lesson_id = ?", (lesson_id,)
        ).fetchone()
        return dict(row) if row else None

    def resume(self) -> dict | None:
        """Most recently touched lesson that is not finished."""
        row = self._conn.execute(
            """
            SELECT * FROM progress
            WHERE completed = 0
            ORDER BY updated_at DESC
            LIMIT 1
            """
        ).fetchone()
        return dict(row) if row else None

    def all(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM progress ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def clear(self, lesson_id: str | None = None) -> int:
        if lesson_id is None:
            cur = self._conn.execute("DELETE FROM progress")
        else:
            cur = self._conn.execute("DELETE FROM progress WHERE lesson_id = ?", (lesson_id,))
        self._conn.commit()
        return cur.rowcount


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")
