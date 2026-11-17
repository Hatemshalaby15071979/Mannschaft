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
import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config import ROOT, load_voices, missing_profiles
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
CLIENT_DIR = Path(__file__).resolve().parent.parent / "client"

# Python's mimetypes does not know .webmanifest on every platform; without this
# some browsers refuse the PWA manifest as application/octet-stream.
mimetypes.add_type("application/manifest+json", ".webmanifest")


class ProgressUpdate(BaseModel):
    lesson_id: str = Field(min_length=1)
    seg_id: str = Field(min_length=1)
    position_ms: int = Field(default=0, ge=0)
    completed: bool = False


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
) -> FastAPI:
    app = FastAPI(
        title="v5",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )

    catalogue = Catalogue(lessons_dir=lessons_dir, audio_dir=audio_dir)
    store = ProgressStore(progress_db or ROOT / "user" / "progress.sqlite")
    queue = JobQueue(render_fn or make_render_fn(catalogue))

    app.state.catalogue = catalogue
    app.state.progress = store
    app.state.jobs = queue
    app.state.voicestudio_url = voicestudio_url

    def configured_voices():
        return voices if voices is not None else load_voices()

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
            {"resume": store.resume(), "lessons": store.all()},
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/progress")
    def post_progress(update: ProgressUpdate) -> dict:
        if catalogue.get(update.lesson_id) is None:
            raise HTTPException(status_code=404, detail=f"no such lesson: {update.lesson_id}")
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

    # ---- client (mounted last: API routes win, everything else is the PWA) --

    assets = Path(client_dir) if client_dir is not None else CLIENT_DIR
    if (assets / "index.html").exists():
        app.mount("/", StaticFiles(directory=assets, html=True), name="client")

    return app
