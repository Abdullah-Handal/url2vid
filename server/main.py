"""HTTP API for the web UI.

The download machinery is shared verbatim with the terminal app: this module
adds routes and a live event stream on top of ``app.downloader`` and
``app.jobs`` rather than reimplementing any of it.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import downloader, jobs
from app.jobs import registry

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

app = FastAPI(title="url2vid", docs_url=None, redoc_url=None)

# The Vite dev server runs on another port during development. Both origins are
# loopback only; the app is never intended to be exposed to a network.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProbeRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class DownloadRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    height: int | None = None
    title: str = ""


def _require_http(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "That is not a full URL. It has to start with http:// or https://")
    return url


@app.post("/api/probe")
async def probe(request: ProbeRequest) -> dict:
    """Resolve a URL to a title and the resolutions on offer."""
    url = _require_http(request.url)
    try:
        info = await run_in_threadpool(downloader.probe, url)
    except Exception as exc:  # noqa: BLE001 - the site's reason is the useful part
        raise HTTPException(422, downloader.explain_error(str(exc), url)) from exc
    # A link that already points at a media file, or a site serving one
    # pre-muxed stream, leaves the user nothing to choose.
    info["auto"] = not info["formats"]
    return info


@app.post("/api/download")
async def start_download(request: DownloadRequest) -> dict:
    url = _require_http(request.url)
    job = downloader.start(url, request.height, request.title or "Fetching…")
    return {"id": job.id}


@app.get("/api/jobs")
async def list_jobs() -> dict:
    revision, job_list = registry.snapshot()
    return {"revision": revision, "jobs": job_list}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel(job_id: str) -> dict:
    if not registry.request_cancel(job_id):
        raise HTTPException(409, "That download has already finished.")
    return {"ok": True}


@app.post("/api/jobs/clear")
async def clear() -> dict:
    return {"cleared": registry.clear_finished()}


@app.get("/api/jobs/{job_id}/file")
async def job_file(job_id: str) -> FileResponse:
    """Serve a finished video so the browser can write it to a chosen folder."""
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(404, "No such download.")
    if job.status != jobs.DONE or not job.filename:
        raise HTTPException(409, "That download has not finished.")

    path = (downloader.DOWNLOAD_DIR / job.filename).resolve()
    # A crafted title must not be able to walk out of the downloads folder.
    if not path.is_relative_to(downloader.DOWNLOAD_DIR.resolve()) or not path.is_file():
        raise HTTPException(404, "The file is no longer on disk.")
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)


@app.get("/api/events")
async def events() -> StreamingResponse:
    """Server-sent events carrying the whole job table whenever it changes."""

    async def stream():
        last = -1
        # An immediate frame means a reconnecting page paints at once rather
        # than sitting blank until something happens to change.
        while True:
            revision, job_list = registry.snapshot()
            if revision != last:
                last = revision
                yield f"data: {json.dumps({'revision': revision, 'jobs': job_list})}\n\n"
            else:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/config")
async def config() -> dict:
    return {"download_dir": str(downloader.DOWNLOAD_DIR), "max_concurrent": downloader.MAX_CONCURRENT}


# Mounted last so the API routes above win. Only present after `npm run build`.
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
