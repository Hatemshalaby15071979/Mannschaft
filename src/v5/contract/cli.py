"""`python -m v5 ...` — the operational surface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import ROOT, load_voices, missing_profiles
from ..render import (
    AssemblyFailed,
    AudioCache,
    LessonNotFound,
    PipelineError,
    RenderFailed,
    ValidationFailed,
    VoicesNotReady,
    VoiceStudioClient,
    assemble,
    render_lesson_to_disk,
    renderable,
)
from .validate import validate_file

LESSONS_DIR = ROOT / "content" / "lessons"
AUDIO_DIR = ROOT / "content" / "audio"
NOT_YET = "not implemented yet — see v5/STATUS.md for the current milestone"

M4_HELP = """
Create them in VoiceStudio → Voice Design (milestone M4), then put the
returned profile id into v5/config/voices.toml. This is the human gate:
an unmapped voice renders in the engine default and every character
sounds identical."""


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


# --------------------------------------------------------------------------
# render / assemble
# --------------------------------------------------------------------------


def _report_assembly(result) -> None:
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


def _cmd_render(args: argparse.Namespace) -> int:
    """Synthesise every segment, then assemble the lesson audio."""
    try:
        outcome = render_lesson_to_disk(
            args.id,
            lessons_dir=LESSONS_DIR,
            audio_dir=AUDIO_DIR,
            cache=AudioCache(),
            client=VoiceStudioClient(),
            voices=load_voices(),
            assemble_audio=not args.segments_only,
        )
    except LessonNotFound as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValidationFailed as exc:
        for issue in exc.issues:
            print(f"  {issue}")
        print(f"{args.id}: refusing to render — validation failed", file=sys.stderr)
        return 1
    except VoicesNotReady as exc:
        print(f"cannot render: {exc}", file=sys.stderr)
        for key in exc.missing:
            print(f"  - {key}", file=sys.stderr)
        print(M4_HELP, file=sys.stderr)
        return 2
    except RenderFailed as exc:
        print(f"render failed: {exc}", file=sys.stderr)
        print("is VoiceStudio running on 127.0.0.1:3900?", file=sys.stderr)
        return 3
    except AssemblyFailed as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except PipelineError as exc:
        print(f"{args.id}: {exc}", file=sys.stderr)
        return 1

    print(
        f"{outcome.lesson_id}: {outcome.segments} segments — "
        f"{outcome.cached} from cache, {outcome.synthesised} synthesised"
    )
    print(f"segments: {outcome.lines_dir}")
    print(f"cache: {outcome.cache_stats}")
    if outcome.assembly is not None:
        _report_assembly(outcome.assembly)
    return 0


def _cmd_assemble(args: argparse.Namespace) -> int:
    """Re-assemble an already-rendered lesson (no synthesis)."""
    try:
        script, voices, level = renderable(
            args.id, lessons_dir=LESSONS_DIR, voices=load_voices()
        )
    except LessonNotFound as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValidationFailed as exc:
        for issue in exc.issues:
            print(f"  {issue}")
        print(f"{args.id}: refusing to assemble — validation failed", file=sys.stderr)
        return 1
    except VoicesNotReady as exc:
        print(f"cannot assemble: {exc}", file=sys.stderr)
        for key in exc.missing:
            print(f"  - {key}", file=sys.stderr)
        print(M4_HELP, file=sys.stderr)
        return 2
    except PipelineError as exc:
        print(f"{args.id}: {exc}", file=sys.stderr)
        return 1

    lines_dir = AUDIO_DIR / script.id / "lines"
    missing = [seg.id for seg in script.segments if not (lines_dir / f"{seg.id}.wav").exists()]
    if missing:
        print(
            f"cannot assemble: no rendered wav for {len(missing)} segment(s), e.g. "
            f"{', '.join(missing[:5])} — run `make render ID={script.id}` first",
            file=sys.stderr,
        )
        return 1

    try:
        result = assemble(
            script,
            {seg.id: lines_dir / f"{seg.id}.wav" for seg in script.segments},
            AUDIO_DIR / script.id,
            voices=voices,
            level=level,
            keep_build=False,
        )
    except PipelineError as exc:
        print(f"assembly failed: {exc}", file=sys.stderr)
        return 4

    _report_assembly(result)
    return 0


# --------------------------------------------------------------------------
# serve
# --------------------------------------------------------------------------


def _cmd_serve(args: argparse.Namespace) -> int:
    from ..server import PORT, assert_loopback, create_app

    try:
        host = assert_loopback(args.host)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    import uvicorn

    port = args.port or PORT
    app = create_app()
    print(f"serving v5 on http://{host}:{port}  (docs: /api/docs)")
    uvicorn.run(app, host=host, port=port, log_level=args.log_level)
    return 0


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

    p_serve = sub.add_parser("serve", help="run the localhost server on 127.0.0.1:8766")
    p_serve.add_argument("--host", default="127.0.0.1", help="must be a loopback address")
    p_serve.add_argument("--port", type=int, default=0, help="default 8766")
    p_serve.add_argument("--log-level", default="info")
    p_serve.set_defaults(func=_cmd_serve)

    p_corpus = sub.add_parser("corpus", help=f"corpus ({NOT_YET})")
    p_corpus.set_defaults(func=lambda _a: (print(NOT_YET), 2)[1])

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
