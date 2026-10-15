"""API tests for the web backend, with the network mocked out."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app import downloader, jobs
from app.jobs import registry
from server.main import app

# The server only answers to loopback names; TestClient's default is "testserver".
client = TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture(autouse=True)
def empty_registry():
    """The registry is a module-level singleton shared by every test."""
    with registry._lock:
        registry._jobs.clear()
    yield
    with registry._lock:
        registry._jobs.clear()


PROBE_RESULT = {
    "title": "Big Buck Bunny",
    "duration": 635,
    "extractor": "Youtube",
    "webpage_url": "https://youtube.com/watch?v=a",
    "formats": [{"height": 1080, "label": "1080p", "size_label": "245.7 MB"}],
    "note": None,
}


class TestProbe:
    def test_returns_title_and_formats(self, monkeypatch):
        monkeypatch.setattr(downloader, "probe", lambda url: dict(PROBE_RESULT))
        body = client.post("/api/probe", json={"url": "https://youtube.com/watch?v=a"}).json()
        assert body["title"] == "Big Buck Bunny"
        assert body["formats"][0]["height"] == 1080

    def test_flags_a_single_stream_as_auto(self, monkeypatch):
        """No resolutions means nothing to ask the user, so the UI just starts."""
        monkeypatch.setattr(downloader, "probe", lambda url: dict(PROBE_RESULT, formats=[]))
        body = client.post("/api/probe", json={"url": "https://x.com/a.mp4"}).json()
        assert body["auto"] is True

    def test_a_choice_is_not_auto(self, monkeypatch):
        monkeypatch.setattr(downloader, "probe", lambda url: dict(PROBE_RESULT))
        assert client.post("/api/probe", json={"url": "https://x.com/a"}).json()["auto"] is False

    def test_rejects_a_url_without_a_scheme(self):
        response = client.post("/api/probe", json={"url": "not a url"})
        assert response.status_code == 400
        assert "http://" in response.json()["detail"]

    def test_failure_returns_the_explanation_not_the_raw_error(self, monkeypatch):
        def boom(url):
            raise ValueError("ERROR: Unsupported URL: https://uqload.is/a.html")

        monkeypatch.setattr(downloader, "probe", boom)
        response = client.post("/api/probe", json={"url": "https://uqload.is/a.html"})
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "no extractor for uqload.is" in detail
        assert "Unsupported URL" not in detail

    def test_absurdly_long_urls_are_refused(self):
        assert client.post("/api/probe", json={"url": "https://x.com/" + "a" * 4000}).status_code == 422


class TestDownloadRoutes:
    def test_start_returns_a_job_id(self, monkeypatch):
        monkeypatch.setattr(
            downloader,
            "start",
            lambda url, height, title, audio=True, audio_only=False, audio_kbps=None: (
                registry.create(url, height, title, audio, audio_only, audio_kbps)
            ),
        )
        body = client.post(
            "/api/download", json={"url": "https://x.com/a", "height": 720, "title": "Clip"}
        ).json()
        assert body["id"] in {job["id"] for job in client.get("/api/jobs").json()["jobs"]}

    def test_cancel_reports_a_finished_job(self):
        job = registry.create("https://x.com/a", 720, "Clip")
        registry.update(job.id, status=jobs.DONE)
        assert client.post(f"/api/jobs/{job.id}/cancel").status_code == 409

    def test_cancel_marks_a_running_job(self):
        job = registry.create("https://x.com/a", 720, "Clip")
        registry.update(job.id, status=jobs.DOWNLOADING)
        assert client.post(f"/api/jobs/{job.id}/cancel").json() == {"ok": True}
        assert registry.get(job.id).cancel_requested

    def test_clear_removes_only_finished_jobs(self):
        done = registry.create("https://x.com/a", 720, "Done")
        registry.update(done.id, status=jobs.DONE)
        registry.create("https://x.com/b", 720, "Running")
        assert client.post("/api/jobs/clear").json() == {"cleared": 1}
        assert len(client.get("/api/jobs").json()["jobs"]) == 1


class TestFileRoute:
    def test_serves_a_finished_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(downloader, "DOWNLOAD_DIR", tmp_path)
        (tmp_path / "clip.mp4").write_bytes(b"video-bytes")
        job = registry.create("https://x.com/a", 720, "Clip")
        registry.update(job.id, status=jobs.DONE, filename="clip.mp4")

        response = client.get(f"/api/jobs/{job.id}/file")
        assert response.status_code == 200
        assert response.content == b"video-bytes"

    def test_refuses_an_unfinished_job(self):
        job = registry.create("https://x.com/a", 720, "Clip")
        registry.update(job.id, status=jobs.DOWNLOADING)
        assert client.get(f"/api/jobs/{job.id}/file").status_code == 409

    def test_unknown_job_is_404(self):
        assert client.get("/api/jobs/j404/file").status_code == 404

    def test_missing_file_is_404(self, tmp_path, monkeypatch):
        monkeypatch.setattr(downloader, "DOWNLOAD_DIR", tmp_path)
        job = registry.create("https://x.com/a", 720, "Clip")
        registry.update(job.id, status=jobs.DONE, filename="gone.mp4")
        assert client.get(f"/api/jobs/{job.id}/file").status_code == 404

    def test_cannot_escape_the_downloads_folder(self, tmp_path, monkeypatch):
        """A crafted filename must not be able to serve arbitrary files."""
        secret = tmp_path / "secret.txt"
        secret.write_bytes(b"not yours")
        served = tmp_path / "downloads"
        served.mkdir()
        monkeypatch.setattr(downloader, "DOWNLOAD_DIR", served)

        job = registry.create("https://x.com/a", 720, "Clip")
        registry.update(job.id, status=jobs.DONE, filename="../secret.txt")
        assert client.get(f"/api/jobs/{job.id}/file").status_code == 404


class TestConfig:
    def test_reports_the_folder_downloads_actually_go_to(self):
        # Not a hard-coded path: a packaged build reports the user's real
        # Downloads folder, a checkout reports whatever is configured.
        body = client.get("/api/config").json()
        assert body["download_dir"] == str(downloader.DOWNLOAD_DIR)
        assert body["max_concurrent"] >= 1


class TestRequestValidation:
    def test_rejects_a_nonsense_bitrate(self):
        body = {"url": "https://x.com/a", "audio_only": True, "audio_kbps": 5}
        assert client.post("/api/download", json=body).status_code == 422

    def test_rejects_a_negative_height(self):
        assert client.post("/api/download", json={"url": "https://x.com/a", "height": -1}).status_code == 422


class TestLocalOnly:
    def test_refuses_a_cross_site_post(self):
        """A bodiless POST needs no CORS preflight, so the Origin is the only tell."""
        job = registry.create("https://x.com/a", 720, "Clip")
        response = client.post(f"/api/jobs/{job.id}/cancel", headers={"Origin": "https://evil.example"})
        assert response.status_code == 403
        assert not registry.get(job.id).cancel_requested

    def test_refuses_a_foreign_host_header(self):
        """DNS rebinding arrives with the attacker's hostname in Host."""
        assert client.get("/api/jobs", headers={"Host": "evil.example:8000"}).status_code == 403

    def test_accepts_the_app_itself_and_the_dev_server(self):
        assert client.get("/api/jobs", headers={"Origin": "http://127.0.0.1:51234"}).status_code == 200
        assert client.get("/api/jobs", headers={"Origin": "http://localhost:5173"}).status_code == 200

    def test_accepts_localhost(self):
        local = TestClient(app, base_url="http://localhost:8000")
        assert local.get("/api/jobs").status_code == 200
