"""Full-screen terminal dashboard for url2vid."""

from __future__ import annotations

from rich.markup import escape
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Footer, Header, Input, ListItem, ListView, Select, Static

from . import downloader, jobs
from .jobs import registry

# Colour per job status, and the label shown on the right of each row.
STATUS_STYLE = {
    jobs.QUEUED: ("dim white", "waiting"),
    jobs.DOWNLOADING: ("bright_cyan", ""),
    jobs.MERGING: ("bright_yellow", "merging"),
    jobs.DONE: ("bright_green", "done"),
    jobs.ERROR: ("bright_red", "failed"),
    jobs.CANCELLED: ("grey50", "cancelled"),
}

# Column widths, sized so a full row fits inside a 100-column terminal.
NAME_WIDTH = 30
BAR_WIDTH = 20
HEADINGS = (
    f"{'NAME':<{NAME_WIDTH}} {'RES':>5} {'PROGRESS':<{BAR_WIDTH}} "
    f"{'%':>6} {'LEFT':>8} {'SPEED':>10} {'SIZE':>9}"
)


def render_bar(pct: float | None, colour: str) -> str:
    """A block-character progress bar as Rich markup."""
    if pct is None:
        return f"[dim]{'╌' * BAR_WIDTH}[/]"
    filled = int(round(pct / 100 * BAR_WIDTH))
    return f"[{colour}]{'█' * filled}[/][dim]{'░' * (BAR_WIDTH - filled)}[/]"


def _fit(text: str, width: int) -> str:
    """Pad or ellipsise to exactly `width` columns."""
    if len(text) > width:
        return text[: width - 1] + "…"
    return f"{text:<{width}}"


def render_row(job: dict) -> str:
    """One download rendered as a single fixed-width markup line."""
    colour, label = STATUS_STYLE.get(job["status"], ("white", job["status"]))
    name = f"[bold]{escape(_fit(job['title'], NAME_WIDTH))}[/]"

    if job["status"] == jobs.ERROR:
        detail = _fit(job.get("error") or "failed", 62)
        return f"{name} [bright_red]✗ {escape(detail)}[/]"

    pct = job["percent"]
    res = f"[dim]{(str(job['height']) + 'p') if job['height'] else 'best':>5}[/]"
    bar = render_bar(pct, colour)
    pct_text = f"[{colour}]{pct:5.1f}%[/]" if pct is not None else "[dim]    --[/]"

    # While running, the right-hand columns are the countdown and speed;
    # otherwise the status word sits in the countdown column.
    if job["status"] == jobs.DOWNLOADING:
        left = f"[{colour}]{(job['eta_label'] or '…'):>8}[/]"
        speed = f"[dim]{(job['speed_label'] or ''):>10}[/]"
    else:
        left = f"[{colour}]{label:>8}[/]"
        speed = " " * 10

    size = f"[dim]{(job['size_label'] or ''):>9}[/]"
    return f"{name} {res} {bar} {pct_text} {left} {speed} {size}"


class Url2VidApp(App):
    """Paste a URL, pick a resolution, watch it download."""

    CSS = """
    Screen { background: $surface; }
    #entry { height: auto; padding: 1 2 0 2; }
    #url { width: 1fr; }
    #res { width: 28; margin-left: 1; }
    #status { padding: 0 2; height: 1; color: $text-muted; }
    #headings { padding: 0 2; height: 1; color: $text-muted; text-style: bold; }
    #list { height: 1fr; border: none; background: $surface; padding: 0 1; }
    ListItem { background: $surface; padding: 0 1; }
    ListItem.--highlight { background: $primary-darken-2; }
    """

    # The URL box holds focus by default and swallows plain letters, so each
    # action also gets a function key. Ctrl chords are avoided deliberately:
    # Input already owns ctrl+x (cut), ctrl+k, ctrl+d, ctrl+u and friends.
    BINDINGS = [
        Binding("f2,d", "focus_url", "New"),
        Binding("escape", "focus_list", "Select"),
        Binding("f3,c", "cancel", "Cancel"),
        Binding("f4,x", "clear", "Clear done"),
        Binding("f5,o", "open_folder", "Folder"),
        Binding("ctrl+q,q", "quit", "Quit"),
    ]

    TITLE = "url2vid"
    SUB_TITLE = "paste a link, get the video"

    def __init__(self) -> None:
        super().__init__()
        self._pending_url: str | None = None
        self._pending_title: str = ""
        self._revision = -1
        self._row_ids: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="entry"):
            with Horizontal():
                yield Input(placeholder="Paste a video URL and press Enter…", id="url")
                yield Select([], prompt="Resolution", id="res", disabled=True)
        yield Static("", id="status")
        yield Static(HEADINGS, id="headings")
        yield ListView(id="list")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#url", Input).focus()
        self.set_interval(0.2, self.refresh_jobs)
        self.set_status("Ready — paste a link above. Esc selects downloads, F4 clears finished.", "cyan")

    # ---------------------------------------------------------------- helpers

    def set_status(self, message: str, colour: str = "white") -> None:
        try:
            self.query_one("#status", Static).update(f"[{colour}]{escape(message)}[/]")
        except NoMatches:
            pass

    # ------------------------------------------------------------- probe flow

    @on(Input.Submitted, "#url")
    def handle_url(self, event: Input.Submitted) -> None:
        url = event.value.strip()
        if not url:
            return
        if not url.startswith(("http://", "https://")):
            self.set_status("That needs to be a full URL starting with http:// or https://", "bright_red")
            return
        self.set_status(f"Fetching info for {url} …", "bright_yellow")
        self.query_one("#res", Select).disabled = True
        self.probe_url(url)

    @work(thread=True, exclusive=True)
    def probe_url(self, url: str) -> None:
        """Look up title + resolutions off the UI thread."""
        try:
            info = downloader.probe(url)
        except Exception as exc:  # noqa: BLE001 - show the site's own reason
            message = downloader.clean_error(str(exc))
            self.call_from_thread(self.set_status, f"Couldn't read that link: {message}", "bright_red")
            return
        self.call_from_thread(self.show_formats, url, info)

    def show_formats(self, url: str, info: dict) -> None:
        options = [("Best available", "best")]
        for fmt in info["formats"]:
            label = fmt["label"] + (f"  ({fmt['size_label']})" if fmt["size_label"] else "")
            options.append((label, str(fmt["height"])))

        select = self.query_one("#res", Select)
        select.set_options(options)
        select.disabled = False
        self._pending_url = url
        self._pending_title = info["title"]

        note = f" — {info['note']}" if info.get("note") else ""
        source = f" [{info['extractor']}]" if info.get("extractor") else ""
        self.set_status(f"{info['title']}{source}{note}  →  choose a resolution", "bright_green")
        select.focus()
        select.expanded = True

    @on(Select.Changed, "#res")
    def handle_resolution(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK or self._pending_url is None:
            return
        height = None if event.value == "best" else int(event.value)
        downloader.start(self._pending_url, height, self._pending_title)
        self.set_status(
            f"Downloading {self._pending_title} at {height or 'best'}{'p' if height else ''}",
            "bright_cyan",
        )

        self._pending_url = None
        select = self.query_one("#res", Select)
        select.set_options([])
        select.disabled = True
        url_input = self.query_one("#url", Input)
        url_input.value = ""
        url_input.focus()

    # ------------------------------------------------------------- live table

    def refresh_jobs(self) -> None:
        revision, job_list = registry.snapshot()
        try:
            listview = self.query_one("#list", ListView)
        except NoMatches:
            # The timer can outlive the widget tree during shutdown.
            return
        ids = [job["id"] for job in job_list]

        if ids != self._row_ids:
            # Job added or cleared: rebuild, preserving the highlighted row.
            keep = listview.index
            listview.clear()
            for job in job_list:
                listview.append(ListItem(Static(render_row(job), id=f"row-{job['id']}")))
            self._row_ids = ids
            if keep is not None and 0 <= keep < len(ids):
                listview.index = keep
        elif revision != self._revision:
            # Same rows, changed numbers: update text in place, no flicker.
            for job in job_list:
                try:
                    self.query_one(f"#row-{job['id']}", Static).update(render_row(job))
                except NoMatches:
                    pass  # row not mounted yet; the next tick will catch it
        self._revision = revision

    # --------------------------------------------------------------- actions

    def action_focus_url(self) -> None:
        self.query_one("#url", Input).focus()

    def action_focus_list(self) -> None:
        """Leave the URL box so the single-letter shortcuts become available."""
        listview = self.query_one("#list", ListView)
        listview.focus()
        if listview.index is None and self._row_ids:
            listview.index = 0

    def action_cancel(self) -> None:
        listview = self.query_one("#list", ListView)
        index = listview.index
        if index is None or index >= len(self._row_ids):
            self.set_status("Select a download with ↑/↓ first, then press c.", "bright_yellow")
            return
        job_id = self._row_ids[index]
        if registry.request_cancel(job_id):
            self.set_status("Cancelling…", "bright_yellow")
        else:
            self.set_status("That download already finished.", "bright_yellow")

    def action_clear(self) -> None:
        count = registry.clear_finished()
        self.set_status(f"Cleared {count} finished download{'s' if count != 1 else ''}.", "cyan")

    def action_open_folder(self) -> None:
        self.set_status(f"Saving to {downloader.DOWNLOAD_DIR}", "cyan")


def run() -> None:
    Url2VidApp().run()
