"""Lesson Script v1 — the contract the whole system is built around.

Audio-first: a lesson is a timeline of spoken segments, not text with audio
attached. Everything downstream (renderer, server, client) reads this shape and
nothing else.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .. import SCHEMA

SegmentType = Literal["scene", "line", "echo", "check", "drill", "note", "vocab", "recap"]
Level = Literal["A1", "A2", "B1", "B2", "C1", "C2"]

LEVELS: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1", "C2")

_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
# Bracket tokens are VoiceStudio markup. Spoken text must never contain them,
# and no line may start with '#' (that begins a chapter in the longform grammar).
_FORBIDDEN_IN_SPEECH = ("[", "]", "====*")


class _Strict(BaseModel):
    # extra=forbid: a typo'd key must fail loudly, not vanish (the v4 bug class).
    # protected_namespaces=(): `schema` is a required contract field.
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


class Title(_Strict):
    de: str
    en: str


class Scene(_Strict):
    # `register` shadows ABCMeta.register (pydantic's metaclass parent), so the
    # Python attribute is `register_` while the JSON key stays `register`.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    setting_de: str
    setting_en: str
    register_: str = Field(alias="register")
    can_do_de: str
    can_do_en: str
    situation_tags: list[str] = Field(default_factory=list)
    grammar_focus: list[str] = Field(default_factory=list)


class CastMember(_Strict):
    role: str
    voice: str  # config key from config/voices.toml, never an inline profile id
    lang: str = "de"

    @model_validator(mode="after")
    def _check_role(self) -> CastMember:
        if not _ID_RE.match(self.role):
            raise ValueError(f"role {self.role!r} must match {_ID_RE.pattern}")
        return self


class Segment(_Strict):
    id: str
    type: SegmentType
    speaker: str
    text: str
    lang: str = "de"
    translation: str | None = None
    pause_after_ms: int = 0
    speed: float | None = None
    focus: list[str] = Field(default_factory=list)
    gloss: list[str] = Field(default_factory=list)
    repeat: int | None = None
    answers: list[str] = Field(default_factory=list)
    answer_pause_ms: int = 2500
    skippable: bool = False

    @model_validator(mode="after")
    def _segment_rules(self) -> Segment:
        if not _ID_RE.match(self.id):
            raise ValueError(f"segment id {self.id!r} must match {_ID_RE.pattern}")
        if not self.text.strip():
            raise ValueError("text must not be empty")
        for token in _FORBIDDEN_IN_SPEECH:
            if token in self.text:
                raise ValueError(
                    f"text contains markup token {token!r}; spoken text must be plain"
                )
        if self.text.lstrip().startswith("#"):
            raise ValueError("text must not start with '#' (chapter marker in longform)")
        if not 0 <= self.pause_after_ms <= 5000:
            raise ValueError(f"pause_after_ms={self.pause_after_ms} outside 0..5000")
        if self.speed is not None and not 0.5 <= self.speed <= 1.5:
            raise ValueError(f"speed={self.speed} outside 0.5..1.5")

        if self.type == "line" and not (self.translation or "").strip():
            raise ValueError("type='line' requires 'translation'")
        if self.type in ("echo", "drill") and (self.repeat is None or not 1 <= self.repeat <= 3):
            raise ValueError(f"type={self.type!r} requires repeat in 1..3")
        if self.type == "check":
            if not self.answers:
                raise ValueError("type='check' requires at least one answer")
            if not 0 <= self.answer_pause_ms <= 10000:
                raise ValueError("answer_pause_ms outside 0..10000")
        return self

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    # ---- timing -------------------------------------------------------
    # Both render paths (longform text and the ffmpeg assembler) read these,
    # so a lesson sounds the same whichever way it is produced.

    @property
    def takes(self) -> int:
        """How many times the audio is played (echo/drill repeat, else 1)."""
        return max(1, self.repeat or 1)

    @property
    def tail_pause_ms(self) -> int:
        """Silence after the last take.

        A `check` uses its thinking time instead of the ordinary pause, so the
        learner gets the authored window to answer before the lesson moves on.
        """
        return self.answer_pause_ms if self.type == "check" else self.pause_after_ms

    @property
    def intra_take_pause_ms(self) -> int:
        """Silence between takes of a repeated segment."""
        return max(300, self.pause_after_ms // 2) if self.takes > 1 else 0

    def gaps(self) -> list[int]:
        """Silence after each take, in order; the last entry is the tail."""
        return [self.intra_take_pause_ms] * (self.takes - 1) + [self.tail_pause_ms]

    @property
    def total_pause_ms(self) -> int:
        """Sum of every gap this segment contributes (takes included)."""
        return sum(self.gaps())


class GlossaryEntry(_Strict):
    id: str
    de: str
    en: str
    pos: str
    example_de: str
    example_en: str
    plural: str | None = None
    article: str | None = None
    note_de: str | None = None
    note_en: str | None = None

    @model_validator(mode="after")
    def _check(self) -> GlossaryEntry:
        if not _ID_RE.match(self.id):
            raise ValueError(f"glossary id {self.id!r} must match {_ID_RE.pattern}")
        return self


class Meta(_Strict):
    authored: Literal["human", "human+assist", "assist"] = "human+assist"
    source_refs: list[str] = Field(default_factory=list)
    est_seconds: int = 0
    script_hash: str | None = None
    version: int = 1


class LessonScript(_Strict):
    # `schema` shadows deprecated BaseModel.schema; Python attr is `schema_`,
    # JSON key stays `schema`.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_: Literal["lesson-script/v1"] = Field(default=SCHEMA, alias="schema")
    id: str
    level: Level
    title: Title
    minutes: int
    scene: Scene
    cast: list[CastMember]
    segments: list[Segment]
    glossary: list[GlossaryEntry] = Field(default_factory=list)
    meta: Meta = Field(default_factory=Meta)

    @model_validator(mode="after")
    def _lesson_rules(self) -> LessonScript:
        if not self.cast:
            raise ValueError("cast must not be empty")
        if not self.segments:
            raise ValueError("segments must not be empty")
        roles = [c.role for c in self.cast]
        if len(roles) != len(set(roles)):
            raise ValueError(f"duplicate cast roles: {roles}")
        return self

    @property
    def roles(self) -> dict[str, CastMember]:
        return {c.role: c for c in self.cast}
