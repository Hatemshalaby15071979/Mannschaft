"""M3 — per-segment renderer + content-addressed cache.

The load-bearing property: a cache key must cover every input that can change
the waveform. If one is missing, editing a lesson silently serves stale audio.
Each test below pins one such input.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from v5.config import ROOT, load_levels, load_voices
from v5.contract import LessonScript
from v5.render import (
    AudioCache,
    RenderError,
    SynthesisRequest,
    VoiceNotReady,
    VoiceStudioClient,
    render_lesson,
    render_segment,
    request_for,
)
from v5.render.segment import MAX_INPUT_CHARS

LESSON = ROOT / "content" / "lessons" / "A2-01.lesson.json"

BASE = SynthesisRequest(text="Guten Morgen!", voice_profile_id="pid-de_young_f", seed=712340023)


class FakeTransport:
    """Records calls; returns filler bytes. Never touches the network."""

    def __init__(self, audio: bytes = b"RIFF" + b"\x00" * 60) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.audio = audio

    def __call__(self, url: str, payload: dict) -> bytes:
        self.calls.append((url, payload))
        return self.audio


@pytest.fixture(scope="module")
def script() -> LessonScript:
    return LessonScript.model_validate(json.loads(LESSON.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def ready_voices():
    """Fake profile ids so the renderer can run before M4 exists."""
    return {
        key: dataclasses.replace(prof, profile_id=f"pid-{key}")
        for key, prof in load_voices().items()
    }


@pytest.fixture
def cache(tmp_path) -> AudioCache:
    return AudioCache(root=tmp_path / "cache")


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def client(transport) -> VoiceStudioClient:
    return VoiceStudioClient(transport=transport)


# --------------------------------------------------------------------------
# cache key coverage — one test per audio-affecting field
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("text", "Guten Abend!"),
        ("voice_profile_id", "pid-de_older_m"),
        ("language", "en"),
        ("speed", 0.85),
        ("seed", 712340053),
        ("model", "indextts2"),
        ("num_step", 64),
        ("guidance_scale", 3.5),
        ("response_format", "mp3"),
    ],
)
def test_every_audio_input_busts_the_key(field, value):
    changed = dataclasses.replace(BASE, **{field: value})
    assert changed.key() != BASE.key(), f"changing {field} must invalidate the cache"


def test_bookkeeping_fields_do_not_bust_the_key():
    # Same audio, different caller: must be one cache entry, not two.
    a = dataclasses.replace(BASE, segment_id="s001", lesson_id="A2-01")
    b = dataclasses.replace(BASE, segment_id="s099", lesson_id="B1-07")
    assert a.key() == b.key()


def test_key_is_deterministic_sha256_over_sorted_json():
    # Independent recomputation: proves the algorithm and that no dict ordering
    # or PYTHONHASHSEED can change the key between processes.
    import hashlib

    blob = json.dumps(BASE.fingerprint(), sort_keys=True, ensure_ascii=False)
    expected = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    assert BASE.key() == expected
    assert len(BASE.key()) == 64


def test_cache_version_is_part_of_the_fingerprint():
    assert BASE.fingerprint()["cache_version"] >= 1


def test_identical_requests_share_one_key():
    assert BASE.key() == dataclasses.replace(BASE).key()


def test_key_is_not_affected_by_float_formatting_noise():
    # 0.9 and 0.90 are the same float; they must not split the cache.
    assert dataclasses.replace(BASE, speed=0.9).key() == dataclasses.replace(BASE, speed=0.90).key()


# --------------------------------------------------------------------------
# payload shape — exactly what /v1/audio/speech accepts
# --------------------------------------------------------------------------


def test_payload_uses_the_endpoint_vocabulary():
    payload = BASE.payload()
    assert payload["input"] == BASE.text
    assert payload["voice"] == BASE.voice_profile_id
    assert payload["model"] == "omnivoice"
    assert payload["response_format"] == "wav"
    assert payload["language"] == "de"
    assert payload["num_step"] == 32
    assert payload["guidance_scale"] == 2.0
    assert payload["seed"] == 712340023
    # the OpenAI-alias bug: never send these
    assert "voice_id" not in payload
    assert "prompt" not in payload


def test_seed_is_omitted_when_absent():
    payload = dataclasses.replace(BASE, seed=None).payload()
    assert "seed" not in payload


def test_speed_survives_as_an_exact_float():
    # The endpoint accepts 0.25–4.0; A2 must render at 0.90, not 0.92.
    assert dataclasses.replace(BASE, speed=0.90).payload()["speed"] == 0.90


# --------------------------------------------------------------------------
# transport contract
# --------------------------------------------------------------------------


def test_client_posts_to_the_speech_endpoint(client, transport):
    client.synthesize(BASE)
    assert len(transport.calls) == 1
    url, payload = transport.calls[0]
    assert url == "http://127.0.0.1:3900/v1/audio/speech"
    assert payload["input"] == BASE.text


def test_client_rejects_empty_text(client, transport):
    with pytest.raises(RenderError, match="empty text"):
        client.synthesize(dataclasses.replace(BASE, text="   "))
    assert transport.calls == []


def test_client_rejects_text_over_endpoint_cap(client, transport):
    long_text = "a" * (MAX_INPUT_CHARS + 1)
    with pytest.raises(RenderError, match="caps at 4096"):
        client.synthesize(dataclasses.replace(BASE, text=long_text))
    assert transport.calls == []


def test_client_accepts_text_exactly_at_the_cap(client, transport):
    client.synthesize(dataclasses.replace(BASE, text="a" * MAX_INPUT_CHARS))
    assert len(transport.calls) == 1


def test_client_refuses_empty_profile_id(client, transport):
    # This is the v4 bug: an empty/alias voice silently renders in the engine
    # default. We refuse instead of shipping inaudible-difference audio.
    with pytest.raises(VoiceNotReady):
        client.synthesize(dataclasses.replace(BASE, voice_profile_id=""))
    assert transport.calls == []


def test_client_rejects_zero_byte_response(transport):
    transport.audio = b""
    with pytest.raises(RenderError, match="0 bytes"):
        VoiceStudioClient(transport=transport).synthesize(BASE)


# --------------------------------------------------------------------------
# cache storage behaviour
# --------------------------------------------------------------------------


def test_cache_is_content_addressed_under_a_tmp_root(cache):
    path = cache.put("abc123", b"RIFF-data")
    assert path.exists()
    assert path.read_bytes() == b"RIFF-data"
    assert cache.root in path.parents
    assert not path.with_suffix(path.suffix + ".part").exists(), "atomic write must clean up"


def test_second_get_is_a_hit(cache):
    key = BASE.key()
    assert cache.get(key) is None
    cache.put(key, b"RIFF")
    assert cache.get(key) is not None
    assert cache.stats.misses == 1
    assert cache.stats.hits == 1
    assert cache.stats.hit_rate == 0.5


def test_empty_cache_entry_is_a_miss_not_a_silent_success(cache):
    key = BASE.key()
    path = cache.path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")  # killed mid-write
    assert cache.get(key) is None


def test_clear_and_size(cache):
    cache.put("k1", b"12345")
    cache.put("k2", b"678")
    assert cache.size_bytes() == 8
    assert cache.clear() == 2
    assert cache.size_bytes() == 0


# --------------------------------------------------------------------------
# render_segment
# --------------------------------------------------------------------------


def test_first_render_misses_second_hits(script, ready_voices, cache, transport, client):
    seg = script.segments[0]
    level = load_levels()[script.level]
    profile = ready_voices["de_narrator_f"]

    first = render_segment(seg, profile, level, cache, client)
    second = render_segment(seg, profile, level, cache, client)

    assert first.cached is False
    assert second.cached is True
    assert first.key == second.key
    assert first.path == second.path
    assert len(transport.calls) == 1, "second render must not hit the engine"


def test_editing_one_line_busts_only_that_line(script, ready_voices, cache, client):
    level = load_levels()[script.level]
    profile = ready_voices["de_narrator_f"]
    seg = script.segments[0]

    render_segment(seg, profile, level, cache, client)
    edited = seg.model_copy(update={"text": seg.text + " Wirklich."})
    result = render_segment(edited, profile, level, cache, client)
    assert result.cached is False


def test_request_for_uses_level_baseline_when_speed_is_unset(script, ready_voices):
    level = load_levels()[script.level]
    seg = next(s for s in script.segments if s.speed is None)
    profile = ready_voices[script.roles[seg.speaker].voice]
    req = request_for(seg, profile, level)
    assert req.speed == level.default_speed == 0.90
    assert req.seed == profile.seed
    assert req.language == "de"


def test_request_for_prefers_authored_speed(script, ready_voices):
    level = load_levels()[script.level]
    seg = next(s for s in script.segments if s.speed is not None)
    profile = ready_voices[script.roles[seg.speaker].voice]
    assert request_for(seg, profile, level).speed == seg.speed


# --------------------------------------------------------------------------
# render_lesson
# --------------------------------------------------------------------------


def test_render_lesson_refuses_when_profiles_are_missing(script, cache, client):
    with pytest.raises(VoiceNotReady, match="no profile_id"):
        render_lesson(
            script, load_voices(), load_levels()[script.level], cache, client, cache.root / "out"
        )


def test_render_lesson_writes_one_wav_per_segment(script, ready_voices, cache, transport, client, tmp_path):
    out = tmp_path / "out"
    level = load_levels()[script.level]

    results = render_lesson(script, ready_voices, level, cache, client, out)

    assert len(results) == len(script.segments)
    assert {r.segment_id for r in results} == {s.id for s in script.segments}
    assert all(r.path.exists() and r.path.stat().st_size > 0 for r in results)
    # repeats (echo/drill) are one synthesis each: the cache is per segment,
    # and the assembler is what repeats the audio.
    expected_keys = {
        request_for(
            s, ready_voices[script.roles[s.speaker].voice], level
        ).key()
        for s in script.segments
    }
    assert len(transport.calls) == len(expected_keys)


def test_second_lesson_render_hits_the_cache(script, ready_voices, cache, transport, client, tmp_path):
    level = load_levels()[script.level]
    out = tmp_path / "out"

    render_lesson(script, ready_voices, level, cache, client, out)
    calls_after_first = len(transport.calls)

    again = render_lesson(script, ready_voices, level, cache, client, out)

    assert len(transport.calls) == calls_after_first, "re-render must not call the engine"
    assert all(r.cached for r in again)


# --------------------------------------------------------------------------
# CLI wiring — `python -m v5 render ID`
# --------------------------------------------------------------------------


def test_cli_render_refuses_while_voices_are_unready(capsys):
    from v5.contract.cli import main

    assert main(["render", "A2-01"]) == 2
    err = capsys.readouterr().err
    assert "profile_id" in err
    assert "M4" in err


def test_cli_render_unknown_lesson_exits_1(capsys):
    from v5.contract.cli import main

    assert main(["render", "ZZ-99"]) == 1
    assert "no such lesson" in capsys.readouterr().err


def test_cli_render_refuses_an_invalid_lesson(tmp_path, monkeypatch, capsys):
    import v5.contract.cli as cli

    bad = json.loads(LESSON.read_text(encoding="utf-8"))
    bad["segments"][0]["pause_after_ms"] = 9000
    (tmp_path / "A2-01.lesson.json").write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setattr(cli, "LESSONS_DIR", tmp_path)

    assert cli.main(["render", "A2-01"]) == 1
    assert "refusing to render" in capsys.readouterr().err


def test_cli_render_renders_a_lesson_end_to_end(tmp_path, monkeypatch, ready_voices, capsys):
    import v5.contract.cli as cli

    fake = FakeTransport()
    monkeypatch.setattr(cli, "load_voices", lambda: ready_voices)
    monkeypatch.setattr(cli, "AudioCache", lambda: AudioCache(root=tmp_path / "cache"))
    monkeypatch.setattr(cli, "VoiceStudioClient", lambda: VoiceStudioClient(transport=fake))
    monkeypatch.setattr(cli, "AUDIO_DIR", tmp_path / "audio")

    assert cli.main(["render", "A2-01"]) == 0
    out = capsys.readouterr().out
    assert "28 segments" in out
    assert "0 from cache, 28 synthesised" in out
    lines = list((tmp_path / "audio" / "A2-01" / "lines").glob("*.wav"))
    assert len(lines) == 28

    # second run is a pure cache replay
    assert cli.main(["render", "A2-01"]) == 0
    assert "28 from cache, 0 synthesised" in capsys.readouterr().out
    assert len(fake.calls) == 28
