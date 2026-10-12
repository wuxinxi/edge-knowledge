import io
import wave
from uuid import uuid4

import pytest
from conftest import MemoryCredentials, TestGenerator, TestOCR
from fastapi.testclient import TestClient
from test_multimodal import SemanticDouble

from edge_knowledge.api.app import create_app
from edge_knowledge.application.backup import BackupService
from edge_knowledge.application.chat import ChatService
from edge_knowledge.application.folders import FolderService
from edge_knowledge.application.images import ImageService
from edge_knowledge.application.knowledge import KnowledgeService
from edge_knowledge.application.semantic import SemanticService
from edge_knowledge.infrastructure.archive import FileArchiveStore
from edge_knowledge.infrastructure.assets import FileAssetStore
from edge_knowledge.infrastructure.backup import ZipBackupCodec
from edge_knowledge.infrastructure.chroma import ChromaKnowledgeRepository
from edge_knowledge.infrastructure.images import PillowImageProcessor
from edge_knowledge.infrastructure.media import AVMediaDecoder
from edge_knowledge.infrastructure.parsers import FileDocumentParser
from edge_knowledge.infrastructure.payloads import FilePayloadStore
from edge_knowledge.infrastructure.settings import JsonSettingsStore
from edge_knowledge.infrastructure.sources import SQLiteSourceStore


@pytest.fixture
def folders(tmp_path):
    repository = ChromaKnowledgeRepository(tmp_path / "chroma", "folders-test")
    settings = JsonSettingsStore(tmp_path, credentials=MemoryCredentials())
    images = ImageService(PillowImageProcessor(), TestOCR(), FileAssetStore(tmp_path / "assets"))
    knowledge = KnowledgeService(
        FileDocumentParser(),
        SemanticDouble(),
        repository,
        settings,
        images,
        FilePayloadStore(tmp_path / "payloads"),
    )
    archive = FileArchiveStore(tmp_path / "archive")
    semantic = SemanticService(
        knowledge, knowledge.embedder, AVMediaDecoder(), knowledge.payloads, archive
    )
    store = SQLiteSourceStore(tmp_path / "sources.sqlite3")
    return FolderService(knowledge, semantic, store)


def test_incremental_replacement_and_source_library_isolation(folders, tmp_path):
    source, other = str(uuid4()), str(uuid4())
    content = b"# Notes\nArchitecture design"
    manual = folders.knowledge.ingest("default", "notes.md", content)["document"]["id"]
    a = folders.upsert("default", source, "work/notes.md", content)["document_id"]
    b = folders.upsert("default", source, "personal/notes.md", content)["document_id"]
    c = folders.upsert("default", other, "work/notes.md", content)["document_id"]
    library = folders.knowledge.repository.create_library("Another").id
    d = folders.upsert(library, source, "work/notes.md", content)["document_id"]
    assert len({manual, a, b, c, d}) == 5
    assert folders.upsert("default", source, "work/notes.md", content)["changed"] is False
    changed = folders.upsert("default", source, "work/notes.md", b"# New notes\nChanged")
    active = {doc.id for doc in folders.knowledge.repository.documents("default")}
    assert a not in active and changed["document_id"] in active
    assert folders.semantic.archive.get("default", a).document.id == a
    folders.reconcile("default", source, [])
    assert {doc.id for doc in folders.knowledge.repository.documents("default")} == {manual, c}
    assert {doc.id for doc in folders.knowledge.repository.documents(library)} == {d}
    reloaded = SQLiteSourceStore(tmp_path / "sources.sqlite3")
    assert reloaded.files("default", other)[0].document_id == c
    assert not reloaded.files("default", source)


def test_failed_embedding_or_ledger_commit_keeps_the_old_index(folders, monkeypatch):
    source = str(uuid4())
    old = folders.upsert("default", source, "notes.md", b"Original")
    old_manifest = folders.files("default", source)
    with monkeypatch.context() as patch:

        def fail(*args):
            raise RuntimeError("test failure")

        patch.setattr(folders.knowledge.embedder, "documents", fail)
        with pytest.raises(RuntimeError):
            folders.upsert("default", source, "notes.md", b"Updated")
    with monkeypatch.context() as patch:
        patch.setattr(folders.store, "put", fail)
        with pytest.raises(RuntimeError):
            folders.upsert("default", source, "notes.md", b"Updated")
    assert folders.files("default", source) == old_manifest
    assert [d.id for d in folders.knowledge.repository.documents("default")] == [old["document_id"]]
    assert folders.semantic.archive.list("default") == []


def test_reconcile_failure_restores_the_file_and_keeps_its_ownership(folders, monkeypatch):
    source = str(uuid4())
    folders.upsert("default", source, "notes.md", b"Original")
    manifest = folders.files("default", source)

    def fail(*args):
        raise OSError("disk failure")

    monkeypatch.setattr(folders.store, "remove", fail)
    with pytest.raises(OSError):
        folders.reconcile("default", source, [])
    assert folders.files("default", source) == manifest
    assert len(folders.knowledge.repository.documents("default")) == 1


def test_returning_to_old_content_or_reappearing_creates_a_distinct_recoverable_revision(folders):
    source = str(uuid4())
    first = folders.upsert("default", source, "notes.md", b"Version one")["document_id"]
    second = folders.upsert("default", source, "notes.md", b"Version two")["document_id"]
    third = folders.upsert("default", source, "notes.md", b"Version one")["document_id"]
    folders.reconcile("default", source, [])
    fourth = folders.upsert("default", source, "notes.md", b"Version one")["document_id"]
    assert len({first, second, third, fourth}) == 4
    backup = BackupService(
        folders.knowledge, folders.semantic.archive, ZipBackupCodec(), "folders-test"
    )
    decoded = ZipBackupCodec().decode(backup.export({}))
    assert len(decoded.libraries[0].items) == 4


def test_folder_api_auth_complete_inventory_validation_and_relative_paths(folders):
    source = str(uuid4())
    app = create_app(
        folders.knowledge,
        ChatService(folders.knowledge, folders.knowledge.settings, TestGenerator()),
        "folder-test",
        semantic=folders.semantic,
        folders=folders,
    )
    endpoint = f"/api/libraries/default/folders/{source}"
    with TestClient(app) as client:
        assert client.get(endpoint + "/files").status_code == 401
        client.headers["Authorization"] = "Bearer folder-test"
        for path in ["../notes.md", "/notes.md", "nested/../notes.md", "C:/notes.md", "a\\b.md"]:
            assert (
                client.post(
                    endpoint + "/files",
                    data={"path": path},
                    files={"file": ("notes.md", b"Not imported")},
                ).status_code
                == 422
            )
        assert (
            client.post(
                endpoint + "/files",
                data={"path": "notes.md"},
                files={"file": ("notes.md", b"Original")},
            ).status_code
            == 200
        )
        for body in [
            {"paths": [], "complete": False},
            {"paths": ["x", "x"], "complete": True},
            {"paths": "notes.md", "complete": True},
            [],
            None,
        ]:
            assert client.post(endpoint + "/reconcile", json=body).status_code == 422
        assert len(folders.knowledge.repository.documents("default")) == 1
        assert client.post(
            endpoint + "/reconcile", json={"paths": [], "complete": True}
        ).json() == {"removed": 1}


def test_native_media_folder_replacement_uses_the_multimodal_pipeline(folders):
    source = str(uuid4())
    stream = io.BytesIO()
    with wave.open(stream, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\0\0" * 16000)
    result = folders.upsert("default", source, "tone.wav", stream.getvalue())
    document = folders.knowledge.repository.documents("default")[0]
    assert document.kind == "audio" and document.id == result["document_id"]
    assert folders.semantic.manifest("default", document.id)[0]["kind"] == "audio"
