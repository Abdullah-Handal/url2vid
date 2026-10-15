"""Prove a freshly built bundle works before it is published.

Starts the packaged executable in its headless serve mode and asks it to
resolve a real video. That exercises the two things packaging most often
breaks: yt-dlp's lazily loaded extractors, and the bundled web UI.

No window is opened, so this runs the same way on a CI runner as on a desktop,
and the app reports its own port rather than the test scraping netstat.

It then downloads a clip served from this machine as an MP3, which only works
if the app finds and runs the ffmpeg bundled inside it. ``--window`` also opens
the real window and waits for the UI to render inside it.

    python scripts/smoke_test.py                      # dist/url2vid/url2vid[.exe]
    python scripts/smoke_test.py path/to/url2vid.exe  # any other build
    python scripts/smoke_test.py --window             # plus the native window
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import subprocess
import sys
import tempfile
import threading
import time
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
# The build machine's copy, used only to make a test clip. The app must use
# the one inside its own bundle.
FFMPEG = ROOT / "bin" / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", nargs="*", help="the app to start (default: the onedir build)")
    parser.add_argument("--window", action="store_true", help="also check the native window renders")
    args = parser.parse_args()
    command = args.command or [str(EXE)]
    if not args.command and not EXE.is_file():
        print(f"no bundle at {EXE}", file=sys.stderr)
        return 1

    status = _serve_checks(command)
    if status == 0 and args.window:
        status = _window_check(command)
    if status == 0:
        print("smoke test passed")
    return status


def _serve_checks(command: list[str]) -> int:
    process = subprocess.Popen(
        [*command, "--serve"],
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

        if not _mp3_download(base, config["download_dir"]):
            return 1
    finally:
        _stop(process)
    return 0


def _stop(process: subprocess.Popen) -> None:
    if sys.platform == "win32":
        # /T: the portable exe is a launcher with the real app as its child,
        # and ending the launcher alone would leave the child running.
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
    else:
        process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()


def _mp3_download(base: str, download_dir: str) -> bool:
    """Download a locally served clip as MP3; the conversion runs the bundled ffmpeg."""
    if not FFMPEG.is_file():
        print(f"no {FFMPEG} to make a test clip with (run scripts/fetch_ffmpeg.py)", file=sys.stderr)
        return False
    with tempfile.TemporaryDirectory() as folder:
        clip = Path(folder) / "url2vid-smoke-clip.mp4"
        subprocess.run(
            [str(FFMPEG), "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
             "-f", "lavfi", "-i", "color=c=blue:s=160x120:d=3",
             "-shortest", "-c:a", "aac", "-y", str(clip)],
            check=True,
        )
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=folder)
        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as files:
            threading.Thread(target=files.serve_forever, daemon=True).start()
            url = f"http://127.0.0.1:{files.server_address[1]}/{clip.name}"
            job = _post(base, "/api/download", {
                "url": url, "title": "smoke", "audio_only": True, "audio_kbps": 128,
            })
            final = _wait_for_job(base, job["id"])
            files.shutdown()

    if final is None or final["status"] != "done" or not final.get("filename"):
        print(f"MP3 download failed: {final}", file=sys.stderr)
        return False
    saved = Path(download_dir) / final["filename"]
    data = saved.read_bytes() if saved.is_file() else b""
    is_mp3 = data.startswith(b"ID3") or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)
    if saved.suffix != ".mp3" or not is_mp3:
        print(f"{saved} is not an MP3 ({len(data)} bytes)", file=sys.stderr)
        return False
    print(f"MP3 download OK: {saved.name} ({len(data)} bytes, converted by the bundled ffmpeg)")
    saved.unlink()
    return True


def _wait_for_job(base: str, job_id: str, timeout: float = 120) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        listing = json.load(urllib.request.urlopen(f"{base}/api/jobs", timeout=30))
        job = next((j for j in listing["jobs"] if j["id"] == job_id), None)
        if job and job["status"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.5)
    return None


def _window_check(command: list[str]) -> int:
    """Open the real window and wait for the app to report the UI rendered."""
    try:
        result = subprocess.run(
            [*command, "--check-window"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        print(f"the window check hung: {exc.output}", file=sys.stderr)
        return 1
    for line in result.stdout.splitlines():
        print(f"  [app] {line}")
    if result.returncode != 0 or "url2vid window rendered" not in result.stdout:
        print("the native window did not render the UI", file=sys.stderr)
        return 1
    print("native window OK")
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


def _post(base: str, path: str, body: dict) -> dict:
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.load(urllib.request.urlopen(request, timeout=30))


def _wait_for_url(process: subprocess.Popen) -> str | None:
    """Read the app's own startup line rather than guessing its port."""
    assert process.stdout is not None
    for line in process.stdout:
        line = line.strip()
        if line:
            print(f"  [app] {line}")
        if line.startswith(READY):
            # Keep draining, so a chatty app can never block on a full pipe.
            threading.Thread(target=_echo, args=(process.stdout,), daemon=True).start()
            return line[len(READY):].strip()
        if process.poll() is not None:
            break
    print("the bundle exited before it was ready", file=sys.stderr)
    return None


def _echo(stream) -> None:
    for line in stream:
        print(f"  [app] {line.rstrip()}")


if __name__ == "__main__":
    raise SystemExit(main())
