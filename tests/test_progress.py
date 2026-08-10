"""Tests for the pure progress/format arithmetic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import progress


class TestPercent:
    def test_basic(self):
        assert progress.percent(50, 200) == 25.0

    def test_unknown_total_is_none(self):
        assert progress.percent(50, None) is None
        assert progress.percent(50, 0) is None

    def test_clamped_to_100(self):
        # yt-dlp occasionally reports slightly more bytes than the estimate.
        assert progress.percent(220, 200) == 100.0


class TestEta:
    def test_remaining_over_speed(self):
        assert progress.eta_seconds(50, 200, 10) == 15

    def test_none_without_speed_or_total(self):
        assert progress.eta_seconds(50, 200, 0) is None
        assert progress.eta_seconds(50, None, 10) is None

    def test_zero_when_complete(self):
        assert progress.eta_seconds(200, 200, 10) == 0


class TestSmoothSpeed:
    def test_first_sample_passes_through(self):
        assert progress.smooth_speed(None, 100) == 100

    def test_smooths_toward_new_sample(self):
        # A 10x spike must not yank the average all the way up.
        result = progress.smooth_speed(100, 1000)
        assert 100 < result < 1000

    def test_ignores_missing_samples(self):
        assert progress.smooth_speed(100, None) == 100
        assert progress.smooth_speed(100, 0) == 100


class TestFormatting:
    def test_eta_labels(self):
        assert progress.format_eta(45) == "45s"
        assert progress.format_eta(131) == "2m 11s"
        assert progress.format_eta(3900) == "1h 05m"
        assert progress.format_eta(None) == ""

    def test_byte_labels(self):
        assert progress.format_bytes(512) == "512 B"
        assert progress.format_bytes(1536) == "1.5 KB"
        assert progress.format_bytes(5 * 1024 * 1024) == "5.0 MB"
        assert progress.format_bytes(None) == ""


class TestDedupeHeights:
    def test_collapses_duplicate_heights_keeping_largest_size(self):
        formats = [
            {"height": 1080, "vcodec": "avc1", "filesize": 100},
            {"height": 1080, "vcodec": "vp9", "filesize": 300},
            {"height": 720, "vcodec": "avc1", "filesize": 50},
        ]
        result = progress.dedupe_heights(formats)
        assert [f["height"] for f in result] == [1080, 720]
        assert result[0]["size_label"] == "300 B"

    def test_skips_audio_only(self):
        formats = [
            {"height": None, "vcodec": "none", "filesize": 10},
            {"height": 720, "vcodec": "avc1", "filesize": 50},
        ]
        assert [f["height"] for f in progress.dedupe_heights(formats)] == [720]

    def test_snaps_odd_heights_to_standard_rungs(self):
        formats = [
            {"height": 1082, "vcodec": "avc1", "filesize": 10},
            {"height": 638, "vcodec": "avc1", "filesize": 10},
        ]
        assert [f["height"] for f in progress.dedupe_heights(formats)] == [1080, 720]

    def test_empty_list(self):
        assert progress.dedupe_heights([]) == []


class TestFormatSelector:
    def test_capped_height(self):
        assert "height<=720" in progress.format_selector(720)

    def test_best_when_none(self):
        assert progress.format_selector(None) == "bestvideo*+bestaudio/best"

    def test_always_has_muxed_fallback(self):
        # Sites serving one pre-muxed stream have nothing to merge.
        assert progress.format_selector(1080).endswith("/best")
