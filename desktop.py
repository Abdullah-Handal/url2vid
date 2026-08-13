"""Desktop entry point: a native window over the local download server.

The server, the download engine and the UI are all the ones the web build
already uses. This module only arranges them into something that opens like an
application: pick a free port, serve on loopback, and point an OS webview at it.
"""

from __future__ import annotations

import logging
import socket
import sys
import threading
import webbrowser
from pathlib import Path

# A newer yt-dlp, if one has been fetched, must win over the copy frozen into
# the bundle -- so this happens before anything imports yt_dlp.
from app import paths  # noqa: E402  (deliberately first)

_deps = paths.deps_dir()
if _deps.is_dir():
    sys.path.insert(0, str(_deps))

from app import downloader  # noqa: E402
from server.main import app as fastapi_app  # noqa: E402

log = logging.getLogger("url2vid")

WINDOW_TITLE = "url2vid"
WINDOW_SIZE = (980, 720)
MIN_SIZE = (620, 480)


def _reserve_port() -> tuple[socket.socket, int]:
    """Bind an OS-assigned free port and keep the socket.

    The socket is handed to uvicorn rather than closed and reopened, so nothing
    can take the port in between. A fixed port would collide with whatever else
    is running, including a second copy of this app.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    return sock, sock.getsockname()[1]


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
        self.window = None

    def choose_folder(self) -> dict:
        """Open the OS folder picker and send downloads there from now on.

        A native dialog rather than the browser's File System Access API: the
        server is on this machine, so it can simply be told where to write.
        That also sidesteps the API being unavailable outside Chrome.
        """
        import webview

        if self.window is None:
            return {"ok": False, "error": "No window."}
        picked = self.window.create_file_dialog(
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


def _open_window(url: str, api: Api) -> bool:
    """Show the app in a native window. False if no webview is available."""
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
        api.window = window
        webview.start()
        return True
    except Exception as exc:  # noqa: BLE001 - any backend failure falls back
        log.warning("native window unavailable: %s", exc)
        return False


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    if not paths.web_dist().is_dir():
        print(
            "The web interface has not been built.\n"
            "Run:  cd web && npm install && npm run build",
            file=sys.stderr,
        )
        return 1

    downloader.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    sock, port = _reserve_port()
    url = f"http://127.0.0.1:{port}"
    server = _Server(sock)

    if not server.start():
        print("The download server did not start.", file=sys.stderr)
        return 1

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
