"""Thread-safe store of download jobs.

Worker threads mutate jobs through the registry while the SSE endpoint reads
snapshots of them, so every access is guarded by a single lock.
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field

from . import progress

# Job status values understood by the front end.
QUEUED = "queued"
DOWNLOADING = "downloading"
MERGING = "merging"
DONE = "done"
ERROR = "error"
CANCELLED = "cancelled"

TERMINAL = {DONE, ERROR, CANCELLED}


@dataclass
class Job:
    id: str
    url: str
    title: str = "Fetching…"
    height: int | None = None
    status: str = QUEUED
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    # Bytes belonging to streams that already finished. A merged download
    # fetches video and audio as separate files; carrying this forward is what
    # keeps the percentage climbing instead of resetting between them.
    completed_bytes: int = 0
    speed: float | None = None
    eta: int | None = None
    error: str | None = None
    filename: str | None = None
    # Set when the total size is unknown and yt-dlp's own percentage is used.
    estimated: bool = False
    created_at: float = field(default_factory=time.time)
    cancel_requested: bool = False

    def as_dict(self) -> dict:
        total = self.total_bytes
        done = self.completed_bytes + self.downloaded_bytes
        pct = progress.percent(done, total)
        if self.status == DONE:
            pct = 100.0
        elif self.status == MERGING and pct is None:
            pct = 100.0
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "height": self.height,
            "status": self.status,
            "percent": round(pct, 1) if pct is not None else None,
            "eta_label": progress.format_eta(self.eta) if self.status == DOWNLOADING else "",
            "size_label": progress.format_bytes(total),
            "downloaded_label": progress.format_bytes(done),
            "speed_label": (
                f"{progress.format_bytes(self.speed)}/s"
                if self.speed and self.status == DOWNLOADING
                else ""
            ),
            "estimated": self.estimated,
            "error": self.error,
            "filename": self.filename,
            "created_at": self.created_at,
        }


class JobRegistry:
    """In-memory job table. Jobs live until the page clears them."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        # Bumped on every mutation so the SSE loop can skip identical frames.
        self._revision = 0

    def create(self, url: str, height: int | None, title: str) -> Job:
        with self._lock:
            job = Job(id=f"j{next(self._ids)}", url=url, height=height, title=title)
            self._jobs[job.id] = job
            self._revision += 1
            return job

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)
            self._revision += 1

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def request_cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in TERMINAL:
                return False
            job.cancel_requested = True
            self._revision += 1
            return True

    def clear_finished(self) -> int:
        with self._lock:
            stale = [jid for jid, job in self._jobs.items() if job.status in TERMINAL]
            for jid in stale:
                del self._jobs[jid]
            if stale:
                self._revision += 1
            return len(stale)

    def snapshot(self) -> tuple[int, list[dict]]:
        """Current revision plus every job, newest first."""
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return self._revision, [job.as_dict() for job in jobs]


registry = JobRegistry()
