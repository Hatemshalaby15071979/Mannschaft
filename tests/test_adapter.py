from __future__ import annotations

import dataclasses
import json

import pytest

from tests.helpers import unready_voices
from v5.adapters import Cue, VoiceNotReady, build, expected_spans, quantise_speed, to_srt
from v5.adapters.longform import real_parser
from v5.config import ROOT, load_levels, load_voices
from v5.contract import LessonScript

LESSON = ROOT / "content" / "lessons" / "A2-01.lesson.json"


@pytest.fixture(scope="module")
def script() -> LessonScript:
    return LessonScript.model_validate(json.loads(LESSON.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def ready_voices():
    """Fake profile ids so the adapter can run before M4 exists."""
    return {
        key: dataclasses.replace(prof, profile_id=f"pid-{key}")
        for key, prof in load_voices().items()
    }


def test_quantise_speed_is_the_only_four_values():
    assert quantise_speed(None) == (None, 1.0)
    assert quantise_speed(0.85) == ("slow", 0.85)
    assert quantise_speed(0.90) == ("emphasis", 0.92)
    assert quantise_speed(0.95) == ("emphasis", 0.92)
    assert quantise_speed(1.00) == (None, 1.0)
    assert quantise_speed(1.15) == ("fast", 1.15)


def test_baseline_speed_is_exact_and_untagged():
    # A2 baseline 0.90 must survive as 0.90, not quantise to 0.92
    assert quantise_speed(0.90, baseline=0.90) == (None, 0.90)
    assert quantise_speed(None, baseline=0.90) == (None, 0.90)
    # a slow echo inside an A2 lesson still gets a tag
    assert quantise_speed(0.85, baseline=0.90) == ("slow", 0.85)
    # 1.0 inside a 0.90 lesson is unrepresentable -> fall back to baseline
    assert quantise_speed(1.0, baseline=0.90) == (None, 0.90)


def test_golden_spans_match_real_parser(script, ready_voices):
    """The load-bearing test: our output, parsed by VoiceStudio itself."""
    level = load_levels()[script.level]
    doc = build(script, ready_voices, level)

    parse_script_to_spans = real_parser()
    chapters = parse_script_to_spans(
        doc.text, default_voice=doc.default_voice, default_speed=doc.default_speed
    )
    actual = [span for chapter in chapters for span in chapter["spans"]]
    expected = expected_spans(script, level)

    assert len(actual) == len(expected), (
        f"parser produced {len(actual)} spans, contract implies {len(expected)}"
    )
    for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
        assert a == e, f"span {i} mismatch:\n  actual   {a}\n  expected {e}"


def test_golden_span_count_accounts_for_repeats(script, ready_voices):
    level = load_levels()[script.level]
    repeats = sum(max(1, s.repeat or 1) for s in script.segments)
    assert repeats == len(expected_spans(script, level))
    assert repeats > len(script.segments), "fixture should contain echo/drill repeats"


def test_no_markup_leaks_into_spoken_text(script, ready_voices):
    level = load_levels()[script.level]
    doc = build(script, ready_voices, level)
    for forbidden in ("[DE]", "[EN]", "===="):
        assert forbidden not in doc.text


def test_emitted_text_contains_only_legal_tokens(script, ready_voices):
    import re

    level = load_levels()[script.level]
    doc = build(script, ready_voices, level)
    legal = re.compile(r"\[(voice:[^\]]+|pause \d+ms|/?(slow|fast|emphasis|spell))\]")
    stripped = legal.sub("", doc.text)
    assert "[" not in stripped and "]" not in stripped, f"illegal bracket token: {stripped[:200]}"


def test_voice_map_keys_are_bare_role_names(script, ready_voices):
    level = load_levels()[script.level]
    doc = build(script, ready_voices, level)
    assert set(doc.voice_map) == {c.role for c in script.cast}
    assert all(not k.startswith("[voice:") for k in doc.voice_map)
    assert doc.voice_map["kunde"] == "pid-de_young_f"


def test_refuses_to_render_with_unready_voices(script):
    level = load_levels()[script.level]
    with pytest.raises(VoiceNotReady, match="no profile_id"):
        build(script, unready_voices(), level)


def test_default_speed_segments_emit_no_inline_tag(script, ready_voices):
    level = load_levels()[script.level]
    doc = build(script, ready_voices, level)
    body = doc.text.splitlines()[1:]  # drop the '# heading'
    assert len(body) == len(script.segments), "one line per segment"
    tagged = 0
    for seg, line in zip(script.segments, body, strict=True):
        if seg.speed is None:
            assert "[slow]" not in line and "[emphasis]" not in line and "[fast]" not in line
        else:
            tagged += 1
    assert tagged == sum(1 for s in script.segments if s.speed is not None)
    assert doc.default_speed == level.default_speed
    assert doc.unrepresentable == {}


def test_default_voice_is_narrator(script, ready_voices):
    level = load_levels()[script.level]
    doc = build(script, ready_voices, level)
    assert doc.default_voice == "pid-de_narrator_f"


def test_srt_formats_timestamps_and_translation():
    cues = [
        Cue(0, 1500, "Guten Morgen!", "Good morning!"),
        Cue(62_345, 3_725_000, "Sehr gut.", None),
    ]
    out = to_srt(cues)
    assert "1\n00:00:00,000 --> 00:00:01,500\nGuten Morgen!\nGood morning!" in out
    assert "2\n00:01:02,345 --> 01:02:05,000\nSehr gut." in out
    assert "Sehr gut.\n" in out and out.count("Sehr gut.") == 1
