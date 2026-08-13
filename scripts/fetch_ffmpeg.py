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
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"

LINUX = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
WINDOWS = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)
WANTED = ("ffmpeg", "ffprobe")


def _download(url: str) -> bytes:
    print(f"fetching {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "url2vid-build"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()


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
        _from_zip(_download(WINDOWS))
        required = [BIN / "ffmpeg.exe", BIN / "ffprobe.exe"]
    else:
        _from_tar(_download(LINUX))
        required = [BIN / "ffmpeg", BIN / "ffprobe"]

    missing = [str(path.name) for path in required if not path.is_file()]
    if missing:
        print(f"ERROR: archive did not contain {', '.join(missing)}", file=sys.stderr)
        return 1
    for path in required:
        print(f"{path.name}: {path.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
