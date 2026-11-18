from __future__ import annotations

import copy
import json

import pytest
from pydantic import ValidationError

from v5.config import ROOT
from v5.contract import LessonScript, validate_script
from v5.contract.validate import validate_file

LESSON = ROOT / "content" / "lessons" / "A2-01.lesson.json"


@pytest.fixture
def good() -> dict:
    return json.loads(LESSON.read_text(encoding="utf-8"))


def _errors(raw: dict) -> list[str]:
    script = LessonScript.model_validate(raw)
    return [i.message for i in validate_script(script) if i.severity == "error"]


def test_example_lesson_is_valid():
    script, issues = validate_file(LESSON)
    assert script is not None
    errors = [i for i in issues if i.severity == "error"]
    assert errors == [], "\n".join(str(e) for e in errors)


def test_example_lesson_meets_content_floor():
    script, _ = validate_file(LESSON)
    assert script is not None
    assert len(script.glossary) >= 15
    assert sum(1 for s in script.segments if s.type == "check") >= 3
    assert script.scene.situation_tags
    assert script.scene.grammar_focus


LESSONS = sorted((ROOT / "content" / "lessons").glob("*.lesson.json"))


@pytest.mark.parametrize("path", LESSONS, ids=lambda p: p.stem.removesuffix(".lesson"))
def test_every_shipped_lesson_validates_clean(path):
    """Every lesson in content/lessons must parse and have zero errors.

    Parametrized per file so a failure names the lesson. This is the guard the
    M9 pilot needs: a broken lesson cannot sit in the content dir unnoticed.
    """
    script, issues = validate_file(path)
    assert script is not None, "\n".join(str(i) for i in issues)
    errors = [i for i in issues if i.severity == "error"]
    assert errors == [], "\n".join(str(e) for e in errors)


def test_line_requires_translation(good):
    seg = next(s for s in good["segments"] if s["type"] == "line")
    del seg["translation"]
    with pytest.raises(ValidationError, match="requires 'translation'"):
        LessonScript.model_validate(good)


def test_pause_out_of_range_rejected(good):
    good["segments"][0]["pause_after_ms"] = 7400
    with pytest.raises(ValidationError, match="outside 0..5000"):
        LessonScript.model_validate(good)


def test_markup_token_in_spoken_text_rejected(good):
    good["segments"][0]["text"] = "[DE] Samstagmorgen."
    with pytest.raises(ValidationError, match="markup token"):
        LessonScript.model_validate(good)


def test_unknown_field_rejected(good):
    good["segments"][0]["voice"] = "de_young_f"  # old plan used `voice`; contract uses `speaker`
    with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        LessonScript.model_validate(good)


def test_duplicate_segment_id_is_an_error(good):
    good["segments"][1]["id"] = good["segments"][0]["id"]
    assert any("duplicate segment id" in m for m in _errors(good))


def test_unknown_speaker_is_an_error(good):
    good["segments"][0]["speaker"] = "stranger"
    assert any("not in cast" in m for m in _errors(good))


def test_missing_gloss_ref_is_an_error(good):
    good["segments"][1]["gloss"] = ["g_missing"]
    assert any("not in glossary" in m for m in _errors(good))


def test_level_word_cap_enforced(good):
    seg = next(s for s in good["segments"] if s["type"] == "line")
    seg["text"] = " ".join(f"wort{i}" for i in range(19))
    seg["translation"] = "nineteen words"
    assert any("exceeds A2 cap" in m for m in _errors(good))


def test_unknown_voice_key_is_an_error(good):
    good["cast"][0]["voice"] = "de_nonexistent"
    assert any("unknown voice" in m for m in _errors(good))


def test_check_without_answers_rejected(good):
    seg = next(s for s in good["segments"] if s["type"] == "check")
    seg["answers"] = []
    with pytest.raises(ValidationError, match="requires at least one answer"):
        LessonScript.model_validate(good)


def test_cli_fails_on_bad_lesson(tmp_path, good, capsys):
    from v5.contract.cli import main

    del good["segments"][0]["pause_after_ms"]
    good["segments"][0]["pause_after_ms"] = 9000
    path = tmp_path / "BAD-01.lesson.json"
    path.write_text(json.dumps(good), encoding="utf-8")
    assert main(["validate", str(path)]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out


def test_cli_passes_on_good_lesson(capsys):
    from v5.contract.cli import main

    assert main(["validate", str(LESSON)]) == 0
    assert "ok" in capsys.readouterr().out


def test_script_hash_is_optional_until_render(good):
    raw = copy.deepcopy(good)
    assert "script_hash" not in raw["meta"]
    LessonScript.model_validate(raw)
