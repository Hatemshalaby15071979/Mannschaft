"""M8 — the PWA client.

Two layers:

* asset integrity: the shipped files exist, reference each other correctly,
  the manifest is well-formed, and the service worker's precache list matches
  the files on disk (a drift here is the classic dead-offline-bug);
* serving: the M7 app mounts the client at `/` with the right MIME types, and
  API routes still win over the static mount.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from v5.config import ROOT
from v5.server import create_app

CLIENT = ROOT / "src" / "v5" / "client"

REQUIRED_FILES = [
    "index.html",
    "manifest.webmanifest",
    "sw.js",
    "css/app.css",
    "js/main.js",
    "js/ui.js",
    "js/api.js",
    "js/store.js",
    "js/player.js",
    "js/screens/home.js",
    "js/screens/library.js",
    "js/screens/lesson.js",
    "js/screens/play.js",
    "js/screens/transcript.js",
    "js/screens/glossary.js",
    "js/screens/drill.js",
    "js/screens/progress.js",
    "icons/icon-192.png",
    "icons/icon-512.png",
    "icons/apple-touch-icon.png",
    "icons/favicon-32.png",
    "assets/logo-mark.png",
    "assets/logo-badge.png",
]

SCREENS = [
    "home",
    "library",
    "lesson",
    "play",
    "transcript",
    "glossary",
    "drill",
    "progress",
]


# ---------------------------------------------------------------------------
# asset integrity
# ---------------------------------------------------------------------------


def test_every_required_file_exists():
    missing = [name for name in REQUIRED_FILES if not (CLIENT / name).is_file()]
    assert missing == [], f"missing client files: {missing}"


def test_index_references_real_assets():
    html = (CLIENT / "index.html").read_text(encoding="utf-8")
    referenced = set(re.findall(r'(?:href|src)="([^"]+)"', html))
    for ref in referenced:
        if ref.startswith(("http", "#", "data:")):
            continue
        target = (CLIENT / ref.lstrip("/")).resolve()
        assert target.is_file(), f"index.html references missing file: {ref}"


def test_index_registers_service_worker_module():
    html = (CLIENT / "index.html").read_text(encoding="utf-8")
    assert 'type="module"' in html
    assert "/js/main.js" in html
    assert "/manifest.webmanifest" in html


def test_manifest_is_valid_json_with_installable_fields():
    manifest = json.loads((CLIENT / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["name"].startswith("Mannschaft")
    assert manifest["short_name"] == "Mannschaft"
    assert manifest["start_url"]
    assert manifest["display"] in {"standalone", "fullscreen", "minimal-ui"}
    assert manifest["icons"]
    for icon in manifest["icons"]:
        assert (CLIENT / icon["src"].lstrip("/")).is_file(), f"manifest icon missing: {icon['src']}"
        assert icon["sizes"]


def test_service_worker_precache_matches_disk():
    source = (CLIENT / "sw.js").read_text(encoding="utf-8")
    match = re.search(r"const SHELL_URLS = \[([^\]]*)\]", source)
    assert match, "sw.js must declare a SHELL_URLS precache list"
    urls = re.findall(r"'([^']+)'", match.group(1))
    for url in urls:
        if url == "/":
            continue  # virtual root — the shell entry, not a file
        target = (CLIENT / url.lstrip("/")).resolve()
        assert target.is_file(), f"sw.js precaches a missing file: {url}"
    for name in SCREENS:
        assert f"/js/screens/{name}.js" in urls, f"sw.js must precache screens/{name}.js"


def test_icons_are_real_pngs():
    for name in ("icon-192.png", "icon-512.png"):
        data = (CLIENT / "icons" / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{name} is not a PNG"
        assert len(data) > 100, f"{name} suspiciously small"


def test_every_screen_exports_render():
    for name in SCREENS:
        source = (CLIENT / "js" / "screens" / f"{name}.js").read_text(encoding="utf-8")
        assert re.search(r"export\s+(async\s+)?function\s+render\b", source), (
            f"screens/{name}.js must export render()"
        )


def test_player_owns_audio_and_transcript_sync_is_measured():
    player_src = (CLIENT / "js" / "player.js").read_text(encoding="utf-8")
    assert "new Audio()" in player_src
    assert "start_ms" in player_src
    transcript_src = (CLIENT / "js" / "screens" / "transcript.js").read_text(encoding="utf-8")
    assert "start_ms" in transcript_src
    assert "estimate" not in transcript_src.lower() or "never by estimation" in transcript_src


# ---------------------------------------------------------------------------
# serving
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    app = create_app(progress_db=tmp_path / "progress.sqlite")
    return TestClient(app)


def test_root_serves_the_shell(tmp_path):
    app = create_app(progress_db=tmp_path / "progress.sqlite")
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert 'js/main.js' in response.text
    assert response.headers["content-type"].startswith("text/html")


def test_manifest_mime_type(tmp_path):
    app = create_app(progress_db=tmp_path / "progress.sqlite")
    response = TestClient(app).get("/manifest.webmanifest")
    assert response.status_code == 200
    assert "manifest+json" in response.headers["content-type"]


def test_sw_js_served_as_javascript(tmp_path):
    app = create_app(progress_db=tmp_path / "progress.sqlite")
    response = TestClient(app).get("/sw.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_api_wins_over_static_mount(tmp_path):
    """The catalogue API must not be shadowed by the static mount at `/`."""
    app = create_app(progress_db=tmp_path / "progress.sqlite")
    client = TestClient(app)
    assert client.get("/api/lessons").status_code == 200
    assert client.get("/api/health").status_code == 200


def test_missing_asset_404s(tmp_path):
    app = create_app(progress_db=tmp_path / "progress.sqlite")
    assert TestClient(app).get("/js/definitely-not-there.js").status_code == 404


def test_icon_served_with_png_mime(tmp_path):
    app = create_app(progress_db=tmp_path / "progress.sqlite")
    response = TestClient(app).get("/icons/icon-192.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_brand_mark_is_in_both_persistent_chromes():
    """The helix mark must ride in the sidebar and the topbar, so every route
    shows it whether the sidebar is visible or the layout has collapsed."""
    html = (CLIENT / "index.html").read_text(encoding="utf-8")
    assert html.count('class="brand-mark') >= 2
    assert html.count('/assets/logo-mark.png') >= 2
    assert "Mannschaft" in html
    assert "brand-scan" in html


def test_brand_animation_is_defined_and_motion_safe():
    css = (CLIENT / "css" / "v6-shell.css").read_text(encoding="utf-8")
    assert "@keyframes brand-sweep" in css
    assert "@keyframes brand-breathe" in css
    assert "prefers-reduced-motion: reduce" in css
    assert ".brand-scan { display: none; }" in css
    assert 'filter: invert(1)' in css


def test_logo_assets_are_real_pngs():
    for name in ("assets/logo-mark.png", "assets/logo-badge.png",
                 "icons/apple-touch-icon.png", "icons/favicon-32.png"):
        data = (CLIENT / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{name} is not a PNG"
        assert len(data) > 500, f"{name} suspiciously small"


def test_service_worker_never_serves_a_stale_shell():
    """A cache-first navigation is how a rebrand ships and nobody sees it."""
    source = (CLIENT / "sw.js").read_text(encoding="utf-8")
    assert "request.mode === 'navigate'" in source
    assert "navigationFirst" in source
    assert "mannschaft-${VERSION}" in source
    assert "clients.matchAll({ type: 'window' })" in source


def test_registration_reloads_once_when_the_worker_changes():
    source = (CLIENT / "js" / "main.js").read_text(encoding="utf-8")
    assert "controllerchange" in source
    assert "updateViaCache: 'none'" in source
    assert "mannschaft-sw-reloaded" in source
