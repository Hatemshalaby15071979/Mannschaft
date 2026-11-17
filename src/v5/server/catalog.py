"""Lesson catalogue: what exists on disk, and what has audio.

The catalogue is derived, never authoritative — `content/lessons/*.lesson.json`
is the source and `content/audio/<id>/manifest.json` says whether it has been
rendered. Nothing here writes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..config import ROOT
from ..contract.models import LessonScript

LESSONS_DIR = ROOT / "content" / "lessons"
AUDIO_DIR = ROOT / "content" / "audio"

LESSON_SUFFIX = ".lesson.json"


@dataclass(frozen=True)
class LessonSummary:
    """One library row. Cheap to build; never includes segments."""

    id: str
    level: str
    title_de: str
    title_en: str
    minutes: int
    segments: int
    tags: tuple[str, ...]
    grammar_focus: tuple[str, ...]
    register: str
    can_do_de: str
    can_do_en: str
    rendered: bool
    duration_ms: int | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "level": self.level,
            "title": {"de": self.title_de, "en": self.title_en},
            "minutes": self.minutes,
            "segments": self.segments,
            "tags": list(self.tags),
            "grammar_focus": list(self.grammar_focus),
            "register": self.register,
            "can_do": {"de": self.can_do_de, "en": self.can_do_en},
            "rendered": self.rendered,
            "duration_ms": self.duration_ms,
        }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class Catalogue:
    """Scans the lessons directory. Cached by mtime, refreshed on demand."""

    def __init__(self, lessons_dir: Path | None = None, audio_dir: Path | None = None) -> None:
        self.lessons_dir = Path(lessons_dir or LESSONS_DIR)
        self.audio_dir = Path(audio_dir or AUDIO_DIR)
        self._cache: dict[str, tuple[float, LessonSummary]] = {}

    # ---- summaries -------------------------------------------------------

    def _rendered_duration(self, lesson_id: str) -> tuple[bool, int | None]:
        manifest = self.audio_dir / lesson_id / "manifest.json"
        audio = self.audio_dir / lesson_id / "lesson.mp3"
        if not (manifest.exists() and audio.exists()):
            return False, None
        try:
            data = _read_json(manifest)
        except (OSError, json.JSONDecodeError):
            return False, None
        return True, int(data.get("duration_ms", 0)) or None

    def _summary(self, path: Path) -> LessonSummary | None:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        cached = self._cache.get(path.name)
        if cached is not None and cached[0] == mtime:
            return cached[1]

        try:
            raw = _read_json(path)
            script = LessonScript.model_validate(raw)
        except Exception:  # noqa: BLE001 — a broken file must not kill the library
            return None

        rendered, duration_ms = self._rendered_duration(script.id)
        summary = LessonSummary(
            id=script.id,
            level=script.level,
            title_de=script.title.de,
            title_en=script.title.en,
            minutes=script.minutes,
            segments=len(script.segments),
            tags=tuple(script.scene.situation_tags),
            grammar_focus=tuple(script.scene.grammar_focus),
            # `register` shadows ABCMeta.register on the model, so the field is
            # stored as `register_` with alias="register". See contract/models.py.
            register=script.scene.register_,
            can_do_de=script.scene.can_do_de,
            can_do_en=script.scene.can_do_en,
            rendered=rendered,
            duration_ms=duration_ms,
        )
        self._cache[path.name] = (mtime, summary)
        return summary

    def summaries(self, *, level: str | None = None, tag: str | None = None) -> list[LessonSummary]:
        out: list[LessonSummary] = []
        for path in sorted(self.lessons_dir.glob(f"*{LESSON_SUFFIX}")):
            summary = self._summary(path)
            if summary is None:
                continue
            if level and summary.level.upper() != level.upper():
                continue
            if tag and tag.lower() not in {t.lower() for t in summary.tags}:
                continue
            out.append(summary)
        out.sort(key=lambda s: (s.level, s.id))
        return out

    def get(self, lesson_id: str) -> LessonSummary | None:
        return self._summary(self.lessons_dir / f"{lesson_id}{LESSON_SUFFIX}")

    # ---- detail ----------------------------------------------------------

    def lesson_path(self, lesson_id: str) -> Path:
        return self.lessons_dir / f"{lesson_id}{LESSON_SUFFIX}"

    def detail(self, lesson_id: str) -> dict | None:
        """Full lesson JSON + measured timeline (null when not rendered)."""
        path = self.lesson_path(lesson_id)
        if not path.exists():
            return None
        try:
            script = _read_json(path)
        except (OSError, json.JSONDecodeError):
            return None
        summary = self.get(lesson_id)
        timeline = None
        timeline_path = self.audio_dir / lesson_id / "timeline.json"
        if timeline_path.exists():
            try:
                timeline = _read_json(timeline_path)
            except (OSError, json.JSONDecodeError):
                timeline = None
        return {
            "lesson": script,
            "summary": summary.as_dict() if summary else None,
            "timeline": timeline,
        }

    # ---- audio -----------------------------------------------------------

    def audio_path(self, lesson_id: str) -> Path | None:
        path = self.audio_dir / lesson_id / "lesson.mp3"
        return path if path.exists() else None

    def line_path(self, lesson_id: str, segment_id: str) -> Path | None:
        path = self.audio_dir / lesson_id / "lines" / f"{segment_id}.mp3"
        return path if path.exists() else None

    def refresh(self) -> None:
        self._cache.clear()
