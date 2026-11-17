"""`python -m v5 ...` — the operational surface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import ROOT, missing_profiles
from .validate import validate_file

LESSONS_DIR = ROOT / "content" / "lessons"
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

    for name in ("render", "serve", "corpus"):
        p = sub.add_parser(name, help=f"{name} ({NOT_YET})")
        p.set_defaults(func=lambda _a: (print(NOT_YET), 2)[1])

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
