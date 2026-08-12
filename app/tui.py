"""Full-screen terminal dashboard for url2vid."""

from __future__ import annotations

from urllib.parse import urlparse

from rich.markup import escape
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    ListItem,
    ListView,
    Select,
    Static,
)

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

# Severity styling for the message line: colour plus a leading glyph, so the
# kind of message is readable even where colour is washed out.
MESSAGE_STYLE = {
    "info": ("cyan", "•"),
    "busy": ("bright_yellow", "◐"),
    "ok": ("bright_green", "✓"),
    "warn": ("bright_yellow", "!"),
    "error": ("bright_red", "✗"),
}

# A link ending in one of these *is* the video, so there is no resolution to
# choose and the download can start as soon as the title is known.
DIRECT_SUFFIXES = (
    ".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi",
    ".flv", ".ts", ".mp3", ".m4a", ".m3u8", ".mpd",
)

# Column widths. The total below must stay inside a 100-column terminal
# once the list's own indent is taken off; test_row_fits_a_100_column_terminal
# pins it.
NAME_WIDTH = 28
BAR_WIDTH = 20
# Columns the ListItem padding eats on each side of every row.
LIST_INDENT = 2
HEADINGS = (
    f"{'NAME':<{NAME_WIDTH}} {'RES':>5} {'PROGRESS':<{BAR_WIDTH}} "
    f"{'%':>6} {'LEFT':>8} {'SPEED':>10} {'SIZE':>9}"
)
ROW_WIDTH = len(HEADINGS)
# What is left for an error message after the name column and the "✗ " marker.
# Derived rather than hard-coded so the row cannot silently outgrow the table.
ERROR_WIDTH = ROW_WIDTH - NAME_WIDTH - 3


def is_direct_media(url: str) -> bool:
    """True when the URL points straight at a media file.

    Checked on the path only: a query string like ``?token=…`` is common on
    signed download links and must not hide the extension.
    """
    path = urlparse(url).path.lower()
    return path.endswith(DIRECT_SUFFIXES)


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
        # Trimmed to keep the row on one line; the untrimmed text is repeated
        # in the message panel when the job fails.
        detail = _fit(job.get("error") or "failed", ERROR_WIDTH)
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


def describe_found(info: dict) -> str:
    """The one-line summary shown under a video's title after a successful fetch."""
    bits = []
    if info.get("extractor"):
        bits.append(str(info["extractor"]))
    duration = info.get("duration")
    if duration:
        total = int(duration)
        bits.append(f"{total // 60}:{total % 60:02d}")
    count = len(info.get("formats") or [])
    bits.append(f"{count} resolution{'s' if count != 1 else ''}" if count else "single stream")
    if info.get("note"):
        bits.append(str(info["note"]))
    return " · ".join(bits)


class Url2VidApp(App):
    """Paste a URL, fetch it, watch it download."""

    CSS = """
    Screen { background: $surface; }
    #entry { height: auto; padding: 1 2 0 2; }
    #choose, #entry { align-vertical: top; }
    #url { width: 1fr; }
    #fetch { min-width: 12; margin-left: 1; }
    #found {
        height: auto; max-height: 3; padding: 0 1; margin: 1 2 0 2;
        border-left: thick $success; background: $boost; display: none;
    }
    #choose { height: auto; padding: 1 2 0 2; display: none; }
    #res { width: 30; }
    #go { min-width: 14; margin-left: 1; }
    #message { height: auto; max-height: 4; padding: 1 2 0 2; }
    #headings { padding: 1 2 0 2; height: 2; color: $text-muted; text-style: bold; }
    #list { height: 1fr; border: none; background: $surface; padding: 0; }
    ListItem { background: $surface; padding: 0 2; }
    ListItem.--highlight { background: $primary-darken-2; }
    /* Rows are fixed-width by design; wrapping one would double its height and
       shear the whole table. Narrow terminals clip instead. */
    ListItem Static { text-wrap: nowrap; text-overflow: ellipsis; }
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
        # Last status announced per job, so each finish or failure is reported
        # in the message panel exactly once.
        self._announced: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="entry"):
            yield Input(placeholder="Paste a video URL and press Enter…", id="url")
            yield Button("Fetch", variant="primary", id="fetch")
        yield Static("", id="found")
        with Horizontal(id="choose"):
            yield Select([], prompt="Choose a resolution", id="res")
            yield Button("Download", variant="success", id="go")
        yield Static("", id="message")
        yield Static(HEADINGS, id="headings")
        yield ListView(id="list")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#url", Input).focus()
        self.set_interval(0.2, self.refresh_jobs)
        self.say("Paste a link and press Enter or click Fetch.", "info")

    # ---------------------------------------------------------------- helpers

    def say(self, message: str, kind: str = "info") -> None:
        """Put a message in the panel under the input. Never silently drops."""
        colour, glyph = MESSAGE_STYLE.get(kind, ("white", "•"))
        try:
            self.query_one("#message", Static).update(
                f"[{colour}]{glyph} {escape(message)}[/]"
            )
        except NoMatches:
            pass

    def show_found(self, title: str, detail: str) -> None:
        """Reveal the found-video panel with its title and summary line."""
        try:
            panel = self.query_one("#found", Static)
        except NoMatches:
            return
        panel.update(f"[bold bright_white]{escape(title)}[/]\n[dim]{escape(detail)}[/]")
        panel.styles.display = "block"

    def hide_found(self) -> None:
        """Clear the whole result area, ready for a fresh lookup."""
        for widget_id in ("#found", "#choose"):
            self._hide(widget_id)

    def hide_choose(self) -> None:
        """Put the picker away but leave the title on screen.

        Once a download starts the resolution question is answered, yet the
        title is still the useful thing to be looking at.
        """
        self._hide("#choose")

    def _hide(self, widget_id: str) -> None:
        try:
            self.query_one(widget_id).styles.display = "none"
        except NoMatches:
            pass

    def set_busy(self, busy: bool) -> None:
        """Flip the Fetch button between idle and in-flight."""
        try:
            button = self.query_one("#fetch", Button)
        except NoMatches:
            return
        button.disabled = busy
        button.label = "Searching…" if busy else "Fetch"

    # ------------------------------------------------------------- probe flow

    @on(Button.Pressed, "#fetch")
    def handle_fetch_click(self, event: Button.Pressed) -> None:
        self.start_probe(self.query_one("#url", Input).value)

    @on(Input.Submitted, "#url")
    def handle_url(self, event: Input.Submitted) -> None:
        self.start_probe(event.value)

    def start_probe(self, raw: str) -> None:
        """Validate the URL and kick off a lookup, reporting every rejection."""
        url = raw.strip()
        if not url:
            self.say("Nothing to fetch — paste a video URL in the box first.", "warn")
            return
        if not url.startswith(("http://", "https://")):
            self.say(
                "That is not a full URL. It has to start with http:// or https://",
                "error",
            )
            return
        self.hide_found()
        self._pending_url = None
        self.set_busy(True)
        self.say("Searching that link for a video…", "busy")
        self.probe_url(url)

    @work(thread=True, exclusive=True)
    def probe_url(self, url: str) -> None:
        """Look up title + resolutions off the UI thread."""
        try:
            info = downloader.probe(url)
        except Exception as exc:  # noqa: BLE001 - show the site's own reason
            message = downloader.explain_error(str(exc), url)
            self.call_from_thread(self.probe_failed, message)
            return
        self.call_from_thread(self.show_formats, url, info)

    def probe_failed(self, message: str) -> None:
        # explain_error already returns a whole sentence, so it is shown as-is
        # rather than buried behind a lead-in that would push it off the panel.
        self.set_busy(False)
        self.say(message, "error")

    def show_formats(self, url: str, info: dict) -> None:
        """Report what was found, then either offer resolutions or just go."""
        self.set_busy(False)
        self._pending_url = url
        self._pending_title = info["title"]
        self.show_found(info["title"], describe_found(info))

        formats = info.get("formats") or []
        # A direct file link, or a site serving one pre-muxed stream, leaves
        # nothing to choose — asking would be a pointless extra click.
        if not formats or is_direct_media(url):
            self.begin_download(None)
            return

        options = [("Best available", "best")]
        for fmt in formats:
            label = fmt["label"] + (f"  ({fmt['size_label']})" if fmt["size_label"] else "")
            options.append((label, str(fmt["height"])))

        select = self.query_one("#res", Select)
        select.set_options(options)
        select.value = "best"
        self.query_one("#choose").styles.display = "block"
        self.say(
            f"Found “{info['title']}” — pick a resolution and press Download.", "ok"
        )
        select.focus()

    # ---------------------------------------------------------- download flow

    @on(Button.Pressed, "#go")
    def handle_go(self, event: Button.Pressed) -> None:
        if self._pending_url is None:
            self.say("Fetch a link first, then press Download.", "warn")
            return
        value = self.query_one("#res", Select).value
        if value is Select.BLANK:
            self.say("Pick a resolution from the list first.", "warn")
            return
        self.begin_download(None if value == "best" else int(value))

    def begin_download(self, height: int | None) -> None:
        """Queue the pending URL and reset the entry row for the next link."""
        if self._pending_url is None:
            self.say("Fetch a link first, then press Download.", "warn")
            return
        downloader.start(self._pending_url, height, self._pending_title)
        quality = f"{height}p" if height else "best quality"
        self.say(f"Downloading “{self._pending_title}” at {quality}…", "ok")

        self._pending_url = None
        self.hide_choose()
        select = self.query_one("#res", Select)
        select.set_options([])
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
        self.announce(job_list)

    def announce(self, job_list: list[dict]) -> None:
        """Report each job's outcome in the message panel, once.

        A row that turns red is easy to miss and its error is trimmed to fit,
        so every finish and failure is repeated in full here.
        """
        live = {job["id"] for job in job_list}
        for stale in [jid for jid in self._announced if jid not in live]:
            del self._announced[stale]

        for job in job_list:
            status = job["status"]
            if status not in jobs.TERMINAL or self._announced.get(job["id"]) == status:
                continue
            self._announced[job["id"]] = status
            title = job["title"]
            if status == jobs.DONE:
                self.say(f"Saved {job.get('filename') or title} to {downloader.DOWNLOAD_DIR}", "ok")
            elif status == jobs.ERROR:
                self.say(f"{title} failed — {job.get('error') or 'unknown reason'}", "error")
            else:
                self.say(f"Cancelled {title}.", "warn")

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
            self.say("Select a download with ↑/↓ first, then press c.", "warn")
            return
        job_id = self._row_ids[index]
        if registry.request_cancel(job_id):
            self.say("Cancelling…", "busy")
        else:
            self.say("That download already finished.", "warn")

    def action_clear(self) -> None:
        count = registry.clear_finished()
        self.say(f"Cleared {count} finished download{'s' if count != 1 else ''}.", "info")

    def action_open_folder(self) -> None:
        self.say(f"Saving to {downloader.DOWNLOAD_DIR}", "info")


def run() -> None:
    Url2VidApp().run()
