"""ffmpeg assembler: per-segment wavs -> lesson.mp3 + timeline.json + .srt + manifest.

Timing is **measured, never estimated**: each clip is trimmed and ffprobe'd, and
the timeline is built from those measured durations plus the authored gaps in
``Segment.gaps()``. The longform adapter reads the same gaps, so the two render
paths cannot disagree about where a line sits.

Loudness is a two-pass loudnorm over the whole lesson, not per segment — per
segment normalisation pumps every time the speaker changes.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path

from ..adapters.srt import Cue, to_srt
from ..config import LevelProfile, VoiceProfile, resolve_voice
from ..contract.models import LessonScript

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

SAMPLE_RATE = 24_000
LESSON_BITRATE = "112k"
LINE_BITRATE = "64k"

TARGET_I = -16.0
TARGET_TP = -1.5
TARGET_LRA = 11.0

# Max drift we accept between the computed timeline and the assembled file.
MAX_DRIFT_MS = 50

# -50 dB is quiet enough to keep soft onsets ("s" in "sieben") while removing
# synthesis silence; start_silence keeps 40 ms so words do not feel clipped.
_TRIM = "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.04:detection=peak"

_JSON_BLOCK = re.compile(r"\{[^{}]*\}", re.S)


class AssemblyError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# subprocess helpers
# --------------------------------------------------------------------------


def _run(cmd: list[str], *, timeout: float = 900.0) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise AssemblyError(f"{cmd[0]} not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise AssemblyError(f"{Path(cmd[0]).name} timed out after {timeout:.0f}s") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-12:]
        raise AssemblyError(
            f"{Path(cmd[0]).name} exited {proc.returncode}:\n" + "\n".join(tail)
        )
    return proc


def probe_duration_ms(path: Path, *, ffprobe: str = FFPROBE) -> int:
    """Measured duration in ms. This is the number the timeline is built from."""
    proc = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ]
    )
    raw = proc.stdout.strip()
    try:
        seconds = float(raw)
    except ValueError as exc:
        # A fully-silent clip trims to nothing; ffprobe then prints "N/A".
        raise AssemblyError(
            f"ffprobe could not read a duration from {path} (got {raw!r}) — "
            "a fully silent clip means synthesis failed"
        ) from exc
    return int(round(seconds * 1000))


def trim_clip(src: Path, dst: Path, *, ffmpeg: str = FFMPEG) -> None:
    """Trim edge silence, then canonicalise to 24 kHz mono s16."""
    audio_filter = (
        f"{_TRIM},areverse,{_TRIM},areverse,"
        f"aresample={SAMPLE_RATE},aformat=sample_fmts=s16:channel_layouts=mono"
    )
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-af",
            audio_filter,
            "-c:a",
            "pcm_s16le",
            str(dst),
        ]
    )


# --------------------------------------------------------------------------
# timeline
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TimelineEntry:
    id: str
    start_ms: int
    end_ms: int
    speaker: str
    voice: str
    type: str
    text: str
    translation: str | None = None
    takes: int = 1
    pause_after_ms: int = 0
    answer_pause_ms: int | None = None

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @classmethod
    def from_dict(cls, data: dict) -> TimelineEntry:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def as_dict(self) -> dict:
        out: dict = {
            "id": self.id,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "speaker": self.speaker,
            "voice": self.voice,
            "type": self.type,
            "text": self.text,
            "takes": self.takes,
            "pause_after_ms": self.pause_after_ms,
        }
        if self.translation:
            out["translation"] = self.translation
        if self.answer_pause_ms is not None:
            out["answer_pause_ms"] = self.answer_pause_ms
        return out


def build_timeline(
    script: LessonScript, durations: dict[str, int]
) -> tuple[list[TimelineEntry], int]:
    """Lay segments on the clock using measured clip durations + authored gaps.

    A repeated segment occupies its takes plus the intra-take gaps; the timeline
    entry covers the first take's start to the last take's end, so transcript
    highlighting does not flicker during a drill.
    """
    entries: list[TimelineEntry] = []
    cursor = 0
    for seg in script.segments:
        if seg.id not in durations:
            raise AssemblyError(f"no rendered audio for segment {seg.id!r}")
        clip_ms = durations[seg.id]
        gaps = seg.gaps()
        start = cursor
        end = start + clip_ms * seg.takes + sum(gaps[:-1])
        entries.append(
            TimelineEntry(
                id=seg.id,
                start_ms=start,
                end_ms=end,
                speaker=seg.speaker,
                voice=script.roles[seg.speaker].voice,
                type=seg.type,
                text=seg.text,
                translation=seg.translation,
                takes=seg.takes,
                pause_after_ms=seg.pause_after_ms,
                answer_pause_ms=seg.answer_pause_ms if seg.type == "check" else None,
            )
        )
        cursor = end + gaps[-1]
    return entries, cursor


# --------------------------------------------------------------------------
# filter graph
# --------------------------------------------------------------------------


def _events(script: LessonScript) -> list[tuple[str, object]]:
    """Ordered ('clip', segment_id) / ('gap', ms) events for the whole lesson."""
    events: list[tuple[str, object]] = []
    for seg in script.segments:
        for gap in seg.gaps():
            events.append(("clip", seg.id))
            if gap > 0:
                events.append(("gap", gap))
    return events


def _graph(script: LessonScript, trimmed: dict[str, Path]) -> tuple[str, list[str]]:
    """filter_complex script + the -i argument list (one input per take)."""
    lines: list[str] = []
    labels: list[str] = []
    inputs: list[str] = []
    for i, (kind, value) in enumerate(_events(script)):
        if kind == "clip":
            inputs.append(str(trimmed[str(value)]))
            idx = len(inputs) - 1
            lines.append(
                f"[{idx}:a]asetpts=N/SR/TB,aresample={SAMPLE_RATE},"
                f"aformat=sample_fmts=s16:channel_layouts=mono[c{i}]"
            )
            labels.append(f"[c{i}]")
        else:
            lines.append(f"anullsrc=r={SAMPLE_RATE}:cl=mono:d={int(value) / 1000:.3f}[g{i}]")
            labels.append(f"[g{i}]")
    lines.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]")
    return ";\n".join(lines), inputs


# --------------------------------------------------------------------------
# loudness
# --------------------------------------------------------------------------


def measure_loudness(path: Path, *, ffmpeg: str = FFMPEG) -> dict:
    audio_filter = (
        f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}:print_format=json"
    )
    proc = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-nostats",
            "-i",
            str(path),
            "-af",
            audio_filter,
            "-f",
            "null",
            "-",
        ]
    )
    blocks = _JSON_BLOCK.findall(proc.stderr or "")
    if not blocks:
        raise AssemblyError("loudnorm printed no JSON — is the audio silent?")
    return json.loads(blocks[-1])


def _encode(
    src: Path, dst: Path, *, bitrate: str, measured: dict | None = None, ffmpeg: str = FFMPEG
) -> None:
    filters: list[str] = []
    if measured is not None:
        filters.append(
            f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}"
            f":measured_I={measured['input_i']}"
            f":measured_TP={measured['input_tp']}"
            f":measured_LRA={measured['input_lra']}"
            f":measured_thresh={measured['input_thresh']}"
            f":offset={measured['target_offset']}:linear=true"
        )
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
    ]
    if filters:
        cmd += ["-af", ",".join(filters)]
    cmd += [
        "-c:a",
        "libmp3lame",
        "-b:a",
        bitrate,
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "1",
        str(dst),
    ]
    _run(cmd)


# --------------------------------------------------------------------------
# metadata helpers
# --------------------------------------------------------------------------


def script_hash(script: LessonScript) -> str:
    """Stable hash of the lesson's semantic content (cache/manifest key)."""
    return hashlib.sha256(script.model_dump_json().encode("utf-8")).hexdigest()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _write_json(path: Path, data: object) -> None:
    _write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


# --------------------------------------------------------------------------
# the assembler
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AssemblyResult:
    lesson_id: str
    audio_path: Path
    timeline_path: Path
    srt_path: Path
    manifest_path: Path
    lines_dir: Path
    timeline: list[TimelineEntry]
    duration_ms: int
    assembled_ms: int
    loudness: dict = field(default_factory=dict)
    script_hash: str = ""
    reused: bool = False

    @property
    def drift_ms(self) -> int:
        return self.assembled_ms - self.duration_ms


def _reusable(out_dir: Path, digest: str, segments: int) -> tuple[list[dict], dict] | None:
    """Existing artefacts for this exact script, if they are complete."""
    manifest_path = out_dir / "manifest.json"
    timeline_path = out_dir / "timeline.json"
    if not (manifest_path.exists() and timeline_path.exists()):
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = json.loads(timeline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if manifest.get("script_hash") != digest:
        return None
    if manifest.get("segments") != segments:
        return None
    if len(entries) != segments:
        return None
    return entries, manifest


def assemble(
    script: LessonScript,
    line_paths: dict[str, Path],
    out_dir: Path,
    *,
    voices: dict[str, VoiceProfile] | None = None,
    level: LevelProfile | None = None,
    keep_build: bool = False,
    reuse: bool = True,
    engine: str = "voiceStudio/omnivoice",
) -> AssemblyResult:
    """Assemble one lesson from its per-segment wavs.

    Writes into ``out_dir``: ``lesson.mp3``, ``timeline.json``, ``lesson.srt``,
    ``manifest.json`` and ``lines/<id>.mp3``. Intermediate trimmed wavs live in
    ``out_dir/build`` and are removed unless ``keep_build``.

    With ``reuse=True`` (the default) an existing assembly whose manifest quotes
    the same script hash is returned untouched, so `make render` after a cache
    hit costs no ffmpeg time at all.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = script_hash(script)
    audio_path = out_dir / "lesson.mp3"

    if reuse:
        found = _reusable(out_dir, digest, len(script.segments))
        if found is not None and audio_path.exists():
            raw_entries, manifest = found
            timeline = [TimelineEntry.from_dict(e) for e in raw_entries]
            return AssemblyResult(
                lesson_id=script.id,
                audio_path=audio_path,
                timeline_path=out_dir / "timeline.json",
                srt_path=out_dir / "lesson.srt",
                manifest_path=out_dir / "manifest.json",
                lines_dir=out_dir / "lines",
                timeline=timeline,
                duration_ms=int(manifest["duration_ms"]),
                assembled_ms=int(manifest["duration_ms"]),
                loudness={"input_i": manifest.get("measured_lufs")},
                script_hash=digest,
                reused=True,
            )

    build = out_dir / "build"
    if build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True)

    lines_dir = out_dir / "lines"
    lines_dir.mkdir(exist_ok=True)

    missing = [seg.id for seg in script.segments if seg.id not in line_paths]
    if missing:
        raise AssemblyError(f"no rendered wav for: {', '.join(missing)}")

    # 1. trim + canonicalise + measure every clip
    trimmed: dict[str, Path] = {}
    durations: dict[str, int] = {}
    for seg in script.segments:
        src = Path(line_paths[seg.id])
        if not src.exists():
            raise AssemblyError(f"segment {seg.id!r}: {src} does not exist")
        dst = build / f"{seg.id}.wav"
        trim_clip(src, dst)
        ms = probe_duration_ms(dst)
        if ms <= 0:
            raise AssemblyError(
                f"segment {seg.id!r} trimmed to {ms} ms — synthesis probably produced silence"
            )
        trimmed[seg.id] = dst
        durations[seg.id] = ms

    # 2. timeline from measured durations
    timeline, total_ms = build_timeline(script, durations)

    # 3. concatenate with exact silence
    graph, inputs = _graph(script, trimmed)
    graph_file = build / "graph.txt"
    graph_file.write_text(graph, encoding="utf-8")
    raw = build / "lesson.raw.wav"
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
    for path in inputs:
        cmd += ["-i", path]
    cmd += [
        "-filter_complex_script",
        str(graph_file),
        "-map",
        "[out]",
        "-c:a",
        "pcm_s16le",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "1",
        str(raw),
    ]
    _run(cmd)

    assembled_ms = probe_duration_ms(raw)
    drift = assembled_ms - total_ms
    if abs(drift) > MAX_DRIFT_MS:
        raise AssemblyError(
            f"timeline drift {drift:+d} ms (computed {total_ms} ms, assembled {assembled_ms} ms) "
            f"exceeds {MAX_DRIFT_MS} ms — transcript sync would be wrong"
        )

    # 4. loudness: measure on the concatenated stream, then apply
    measured = measure_loudness(raw)
    _encode(raw, audio_path, bitrate=LESSON_BITRATE, measured=measured)

    # 5. per-segment clips for drill/replay + offline
    for seg in script.segments:
        _encode(trimmed[seg.id], lines_dir / f"{seg.id}.mp3", bitrate=LINE_BITRATE)

    # 6. sidecars
    timeline_path = out_dir / "timeline.json"
    _write_json(timeline_path, [entry.as_dict() for entry in timeline])

    srt_path = out_dir / "lesson.srt"
    cues = [
        Cue(e.start_ms, e.end_ms, e.text, e.translation)
        for e in timeline
        if e.type != "check"  # the question is audio; the answer is the UI's job
    ]
    _write(srt_path, to_srt(cues))

    manifest_path = out_dir / "manifest.json"
    if voices is None:
        voice_ids: dict = {role: member.voice for role, member in script.roles.items()}
    else:
        voice_ids = {
            role: {
                "voice": member.voice,
                "profile_id": resolve_voice(voices, member.voice).profile_id,
                "seed": resolve_voice(voices, member.voice).seed,
            }
            for role, member in script.roles.items()
        }
    manifest = {
        "schema": "lesson-audio/v1",
        "lesson_id": script.id,
        "level": script.level,
        "script_hash": script_hash(script),
        "engine": engine,
        "rendered_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sample_rate": SAMPLE_RATE,
        "bitrate": LESSON_BITRATE,
        "target_lufs": TARGET_I,
        "measured_lufs": float(measured["input_i"]),
        "duration_ms": total_ms,
        "segments": len(script.segments),
        "durations": durations,
        "voice_ids": voice_ids,
        "level_default_speed": level.default_speed if level else None,
    }
    _write_json(manifest_path, manifest)

    if not keep_build:
        shutil.rmtree(build, ignore_errors=True)

    return AssemblyResult(
        lesson_id=script.id,
        audio_path=audio_path,
        timeline_path=timeline_path,
        srt_path=srt_path,
        manifest_path=manifest_path,
        lines_dir=lines_dir,
        timeline=timeline,
        duration_ms=total_ms,
        assembled_ms=assembled_ms,
        loudness=measured,
        script_hash=manifest["script_hash"],
    )
