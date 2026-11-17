"""The shared pipeline: the guards the CLI and the server both depend on.

If these guards drift, `make render` and `POST /api/render/{id}` stop agreeing
about what is allowed to reach the GPU — so they get their own tests.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from v5.config import load_voices
from v5.render import (
    LessonNotFound,
    ValidationFailed,
    VoicesNotReady,
    renderable,
)
from v5.server.app import make_render_fn
from v5.server.catalog import Catalogue


def _write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _minimal(lesson_id: str = "A1-97") -> dict:
    return {
        "id": lesson_id,
        "level": "A1",
        "title": {"de": "Test", "en": "Test"},
        "minutes": 1,
        "scene": {
            "setting_de": "Test.",
            "setting_en": "Test.",
            "register": "neutral",
            "can_do_de": "Test.",
            "can_do_en": "Test.",
            "situation_tags": ["test"],
            "grammar_focus": ["test"],
        },
        "cast": [{"role": "narrator", "voice": "de_narrator_f"}],
        "segments": [
            {
                "id": "s1",
                "type": "line",
                "speaker": "narrator",
                "text": "Hallo.",
                "translation": "Hello.",
                "pause_after_ms": 300,
            }
        ],
        "glossary": [],
    }


@pytest.fixture
def lessons(tmp_path) -> Path:
    directory = tmp_path / "lessons"
    directory.mkdir()
    _write(directory / "A1-97.lesson.json", _minimal())
    return directory


@pytest.fixture
def ready_voices():
    return {
        key: dataclasses.replace(prof, profile_id=f"pid-{key}")
        for key, prof in load_voices().items()
    }


def test_unknown_lesson_names_the_path_it_looked_at(lessons):
    with pytest.raises(LessonNotFound) as info:
        renderable("ZZ-99", lessons_dir=lessons)
    assert "ZZ-99.lesson.json" in str(info.value)


def test_unready_voices_raise_with_the_missing_keys(lessons):
    with pytest.raises(VoicesNotReady) as info:
        renderable("A1-97", lessons_dir=lessons, voices=load_voices())
    assert info.value.missing == sorted(load_voices())
    assert "M4" in str(info.value)


def test_invalid_lesson_reports_pointed_issues(lessons):
    bad = _minimal()
    bad["segments"][0]["pause_after_ms"] = 9000  # contract max is 5000
    _write(lessons / "A1-97.lesson.json", bad)
    with pytest.raises(ValidationFailed) as info:
        renderable("A1-97", lessons_dir=lessons, voices=load_voices())
    assert info.value.issues


def test_valid_lesson_with_ready_voices_passes(lessons, ready_voices):
    script, voices, level = renderable("A1-97", lessons_dir=lessons, voices=ready_voices)
    assert script.id == "A1-97"
    assert level.level == "A1"
    assert voices["de_narrator_f"].profile_id == "pid-de_narrator_f"


def test_default_render_fn_is_bound_to_the_apps_own_dirs(tmp_path, lessons):
    """Regression: an app created with test dirs must not render real content."""
    catalogue = Catalogue(lessons_dir=lessons, audio_dir=tmp_path / "audio")
    render = make_render_fn(catalogue)
    with pytest.raises(LessonNotFound) as info:
        render("ZZ-99", lambda done, total: None)
    assert str(lessons) in str(info.value)
