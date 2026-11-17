"""Helpers shared by the audio tests — real wav files made by ffmpeg.

Synthetic audio keeps the audio tests runnable without VoiceStudio, a GPU or
the M4 voices. Every wav has padding so trimming is genuinely exercised.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def make_clip(path: Path, seconds: float, freq: int = 440, pad_s: float = 0.15) -> Path:
    """A tone with leading/trailing silence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}:sample_rate=24000",
            "-af", f"adelay={int(pad_s * 1000)}:all=1,apad=pad_dur={pad_s}",
            "-c:a", "pcm_s16le", str(path),
        ],
        check=True,
    )
    return path


def make_silence(path: Path, seconds: float = 1.0) -> Path:
    """Pure silence — used to prove a dead synthesis aborts the assembly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono:d={seconds}",
            "-c:a", "pcm_s16le", str(path),
        ],
        check=True,
    )
    return path
