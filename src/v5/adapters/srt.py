"""SubRip output from a render timeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    text: str
    translation: str | None = None


def _ts(ms: int) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: list[Cue], *, bilingual: bool = True) -> str:
    """One cue per entry; translation on a second line when enabled."""
    blocks: list[str] = []
    for i, cue in enumerate(cues, start=1):
        body = cue.text
        if bilingual and cue.translation:
            body = f"{cue.text}\n{cue.translation}"
        blocks.append(f"{i}\n{_ts(cue.start_ms)} --> {_ts(cue.end_ms)}\n{body}\n")
    return "\n".join(blocks)
