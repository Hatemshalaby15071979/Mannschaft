"""M7 — the localhost server.

The load-bearing assertions: byte-range seeking returns real 206s with the right
`Content-Range`, health tells the truth when VoiceStudio is down, and the app
refuses to bind anywhere but loopback.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from v5.config import load_voices
from v5.server import ProgressStore, assert_loopback, create_app

AUDIO_BYTES = bytes(range(256)) * 8  # 2048 bytes, deterministic


def _lesson(lesson_id: str = "A1-98", level: str = "A1", tag: str = "test") -> dict:
    return {
        "id": lesson_id,
        "level": level,
        "title": {"de": "Kurz", "en": "Short"},
        "minutes": 1,
        "scene": {
            "setting_de": "Ein Test.",
            "setting_en": "A test.",
            "register": "neutral",
            "can_do_de": "Ich kann testen.",
            "can_do_en": "I can test.",
            "situation_tags": [tag],
            "grammar_focus": ["test"],
        },
        "cast": [{"role": "narrator", "voice": "de_narrator_f"}],
        "segments": [
            {
                "id": "s1",
                "type": "line",
                "speaker": "narrator",
                "text": "Guten Tag.",
                "translation": "Good day.",
                "pause_after_ms": 400,
            },
            {
                "id": "s2",
                "type": "line",
                "speaker": "narrator",
                "text": "Bis später.",
                "translation": "See you later.",
                "pause_after_ms": 300,
            },
            {
                "id": "s3",
                "type": "check",
                "speaker": "narrator",
                "text": "Wie geht es?",
                "translation": "How are you?",
                "answers": ["gut"],
                "answer_pause_ms": 1500,
                "pause_after_ms": 0,
            },
        ],
        "glossary": [],
    }


@pytest.fixture
def ready_voices():
    return {
        key: dataclasses.replace(prof, profile_id=f"pid-{key}")
        for key, prof in load_voices().items()
    }


@pytest.fixture
def env(tmp_path) -> dict:
    lessons = tmp_path / "lessons"
    lessons.mkdir()
    (lessons / "A1-98.lesson.json").write_text(json.dumps(_lesson()), encoding="utf-8")
    (lessons / "B1-07.lesson.json").write_text(
        json.dumps(_lesson("B1-07", "B1", "work")), encoding="utf-8"
    )

    audio = tmp_path / "audio"
    lesson_dir = audio / "A1-98"
    (lesson_dir / "lines").mkdir(parents=True)
    (lesson_dir / "lesson.mp3").write_bytes(AUDIO_BYTES)
    (lesson_dir / "lines" / "s1.mp3").write_bytes(AUDIO_BYTES[:400])
    (lesson_dir / "timeline.json").write_text(
        json.dumps(
            [
                {"id": "s1", "start_ms": 0, "end_ms": 900, "speaker": "narrator",
                 "voice": "de_narrator_f", "type": "line", "text": "Guten Tag."},
                {"id": "s2", "start_ms": 1300, "end_ms": 2100, "speaker": "narrator",
                 "voice": "de_narrator_f", "type": "line", "text": "Bis später."},
            ]
        ),
        encoding="utf-8",
    )
    (lesson_dir / "manifest.json").write_text(
        json.dumps({"lesson_id": "A1-98", "duration_ms": 2100, "segments": 3}),
        encoding="utf-8",
    )

    return {"tmp": tmp_path, "lessons": lessons, "audio": audio}


@pytest.fixture
def client(env, ready_voices, monkeypatch):
    # VoiceStudio is down for every test that does not say otherwise.
    monkeypatch.setattr(
        "v5.server.app.probe",
        lambda *a, **k: {"up": False, "voices": None, "error": "connection refused"},
    )
    app = create_app(
        lessons_dir=env["lessons"],
        audio_dir=env["audio"],
        progress_db=env["tmp"] / "progress.sqlite",
        voices=ready_voices,
        render_fn=lambda lesson_id, progress: SimpleNamespace(segments=3),
    )
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------
# binding
# --------------------------------------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_hosts_are_allowed(host):
    assert assert_loopback(host) == host


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "10.0.0.1", "::"])
def test_non_loopback_hosts_are_refused(host):
    with pytest.raises(ValueError, match="localhost-only"):
        assert_loopback(host)


def test_serve_cli_refuses_to_bind_publicly(capsys):
    from v5.contract.cli import main

    assert main(["serve", "--host", "0.0.0.0"]) == 2
    assert "localhost-only" in capsys.readouterr().err


# --------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------


def test_health_reports_voicestudio_down(client):
    body = client.get("/api/health").json()
    assert body["app"] == "ok"
    assert body["voicestudio"]["up"] is False
    assert "refused" in body["voicestudio"]["error"]
    assert body["voices_ok"] is True
    assert body["lessons"] == {"total": 2, "rendered": 1}


def test_health_reports_missing_voices(env, monkeypatch):
    monkeypatch.setattr(
        "v5.server.app.probe", lambda *a, **k: {"up": True, "voices": 3, "error": None}
    )
    app = create_app(
        lessons_dir=env["lessons"],
        audio_dir=env["audio"],
        progress_db=env["tmp"] / "p.sqlite",
        voices=load_voices(),  # real config: profile ids are empty until M4
    )
    body = TestClient(app).get("/api/health").json()
    assert body["voices_ok"] is False
    assert len(body["missing_voices"]) == 6
    assert body["voicestudio"]["up"] is True


# --------------------------------------------------------------------------
# catalogue
# --------------------------------------------------------------------------


def test_lessons_lists_every_valid_file(client):
    body = client.get("/api/lessons").json()
    assert body["count"] == 2
    assert [row["id"] for row in body["lessons"]] == ["A1-98", "B1-07"]
    row = body["lessons"][0]
    assert row["rendered"] is True
    assert row["duration_ms"] == 2100
    assert row["segments"] == 3


def test_lessons_filter_by_level_and_tag(client):
    assert [r["id"] for r in client.get("/api/lessons?level=A1").json()["lessons"]] == ["A1-98"]
    assert [r["id"] for r in client.get("/api/lessons?tag=work").json()["lessons"]] == ["B1-07"]
    assert client.get("/api/lessons?level=C2").json()["count"] == 0


def test_lesson_detail_includes_script_and_measured_timeline(client):
    body = client.get("/api/lessons/A1-98").json()
    assert body["lesson"]["id"] == "A1-98"
    assert len(body["lesson"]["segments"]) == 3
    assert [e["id"] for e in body["timeline"]] == ["s1", "s2"]
    assert body["summary"]["rendered"] is True


def test_unrendered_lesson_has_no_timeline(env, ready_voices):
    app = create_app(
        lessons_dir=env["lessons"],
        audio_dir=env["audio"],
        progress_db=env["tmp"] / "p.sqlite",
        voices=ready_voices,
        render_fn=lambda lesson_id, progress: SimpleNamespace(segments=3),
    )
    body = TestClient(app).get("/api/lessons/B1-07").json()
    assert body["lesson"]["id"] == "B1-07"
    assert body["timeline"] is None
    assert body["summary"]["rendered"] is False


def test_unknown_lesson_is_404(client):
    assert client.get("/api/lessons/ZZ-99").status_code == 404


# --------------------------------------------------------------------------
# byte-range audio — the milestone's headline assertion
# --------------------------------------------------------------------------


def test_full_audio_is_200_and_byte_exact(client):
    response = client.get("/api/audio/A1-98")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.content == AUDIO_BYTES


def test_range_request_returns_206_with_content_range(client):
    response = client.get("/api/audio/A1-98", headers={"Range": "bytes=0-99"})
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 0-99/{len(AUDIO_BYTES)}"
    assert response.headers["content-length"] == "100"
    assert response.content == AUDIO_BYTES[:100]


def test_mid_file_range_is_exact(client):
    response = client.get("/api/audio/A1-98", headers={"Range": "bytes=1000-1099"})
    assert response.status_code == 206
    assert response.content == AUDIO_BYTES[1000:1100]
    assert response.headers["content-range"] == f"bytes 1000-1099/{len(AUDIO_BYTES)}"


def test_suffix_range_returns_the_tail(client):
    response = client.get("/api/audio/A1-98", headers={"Range": "bytes=-64"})
    assert response.status_code == 206
    assert response.content == AUDIO_BYTES[-64:]


def test_unsatisfiable_range_is_416(client):
    response = client.get("/api/audio/A1-98", headers={"Range": "bytes=99999-100000"})
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(AUDIO_BYTES)}"


def test_unrendered_audio_is_404_with_a_hint(client):
    response = client.get("/api/audio/B1-07")
    assert response.status_code == 404
    assert "POST /api/render/B1-07" in response.json()["detail"]


def test_line_clip_and_missing_clip(client):
    ok = client.get("/api/audio/A1-98/lines/s1")
    assert ok.status_code == 200
    assert ok.content == AUDIO_BYTES[:400]
    assert client.get("/api/audio/A1-98/lines/s2").status_code == 404


# --------------------------------------------------------------------------
# progress
# --------------------------------------------------------------------------


def test_progress_starts_empty(client):
    body = client.get("/api/progress").json()
    assert body["resume"] is None
    assert body["lessons"] == []


def test_progress_resumes_at_the_segment(client):
    client.post(
        "/api/progress",
        json={"lesson_id": "A1-98", "seg_id": "s2", "position_ms": 1300},
    )
    body = client.get("/api/progress").json()
    assert body["resume"]["lesson_id"] == "A1-98"
    assert body["resume"]["seg_id"] == "s2"
    assert body["resume"]["position_ms"] == 1300
    assert body["resume"]["completed"] == 0


def test_completed_lesson_drops_out_of_resume(client):
    client.post(
        "/api/progress",
        json={"lesson_id": "A1-98", "seg_id": "s3", "position_ms": 2100, "completed": True},
    )
    assert client.get("/api/progress").json()["resume"] is None


def test_progress_for_unknown_lesson_is_404(client):
    response = client.post(
        "/api/progress", json={"lesson_id": "ZZ-99", "seg_id": "s1", "position_ms": 0}
    )
    assert response.status_code == 404


def test_progress_survives_a_reopened_store(env):
    path = env["tmp"] / "reopen.sqlite"
    ProgressStore(path).upsert("A1-98", "s1", 500)
    row = ProgressStore(path).for_lesson("A1-98")
    assert row["seg_id"] == "s1"
    assert row["position_ms"] == 500


def test_negative_position_is_rejected(client):
    response = client.post(
        "/api/progress", json={"lesson_id": "A1-98", "seg_id": "s1", "position_ms": -5}
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# render jobs
# --------------------------------------------------------------------------


def test_render_job_is_queued_then_completes(env, ready_voices, monkeypatch):
    monkeypatch.setattr(
        "v5.server.app.probe", lambda *a, **k: {"up": False, "voices": None, "error": "down"}
    )

    def fake_render(lesson_id, progress):
        progress(1, 3)
        progress(3, 3)
        return SimpleNamespace(segments=3)

    app = create_app(
        lessons_dir=env["lessons"],
        audio_dir=env["audio"],
        progress_db=env["tmp"] / "p.sqlite",
        voices=ready_voices,
        render_fn=fake_render,
    )
    with TestClient(app) as client:
        response = client.post("/api/render/B1-07")
        assert response.status_code == 202
        job = response.json()["job"]
        assert job["lesson_id"] == "B1-07"
        assert job["state"] in ("queued", "running", "done")

        app.state.jobs.wait(job["job_id"], timeout=5)
        final = client.get(f"/api/render/{job['job_id']}").json()
        assert final["state"] == "done"
        assert final["done"] == final["total"] == 3


def test_render_refuses_while_voices_are_unready(env):
    app = create_app(
        lessons_dir=env["lessons"],
        audio_dir=env["audio"],
        progress_db=env["tmp"] / "p.sqlite",
        voices=load_voices(),
    )
    response = TestClient(app).post("/api/render/A1-98")
    assert response.status_code == 409
    assert len(response.json()["detail"]["missing_voices"]) == 6


def test_render_unknown_lesson_is_404(client):
    assert client.post("/api/render/ZZ-99").status_code == 404


def test_render_unknown_job_is_404(client):
    assert client.get("/api/render/nope").status_code == 404


def test_duplicate_submit_returns_the_active_job(env, ready_voices):
    import threading

    gate = threading.Event()

    def slow_render(lesson_id, progress):
        gate.wait(timeout=5)
        return SimpleNamespace(segments=3)

    app = create_app(
        lessons_dir=env["lessons"],
        audio_dir=env["audio"],
        progress_db=env["tmp"] / "p.sqlite",
        voices=ready_voices,
        render_fn=slow_render,
    )
    with TestClient(app) as client:
        first = client.post("/api/render/A1-98").json()["job"]
        second = client.post("/api/render/A1-98")
        assert second.status_code == 202
        assert second.json()["job"]["job_id"] == first["job_id"]
        assert second.json()["already_active"] is True
        gate.set()
        app.state.jobs.wait(first["job_id"], timeout=5)


def test_job_error_is_reported_not_raised(env, ready_voices):
    def broken_render(lesson_id, progress):
        raise RuntimeError("engine exploded")

    app = create_app(
        lessons_dir=env["lessons"],
        audio_dir=env["audio"],
        progress_db=env["tmp"] / "p.sqlite",
        voices=ready_voices,
        render_fn=broken_render,
    )
    with TestClient(app) as client:
        job = client.post("/api/render/A1-98").json()["job"]
        app.state.jobs.wait(job["job_id"], timeout=5)
        final = client.get(f"/api/render/{job['job_id']}").json()
        assert final["state"] == "error"
        assert "engine exploded" in final["error"]


# --------------------------------------------------------------------------
# corpus
# --------------------------------------------------------------------------


def test_corpus_suggest_is_honest_when_the_corpus_is_empty(client, monkeypatch):
    monkeypatch.setattr("v5.server.app.CORPUS_PATH", Path("/nonexistent/clips.jsonl"))
    body = client.get("/api/corpus/suggest?level=A2").json()
    assert body["candidates"] == []
    assert "M6" in body["reason"]


def test_api_root_answers(client):
    assert client.get("/api").json()["app"] == "v5"


def test_client_is_served_at_root(tmp_path):
    """When the PWA assets exist, `/` is the app shell, not a JSON root."""
    from v5.server import create_app

    app = create_app(progress_db=tmp_path / "p.sqlite")
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "js/main.js" in response.text
