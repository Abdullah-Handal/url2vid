"""Desktop entry point: a native window over the local download server.

The server, the download engine and the UI are all the ones the web build
already uses. This module only arranges them into something that opens like an
application: pick a free port, serve on loopback, and point an OS webview at it.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# A newer yt-dlp, if one has been fetched, must win over the copy frozen into
# the bundle -- so this happens before anything imports yt_dlp.
from app import paths  # noqa: E402  (deliberately first)

# A windowed build has no console attached, so Python leaves these as None.
# Anything that writes to them -- a stray print, a library's warning -- then
# fails at an unpredictable moment, so they are pointed at a sink up front.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")  # noqa: SIM115 - lives for the process
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")  # noqa: SIM115

_deps = paths.deps_dir()
if _deps.is_dir():
    sys.path.insert(0, str(_deps))

from app import downloader  # noqa: E402
from server.main import app as fastapi_app  # noqa: E402

log = logging.getLogger("url2vid")

WINDOW_TITLE = "url2vid"
WINDOW_SIZE = (980, 720)
MIN_SIZE = (620, 480)


def _reserve_port(preferred: int = 0) -> tuple[socket.socket, int]:
    """Bind a port and keep the socket. 0 lets the OS assign a free one.

    The socket is handed to uvicorn rather than closed and reopened, so nothing
    can take the port in between. A fixed port would collide with whatever else
    is running, including a second copy of this app.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Not on Windows: there SO_REUSEADDR lets a second socket bind a port that
    # is already in use, so a fixed --port could silently share someone's port.
    if sys.platform != "win32":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", preferred))
    sock.listen(128)
    return sock, sock.getsockname()[1]


def _ensure_download_dir() -> Path:
    """Make sure the download folder exists, falling back to the OS default.

    The saved folder may be on a USB stick or network drive that is not there
    today. Failing to create it used to kill the windowed app at launch with
    nothing on screen. The saved choice is left alone so it works again once
    the drive is back.
    """
    try:
        downloader.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("download folder %s unavailable (%s); using the default", downloader.DOWNLOAD_DIR, exc)
        downloader.DOWNLOAD_DIR = paths.default_download_dir()
        downloader.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return downloader.DOWNLOAD_DIR


class _Server:
    """uvicorn on a background thread, with a shutdown that actually returns."""

    def __init__(self, sock: socket.socket) -> None:
        import uvicorn

        self._sock = sock
        self._config = uvicorn.Config(
            fastapi_app,
            log_level="warning",
            access_log=False,
            lifespan="off",
            # uvicorn's default logging config declares handlers writing to
            # ext://sys.stderr. In a windowed build that is None, and
            # dictConfig dies with "Unable to configure formatter 'default'"
            # before the server ever starts. Nothing here needs uvicorn's log
            # formatting, so the config is skipped rather than repaired.
            log_config=None,
            # Stated rather than auto-detected: uvloop and httptools are
            # optional C accelerators worth ~17 MB that a loopback server
            # serving one user gains nothing from. Naming the pure-Python
            # pair here means excluding them cannot alter behaviour.
            loop="asyncio",
            http="h11",
        )
        self._server = uvicorn.Server(self._config)
        self._thread = threading.Thread(target=self._run, name="server", daemon=True)

    def _run(self) -> None:
        self._server.run(sockets=[self._sock])

    def start(self, timeout: float = 20.0) -> bool:
        self._thread.start()
        deadline = threading.Event()
        waited = 0.0
        while waited < timeout:
            if self._server.started:
                return True
            deadline.wait(0.05)
            waited += 0.05
        return False

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)


class Api:
    """Methods the page can call as ``window.pywebview.api.*``."""

    def __init__(self) -> None:
        # Private on purpose: pywebview exposes every public attribute of this
        # object to the page, recursing into it. A public window made it walk
        # the whole WinForms object graph on each page load, so the bridge
        # took minutes to appear and the UI fell back to browser mode.
        self._window = None

    def choose_folder(self) -> dict:
        """Open the OS folder picker and send downloads there from now on.

        A native dialog rather than the browser's File System Access API: the
        server is on this machine, so it can simply be told where to write.
        That also sidesteps the API being unavailable outside Chrome.
        """
        import webview

        if self._window is None:
            return {"ok": False, "error": "No window."}
        picked = self._window.create_file_dialog(
            webview.FOLDER_DIALOG, directory=str(downloader.DOWNLOAD_DIR)
        )
        if not picked:
            return {"ok": False, "cancelled": True}
        target = picked[0] if isinstance(picked, (list, tuple)) else picked
        try:
            resolved = downloader.set_download_dir(Path(target))
        except OSError as exc:
            return {"ok": False, "error": f"Cannot write to that folder: {exc}"}
        return {"ok": True, "download_dir": str(resolved)}

    def reveal_downloads(self) -> dict:
        """Open the download folder in the system file manager."""
        import subprocess

        folder = downloader.DOWNLOAD_DIR
        folder.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(folder)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}


def _open_window(url: str, api: Api, on_start=None) -> bool:
    """Show the app in a native window. False if no webview is available.

    ``on_start(window)`` runs on its own thread once the GUI loop is up.
    """
    try:
        import webview
    except ImportError:
        log.warning("pywebview is not installed")
        return False

    try:
        window = webview.create_window(
            WINDOW_TITLE,
            url,
            width=WINDOW_SIZE[0],
            height=WINDOW_SIZE[1],
            min_size=MIN_SIZE,
            js_api=api,
        )
        api._window = window
        if on_start:
            webview.start(on_start, window)
        else:
            webview.start()
        return True
    except Exception as exc:  # noqa: BLE001 - any backend failure falls back
        log.warning("native window unavailable: %s", exc)
        return False


def _window_renders(window, timeout: float = 60.0) -> bool:
    """True once the page inside the window has mounted the React UI."""
    if not window.events.loaded.wait(timeout):
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if window.evaluate_js("document.getElementById('root').childElementCount"):
                return True
        except Exception:  # noqa: BLE001 - the page may still be loading
            pass
        time.sleep(0.5)
    return False


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="url2vid", description="Download videos from a URL.")
    parser.add_argument(
        "--serve",
        action="store_true",
        help="run the server without opening a window (used by the build's smoke test)",
    )
    parser.add_argument(
        "--check-window",
        action="store_true",
        help="open the window, confirm the UI renders, then exit (used by the build's smoke test)",
    )
    parser.add_argument(
        "--port", type=int, default=0, help="port to listen on; 0 lets the OS choose"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    if not paths.web_dist().is_dir():
        print(
            "The web interface has not been built.\n"
            "Run:  cd web && npm install && npm run build",
            file=sys.stderr,
        )
        return 1

    _ensure_download_dir()

    sock, port = _reserve_port(args.port)
    url = f"http://127.0.0.1:{port}"
    server = _Server(sock)

    if not server.start():
        print("The download server did not start.", file=sys.stderr)
        return 1

    # Announced on stdout so a caller never has to scrape netstat/ss for it --
    # those differ per platform and were the smoke test's weakest link.
    print(f"url2vid listening on {url}", flush=True)

    if args.serve:
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            server.stop()
        return 0

    if args.check_window:
        # Proves the part --serve never touches: the webview backend (WinForms
        # via pythonnet + WebView2 on Windows, GTK + WebKit on Linux) loads in
        # the frozen build and actually renders the page.
        result = {}

        def check(window) -> None:
            result["ok"] = _window_renders(window)
            window.destroy()

        try:
            opened = _open_window(url, Api(), on_start=check)
        finally:
            server.stop()
        ok = opened and result.get("ok", False)
        print("url2vid window rendered" if ok else "url2vid window did not render", flush=True)
        return 0 if ok else 1

    try:
        if not _open_window(url, Api()):
            # No webview on this machine: fall back to the default browser so
            # the app still works rather than failing outright.
            print(f"Opening {url} in your browser (no native window available).")
            webbrowser.open(url)
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                pass
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
