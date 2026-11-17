"""Semantic validation beyond what pydantic can express per-field.

Returns structured issues so the CLI can point at the exact segment. Errors
block a render; warnings do not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from ..config import load_levels, load_voices, resolve_voice
from .models import LEVELS, LessonScript


@dataclass(frozen=True)
class Issue:
    severity: str  # "error" | "warning"
    location: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.location}: {self.message}"


def load_lesson(path: Path) -> LessonScript:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return LessonScript.model_validate(raw)


def validate_script(script: LessonScript) -> list[Issue]:
    issues: list[Issue] = []
    levels = load_levels()
    voices = load_voices()
    lid = script.id

    def err(loc: str, msg: str) -> None:
        issues.append(Issue("error", f"{lid} {loc}", msg))

    def warn(loc: str, msg: str) -> None:
        issues.append(Issue("warning", f"{lid} {loc}", msg))

    # id / level agreement
    if script.level not in LEVELS:
        err("level", f"unknown level {script.level!r}")
    elif not script.id.startswith(script.level + "-"):
        err("id", f"id {script.id!r} must start with {script.level!r}-")

    lvl = levels.get(script.level)

    # cast voice keys must exist and be configured
    for member in script.cast:
        try:
            resolve_voice(voices, member.voice)
        except KeyError as exc:
            err(f"cast[{member.role}]", str(exc))

    # segment ids unique
    seen: dict[str, int] = {}
    for i, seg in enumerate(script.segments):
        if seg.id in seen:
            err(f"segments[{i}]", f"duplicate segment id {seg.id!r} (first at index {seen[seg.id]})")
        seen[seg.id] = i

    # speakers resolve
    roles = script.roles
    for i, seg in enumerate(script.segments):
        if seg.speaker not in roles:
            err(f"segments[{i}:{seg.id}]", f"speaker {seg.speaker!r} not in cast {sorted(roles)}")

    # gloss refs resolve; gloss ids unique
    gloss_ids = [g.id for g in script.glossary]
    dupes = {g for g in gloss_ids if gloss_ids.count(g) > 1}
    for g in sorted(dupes):
        err("glossary", f"duplicate glossary id {g!r}")
    known = set(gloss_ids)
    for i, seg in enumerate(script.segments):
        for ref in seg.gloss:
            if ref not in known:
                err(f"segments[{i}:{seg.id}]", f"gloss ref {ref!r} not in glossary")

    # level word cap on spoken dialogue
    if lvl is not None:
        for i, seg in enumerate(script.segments):
            if seg.type == "line" and seg.word_count > lvl.max_words_per_line:
                err(
                    f"segments[{i}:{seg.id}]",
                    f"{seg.word_count} words exceeds {script.level} cap of "
                    f"{lvl.max_words_per_line}: {seg.text!r}",
                )

    # content-completeness warnings (do not block)
    checks = sum(1 for s in script.segments if s.type == "check")
    if checks < 3:
        warn("segments", f"only {checks} comprehension check(s); plan requires 3-6")
    if len(script.glossary) < 15:
        warn("glossary", f"only {len(script.glossary)} entries; plan requires 15-30")
    if not script.scene.situation_tags:
        warn("scene", "no situation_tags — library filter will not find this lesson")
    if not script.scene.grammar_focus:
        warn("scene", "no grammar_focus")

    # duplicate adjacent speakers is a smell: monologue disguised as dialogue
    run = 1
    for a, b in zip(script.segments, script.segments[1:], strict=False):
        run = run + 1 if a.speaker == b.speaker and a.type == b.type == "line" else 1
        if run >= 6:
            warn(f"segments[{b.id}]", f"{run} consecutive lines by {b.speaker!r} — sounds like a monologue")
            run = 1

    return issues


def validate_file(path: Path) -> tuple[LessonScript | None, list[Issue]]:
    try:
        script = load_lesson(path)
    except ValidationError as exc:
        issues = [
            Issue("error", f"{path.name} {'/'.join(str(p) for p in e['loc'])}", e["msg"])
            for e in exc.errors()
        ]
        return None, issues
    except (json.JSONDecodeError, OSError) as exc:
        return None, [Issue("error", path.name, str(exc))]
    return script, validate_script(script)


def has_errors(issues: list[Issue]) -> bool:
    return any(i.severity == "error" for i in issues)
