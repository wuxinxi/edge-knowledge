"""Download integrity and interruption recovery without accessing the network."""

import hashlib
import importlib.util
import json
from io import BytesIO
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "model_download", Path(__file__).resolve().parents[2] / "scripts/download_model.py"
)
model_download = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model_download)


class Response(BytesIO):
    def __init__(self, content, status=200, headers=None):
        super().__init__(content)
        self.status, self.headers = status, headers or {}


def item(content):
    return {
        "type": "file",
        "path": "config.json",
        "size": len(content),
        "oid": "unused",
        "lfs": {"oid": hashlib.sha256(content).hexdigest()},
    }


def test_complete_partial_recovers_without_redownloading(tmp_path, monkeypatch):
    content = b"verified snapshot data"
    (tmp_path / "config.json.part").write_bytes(content)

    def metadata_only(request, timeout):
        assert "/tree/" in request
        return Response(json.dumps([item(content)]).encode())

    monkeypatch.setattr(model_download.urllib.request, "urlopen", metadata_only)
    model_download.download(tmp_path)
    assert (tmp_path / "config.json").read_bytes() == content
    assert json.loads((tmp_path / "edge-model.json").read_text())["model"] == model_download.MODEL


def test_corruption_never_marks_model_ready(tmp_path, monkeypatch):
    def corrupt(request, timeout):
        return Response(
            json.dumps([item(b"correct")]).encode() if isinstance(request, str) else b"damaged"
        )

    monkeypatch.setattr(model_download.urllib.request, "urlopen", corrupt)
    with pytest.raises(ValueError, match="Integrity check failed"):
        model_download.download(tmp_path)
    assert not (tmp_path / "edge-model.json").exists()
    assert not (tmp_path / "config.json").exists()


def test_manifest_cannot_escape_model_directory(tmp_path, monkeypatch):
    entry = {**item(b"data"), "path": "../escaped"}
    monkeypatch.setattr(
        model_download.urllib.request,
        "urlopen",
        lambda *a, **k: Response(json.dumps([entry]).encode()),
    )
    with pytest.raises(ValueError, match="Invalid model file path"):
        model_download.download(tmp_path)
    assert not (tmp_path.parent / "escaped").exists()


def test_range_response_must_match_requested_offset(tmp_path, monkeypatch):
    monkeypatch.setattr(model_download.time, "sleep", lambda *a: None)
    monkeypatch.setattr(
        model_download.urllib.request,
        "urlopen",
        lambda *a, **k: Response(b"wrong", 206, {"Content-Range": "bytes 1-5/5"}),
    )
    partial = tmp_path / "weights.part"
    with pytest.raises(ValueError, match="unexpected model range"):
        model_download.download_ranges("https://example.invalid/model", partial, 5)
    assert not partial.exists()
