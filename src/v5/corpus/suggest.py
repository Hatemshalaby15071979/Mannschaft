"""Shared candidate lookup for `corpus suggest` and `GET /api/corpus/suggest`.

One filter implementation, two callers — the CLI and the server must never
drift on level/situation semantics (a recurring bug class in this project).

Mined clips carry ``level_est`` (not ``level``); both names are accepted here
so a hand-edited clips.jsonl still works. The file is written in descending
score order by :func:`v5.corpus.mine.mine`, so the first ``limit`` matches are
the best ones.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_CLIPS = Path(__file__).resolve().parents[3] / "content" / "corpus" / "clips.jsonl"


def load_clips(path: Path | str = DEFAULT_CLIPS) -> list[dict]:
    """Read clips.jsonl, skipping blank or malformed lines."""
    p = Path(path)
    if not p.exists():
        return []
    clips: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            clips.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return clips


def suggest(
    path: Path | str = DEFAULT_CLIPS,
    *,
    level: str | None = None,
    situation: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Return up to ``limit`` clips matching level and/or situation.

    Level compares case-insensitively against ``level_est`` (falling back to
    ``level``). Situation is a substring match on the clip's situation label.
    """
    out: list[dict] = []
    for clip in load_clips(path):
        if level:
            got = str(clip.get("level_est") or clip.get("level") or "").upper()
            if got != level.upper():
                continue
        if situation and situation.lower() not in str(clip.get("situation") or "").lower():
            continue
        out.append(clip)
        if len(out) >= limit:
            break
    return out
