"""Tests for downloader helpers that don't touch the network."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import downloader


class TestOutputTemplate:
    def test_includes_id_when_it_adds_information(self):
        template = downloader._output_template({"id": "aqz-KE-bpKQ", "title": "Big Buck Bunny"})
        assert "%(id)" in template

    def test_omits_id_when_already_in_title(self):
        """The generic extractor derives the id from the title, which would
        otherwise yield 'Clip [Clip].mp4'."""
        template = downloader._output_template(
            {"id": "Big_Buck_Bunny_360_10s_1MB", "title": "Big_Buck_Bunny_360_10s_1MB"}
        )
        assert "%(id)" not in template

    def test_omits_id_on_case_insensitive_match(self):
        template = downloader._output_template({"id": "myclip", "title": "MyClip"})
        assert "%(id)" not in template

    def test_handles_missing_fields(self):
        assert "%(title)" in downloader._output_template({})


class TestStreamEstimates:
    def test_lists_video_and_audio_streams(self):
        info = {"requested_formats": [{"filesize": 1000}, {"filesize": 250}]}
        assert downloader._stream_estimates(info) == [1000, 250]

    def test_falls_back_to_approx_size(self):
        assert downloader._stream_estimates({"requested_formats": [{"filesize_approx": 900}]}) == [900]

    def test_single_muxed_stream(self):
        assert downloader._stream_estimates({"filesize": 500}) == [500]


class TestTotalFromEstimates:
    def test_sums_known_streams(self):
        assert downloader.total_from_estimates([1000, 250]) == 1250

    def test_none_when_any_stream_size_unknown(self):
        # A partial sum would make the percentage lie, so refuse to guess.
        assert downloader.total_from_estimates([1000, None]) is None

    def test_none_on_empty(self):
        assert downloader.total_from_estimates([]) is None

    def test_refined_totals_replace_estimates(self):
        """Estimates overshoot; swapping in real sizes is what lets the bar
        actually reach 100% instead of stalling in the high eighties."""
        estimates = [30_000_000, 2_862_898]
        assert downloader.total_from_estimates(estimates) == 32_862_898
        estimates[0] = 26_500_000  # real size, known once the stream finishes
        assert downloader.total_from_estimates(estimates) == 29_362_898


class TestCleanError:
    def test_strips_prefix_and_ansi(self):
        assert downloader.clean_error("\x1b[0;31mERROR: \x1b[0mUnsupported URL") == "Unsupported URL"

    def test_truncates_long_messages(self):
        assert len(downloader.clean_error("x" * 900)) == 400

    def test_empty_message_gets_a_fallback(self):
        assert downloader.clean_error("") != ""
