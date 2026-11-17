"""Config loading: voices and per-level authoring limits.

Single source of truth for both. Nothing else may hardcode a profile id or a
level's speed.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(os.environ.get("V5_CONFIG_DIR", ROOT / "config"))

# VoiceStudio's design whitelist (omnivoice/utils/voice_design.py). Anything
# outside this is silently dropped by sanitize_instruct(), so we refuse it here.
VALID_GENDER = {"male", "female"}
VALID_AGE = {"child", "teenager", "young adult", "middle-aged", "elderly"}
VALID_PITCH = {"very low pitch", "low pitch", "moderate pitch", "high pitch", "very high pitch"}


@dataclass(frozen=True)
class VoiceProfile:
    key: str
    name: str
    profile_id: str
    seed: int
    gender: str
    age: str
    pitch: str
    whisper: bool
    language: str
    use: tuple[str, ...] = field(default=())

    @property
    def instruct(self) -> str:
        """Instruct string in VoiceStudio's whitelist vocabulary, in order."""
        parts = [self.gender, self.age, self.pitch]
        if self.whisper:
            parts.append("whisper")
        return ", ".join(parts)

    def validate(self) -> None:
        if self.gender not in VALID_GENDER:
            raise ValueError(f"{self.key}: bad gender {self.gender!r}")
        if self.age not in VALID_AGE:
            raise ValueError(f"{self.key}: bad age {self.age!r}")
        if self.pitch not in VALID_PITCH:
            raise ValueError(f"{self.key}: bad pitch {self.pitch!r}")

    @property
    def ready(self) -> bool:
        return bool(self.profile_id)


@dataclass(frozen=True)
class LevelProfile:
    level: str
    max_words_per_line: int
    default_speed: float
    base_pause_ms: int
    target_minutes: int
    target_segments: int


def _read(name: str) -> dict:
    path = CONFIG_DIR / name
    with path.open("rb") as fh:
        return tomllib.load(fh)


@lru_cache(maxsize=1)
def load_voices() -> dict[str, VoiceProfile]:
    raw = _read("voices.toml")["voices"]
    out: dict[str, VoiceProfile] = {}
    for key, item in raw.items():
        prof = VoiceProfile(
            key=key,
            name=item["name"],
            profile_id=item.get("profile_id", ""),
            seed=int(item["seed"]),
            gender=item["gender"],
            age=item["age"],
            pitch=item["pitch"],
            whisper=bool(item.get("whisper", False)),
            language=item.get("language", "German"),
            use=tuple(item.get("use", ())),
        )
        prof.validate()
        out[key] = prof
    return out


@lru_cache(maxsize=1)
def load_levels() -> dict[str, LevelProfile]:
    raw = _read("levels.toml")
    return {
        level: LevelProfile(
            level=level,
            max_words_per_line=int(item["max_words_per_line"]),
            default_speed=float(item["default_speed"]),
            base_pause_ms=int(item["base_pause_ms"]),
            target_minutes=int(item["target_minutes"]),
            target_segments=int(item["target_segments"]),
        )
        for level, item in raw.items()
    }


def missing_profiles(voices: dict[str, VoiceProfile] | None = None) -> list[str]:
    """Voice keys with no profile_id yet — renderers must refuse while non-empty."""
    voices = voices if voices is not None else load_voices()
    return sorted(k for k, v in voices.items() if not v.ready)


def resolve_voice(voices: dict[str, VoiceProfile], role_voice: str) -> VoiceProfile:
    """Resolve a cast entry's `voice` field to a configured profile.

    The field is a config key (e.g. `de_young_f`), never an inline profile id.
    Accepts a raw profile id too, for hand-written test fixtures.
    """
    if role_voice in voices:
        return voices[role_voice]
    for prof in voices.values():
        if prof.profile_id and prof.profile_id == role_voice:
            return prof
    raise KeyError(f"unknown voice {role_voice!r}; known keys: {sorted(voices)}")
