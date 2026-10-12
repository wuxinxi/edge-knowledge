import json

import pytest

from edge_knowledge.domain.models import AppError
from edge_knowledge.infrastructure.embedding import SentenceTransformerEmbedder


def snapshot(path, model="google/embeddinggemma-2"):
    path.mkdir()
    for name in ["model.safetensors", "tokenizer.json", "modules.json", "config.json"]:
        (path / name).write_text("fixture")
    (path / "edge-model.json").write_text(json.dumps({"model": model}))


def test_missing_model_fails_before_loading_or_network(tmp_path, monkeypatch):
    monkeypatch.setattr("huggingface_hub.constants.HF_HUB_CACHE", str(tmp_path / "cache"))
    embedder = SentenceTransformerEmbedder("google/embeddinggemma-2", False)
    with pytest.raises(AppError) as failure:
        embedder.query("测试")
    assert failure.value.status == 503 and failure.value.code == "model_not_ready"
    assert not embedder.loaded


def test_prepared_model_can_be_discovered_without_restart(tmp_path, monkeypatch):
    monkeypatch.setattr("huggingface_hub.constants.HF_HUB_CACHE", str(tmp_path / "cache"))
    path = tmp_path / "prepared"
    embedder = SentenceTransformerEmbedder("google/embeddinggemma-2", True, prepared_path=path)
    assert not embedder.ready
    snapshot(path)
    assert embedder.ready and embedder._local_source() == path
    (path / "tokenizer.json").unlink()
    assert not embedder.ready


def test_prepared_marker_cannot_select_another_model(tmp_path, monkeypatch):
    monkeypatch.setattr("huggingface_hub.constants.HF_HUB_CACHE", str(tmp_path / "cache"))
    path = tmp_path / "prepared"
    snapshot(path)
    embedder = SentenceTransformerEmbedder("other/model", True, prepared_path=path)
    assert not embedder.ready
    (path / "edge-model.json").write_text("{")
    assert not embedder.ready


def test_readiness_requires_embedding_runtime(tmp_path, monkeypatch):
    path = tmp_path / "prepared"
    snapshot(path)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    embedder = SentenceTransformerEmbedder("google/embeddinggemma-2", True, model_path=path)
    assert not embedder.ready
