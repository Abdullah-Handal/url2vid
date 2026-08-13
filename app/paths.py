"""Where everything lives, in a source checkout and inside a frozen bundle.

PyInstaller unpacks the application into a temporary directory and rewrites
``__file__`` to point inside it, so the usual ``Path(__file__).parent.parent``
trick silently resolves somewhere useless once packaged. Every path question is
answered here instead, so exactly one module has to know that.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "url2vid"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle rather than the source tree."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Read-only files shipped with the app: the built web UI and ffmpeg.

    ``sys._MEIPASS`` is the directory PyInstaller unpacks into; it only exists
    in a frozen build.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return Path(__file__).resolve().parent.parent


def web_dist() -> Path:
    """The built React UI."""
    return resource_dir() / "web" / "dist"


def data_dir() -> Path:
    """Writable per-user directory for settings and the updated yt-dlp.

    The bundle itself must be treated as read-only: on Windows it commonly
    lands under Program Files, and on Linux it may be a mounted AppImage.
    """
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / APP_NAME


def deps_dir() -> Path:
    """Where a newer yt-dlp is installed so it can shadow the bundled copy."""
    return data_dir() / "deps"


def settings_file() -> Path:
    return data_dir() / "settings.json"


def bundled_ffmpeg() -> Path | None:
    """The ffmpeg shipped beside the app, or None when running from source.

    Returning None lets yt-dlp fall back to whatever is on PATH, which is what
    a development checkout wants.
    """
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    candidate = resource_dir() / "bin" / name
    return candidate if candidate.is_file() else None


def _xdg_download_dir() -> Path | None:
    """Read XDG_DOWNLOAD_DIR out of the user's user-dirs.dirs.

    Parsed directly rather than shelling out to ``xdg-user-dir``, which is not
    installed everywhere and costs a subprocess at startup. Honours localised
    folder names, so a German desktop gets "Downloads" from its own config
    rather than a hard-coded English guess.
    """
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    dirs_file = config / "user-dirs.dirs"
    try:
        text = dirs_file.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("XDG_DOWNLOAD_DIR"):
            continue
        _, _, value = line.partition("=")
        value = value.strip().strip('"')
        if not value:
            return None
        expanded = os.path.expandvars(value.replace("$HOME", str(Path.home())))
        return Path(expanded)
    return None


def default_download_dir() -> Path:
    """The operating system's own Downloads folder.

    Where a packaged app is expected to put things, and somewhere the user can
    certainly write -- unlike a folder next to the executable.
    """
    if sys.platform != "win32":
        found = _xdg_download_dir()
        if found:
            return found
    if sys.platform == "win32":
        profile = os.environ.get("USERPROFILE")
        if profile:
            return Path(profile) / "Downloads"
    return Path.home() / "Downloads"


def _read_settings() -> dict:
    try:
        data = json.loads(settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def download_dir() -> Path:
    """Where finished videos are written: the saved choice, else the OS default."""
    saved = _read_settings().get("download_dir")
    if saved:
        return Path(saved).expanduser()
    return default_download_dir()


def save_download_dir(path: Path) -> None:
    """Persist the user's folder choice so it survives a restart."""
    data_dir().mkdir(parents=True, exist_ok=True)
    settings = _read_settings()
    settings["download_dir"] = str(path)
    settings_file().write_text(json.dumps(settings, indent=2), encoding="utf-8")
