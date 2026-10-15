"""One-shot mode output, with the network mocked out."""

import io

from rich.console import Console

from app import cli, downloader, jobs
from app.jobs import registry


def test_saved_filename_is_printed_verbatim(monkeypatch, tmp_path):
    """Saved names carry "[id] [1080p]" tags; Rich must not eat them as markup."""
    name = "Clip [abc123] [audio 192k] [/].mp3"
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        downloader, "probe", lambda url: {"title": "Clip", "extractor": "Generic", "formats": []}
    )

    def finished(url, height, title):
        job = registry.create(url, height, title)
        registry.update(job.id, status=jobs.DONE, filename=name)
        return job

    monkeypatch.setattr(downloader, "start", finished)
    out = io.StringIO()
    monkeypatch.setattr(cli, "console", Console(file=out, width=200))

    assert cli.download_once("https://x.com/a.mp4", None) == 0
    assert name in out.getvalue()
