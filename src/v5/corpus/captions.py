"""Stage B — word-timed captions (plan §8.2).

Parse YouTube json3 caption streams into `words` rows. Caption download is
injectable (`fetch` callable) so tests use a local fixture, never the network.
Only subtitles are pulled — never the video.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from . import db

ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = ROOT / "content" / "corpus" / "cache"

Fetcher = Callable[[str, Path], Path | None]


def parse_json3(doc: dict, video_id: str) -> list[dict]:
    """Flatten a json3 caption document to word rows.

    json3 `events` carry `segs`; a seg's `utf8` is a word or a fragment. Each
    event has `tStartMs` and `dDurationMs`. We split each event's seg text into
    whitespace tokens and distribute the event duration evenly across them —
    good enough for 700 ms boundary detection, which is what stage C needs.
    """
    words: list[dict] = []
    idx = 0
    for line_idx, event in enumerate(doc.get("events") or []):
        if "segs" not in event:
            continue
        text = "".join(seg.get("utf8", "") for seg in event["segs"])
        toks = text.split()
        if not toks:
            continue
        start = int(event.get("tStartMs", 0))
        dur = int(event.get("dDurationMs", 0))
        per = dur / len(toks) if toks else 0
        for n, tok in enumerate(toks):
            words.append(
                {
                    "video_id": video_id,
                    "idx": idx,
                    "start_ms": int(start + n * per),
                    "end_ms": int(start + (n + 1) * per),
                    "token": tok,
                    "line_idx": line_idx,
                }
            )
            idx += 1
    return words


def yt_dlp_fetch(video_id: str, cache_dir: Path) -> Path | None:
    """Default fetcher: download `de` json3 captions for one video, no video.

    Returns the json3 path, or None when no German caption stream exists.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{video_id}.de.json3"
    if target.exists() and target.stat().st_size > 0:
        return target  # resumable: already fetched
    pattern = str(cache_dir / f"{video_id}.%(ext)s")
    cmd = [
        "yt-dlp", "--skip-download", "--write-auto-subs", "--write-subs",
        "--sub-langs", "de,de-orig", "--sub-format", "json3", "--no-update",
        "-o", pattern, f"https://www.youtube.com/watch?v={video_id}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0 or not target.exists():
        return None
    return target


def build_words(
    conn,
    *,
    video_ids: list[str] | None = None,
    cache_dir: Path = CACHE_DIR,
    fetch: Fetcher = yt_dlp_fetch,
    limit: int | None = None,
) -> dict:
    """Run stage B. Returns processed/failed counts."""
    ids = video_ids if video_ids is not None else db.caption_video_ids(conn)
    if limit is not None:
        ids = ids[:limit]
    ok = failed = 0
    for vid in ids:
        path = fetch(vid, cache_dir)
        if path is None:
            failed += 1
            conn.execute("UPDATE videos SET has_de_caption=0 WHERE id=?", (vid,))
            conn.commit()
            continue
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            failed += 1
            continue
        db.replace_words(conn, vid, parse_json3(doc, vid))
        conn.commit()
        ok += 1
    return {"attempted": len(ids), "ok": ok, "failed": failed, "words": db.word_count(conn)}


if __name__ == "__main__":  # pragma: no cover
    conn = db.connect()
    print(json.dumps(build_words(conn), ensure_ascii=False, indent=2))
