"""SQLite storage for the corpus (plan §8.1, §8.2).

Two tables: `videos` (stage A manifest, deduplicated across playlists) and
`words` (stage B, word-timed caption stream). Both are resumable: re-running a
stage is safe because rows are replaced by primary key, never appended blindly.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[3] / "content" / "corpus" / "corpus.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id             TEXT PRIMARY KEY,
    title          TEXT,
    channel        TEXT,
    duration_s     INTEGER,
    upload_date    TEXT,
    level_tag      TEXT,
    playlists      TEXT,          -- JSON array of playlist ids
    has_de_caption INTEGER,
    has_en_caption INTEGER,
    caption_kind   TEXT,          -- 'auto' | 'manual' | NULL
    fetched_at     REAL
);
CREATE TABLE IF NOT EXISTS words (
    video_id  TEXT NOT NULL,
    idx       INTEGER NOT NULL,
    start_ms  INTEGER NOT NULL,
    end_ms    INTEGER NOT NULL,
    token     TEXT NOT NULL,
    line_idx  INTEGER NOT NULL,
    PRIMARY KEY (video_id, idx)
);
CREATE INDEX IF NOT EXISTS words_by_video ON words(video_id, idx);
"""


def connect(path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_video(conn: sqlite3.Connection, video: dict) -> None:
    """Insert or merge a stage-A video row.

    Merging matters: the same video appears in several playlists (≈60% overlap),
    so we union the playlist ids rather than overwriting them.
    """
    row = conn.execute("SELECT playlists FROM videos WHERE id=?", (video["id"],)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO videos (id, title, channel, duration_s, upload_date, level_tag, "
            "playlists, has_de_caption, has_en_caption, caption_kind, fetched_at) "
            "VALUES (:id, :title, :channel, :duration_s, :upload_date, :level_tag, "
            ":playlists, :has_de_caption, :has_en_caption, :caption_kind, :fetched_at)",
            video,
        )
        return
    old = set(__import__("json").loads(row["playlists"] or "[]"))
    merged = sorted(old | set(__import__("json").loads(video["playlists"] or "[]")))
    conn.execute(
        "UPDATE videos SET playlists=?, has_de_caption=MAX(has_de_caption, ?), "
        "has_en_caption=MAX(has_en_caption, ?), fetched_at=? WHERE id=?",
        (
            __import__("json").dumps(merged),
            video["has_de_caption"],
            video["has_en_caption"],
            video["fetched_at"],
            video["id"],
        ),
    )


def replace_words(conn: sqlite3.Connection, video_id: str, words: list[dict]) -> None:
    """Replace the full word stream for one video (idempotent re-fetch)."""
    conn.execute("DELETE FROM words WHERE video_id=?", (video_id,))
    conn.executemany(
        "INSERT INTO words (video_id, idx, start_ms, end_ms, token, line_idx) "
        "VALUES (:video_id, :idx, :start_ms, :end_ms, :token, :line_idx)",
        words,
    )


def caption_video_ids(conn: sqlite3.Connection) -> list[str]:
    return [
        r["id"]
        for r in conn.execute("SELECT id FROM videos WHERE has_de_caption=1 ORDER BY id")
    ]


def video_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM videos").fetchone()["n"]


def word_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM words").fetchone()["n"]
