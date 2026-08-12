"""Headless smoke tests for the dashboard, driven by Textual's test pilot."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import jobs
from app.jobs import registry
from app.tui import (
    LIST_INDENT,
    Url2VidApp,
    describe_found,
    is_direct_media,
    render_bar,
    render_row,
)
from textual.widgets import Button, Input, ListView, Select, Static


class TestRendering:
    def test_bar_fills_proportionally(self):
        from app.tui import BAR_WIDTH
        assert render_bar(50.0, "cyan").count("█") == BAR_WIDTH // 2
        assert render_bar(100.0, "cyan").count("░") == 0
        assert render_bar(0.0, "cyan").count("█") == 0

    def test_bar_shows_placeholder_when_percent_unknown(self):
        assert "╌" in render_bar(None, "cyan")

    def test_row_escapes_markup_in_titles(self):
        """A title containing brackets must not be parsed as Rich markup."""
        job = _job(title="Video [bold]not markup[/]")
        assert "\\[bold]" in render_row(job)

    def test_row_shows_error_text_when_failed(self):
        job = _job(status=jobs.ERROR, error="Unsupported URL")
        assert "Unsupported URL" in render_row(job)

    def test_error_rows_match_the_table_width(self):
        """A long error must not push the row past the table and get clipped."""
        from rich.text import Text
        from app.tui import ROW_WIDTH
        row = Text.from_markup(
            render_row(_job(status=jobs.ERROR, error="x " * 200))
        ).plain
        assert len(row) == ROW_WIDTH, f"error row is {len(row)}, table is {ROW_WIDTH}"

    def test_row_truncates_long_titles(self):
        row = render_row(_job(title="x" * 200))
        assert "…" in row

    def test_rows_share_one_width_across_statuses(self):
        """Ragged columns look broken; every non-error row must line up."""
        from rich.text import Text
        from app import jobs as j
        widths = {
            len(Text.from_markup(render_row(_job(status=s, percent=p))).plain)
            for s, p in [
                (j.DOWNLOADING, 50.0), (j.MERGING, 100.0),
                (j.DONE, 100.0), (j.QUEUED, None),
            ]
        }
        assert len(widths) == 1, f"row widths differ: {widths}"

    def test_row_fits_a_100_column_terminal(self):
        """Rows sit inside a list that indents them, so 100 is not the budget."""
        from rich.text import Text
        from app.tui import HEADINGS
        row = Text.from_markup(render_row(_job())).plain
        assert len(row) <= 100 - 2 * LIST_INDENT, f"row is {len(row)} cols"
        assert len(HEADINGS) == len(row), "header and rows must align"


def _job(**overrides):
    base = {
        "id": "j1", "title": "Clip", "height": 720, "status": jobs.DOWNLOADING,
        "percent": 50.0, "eta_label": "1m 00s", "speed_label": "1.0 MB/s",
        "downloaded_label": "5.0 MB", "size_label": "10.0 MB", "error": None,
    }
    return base | overrides


def _message(pilot) -> str:
    """Plain text currently shown in the message panel under the input."""
    from rich.text import Text
    return Text.from_markup(str(pilot.app.query_one("#message", Static).content)).plain


def _found(pilot) -> str:
    from rich.text import Text
    return Text.from_markup(str(pilot.app.query_one("#found", Static).content)).plain


def _info(**overrides) -> dict:
    base = {
        "title": "Big Buck Bunny", "duration": 634, "extractor": "Youtube",
        "webpage_url": "http://example.com/v", "note": None,
        "formats": [
            {"height": 1080, "label": "1080p", "size_label": "50.0 MB"},
            {"height": 720, "label": "720p", "size_label": "20.0 MB"},
        ],
    }
    return base | overrides


@pytest.fixture(autouse=True)
def empty_registry():
    """The registry is a module-level singleton shared by every test."""
    with registry._lock:
        registry._jobs.clear()
    yield
    with registry._lock:
        registry._jobs.clear()


@pytest.mark.asyncio
class TestApp:
    async def test_app_starts_with_url_focused(self):
        async with Url2VidApp().run_test() as pilot:
            assert isinstance(pilot.app.focused, Input)

    async def test_rejects_non_http_input(self):
        async with Url2VidApp().run_test() as pilot:
            pilot.app.query_one("#url", Input).value = "not a url"
            await pilot.press("enter")
            await pilot.pause()
            assert "http" in _message(pilot)

    async def test_empty_input_says_so_instead_of_doing_nothing(self):
        """Silence on a no-op is the exact complaint this guards against."""
        async with Url2VidApp().run_test() as pilot:
            await pilot.click("#fetch")
            await pilot.pause()
            assert "paste" in _message(pilot).lower()

    async def test_fetch_button_runs_the_same_path_as_enter(self):
        async with Url2VidApp().run_test() as pilot:
            pilot.app.query_one("#url", Input).value = "ftp://nope"
            await pilot.click("#fetch")
            await pilot.pause()
            assert "http" in _message(pilot)

    async def test_resolution_row_is_hidden_until_a_video_is_found(self):
        async with Url2VidApp().run_test() as pilot:
            assert pilot.app.query_one("#choose").styles.display == "none"
            assert pilot.app.query_one("#found").styles.display == "none"

    async def test_jobs_appear_as_rows(self):
        async with Url2VidApp().run_test() as pilot:
            job = registry.create("http://example.com/v", 720, "Test Clip")
            await pilot.pause(0.4)
            row = pilot.app.query_one(f"#row-{job.id}", Static)
            assert "Test Clip" in str(row.content)

    async def test_clear_action_removes_finished_rows(self):
        async with Url2VidApp().run_test() as pilot:
            job = registry.create("http://example.com/v", 720, "Done Clip")
            registry.update(job.id, status=jobs.DONE)
            await pilot.pause(0.4)
            await pilot.press("f4")
            await pilot.pause(0.4)
            assert registry.snapshot()[1] == []

    async def test_plain_letter_keys_are_typed_not_swallowed_as_actions(self):
        """The URL box owns plain letters; only function keys act while it has
        focus. Ctrl chords are unusable here — Input binds ctrl+x to cut."""
        async with Url2VidApp().run_test() as pilot:
            job = registry.create("http://example.com/v", 720, "Done Clip")
            registry.update(job.id, status=jobs.DONE)
            await pilot.press("x")
            await pilot.pause(0.2)
            assert pilot.app.query_one("#url", Input).value == "x"
            assert registry.snapshot()[1] != []

    async def test_escape_moves_focus_to_the_list(self):
        async with Url2VidApp().run_test() as pilot:
            registry.create("http://example.com/v", 720, "Clip")
            await pilot.pause(0.4)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(pilot.app.focused, ListView)


class TestDirectLinks:
    def test_media_extensions_are_recognised(self):
        assert is_direct_media("https://x.com/a/clip.mp4")
        assert is_direct_media("https://x.com/a/CLIP.MKV")
        assert is_direct_media("https://cdn.x.com/v.m3u8")

    def test_query_string_does_not_hide_the_extension(self):
        """Signed download links carry tokens after the path."""
        assert is_direct_media("https://cdn.x.com/v.mp4?token=abc&expires=1")

    def test_ordinary_pages_are_not_direct(self):
        assert not is_direct_media("https://youtube.com/watch?v=abc")
        assert not is_direct_media("https://example.com/")


class TestDescribeFound:
    def test_summarises_source_duration_and_choices(self):
        text = describe_found(_info())
        assert "Youtube" in text and "10:34" in text and "2 resolutions" in text

    def test_says_single_stream_when_there_is_no_choice(self):
        assert "single stream" in describe_found(_info(formats=[]))

    def test_playlist_note_is_carried_through(self):
        note = "Link is a playlist (9 items)"
        assert note in describe_found(_info(note=note))


@pytest.mark.asyncio
class TestFoundAndFeedback:
    async def test_found_video_title_is_displayed(self):
        async with Url2VidApp().run_test() as pilot:
            pilot.app.show_formats("http://example.com/v", _info())
            await pilot.pause()
            assert "Big Buck Bunny" in _found(pilot)
            assert pilot.app.query_one("#found").styles.display == "block"

    async def test_resolutions_are_offered_when_there_is_a_choice(self, monkeypatch):
        started = []
        monkeypatch.setattr("app.tui.downloader.start", lambda *a: started.append(a))
        async with Url2VidApp().run_test() as pilot:
            pilot.app.show_formats("http://example.com/v", _info())
            await pilot.pause()
            assert pilot.app.query_one("#choose").styles.display == "block"
            assert started == [], "must wait for the Download button"

    async def test_direct_link_downloads_without_asking(self, monkeypatch):
        """A .mp4 link has nothing to choose, so it must start on its own."""
        started = []
        monkeypatch.setattr("app.tui.downloader.start", lambda *a: started.append(a))
        async with Url2VidApp().run_test() as pilot:
            pilot.app.show_formats("http://example.com/clip.mp4", _info(formats=[]))
            await pilot.pause()
            assert started == [("http://example.com/clip.mp4", None, "Big Buck Bunny")]
            assert "Downloading" in _message(pilot)

    async def test_download_button_uses_the_selected_height(self, monkeypatch):
        started = []
        monkeypatch.setattr("app.tui.downloader.start", lambda *a: started.append(a))
        async with Url2VidApp().run_test() as pilot:
            pilot.app.show_formats("http://example.com/v", _info())
            await pilot.pause()
            pilot.app.query_one("#res", Select).value = "720"
            await pilot.click("#go")
            await pilot.pause()
            assert started == [("http://example.com/v", 720, "Big Buck Bunny")]

    async def test_probe_failure_reports_the_reason(self):
        async with Url2VidApp().run_test() as pilot:
            pilot.app.probe_failed("Unsupported URL: http://example.com")
            await pilot.pause()
            text = _message(pilot)
            assert "No video found" in text and "Unsupported URL" in text
            assert not pilot.app.query_one("#fetch", Button).disabled

    async def test_failed_download_is_announced_in_full(self):
        """The row trims the error to fit; the panel must show all of it."""
        async with Url2VidApp().run_test() as pilot:
            job = registry.create("http://example.com/v", 720, "Bad Clip")
            registry.update(job.id, status=jobs.ERROR, error="server said 403 Forbidden")
            await pilot.pause(0.4)
            text = _message(pilot)
            assert "Bad Clip" in text and "403 Forbidden" in text

    async def test_finished_download_is_announced_once(self):
        async with Url2VidApp().run_test() as pilot:
            job = registry.create("http://example.com/v", 720, "Good Clip")
            registry.update(job.id, status=jobs.DONE, filename="Good Clip.mp4")
            await pilot.pause(0.4)
            assert "Good Clip.mp4" in _message(pilot)
            pilot.app.say("quiet", "info")
            await pilot.pause(0.4)
            assert _message(pilot).endswith("quiet"), "announced twice"

    async def test_title_stays_on_screen_while_downloading(self, monkeypatch):
        """Hiding the title the instant a download starts wastes the answer."""
        monkeypatch.setattr("app.tui.downloader.start", lambda *a: None)
        async with Url2VidApp().run_test() as pilot:
            pilot.app.show_formats("http://example.com/clip.mp4", _info(formats=[]))
            await pilot.pause()
            assert pilot.app.query_one("#found").styles.display == "block"
            assert pilot.app.query_one("#choose").styles.display == "none"

    async def test_a_new_fetch_clears_the_previous_result(self, monkeypatch):
        monkeypatch.setattr("app.tui.downloader.start", lambda *a: None)
        # Keep the second fetch off the network. It fails, so a stale title
        # left on screen would be actively misleading.
        def boom(url):
            raise ValueError("nope")
        monkeypatch.setattr("app.tui.downloader.probe", boom)
        async with Url2VidApp().run_test() as pilot:
            pilot.app.show_formats("http://example.com/clip.mp4", _info(formats=[]))
            await pilot.pause()
            pilot.app.query_one("#url", Input).value = "https://example.com/other"
            await pilot.click("#fetch")
            await pilot.pause(0.3)
            assert pilot.app.query_one("#found").styles.display == "none"
            assert "nope" in _message(pilot)
