"""yt-dlp self-update, with PyPI mocked out."""

import hashlib
import io
import json
import zipfile

import pytest

from app import paths, updater


def _wheel() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("yt_dlp/__init__.py", "")
        archive.writestr("../escape.py", "")
    return buffer.getvalue()


@pytest.fixture
def pypi(monkeypatch, tmp_path):
    """Serve a fake PyPI index and wheel; returns the dict to tamper with."""
    wheel = _wheel()
    state = {"wheel": wheel, "sha256": hashlib.sha256(wheel).hexdigest()}

    def urlopen(url, timeout):
        if url == updater.PYPI:
            index = {
                "info": {"version": "2099.1.1"},
                "releases": {
                    "2099.1.1": [
                        {
                            "packagetype": "bdist_wheel",
                            "filename": "yt_dlp-2099.1.1-py3-none-any.whl",
                            "url": "https://files.example/yt_dlp.whl",
                            "digests": {"sha256": state["sha256"]},
                        }
                    ]
                },
            }
            return io.BytesIO(json.dumps(index).encode())
        return io.BytesIO(state["wheel"])

    monkeypatch.setattr(updater.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(paths, "deps_dir", lambda: tmp_path / "deps")
    return state


def test_installs_a_verified_wheel(pypi, tmp_path):
    assert updater.update()["updated"] is True
    assert (tmp_path / "deps" / "yt_dlp" / "__init__.py").is_file()
    assert not (tmp_path / "escape.py").exists()


def test_refuses_a_wheel_that_does_not_match_its_checksum(pypi, tmp_path):
    pypi["wheel"] = pypi["wheel"] + b"tampered"
    with pytest.raises(RuntimeError, match="checksum"):
        updater.update()
    assert not (tmp_path / "deps").exists()
