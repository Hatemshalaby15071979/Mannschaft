"""Build ``content/dictionary/seed.json`` from the lessons' own glossaries.

De-duplication key: the German headword, case-folded and stripped. The first
lesson to use a word owns ``source_lesson``; every lesson that uses it is kept
in ``sources`` so the attribution is complete rather than merely present.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from ..config import ROOT
from .schema import DictionarySeed, SeedEntry

LESSONS_DIR = ROOT / "content" / "lessons"
SEED_PATH = ROOT / "content" / "dictionary" / "seed.json"


def _key(word: str) -> str:
    return " ".join(word.strip().lower().split())


def build_seed(lessons_dir: Path = LESSONS_DIR, *, today: str | None = None) -> DictionarySeed:
    entries: dict[str, SeedEntry] = {}
    for path in sorted(lessons_dir.glob("*.lesson.json")):
        lesson = json.loads(path.read_text(encoding="utf-8"))
        lesson_id = lesson["id"]
        for raw in lesson.get("glossary") or []:
            key = _key(raw.get("de") or "")
            if not key:
                continue
            if key in entries:
                if lesson_id not in entries[key].sources:
                    entries[key].sources.append(lesson_id)
                continue
            entries[key] = SeedEntry(
                de=raw["de"].strip(),
                en=raw.get("en", "").strip(),
                pos=(raw.get("pos") or "").strip(),
                note_de=raw.get("note_de"),
                note_en=raw.get("note_en"),
                example_de=raw.get("example_de"),
                example_en=raw.get("example_en"),
                plural=raw.get("plural"),
                article=raw.get("article"),
                source_lesson=lesson_id,
                sources=[lesson_id],
            )
    ordered = sorted(entries.values(), key=lambda entry: (entry.de.casefold(), entry.de))
    return DictionarySeed(
        version=1,
        generated=today or date.today().isoformat(),
        count=len(ordered),
        entries=ordered,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v5.dictionary.seed")
    parser.add_argument("--lessons-dir", type=Path, default=LESSONS_DIR)
    parser.add_argument("--out", type=Path, default=SEED_PATH)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    seed = build_seed(args.lessons_dir, today=date.today().isoformat())
    text = json.dumps(seed.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"

    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else None
        if current is None:
            print(f"{args.out} does not exist", file=sys.stderr)
            return 1
        if json.loads(current).get("entries") != json.loads(text).get("entries"):
            print("dictionary seed is stale — rerun python -m v5.dictionary.seed", file=sys.stderr)
            return 1
        print("dictionary seed is current")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"{seed.count} entries → {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
