"""Clip teachability scoring (plan §8.3).

Pure functions — no I/O, no network. Every component returns a float so the
formula is deterministic and unit-testable. Only the word bands (data) change
an individual score; the formula itself is fixed here.

    teachability =
        1.4 · level_fit            CEFR-band lexical coverage
      + 1.0 · completeness         starts + ends on a full sentence
      + 0.8 · question_present     contains an interrogative
      + 0.6 · situation_confidence keyword→situation hit
      + 0.5 · speech_rate_fit      words/sec within band for level
      + 0.4 · low_filler_ratio     (high when few fillers)
      − 1.0 · profanity_or_slur
      − 0.8 · background_noise     (0 in stage C; astats is optional)
"""

from __future__ import annotations

import functools
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = Path(__import__("os").environ.get("V5_CONFIG_DIR", ROOT / "config"))

LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
_WORD_RE = re.compile(r"[a-zäöüßA-ZÄÖÜ]+")
_SENT_END = ".!?"
_INTERROGATIVES = {"wer", "was", "wie", "warum", "wieso", "weshalb", "wann", "wo", "wohin",
                   "woher", "welche", "welcher", "welches", "ob", "wie viele", "was für"}


@functools.lru_cache(maxsize=1)
def config() -> dict:
    with (CONFIG_DIR / "corpus.toml").open("rb") as fh:
        return tomllib.load(fh)


@functools.lru_cache(maxsize=1)
def word_bands() -> dict[str, str]:
    with (CONFIG_DIR / "de_bands.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(text)]


def level_fit(text: str, target: str, *, bands: dict[str, str] | None = None) -> float:
    """Fraction of known content words at or below `target`'s CEFR band.

    Unknown words (not in the band map) are ignored — they cannot be scored
    without a frequency entry, and treating them as above-level would punish
    any unfamiliar-but-common word. Returns 0.0 when nothing is scoreable.
    """
    bands = bands if bands is not None else word_bands()
    order = {lv: i for i, lv in enumerate(LEVELS)}
    ceiling = order[target]
    toks = [t for t in tokens(text) if len(t) > 2 and t in bands]
    if not toks:
        return 0.0
    return sum(1 for t in toks if order[bands[t]] <= ceiling) / len(toks)


def completeness(text: str) -> float:
    """1.0 when the clip starts uppercase and ends on a full sentence."""
    stripped = text.strip()
    if not stripped:
        return 0.0
    starts = 1.0 if stripped[0].isupper() else 0.0
    ends = 1.0 if stripped[-1] in _SENT_END else 0.0
    return (starts + ends) / 2


def question_present(text: str) -> float:
    """1.0 for a question mark or an interrogative token."""
    low = text.lower()
    if "?" in text:
        return 1.0
    toks = set(tokens(low))
    return 1.0 if toks & _INTERROGATIVES else 0.0


def detect_situation(text: str) -> tuple[str | None, float]:
    """First situation (config order) whose keywords appear; confidence = hits/len.

    Returns (label, confidence). `None, 0.0` when no keyword matches.
    """
    toks = tokens(text)
    if not toks:
        return None, 0.0
    for rule in config()["situation"]:
        hits = sum(1 for kw in rule["keywords"] if kw.lower() in toks)
        if hits:
            return rule["label"], min(1.0, hits / 3)
    return None, 0.0


def situation_confidence(text: str) -> float:
    return detect_situation(text)[1]


def speech_rate_fit(word_count: int, seconds: float, target: str) -> float:
    """1.0 at the band's target words/sec, decaying linearly to 0 at 2× off."""
    if seconds <= 0:
        return 0.0
    target_rate = config()["rate"][target]
    rate = word_count / seconds
    return max(0.0, 1.0 - abs(rate - target_rate) / target_rate)


def low_filler_ratio(text: str) -> float:
    """1.0 when no fillers; decreases with the share of filler tokens."""
    toks = tokens(text)
    if not toks:
        return 0.0
    fillers = {f.lower() for f in config()["fillers"]}
    n = sum(1 for t in toks if t in fillers)
    return 1.0 - n / len(toks)


def profanity_or_slur(text: str) -> float:
    toks = set(tokens(text))
    bad = {p.lower() for p in config()["profanity"]}
    return 1.0 if toks & bad else 0.0


def teachability(
    text: str,
    *,
    level: str,
    word_count: int,
    seconds: float,
    background_noise: float = 0.0,
    bands: dict[str, str] | None = None,
) -> float:
    """The full weighted score from plan §8.3."""
    score = (
        1.4 * level_fit(text, level, bands=bands)
        + 1.0 * completeness(text)
        + 0.8 * question_present(text)
        + 0.6 * situation_confidence(text)
        + 0.5 * speech_rate_fit(word_count, seconds, level)
        + 0.4 * low_filler_ratio(text)
        - 1.0 * profanity_or_slur(text)
        - 0.8 * background_noise
    )
    return round(score, 3)
