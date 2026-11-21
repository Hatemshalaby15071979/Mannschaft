"""Contract for ``content/cards/<lesson>.json``.

Cards are generated only from a lesson's own segment pairs and glossary
entries. No new prose is invented, and every card that points at a segment must
point at one that exists — the server and the tests both enforce that.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CardKind = Literal["recall", "cloze", "order", "produce"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Card(_Strict):
    id: str
    kind: CardKind
    segment_id: str | None = None

    prompt_de: str | None = None
    answer_en: str | None = None
    answer_de: str | None = None
    hint: str | None = None
    audio: str | None = None

    tokens: list[str] = Field(default_factory=list)
    answer: str | None = None

    can_do_en: str | None = None
    can_do_de: str | None = None
    source: str | None = None

    @model_validator(mode="after")
    def _shape_for_kind(self) -> Card:
        if self.kind == "recall":
            if not (self.segment_id and self.prompt_de and self.answer_en):
                raise ValueError("recall needs segment_id, prompt_de, answer_en")
        elif self.kind == "cloze":
            if not (self.segment_id and self.prompt_de and self.answer_de):
                raise ValueError("cloze needs segment_id, prompt_de, answer_de")
        elif self.kind == "order":
            if not (self.segment_id and self.tokens and self.answer):
                raise ValueError("order needs segment_id, tokens, answer")
            if len(self.tokens) < 2:
                raise ValueError("order needs at least two tokens")
        elif self.kind == "produce" and not (self.can_do_en and self.answer_de):
            raise ValueError("produce needs can_do_en, answer_de")
        return self


class CardDeck(_Strict):
    lesson: str
    version: int = 1
    cards: list[Card] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> CardDeck:
        ids = [card.id for card in self.cards]
        if len(ids) != len(set(ids)):
            raise ValueError("card ids must be unique")
        return self
