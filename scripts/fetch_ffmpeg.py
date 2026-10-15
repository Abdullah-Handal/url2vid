"""Download a static ffmpeg for the platform being built on.

The system ffmpeg cannot be bundled: it is dynamically linked against dozens of
libraries that will not exist on someone else's machine. These builds are
self-contained single binaries.

Both builds are GPL. Redistributing them means shipping their licence, which
``LICENSE-ffmpeg.txt`` alongside the binary covers.
"""

from __future__ import annotations

import io
import shutil
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"

# Tried in order. The first is the smallest build, but it is one person's
# server and intermittently answers with something that is not the archive
# (a rate-limit or error page), which failed a build mid-release. The second
# is larger but sits on GitHub's infrastructure.
LINUX_SOURCES = (
    "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-linux64-gpl.tar.xz",
)
LINUX = LINUX_SOURCES[0]

# First bytes of an xz stream. Checked before unpacking so a served error page
# is reported as what it is, rather than as "not an lzma file".
XZ_MAGIC = b"\xfd7zXZ\x00"
WINDOWS = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)
WANTED = ("ffmpeg", "ffprobe")
ATTEMPTS = 3


def _download(url: str) -> bytes:
    print(f"fetching {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "url2vid-build"})
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


def _download_archive(sources: tuple[str, ...], magic: bytes) -> bytes:
    """Download the first source that actually returns the expected archive."""
    problems = []
    # Each source gets a few tries: Windows has only one, so a single network
    # blip on it used to fail the whole release build.
    for url in sources:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                payload = _download(url)
            except Exception as exc:  # noqa: BLE001 - any failure is retried
                problems.append(f"{url} (try {attempt}): {exc}")
                print(f"  failed: {exc}")
            else:
                if payload.startswith(magic):
                    return payload
                head = payload[:80].decode("utf-8", "replace").strip()
                problems.append(f"{url} (try {attempt}): not an archive (starts with {head!r})")
                print("  failed: response was not an archive")
            if attempt < ATTEMPTS:
                time.sleep(5 * attempt)
    raise RuntimeError("could not download ffmpeg:\n  " + "\n  ".join(problems))


def _from_tar(payload: bytes) -> None:
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:xz") as archive:
        for member in archive.getmembers():
            name = Path(member.name).name
            if member.isfile() and name in WANTED:
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                target = BIN / name
                target.write_bytes(extracted.read())
                target.chmod(0o755)
                print(f"  -> {target.relative_to(ROOT)}")
            elif member.isfile() and name in ("LICENSE", "GPLv3.txt"):
                (BIN / "LICENSE-ffmpeg.txt").write_bytes(archive.extractfile(member).read())


def _from_zip(payload: bytes) -> None:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for entry in archive.namelist():
            name = Path(entry).name
            if name in (f"{w}.exe" for w in WANTED):
                target = BIN / name
                target.write_bytes(archive.read(entry))
                print(f"  -> {target.relative_to(ROOT)}")
            elif name == "LICENSE.txt":
                (BIN / "LICENSE-ffmpeg.txt").write_bytes(archive.read(entry))


def main() -> int:
    BIN.mkdir(exist_ok=True)
    if sys.platform == "win32":
        _from_zip(_download_archive((WINDOWS,), b"PK\x03\x04"))
        required = [BIN / "ffmpeg.exe", BIN / "ffprobe.exe"]
    else:
        _from_tar(_download_archive(LINUX_SOURCES, XZ_MAGIC))
        required = [BIN / "ffmpeg", BIN / "ffprobe"]

    # The spec bundles this unconditionally, and archives do not all carry a
    # licence at a predictable path. Writing a pointer beats failing the build,
    # and still satisfies the GPL requirement to say where the source is.
    licence = BIN / "LICENSE-ffmpeg.txt"
    if not licence.is_file():
        licence.write_text(
            "ffmpeg is distributed under the GNU General Public License.\n"
            "Source and full licence text: https://ffmpeg.org/legal.html\n"
            f"Build obtained from: {WINDOWS if sys.platform == 'win32' else LINUX}\n",
            encoding="utf-8",
        )

    missing = [str(path.name) for path in required if not path.is_file()]
    if missing:
        print(f"ERROR: archive did not contain {', '.join(missing)}", file=sys.stderr)
        return 1
    for path in required:
        print(f"{path.name}: {path.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
