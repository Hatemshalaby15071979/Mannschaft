"""Choose one corpus clip per lesson.

Scoring rule (V6 plan §3.1):

    score = clip.score
            − LEVEL_PENALTY × |clip level − lesson level|
            + SITUATION_BONUS when a canonical situation matches
            + GRAMMAR_BONUS × |grammar_focus ∩ clip.grammar_exhibits|

Deterministic: ties break by ``clip_id`` ascending, so two runs over the same
corpus always produce the same file. A clip only wins above ``THRESHOLD``;
below it the lesson gets ``primary: null`` and the rendered-audio fallback.

The corpus in this repository has **no** populated ``grammar_exhibits`` (all
790 clips are empty), so the grammar term contributes 0 today. It stays in the
formula so a later corpus rebuild benefits without touching this file.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from ..config import ROOT
from .manifest import (
    MANIFEST_NAME,
    OVERRIDES_NAME,
    LessonMedia,
    MediaManifest,
    MediaPick,
    Relevance,
    load_overrides,
    merge_overrides,
    write_manifest,
)

LESSONS_DIR = ROOT / "content" / "lessons"
CORPUS_PATH = ROOT / "content" / "corpus" / "clips.jsonl"
CONTENT_DIR = ROOT / "content"

LEVEL_INDEX = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}

LEVEL_PENALTY = 1.5
SITUATION_BONUS = 0.75
GRAMMAR_BONUS = 0.25
THRESHOLD = 2.6
MAX_ALTERNATES = 2

# Lesson tags are authored for the scene; the corpus labels come from Easy
# German's own situations. This table is the documented bridge between them.
# A tag may map to several corpus labels; any overlap counts as a match.
SITUATION_ALIASES: dict[str, tuple[str, ...]] = {
    "first-day": ("school",),
    "introductions": ("school",),
    "small-talk": ("school", "work", "leisure"),
    "café": ("food",),
    "food": ("food", "bakery"),
    "service": ("food", "shopping", "housing"),
    "numbers": (),
    "bureaucracy": ("housing", "work"),
    "registration": ("housing",),
    "housing": ("housing",),
    "work": ("work",),
    "meetings": ("work",),
    "planning": ("work",),
    "application": ("work",),
    "interview": ("work",),
    "negotiation": ("work",),
    "salary": ("work",),
    "strategy": ("work",),
    "suppliers": ("work",),
    "culture": ("leisure",),
    "literature": ("leisure",),
    "conversation": ("leisure",),
    "atmosphere": ("leisure",),
}


def load_clips(path: Path = CORPUS_PATH) -> list[dict]:
    if not path.exists():
        return []
    clips = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                clips.append(json.loads(line))
    return clips


def load_lessons(lessons_dir: Path = LESSONS_DIR) -> list[dict]:
    lessons = []
    for path in sorted(lessons_dir.glob("*.lesson.json")):
        lessons.append(json.loads(path.read_text(encoding="utf-8")))
    return lessons


def canonical_situations(tags: list[str]) -> set[str]:
    out: set[str] = set()
    for tag in tags:
        out.update(SITUATION_ALIASES.get(tag.strip().lower(), ()))
    return out


def score_clip(
    clip: dict,
    *,
    level: str,
    tags: list[str],
    grammar_focus: list[str],
) -> dict:
    """Return the total and its parts. Pure function, no I/O."""
    clip_level = clip.get("level_est") or level
    gap = abs(LEVEL_INDEX.get(clip_level, LEVEL_INDEX[level]) - LEVEL_INDEX[level])

    wanted = canonical_situations(tags)
    situation = (clip.get("situation") or "").strip().lower()
    situation_match = bool(situation) and situation in wanted

    exhibits = {str(item).lower() for item in (clip.get("grammar_exhibits") or [])}
    focus = {str(item).lower() for item in grammar_focus}
    overlap = len(exhibits & focus)

    total = (
        float(clip.get("score") or 0.0)
        - LEVEL_PENALTY * gap
        + (SITUATION_BONUS if situation_match else 0.0)
        + GRAMMAR_BONUS * overlap
    )
    return {
        "total": round(total, 6),
        "level_gap": gap,
        "situation_match": situation_match,
        "grammar_overlap": overlap,
        "clip_level": clip_level,
        "situation": situation,
    }


def _pick(clip: dict, parts: dict, lesson_level: str) -> MediaPick:
    gap = parts["level_gap"]
    if gap == 0 and parts["situation_match"]:
        reason = f"Gleiches Niveau; Situation passt ({parts['situation']})."
    elif gap == 0:
        reason = "Gleiches Niveau; kein Situations-Tag am Clip."
    elif parts["situation_match"]:
        reason = (
            f"Kein Clip auf {lesson_level}; {parts['clip_level']} mit passender "
            f"Situation (Abstand {gap})."
        )
    else:
        reason = (
            f"Kein Clip auf {lesson_level}; nächstes Niveau "
            f"{parts['clip_level']} (Abstand {gap})."
        )
    return MediaPick(
        video_id=clip["video_id"],
        start_s=round(float(clip["start_s"]), 1),
        end_s=round(float(clip["end_s"]), 1),
        clip_id=clip["clip_id"],
        reason=reason,
    )


def select_for_lesson(lesson: dict, clips: list[dict], *, threshold: float = THRESHOLD) -> LessonMedia:
    level = lesson["level"]
    scene = lesson.get("scene") or {}
    tags = list(scene.get("situation_tags") or [])
    grammar = list(scene.get("grammar_focus") or [])

    ranked = []
    for clip in clips:
        if not clip.get("video_id"):
            continue
        parts = score_clip(clip, level=level, tags=tags, grammar_focus=grammar)
        if parts["total"] >= threshold:
            ranked.append((parts["total"], clip["clip_id"], clip, parts))

    if not ranked:
        return LessonMedia(primary=None, alternates=[], fallback="rendered_audio")

    # Highest score first; deterministic tie-break by clip_id ascending.
    ranked.sort(key=lambda item: (-item[0], item[1]))
    _, _, best, parts = ranked[0]
    alternates = [_pick(clip, p, level) for _, _, clip, p in ranked[1 : 1 + MAX_ALTERNATES]]
    return LessonMedia(
        primary=_pick(best, parts, level),
        alternates=alternates,
        fallback="rendered_audio",
        relevance=Relevance(
            level_gap=parts["level_gap"],
            situation_match=parts["situation_match"],
            grammar_overlap=parts["grammar_overlap"],
        ),
    )


def build_manifest(
    *,
    lessons_dir: Path = LESSONS_DIR,
    corpus_path: Path = CORPUS_PATH,
    overrides_path: Path | None = None,
    today: str | None = None,
) -> MediaManifest:
    clips = load_clips(corpus_path)
    lessons = load_lessons(lessons_dir)
    media: dict[str, LessonMedia] = {}
    for lesson in lessons:
        media[lesson["id"]] = select_for_lesson(lesson, clips)
    manifest = MediaManifest(
        version=1,
        generated=today or date.today().isoformat(),
        lessons=media,
    )
    overrides = load_overrides(overrides_path or CONTENT_DIR / OVERRIDES_NAME)
    return merge_overrides(manifest, overrides)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v5.media.select")
    parser.add_argument("--lessons-dir", type=Path, default=LESSONS_DIR)
    parser.add_argument("--corpus", type=Path, default=CORPUS_PATH)
    parser.add_argument("--out", type=Path, default=CONTENT_DIR / MANIFEST_NAME)
    parser.add_argument("--overrides", type=Path, default=CONTENT_DIR / OVERRIDES_NAME)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 when the checked-in manifest differs from a fresh build",
    )
    args = parser.parse_args(argv)

    fresh = build_manifest(
        lessons_dir=args.lessons_dir,
        corpus_path=args.corpus,
        overrides_path=args.overrides,
        today=date.today().isoformat(),
    )

    if args.check:
        existing = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else None
        current = json.loads(fresh.model_dump_json())
        if existing is None:
            print(f"{args.out} does not exist", file=sys.stderr)
            return 1
        # `generated` is a date stamp, not a content difference.
        existing.pop("generated", None)
        current.pop("generated", None)
        if existing != current:
            print("lesson_media.json is stale — rerun python -m v5.media.select", file=sys.stderr)
            return 1
        print("lesson_media.json is current")
        return 0

    write_manifest(args.out, fresh)
    fallbacks = [lid for lid, item in fresh.lessons.items() if item.primary is None]
    print(f"{len(fresh.lessons)} lessons → {len(fresh.lessons) - len(fallbacks)} with a clip")
    for lesson_id, item in fresh.lessons.items():
        if item.primary is None:
            print(f"  {lesson_id}: fallback rendered_audio")
        else:
            print(
                f"  {lesson_id}: {item.primary.video_id} "
                f"{item.primary.start_s:.0f}–{item.primary.end_s:.0f}s "
                f"(gap {item.relevance.level_gap}, situation {item.relevance.situation_match})"
            )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
