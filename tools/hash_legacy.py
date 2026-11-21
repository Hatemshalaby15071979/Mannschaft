#!/usr/bin/env python3
"""V6 guardrail-1 hash snapshot.

Usage:
    python3 tools/hash_legacy.py [ROOT] [OUT]

Hashes every file in the frozen (legacy) set with SHA-256 and writes one
"<sha256>  <path>" line per file, sorted by path. Run before Phase 0 and again
after Phase 5; the diff must be empty — that is a release gate.

The frozen set is everything V6-EXECUTION-PROMPT.md §3.1 declares off limits:
the three archive trees, the rendered audio, the committed corpus, the voice
config, and the existing render/adapters/contract/corpus/server modules.

Two files are deliberately carved out of the frozen set — they are the
sanctioned additive mutation surface for V6:

    v5/src/v5/server/app.py        (new GET routes)
    v5/src/v5/client/js/main.js    (new screen routes)

Everything else in the tree is frozen for the duration of V6.
"""

import hashlib
import pathlib
import sys

# Relative to ROOT. Directories are walked recursively; single files are
# hashed as-is.
FROZEN = [
    "v3",
    "v4",
    "webapp",
    "v5/content/audio",
    "v5/content/corpus/clips.jsonl",
    "v5/config/voices.toml",
    "v5/src/v5/render",
    "v5/src/v5/adapters",
    "v5/src/v5/contract",
    "v5/src/v5/corpus",
    "v5/src/v5/server",
]

# Carved out of the frozen set: the two sanctioned additive mutation points.
EXCLUDE_FILES = {
    "v5/src/v5/server/app.py",
    "v5/src/v5/client/js/main.js",
}

_CHUNK = 1 << 20  # 1 MiB


def iter_frozen_files(root: pathlib.Path):
    seen = set()
    for rel in FROZEN:
        p = root / rel
        if not p.exists():
            print(f"WARNING: {rel} does not exist, skipping", file=sys.stderr)
            continue
        if p.is_file():
            if rel in EXCLUDE_FILES:
                continue
            yield rel
            seen.add(rel)
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if not f.is_file():
                    continue
                rp = f.relative_to(root).as_posix()
                if rp in EXCLUDE_FILES:
                    continue
                yield rp
        else:
            print(f"WARNING: {rel} is neither file nor dir, skipping", file=sys.stderr)


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    root = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else pathlib.Path.cwd()
    out = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else None

    lines = []
    for rp in sorted(set(iter_frozen_files(root))):
        lines.append(f"{sha256_file(root / rp)}  {rp}\n")

    text = "".join(lines)
    if out is not None:
        out.write_text(text)
    else:
        sys.stdout.write(text)
    print(f"# {len(lines)} files hashed", file=sys.stderr)


if __name__ == "__main__":
    main()