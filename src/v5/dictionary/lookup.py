"""Local dictionary search + outbound links.

Local seed first, always. The links are plain URLs — the app never fetches or
stores a dictionary page, so there is no proprietary content and no scraping.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

from ..config import ROOT
from .schema import DictionarySeed, SeedEntry

SEED_PATH = ROOT / "content" / "dictionary" / "seed.json"

_cache: dict[str, tuple[float, DictionarySeed]] = {}


def load_seed(path: Path = SEED_PATH) -> DictionarySeed | None:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    cached = _cache.get(str(path))
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        seed = DictionarySeed.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    _cache[str(path)] = (mtime, seed)
    return seed


def _rank(entry: SeedEntry, needle: str) -> int | None:
    """Rank a hit. German compounds count (Werktag, Tagesschau); arbitrary
    mid-word substrings do not ("tag" inside "stagnieren"), and English matches
    must be whole words ("tag" inside "advantage" is noise)."""
    de = entry.de.casefold()
    en = entry.en.casefold()
    word = re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)")
    if de == needle:
        return 0
    if de.startswith(needle):
        return 1
    if word.search(de) or de.endswith(needle):
        return 2
    if en == needle:
        return 3
    if word.search(en):
        return 4
    return None


def search(seed: DictionarySeed, query: str, *, limit: int = 20) -> list[dict]:
    needle = " ".join((query or "").strip().casefold().split())
    if not needle:
        return [entry.model_dump(mode="json") for entry in seed.entries[:limit]]
    ranked = []
    for entry in seed.entries:
        rank = _rank(entry, needle)
        if rank is not None:
            ranked.append((rank, entry.de.casefold(), entry))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [entry.model_dump(mode="json") for _, _, entry in ranked[:limit]]


def outbound_links(query: str) -> list[dict]:
    word = (query or "").strip()
    if not word:
        return []
    slug = quote(word.replace(" ", "_"), safe="")
    term = quote(word, safe="")
    return [
        {"label": "DWDS", "url": f"https://www.dwds.de/wb/{term}", "note": "deutsches Wörterbuch"},
        {
            "label": "Wiktionary",
            "url": f"https://de.wiktionary.org/wiki/{slug}",
            "note": "frei, CC-lizenziert",
        },
        {
            "label": "Cambridge",
            "url": f"https://dictionary.cambridge.org/dictionary/german-english/{term}",
            "note": "deutsch → englisch",
        },
        {
            "label": "Collins",
            "url": f"https://www.collinsdictionary.com/dictionary/german-english/{term}",
            "note": "deutsch → englisch",
        },
    ]


def lookup(query: str, *, path: Path = SEED_PATH, limit: int = 20) -> dict:
    seed = load_seed(path)
    if seed is None:
        return {
            "query": query,
            "local": [],
            "links": outbound_links(query),
            "reason": "dictionary seed not built yet (python -m v5.dictionary.seed)",
        }
    return {
        "query": query,
        "local": search(seed, query, limit=limit),
        "links": outbound_links(query),
        "count": len(seed.entries),
    }


def dump_seed(path: Path = SEED_PATH) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
