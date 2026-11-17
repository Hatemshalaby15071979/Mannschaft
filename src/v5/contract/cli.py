"""`python -m v5 ...` — the operational surface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import ROOT, load_levels, load_voices, missing_profiles
from ..render import (
    AssemblyError,
    AudioCache,
    RenderError,
    VoiceNotReady,
    VoiceStudioClient,
    assemble,
    render_lesson,
)
from .validate import has_errors, validate_file

LESSONS_DIR = ROOT / "content" / "lessons"
AUDIO_DIR = ROOT / "content" / "audio"
NOT_YET = "not implemented yet — see v5/STATUS.md for the current milestone"


def _cmd_validate(args: argparse.Namespace) -> int:
    paths: list[Path] = [Path(p) for p in args.paths]
    if args.all or not paths:
        paths = sorted(LESSONS_DIR.glob("*.lesson.json"))
    if not paths:
        print(f"no lessons found in {LESSONS_DIR}", file=sys.stderr)
        return 1

    total_errors = 0
    total_warnings = 0
    for path in paths:
        _script, issues = validate_file(path)
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        total_errors += len(errors)
        total_warnings += len(warnings)
        status = "FAIL" if errors else "ok"
        print(f"{status:5} {path.name}  ({len(errors)} errors, {len(warnings)} warnings)")
        for issue in issues:
            print(f"       {issue}")

    print(f"\n{len(paths)} lesson(s): {total_errors} error(s), {total_warnings} warning(s)")
    if args.strict and total_warnings:
        return 1
    return 1 if total_errors else 0


def _cmd_health(_args: argparse.Namespace) -> int:
    missing = missing_profiles()
    if missing:
        print("voices NOT ready — create these in VoiceStudio → Design, then set profile_id:")
        for key in missing:
            print(f"  - {key}")
        return 1
    print("all voices configured")
    return 0


def _load_renderable(lesson_id: str, verb: str = "render") -> tuple[object, dict, object] | int:
    """Shared guard for render/assemble: valid lesson + all voices configured."""
    path = LESSONS_DIR / f"{lesson_id}.lesson.json"
    if not path.exists():
        print(f"no such lesson: {path}", file=sys.stderr)
        return 1

    # Invariant 7: audio is never generated from content that fails validation.
    script, issues = validate_file(path)
    for issue in issues:
        print(f"  {issue}")
    if script is None or has_errors(issues):
        print(f"{lesson_id}: refusing to {verb} — validation failed", file=sys.stderr)
        return 1

    voices = load_voices()
    missing = missing_profiles(voices)
    if missing:
        print(f"cannot {verb}: these voices have no profile_id yet:", file=sys.stderr)
        for key in missing:
            print(f"  - {key}", file=sys.stderr)
        print(
            "\nCreate them in VoiceStudio → Voice Design (milestone M4), then put the\n"
            "returned profile id into v5/config/voices.toml. This is the human gate:\n"
            "an unmapped voice renders in the engine default and every character\n"
            "sounds identical.",
            file=sys.stderr,
        )
        return 2

    return script, voices, load_levels()[script.level]


def _cmd_render(args: argparse.Namespace) -> int:
    """Synthesise every segment, then assemble the lesson audio."""
    loaded = _load_renderable(args.id)
    if isinstance(loaded, int):
        return loaded
    script, voices, level = loaded

    cache = AudioCache()
    client = VoiceStudioClient()
    lines_dir = AUDIO_DIR / script.id / "lines"

    try:
        results = render_lesson(script, voices, level, cache, client, lines_dir)
    except VoiceNotReady as exc:
        print(f"cannot render: {exc}", file=sys.stderr)
        return 2
    except RenderError as exc:
        print(f"render failed: {exc}", file=sys.stderr)
        print("is VoiceStudio running on 127.0.0.1:3900?", file=sys.stderr)
        return 3

    hits = sum(1 for r in results if r.cached)
    print(
        f"{script.id}: {len(results)} segments — "
        f"{hits} from cache, {len(results) - hits} synthesised"
    )
    print(f"segments: {lines_dir}")
    print(f"cache: {cache.stats}")

    if args.segments_only:
        return 0
    return _run_assembly(script, voices, level, lines_dir)


def _run_assembly(script, voices, level, lines_dir) -> int:
    out_dir = AUDIO_DIR / script.id
    try:
        result = assemble(
            script,
            {seg.id: lines_dir / f"{seg.id}.wav" for seg in script.segments},
            out_dir,
            voices=voices,
            level=level,
            keep_build=False,
        )
    except AssemblyError as exc:
        print(f"assembly failed: {exc}", file=sys.stderr)
        return 4

    if result.reused:
        print(f"assembly: up to date ({result.duration_ms / 1000:.1f}s, script unchanged)")
    else:
        lufs = result.loudness.get("input_i")
        print(
            f"assembly: {result.duration_ms / 1000:.1f}s, "
            f"{lufs} LUFS source → {result.drift_ms:+d} ms drift"
        )
    print(f"lesson:  {result.audio_path}")
    print(f"timeline: {result.timeline_path}")
    print(f"srt:     {result.srt_path}")
    return 0


def _cmd_assemble(args: argparse.Namespace) -> int:
    """Re-assemble an already-rendered lesson (no synthesis)."""
    loaded = _load_renderable(args.id, verb="assemble")
    if isinstance(loaded, int):
        return loaded
    script, voices, level = loaded

    lines_dir = AUDIO_DIR / script.id / "lines"
    missing = [seg.id for seg in script.segments if not (lines_dir / f"{seg.id}.wav").exists()]
    if missing:
        print(
            f"cannot assemble: no rendered wav for {len(missing)} segment(s), e.g. "
            f"{', '.join(missing[:5])} — run `make render ID={script.id}` first",
            file=sys.stderr,
        )
        return 1
    return _run_assembly(script, voices, level, lines_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v5")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate", help="validate lesson scripts")
    p_val.add_argument("paths", nargs="*")
    p_val.add_argument("--all", action="store_true")
    p_val.add_argument("--strict", action="store_true", help="warnings fail too")
    p_val.set_defaults(func=_cmd_validate)

    p_health = sub.add_parser("health", help="check voice profiles are configured")
    p_health.set_defaults(func=_cmd_health)

    p_render = sub.add_parser("render", help="render one lesson's segments and assemble it")
    p_render.add_argument("id", metavar="ID", help="lesson id, e.g. A2-01")
    p_render.add_argument(
        "--segments-only", action="store_true", help="synthesise but do not assemble"
    )
    p_render.set_defaults(func=_cmd_render)

    p_asm = sub.add_parser("assemble", help="re-assemble an already-rendered lesson")
    p_asm.add_argument("id", metavar="ID", help="lesson id, e.g. A2-01")
    p_asm.set_defaults(func=_cmd_assemble)

    for name in ("serve", "corpus"):
        p = sub.add_parser(name, help=f"{name} ({NOT_YET})")
        p.set_defaults(func=lambda _a: (print(NOT_YET), 2)[1])

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
