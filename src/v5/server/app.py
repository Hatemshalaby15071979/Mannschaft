"""FastAPI app: content API + byte-range audio + render jobs on 127.0.0.1.

Design constraints that shape this file:

* The server never renders inline. A render is queued, because a 10-minute
  lesson would otherwise hold an HTTP connection for 10 minutes and no progress
  would be visible.
* Audio goes through ``FileResponse``, which implements HTTP Range correctly
  (206 + ``Content-Range``, 416 when unsatisfiable). Seeking is the feature, so
  it is not hand-rolled.
* Nothing binds to anything but loopback. ``assert_loopback`` refuses the rest.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import mimetypes
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config import ROOT, load_voices, missing_profiles
from ..dictionary.lookup import lookup as dictionary_lookup
from ..events import EventStore
from ..media.manifest import load_manifest_cached
from ..render import (
    LessonNotFound,
    PipelineError,
    RenderOutcome,
    ValidationFailed,
    VoicesNotReady,
    render_lesson_to_disk,
    renderable,
)
from .catalog import Catalogue
from .health import DEFAULT_VOICESTUDIO_URL, probe
from .jobs import JobQueue
from .progress import ProgressStore

PORT = 8766
CORPUS_PATH = ROOT / "content" / "corpus" / "clips.jsonl"
MEDIA_PATH = ROOT / "content" / "lesson_media.json"
CARDS_DIR = ROOT / "content" / "cards"
DICTIONARY_PATH = ROOT / "content" / "dictionary" / "seed.json"
CLIENT_DIR = Path(__file__).resolve().parent.parent / "client"

# The client may post these; anything else is ignored by the model.
EVENT_KINDS = ("card_graded", "clip_opened")

# Python's mimetypes does not know .webmanifest on every platform; without this
# some browsers refuse the PWA manifest as application/octet-stream.
mimetypes.add_type("application/manifest+json", ".webmanifest")

# One structured line per request: timestamp, method, route, status, duration.
# A dedicated handler keeps the format stable whether the app runs under
# uvicorn, in tests, or from the CLI. No query string and no headers are logged.
_http_log = logging.getLogger("v5.http")
if not _http_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _http_log.addHandler(_handler)
    _http_log.setLevel(logging.INFO)
    _http_log.propagate = False


class ProgressUpdate(BaseModel):
    lesson_id: str = Field(min_length=1)
    # `seg_id` stays first-class for the v5 player. A card or clip event may not
    # have one (a `produce` card has no audio), so it is optional for events.
    seg_id: str | None = Field(default=None, min_length=1)
    position_ms: int = Field(default=0, ge=0)
    completed: bool = False
    event: str | None = None
    detail: dict | None = None


def assert_loopback(host: str) -> str:
    """Invariant 9: nothing binds to 0.0.0.0. Refuse anything non-loopback."""
    if host in ("localhost", "::1"):
        return host
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError(f"{host!r} is not an IP address; use 127.0.0.1") from exc
    if not address.is_loopback:
        raise ValueError(f"refusing to bind to {host} — this app is localhost-only")
    return host


_clip_counts: dict[str, tuple[float, int]] = {}


def _count_clips(path: Path) -> int:
    """Cheap, honest corpus size for the KPI tile. Cached by mtime."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return 0
    cached = _clip_counts.get(str(path))
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        with path.open(encoding="utf-8") as fh:
            count = sum(1 for line in fh if line.strip())
    except OSError:
        return 0
    _clip_counts[str(path)] = (mtime, count)
    return count


def make_render_fn(catalogue: Catalogue):
    """Bind the pipeline to this app's lesson/audio dirs.

    Without this, an app created with test directories would still render from
    the real `content/` tree — a test could quietly write to production audio.
    """

    def render(lesson_id: str, on_progress) -> RenderOutcome:
        return render_lesson_to_disk(
            lesson_id,
            lessons_dir=catalogue.lessons_dir,
            audio_dir=catalogue.audio_dir,
            on_progress=on_progress,
        )

    return render


def create_app(
    *,
    lessons_dir: Path | None = None,
    audio_dir: Path | None = None,
    progress_db: Path | None = None,
    voicestudio_url: str = DEFAULT_VOICESTUDIO_URL,
    render_fn=None,
    voices=None,
    client_dir: Path | None = None,
    corpus_path: Path | None = None,
    media_path: Path | None = None,
    cards_dir: Path | None = None,
    dictionary_path: Path | None = None,
    events_db: Path | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Mannschaft",
        version="6.0.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )

    catalogue = Catalogue(lessons_dir=lessons_dir, audio_dir=audio_dir)
    store = ProgressStore(progress_db or ROOT / "user" / "progress.sqlite")
    if events_db is None:
        events_db = (
            Path(progress_db).with_name("events.sqlite")
            if progress_db is not None
            else ROOT / "user" / "events.sqlite"
        )
    events = EventStore(events_db)
    queue = JobQueue(render_fn or make_render_fn(catalogue))

    app.state.catalogue = catalogue
    app.state.progress = store
    app.state.events = events
    app.state.jobs = queue
    app.state.voicestudio_url = voicestudio_url
    app.state.media_path = Path(media_path or MEDIA_PATH)
    app.state.cards_dir = Path(cards_dir or CARDS_DIR)
    app.state.dictionary_path = Path(dictionary_path or DICTIONARY_PATH)

    def configured_voices():
        return voices if voices is not None else load_voices()

    @app.middleware("http")
    async def log_requests(request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        _http_log.info(
            "ts=%s method=%s route=%s status=%d ms=%.1f",
            datetime.now(UTC).isoformat(timespec="seconds"),
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response

    # ---- meta ----------------------------------------------------------

    @app.get("/api")
    def api_root() -> dict:
        return {"app": "v5", "status": "ok", "docs": "/api/docs"}

    @app.get("/api/health")
    def health() -> dict:
        engine = probe(app.state.voicestudio_url)
        configured = configured_voices()
        missing = missing_profiles(configured)
        summaries = catalogue.summaries()
        return {
            "app": "ok",
            "voicestudio": engine,
            "voices_ok": not missing,
            "missing_voices": missing,
            "lessons": {
                "total": len(summaries),
                "rendered": sum(1 for s in summaries if s.rendered),
            },
            "corpus": {"clips": _count_clips(corpus_path or CORPUS_PATH)},
        }

    # ---- content -------------------------------------------------------

    @app.get("/api/lessons")
    def lessons(
        level: str | None = Query(default=None),
        tag: str | None = Query(default=None),
    ) -> dict:
        rows = catalogue.summaries(level=level, tag=tag)
        return {"lessons": [row.as_dict() for row in rows], "count": len(rows)}

    @app.get("/api/lessons/{lesson_id}")
    def lesson_detail(lesson_id: str) -> dict:
        detail = catalogue.detail(lesson_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"no such lesson: {lesson_id}")
        return detail

    # ---- audio (byte-range comes free with FileResponse) ---------------

    @app.get("/api/audio/{lesson_id}")
    def lesson_audio(lesson_id: str) -> FileResponse:
        path = catalogue.audio_path(lesson_id)
        if path is None:
            raise HTTPException(
                status_code=404,
                detail=f"{lesson_id} has no rendered audio — POST /api/render/{lesson_id}",
            )
        return FileResponse(path, media_type="audio/mpeg")

    @app.get("/api/audio/{lesson_id}/lines/{segment_id}")
    def line_audio(lesson_id: str, segment_id: str) -> FileResponse:
        path = catalogue.line_path(lesson_id, segment_id)
        if path is None:
            raise HTTPException(
                status_code=404,
                detail=f"{lesson_id} has no clip {segment_id!r}",
            )
        return FileResponse(path, media_type="audio/mpeg")

    # ---- progress ------------------------------------------------------

    @app.get("/api/progress")
    def get_progress() -> dict:
        return JSONResponse(
            {
                "resume": store.resume(),
                "lessons": store.all(),
                # Additive V6 fields: old clients ignore unknown keys.
                "events": events.recent(50),
                "event_counts": events.counts(),
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/progress")
    def post_progress(update: ProgressUpdate) -> dict:
        if catalogue.get(update.lesson_id) is None:
            raise HTTPException(status_code=404, detail=f"no such lesson: {update.lesson_id}")

        if update.event is not None:
            if update.event not in EVENT_KINDS:
                raise HTTPException(
                    status_code=422,
                    detail=f"unknown event {update.event!r}; expected one of {list(EVENT_KINDS)}",
                )
            event = events.add(update.lesson_id, update.event, update.detail)
            if update.seg_id:
                row = store.upsert(
                    update.lesson_id,
                    update.seg_id,
                    update.position_ms,
                    completed=update.completed,
                )
            else:
                row = store.for_lesson(update.lesson_id)
            return {"event": event, "progress": row}

        if not update.seg_id:
            raise HTTPException(status_code=422, detail="seg_id is required for a progress update")
        row = store.upsert(
            update.lesson_id,
            update.seg_id,
            update.position_ms,
            completed=update.completed,
        )
        return {"progress": row}

    # ---- render jobs ---------------------------------------------------

    @app.post("/api/render/{lesson_id}", status_code=202)
    def queue_render(lesson_id: str) -> dict:
        # Pre-flight synchronously so a bad request fails with a useful status
        # instead of becoming a job that reports the same error later.
        try:
            renderable(lesson_id, lessons_dir=catalogue.lessons_dir, voices=configured_voices())
        except LessonNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValidationFailed as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": f"{lesson_id} failed validation",
                    "issues": [str(i) for i in exc.issues],
                },
            ) from exc
        except VoicesNotReady as exc:
            raise HTTPException(
                status_code=409,
                detail={"message": str(exc), "missing_voices": exc.missing},
            ) from exc
        except PipelineError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        job = queue.submit(lesson_id)
        return {"job": job.as_dict(), "already_active": job.state in ("queued", "running")}

    @app.get("/api/render/{job_id}")
    def render_status(job_id: str) -> dict:
        job = queue.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"no such job: {job_id}")
        return job.as_dict()

    # ---- corpus --------------------------------------------------------

    @app.get("/api/corpus/suggest")
    def corpus_suggest(
        level: str | None = Query(default=None),
        situation: str | None = Query(default=None),
        limit: int = Query(default=10, ge=1, le=100),
    ) -> dict:
        from ..corpus.suggest import suggest

        candidates = suggest(
            corpus_path or CORPUS_PATH,
            level=level,
            situation=situation,
            limit=limit,
        )
        result: dict = {"candidates": candidates, "count": len(candidates)}
        if not candidates and not (corpus_path or CORPUS_PATH).exists():
            result["reason"] = "corpus not built yet (M6)"
        return result

    # ---- V6: media, cards, dictionary, journey context -----------------

    @app.get("/api/media/{lesson_id}")
    def lesson_media(lesson_id: str) -> dict:
        if catalogue.get(lesson_id) is None:
            raise HTTPException(status_code=404, detail=f"no such lesson: {lesson_id}")
        manifest = load_manifest_cached(app.state.media_path)
        if manifest is None:
            raise HTTPException(
                status_code=404,
                detail="lesson media not generated — run python -m v5.media.select",
            )
        item = manifest.lessons.get(lesson_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"no media entry for {lesson_id}")
        return {
            "lesson_id": lesson_id,
            "primary": item.primary.model_dump(mode="json") if item.primary else None,
            "alternates": [pick.model_dump(mode="json") for pick in item.alternates],
            "fallback": item.fallback,
            "relevance": item.relevance.model_dump(mode="json"),
            "embed_url": manifest.embed_url(lesson_id),
        }

    @app.get("/api/cards/{lesson_id}")
    def lesson_cards(lesson_id: str) -> dict:
        if catalogue.get(lesson_id) is None:
            raise HTTPException(status_code=404, detail=f"no such lesson: {lesson_id}")
        path = app.state.cards_dir / f"{lesson_id}.json"
        if not path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"no card deck for {lesson_id} — run python -m v5.cards.build",
            )
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail=f"unreadable deck: {exc}") from exc

    @app.get("/api/dict")
    def dictionary(q: str = Query(default=""), limit: int = Query(default=20, ge=1, le=100)) -> dict:
        return dictionary_lookup(q, path=app.state.dictionary_path, limit=limit)

    @app.get("/api/lesson/{lesson_id}/context")
    def lesson_context(lesson_id: str) -> dict:
        detail = catalogue.detail(lesson_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"no such lesson: {lesson_id}")
        lesson = detail["lesson"]
        scene = lesson.get("scene") or {}
        manifest = load_manifest_cached(app.state.media_path)
        item = manifest.lessons.get(lesson_id) if manifest else None
        card_count = None
        deck_path = app.state.cards_dir / f"{lesson_id}.json"
        if deck_path.exists():
            try:
                card_count = len(json.loads(deck_path.read_text(encoding="utf-8")).get("cards", []))
            except (OSError, json.JSONDecodeError):
                card_count = None
        return {
            "id": lesson_id,
            "level": lesson.get("level"),
            "title": lesson.get("title"),
            "minutes": lesson.get("minutes"),
            "can_do": {"de": scene.get("can_do_de"), "en": scene.get("can_do_en")},
            "situation_tags": scene.get("situation_tags") or [],
            "grammar_focus": scene.get("grammar_focus") or [],
            "register": scene.get("register"),
            "rendered": bool(detail.get("summary") and detail["summary"].get("rendered")),
            "media": {
                "has_clip": bool(item and item.primary),
                "embed_url": manifest.embed_url(lesson_id) if manifest else None,
                "fallback": item.fallback if item else "rendered_audio",
            },
            "cards": {"count": card_count, "available": card_count is not None},
        }

    # ---- client (mounted last: API routes win, everything else is the PWA) --

    assets = Path(client_dir) if client_dir is not None else CLIENT_DIR
    if (assets / "index.html").exists():
        app.mount("/", StaticFiles(directory=assets, html=True), name="client")

    return app
