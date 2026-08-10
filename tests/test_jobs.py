"""Tests for job state, especially progress across merged streams."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import jobs
from app.jobs import Job, JobRegistry


class TestJobDict:
    def test_percent_spans_two_streams_without_resetting(self):
        """The bug this guards: a merged download fetches video then audio as
        separate files, so a per-file percentage would drop back to ~0 midway."""
        job = Job(id="j1", url="u", total_bytes=1000)

        job.downloaded_bytes = 600  # video stream, 60% of the whole job
        assert job.as_dict()["percent"] == 60.0

        # Video finishes, audio starts from zero bytes of its own.
        job.completed_bytes = 600
        job.downloaded_bytes = 0
        assert job.as_dict()["percent"] == 60.0  # not 0.0

        job.downloaded_bytes = 200
        assert job.as_dict()["percent"] == 80.0

    def test_unknown_total_yields_null_percent(self):
        job = Job(id="j1", url="u", total_bytes=None, downloaded_bytes=500)
        assert job.as_dict()["percent"] is None

    def test_done_is_always_100(self):
        job = Job(id="j1", url="u", status=jobs.DONE, total_bytes=None)
        assert job.as_dict()["percent"] == 100.0

    def test_merging_shows_100_when_size_unknown(self):
        job = Job(id="j1", url="u", status=jobs.MERGING, total_bytes=None)
        assert job.as_dict()["percent"] == 100.0

    def test_eta_only_while_downloading(self):
        job = Job(id="j1", url="u", status=jobs.DOWNLOADING, eta=131)
        assert job.as_dict()["eta_label"] == "2m 11s"
        job.status = jobs.MERGING
        assert job.as_dict()["eta_label"] == ""


class TestRegistry:
    def test_create_and_snapshot(self):
        reg = JobRegistry()
        reg.create("http://a", 720, "A")
        reg.create("http://b", None, "B")
        _, snap = reg.snapshot()
        assert {j["title"] for j in snap} == {"A", "B"}

    def test_revision_advances_on_change(self):
        reg = JobRegistry()
        job = reg.create("http://a", 720, "A")
        rev1, _ = reg.snapshot()
        reg.update(job.id, downloaded_bytes=10)
        rev2, _ = reg.snapshot()
        assert rev2 > rev1

    def test_revision_static_without_change(self):
        # This is what stops the TUI redrawing rows that did not move.
        reg = JobRegistry()
        reg.create("http://a", 720, "A")
        assert reg.snapshot()[0] == reg.snapshot()[0]

    def test_update_unknown_job_is_a_noop(self):
        reg = JobRegistry()
        reg.update("nope", downloaded_bytes=5)  # must not raise

    def test_cancel_marks_flag_and_refuses_finished_jobs(self):
        reg = JobRegistry()
        job = reg.create("http://a", 720, "A")
        assert reg.request_cancel(job.id) is True
        assert reg.get(job.id).cancel_requested is True

        reg.update(job.id, status=jobs.DONE)
        assert reg.request_cancel(job.id) is False

    def test_clear_removes_only_terminal_jobs(self):
        reg = JobRegistry()
        running = reg.create("http://a", 720, "A")
        finished = reg.create("http://b", 720, "B")
        reg.update(finished.id, status=jobs.DONE)

        assert reg.clear_finished() == 1
        _, snap = reg.snapshot()
        assert [j["id"] for j in snap] == [running.id]
