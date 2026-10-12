import json
from io import BytesIO

import pytest
from PIL import Image

from edge_knowledge.domain.models import AppError, OCRResult
from edge_knowledge.infrastructure.assets import FileAssetStore
from edge_knowledge.infrastructure.images import PillowImageProcessor


def png(color="white"):
    output = BytesIO()
    Image.new("RGB", (320, 180), color).save(output, "PNG")
    return output.getvalue()


def upload(client, name="ticket.png", content=None, library="default"):
    return client.post(
        f"/api/libraries/{library}/documents",
        files={"file": (name, png() if content is None else content, "image/png")},
    )


def events(response):
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


def test_image_ingest_preview_ocr_metadata_and_delete(system, tmp_path):
    client, knowledge, *_ = system
    result = upload(client)
    assert result.status_code == 201
    doc = result.json()["document"]
    assert doc["kind"] == "image" and doc["ocr_status"] == "ready"
    assert (doc["width"], doc["height"]) == (320, 180)
    assert doc["chunks"] == 2
    doc_id = doc["id"]
    assert upload(client).json()["duplicate"] is True
    records = client.get("/api/libraries/default/documents").json()
    assert len(records) == 1 and records[0]["kind"] == "image"
    image = client.get(f"/api/libraries/default/documents/{doc_id}/image")
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert image.headers["cache-control"] == "no-store"
    assert client.get(f"/api/libraries/default/documents/{doc_id}/thumbnail").status_code == 200
    record = json.loads((tmp_path / "assets/default" / doc_id / "ocr.json").read_text())
    assert record["regions"][0]["bbox"] == [0.1, 0.2, 0.3, 0.1]
    assert "6583" in record["text"]
    hits = client.post("/api/search", json={"question": "取件码"}).json()
    assert len(hits) == 1 and hits[0]["kind"] == "image"
    assert "6583" in hits[0]["text"]
    client.delete(f"/api/libraries/default/documents/{doc_id}")
    assert not (tmp_path / "assets/default" / doc_id).exists()
    assert client.get(f"/api/libraries/default/documents/{doc_id}/image").status_code == 404
    assert knowledge.repository.documents("default") == []


def test_images_are_authenticated_and_library_scoped(system):
    client, *_ = system
    doc_id = upload(client).json()["document"]["id"]
    path = f"/api/libraries/default/documents/{doc_id}/thumbnail"
    assert client.get(path, headers={"Authorization": ""}).status_code == 401
    library = client.post("/api/libraries", json={"name": "其他资料"}).json()["id"]
    assert client.get(f"/api/libraries/{library}/documents/{doc_id}/image").status_code == 404


def test_image_import_failure_removes_assets(system, tmp_path, monkeypatch):
    _, knowledge, *_ = system

    def broken(*args):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(knowledge.repository, "add", broken)
    with pytest.raises(RuntimeError):
        knowledge.ingest("default", "failed.png", png())
    assert not list((tmp_path / "assets/default").glob("*/image.png"))
    assert knowledge.repository.documents("default") == []


def test_ocr_text_mode_never_attaches_images(system):
    client, _, chat, _ = system
    upload(client)
    client.patch("/api/settings", json={"api_key": "test-key", "model": "deepseek-chat"})
    plan = chat.prepare("default", "取件码是多少？")
    assert plan.images == []
    assert "本地 OCR 提取文字" in plan.prompt and "6583" in plan.prompt
    payloads = events(client.post("/api/query", json={"question": "取件码是多少？"}))
    assert any(
        event["type"] == "notice" and "未向 DeepSeek 发送图片" in event["message"]
        for event in payloads
    )
    assert payloads[-1] == {"type": "done"}


@pytest.mark.parametrize("status", ["empty", "unavailable", "error"])
def test_image_without_ocr_does_not_fake_visual_understanding(system, status):
    client, knowledge, _, generator = system

    class NoOCR:
        available = status != "unavailable"

        def recognize(self, content):
            return OCRResult(status)

    knowledge.images.ocr = NoOCR()
    upload(client)
    response = client.post("/api/query", json={"question": "图片里是什么？"})
    assert response.status_code == 200
    assert "没有可用的 OCR 文字" in response.text
    assert generator.calls == 0


def test_cloud_vision_requires_capability_and_per_request_consent(system, monkeypatch):
    client, knowledge, chat, _ = system
    upload(client)
    client.patch("/api/settings", json={"api_key": "test-key", "image_qa_mode": "cloud_vision"})

    # No asset read and no generator execution occur before this authorization check.
    def forbidden(*args):
        raise AssertionError("Image should not have been read")

    with monkeypatch.context() as context:
        context.setattr(knowledge.images, "attachment", forbidden)
        response = client.post("/api/query", json={"question": "看图"})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "image_upload_required"
    client.patch("/api/settings", json={"model": "deepseek-chat"})
    response = client.post("/api/query", json={"question": "看图", "allow_image_upload": True})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "image_model_unsupported"
    client.patch("/api/settings", json={"model": "deepseek-flash"})
    plan = chat.prepare("default", "看图", allow_image_upload=True)
    assert len(plan.images) == 1 and plan.images[0].media_type == "image/jpeg"
    assert Image.open(BytesIO(plan.images[0].data)).format == "JPEG"
    payloads = events(
        client.post("/api/query", json={"question": "看图", "allow_image_upload": True})
    )
    assert payloads[-1] == {"type": "done"}
    assert "base64" not in str(payloads) and "test-key" not in str(payloads)


def test_cloud_image_budget_and_source_numbering(system):
    client, _, chat, _ = system
    for i, color in enumerate(["white", "red", "blue", "green"]):
        upload(client, name=f"image-{i}.png", content=png(color))
    client.patch("/api/settings", json={"api_key": "test-key", "image_qa_mode": "cloud_vision"})
    plan = chat.prepare("default", "图片", top_k=10, allow_image_upload=True)
    assert len(plan.sources) == 4 and len(plan.images) == 3
    assert "其余图片未发送" in plan.notice
    for attachment in plan.images:
        index = next(
            i for i, hit in enumerate(plan.sources, 1) if hit.document_id == attachment.document_id
        )
        assert f"[{index}] 文件：{attachment.filename}" in plan.prompt


def test_capabilities_are_per_model(system):
    client, *_ = system
    assert (
        client.get("/api/capabilities?model=deepseek-flash").json()["generator"]["images"] is True
    )
    assert (
        client.get("/api/capabilities?model=deepseek-chat").json()["generator"]["images"] is False
    )
    assert client.get("/api/capabilities").json()["ocr"]["available"] is True
    assert client.get("/api/settings").json()["image_qa_mode"] == "local_ocr"


@pytest.mark.parametrize("content", [b"not an image", b"%PDF-1.4", b""])
def test_corrupt_or_disguised_images_are_rejected(system, content):
    client, *_ = system
    assert upload(client, content=content).status_code == 400


def test_image_normalization_strips_metadata_and_limits_cloud_size():
    source = Image.new("RGB", (3000, 1000), "white")
    exif = Image.Exif()
    exif[315] = "private author metadata"
    output = BytesIO()
    source.save(output, "JPEG", exif=exif)
    processor = PillowImageProcessor()
    prepared = processor.prepare(output.getvalue())
    assert not Image.open(BytesIO(prepared.data)).getexif()
    assert Image.open(BytesIO(prepared.thumbnail)).width <= 480
    for_cloud = processor.for_generation(prepared.data)
    image = Image.open(BytesIO(for_cloud.data))
    assert max(image.size) <= 2048 and not image.getexif()


def test_oversized_and_animated_images_are_rejected():
    output = BytesIO()
    Image.new("RGB", (8193, 1)).save(output, "PNG")
    with pytest.raises(AppError):
        PillowImageProcessor().prepare(output.getvalue())
    output = BytesIO()
    Image.new("RGB", (5, 5), "red").save(
        output,
        "WEBP",
        save_all=True,
        append_images=[Image.new("RGB", (5, 5), "blue")],
        duration=100,
    )
    with pytest.raises(AppError):
        PillowImageProcessor().prepare(output.getvalue())


def test_asset_storage_rejects_path_traversal(tmp_path):
    store = FileAssetStore(tmp_path)
    with pytest.raises(AppError):
        store.get("../outside", "a" * 64)
    with pytest.raises(AppError):
        store.get("default", "../secrets")


def test_standalone_ocr_requires_no_embedding_or_cloud(system, monkeypatch):
    client, knowledge, _, generator = system

    def forbidden(*args):
        raise AssertionError("OCR must not load embeddings")

    monkeypatch.setattr(knowledge.embedder, "image", forbidden)
    response = client.post("/api/ocr", files={"file": ("ticket.png", png(), "image/png")})
    assert response.status_code == 200
    assert response.json()["text"] == "快递取件码 6583"
    assert response.json()["regions"][0]["bbox"] == [0.1, 0.2, 0.3, 0.1]
    assert knowledge.repository.documents("default") == []
    assert generator.calls == 0
