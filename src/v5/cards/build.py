"""Generate ``content/cards/<lesson>.json`` from existing lesson material.

Kinds and sources (V6 plan §3.2):

* ``recall``  — a segment's DE text → its own EN translation.
* ``cloze``   — a glossary word blanked inside a sentence that already uses it.
* ``order``   — a short sentence split into tokens and shuffled.
* ``produce`` — the lesson's own ``can_do`` prompt.

Every card carries the segment it came from (except ``produce``), so the audio
URL is always a real per-line render. The generator is deterministic: the same
lesson always produces the same deck, including the ``order`` shuffles.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path

from ..config import ROOT
from .schema import Card, CardDeck

LESSONS_DIR = ROOT / "content" / "lessons"
CARDS_DIR = ROOT / "content" / "cards"

SPEECH_TYPES = ("line", "echo", "drill", "scene", "note")
MIN_CARDS = 8
MAX_CARDS = 12
RECALL_CAP = 4
CLOZE_CAP = 3
ORDER_CAP = 2


def _words(text: str) -> list[str]:
    return text.split()


def _audio(lesson_id: str, segment_id: str) -> str:
    return f"/api/audio/{lesson_id}/lines/{segment_id}"


def _shuffled(tokens: list[str], seed: str) -> list[str]:
    rnd = random.Random(hashlib.sha256(seed.encode("utf-8")).hexdigest())
    out = list(tokens)
    rnd.shuffle(out)
    if out == tokens and len(out) > 1:
        out = out[1:] + out[:1]
    return out


def _candidates(lesson: dict) -> list[dict]:
    out = []
    for segment in lesson.get("segments", []):
        if segment.get("type") not in SPEECH_TYPES:
            continue
        text = (segment.get("text") or "").strip()
        translation = (segment.get("translation") or "").strip()
        if not text or not translation:
            continue
        out.append(segment)
    return out


def _hint(segment: dict, glossary_by_id: dict) -> str | None:
    for ref in segment.get("gloss") or []:
        entry = glossary_by_id.get(ref)
        if entry:
            return entry.get("note_en") or entry.get("note_de")
    return None


def _cloze_prompts(lesson: dict, segments: list[dict]) -> list[Card]:
    glossary = lesson.get("glossary") or []
    cards: list[Card] = []
    for entry in glossary:
        word = (entry.get("de") or "").strip()
        if len(word) < 3:
            continue
        pattern = re.compile(r"(?<!\w)" + re.escape(word) + r"(?!\w)", re.IGNORECASE)
        # Prefer a sentence that explicitly glosses this word, then the first
        # sentence that uses it. The blank must leave a real sentence behind —
        # "___!" teaches nothing.
        explicit = [s for s in segments if entry["id"] in (s.get("gloss") or [])]
        ordered = explicit + [s for s in segments if s not in explicit]
        for segment in ordered:
            text = segment["text"].strip()
            if not pattern.search(text):
                continue
            remainder = pattern.sub("", text, count=1)
            if len(_words(remainder)) < 2:
                continue
            prompt = pattern.sub("___", text, count=1)
            if "___" not in prompt or prompt == text:
                continue
            cards.append(
                Card(
                    id="pending",
                    kind="cloze",
                    segment_id=segment["id"],
                    prompt_de=prompt,
                    answer_de=word,
                    audio=_audio(lesson["id"], segment["id"]),
                )
            )
            break
    return cards


TYPE_PRIORITY = {"line": 0, "echo": 1, "drill": 2, "scene": 3}


def build_deck(lesson: dict) -> CardDeck:
    lesson_id = lesson["id"]
    glossary_by_id = {entry["id"]: entry for entry in lesson.get("glossary") or []}
    segments = _candidates(lesson)

    recall: list[Card] = []
    seen_recall: set[str] = set()
    for segment in sorted(segments, key=lambda s: (TYPE_PRIORITY.get(s["type"], 9), s["id"])):
        if segment["type"] not in ("line", "echo", "drill", "scene"):
            continue
        if not 3 <= len(_words(segment["text"])) <= 12:
            continue
        prompt = segment["text"].strip()
        if prompt in seen_recall:
            continue
        seen_recall.add(prompt)
        recall.append(
            Card(
                id="pending",
                kind="recall",
                segment_id=segment["id"],
                prompt_de=prompt,
                answer_en=segment["translation"].strip(),
                hint=_hint(segment, glossary_by_id),
                audio=_audio(lesson_id, segment["id"]),
            )
        )

    cloze: list[Card] = []
    seen_cloze: set[str] = set()
    for card in _cloze_prompts(lesson, segments):
        if card.prompt_de in seen_cloze:
            continue
        seen_cloze.add(card.prompt_de)
        cloze.append(card)

    order: list[Card] = []
    seen_order: set[str] = set()
    for segment in sorted(segments, key=lambda s: (len(_words(s["text"])), s["id"])):
        if segment["type"] not in ("line", "echo", "drill"):
            continue
        tokens = _words(segment["text"].strip())
        if not 3 <= len(tokens) <= 8:
            continue
        text = segment["text"].strip()
        if text in seen_order:
            continue
        seen_order.add(text)
        order.append(
            Card(
                id="pending",
                kind="order",
                segment_id=segment["id"],
                tokens=_shuffled(tokens, f"{lesson_id}:{segment['id']}"),
                answer=text,
                audio=_audio(lesson_id, segment["id"]),
            )
        )
        if len(order) >= ORDER_CAP:
            break

    chosen: list[Card] = []
    chosen.extend(recall[:RECALL_CAP])
    chosen.extend(cloze[:CLOZE_CAP])
    chosen.extend(order[:ORDER_CAP])

    # Top up only when a deck would fall under the floor — never inventing content.
    if len(chosen) < MIN_CARDS:
        for extra in (recall[RECALL_CAP:], order[ORDER_CAP:], cloze[CLOZE_CAP:]):
            for card in extra:
                if len(chosen) >= MIN_CARDS:
                    break
                chosen.append(card)

    # Interleave kinds so the deck does not run in blocks; produce goes last.
    buckets: dict[str, list[Card]] = {"recall": [], "cloze": [], "order": []}
    for card in chosen:
        buckets[card.kind].append(card)
    ordered: list[Card] = []
    while any(buckets.values()):
        for kind in ("recall", "cloze", "order"):
            if buckets[kind]:
                ordered.append(buckets[kind].pop(0))

    scene = lesson.get("scene") or {}
    can_do_de = (scene.get("can_do_de") or "").strip()
    can_do_en = (scene.get("can_do_en") or "").strip()
    if can_do_de and can_do_en:
        ordered.append(
            Card(
                id="pending",
                kind="produce",
                can_do_en=can_do_en,
                can_do_de=can_do_de,
                answer_de=can_do_de,
                source="scene.can_do_de",
            )
        )

    if len(ordered) > MAX_CARDS:
        ordered = ordered[: MAX_CARDS - 1] + [ordered[-1]]

    for index, card in enumerate(ordered, start=1):
        card.id = f"c{index:03d}"

    return CardDeck(lesson=lesson_id, version=1, cards=ordered)


def build_all(
    *,
    lessons_dir: Path = LESSONS_DIR,
    out_dir: Path = CARDS_DIR,
    check: bool = False,
) -> int:
    stale = 0
    written = 0
    for path in sorted(lessons_dir.glob("*.lesson.json")):
        lesson = json.loads(path.read_text(encoding="utf-8"))
        deck = build_deck(lesson)
        target = out_dir / f"{deck.lesson}.json"
        text = json.dumps(deck.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        if check:
            current = target.read_text(encoding="utf-8") if target.exists() else None
            if current != text:
                print(f"stale: {target}", file=sys.stderr)
                stale += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written += 1
        print(f"{deck.lesson}: {len(deck.cards)} cards")
    if check:
        if stale:
            return 1
        print("card decks are current")
        return 0
    print(f"{written} deck(s) written to {out_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v5.cards.build")
    parser.add_argument("--lessons-dir", type=Path, default=LESSONS_DIR)
    parser.add_argument("--out", type=Path, default=CARDS_DIR)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    return build_all(lessons_dir=args.lessons_dir, out_dir=args.out, check=args.check)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
