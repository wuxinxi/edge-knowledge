from uuid import uuid4

import pytest
from conftest import TestGenerator
from fastapi.testclient import TestClient
from test_folders import folders as folders

from edge_knowledge.api.app import create_app
from edge_knowledge.application.chat import ChatService
from edge_knowledge.application.maintenance import LibraryMaintenance
from edge_knowledge.domain.models import AppError, Chunk, Document
from edge_knowledge.infrastructure.archive import FileArchiveStore


def test_batch_archive_undo_and_library_isolation(folders):
    k = folders.knowledge
    maintenance = LibraryMaintenance(k, folders.semantic.archive, folders)
    first = k.ingest("default", "first.md", b"First document")["document"]["id"]
    second = k.ingest("default", "second.md", b"Second document")["document"]["id"]
    other = k.repository.create_library("Other").id
    foreign = k.ingest(other, "foreign.md", b"Other library")["document"]["id"]
    with pytest.raises(AppError):
        maintenance.archive_documents("default", [first, foreign])
    assert len(k.repository.documents("default")) == 2
    result = maintenance.archive_documents("default", [first, second])
    assert result["archived"] == 2 and not k.repository.documents("default")
    assert len(k.repository.documents(other)) == 1
    assert len(folders.semantic.archive.list("default")) == 2
    maintenance.restore_documents("default", result["document_ids"])
    assert {d.id for d in k.repository.documents("default")} == {first, second}
    assert not folders.semantic.archive.list("default")


def test_clear_suspends_sources_and_rejects_late_uploads_even_after_resume(folders):
    source = str(uuid4())
    maintenance = LibraryMaintenance(folders.knowledge, folders.semantic.archive, folders)
    folders.upsert("default", source, "notes.md", b"Original")
    assert folders.lease("default", source) == {"epoch": 0, "enabled": True}
    maintenance.archive_documents("default", [], True)
    assert folders.lease("default", source) == {"epoch": 1, "enabled": False}
    with pytest.raises(AppError, match="暂停"):
        folders.upsert("default", source, "notes.md", b"Late update", 0)
    folders.activate("default", source)
    with pytest.raises(AppError, match="暂停"):
        folders.upsert("default", source, "notes.md", b"Late update", 0)
    with pytest.raises(AppError):
        folders.reconcile("default", source, [], 0)
    assert not folders.knowledge.repository.documents("default")
    assert not folders.upsert("default", source, "notes.md", b"Original", 1)["changed"]
    folders.upsert("default", source, "notes.md", b"Explicit new version", 1)
    assert len(folders.knowledge.repository.documents("default")) == 1


def test_archive_write_failure_and_partial_index_delete_roll_back(folders, monkeypatch):
    k = folders.knowledge
    maintenance = LibraryMaintenance(k, folders.semantic.archive)
    ids = [k.ingest("default", str(i) + ".md", b"Text")["document"]["id"] for i in range(3)]
    put = folders.semantic.archive.put
    calls = 0

    def fail_put(library, record):
        nonlocal calls
        calls += 1
        put(library, record)
        if calls == 2:
            raise OSError("test disk failure")

    with monkeypatch.context() as patch:
        patch.setattr(folders.semantic.archive, "put", fail_put)
        with pytest.raises(AppError):
            maintenance.archive_documents("default", ids)
    assert {d.id for d in k.repository.documents("default")} == set(ids)
    assert not folders.semantic.archive.list("default")
    delete = k.repository.delete_many

    def fail_delete(library, values):
        delete(library, values[:1])
        raise RuntimeError("test partial failure")

    with monkeypatch.context() as patch:
        patch.setattr(k.repository, "delete_many", fail_delete)
        with pytest.raises(AppError):
            maintenance.archive_documents("default", ids)
    assert {d.id for d in k.repository.documents("default")} == set(ids)
    assert not folders.semantic.archive.list("default")


def test_restore_failure_rebuilds_deleted_archive_records(folders, monkeypatch):
    k = folders.knowledge
    maintenance = LibraryMaintenance(k, folders.semantic.archive)
    ids = [k.ingest("default", str(i) + ".md", b"Text")["document"]["id"] for i in range(2)]
    maintenance.archive_documents("default", ids)
    delete = folders.semantic.archive.delete
    calls = 0

    def fail_delete(library, id):
        nonlocal calls
        calls += 1
        delete(library, id)
        if calls == 2:
            raise OSError("test failure")

    with monkeypatch.context() as patch:
        patch.setattr(folders.semantic.archive, "delete", fail_delete)
        with pytest.raises(AppError):
            maintenance.restore_documents("default", ids)
    assert not k.repository.documents("default")
    assert {d.id for d in folders.semantic.archive.list("default")} == set(ids)
    maintenance.restore_documents("default", ids)
    assert len(k.repository.documents("default")) == 2


def test_large_corpus_archive_preserves_all_chunks_without_exact_search_limit(system, tmp_path):
    _, k, *_ = system
    id = "b" * 64
    document = Document(id, "large.md", 10001, 10001, "2026-10-12")
    chunks = [Chunk(str(i), i, "Large document") for i in range(10001)]
    k.repository.add("default", document, chunks, [[1.0, 0.0, 0.0]] * len(chunks))
    archive = FileArchiveStore(tmp_path / "archive-large")
    maintenance = LibraryMaintenance(k, archive)
    maintenance.archive_documents("default", [], True)
    record = archive.get("default", id)
    assert len(record.chunks) == len(record.vectors) == 10001
    assert record.chunks[-1].text == "10000"
    maintenance.restore_documents("default", [id])
    assert len(k.repository.record("default", id).chunks) == 10001


def test_batch_api_auth_validation_and_restore(folders):
    k = folders.knowledge
    maintenance = LibraryMaintenance(k, folders.semantic.archive, folders)
    id = k.ingest("default", "notes.md", b"Local text")["document"]["id"]
    app = create_app(
        k,
        ChatService(k, k.settings, TestGenerator()),
        "batch-test",
        semantic=folders.semantic,
        folders=folders,
        maintenance=maintenance,
    )
    endpoint = "/api/libraries/default/documents/archive-batch"
    with TestClient(app) as client:
        assert client.post(endpoint, json={"all_documents": True}).status_code == 401
        client.headers["Authorization"] = "Bearer batch-test"
        for body in [
            {},
            {"document_ids": [id, id]},
            {"all_documents": True, "document_ids": [id]},
            {"document_ids": ["../bad"]},
        ]:
            assert client.post(endpoint, json=body).status_code == 422
        result = client.post(endpoint, json={"all_documents": True}).json()
        assert result["archived"] == 1 and not k.repository.documents("default")
        response = client.post(
            "/api/libraries/default/archive/restore-batch",
            json={"document_ids": result["document_ids"]},
        )
        assert response.json() == {"restored": 1}
