"""Pure progress/format helpers.

Deliberately free of yt-dlp and I/O imports so the arithmetic that drives the
percentage and ETA can be tested without touching the network.
"""

from __future__ import annotations

# Resolutions offered in the dropdown, tallest first.
KNOWN_HEIGHTS = (2160, 1440, 1080, 720, 480, 360, 240, 144)

# Weight for the exponential moving average applied to download speed. Lower
# values smooth harder; 0.3 settles within a few seconds without lagging badly
# when the real speed genuinely changes.
SPEED_SMOOTHING = 0.3


def smooth_speed(previous: float | None, sample: float | None) -> float | None:
    """Blend a new speed sample into the running average.

    yt-dlp reports instantaneous speed, which swings wildly between chunks. A
    raw sample would make the ETA jitter by tens of seconds every refresh.
    """
    if sample is None or sample <= 0:
        return previous
    if previous is None:
        return sample
    return SPEED_SMOOTHING * sample + (1 - SPEED_SMOOTHING) * previous


def percent(downloaded: int, total: int | None) -> float | None:
    """Percentage complete, clamped to 0-100. None when the total is unknown."""
    if not total or total <= 0:
        return None
    return max(0.0, min(100.0, downloaded / total * 100))


def eta_seconds(downloaded: int, total: int | None, speed: float | None) -> int | None:
    """Seconds remaining, from smoothed speed over the *remaining* bytes.

    Computed here rather than taken from yt-dlp's own ``eta`` because that value
    describes only the stream currently downloading; for a merged
    video+audio download it would read as the ETA of one half.
    """
    if not total or total <= 0 or not speed or speed <= 0:
        return None
    remaining = total - downloaded
    if remaining <= 0:
        return 0
    return int(remaining / speed)


def format_eta(seconds: int | None) -> str:
    """Human-readable countdown: '45s', '2m 11s', '1h 04m'."""
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


def format_bytes(num: int | float | None) -> str:
    """Byte count as a short human string."""
    if not num or num <= 0:
        return ""
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB"):
        if num < step or unit == "GB":
            precision = 0 if unit == "B" else 1
            return f"{num:.{precision}f} {unit}"
        num /= step
    return ""


MP3_KBPS = 192

# Offered MP3 bitrates, best first. Encoding above the source stream's own
# bitrate cannot add detail, so the ceiling is kept sane rather than silly.
AUDIO_BITRATES = (320, 256, 192, 128, 96)


def mp3_estimate(duration: float | None, kbps: int = MP3_KBPS) -> int | None:
    """Rough size of the MP3 a download will be converted into.

    The source audio stream's own filesize is the wrong number to show here:
    it is what crosses the network, not what is kept. A ten-minute track can
    arrive as a 30 MB Opus stream and land as a 14 MB MP3. Constant bitrate
    makes the arithmetic exact enough to be useful.
    """
    if not duration or duration <= 0:
        return None
    return int(duration * kbps * 1000 / 8)


def audio_options(duration: float | None) -> list[dict]:
    """The MP3 bitrates on offer, each with the size it would produce."""
    return [
        {
            "kbps": kbps,
            "label": f"{kbps} kbps",
            "size_label": format_bytes(mp3_estimate(duration, kbps)),
        }
        for kbps in AUDIO_BITRATES
    ]


def dedupe_heights(formats: list[dict]) -> list[dict]:
    """Collapse a yt-dlp format list into one entry per offered resolution.

    A single video commonly exposes a dozen renditions of the same height
    (different codecs and bitrates); the dropdown only needs each height once.
    Heights are snapped to the nearest known label so oddities like 1082 or
    638 present as 1080p and 720p rather than as their raw numbers.

    ``height`` stays the real, unsnapped maximum for the bucket while ``label``
    carries the tidy name. Selecting on a snapped number is a trap: a 256p
    stream shown as "240p" is not matched by ``height<=240``, so the request
    misses everything and falls through to the best available -- asking for the
    smallest rendition and being handed the largest.

    Sizes include the audio that will be merged in, since a video-only stream's
    own filesize can be a small fraction of what actually gets downloaded.
    """
    audio_sizes = [
        fmt.get("filesize") or fmt.get("filesize_approx") or 0
        for fmt in formats
        if fmt.get("vcodec") in (None, "none") and fmt.get("acodec") not in (None, "none")
    ]
    best_audio = max(audio_sizes) if audio_sizes else 0

    buckets: dict[int, dict] = {}
    for fmt in formats:
        if fmt.get("vcodec") in (None, "none"):
            continue  # audio-only rendition
        height = fmt.get("height")
        if not height:
            continue
        height = int(height)
        size = fmt.get("filesize") or fmt.get("filesize_approx") or 0
        if size and fmt.get("acodec") in (None, "none"):
            size += best_audio

        bucket = buckets.setdefault(_snap_height(height), {"height": 0, "approx_size": 0})
        # Largest real height in the bucket, so "height<=" covers the whole of it.
        bucket["height"] = max(bucket["height"], height)
        bucket["approx_size"] = max(bucket["approx_size"], size)

    ordered = []
    for label_height in sorted(buckets, reverse=True):
        bucket = buckets[label_height]
        ordered.append(
            {
                "height": bucket["height"],
                "label": f"{label_height}p",
                "size_label": format_bytes(bucket["approx_size"]),
            }
        )
    return ordered


def _snap_height(height: int) -> int:
    """Snap an arbitrary height to the closest standard rung."""
    return min(KNOWN_HEIGHTS, key=lambda known: abs(known - height))


def format_selector(
    height: int | None, audio: bool = True, audio_only: bool = False
) -> str:
    """yt-dlp format string for a requested max height ('best' when None).

    The ``/best`` tail is the fallback for sites that only ever serve a single
    pre-muxed stream and have nothing to merge.
    """
    if audio_only:
        # No re-encode: take the site's own best audio track as it comes.
        return "bestaudio/best"
    if not audio:
        if height is None:
            return "bestvideo/best"
        return f"bestvideo[height<={height}]/bestvideo/best"
    if height is None:
        return "bestvideo*+bestaudio/best"
    # The tail matters: if nothing is small enough, fall back to the *smallest*
    # rendition rather than the best one. The old tail asked for the best
    # available, so a request no format could satisfy quietly downloaded the
    # largest file on offer -- 708 MB when asked for the smallest.
    return (
        f"bestvideo[height<={height}]+bestaudio/"
        f"best[height<={height}]/"
        f"worstvideo*+bestaudio/worst"
    )
