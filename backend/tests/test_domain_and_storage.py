import ast
from pathlib import Path

import pytest

from edge_knowledge.domain.chunking import split_document
from edge_knowledge.domain.models import AppError
from edge_knowledge.infrastructure.chroma import ChromaKnowledgeRepository
from edge_knowledge.infrastructure.settings import JsonSettingsStore


def test_chunking_preserves_sections_and_no_tail_loss():
    text = "# 第一节\n" + "一" * 130 + "\n# 第二节\n" + "二" * 150 + "结尾"
    chunks = split_document(text, 100, 20)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert set(chunk.section for chunk in chunks) == {"第一节", "第二节"}
    assert chunks[-1].text.endswith("结尾")
    assert all(len(chunk.text) <= 100 for chunk in chunks)
    assert "".join(chunk.text for chunk in chunks).count("一") >= 130
    assert "".join(chunk.text for chunk in chunks).count("二") >= 150


@pytest.mark.parametrize("size, overlap", [(50, 0), (100, 100), (100, -1)])
def test_invalid_chunking_parameters(size, overlap):
    with pytest.raises(AppError):
        split_document("text", size, overlap)


def test_settings_persist_key_removal_and_permissions(tmp_path):
    from conftest import MemoryCredentials

    credentials = MemoryCredentials()
    settings = JsonSettingsStore(tmp_path, "env-key", credentials)
    assert settings.api_key() == "env-key"
    settings.update({"api_key": "saved-key", "top_k": 3})
    reloaded = JsonSettingsStore(tmp_path, "env-key", credentials)
    assert reloaded.api_key() == "saved-key" and reloaded.read()["top_k"] == 3
    assert (tmp_path / "settings.json").stat().st_mode & 0o777 == 0o600
    reloaded.update({"api_key": ""})
    assert JsonSettingsStore(tmp_path, "env-key", credentials).api_key() == ""


def test_real_chroma_persistence_and_model_namespace(system, tmp_path):
    client, knowledge, *_ = system
    client.post(
        "/api/libraries/default/documents",
        files={"file": ("notes.txt", b"local knowledge", "text/plain")},
    )
    reloaded = ChromaKnowledgeRepository(tmp_path / "chroma", "test-model")
    assert len(reloaded.documents("default")) == 1
    alternative = ChromaKnowledgeRepository(tmp_path / "chroma", "different-model")
    assert alternative.documents("default") == []
    assert knowledge.repository.search("default", [1, 0, 0], 20)[0].filename == "notes.txt"


def test_architecture_dependency_direction():
    root = Path(__file__).parents[1] / "src" / "edge_knowledge"
    forbidden = {
        "domain": {"application", "infrastructure", "api", "bootstrap"},
        "application": {"infrastructure", "api", "bootstrap"},
        "api": {"infrastructure", "bootstrap"},
    }
    frameworks = {"fastapi", "chromadb", "openai", "sentence_transformers", "pydantic"}
    for layer, blocked in forbidden.items():
        for file in (root / layer).glob("*.py"):
            for node in ast.walk(ast.parse(file.read_text())):
                names = []
                if isinstance(node, ast.Import):
                    names = [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for name in names:
                    if name.startswith("edge_knowledge."):
                        assert name.split(".")[1] not in blocked, f"Layer violation: {file}: {name}"
                    if layer in {"domain", "application"}:
                        assert name.split(".")[0] not in frameworks, (
                            f"Framework leak: {file}: {name}"
                        )
