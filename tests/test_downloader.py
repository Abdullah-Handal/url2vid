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


class TestExplainError:
    """Every branch names the site and says whose problem it is."""

    def test_unsupported_url_explains_itself(self):
        """The bare yt-dlp text reads like a bug in this app; it isn't."""
        out = downloader.explain_error(
            "ERROR: Unsupported URL: https://uqload.is/abc.html",
            "https://uqload.is/abc.html",
        )
        assert "no extractor for uqload.is" in out
        assert "JavaScript" in out
        assert "Unsupported URL" not in out

    def test_dns_failure_is_not_reported_as_a_missing_video(self):
        out = downloader.explain_error(
            "ERROR: [generic] v: Unable to download webpage: [Errno -2] "
            "Name or service not known (caused by TransportError('x'))",
            "https://nope.invalid/v.mp4",
        )
        assert "does not resolve" in out and "nope.invalid" in out

    def test_404_names_the_site(self):
        out = downloader.explain_error(
            "ERROR: [generic] x: Unable to download webpage: HTTP Error 404: Not Found",
            "https://www.example.com/x",
        )
        assert "example.com returned 404" in out

    def test_403_suggests_the_likely_cause(self):
        out = downloader.explain_error("ERROR: HTTP Error 403: Forbidden", "https://a.tv/x")
        assert "403" in out and "expired" in out

    def test_login_walled_video_says_so(self):
        out = downloader.explain_error(
            "ERROR: [youtube] a: Private video. Sign in if you have been granted access.",
            "https://youtube.com/watch?v=a",
        )
        assert "needs an account" in out

    def test_geo_block_is_distinguished_from_a_missing_video(self):
        out = downloader.explain_error(
            "ERROR: [x] a: The uploader has not made this video available in your country",
            "https://x.com/a",
        )
        assert "region" in out

    def test_removed_video_quotes_the_site(self):
        out = downloader.explain_error("ERROR: [yt] a: Video unavailable", "https://yt.com/a")
        assert "gone" in out and "Video unavailable" in out

    def test_drm_is_called_out(self):
        assert "DRM" in downloader.explain_error("ERROR: This video is DRM protected", "https://a.tv/x")

    def test_unrecognised_errors_pass_through_untouched(self):
        """Flattening an unknown failure into a vague catch-all loses the only
        clue there is."""
        out = downloader.explain_error("ERROR: ffmpeg exited with code 234", "https://a.tv/x")
        assert out == "ffmpeg exited with code 234"

    def test_extractor_prefix_and_caused_by_tail_are_dropped(self):
        out = downloader.explain_error(
            "ERROR: [generic] clip42: something odd (caused by TransportError('boom'))",
            "https://a.tv/x",
        )
        assert out == "something odd"

    def test_missing_url_still_produces_a_sentence(self):
        out = downloader.explain_error("ERROR: Unsupported URL: x", "")
        assert "that site" in out


class TestHost:
    def test_strips_www_and_port(self):
        assert downloader._host("https://www.example.com:8443/a") == "example.com"

    def test_empty_for_a_bare_string(self):
        assert downloader._host("not a url") == ""


class TestModeMarker:
    """The marker is what stops one mode's file being handed back for another.

    ``overwrites`` is off, so two jobs that resolve to the same filename make
    yt-dlp reuse whatever is already on disk.
    """

    def test_each_mode_gets_a_distinct_marker(self):
        markers = {
            downloader.mode_marker(144, True, False),
            downloader.mode_marker(144, False, False),
            downloader.mode_marker(None, True, True),
            downloader.mode_marker(1080, True, False),
            downloader.mode_marker(None, True, False),
        }
        assert len(markers) == 5

    def test_audio_only_marker_ignores_height(self):
        assert downloader.mode_marker(1080, True, True) == "audio"

    def test_marker_lands_in_the_filename(self):
        template = downloader._output_template({"id": "abc123", "title": "Clip"}, "144p silent")
        assert "[144p silent]" in template
        assert template.endswith(".%(ext)s")

    def test_no_marker_leaves_the_name_clean(self):
        assert "[]" not in downloader._output_template({"id": "abc123", "title": "Clip"})
