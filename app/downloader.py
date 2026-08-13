"""All contact with yt-dlp lives here.

yt-dlp is used as a library rather than a subprocess so progress arrives as
exact byte counts through ``progress_hooks`` instead of scraped stdout text.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from yt_dlp.utils import DownloadError

from . import jobs, paths, progress
from .jobs import registry

log = logging.getLogger("url2vid")

# Resolved through ``paths`` so a packaged build writes to the user's real
# Downloads folder instead of somewhere inside the bundle. Reassigned by
# ``set_download_dir``; tests monkeypatch it directly.
DOWNLOAD_DIR = paths.download_dir()
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
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _SilentLogger(),
        "noplaylist": True,
        # Surface the real reason a site failed instead of dying on the first
        # extractor hiccup.
        "ignoreerrors": False,
    }
    # A packaged build ships its own ffmpeg; pointing yt-dlp at it explicitly
    # means merging works on machines that have no ffmpeg on PATH at all.
    bundled = paths.bundled_ffmpeg()
    if bundled:
        opts["ffmpeg_location"] = str(bundled)
    return opts


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
        "thumbnail": info.get("thumbnail"),
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


def mode_marker(height: int | None, audio: bool, audio_only: bool) -> str:
    """Short tag describing what a job actually fetches.

    Without it, the same video downloaded twice in different modes lands on one
    filename -- and because ``overwrites`` is off, yt-dlp hands back the file
    already on disk instead of the one that was asked for. Asking for 1080p
    after 144p would quietly return the 144p copy.
    """
    if audio_only:
        return "audio"
    quality = f"{height}p" if height else "best"
    return quality if audio else f"{quality} silent"


def _output_template(info: dict, marker: str = "") -> str:
    """Filename template for a job.

    The video id keeps distinct videos with identical titles from colliding,
    but the generic extractor often *derives* the id from the title, which
    would produce "Clip [Clip].mp4". Drop it when it adds nothing.
    """
    video_id = str(info.get("id") or "")
    title = str(info.get("title") or "")
    tag = f" [{marker}]" if marker else ""
    if video_id and video_id.lower() not in title.lower():
        return f"%(title).150B [%(id).40B]{tag}.%(ext)s"
    return f"%(title).180B{tag}.%(ext)s"


def _run(job_id: str) -> None:
    job = registry.get(job_id)
    if job is None or job.cancel_requested:
        return

    selector = progress.format_selector(job.height, job.audio, job.audio_only)
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
            "outtmpl": _output_template(
                info, mode_marker(job.height, job.audio, job.audio_only)
            ),
            "paths": {"home": str(DOWNLOAD_DIR)},
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [postprocessor_hook],
            "overwrites": False,
            "continuedl": True,
            "retries": 5,
            "fragment_retries": 5,
        }
        # Only a video download has two streams to combine; forcing mp4 on an
        # audio-only job would hand ffmpeg a container it should not be using.
        if not job.audio_only:
            opts["merge_output_format"] = "mp4"
        with yt_dlp.YoutubeDL(opts) as ydl:
            result = ydl.process_ie_result(info, download=True)
        downloads = (result or {}).get("requested_downloads") or []
        if downloads:
            saved = downloads[0].get("filepath")

    except Cancelled:
        registry.update(job_id, status=jobs.CANCELLED, speed=None, eta=None)
        return
    except DownloadError as exc:
        registry.update(
            job_id, status=jobs.ERROR, error=explain_error(str(exc), job.url), speed=None, eta=None
        )
        return
    except Exception as exc:  # noqa: BLE001 - one bad URL must not kill the worker
        log.exception("download failed for %s", job.url)
        registry.update(
            job_id, status=jobs.ERROR, error=explain_error(str(exc), job.url), speed=None, eta=None
        )
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


def _host(url: str) -> str:
    """Bare hostname of a URL, or "" if it hasn't got one."""
    try:
        netloc = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc.split("@")[-1].split(":")[0]


def _strip_noise(text: str) -> str:
    """Drop the "[extractor] id:" prefix and the "(caused by ...)" tail.

    Both are yt-dlp internals. The first names the extractor and the video id,
    neither of which helps someone reading the message; the second repeats the
    same failure as a Python exception repr.
    """
    head = text.split(" (caused by ")[0].strip()
    return re.sub(r"^\[[^\]]+\]\s+[^:]{1,60}:\s*", "", head).strip()


def _any(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def explain_error(message: str, url: str = "") -> str:
    """Turn a yt-dlp failure into a sentence that says what actually went wrong.

    yt-dlp's own text answers "what broke" but rarely "whose fault is it".
    "Unsupported URL" is the worst of them: on its own it reads like a bug in
    this app, when it means no extractor matched the site *and* the page held
    no findable stream. Anything unrecognised falls through unchanged rather
    than being flattened into a vague catch-all.
    """
    detail = _strip_noise(clean_error(message))
    low = detail.lower()
    site = _host(url) or "that site"

    if "unsupported url" in low:
        return (
            f"yt-dlp has no extractor for {site}, and no video could be found in "
            "the page itself. Sites that build their player in JavaScript keep "
            "the stream out of the page source, so there is nothing to pick up."
        )
    if _any(low, "name or service not known", "nodename nor servname",
            "temporary failure in name resolution", "no address associated"):
        return (
            f"Could not reach {site} — that domain does not resolve. "
            "Check the spelling and your connection."
        )
    if _any(low, "connection refused", "connection reset", "connection timed out",
            "timed out", "connectionerror"):
        return f"Could not connect to {site}. It may be down, or blocked on your network."
    if "404" in low:
        return f"{site} returned 404 Not Found — the link is wrong, or the video was deleted."
    if _any(low, "403", "forbidden"):
        return (
            f"{site} refused the request (403 Forbidden). The link may have expired, "
            "or the site may be blocking non-browser requests."
        )
    if _any(low, "429", "too many requests", "rate limit"):
        return f"{site} is rate-limiting you (429). Wait a while and try again."
    if "drm" in low:
        return "That video is DRM-protected, which url2vid does not handle."
    if _any(low, "sign in", "log in", "login", "cookies", "authentication",
            "private video", "members-only", "subscribers only", "premium"):
        return f"That video needs an account — url2vid does not sign in or use cookies. {site} said: {detail}"
    if _any(low, "your country", "geo restrict", "geo-restrict", "geo block",
            "not available in your", "blocked in your"):
        return f"{site} blocks that video in your region."
    if _any(low, "video unavailable", "has been removed", "no longer available",
            "does not exist", "was deleted", "not found"):
        return f"{site} says that video is gone: {detail}"
    if _any(low, "is not a valid url", "invalid url"):
        return "That is not a URL yt-dlp can read. Check it for typos or stray characters."
    return detail or "The download failed for an unknown reason."


def set_download_dir(path: Path) -> Path:
    """Point downloads at a new folder and remember the choice.

    Rebinding the module global keeps every existing reader -- the API's path
    guard, the CLI, the terminal UI -- pointed at one value.
    """
    global DOWNLOAD_DIR
    resolved = Path(path).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    # Fail before saving if the folder cannot actually be written to.
    probe_file = resolved / ".url2vid-write-test"
    probe_file.touch()
    probe_file.unlink()
    DOWNLOAD_DIR = resolved
    paths.save_download_dir(resolved)
    return resolved


def start(
    url: str,
    height: int | None,
    title: str,
    audio: bool = True,
    audio_only: bool = False,
) -> jobs.Job:
    """Register a job and hand it to the worker pool."""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    job = registry.create(
        url=url, height=height, title=title, audio=audio, audio_only=audio_only
    )
    _pool.submit(_run, job.id)
    return job
