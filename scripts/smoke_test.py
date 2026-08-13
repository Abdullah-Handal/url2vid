"""Prove a freshly built bundle works before it is published.

Starts the packaged executable in its headless serve mode and asks it to
resolve a real video. That exercises the two things packaging most often
breaks: yt-dlp's lazily loaded extractors, and the bundled web UI.

No window is opened, so this runs the same way on a CI runner as on a desktop,
and the app reports its own port rather than the test scraping netstat.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "url2vid" / ("url2vid.exe" if sys.platform == "win32" else "url2vid")
# A plain media file, not YouTube. Build runners sit in datacentre IP ranges
# that YouTube refuses with a bot check, so a YouTube probe fails on CI for
# reasons that say nothing about the bundle. This still exercises the whole
# path -- server, lazily loaded extractors, generic extraction.
PROBE_URL = "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_1MB.mp4"
# Tried as well, but never fatal: it proves site extractors work when the
# runner is not blocked, and is worth knowing about either way.
OPTIONAL_PROBE_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
READY = "url2vid listening on "


def main() -> int:
    if not EXE.is_file():
        print(f"no bundle at {EXE}", file=sys.stderr)
        return 1

    process = subprocess.Popen(
        [str(EXE), "--serve"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    try:
        base = _wait_for_url(process)
        if base is None:
            return 1

        config = json.load(urllib.request.urlopen(f"{base}/api/config", timeout=30))
        print("config:", config)

        index = urllib.request.urlopen(base + "/", timeout=30)
        if index.status != 200 or not index.read():
            print("the bundled web UI did not load", file=sys.stderr)
            return 1
        print("web UI served OK")

        request = _probe_request(base, PROBE_URL)
        info = json.load(urllib.request.urlopen(request, timeout=120))
        print(f"probe OK: {info['title']} ({info['extractor']})")
        if not info.get("title"):
            print("probe returned nothing usable", file=sys.stderr)
            return 1

        # Advisory only -- see OPTIONAL_PROBE_URL.
        try:
            extra = _probe(base, OPTIONAL_PROBE_URL)
            print(f"site extractor OK: {extra['title']} ({extra['extractor']})")
        except Exception as exc:  # noqa: BLE001
            print(f"note: {OPTIONAL_PROBE_URL} was not reachable from this runner ({exc})")
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()

    print("smoke test passed")
    return 0


def _probe_request(base: str, url: str) -> urllib.request.Request:
    return urllib.request.Request(
        f"{base}/api/probe",
        data=json.dumps({"url": url}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def _probe(base: str, url: str) -> dict:
    return json.load(urllib.request.urlopen(_probe_request(base, url), timeout=120))


def _wait_for_url(process: subprocess.Popen) -> str | None:
    """Read the app's own startup line rather than guessing its port."""
    assert process.stdout is not None
    for line in process.stdout:
        line = line.strip()
        if line:
            print(f"  [app] {line}")
        if line.startswith(READY):
            return line[len(READY):].strip()
        if process.poll() is not None:
            break
    print("the bundle exited before it was ready", file=sys.stderr)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
