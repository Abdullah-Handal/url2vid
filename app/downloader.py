"""All contact with yt-dlp lives here.

yt-dlp is used as a library rather than a subprocess so progress arrives as
exact byte counts through ``progress_hooks`` instead of scraped stdout text.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError

from . import jobs, progress
from .jobs import registry

log = logging.getLogger("url2vid")

DOWNLOAD_DIR = Path(__file__).resolve().parent.parent / "downloads"
MAX_CONCURRENT = 3

_pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT, thread_name_prefix="dl")


class Cancelled(Exception):
    """Raised inside a hook to unwind a download the user cancelled."""


class _SilentLogger:
    """Swallow yt-dlp's own console output.

    ``quiet`` alone still lets it write ERROR lines straight to stderr, which
    would scribble over the progress bar and duplicate the message we print.
    """

    def debug(self, msg: str) -> None: ...
    def info(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


def _base_opts() -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _SilentLogger(),
        "noplaylist": True,
        # Surface the real reason a site failed instead of dying on the first
        # extractor hiccup.
        "ignoreerrors": False,
    }


def probe(url: str) -> dict:
    """Look up title and available resolutions without downloading anything."""
    opts = _base_opts() | {"skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    playlist_note = None
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise ValueError("That link is a playlist with no downloadable entries.")
        playlist_note = f"Link is a playlist ({len(entries)} items) — downloading the first video only."
        info = entries[0]

    heights = progress.dedupe_heights(info.get("formats") or [])
    return {
        "title": info.get("title") or "Untitled video",
        "duration": info.get("duration"),
        "extractor": info.get("extractor_key") or info.get("extractor"),
        "webpage_url": info.get("webpage_url") or url,
        "formats": heights,
        "note": playlist_note,
    }


def _stream_estimates(info: dict) -> list[int | None]:
    """Estimated byte size of each stream the selection will fetch.

    Kept as a per-stream list rather than a single sum so that a finished
    stream's real size can replace its estimate mid-download.
    """
    selected = info.get("requested_formats") or [info]
    return [fmt.get("filesize") or fmt.get("filesize_approx") for fmt in selected]


def total_from_estimates(estimates: list[int | None]) -> int | None:
    """Sum the per-stream sizes, or None if any piece is unknown.

    A partial sum would understate the total and make the percentage lie, so
    an unknown piece disables the percentage entirely rather than guessing.
    """
    if not estimates or any(e is None for e in estimates):
        return None
    total = sum(estimates)
    return total or None


def _make_hooks(job_id: str, estimates: list[int | None]) -> tuple:
    """Build the progress and postprocessor hooks for one job."""
    state = {"current_file": None, "speed": None, "estimates": list(estimates), "index": 0}

    def progress_hook(d: dict) -> None:
        job = registry.get(job_id)
        if job is None:
            raise Cancelled()
        if job.cancel_requested:
            raise Cancelled()

        info = d.get("info_dict") or {}
        filename = info.get("_filename") or d.get("filename")

        if d["status"] == "downloading":
            # A new filename means yt-dlp moved on to the next stream; bank the
            # finished one so the running total keeps climbing.
            if state["current_file"] is None:
                state["current_file"] = filename
            elif filename != state["current_file"]:
                banked = registry.get(job_id)
                if banked:
                    registry.update(
                        job_id,
                        completed_bytes=banked.completed_bytes + banked.downloaded_bytes,
                        downloaded_bytes=0,
                    )
                state["current_file"] = filename

            downloaded = d.get("downloaded_bytes") or 0
            state["speed"] = progress.smooth_speed(state["speed"], d.get("speed"))
            current = registry.get(job_id)
            completed = current.completed_bytes if current else 0
            total = current.total_bytes if current else None

            if total is None:
                # Unknown overall size: fall back to this stream's own totals
                # and flag the reading as an estimate in the UI.
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                registry.update(job_id, total_bytes=total, estimated=True)

            eta = progress.eta_seconds(completed + downloaded, total, state["speed"])
            if eta is None:
                eta = d.get("eta")

            registry.update(
                job_id,
                status=jobs.DOWNLOADING,
                downloaded_bytes=downloaded,
                speed=state["speed"],
                eta=eta,
            )

        elif d["status"] == "finished":
            current = registry.get(job_id)
            if current:
                actual = d.get("downloaded_bytes") or d.get("total_bytes") or current.downloaded_bytes
                index = state["index"]
                if actual and index < len(state["estimates"]):
                    # Estimates routinely overshoot; without this the bar
                    # stalls short of 100% and then snaps.
                    state["estimates"][index] = actual
                state["index"] = index + 1

                refined = total_from_estimates(state["estimates"])
                fields = {
                    "completed_bytes": current.completed_bytes + (actual or 0),
                    "downloaded_bytes": 0,
                    "eta": None,
                }
                if refined:
                    fields["total_bytes"] = refined
                registry.update(job_id, **fields)
            state["current_file"] = None

    def postprocessor_hook(d: dict) -> None:
        # ffmpeg merging can take a while on large files; without this the bar
        # sits at 100% looking hung.
        if d.get("status") == "started":
            registry.update(job_id, status=jobs.MERGING, speed=None, eta=None)

    return progress_hook, postprocessor_hook


def _output_template(info: dict) -> str:
    """Filename template for a job.

    The video id keeps distinct videos with identical titles from colliding,
    but the generic extractor often *derives* the id from the title, which
    would produce "Clip [Clip].mp4". Drop it when it adds nothing.
    """
    video_id = str(info.get("id") or "")
    title = str(info.get("title") or "")
    if video_id and video_id.lower() not in title.lower():
        return "%(title).150B [%(id).40B].%(ext)s"
    return "%(title).180B.%(ext)s"


def _run(job_id: str) -> None:
    job = registry.get(job_id)
    if job is None or job.cancel_requested:
        return

    selector = progress.format_selector(job.height)
    saved: str | None = None

    try:
        # Pass one: resolve the video and pick formats, downloading nothing.
        with yt_dlp.YoutubeDL(_base_opts() | {"format": selector}) as probe_ydl:
            info = probe_ydl.extract_info(job.url, download=False)

        if info.get("_type") == "playlist":
            entries = [e for e in (info.get("entries") or []) if e]
            if not entries:
                raise DownloadError("Playlist contained no downloadable videos.")
            info = entries[0]

        estimates = _stream_estimates(info)
        progress_hook, postprocessor_hook = _make_hooks(job_id, estimates)
        registry.update(
            job_id,
            title=info.get("title") or job.title,
            total_bytes=total_from_estimates(estimates),
            status=jobs.DOWNLOADING,
        )
        if registry.get(job_id).cancel_requested:
            raise Cancelled()

        # Pass two: fetch, now that the filename template can use the real id.
        opts = _base_opts() | {
            "format": selector,
            "merge_output_format": "mp4",
            "outtmpl": _output_template(info),
            "paths": {"home": str(DOWNLOAD_DIR)},
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [postprocessor_hook],
            "overwrites": False,
            "continuedl": True,
            "retries": 5,
            "fragment_retries": 5,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            result = ydl.process_ie_result(info, download=True)
        downloads = (result or {}).get("requested_downloads") or []
        if downloads:
            saved = downloads[0].get("filepath")

    except Cancelled:
        registry.update(job_id, status=jobs.CANCELLED, speed=None, eta=None)
        return
    except DownloadError as exc:
        registry.update(job_id, status=jobs.ERROR, error=clean_error(str(exc)), speed=None, eta=None)
        return
    except Exception as exc:  # noqa: BLE001 - one bad URL must not kill the worker
        log.exception("download failed for %s", job.url)
        registry.update(job_id, status=jobs.ERROR, error=clean_error(str(exc)), speed=None, eta=None)
        return

    registry.update(
        job_id,
        status=jobs.DONE,
        filename=Path(saved).name if saved else None,
        speed=None,
        eta=None,
    )


def clean_error(message: str) -> str:
    """Trim yt-dlp's ANSI noise and prefixes down to the useful sentence.

    The result is plain text and may contain square brackets such as
    "[generic]", so callers must escape it before handing it to Rich.
    """
    text = message.replace("\x1b[0;31m", "").replace("\x1b[0m", "")
    for prefix in ("ERROR: ", "ERROR:"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    text = text.strip()
    return text[:400] if text else "Download failed for an unknown reason."


def start(url: str, height: int | None, title: str) -> jobs.Job:
    """Register a job and hand it to the worker pool."""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    job = registry.create(url=url, height=height, title=title)
    _pool.submit(_run, job.id)
    return job
