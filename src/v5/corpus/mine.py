"""Stage C — clip mining (plan §8.3).

Segment each video's word stream into candidate exchanges and score them.
A boundary is placed at a gap > 700 ms that follows a sentence-final token.
Candidates are 8–40 words and 30–90 s. Output is `clips.jsonl`.

Mining is pure over the word rows in SQLite (no network), so it is fully
testable. `review` is always "pending" — the human promotion gate (stage D)
is deliberately not automated.

The plan's "8–40 words and 30–90 s" bounds are contradictory at natural
speech rate (~2.4 words/s → 30 s ≈ 72 words), so we keep the 30–90 s time
bound and widen the word bound (config/corpus.toml). Boundaries are placed at
sentence-final tokens after `window_seconds`, because auto-captions have
sentence ends every ~5 s but negligible inter-sentence gaps.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import db, score

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CLIPS = ROOT / "content" / "corpus" / "clips.jsonl"

_SENT_END = ".!?"


def segment_words(
    words: list[sqlite3.Row],
    gap_ms: int,
    window_seconds: float = float("inf"),
) -> list[list[sqlite3.Row]]:
    """Split a video's ordered word rows into candidate exchanges.

    A boundary is placed after a sentence-final token (``.?!``) when either a
    long pause follows (``gap_ms``) *or* the current window has run for at
    least ``window_seconds``. Real auto-captions have sentence-final tokens
    every ~5 s but negligible inter-sentence gaps, so without the window rule
    a whole speaker turn (60–250 s) becomes one un-emittable group. Defaulting
    the window to infinity keeps the pure gap-based behaviour for callers that
    do not opt in (and for the unit tests).
    """
    groups: list[list[sqlite3.Row]] = []
    current: list[sqlite3.Row] = []
    for w in words:
        if current:
            prev = current[-1]
            prev_token = prev["token"].rstrip()
            gap = w["start_ms"] - prev["end_ms"]
            sentence_end = bool(prev_token) and prev_token[-1] in _SENT_END
            elapsed_s = (prev["end_ms"] - current[0]["start_ms"]) / 1000.0
            if sentence_end and (gap > gap_ms or elapsed_s >= window_seconds):
                groups.append(current)
                current = []
        current.append(w)
    if current:
        groups.append(current)
    return groups


def clip_from_group(
    group: list[sqlite3.Row],
    video_id: str,
    *,
    level: str,
    min_words: int,
    max_words: int,
    min_seconds: float,
    max_seconds: float,
    bands: dict[str, str] | None = None,
) -> dict | None:
    """Build one scored clip from a word group, or None if out of bounds."""
    n = len(group)
    if not (min_words <= n <= max_words):
        return None
    start_ms = group[0]["start_ms"]
    end_ms = group[-1]["end_ms"]
    seconds = (end_ms - start_ms) / 1000.0
    if not (min_seconds <= seconds <= max_seconds):
        return None
    text = " ".join(w["token"] for w in group)
    # level_fit is computed for the assigned level; a clip is only emitted when
    # its lexical coverage clears a floor, so we never ship gibberish as A1.
    fit = score.level_fit(text, level, bands=bands)
    if fit < 0.25:
        return None
    situation, _conf = score.detect_situation(text)
    s = score.teachability(
        text,
        level=level,
        word_count=n,
        seconds=seconds,
        bands=bands,
    )
    return {
        "clip_id": f"eg:{video_id}:{start_ms / 1000:.1f}-{end_ms / 1000:.1f}",
        "video_id": video_id,
        "start_s": round(start_ms / 1000, 1),
        "end_s": round(end_ms / 1000, 1),
        "level_est": level,
        "score": s,
        "situation": situation,
        "text_de": text,
        "word_count": n,
        "grammar_exhibits": [],  # populated by the human review stage (plan §8.4)
        "review": "pending",
    }


def mine(
    conn: sqlite3.Connection,
    *,
    out_path: Path = DEFAULT_CLIPS,
    bands: dict[str, str] | None = None,
) -> dict:
    """Run stage C; write `clips.jsonl`; return counts."""
    cfg = score.config()["mining"]
    bands = bands if bands is not None else score.word_bands()
    clips: list[dict] = []
    for row in conn.execute(
        "SELECT id, level_tag FROM videos WHERE has_de_caption=1 ORDER BY id"
    ):
        vid = row["id"]
        level = row["level_tag"] or "B1"  # untagged playlists default to B1
        words = conn.execute(
            "SELECT * FROM words WHERE video_id=? ORDER BY idx", (vid,)
        ).fetchall()
        if len(words) < cfg["min_words"]:
            continue
        for group in segment_words(
            words, cfg["boundary_gap_ms"], window_seconds=cfg["window_seconds"]
        ):
            clip = clip_from_group(
                group,
                vid,
                level=level,
                min_words=cfg["min_words"],
                max_words=cfg["max_words"],
                min_seconds=cfg["min_seconds"],
                max_seconds=cfg["max_seconds"],
                bands=bands,
            )
            if clip is not None:
                clips.append(clip)
    clips.sort(key=lambda c: (-c["score"], c["clip_id"]))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for clip in clips:
            fh.write(json.dumps(clip, ensure_ascii=False) + "\n")
    return {"clips": len(clips), "path": str(out_path)}


if __name__ == "__main__":  # pragma: no cover
    conn = db.connect()
    print(json.dumps(mine(conn), ensure_ascii=False, indent=2))
