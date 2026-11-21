"""M8 — browser smoke test.

Proves the user-visible spine end-to-end, with no VoiceStudio and no M4:

* build a real lesson file,
* render it with a fake transport (deterministic ffmpeg tones),
* assemble `lesson.mp3` + `timeline.json`,
* start the M7 app on an ephemeral port,
* drive a headless browser: library → lesson → play,
* assert playback position advances,
* reload, assert position is restored,
* assert a 206 Range request returns the right slice (the SW's input).

Skips itself when Playwright or a browser is unavailable, because the
machine that fails `make check` for wanting a browser is not the right place
to be failing.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="Playwright browser required for the M8 smoke test")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from v5.config import load_voices  # noqa: E402
from v5.render import AudioCache, render_lesson_to_disk  # noqa: E402
from v5.server import create_app  # noqa: E402

try:  # tests/ is a sibling of src/, so import the module directly
    from tests.helpers import make_clip  # noqa: E402
except ModuleNotFoundError:  # pragma: no cover
    import subprocess

    def make_clip(path, seconds, freq=440, pad_s=0.15):
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}:sample_rate=24000",
                "-af", f"adelay={int(pad_s * 1000)}:all=1,apad=pad_dur={pad_s}",
                "-c:a", "pcm_s16le", str(path),
            ],
            check=True,
        )
        return path

try:
    from playwright.sync_api import sync_playwright  # noqa: E402
except Exception:  # pragma: no cover
    sync_playwright = None


def _importorskip_browser():
    if sync_playwright is None:
        pytest.skip("playwright python module is not installed on this machine")


def _minimal_lesson(lesson_id: str, segments: int, per_line_s: float = 0.6) -> dict:
    segs = []
    for i in range(segments):
        segs.append(
            {
                "id": f"s{i+1}",
                "type": "line",
                "speaker": "narrator",
                "text": f"Satz {i+1}.",
                "translation": f"Line {i+1}.",
                "pause_after_ms": int(per_line_s * 1000),
            }
        )
    return {
        "id": lesson_id,
        "level": "A1",
        "title": {"de": "Smoke", "en": "Smoke"},
        "minutes": 1,
        "scene": {
            "setting_de": "Test.",
            "setting_en": "Test.",
            "register": "neutral",
            "can_do_de": "Kann testen.",
            "can_do_en": "Can test.",
            "situation_tags": ["smoke"],
            "grammar_focus": ["smoke"],
        },
        "cast": [{"role": "narrator", "voice": "de_narrator_f"}],
        "segments": segs,
        "glossary": [
            {
                "id": "g1",
                "de": "Test",
                "en": "test",
                "pos": "n",
                "example_de": "Ein Test.",
                "example_en": "A test.",
            }
        ],
    }


@pytest.fixture(scope="session")
def server_url(tmp_path_factory):
    _importorskip_browser()

    base = tmp_path_factory.mktemp("smoke")
    lessons = base / "lessons"
    audio = base / "audio"
    lessons.mkdir()
    (lessons / "A1-01.lesson.json").write_text(
        json.dumps(_minimal_lesson("A1-01", 6)), encoding="utf-8"
    )

    # render with ffmpeg tones — deterministic, no GPU, no M4
    import dataclasses

    voices = {
        key: dataclasses.replace(profile, profile_id=f"pid-{key}")
        for key, profile in load_voices().items()
    }

    class FakeClient:
        def synthesize(self, request):
            wav = make_clip(base / "wav" / f"{request.segment_id}.wav", 1.0, 440)
            return wav.read_bytes()


    outcome = render_lesson_to_disk(
        "A1-01",
        lessons_dir=lessons,
        audio_dir=audio,
        cache=AudioCache(base / "cache"),
        client=FakeClient(),
        voices=voices,
    )
    assert outcome.assembly is not None

    progress_db = base / "progress.sqlite"
    app = create_app(
        lessons_dir=lessons,
        audio_dir=audio,
        progress_db=progress_db,
        voices=voices,
    )

    # ephemeral port, loopback only
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            import urllib.request

            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5)
            break
        except Exception:
            time.sleep(0.1)
    else:
        pytest.fail("server did not come up")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)


def test_library_to_play_and_position_restores(server_url):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--autoplay-policy=no-user-gesture-required", "--use-fake-device-for-media-device"]
        )
        page = browser.new_page()
        page.on("console", lambda msg: print("console:", msg.text))
        page.on("pageerror", lambda err: print("pageerror:", err))
        page.goto(server_url, wait_until="load")
        page.wait_for_selector(".tabbar", timeout=10_000)

        # library renders the lesson row
        page.evaluate("location.hash = '#/library'")
        page.wait_for_selector('a[href="#/lesson/A1-01"]', timeout=15_000)

        # lesson detail offers the player link
        page.evaluate("location.hash = '#/lesson/A1-01'")
        page.wait_for_selector('a[href="#/play/A1-01"]', timeout=15_000)

        # player loads and advances
        page.evaluate("location.hash = '#/play/A1-01?play=1'")
        page.wait_for_selector(".now .de", timeout=15_000)
        position_before = page.evaluate("document.querySelector('input#seek').value")
        page.wait_for_timeout(1200)
        position_after = page.evaluate("document.querySelector('input#seek').value")
        assert int(position_after) > int(position_before), "playback position must advance"

        # verify the save actually landed on the server
        direct = page.evaluate(
            """async () => {
                const r = await fetch('/api/progress', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ lesson_id: 'A1-01', seg_id: 's3', position_ms: 1500, completed: false })
                });
                await new Promise(res => setTimeout(res, 300));
                const g = await fetch('/api/progress?ts=' + Date.now(), { cache: 'no-store' });
                const j = await g.json();
                const row = (j.lessons || []).find(x => x.lesson_id === 'A1-01');
                return { status: r.status, position: row ? row.position_ms : 0 };
            }"""
        )
        assert direct["status"] == 200, f"POST /api/progress returned {direct['status']}"
        assert direct["position"] >= 1000, (
            f"server should have the save (direct={direct})"
        )

        # reload restores position
        page.reload(wait_until="load")
        page.evaluate("location.hash = '#/play/A1-01'")
        page.wait_for_selector(".now .de", timeout=15_000)
        # give the audio element time to load its metadata and seek to the
        # restored position
        page.wait_for_timeout(2000)
        restored = page.evaluate("document.querySelector('input#seek').value")
        assert int(restored) >= 1000, (
            f"position must roughly survive reload (restored={restored}, server had {direct['position']})"
        )

        browser.close()


def test_every_screen_renders_real_content(server_url):
    """No screen may fall through to the literal text 'undefined'.

    Regression: home.js destructured an undeclared `all` (ReferenceError in an
    ES module), and main.js appended `result.node` even when a screen's error
    path returned a bare element — both rendered the word 'undefined'. The old
    smoke test only visited library/lesson/play, so neither was caught.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page()
        page.goto(server_url, wait_until="load")
        page.wait_for_selector(".tabbar", timeout=10_000)

        routes = [
            ("#/", "Hören zuerst."),
            ("#/library", "Bibliothek"),
            ("#/lesson/A1-01", "Segmente"),
            ("#/play/A1-01", "NARRATOR"),
            ("#/transcript/A1-01", "Zeilen"),
            ("#/glossary/A1-01", "Glossar"),
            ("#/drill/A1-01", "bung"),
            ("#/progress", "Fortschritt"),
            ("#/clip/A1-01", "EIN CLIP"),
            ("#/cards/A1-01", "KARTEN"),
            ("#/dict", "Wort nachschlagen"),
        ]
        for route, expected in routes:
            page.evaluate(f"location.hash = {json.dumps(route)}")
            page.wait_for_timeout(400)
            text = page.locator("#screen").inner_text()
            assert text.strip(), f"{route} rendered nothing"
            assert "undefined" not in text, f"{route} rendered literal 'undefined': {text[:200]}"
            assert expected in text, f"{route} missing expected text {expected!r}: {text[:200]}"

        browser.close()


def test_player_saves_progress_during_playback(server_url):
    """The player must auto-save while playing, with no manual POST.

    Regression: player.load() never assigned `this.detail`, so _maybeSave and
    _save both returned early and no progress was ever written during ordinary
    listening. The other smoke test POSTs progress by hand and only checks
    restore, so it passed despite the broken auto-save.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--autoplay-policy=no-user-gesture-required", "--no-sandbox"]
        )
        page = browser.new_page()
        posts = []
        page.on("request", lambda req: posts.append(req.url) if req.method == "POST" else None)
        page.goto(server_url + "/#/play/A1-01", wait_until="load")
        page.wait_for_selector("input#seek", timeout=15_000)

        # The player must retain the lesson detail after load().
        has_detail = page.evaluate(
            "async () => (await import('/js/player.js')).player.detail !== null"
        )
        assert has_detail, "player.load() must keep the lesson detail for progress saving"

        # Play longer than SAVE_INTERVAL_MS (4 s) so the periodic save fires.
        page.locator("[data-action=play]").click()
        page.wait_for_timeout(5_000)
        assert any("/api/progress" in url for url in posts), (
            f"no automatic progress POST during playback (posts={posts})"
        )
        browser.close()


def test_range_requests_serve_sliced_bytes(server_url):
    import urllib.request

    url = f"{server_url}/api/audio/A1-01"
    full = urllib.request.urlopen(url).read()
    assert len(full) > 0

    range_request = urllib.request.Request(url, headers={"Range": "bytes=0-99"})
    response = urllib.request.urlopen(range_request)
    assert response.status == 206
    assert response.headers.get("Content-Range") == f"bytes 0-99/{len(full)}"
    assert response.read() == full[:100]
