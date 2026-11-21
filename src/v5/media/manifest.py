"""Contract + file I/O for ``content/lesson_media.json``.

The generated file is checked in and never hand-edited. A human correction goes
into ``content/lesson_media.overrides.json`` (same shape, partial), which the
generator merges last — that is the supported way to fix a bad match without
losing the audit trail.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MANIFEST_NAME = "lesson_media.json"
OVERRIDES_NAME = "lesson_media.overrides.json"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MediaPick(_Strict):
    video_id: str
    start_s: float
    end_s: float
    clip_id: str
    reason: str = ""


class Relevance(_Strict):
    level_gap: int = 0
    situation_match: bool = False
    grammar_overlap: int = 0


class LessonMedia(_Strict):
    primary: MediaPick | None = None
    alternates: list[MediaPick] = Field(default_factory=list)
    fallback: Literal["rendered_audio"] = "rendered_audio"
    relevance: Relevance = Field(default_factory=Relevance)


class MediaManifest(_Strict):
    version: int = 1
    generated: str
    lessons: dict[str, LessonMedia] = Field(default_factory=dict)

    def embed_url(self, lesson_id: str) -> str | None:
        """Privacy-enhanced embed URL, or None when the lesson falls back."""
        lesson = self.lessons.get(lesson_id)
        if lesson is None or lesson.primary is None:
            return None
        pick = lesson.primary
        start = int(pick.start_s)
        end = int(pick.end_s)
        return (
            f"https://www.youtube-nocookie.com/embed/{pick.video_id}"
            f"?start={start}&end={end}&rel=0"
        )


def load_manifest(path: Path) -> MediaManifest | None:
    if not path.exists():
        return None
    return MediaManifest.model_validate_json(path.read_text(encoding="utf-8"))


_cache: dict[str, tuple[float, MediaManifest]] = {}


def load_manifest_cached(path: Path) -> MediaManifest | None:
    """Re-read only when the file's mtime changes (the server calls this per request)."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    cached = _cache.get(str(path))
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        manifest = load_manifest(path)
    except (OSError, ValueError):
        return None
    if manifest is not None:
        _cache[str(path)] = (mtime, manifest)
    return manifest


def load_overrides(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(path: Path, manifest: MediaManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        manifest.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=False
    )
    path.write_text(text + "\n", encoding="utf-8")


def merge_overrides(manifest: MediaManifest, overrides: dict) -> MediaManifest:
    """Apply partial per-lesson overrides. Unknown lessons are rejected."""
    if not overrides:
        return manifest
    raw = json.loads(manifest.model_dump_json())
    known = raw["lessons"]
    for lesson_id, patch in overrides.get("lessons", {}).items():
        if lesson_id not in known:
            raise ValueError(f"override for unknown lesson {lesson_id!r}")
        known[lesson_id].update(patch)
    return MediaManifest.model_validate(raw)
