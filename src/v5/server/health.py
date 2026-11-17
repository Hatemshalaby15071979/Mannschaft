"""VoiceStudio health probe.

`/api/health` exists so the client can say *why* something is unavailable
instead of showing a spinner forever. It must never hang: the probe has a hard
timeout, and a dead engine is a normal answer, not an exception.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

DEFAULT_VOICESTUDIO_URL = "http://127.0.0.1:3900"
VOICES_PATH = "/v1/audio/voices"


def probe(url: str = DEFAULT_VOICESTUDIO_URL, *, timeout: float = 1.5) -> dict:
    """Return ``{up, voices, error}``. Never raises."""
    endpoint = url.rstrip("/") + VOICES_PATH
    try:
        with urllib.request.urlopen(endpoint, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"up": False, "voices": None, "error": _describe(exc)}

    profiles = payload.get("voices") or payload.get("data") or payload
    count = len(profiles) if isinstance(profiles, list) else None
    return {"up": True, "voices": count, "error": None}


def _describe(exc: Exception) -> str:
    reason = getattr(exc, "reason", None)
    if reason is not None:
        return str(reason)
    return str(exc) or exc.__class__.__name__
