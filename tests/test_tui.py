"""Headless smoke tests for the dashboard, driven by Textual's test pilot."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import jobs
from app.jobs import registry
from app.tui import Url2VidApp, render_bar, render_row
from textual.widgets import Input, ListView, Select, Static


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
        from rich.text import Text
        from app.tui import HEADINGS
        row = Text.from_markup(render_row(_job())).plain
        assert len(row) <= 100, f"row is {len(row)} cols"
        assert len(HEADINGS) == len(row), "header and rows must align"


def _job(**overrides):
    base = {
        "id": "j1", "title": "Clip", "height": 720, "status": jobs.DOWNLOADING,
        "percent": 50.0, "eta_label": "1m 00s", "speed_label": "1.0 MB/s",
        "downloaded_label": "5.0 MB", "size_label": "10.0 MB", "error": None,
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
            assert "http" in str(pilot.app.query_one("#status", Static).content)

    async def test_resolution_select_starts_disabled(self):
        async with Url2VidApp().run_test() as pilot:
            assert pilot.app.query_one("#res", Select).disabled

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
