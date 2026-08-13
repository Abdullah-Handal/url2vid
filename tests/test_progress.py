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

    def test_labels_are_snapped_but_heights_stay_real(self):
        # The label is cosmetic; the height is what the format selector
        # filters on. Snapping the height itself means "height<=240" fails to
        # match the 256p stream shown as 240p, and the request escalates to
        # the best available instead.
        formats = [
            {"height": 1082, "vcodec": "avc1", "filesize": 10},
            {"height": 638, "vcodec": "avc1", "filesize": 10},
        ]
        result = progress.dedupe_heights(formats)
        assert [f["label"] for f in result] == ["1080p", "720p"]
        assert [f["height"] for f in result] == [1082, 638]

    def test_a_selection_matches_the_format_it_came_from(self):
        formats = [{"height": 256, "vcodec": "avc1", "filesize": 10}]
        entry = progress.dedupe_heights(formats)[0]
        assert entry["label"] == "240p"
        assert 256 <= entry["height"]  # "height<=" must still include it

    def test_size_includes_the_audio_that_gets_merged_in(self):
        # A video-only stream's own size is not what ends up on disk.
        formats = [
            {"height": 240, "vcodec": "av01", "acodec": "none", "filesize": 1_000_000},
            {"height": None, "vcodec": "none", "acodec": "mp4a", "filesize": 3_000_000},
        ]
        assert progress.dedupe_heights(formats)[0]["size_label"] == "3.8 MB"

    def test_empty_list(self):
        assert progress.dedupe_heights([]) == []


class TestFormatSelector:
    def test_capped_height(self):
        assert "height<=720" in progress.format_selector(720)

    def test_best_when_none(self):
        assert progress.format_selector(None) == "bestvideo*+bestaudio/best"

    def test_always_has_muxed_fallback(self):
        # Sites serving one pre-muxed stream have nothing to merge.
        assert progress.format_selector(1080).endswith("/worst")

    def test_fallback_never_escalates_above_the_request(self):
        # When nothing is small enough the tail decides what arrives. Asking
        # for the smallest rendition and receiving the largest is the bug this
        # guards: the old tail ended "bestvideo*+bestaudio/best".
        selector = progress.format_selector(240)
        assert "bestvideo*" not in selector
        assert selector.endswith("worstvideo*+bestaudio/worst")


class TestAudioModes:
    def test_audio_only_ignores_resolution(self):
        assert progress.format_selector(1080, audio_only=True) == "bestaudio/best"

    def test_silent_video_asks_for_no_audio_stream(self):
        selector = progress.format_selector(720, audio=False)
        assert "bestaudio" not in selector
        assert "height<=720" in selector

    def test_normal_download_still_merges_video_and_audio(self):
        assert "+bestaudio" in progress.format_selector(1080)


class TestMp3Estimate:
    def test_scales_with_duration(self):
        # 600 s at 192 kbps -> 600 * 192000 / 8 bytes
        assert progress.mp3_estimate(600) == 14_400_000

    def test_unknown_duration_gives_no_number(self):
        assert progress.mp3_estimate(None) is None
        assert progress.mp3_estimate(0) is None

    def test_is_not_the_source_stream_size(self):
        # The point of the estimate: a 30 MB Opus stream becomes a much
        # smaller MP3, so showing the source size would mislead.
        assert progress.mp3_estimate(600) < 30_000_000


class TestAudioOptions:
    def test_offers_bitrates_best_first(self):
        options = progress.audio_options(600)
        assert [o["kbps"] for o in options] == list(progress.AUDIO_BITRATES)
        assert options[0]["kbps"] > options[-1]["kbps"]

    def test_size_falls_with_bitrate(self):
        options = progress.audio_options(600)
        sizes = [progress.mp3_estimate(600, o["kbps"]) for o in options]
        assert sizes == sorted(sizes, reverse=True)

    def test_unknown_duration_still_offers_the_choices(self):
        # No duration means no size to show, but the bitrates remain pickable.
        options = progress.audio_options(None)
        assert len(options) == len(progress.AUDIO_BITRATES)
        assert all(o["size_label"] == "" for o in options)
