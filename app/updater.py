"""Keep yt-dlp current without reinstalling the app.

Extractors break whenever a video site changes, which is often. A frozen build
ships whatever yt-dlp was current on release day, so without a way to refresh it
the app quietly stops working for anyone who cannot rebuild it.

A newer copy is unpacked into ``paths.deps_dir()``, which the entry point puts
at the front of ``sys.path`` -- so it shadows the bundled one from the next
launch. Nothing overwrites the bundle itself, which may be read-only.
"""

from __future__ import annotations

import io
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

from . import paths

PYPI = "https://pypi.org/pypi/yt-dlp/json"
TIMEOUT = 30


def installed_version() -> str:
    try:
        # Lives in the submodule, not on the package itself.
        from yt_dlp.version import __version__

        return __version__
    except Exception:  # noqa: BLE001 - a broken install must still report
        return "unknown"


def latest_version() -> str:
    with urllib.request.urlopen(PYPI, timeout=TIMEOUT) as response:
        data = json.load(response)
    return data["info"]["version"]


def _same_version(a: str, b: str) -> bool:
    """Compare releases despite inconsistent zero-padding.

    yt-dlp reports itself as "2026.07.04" while PyPI names the same release
    "2026.7.4"; compared as strings they never match, so the app would
    re-download an identical copy on every check.
    """
    def parts(value: str) -> tuple:
        try:
            return tuple(int(piece) for piece in value.split("."))
        except ValueError:
            return (value,)

    return parts(a) == parts(b)


def _wheel_url(version: str) -> str:
    """The pure-Python wheel for a given yt-dlp release.

    A wheel is a zip, so it can be unpacked directly. That avoids needing pip,
    which is not present inside a PyInstaller bundle.
    """
    with urllib.request.urlopen(PYPI, timeout=TIMEOUT) as response:
        data = json.load(response)
    for item in data["releases"].get(version, []):
        if item["packagetype"] == "bdist_wheel" and item["filename"].endswith("-none-any.whl"):
            return item["url"]
    raise RuntimeError(f"No portable wheel published for yt-dlp {version}.")


def _safe_members(archive: zipfile.ZipFile) -> list[str]:
    """Members that stay inside the target directory.

    A zip may contain absolute or ``..`` paths; extracting those would write
    outside the deps folder.
    """
    safe = []
    for name in archive.namelist():
        candidate = Path(name)
        if candidate.is_absolute() or ".." in candidate.parts:
            continue
        safe.append(name)
    return safe


def update(force: bool = False) -> dict:
    """Fetch the newest yt-dlp into the deps directory.

    Returns what happened rather than raising, so the UI can report it.
    """
    current = installed_version()
    latest = latest_version()
    if not force and _same_version(current, latest):
        return {"updated": False, "current": current, "latest": latest, "reason": "already current"}

    url = _wheel_url(latest)
    with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
        payload = response.read()

    target = paths.deps_dir()
    staging = target.parent / "deps.new"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        archive.extractall(staging, members=_safe_members(archive))

    # Swap only once the new copy is complete, so a failed download cannot
    # leave a half-written package that breaks the next start.
    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)

    return {"updated": True, "current": current, "latest": latest, "restart_required": True}
