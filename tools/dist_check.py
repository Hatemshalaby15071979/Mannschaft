#!/usr/bin/env python3
"""Verify a distribution actually works from a clean directory.

    python3 tools/dist_check.py [--keep]

Builds the core zip, unzips it into a fresh temp directory, then runs:

* `python3 -m v5 --help` with PYTHONPATH=src
* `python3 -m v5 validate --all`
* `python3 -m pytest`
* a live health probe against `python3 -m v5 serve` on an ephemeral loopback port

The temp directory is deleted afterwards unless --keep is passed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def _run(cwd: Path, args: list[str], env: dict | None = None) -> None:
    print(f"$ {' '.join(args)}  (cwd={cwd})")
    merged = {**os.environ, "PYTHONPATH": "src", **(env or {})}
    subprocess.run(args, cwd=cwd, env=merged, check=True)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools/dist_check.py")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)

    tmp = Path(tempfile.mkdtemp(prefix="v5-dist-check-"))
    archive = tmp / "v5-core.zip"
    install = tmp / "install"
    install.mkdir()

    try:
        subprocess.run(
            [PY, str(ROOT / "tools" / "package.py"), "--kind", "core", "--out", str(archive)],
            check=True,
        )
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(install)

        _run(install, [PY, "-m", "v5", "--help"])
        _run(install, [PY, "-m", "v5", "validate", "--all"])
        _run(install, [PY, "-m", "pytest", "-q"])

        port = _free_port()
        env = {**os.environ, "PYTHONPATH": "src"}
        server = subprocess.Popen(
            [PY, "-m", "v5", "serve", "--host", "127.0.0.1", "--port", str(port)],
            cwd=install,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            health = None
            for _ in range(60):
                if server.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/health", timeout=1.0
                    ) as response:
                        health = json.loads(response.read().decode("utf-8"))
                        break
                except OSError:
                    time.sleep(0.25)
            if health is None:
                output = server.stdout.read() if server.stdout else ""
                raise RuntimeError(f"server did not answer /api/health\n{output}")
            print("health:", json.dumps(health, ensure_ascii=False))
            if health.get("app") != "ok":
                raise RuntimeError("health did not report app=ok")
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()

        print("dist-check: OK")
        return 0
    finally:
        if args.keep:
            print(f"kept {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
