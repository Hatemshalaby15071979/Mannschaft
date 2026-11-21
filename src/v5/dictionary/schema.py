"""Contract for the local dictionary seed.

The seed is built only from the 12 lessons' own glossaries. It is attributable
(the source lesson travels with every entry) and it works offline. Outbound
links to DWDS / Wiktionary / Cambridge / Collins are links, never scraped
content.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeedEntry(_Strict):
    de: str
    en: str
    pos: str = ""
    note_de: str | None = None
    note_en: str | None = None
    example_de: str | None = None
    example_en: str | None = None
    plural: str | None = None
    article: str | None = None
    source_lesson: str
    sources: list[str] = Field(default_factory=list)
    source: str = "v5 lesson glossary"


class DictionarySeed(_Strict):
    version: int = 1
    generated: str
    count: int
    entries: list[SeedEntry] = Field(default_factory=list)
