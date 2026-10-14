import json
from dataclasses import replace
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from conftest import MemoryCredentials, TestEmbedder, TestGenerator, TestOCR
from fastapi.testclient import TestClient
from PIL import Image

from edge_knowledge.api.app import create_app
from edge_knowledge.application.backup import BackupService
from edge_knowledge.application.chat import ChatService
from edge_knowledge.application.images import ImageService
from edge_knowledge.application.knowledge import KnowledgeService
from edge_knowledge.domain.models import AppError
from edge_knowledge.domain.multimodal import InputAsset
from edge_knowledge.infrastructure.archive import FileArchiveStore
from edge_knowledge.infrastructure.assets import FileAssetStore
from edge_knowledge.infrastructure.backup import ZipBackupCodec
from edge_knowledge.infrastructure.chroma import ChromaKnowledgeRepository
from edge_knowledge.infrastructure.images import PillowImageProcessor
from edge_knowledge.infrastructure.parsers import FileDocumentParser
from edge_knowledge.infrastructure.payloads import FilePayloadStore
from edge_knowledge.infrastructure.settings import JsonSettingsStore


@pytest.fixture
def backups(tmp_path):
    settings = JsonSettingsStore(tmp_path, credentials=MemoryCredentials())
    repo = ChromaKnowledgeRepository(tmp_path / "chroma", "test-backup-model")
    images = ImageService(PillowImageProcessor(), TestOCR(), FileAssetStore(tmp_path / "assets"))
    payloads = FilePayloadStore(tmp_path / "payloads")
    knowledge = KnowledgeService(
        FileDocumentParser(), TestEmbedder(), repo, settings, images, payloads
    )
    archive = FileArchiveStore(tmp_path / "archive")
    service = BackupService(knowledge, archive, ZipBackupCodec(), "test-backup-model", 3)
    knowledge.ingest("default", "guide.md", b"# Guide\nBackup original text.")
    output = BytesIO()
    Image.new("RGB", (20, 10), "blue").save(output, format="PNG")
    knowledge.ingest("default", "sample.png", output.getvalue())
    records = repo.snapshot("default")
    archived = next(record for record in records if record.document.kind == "document")
    archive.put("default", replace(archived, document=replace(archived.document, id="a" * 64)))
    return knowledge, archive, service


def rewrite(data, mutate):
    output = BytesIO()
    with ZipFile(BytesIO(data)) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        manifest = json.loads(source.read("manifest.json"))
        mutate(manifest)
        for member in source.infolist():
            target.writestr(
                member.filename,
                json.dumps(manifest).encode()
                if member.filename == "manifest.json"
                else source.read(member.filename),
            )
    return output.getvalue()


def test_roundtrip_preserves_indexes_images_ocr_originals_and_archive(backups):
    knowledge, archive, service = backups
    knowledge.settings.update({"api_key": "excluded-fixture-secret"})
    frontend = {
        "chats": {"version": 1, "sessions": [], "active": {}},
        "preferences": {"fontSize": 13},
    }
    data = service.export(frontend)
    with ZipFile(BytesIO(data)) as file:
        assert "excluded-fixture-secret" not in file.read("manifest.json").decode()
        assert all(name == "manifest.json" or name.startswith("blobs/") for name in file.namelist())
    assert service.inspect(data)["documents"] == 3
    before = knowledge.repository.documents("default")
    result = service.restore(data)
    restored = result["mapping"]["default"]
    assert knowledge.repository.documents("default") == before
    assert knowledge.repository.documents(restored) == before
    assert len(archive.list(restored)) == 1
    assert (
        knowledge.payloads.get(restored, next(doc.id for doc in before if doc.kind == "document"))[
            1
        ][0].content
        == b"# Guide\nBackup original text."
    )
    image = next(doc for doc in before if doc.kind == "image")
    assert knowledge.images.assets.snapshot(restored, image.id)[1].text == "快递取件码 6583"
    assert knowledge.search(restored, "text", 5)
    assert result["frontend"] == frontend


def test_engine_provenance_survives_backup_restore(backups):
    knowledge, _, service = backups
    document = next(doc for doc in knowledge.repository.documents("default") if doc.kind == "image")
    image, ocr = knowledge.images.assets.snapshot("default", document.id)
    knowledge.images.assets.put(
        "default", document.id, image, replace(ocr, engine="RapidOCR · ONNX Runtime")
    )
    restored = service.restore(service.export({}))["mapping"]["default"]
    assert (
        knowledge.images.assets.snapshot(restored, document.id)[1].engine
        == "RapidOCR · ONNX Runtime"
    )


def test_wrong_model_and_corruption_do_not_create_libraries(backups):
    knowledge, _, service = backups
    data = service.export({})
    wrong = rewrite(data, lambda manifest: manifest.update(model="different-model"))
    assert service.inspect(wrong)["compatible"] is False
    with pytest.raises(AppError) as error:
        service.restore(wrong)
    assert error.value.code == "backup_model_mismatch"
    assert len(knowledge.repository.libraries()) == 1
    bad = rewrite(
        data, lambda manifest: manifest["libraries"][0]["items"][0]["vectors"][0].append(0.0)
    )
    with pytest.raises(AppError):
        service.restore(bad)
    assert len(knowledge.repository.libraries()) == 1


def test_traversal_and_hash_mismatch_are_rejected(backups):
    _, _, service = backups
    data = service.export({})

    def mutate(manifest):
        image = next(item for item in manifest["libraries"][0]["items"] if item.get("image"))
        image["image"]["image"]["sha256"] = "0" * 64

    with pytest.raises(AppError):
        service.inspect(rewrite(data, mutate))
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("../outside", "bad")
        archive.writestr("manifest.json", "{}")
    with pytest.raises(AppError):
        service.restore(output.getvalue())


def test_restore_failure_rolls_back_only_new_copies(backups, monkeypatch):
    knowledge, archive, service = backups
    data = service.export({})
    original = knowledge.repository.documents("default")
    add = knowledge.repository.add

    def fail(library, document, chunks, vectors):
        if document.kind == "image":
            raise RuntimeError("simulated storage failure")
        return add(library, document, chunks, vectors)

    monkeypatch.setattr(knowledge.repository, "add", fail)
    with pytest.raises(RuntimeError):
        service.restore(data)
    assert knowledge.repository.documents("default") == original
    assert len(knowledge.repository.libraries()) == 1
    assert len(archive.list("default")) == 1


def test_backup_api_is_authenticated_and_inspection_has_no_writes(backups):
    knowledge, _, service = backups
    chat = ChatService(knowledge, knowledge.settings, TestGenerator())
    with TestClient(
        create_app(knowledge, chat, "backup-test-token", backup=service),
        headers={"Authorization": "Bearer backup-test-token"},
    ) as client:
        assert (
            client.post("/api/backup/export", json={}, headers={"Authorization": ""}).status_code
            == 401
        )
        exported = client.post("/api/backup/export", json={})
        assert exported.status_code == 200 and exported.headers["cache-control"] == "no-store"
        inspected = client.post(
            "/api/backup/inspect", files={"file": ("test.edgebackup", exported.content)}
        )
        assert inspected.status_code == 200 and inspected.json()["compatible"]
        assert len(knowledge.repository.libraries()) == 1
        assert (
            client.post(
                "/api/backup/restore", files={"file": ("bad.edgebackup", b"bad")}
            ).status_code
            == 422
        )
        restored = client.post(
            "/api/backup/restore", files={"file": ("test.edgebackup", exported.content)}
        )
        assert restored.status_code == 200 and len(knowledge.repository.libraries()) == 2


def test_media_payload_bytes_survive_roundtrip(backups):
    knowledge, _, service = backups
    record = knowledge.repository.snapshot("default")[0]
    document = replace(record.document, id="b" * 64, kind="audio", filename="sample.wav", assets=1)
    knowledge.repository.add("default", document, record.chunks, record.vectors)
    knowledge.payloads.put(
        "default",
        document.id,
        "",
        [InputAsset("sample.wav", "audio", b"fixture-audio-bytes", "audio/wav")],
    )
    result = service.restore(service.export({}))
    assert (
        knowledge.payloads.get(result["mapping"]["default"], document.id)[1][0].content
        == b"fixture-audio-bytes"
    )


def test_frontend_rejects_credential_and_permission_fields(backups):
    _, _, service = backups
    with pytest.raises(AppError):
        service.export({"api_key": "must-not-export"})
    with pytest.raises(AppError):
        service.export({"preferences": {"local_access": "outside"}})


def test_unsent_chat_draft_survives_backup_restore(backups):
    _, _, service = backups
    draft = {"content": "  待续的问题\n\n保留空白  ", "mode": "search"}
    chat = {
        "id": "draft-chat",
        "library": "default",
        "title": "",
        "createdAt": "2026-10-14",
        "updatedAt": "2026-10-14",
        "messages": [],
        "references": [],
        "draft": draft,
    }
    frontend = {"chats": {"version": 1, "sessions": [chat], "active": {"default": chat["id"]}}}
    result = service.restore(service.export(frontend))
    assert result["frontend"]["chats"]["sessions"][0]["draft"] == draft
    draft["allowImageUpload"] = True
    with pytest.raises(AppError):
        service.export(frontend)


def test_duplicate_zip_entries_and_excessive_expansion_are_rejected(backups, monkeypatch):
    _, _, service = backups
    data = service.export({})
    import edge_knowledge.infrastructure.backup as codec_module

    monkeypatch.setattr(codec_module, "MAX_BACKUP_BYTES", 1000)
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", "{}")
        archive.writestr("blobs/0", b"a" * 10000)
    with pytest.raises(AppError):
        service.inspect(output.getvalue())
    monkeypatch.setattr(codec_module, "MAX_BACKUP_BYTES", 512 * 1024 * 1024)
    output = BytesIO()
    with ZipFile(BytesIO(data)) as source, ZipFile(output, "w") as target:
        for name in source.namelist():
            target.writestr(name, source.read(name))
        with pytest.warns(UserWarning):
            target.writestr("manifest.json", "{}")
    with pytest.raises(AppError):
        service.restore(output.getvalue())


def test_invalid_chat_schema_and_missing_original_notice(backups):
    _, _, service = backups
    with pytest.raises(AppError):
        service.export({"chats": {"version": 1, "sessions": [{"api_key": "excluded"}]}})
    result = service.inspect(service.export({}))
    assert result["missing_originals"] == 1  # synthetic archived record has no old original
