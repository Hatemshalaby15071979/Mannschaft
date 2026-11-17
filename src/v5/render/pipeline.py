"""One render pipeline, shared by the CLI and the server's job runner.

Keeping this in one place is deliberate: `make render` and `POST /api/render/{id}`
must produce byte-identical audio, and they must fail for the same reasons. A
second copy would drift the moment either grows a special case.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..config import ROOT, LevelProfile, VoiceProfile, load_levels, load_voices, missing_profiles
from ..contract.models import LessonScript
from ..contract.validate import Issue, has_errors, validate_file
from .assemble import AssemblyError, AssemblyResult, assemble
from .cache import AudioCache, CacheStats
from .segment import RenderError, SegmentRender, VoiceNotReady, VoiceStudioClient, render_lesson

LESSONS_DIR = ROOT / "content" / "lessons"
AUDIO_DIR = ROOT / "content" / "audio"

Progress = Callable[[int, int], None]


# --------------------------------------------------------------------------
# typed failures — callers map these to exit codes / HTTP statuses
# --------------------------------------------------------------------------


class PipelineError(RuntimeError):
    """Base for everything the pipeline can refuse to do."""


class LessonNotFound(PipelineError):
    def __init__(self, lesson_id: str, path: Path) -> None:
        super().__init__(f"no such lesson: {path}")
        self.lesson_id = lesson_id
        self.path = path


class ValidationFailed(PipelineError):
    def __init__(self, lesson_id: str, issues: list[Issue]) -> None:
        super().__init__(f"{lesson_id}: validation failed")
        self.lesson_id = lesson_id
        self.issues = issues


class RenderFailed(PipelineError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class VoicesNotReady(PipelineError):
    """The M4 gate: a cast voice has no profile id yet."""

    def __init__(self, missing: list[str]) -> None:
        super().__init__("no profile_id for " + ", ".join(missing) + " (M4 is manual)")
        self.missing = missing


class AssemblyFailed(PipelineError):
    pass


@dataclass(frozen=True)
class RenderOutcome:
    lesson_id: str
    script: LessonScript
    segments: int
    synthesised: int
    cached: int
    cache_stats: CacheStats
    lines_dir: Path
    assembly: AssemblyResult | None = None

    @property
    def total(self) -> int:
        return self.segments


# --------------------------------------------------------------------------
# guards
# --------------------------------------------------------------------------


def load_lesson_json(path: Path) -> LessonScript:
    """Parse + validate a lesson file, raising ValidationFailed on any error."""
    script, issues = validate_file(path)
    if script is None or has_errors(issues):
        raise ValidationFailed(path.stem.removesuffix(".lesson"), issues)
    return script


def renderable(
    lesson_id: str,
    *,
    lessons_dir: Path | None = None,
    voices: dict[str, VoiceProfile] | None = None,
) -> tuple[LessonScript, dict[str, VoiceProfile], LevelProfile]:
    """The pre-flight every render needs: valid lesson + every voice configured."""
    directory = lessons_dir or LESSONS_DIR
    path = directory / f"{lesson_id}.lesson.json"
    if not path.exists():
        raise LessonNotFound(lesson_id, path)

    script = load_lesson_json(path)

    configured = voices if voices is not None else load_voices()
    unready = missing_profiles(configured)
    if unready:
        raise VoicesNotReady(unready)

    level = load_levels().get(script.level)
    if level is None:
        raise PipelineError(f"{lesson_id}: unknown level {script.level!r}")
    return script, configured, level


# --------------------------------------------------------------------------
# the pipeline
# --------------------------------------------------------------------------


def render_lesson_to_disk(
    lesson_id: str,
    *,
    lessons_dir: Path | None = None,
    audio_dir: Path | None = None,
    cache: AudioCache | None = None,
    client: VoiceStudioClient | None = None,
    voices: dict[str, VoiceProfile] | None = None,
    assemble_audio: bool = True,
    keep_build: bool = False,
    on_progress: Progress | None = None,
) -> RenderOutcome:
    """Synthesise every segment, then assemble the lesson.

    Nothing is written for content that fails validation (invariant 7), and
    nothing is synthesised while a voice has no profile id (the M4 gate).
    """
    script, configured, level = renderable(lesson_id, lessons_dir=lessons_dir, voices=voices)

    audio_root = audio_dir or AUDIO_DIR
    lines_dir = audio_root / script.id / "lines"
    cache = cache if cache is not None else AudioCache()
    client = client if client is not None else VoiceStudioClient()

    try:
        rendered: list[SegmentRender] = render_lesson(
            script, configured, level, cache, client, lines_dir, on_segment=on_progress
        )
    except VoiceNotReady as exc:
        raise RenderFailed(str(exc)) from exc
    except RenderError as exc:
        raise RenderFailed(str(exc)) from exc

    hits = sum(1 for r in rendered if r.cached)
    outcome = RenderOutcome(
        lesson_id=script.id,
        script=script,
        segments=len(rendered),
        synthesised=len(rendered) - hits,
        cached=hits,
        cache_stats=cache.stats,
        lines_dir=lines_dir,
    )

    if not assemble_audio:
        return outcome

    line_paths = {seg.id: lines_dir / f"{seg.id}.wav" for seg in script.segments}
    missing = [seg.id for seg, path in line_paths.items() if not path.exists()]
    if missing:
        raise PipelineError(f"{script.id}: {len(missing)} segment(s) missing audio: {missing[:5]}")

    try:
        result = assemble(
            script,
            line_paths,
            audio_root / script.id,
            voices=configured,
            level=level,
            keep_build=keep_build,
        )
    except AssemblyError as exc:
        raise AssemblyFailed(f"assembly failed: {exc}") from exc

    return RenderOutcome(
        lesson_id=outcome.lesson_id,
        script=outcome.script,
        segments=outcome.segments,
        synthesised=outcome.synthesised,
        cached=outcome.cached,
        cache_stats=outcome.cache_stats,
        lines_dir=outcome.lines_dir,
        assembly=result,
    )
