"""V6 — media wiring, sentence cards, dictionary, journey, guardrails.

These tests assert the parts that can fail: determinism, referential integrity,
honest fallbacks, additive progress events, the legacy hash guard, and the
design-leak grep. They read the real authored content; nothing is written.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from v5.cards.build import build_deck
from v5.cards.schema import CardDeck
from v5.config import ROOT
from v5.dictionary.lookup import lookup
from v5.dictionary.schema import DictionarySeed
from v5.dictionary.seed import build_seed
from v5.media.manifest import MediaManifest
from v5.media.select import (
    LEVEL_INDEX,
    build_manifest,
    load_clips,
    select_for_lesson,
)
from v5.server import create_app

CONTENT = ROOT / "content"
LESSONS = sorted((CONTENT / "lessons").glob("*.lesson.json"))
LESSON_IDS = [path.name.removesuffix(".lesson.json") for path in LESSONS]
CLIENT = ROOT / "src" / "v5" / "client"


def _lesson(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def lessons() -> list[dict]:
    return [_lesson(path) for path in LESSONS]


@pytest.fixture(scope="module")
def clips() -> list[dict]:
    return load_clips()


@pytest.fixture(scope="module")
def manifest() -> MediaManifest:
    return build_manifest()


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(progress_db=tmp_path / "progress.sqlite"))


# ---------------------------------------------------------------------------
# media selector
# ---------------------------------------------------------------------------


def test_selector_is_deterministic(lessons, clips):
    first = build_manifest()
    second = build_manifest()
    assert first.model_dump() == second.model_dump()


def test_manifest_on_disk_is_current(manifest):
    stored = json.loads((CONTENT / "lesson_media.json").read_text(encoding="utf-8"))
    fresh = json.loads(manifest.model_dump_json())
    stored.pop("generated", None)
    fresh.pop("generated", None)
    assert stored == fresh, "lesson_media.json is stale — run python -m v5.media.select"


def test_empty_corpus_falls_back_honestly():
    lesson = {"id": "X-1", "level": "B1", "scene": {"situation_tags": [], "grammar_focus": []}}
    media = select_for_lesson(lesson, [])
    assert media.primary is None
    assert media.alternates == []
    assert media.fallback == "rendered_audio"


def test_tie_breaks_by_clip_id():
    lesson = {"id": "X-1", "level": "B1", "scene": {"situation_tags": [], "grammar_focus": []}}
    base = {"video_id": "v", "start_s": 1.0, "end_s": 2.0, "score": 4.0, "level_est": "B1"}
    clip_b = {**base, "clip_id": "b"}
    clip_a = {**base, "clip_id": "a"}
    media = select_for_lesson(lesson, [clip_b, clip_a])
    assert media.primary is not None
    assert media.primary.clip_id == "a"


def test_level_gap_is_recorded_not_hidden(lessons, clips, manifest):
    by_id = {clip["clip_id"]: clip for clip in clips}
    for lesson in lessons:
        media = manifest.lessons[lesson["id"]]
        if media.primary is None:
            assert media.fallback == "rendered_audio"
            continue
        clip = by_id[media.primary.clip_id]
        expected = abs(LEVEL_INDEX[clip["level_est"]] - LEVEL_INDEX[lesson["level"]])
        assert media.relevance.level_gap == expected
        if expected > 0:
            assert "Abstand" in media.primary.reason


def test_every_lesson_has_a_media_entry(manifest):
    assert set(manifest.lessons) == set(LESSON_IDS)


# ---------------------------------------------------------------------------
# cards
# ---------------------------------------------------------------------------


def test_card_decks_are_current():
    for path in LESSONS:
        lesson = _lesson(path)
        deck = build_deck(lesson)
        stored = json.loads((CONTENT / "cards" / f"{lesson['id']}.json").read_text(encoding="utf-8"))
        assert stored == json.loads(deck.model_dump_json()), f"stale deck for {lesson['id']}"


def test_card_count_and_kinds(lessons):
    for lesson in lessons:
        deck = build_deck(lesson)
        assert 8 <= len(deck.cards) <= 12, f"{lesson['id']} has {len(deck.cards)} cards"
        kinds = {card.kind for card in deck.cards}
        assert {"recall", "cloze", "order", "produce"} <= kinds


def test_card_segment_refs_exist(lessons):
    for lesson in lessons:
        ids = {segment["id"] for segment in lesson["segments"]}
        deck = build_deck(lesson)
        for card in deck.cards:
            if card.segment_id is not None:
                assert card.segment_id in ids, f"{lesson['id']} card {card.id} orphan segment"
                assert card.audio == f"/api/audio/{lesson['id']}/lines/{card.segment_id}"


def test_card_ids_are_unique(lessons):
    for lesson in lessons:
        deck = build_deck(lesson)
        ids = [card.id for card in deck.cards]
        assert len(ids) == len(set(ids))


def test_card_deck_contract_round_trips(lessons):
    for lesson in lessons:
        deck = build_deck(lesson)
        CardDeck.model_validate_json(deck.model_dump_json())


def test_order_cards_are_shuffled(lessons):
    for lesson in lessons:
        for card in build_deck(lesson).cards:
            if card.kind == "order":
                assert " ".join(card.tokens) != card.answer


# ---------------------------------------------------------------------------
# dictionary
# ---------------------------------------------------------------------------


def test_seed_is_deduplicated_and_attributed():
    seed = build_seed()
    assert seed.count >= 100
    keys = [entry.de.casefold() for entry in seed.entries]
    assert len(keys) == len(set(keys))
    assert set(LESSON_IDS) >= {entry.source_lesson for entry in seed.entries}
    for entry in seed.entries:
        assert entry.source_lesson in entry.sources


def test_seed_on_disk_is_current():
    seed = build_seed()
    stored = json.loads((CONTENT / "dictionary" / "seed.json").read_text(encoding="utf-8"))
    assert stored["entries"] == json.loads(seed.model_dump_json())["entries"]


def test_on_disk_json_validates_against_its_schema():
    """Every generated JSON file must load through its strict model.

    The schemas live beside their generators rather than in the frozen
    ``src/v5/contract/`` package: V6's guardrail freezes that directory, so
    adding files there would break the no-deletion hash gate. The models still
    use ``extra="forbid"`` and are the single documented contract.
    """
    MediaManifest.model_validate_json(
        (CONTENT / "lesson_media.json").read_text(encoding="utf-8")
    )
    DictionarySeed.model_validate_json(
        (CONTENT / "dictionary" / "seed.json").read_text(encoding="utf-8")
    )
    for lesson_id in LESSON_IDS:
        CardDeck.model_validate_json(
            (CONTENT / "cards" / f"{lesson_id}.json").read_text(encoding="utf-8")
        )
    overrides = json.loads(
        (CONTENT / "lesson_media.overrides.json").read_text(encoding="utf-8")
    )
    assert overrides["version"] == 1
    assert set(overrides["lessons"]) <= set(LESSON_IDS)


def test_lookup_prefers_exact_and_returns_links():
    result = lookup("ich bin")
    assert result["local"]
    assert result["local"][0]["de"] == "ich bin"
    labels = {link["label"] for link in result["links"]}
    assert {"DWDS", "Wiktionary", "Cambridge", "Collins"} <= labels
    assert all(link["url"].startswith("https://") for link in result["links"])


def test_lookup_unknown_word_keeps_outbound_links():
    result = lookup("flurbelwort")
    assert result["local"] == []
    assert result["links"]


def test_lookup_does_not_match_noise_substrings():
    """'tag' must find Tag/Werktag, not 'advantage' or 'stagnieren'."""
    words = [entry["de"].casefold() for entry in lookup("tag")["local"]]
    assert "guten tag" in words
    assert "der werktag" in words
    assert "der vorteil" not in words
    assert "stagnieren" not in words


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


def test_media_route_for_every_lesson(client):
    for lesson_id in LESSON_IDS:
        response = client.get(f"/api/media/{lesson_id}")
        assert response.status_code == 200, lesson_id
        body = response.json()
        assert body["lesson_id"] == lesson_id
        if body["primary"]:
            assert body["embed_url"].startswith("https://www.youtube-nocookie.com/embed/")
            assert "start=" in body["embed_url"] and "end=" in body["embed_url"]
            assert "rel=0" in body["embed_url"]
        else:
            assert body["fallback"] == "rendered_audio"


def test_media_route_unknown_lesson_is_404(client):
    assert client.get("/api/media/ZZ-99").status_code == 404


def test_cards_route_for_every_lesson(client):
    for lesson_id in LESSON_IDS:
        response = client.get(f"/api/cards/{lesson_id}")
        assert response.status_code == 200, lesson_id
        assert 8 <= len(response.json()["cards"]) <= 12


def test_cards_route_unknown_lesson_is_404(client):
    assert client.get("/api/cards/ZZ-99").status_code == 404


def test_dictionary_route(client):
    body = client.get("/api/dict", params={"q": "hallo"}).json()
    assert body["local"][0]["de"] == "hallo"
    assert body["count"] >= 100
    empty = client.get("/api/dict", params={"q": "zzzz"}).json()
    assert empty["local"] == []
    assert empty["links"]


def test_context_route_matches_the_deck_and_media(client, manifest):
    for lesson_id in LESSON_IDS:
        response = client.get(f"/api/lesson/{lesson_id}/context")
        assert response.status_code == 200, lesson_id
        body = response.json()
        deck = json.loads((CONTENT / "cards" / f"{lesson_id}.json").read_text(encoding="utf-8"))
        assert body["cards"]["count"] == len(deck["cards"])
        assert body["media"]["has_clip"] == (manifest.lessons[lesson_id].primary is not None)
        assert body["level"] == lesson_id[:2]
        assert body["can_do"]["de"]


def test_context_route_unknown_lesson_is_404(client):
    assert client.get("/api/lesson/ZZ-99/context").status_code == 404


# ---------------------------------------------------------------------------
# additive progress events
# ---------------------------------------------------------------------------


def test_card_graded_event_is_recorded_without_a_segment(client):
    response = client.post(
        "/api/progress",
        json={
            "lesson_id": "A1-01",
            "event": "card_graded",
            "detail": {"card_id": "c010", "kind": "produce", "grade": "good"},
        },
    )
    assert response.status_code == 200
    assert response.json()["event"]["kind"] == "card_graded"
    body = client.get("/api/progress").json()
    assert body["events"][0]["detail"]["card_id"] == "c010"
    assert body["event_counts"]["card_graded"] == 1


def test_clip_opened_event_and_plain_progress_coexist(client):
    client.post(
        "/api/progress",
        json={"lesson_id": "A1-01", "event": "clip_opened", "detail": {"clip_id": "x"}},
    )
    client.post("/api/progress", json={"lesson_id": "A1-01", "seg_id": "s001", "position_ms": 1200})
    body = client.get("/api/progress").json()
    assert body["resume"]["seg_id"] == "s001"
    assert body["event_counts"] == {"clip_opened": 1}
    assert {"resume", "lessons", "events", "event_counts"} <= set(body)


def test_unknown_event_is_422(client):
    response = client.post(
        "/api/progress", json={"lesson_id": "A1-01", "event": "not_a_real_event"}
    )
    assert response.status_code == 422


def test_plain_progress_still_requires_a_segment(client):
    response = client.post("/api/progress", json={"lesson_id": "A1-01", "position_ms": 10})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# client + guardrails
# ---------------------------------------------------------------------------


def test_index_links_the_shell_stylesheets():
    html = (CLIENT / "index.html").read_text(encoding="utf-8")
    assert "/css/v6-shell.css" in html
    assert "/css/v6.css" in html
    # Specimen is dealt light-first; dark is a derived variant, not the default.
    assert "/css/specimen.css" in html
    assert re.search(r'data-theme="(light|dark)"', html)
    assert "side-index" in html

    specimen = (CLIENT / "css" / "specimen.css").read_text(encoding="utf-8")
    assert '@import url("./tokens.css")' in specimen
    assert '@import url("./base.css")' in specimen


def test_service_worker_precaches_v6_and_excludes_youtube():
    source = (CLIENT / "sw.js").read_text(encoding="utf-8")
    for name in ("clip", "cards", "dictionary"):
        assert f"/js/screens/{name}.js" in source
    for asset in ("/css/v6-shell.css", "/css/specimen.css", "/assets/fonts/bodoni.woff2"):
        assert asset in source
    assert "youtube-nocookie" in source
    assert "VIDEO_ORIGINS" in source


def test_new_screens_export_render():
    for name in ("clip", "cards", "dictionary"):
        source = (CLIENT / "js" / "screens" / f"{name}.js").read_text(encoding="utf-8")
        assert re.search(r"export\s+async\s+function\s+render\b", source)


def test_no_design_content_leaks():
    """The matrix is a visual reference; none of its content may appear here."""
    forbidden = re.compile(
        r"n8n|WFM|Hatemshalaby|Operations___|github\.com/Hatemshalaby|Sami\b",
        re.IGNORECASE,
    )
    roots = [CLIENT, CONTENT / "lessons", CONTENT / "cards", CONTENT / "dictionary"]
    offenders = []
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".js", ".css", ".html", ".json", ".md"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if forbidden.search(text):
                offenders.append(str(path))
    assert offenders == [], f"design/content leak in: {offenders}"


def test_health_reports_corpus_and_lesson_counts(client):
    body = client.get("/api/health").json()
    assert body["lessons"]["total"] == len(LESSON_IDS)
    assert body["corpus"]["clips"] >= 700


def test_requests_are_logged_with_timestamp_route_and_status(client):
    messages: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    logger = logging.getLogger("v5.http")
    handler = Capture()
    logger.addHandler(handler)
    try:
        client.get("/api/health")
    finally:
        logger.removeHandler(handler)

    assert any(
        "ts=" in message
        and "route=/api/health" in message
        and "status=200" in message
        and "method=GET" in message
        for message in messages
    ), f"no structured request log: {messages}"


def test_shell_files_are_served_no_cache(client):
    """index/sw/manifest must revalidate so a new build is actually seen."""
    for path in ("/", "/sw.js", "/manifest.webmanifest"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers.get("cache-control") == "no-cache", path
