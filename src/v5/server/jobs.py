"""Sequential render jobs.

The GPU is a single resource: two renders at once would thrash 12 GB of VRAM.
So the pool has exactly one worker, and the queue is the only way in.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from ..render import RenderOutcome

JobState = Literal["queued", "running", "done", "error"]

RenderFn = Callable[[str, Callable[[int, int], None]], RenderOutcome]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Job:
    id: str
    lesson_id: str
    state: JobState = "queued"
    done: int = 0
    total: int = 0
    error: str | None = None
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None

    def as_dict(self) -> dict:
        return {
            "job_id": self.id,
            "lesson_id": self.lesson_id,
            "state": self.state,
            "done": self.done,
            "total": self.total,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class JobQueue:
    def __init__(self, render_fn: RenderFn, *, max_workers: int = 1) -> None:
        self._render_fn = render_fn
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="v5-render")
        self._jobs: dict[str, Job] = {}
        self._active: dict[str, str] = {}  # lesson_id -> job_id
        self._finished: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def submit(self, lesson_id: str) -> Job:
        """Queue a render. Returns the existing job if one is already active."""
        with self._lock:
            existing = self._active.get(lesson_id)
            if existing is not None:
                job = self._jobs[existing]
                if job.state in ("queued", "running"):
                    return job
            job = Job(id=uuid.uuid4().hex[:12], lesson_id=lesson_id)
            self._jobs[job.id] = job
            self._active[lesson_id] = job.id
            self._finished[job.id] = threading.Event()
        self._pool.submit(self._run, job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def wait(self, job_id: str, timeout: float | None = None) -> Job | None:
        """Block until the job finishes (or the timeout expires)."""
        with self._lock:
            event = self._finished.get(job_id)
            job = self._jobs.get(job_id)
        if event is not None:
            event.wait(timeout)
        return job

    def active_for(self, lesson_id: str) -> Job | None:
        with self._lock:
            job_id = self._active.get(lesson_id)
            return self._jobs.get(job_id) if job_id else None

    def _run(self, job: Job) -> None:
        with self._lock:
            job.state = "running"
            job.started_at = _now()

        def progress(done: int, total: int) -> None:
            with self._lock:
                job.done, job.total = done, total

        try:
            outcome = self._render_fn(job.lesson_id, progress)
        except Exception as exc:  # noqa: BLE001 — a failed job must report, not crash the pool
            with self._lock:
                job.state = "error"
                job.error = str(exc)
                job.finished_at = _now()
        else:
            with self._lock:
                job.state = "done"
                job.done = outcome.segments
                job.total = outcome.segments
                job.finished_at = _now()
        finally:
            with self._lock:
                event = self._finished.get(job.id)
            if event is not None:
                event.set()

    def shutdown(self, *, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=True)
