#!/usr/bin/env python3
"""Build the two V6 distributions.

    python3 tools/package.py --kind core --out dist/v5-core.zip
    python3 tools/package.py --kind full --out dist/v5-full.zip

`core` is code + authored lessons + derived JSON + config + client assets +
README. It excludes rendered audio and raw corpus intermediates, and must stay
under 20 MB. `full` adds `content/audio/` and the corpus working files; it is
built locally on demand and never in CI.

Archive paths are relative to the v5 project root, so unzipping into an empty
directory yields a working tree with `src/` at the top.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CORE_DIRS = [
    "src",
    "tests",
    "config",
    "tools",
    ".github",
    "content/lessons",
    "content/cards",
    "content/dictionary",
]
CORE_FILES = [
    "Makefile",
    "pyproject.toml",
    "README.md",
    "STATUS.md",
    "content/lesson_media.json",
    "content/lesson_media.overrides.json",
    "content/corpus/clips.jsonl",
]
FULL_EXTRA_DIRS = ["content/audio", "content/corpus"]

EXCLUDE_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".git",
    "node_modules",
    "dist",
    "build",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".egg-info"}
EXCLUDE_PATH_PARTS = {"user", "audio/.cache"}

CORE_LIMIT_BYTES = 20 * 1024 * 1024


def _excluded(rel: Path) -> bool:
    parts = set(rel.parts)
    if parts & EXCLUDE_DIR_NAMES:
        return True
    if any(str(rel).endswith(suffix) for suffix in EXCLUDE_SUFFIXES):
        return True
    text = rel.as_posix()
    return any(part in text for part in EXCLUDE_PATH_PARTS)


def _files_for(dirs: list[str], files: list[str]) -> list[Path]:
    out: list[Path] = []
    for name in files:
        path = ROOT / name
        if path.is_file():
            out.append(path)
        else:
            print(f"warning: missing {name}", file=sys.stderr)
    for name in dirs:
        base = ROOT / name
        if not base.exists():
            print(f"warning: missing {name}", file=sys.stderr)
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and not _excluded(path.relative_to(ROOT)):
                out.append(path)
    # De-duplicate while preserving a stable order.
    seen = set()
    unique = []
    for path in out:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def build(kind: str, out: Path) -> tuple[int, str]:
    dirs = list(CORE_DIRS)
    files = list(CORE_FILES)
    if kind == "full":
        dirs += FULL_EXTRA_DIRS
    elif kind != "core":
        raise ValueError(f"unknown kind {kind!r}")

    paths = _files_for(dirs, files)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in paths:
            archive.write(path, path.relative_to(ROOT).as_posix())

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    return out.stat().st_size, digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools/package.py")
    parser.add_argument("--kind", choices=("core", "full"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    size, digest = build(args.kind, args.out)
    print(f"{args.kind}: {args.out}  {size / 1024 / 1024:.2f} MiB  sha256 {digest}")
    if args.kind == "core" and size > CORE_LIMIT_BYTES:
        print(f"error: core zip exceeds {CORE_LIMIT_BYTES} bytes", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
