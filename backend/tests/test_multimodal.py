import io
import json
import math
import wave
from pathlib import Path

import pytest
from conftest import TestGenerator, TestOCR
from fastapi.testclient import TestClient

from edge_knowledge.api.app import create_app
from edge_knowledge.application.chat import ChatService
from edge_knowledge.application.images import ImageService
from edge_knowledge.application.knowledge import KnowledgeService
from edge_knowledge.application.semantic import SemanticService
from edge_knowledge.domain.models import AppError
from edge_knowledge.domain.multimodal import EmbeddingInput, InputAsset, budget_for, unit
from edge_knowledge.infrastructure.archive import FileArchiveStore
from edge_knowledge.infrastructure.assets import FileAssetStore
from edge_knowledge.infrastructure.chroma import ChromaKnowledgeRepository
from edge_knowledge.infrastructure.images import PillowImageProcessor
from edge_knowledge.infrastructure.media import AVMediaDecoder
from edge_knowledge.infrastructure.parsers import FileDocumentParser
from edge_knowledge.infrastructure.payloads import FilePayloadStore
from edge_knowledge.infrastructure.settings import JsonSettingsStore

FIXTURES = Path(__file__).parent / "fixtures"


class SemanticDouble:
    """Port double for boundary tests only; all codec/storage/API paths are real."""

    ready = loaded = enable_images = True
    calls = []

    def budget(self, item, task="search"):
        return budget_for(item, len(item.text) + 10)

    def split_text(self, text, task="document"):
        return [text[i : i + 8000] for i in range(0, len(text), 8000)]

    def encode_input(self, item, task="search", dimension=768):
        self.budget(item, task).ensure()
        self.calls.append((item, task, dimension))
        index = 0 if "architecture" in item.text.lower() or "computer" in item.text.lower() else 1
        if item.has_media:
            index = 2
        return unit([1.0 if i == index else 0.0 for i in range(dimension)])

    def documents(self, texts):
        return [self.encode_input(EmbeddingInput(text=text), "document") for text in texts]

    def query(self, text):
        return self.encode_input(EmbeddingInput(text=text))

    def image(self, content):
        return self.encode_input(EmbeddingInput(images=(content,)))


@pytest.fixture
def multimodal(tmp_path):
    from conftest import MemoryCredentials

    settings = JsonSettingsStore(tmp_path, credentials=MemoryCredentials())
    repo = ChromaKnowledgeRepository(tmp_path / "chroma", "semantic-test")
    embedder = SemanticDouble()
    embedder.calls = []
    payloads = FilePayloadStore(tmp_path / "payloads")
    knowledge = KnowledgeService(
        FileDocumentParser(),
        embedder,
        repo,
        settings,
        ImageService(PillowImageProcessor(), TestOCR(), FileAssetStore(tmp_path / "images")),
        payloads,
    )
    semantic = SemanticService(
        knowledge, embedder, AVMediaDecoder(), payloads, FileArchiveStore(tmp_path / "archive")
    )
    chat = ChatService(knowledge, settings, TestGenerator())
    app = create_app(knowledge, chat, "token", semantic=semantic)
    with TestClient(app, headers={"Authorization": "Bearer token"}) as client:
        yield client, semantic, embedder


def upload(client, path, options, files=None):
    return client.post(path, data={"options": json.dumps(options)}, files=files or [])


def test_joint_input_is_one_encoding_and_respects_scope(multimodal):
    client, semantic, embedder = multimodal
    image = (FIXTURES / "parcel-demo.png").read_bytes()
    response = upload(
        client,
        "/api/multimodal/ingest",
        {"name": "joint", "text": "architecture", "library_id": "default"},
        [("files", ("a.png", image)), ("files", ("b.png", image))],
    )
    assert response.status_code == 201
    doc = response.json()["document"]
    assert doc["kind"] == "bundle" and doc["chunks"] == 1
    assert len(embedder.calls[-1][0].images) == 2 and embedder.calls[-1][0].text == "architecture"
    response = upload(
        client,
        "/api/multimodal/search",
        {"text": "architecture", "document_ids": [doc["id"]], "dimension": 128},
        [("files", ("a.png", image))],
    )
    assert response.status_code == 200 and response.json()["aggregation"] == "joint"
    assert response.json()["sources"][0]["document_id"] == doc["id"]
    assert semantic.original("default", doc["id"], 0).data
    assert (
        client.get(f"/api/libraries/default/documents/{doc['id']}/media").json()[1]["filename"]
        == "b.png"
    )


def test_membership_rejected_before_model_and_private_assets(multimodal):
    client, semantic, embedder = multimodal
    doc = semantic.ingest(
        "default",
        "private",
        "architecture",
        [("a.png", (FIXTURES / "parcel-demo.png").read_bytes())],
    )["document"]
    other = client.post("/api/libraries", json={"name": "other"}).json()["id"]
    count = len(embedder.calls)
    result = upload(
        client,
        "/api/multimodal/search",
        {"library_id": other, "text": "x", "document_ids": [doc["id"]]},
    )
    assert result.status_code == 404 and len(embedder.calls) == count
    assert client.get(f"/api/libraries/{other}/documents/{doc['id']}/media/0").status_code == 404
    assert (
        client.get(
            f"/api/libraries/default/documents/{doc['id']}/media/0",
            headers={"Authorization": "bad"},
        ).status_code
        == 401
    )
    assert client.get("/api/libraries/default/documents/not-an-id/media/0").status_code == 404
    client.delete(f"/api/libraries/default/documents/{doc['id']}")
    assert client.get(f"/api/libraries/default/documents/{doc['id']}/media/0").status_code == 404
    with pytest.raises(AppError):
        semantic.payloads.get("default", doc["id"])


def test_context_overflow_is_rejected_without_inference(multimodal):
    client, _, embedder = multimodal
    response = upload(
        client,
        "/api/multimodal/search",
        {"text": "x" * 10000},
        [("files", ("a.png", (FIXTURES / "parcel-demo.png").read_bytes()))],
    )
    assert (
        response.status_code == 413
        and response.json()["error"]["code"] == "context_budget_exceeded"
    )
    assert not embedder.calls
    with pytest.raises(AppError):
        unit([0, 0])
    assert math.isclose(sum(v * v for v in unit([1, 2, 3], 2)), 1)


def test_actual_audio_video_decoding_and_time_metadata(multimodal):
    client, _, embedder = multimodal
    for name, kind in [("speech-demo.wav", "audio"), ("video-demo.mp4", "video")]:
        response = client.post(
            "/api/libraries/default/documents",
            files={"file": (name, (FIXTURES / name).read_bytes())},
        )
        assert response.status_code == 201, response.text
        doc = response.json()["document"]
        assert doc["kind"] == kind and 0 < doc["duration"] < 20
        response = upload(client, "/api/multimodal/search", {"text": "audio", "kinds": [kind]})
        hit = response.json()["sources"][0]
        assert hit["end"] == doc["duration"] and hit["start"] == 0
    video = next(call[0] for call in embedder.calls if call[0].frames)
    assert len(video.frames) == 4 and video.audio


def test_audio_segmentation_is_lossless_and_bounded():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 16000 * 50)
    asset = InputAsset("long.wav", "audio", buffer.getvalue(), "audio/wav")
    segments = list(AVMediaDecoder().segments(asset))
    assert [(item.start, item.end) for item in segments] == [(0, 24), (24, 48), (48, 50)]
    assert sum(len(item.audio) // 4 for item in segments) == 50 * 16000
    assert all(budget_for(item, 0).total < 8192 for item in segments)


def test_task_specific_classification_clustering_and_duplicates(multimodal):
    client, semantic, embedder = multimodal
    for name, text in [
        ("a", "computer architecture"),
        ("b", "computer architecture"),
        ("c", "cooking recipe"),
    ]:
        semantic.ingest("default", name, text, [])
    classification = client.post(
        "/api/organize",
        json={"task": "classification", "labels": ["computer", "recipe"], "threshold": 0},
    ).json()
    assert [row["label"] for row in classification["assignments"]].count("computer") == 2
    clusters = client.post("/api/organize", json={"task": "clustering", "clusters": 2}).json()[
        "groups"
    ]
    assert sorted(len(group) for group in clusters) == [1, 2]
    pairs = client.post("/api/organize", json={"task": "similarity", "threshold": 0.99}).json()[
        "pairs"
    ]
    assert len(pairs) == 1 and pairs[0]["score"] == 1
    assert {"classification", "clustering", "similarity"} <= {call[1] for call in embedder.calls}
    assert len(semantic.knowledge.repository.documents("default")) == 3


def test_media_vectors_are_never_cloud_text_evidence(multimodal):
    client, semantic, _ = multimodal
    semantic.ingest(
        "default",
        "speech-demo.wav",
        "",
        [("speech-demo.wav", (FIXTURES / "speech-demo.wav").read_bytes())],
    )
    semantic.knowledge.settings.update({"min_score": -1})
    response = client.post("/api/query", json={"question": "find speech"})
    assert response.status_code == 200
    assert "missing_api_key" not in response.text
    assert "未将媒体发送到云端" in response.text


def test_failed_index_rolls_back_payload(multimodal, monkeypatch):
    _, semantic, _ = multimodal
    original = semantic.payloads.put
    captured = []

    def put(library, doc, text, assets):
        captured.append(doc)
        original(library, doc, text, assets)

    monkeypatch.setattr(semantic.payloads, "put", put)

    def fail(*args):
        raise RuntimeError("test index failure")

    monkeypatch.setattr(semantic.knowledge.repository, "add", fail)
    with pytest.raises(RuntimeError):
        semantic.ingest("default", "joint", "text", [])
    with pytest.raises(AppError):
        semantic.payloads.get("default", captured[0])


@pytest.mark.parametrize(
    "options",
    [
        {"dimension": 127},
        {"document_ids": ["../private"]},
        {"top_k": 51},
        {"task": "bad"},
        {"unexpected": "value"},
    ],
)
def test_multimodal_parameter_validation(multimodal, options):
    client, _, _ = multimodal
    assert upload(client, "/api/multimodal/search", options).status_code == 422


def test_archive_is_recoverable_and_blocks_media_access(multimodal):
    client, semantic, _ = multimodal
    doc = semantic.ingest(
        "default", "joint", "text", [("a.png", (FIXTURES / "parcel-demo.png").read_bytes())]
    )["document"]
    other = client.post("/api/libraries", json={"name": "other"}).json()["id"]
    assert client.post(f"/api/libraries/{other}/documents/{doc['id']}/archive").status_code == 404
    assert client.post(f"/api/libraries/default/documents/{doc['id']}/archive").status_code == 200
    assert client.get(f"/api/libraries/default/documents/{doc['id']}/media/0").status_code == 404
    assert client.get("/api/libraries/default/archive").json()[0]["id"] == doc["id"]
    assert client.post(f"/api/libraries/{other}/archive/{doc['id']}/restore").status_code == 404
    assert client.post(f"/api/libraries/default/archive/{doc['id']}/restore").status_code == 200
    assert client.get(f"/api/libraries/default/documents/{doc['id']}/media/0").status_code == 200
    assert client.get("/api/libraries/default/archive").json() == []


def test_budget_preflight_returns_overflow_without_inference(multimodal):
    client, _, embedder = multimodal
    response = upload(
        client,
        "/api/multimodal/budget",
        {"text": "x" * 10000},
        [("files", ("a.png", (FIXTURES / "parcel-demo.png").read_bytes()))],
    )
    assert response.status_code == 200 and response.json()["fits"] is False
    assert response.json()["max_tokens"] > 8192 and not embedder.calls


def test_image_results_collapse_visual_and_ocr_chunks(multimodal):
    client, semantic, _ = multimodal
    semantic.knowledge.ingest("default", "image.png", (FIXTURES / "parcel-demo.png").read_bytes())
    result = upload(
        client,
        "/api/multimodal/search",
        {"kinds": ["image"]},
        [("files", ("a.png", (FIXTURES / "parcel-demo.png").read_bytes()))],
    )
    assert result.status_code == 200 and len(result.json()["sources"]) == 1


def test_variable_frame_timing_keeps_one_frame_per_second():
    from fractions import Fraction

    import av
    import numpy as np

    container_bytes = io.BytesIO()
    with av.open(container_bytes, "w", format="mp4") as container:
        stream = container.add_stream("libx264", rate=10)
        stream.width = stream.height = 16
        stream.pix_fmt = "yuv420p"
        stream.codec_context.time_base = Fraction(1, 10)
        for pts in [0, 50, 51, 100, 110, 200]:
            frame = av.VideoFrame.from_ndarray(
                np.zeros((16, 16, 3), dtype=np.uint8), format="rgb24"
            )
            frame.pts = pts
            frame.time_base = Fraction(1, 10)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    asset = InputAsset("variable.mp4", "video", container_bytes.getvalue(), "video/mp4")
    segments = list(AVMediaDecoder().segments(asset))
    # 5.0s and 5.1s occupy the same sampling slot; timestamp gaps must not oversample.
    assert len(segments) == 1 and len(segments[0].frames) == 5
