"""Stage A — the manifest (plan §8.1).

Fetch each playlist's flat entry list with yt-dlp, deduplicate across the 22
playlists, and write one `videos` row per unique video. No video/audio is
downloaded. The fetch function is injectable so tests never touch the network.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from . import db

ROOT = Path(__file__).resolve().parents[3]
PLAYLISTS_PATH = ROOT / "config" / "playlists.toml"

# The 22 Easy German playlists (confirmed live 2026-11-17). level_tag comes from
# the playlist name; None means "not a level playlist" (grammar, cities, …).
PLAYLISTS: tuple[tuple[str, str, str | None], ...] = (
    ("PLk1fjOl39-51j7LVOP09IDktNFItfC0FZ", "Street Interviews", "B1"),
    ("PLk1fjOl39-51vSJC0B3VdUtNeX80H541u", "German Compared", None),
    ("PLk1fjOl39-519ioxhETvosO8nUPAk4iF0", "German Verbs", "A2"),
    ("PLk1fjOl39-53c2XjWHTFwjYPFaalzvj7A", "Salaries in Germany", "B2"),
    ("PLk1fjOl39-510b2pluGVqLsQxng_IUSUU", "What are you doing today", "A2"),
    ("PLk1fjOl39-50w2RABiN_MaMSPsuo6ffFN", "Germany Explained", "B2"),
    ("PLk1fjOl39-52ihy3oEHgb6-fI7o5rOww8", "Easy German Grammar", None),
    ("PLk1fjOl39-50hTI9yYPnmTIqL_1zWJI1a", "German C2", "C2"),
    ("PLk1fjOl39-53Sy0xxIHKnQoZLHWb8rbl9", "Slow German Videos", "A2"),
    ("PLk1fjOl39-52AXeDQz2WPVv-wZnkjldoX", "Easy German Podcast", "B2"),
    ("PLk1fjOl39-50RITUTsTOLTnBoTRlxwroe", "Easy German Vlogs", "B2"),
    ("PLk1fjOl39-50JyQ3TG_BrJFB8n4KBaAYn", "Cities D/A/CH", None),
    ("PLk1fjOl39-528ICHMD7XU3JJDGvx6KLHO", "Switzerland", None),
    ("PLk1fjOl39-53i-HBUyGUXE2dIrxLgaqT4", "Austria", None),
    ("PLk1fjOl39-51CvkW5ay3Kk5OV8J016bnp", "German Dialects", None),
    ("PLk1fjOl39-51qucFNZjxnz6c3MzOmHzsq", "Our Favourites", None),
    ("PLk1fjOl39-5201BUdhtOM_x23poNvLouT", "German A2", "A2"),
    ("PLk1fjOl39-50kWobutO8NVFzbw9PHtbbg", "German A1", "A1"),
    ("PLk1fjOl39-53pjPz2VLCeu5vjOUMKZ22O", "German C1", "C1"),
    ("PLk1fjOl39-51lvdiuQYsLW-0aGIdNNknA", "German B2", "B2"),
    ("PLk1fjOl39-53yooogv6RaJAK29mx7nz1d", "German B1", "B1"),
    ("PLk1fjOl39-53GxQIn1Hxdouokf0J0SDpl", "Super Easy German", "A2"),
)

Fetcher = __import__("typing").Callable[[str], dict]


def yt_dlp_fetch(url: str) -> dict:
    """Default fetcher: `yt-dlp --flat-playlist --dump-single-json`."""
    cmd = [
        "yt-dlp", "--flat-playlist", "--dump-single-json", "--no-update",
        "--skip-download", url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)
    return json.loads(result.stdout)


def video_row(entry: dict, playlist_id: str, level_tag: str | None) -> dict:
    """Map one flat-playlist entry + its playlist into a `videos` row.

    Flat entries carry no caption flags, so `has_de_caption` is set optimistically
    from ` automatic_captions`/`subtitles` when present; stage B verifies by
    actually requesting the json3 stream and downgrades on failure.
    """
    auto = entry.get("automatic_captions") or {}
    subs = entry.get("subtitles") or {}
    has_de = int("de" in auto or "de" in subs)
    has_en = int("en" in auto or "en" in subs)
    kind = "manual" if "de" in subs else ("auto" if "de" in auto else None)
    stamp = entry.get("timestamp")
    upload = ""
    if stamp is not None:
        upload = time.strftime("%Y%m%d", time.gmtime(float(stamp)))
    return {
        "id": entry["id"],
        "title": entry.get("title") or "",
        "channel": entry.get("playlist_channel") or entry.get("channel") or "Easy German",
        "duration_s": int(entry.get("duration") or 0),
        "upload_date": upload,
        "level_tag": level_tag,
        "playlists": json.dumps([playlist_id]),
        "has_de_caption": has_de,
        "has_en_caption": has_en,
        "caption_kind": kind,
        "fetched_at": time.time(),
    }


def build_manifest(
    conn,
    *,
    playlists: tuple[tuple[str, str, str | None], ...] = PLAYLISTS,
    fetch: Fetcher = yt_dlp_fetch,
) -> dict:
    """Run stage A; return counts. `fetch(playlist_url) -> dump-single-json dict`."""
    seen_before = db.video_count(conn)
    errors: list[str] = []
    for pid, _name, level in playlists:
        url = f"https://www.youtube.com/playlist?list={pid}"
        try:
            doc = fetch(url)
        except Exception as exc:  # one bad playlist must not abort the other 21
            errors.append(f"{pid}: {exc}")
            continue
        for entry in doc.get("entries") or []:
            if not entry or not entry.get("id"):
                continue
            row = video_row(entry, pid, level)
            # Flat entries lack caption flags; assume German captions exist so
            # stage B tries them — Easy German auto-captions nearly everything.
            if not row["has_de_caption"]:
                row["has_de_caption"] = 1
                row["caption_kind"] = "auto"
            db.upsert_video(conn, row)
        conn.commit()
    return {
        "videos_before": seen_before,
        "videos_after": db.video_count(conn),
        "playlists": len(playlists),
        "errors": errors,
    }


if __name__ == "__main__":  # pragma: no cover
    conn = db.connect()
    stats = build_manifest(conn)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
