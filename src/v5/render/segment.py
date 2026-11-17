"""Per-segment synthesis against VoiceStudio's OpenAI-compatible endpoint.

Primary render path. One request per segment, cached by content hash, so editing
one line re-renders one line instead of a ten-minute lesson.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..config import LevelProfile, VoiceProfile, missing_profiles, resolve_voice
from ..contract.models import LessonScript, Segment
from .cache import AudioCache, SynthesisRequest

DEFAULT_BASE_URL = "http://127.0.0.1:3900"
SPEECH_PATH = "/v1/audio/speech"
MAX_INPUT_CHARS = 4096

Transport = Callable[[str, dict], bytes]


class RenderError(RuntimeError):
    pass


class VoiceNotReady(RenderError):
    pass


def http_transport(url: str, payload: dict, *, timeout: float = 300.0) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:  # surface the engine's message, not a bare 400
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise RenderError(f"{url} -> {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RenderError(f"VoiceStudio unreachable at {url}: {exc.reason}") from exc


@dataclass
class VoiceStudioClient:
    base_url: str = DEFAULT_BASE_URL
    transport: Transport = http_transport

    def synthesize(self, request: SynthesisRequest) -> bytes:
        if not request.text.strip():
            raise RenderError("refusing to synthesise empty text")
        if len(request.text) > MAX_INPUT_CHARS:
            raise RenderError(
                f"text is {len(request.text)} chars, endpoint caps at {MAX_INPUT_CHARS}; "
                "split the segment"
            )
        if not request.voice_profile_id:
            raise VoiceNotReady("empty voice profile id would render in the engine default voice")
        audio = self.transport(self.base_url + SPEECH_PATH, request.payload())
        if not audio:
            raise RenderError("engine returned 0 bytes")
        return audio

    def voices(self) -> dict:
        url = self.base_url + "/v1/audio/voices"
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))


@dataclass
class SegmentRender:
    segment_id: str
    path: Path
    cached: bool
    key: str


def request_for(
    segment: Segment,
    profile: VoiceProfile,
    level: LevelProfile,
) -> SynthesisRequest:
    """Build the synthesis request for one segment.

    `speed` is the authored value, else the level baseline — the exact float,
    because this endpoint accepts 0.25–4.0 and has no reason to quantise.
    """
    speed = segment.speed if segment.speed is not None else level.default_speed
    return SynthesisRequest(
        text=segment.text.strip(),
        voice_profile_id=profile.profile_id,
        language="de",
        speed=speed,
        seed=profile.seed,
        segment_id=segment.id,
    )


def render_segment(
    segment: Segment,
    profile: VoiceProfile,
    level: LevelProfile,
    cache: AudioCache,
    client: VoiceStudioClient,
) -> SegmentRender:
    request = request_for(segment, profile, level)
    key = request.key()
    hit = cache.get(key)
    if hit is not None:
        return SegmentRender(segment.id, hit, True, key)
    audio = client.synthesize(request)
    return SegmentRender(segment.id, cache.put(key, audio), False, key)


def render_lesson(
    script: LessonScript,
    voices: dict[str, VoiceProfile],
    level: LevelProfile,
    cache: AudioCache,
    client: VoiceStudioClient,
    out_dir: Path,
    *,
    on_segment: Callable[[int, int], None] | None = None,
) -> list[SegmentRender]:
    """Render every segment once. Refuses if any cast voice is unconfigured.

    ``on_segment(done, total)`` is called after each clip so a job runner or a
    progress bar can report honestly instead of guessing.
    """
    unready = missing_profiles(voices)
    if unready:
        raise VoiceNotReady(
            "cannot render: no profile_id for " + ", ".join(unready) + " (M4 is manual)"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(script.segments)
    results: list[SegmentRender] = []
    for index, segment in enumerate(script.segments, start=1):
        member = script.roles[segment.speaker]
        profile = resolve_voice(voices, member.voice)
        rendered = render_segment(segment, profile, level, cache, client)
        target = out_dir / f"{segment.id}.wav"
        if rendered.path != target:
            target.write_bytes(rendered.path.read_bytes())
        results.append(SegmentRender(segment.id, target, rendered.cached, rendered.key))
        if on_segment is not None:
            on_segment(index, total)
    return results
