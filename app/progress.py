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


def dedupe_heights(formats: list[dict]) -> list[dict]:
    """Collapse a yt-dlp format list into one entry per offered resolution.

    A single video commonly exposes a dozen renditions of the same height
    (different codecs and bitrates); the dropdown only needs each height once.
    Heights are snapped to the nearest known label so oddities like 1082 or
    638 present as 1080p and 720p rather than as their raw numbers.
    """
    best: dict[int, dict] = {}
    for fmt in formats:
        if fmt.get("vcodec") in (None, "none"):
            continue  # audio-only rendition
        height = fmt.get("height")
        if not height:
            continue
        label_height = _snap_height(int(height))
        size = fmt.get("filesize") or fmt.get("filesize_approx") or 0
        current = best.get(label_height)
        # Keep the largest known size per height as the size estimate shown.
        if current is None or size > current["approx_size"]:
            best[label_height] = {
                "height": label_height,
                "label": f"{label_height}p",
                "approx_size": size,
            }
    ordered = [best[h] for h in sorted(best, reverse=True)]
    for entry in ordered:
        entry["size_label"] = format_bytes(entry.pop("approx_size"))
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
    return (
        f"bestvideo[height<={height}]+bestaudio/"
        f"best[height<={height}]/"
        f"bestvideo*+bestaudio/best"
    )
