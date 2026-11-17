"""Content-addressed cache for synthesised segments.

A cache key must cover EVERY input that can change the audio. If a field can
alter the waveform and is missing from the fingerprint, editing a lesson
silently serves stale audio — the worst kind of bug, because it sounds fine.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..config import ROOT

DEFAULT_CACHE_DIR = ROOT / "audio" / ".cache"

# Bump when the payload shape or engine default changes in a way that should
# invalidate every cached render.
CACHE_VERSION = 1

# Fields that must never influence audio (bookkeeping / disk paths).
_NON_AUDIO = {"out_dir"}


@dataclass(frozen=True)
class SynthesisRequest:
    """One unit of speech. The cache key is derived from this object."""

    text: str
    voice_profile_id: str
    language: str = "de"
    speed: float = 1.0
    seed: int | None = None
    model: str = "omnivoice"
    num_step: int = 32
    guidance_scale: float = 2.0
    response_format: str = "wav"
    segment_id: str = ""
    lesson_id: str = ""

    def fingerprint(self) -> dict:
        data = {k: v for k, v in asdict(self).items() if k not in _NON_AUDIO}
        # Bookkeeping fields identify the caller; they must not bust the cache.
        data.pop("segment_id", None)
        data.pop("lesson_id", None)
        data["cache_version"] = CACHE_VERSION
        return data

    def key(self) -> str:
        blob = json.dumps(self.fingerprint(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def payload(self) -> dict:
        """The exact JSON body /v1/audio/speech accepts."""
        return {
            "model": self.model,
            "input": self.text,
            "voice": self.voice_profile_id,
            "response_format": self.response_format,
            "speed": self.speed,
            "language": self.language,
            "num_step": self.num_step,
            "guidance_scale": self.guidance_scale,
            **({"seed": self.seed} if self.seed is not None else {}),
        }


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    written: int = 0

    @property
    def total(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.total if self.total else 0.0

    def __str__(self) -> str:
        return f"{self.hits} hits / {self.misses} misses ({self.hit_rate:.0%})"


@dataclass
class AudioCache:
    root: Path = field(default_factory=lambda: DEFAULT_CACHE_DIR)
    stats: CacheStats = field(default_factory=CacheStats)

    def path_for(self, key: str, ext: str = "wav") -> Path:
        return self.root / key[:2] / key[2:4] / f"{key}.{ext}"

    def get(self, key: str, ext: str = "wav") -> Path | None:
        path = self.path_for(key, ext)
        if path.exists() and path.stat().st_size > 0:
            self.stats.hits += 1
            return path
        self.stats.misses += 1
        return None

    def put(self, key: str, data: bytes, ext: str = "wav") -> Path:
        path = self.path_for(key, ext)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)  # atomic: a killed render never leaves a corrupt entry
        self.stats.written += 1
        return path

    def clear(self) -> int:
        removed = 0
        if not self.root.exists():
            return 0
        for f in self.root.rglob("*.wav"):
            f.unlink()
            removed += 1
        return removed

    def size_bytes(self) -> int:
        if not self.root.exists():
            return 0
        return sum(f.stat().st_size for f in self.root.rglob("*.wav"))
