"""M6 — corpus stages A–C.

Load-bearing assertions:

* The teachability formula is deterministic and each component pulls in the
  documented direction (profanity lowers, a question raises, fillers lower).
* Stage A deduplicates a video seen in two playlists and survives one bad one.
* Stage B flattens json3 word timings and downgrades a video with no caption.
* Stage C segments at a sentence-final gap, respects the word/second bounds,
  and writes clips sorted by score with ``review="pending"``.
* ``suggest`` (CLI + server) filters on ``level_est`` and situation — the exact
  regression the old server stub had (it filtered on a nonexistent ``level``).

Every fetch is injected. These tests never touch YouTube.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from v5.contract import cli
from v5.corpus import captions, db, manifest, mine, score, suggest

# A small controlled band map so score tests do not depend on the real 552-word list.
BANDS = {
    "ich": "A1", "gehe": "A1", "zum": "A1", "bäcker": "A2", "brötchen": "A2",
    "und": "A1", "einen": "A1", "kaffee": "A2", "bitte": "A1", "danke": "A1",
    "arbeit": "A2", "kollege": "B1", "kompliziert": "C1", "scheiße": "B2",
}


def _words():
    """In-memory word rows (dicts) with a sentence-final gap for segmentation.

    Two ~60 s / 25-word exchanges separated by a 28 s gap, so both clear the
    realistic mining bounds (20–220 words, 30–90 s) and the gap is a valid
    sentence-final boundary.
    """
    rows = []
    idx = 0
    sentences = [
        ("Ich gehe zum Bäcker und kaufe Brötchen und einen Kaffee bitte danke "
         "Ich gehe zum Bäcker und kaufe Brötchen und einen Kaffee bitte danke .", 0),
        ("Ein Kollege von der Arbeit ist kompliziert und der Chef im Büro ist "
         "ein Kollege von der Arbeit ist kompliziert und der Chef im Büro ist ?", 90_000),
    ]
    for sent, base in sentences:
        toks = sent.split()
        for n, tok in enumerate(toks):
            step = 2400
            rows.append({
                "video_id": "v", "idx": idx,
                "start_ms": base + n * step, "end_ms": base + n * step + 500,
                "token": tok, "line_idx": 0,
            })
            idx += 1
    return rows


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "corpus.sqlite3")
    yield c
    c.close()


# --------------------------------------------------------------------------
# score (pure)
# --------------------------------------------------------------------------


def test_tokens_extract_lowercase_german_words():
    assert score.tokens("Ich gehe zum Bäcker!") == ["ich", "gehe", "zum", "bäcker"]


def test_level_fit_counts_only_known_content_words_at_or_below_ceiling():
    # "kompliziert" is C1 -> out of an A2 target; "ich/und" are A1 -> in.
    fit = score.level_fit("Ich und der komplizierte Kollege", "A2", bands=BANDS)
    # scoreable: ich(A1 ✓), und(A1 ✓), kollege(B1 ✗) -> 2/3
    assert fit == pytest.approx(2 / 3)


def test_completeness_needs_both_a_capital_start_and_a_sentence_end():
    assert score.completeness("Ich gehe.") == 1.0
    assert score.completeness("ich gehe.") == 0.5
    assert score.completeness("Ich gehe") == 0.5


def test_question_present_detects_mark_or_interrogative():
    assert score.question_present("Was machst du?") == 1.0
    assert score.question_present("Wie geht es") == 1.0
    assert score.question_present("Ich gehe heim.") == 0.0


def test_detect_situation_uses_the_configured_keyword_map():
    label, conf = score.detect_situation("Ich kaufe Brötchen beim Bäcker.")
    assert label == "bakery"
    assert conf > 0


def test_speech_rate_fit_peaks_at_the_target_rate():
    # B1 target is 2.2 words/s; 22 words in 10 s is a perfect fit.
    assert score.speech_rate_fit(22, 10.0, "B1") == pytest.approx(1.0)
    assert score.speech_rate_fit(44, 10.0, "B1") == pytest.approx(0.0)


def test_low_filler_ratio_and_profanity_pull_in_opposite_directions():
    assert score.low_filler_ratio("Ich gehe zum Bäcker") == 1.0
    assert score.low_filler_ratio("Ich halt also gehe") < 1.0
    assert score.profanity_or_slur("Das ist Scheiße") == 1.0
    assert score.profanity_or_slur("Das ist schön") == 0.0


def test_teachability_is_deterministic_and_profanity_lowers_it():
    kwargs = dict(level="A2", word_count=10, seconds=5.0, bands=BANDS)
    clean = score.teachability("Ich gehe zum Bäcker und kaufe Brötchen", **kwargs)
    dirty = score.teachability("Ich gehe zum Bäcker und kaufe Scheiße", **kwargs)
    assert clean == score.teachability("Ich gehe zum Bäcker und kaufe Brötchen", **kwargs)
    assert dirty < clean


# --------------------------------------------------------------------------
# db (SQLite)
# --------------------------------------------------------------------------


def test_upsert_merges_playlists_instead_of_overwriting(conn):
    base = dict(title="t", channel="c", duration_s=10, upload_date="", level_tag="B1",
                has_de_caption=1, has_en_caption=0, caption_kind="auto", fetched_at=1.0)
    db.upsert_video(conn, {**base, "id": "v1", "playlists": json.dumps(["A"])})
    db.upsert_video(conn, {**base, "id": "v1", "playlists": json.dumps(["B"])})
    row = conn.execute("SELECT playlists FROM videos WHERE id='v1'").fetchone()
    assert json.loads(row["playlists"]) == ["A", "B"]
    assert db.video_count(conn) == 1  # still one video, deduplicated


def test_replace_words_is_idempotent(conn):
    rows = [{"video_id": "v", "idx": 0, "start_ms": 0, "end_ms": 100,
             "token": "hallo", "line_idx": 0}]
    db.replace_words(conn, "v", rows)
    db.replace_words(conn, "v", rows)
    assert db.word_count(conn) == 1


# --------------------------------------------------------------------------
# stage A — manifest
# --------------------------------------------------------------------------


def test_video_row_maps_a_flat_entry():
    row = manifest.video_row(
        {"id": "x", "title": "T", "duration": 90, "timestamp": 0,
         "automatic_captions": {"de": []}}, "PL1", "A2",
    )
    assert row["id"] == "x"
    assert row["level_tag"] == "A2"
    assert json.loads(row["playlists"]) == ["PL1"]
    assert row["has_de_caption"] == 1


def test_build_manifest_dedups_and_survives_one_bad_playlist(conn):
    def fake_fetch(url):
        if "BAD" in url:
            raise RuntimeError("boom")
        return {"entries": [{"id": "shared", "title": "S", "duration": 60}]}

    playlists = (
        ("GOOD1", "g1", "A2"), ("BAD", "bad", "B1"), ("GOOD2", "g2", "B1"),
    )
    stats = manifest.build_manifest(conn, playlists=playlists, fetch=fake_fetch)
    assert stats["videos_after"] == 1  # "shared" seen twice, stored once
    assert len(stats["errors"]) == 1  # bad playlist recorded, not fatal
    row = conn.execute("SELECT playlists FROM videos WHERE id='shared'").fetchone()
    assert json.loads(row["playlists"]) == ["GOOD1", "GOOD2"]


# --------------------------------------------------------------------------
# stage B — captions
# --------------------------------------------------------------------------


def test_parse_json3_flattens_events_to_word_rows():
    doc = {"events": [
        {"tStartMs": 1000, "dDurationMs": 1000, "segs": [{"utf8": "Ich gehe"}]},
        {"tStartMs": 2000, "dDurationMs": 500, "segs": [{"utf8": "heim"}]},
    ]}
    words = captions.parse_json3(doc, "v1")
    assert [w["token"] for w in words] == ["Ich", "gehe", "heim"]
    assert words[0]["start_ms"] == 1000 and words[0]["end_ms"] == 1500
    assert words[1]["start_ms"] == 1500 and words[2]["line_idx"] == 1


def test_build_words_downgrades_a_video_with_no_caption(tmp_path, conn):
    db.upsert_video(conn, dict(
        id="nocap", title="t", channel="c", duration_s=10, upload_date="", level_tag="B1",
        playlists=json.dumps(["P"]), has_de_caption=1, has_en_caption=0,
        caption_kind="auto", fetched_at=1.0,
    ))
    stats = captions.build_words(conn, video_ids=["nocap"], cache_dir=tmp_path,
                                 fetch=lambda _vid, _dir: None)
    assert stats["failed"] == 1
    row = conn.execute("SELECT has_de_caption FROM videos WHERE id='nocap'").fetchone()
    assert row["has_de_caption"] == 0


# --------------------------------------------------------------------------
# stage C — mining
# --------------------------------------------------------------------------


def test_segment_words_only_breaks_at_a_sentence_final_gap():
    words = _words()
    # Convert to sqlite-like Rows via a real in-memory table for faithful access.
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE w (idx INT, start_ms INT, end_ms INT, token TEXT, line_idx INT)")
    c.executemany("INSERT INTO w VALUES (:idx,:start_ms,:end_ms,:token,:line_idx)", words)
    rows = c.execute("SELECT * FROM w ORDER BY idx").fetchall()
    groups = mine.segment_words(rows, gap_ms=700)
    assert len(groups) == 2  # the 39.5 s gap after " . " is a boundary
    assert groups[0][-1]["token"] == "."


def test_clip_from_group_respects_bounds_and_marks_review_pending():
    # 20 words over ~31 s -> inside 8–40 words / 30–90 s. Use an A1-friendly
    # text so level_fit clears the 0.25 floor.
    group = [
        {"start_ms": n * 1600, "end_ms": n * 1600 + 400, "token": t}
        for n, t in enumerate(["Ich", "und", "gehe", "zum", "Bäcker"] * 4)
    ]
    clip = mine.clip_from_group(
        group, "vid", level="A2", min_words=8, max_words=40,
        min_seconds=30.0, max_seconds=90.0, bands=BANDS,
    )
    assert clip is not None
    assert clip["level_est"] == "A2"
    assert clip["review"] == "pending"
    assert clip["word_count"] == 20
    assert "grammar_exhibits" in clip

    too_short = mine.clip_from_group(
        group[:3], "vid", level="A2", min_words=8, max_words=40,
        min_seconds=0, max_seconds=90, bands=BANDS,
    )
    assert too_short is None


def test_mine_writes_clips_sorted_by_score(conn, tmp_path):
    # Seed a video with a word stream and enough vocabulary to clear the floor.
    db.upsert_video(conn, dict(
        id="v", title="t", channel="c", duration_s=90, upload_date="", level_tag="A2",
        playlists=json.dumps(["P"]), has_de_caption=1, has_en_caption=0,
        caption_kind="auto", fetched_at=1.0,
    ))
    db.replace_words(conn, "v", _words())
    out = tmp_path / "clips.jsonl"
    stats = mine.mine(conn, out_path=out, bands=BANDS)
    clips = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert stats["clips"] == len(clips)
    assert clips == sorted(clips, key=lambda c: -c["score"])
    assert all(c["review"] == "pending" for c in clips)


# --------------------------------------------------------------------------
# suggest (shared by CLI + server)
# --------------------------------------------------------------------------


def _clip(level, situation, score_value):
    return {"clip_id": f"eg:x:{score_value}", "level_est": level,
            "score": score_value, "situation": situation,
            "text_de": "Ich gehe zum Bäcker.", "review": "pending"}


def test_suggest_filters_on_level_est_and_situation(tmp_path):
    path = tmp_path / "clips.jsonl"
    path.write_text("\n".join(json.dumps(c) for c in [
        _clip("A2", "bakery", 4.0),
        _clip("B1", "work", 3.5),
        _clip("B1", "work", 3.0),
        _clip("B1", "transport", 2.5),
    ]), encoding="utf-8")
    got = suggest.suggest(path, level="B1", situation="work", limit=10)
    assert [c["score"] for c in got] == [3.5, 3.0]
    assert suggest.suggest(path, level="A1") == []
    assert len(suggest.suggest(path, level="B1", limit=1)) == 1


def test_load_clips_skips_malformed_lines(tmp_path):
    path = tmp_path / "clips.jsonl"
    path.write_text('{"clip_id":"ok"}\nnot json\n\n', encoding="utf-8")
    assert suggest.load_clips(path) == [{"clip_id": "ok"}]


def test_cli_suggest_reads_real_candidates(monkeypatch):
    data = [_clip("B1", "work", 4.0), _clip("B1", "work", 3.0)]
    monkeypatch.setattr("v5.corpus.suggest.suggest", lambda **kw: data[: kw.get("limit", 10)])
    assert cli.main(["corpus", "suggest", "--level", "B1", "--situation", "work"]) == 0


def test_cli_suggest_exits_1_when_nothing_matches(monkeypatch):
    monkeypatch.setattr("v5.corpus.suggest.suggest", lambda **kw: [])
    assert cli.main(["corpus", "suggest", "--level", "C2"]) == 1


def test_server_corpus_endpoint_returns_real_candidates(tmp_path):
    from fastapi.testclient import TestClient

    from v5.server import create_app

    path = tmp_path / "clips.jsonl"
    path.write_text("\n".join(json.dumps(c) for c in [
        _clip("B1", "work", 4.0),
        _clip("B1", "work", 3.0),
        _clip("A2", "bakery", 2.0),
    ]), encoding="utf-8")
    app = create_app(corpus_path=path)
    body = TestClient(app).get("/api/corpus/suggest?level=B1&situation=work").json()
    assert body["count"] == 2
    assert "reason" not in body
    assert all(c["level_est"] == "B1" and c["situation"] == "work"
               for c in body["candidates"])
