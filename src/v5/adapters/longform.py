"""Lesson Script v1 -> VoiceStudio longform text.

VoiceStudio's grammar is owned by ``longform_parser.py``. We emit ONLY that
grammar, and the golden test proves it by parsing our output with the real
module. Nothing here invents a token.

Speed strategy: the lesson's level baseline goes into the parser's
``default_speed`` parameter, which is an **exact float** — so A2 renders at
0.90, not at a quantised 0.92, and most segments emit no inline tag at all.
Only segments that deviate from the baseline get a tag, and deviating speeds
are quantised to what the grammar can express (0.85 / 0.92 / 1.15).

voice_map: VoiceStudio's router does ``voice_map.get(voice_id)`` where voice_id
is the RAW name captured from ``[voice:NAME]`` — i.e. the key is ``"kunde"``,
NOT ``"[voice:kunde]"``. Its own docstring says otherwise; the code wins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import LevelProfile, VoiceProfile, resolve_voice
from ..contract.models import LessonScript, Segment

SLOW = 0.85
EMPHASIS = 0.92
FAST = 1.15
DEFAULT_SPEED = 1.0
# Below this, a segment is "the same speed as the lesson baseline" and gets no tag.
SAME_SPEED_EPS = 0.02

VOICESTUDIO_PROJECT = Path("/home/hatem/.config/VoiceStudio/runtime/project")


@dataclass(frozen=True)
class LongformDocument:
    text: str
    voice_map: dict[str, str]
    default_voice: str | None
    default_speed: float = DEFAULT_SPEED
    speeds: dict[str, float] = field(default_factory=dict)
    unrepresentable: dict[str, float] = field(default_factory=dict)


class VoiceNotReady(RuntimeError):
    """A cast voice has no profile_id yet (milestone M4 is manual)."""


def quantise_speed(speed: float | None, baseline: float = DEFAULT_SPEED) -> tuple[str | None, float]:
    """Map an authored speed onto (inline_tag, effective_speed).

    ``None`` tag means "inherit the document baseline". Speeds that are within
    SAME_SPEED_EPS of the baseline are left untagged so the output stays clean
    and the exact float survives.
    """
    if speed is None or abs(speed - baseline) < SAME_SPEED_EPS:
        return None, baseline
    if speed <= 0.875:
        return "slow", SLOW
    if speed < 0.985:
        return "emphasis", EMPHASIS
    if speed <= 1.055:
        # No tag in this grammar means "baseline"; there is no way to say
        # "exactly 1.0" inside a non-1.0 lesson. Fall back to the baseline and
        # record it so the renderer can warn.
        return None, baseline
    return "fast", FAST


def _wrap(text: str, tag: str | None) -> str:
    return f"[{tag}]{text}[/{tag}]" if tag else text


def _takes(seg: Segment) -> int:
    return max(1, seg.repeat or 1)


def _gaps(seg: Segment) -> list[int]:
    """Silence after each take; the last one is the authored pause."""
    n = _takes(seg)
    intra = max(300, seg.pause_after_ms // 2) if n > 1 else 0
    return [intra] * (n - 1) + [seg.pause_after_ms]


def _segment_line(seg: Segment, baseline: float) -> tuple[str, list[tuple[str, float]]]:
    """Emit one segment as one line; return the line and its per-take speeds."""
    authored = seg.speed if seg.speed is not None else baseline
    tag, effective = quantise_speed(authored, baseline)
    wrapped = _wrap(seg.text.strip(), tag)

    body: list[str] = []
    for gap in _gaps(seg):
        body.append(wrapped)
        if gap > 0:
            body.append(f"[pause {gap}ms]")
    return f"[voice:{seg.speaker}] " + " ".join(body), [
        (seg.text.strip(), effective) for _ in range(_takes(seg))
    ]


def build(
    script: LessonScript,
    voices: dict[str, VoiceProfile],
    level: LevelProfile,
    *,
    allow_unready: bool = False,
) -> LongformDocument:
    """Render the lesson to longform text plus the cast map.

    Raises VoiceNotReady unless every cast voice has a profile_id, because a
    lesson rendered with unmapped voices silently collapses to one voice — the
    exact bug this rewrite exists to kill.
    """
    voice_map: dict[str, str] = {}
    unresolved: list[str] = []
    for member in script.cast:
        prof = resolve_voice(voices, member.voice)
        if not prof.ready and not allow_unready:
            unresolved.append(f"{member.role}->{member.voice}")
        voice_map[member.role] = prof.profile_id or f"unready:{member.voice}"
    if unresolved:
        raise VoiceNotReady(
            "no profile_id for: "
            + ", ".join(unresolved)
            + " (create them in VoiceStudio → Design, M4)"
        )

    baseline = level.default_speed
    lines = [f"# {script.title.de}"]
    speeds: dict[str, float] = {}
    unrepresentable: dict[str, float] = {}
    for seg in script.segments:
        line, takes = _segment_line(seg, baseline)
        lines.append(line)
        speeds[seg.id] = takes[0][1]
        authored = seg.speed if seg.speed is not None else baseline
        if abs(authored - takes[0][1]) > SAME_SPEED_EPS:
            unrepresentable[seg.id] = authored

    narrator = script.roles.get("narrator") or script.cast[0]
    return LongformDocument(
        text="\n".join(lines) + "\n",
        voice_map=voice_map,
        default_voice=voice_map.get(narrator.role),
        default_speed=baseline,
        speeds=speeds,
        unrepresentable=unrepresentable,
    )


def expected_spans(script: LessonScript, level: LevelProfile) -> list[dict]:
    """The span list VoiceStudio must produce. Used by the golden test."""
    baseline = level.default_speed
    out: list[dict] = []
    for seg in script.segments:
        _line, takes = _segment_line(seg, baseline)
        for (text, speed), gap in zip(takes, _gaps(seg), strict=True):
            out.append(
                {
                    "voice_id": seg.speaker,
                    "text": text,
                    "pause_ms_after": gap,
                    "speed": speed,
                }
            )
    return out


def real_parser():
    """Import VoiceStudio's actual parser (lazy: keeps `make check` host-agnostic)."""
    import sys

    root = VOICESTUDIO_PROJECT
    if not (root / "backend" / "services" / "longform_parser.py").exists():
        raise RuntimeError(f"VoiceStudio parser not found under {root}")
    for p in (str(root), str(root / "backend")):
        if p not in sys.path:
            sys.path.insert(0, p)
    from services.longform_parser import parse_script_to_spans  # noqa: PLC0415

    return parse_script_to_spans
