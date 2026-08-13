"""Prove a freshly built bundle actually works before it is published.

Starts the packaged executable, finds the port it chose, and asks it to resolve
a real video. That exercises the two things packaging most often breaks:
yt-dlp's lazily-loaded extractors, and the bundled web UI.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "url2vid" / ("url2vid.exe" if sys.platform == "win32" else "url2vid")
PROBE_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def main() -> int:
    if not EXE.is_file():
        print(f"no bundle at {EXE}", file=sys.stderr)
        return 1

    env = dict(os.environ)
    # No display on a CI runner, so skip the window and let it serve headless.
    env["PYWEBVIEW_GUI"] = "mshtml" if sys.platform == "win32" else "gtk"

    process = subprocess.Popen([str(EXE)], env=env)
    try:
        port = _find_port(process.pid)
        if port is None:
            print("the bundle never opened a port", file=sys.stderr)
            return 1
        base = f"http://127.0.0.1:{port}"

        config = json.load(urllib.request.urlopen(f"{base}/api/config", timeout=20))
        print("config:", config)

        request = urllib.request.Request(
            f"{base}/api/probe",
            data=json.dumps({"url": PROBE_URL}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        info = json.load(urllib.request.urlopen(request, timeout=90))
        print(f"probe OK: {info['title']} ({info['extractor']})")
        if not info.get("title"):
            return 1
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    print("smoke test passed")
    return 0


def _find_port(pid: int, attempts: int = 40) -> int | None:
    """Poll for the loopback port the app bound to."""
    import re

    for _ in range(attempts):
        time.sleep(2)
        if platform.system() == "Windows":
            out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
            pattern = re.compile(rf"127\.0\.0\.1:(\d+)\s+\S+\s+LISTENING\s+{pid}\b")
        else:
            out = subprocess.run(["ss", "-lntp"], capture_output=True, text=True).stdout
            pattern = re.compile(rf"127\.0\.0\.1:(\d+).*pid={pid}\b")
        match = pattern.search(out)
        if match:
            return int(match.group(1))
    return None


if __name__ == "__main__":
    raise SystemExit(main())
