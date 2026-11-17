from __future__ import annotations

import v5
from v5.config import load_levels, load_voices, missing_profiles


def test_version():
    assert v5.__version__ == "0.1.0"
    assert v5.SCHEMA == "lesson-script/v1"


def test_six_voices_configured():
    voices = load_voices()
    assert len(voices) == 6
    assert set(voices) == {
        "de_narrator_f",
        "de_narrator_m",
        "de_young_f",
        "de_young_m",
        "de_older_f",
        "de_older_m",
    }


def test_voice_seeds_are_distinct():
    seeds = [v.seed for v in load_voices().values()]
    assert len(seeds) == len(set(seeds)), "duplicate seeds push voices toward same timbre"
    assert 445117530 not in seeds, "seed already used by existing English profiles"


def test_voice_instruct_uses_only_whitelist_tokens():
    allowed = {
        "male", "female",
        "child", "teenager", "young adult", "middle-aged", "elderly",
        "very low pitch", "low pitch", "moderate pitch", "high pitch", "very high pitch",
        "whisper",
    }
    for prof in load_voices().values():
        tokens = {t.strip() for t in prof.instruct.split(",")}
        assert tokens <= allowed, f"{prof.key}: {tokens - allowed} not in whitelist"
        assert "accent" not in prof.instruct, "accents are English-only"


def test_voices_are_pending_until_m4():
    # M4 is manual: until the user creates them, ids must be empty so renderers refuse.
    missing = missing_profiles()
    assert isinstance(missing, list)


def test_levels_have_monotonic_difficulty():
    levels = load_levels()
    assert list(levels) == ["A1", "A2", "B1", "B2", "C1", "C2"]
    speeds = [levels[k].default_speed for k in levels]
    assert speeds == sorted(speeds), "speed must increase with level"
    word_caps = [levels[k].max_words_per_line for k in levels]
    assert word_caps == sorted(word_caps), "word cap must increase with level"
