"""Real EmbeddingGemma 2 acceptance, local fixtures only and no cloud calls."""

import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from edge_knowledge.application.images import ImageService
from edge_knowledge.application.knowledge import KnowledgeService
from edge_knowledge.application.semantic import SemanticService
from edge_knowledge.domain.models import AppError
from edge_knowledge.domain.multimodal import EmbeddingInput, InputAsset, cosine
from edge_knowledge.infrastructure.assets import FileAssetStore
from edge_knowledge.infrastructure.chroma import ChromaKnowledgeRepository
from edge_knowledge.infrastructure.config import RuntimeConfig
from edge_knowledge.infrastructure.embedding import SentenceTransformerEmbedder
from edge_knowledge.infrastructure.images import PillowImageProcessor
from edge_knowledge.infrastructure.media import AVMediaDecoder
from edge_knowledge.infrastructure.ocr import LocalOCR
from edge_knowledge.infrastructure.parsers import FileDocumentParser
from edge_knowledge.infrastructure.payloads import FilePayloadStore
from edge_knowledge.infrastructure.settings import JsonSettingsStore

config = RuntimeConfig()
fixtures = Path(__file__).resolve().parents[1] / "backend/tests/fixtures"
embedder = SentenceTransformerEmbedder(
    config.embedding_model,
    True,
    model_path=config.embedding_model_path,
    prepared_path=config.prepared_model_dir
    or config.data_dir / "models/embeddinggemma-2",
)
report = {}
with TemporaryDirectory(prefix="edge-multimodal-check-") as directory:
    root = Path(directory)
    repo = ChromaKnowledgeRepository(root / "chroma", config.embedding_model)
    payloads = FilePayloadStore(root / "payloads")
    knowledge = KnowledgeService(
        FileDocumentParser(),
        embedder,
        repo,
        JsonSettingsStore(root),
        ImageService(
            PillowImageProcessor(), LocalOCR(), FileAssetStore(root / "assets")
        ),
        payloads,
    )
    semantic = SemanticService(knowledge, embedder, AVMediaDecoder(), payloads)
    image = (fixtures / "parcel-demo.png").read_bytes()
    knowledge.ingest("default", "parcel.png", image)
    knowledge.ingest(
        "default",
        "architecture.txt",
        b"Local documents are indexed and searched on the computer.",
    )
    knowledge.ingest(
        "default",
        "architecture-copy.txt",
        b"Local documents are indexed and searched on the computer.",
    )
    for kind, filename in [("audio", "speech-demo.wav"), ("video", "video-demo.mp4")]:
        result = semantic.ingest(
            "default", filename, "", [(filename, (fixtures / filename).read_bytes())]
        )
        assert result["document"]["kind"] == kind and result["document"]["duration"] > 0
        result = semantic.search(
            "default",
            "",
            [(filename, (fixtures / filename).read_bytes())],
            2,
            [],
            [kind],
            "search",
            768,
        )
        assert result["sources"] and result["sources"][0]["filename"] == filename
        assert result["sources"][0]["score"] > 0.99
        report[kind] = {
            "score": result["sources"][0]["score"],
            "budget": result["budget"],
        }
        print(f"Real {kind} indexing and same-media retrieval passed", flush=True)
    long_video = semantic.ingest(
        "default",
        "video-long-demo.mp4",
        "",
        [("video-long-demo.mp4", (fixtures / "video-long-demo.mp4").read_bytes())],
    )
    assert (
        long_video["document"]["chunks"] == 2
        and long_video["document"]["duration"] == 26
    )
    long_result = semantic.search(
        "default",
        "A delivery note with pickup code",
        [],
        2,
        [long_video["document"]["id"]],
        [],
        "search",
        768,
    )
    times = sorted(
        (source["start"], source["end"]) for source in long_result["sources"]
    )
    assert times == [(0, 24), (24, 26)]
    report["long_video"] = {
        "duration": 26,
        "segments": 2,
        "times": times,
        "max_segment_tokens": long_video["budget"]["max_tokens"],
    }
    print(
        "Real 26-second video inference and tail-segment retrieval passed", flush=True
    )
    audio_item = next(
        AVMediaDecoder().segments(
            InputAsset(
                "speech-demo.wav",
                "audio",
                (fixtures / "speech-demo.wav").read_bytes(),
                "audio/wav",
            )
        )
    )
    audio_vector = embedder.encode_input(audio_item)
    related = cosine(
        audio_vector,
        embedder.query("A spoken delivery note with pickup code six five eight three"),
    )
    unrelated = cosine(
        audio_vector, embedder.query("A cooking recipe for tomatoes and scrambled eggs")
    )
    assert related > unrelated
    report["text_to_audio"] = {
        "related_score": round(related, 4),
        "unrelated_score": round(unrelated, 4),
    }
    for dimension in [128, 256, 512, 768]:
        result = semantic.search(
            "default",
            "",
            [("parcel.png", image)],
            3,
            [],
            ["image"],
            "search",
            dimension,
        )
        assert (
            result["sources"][0]["filename"] == "parcel.png"
            and result["sources"][0]["score"] > 0.99
        )
    report["image_to_image_dimensions"] = [128, 256, 512, 768]
    combined = semantic.ingest(
        "default",
        "Delivery package",
        "Delivery note and pickup code",
        [("front.png", image), ("detail.png", image)],
    )
    result = semantic.search(
        "default",
        "Delivery note and pickup code",
        [("front.png", image), ("detail.png", image)],
        3,
        [combined["document"]["id"]],
        [],
        "search",
        768,
    )
    assert result["aggregation"] == "joint" and result["sources"]
    report["joint_images_text"] = result["budget"]
    print("Real image query, text+two-image joint encoding and MRL passed", flush=True)
    full = semantic.ingest(
        "default",
        "Full joint media",
        "Delivery note",
        [
            ("front.png", image),
            ("detail.png", image),
            ("video-demo.mp4", (fixtures / "video-demo.mp4").read_bytes()),
        ],
    )
    assert full["document"]["kind"] == "bundle" and full["budget"]["segments"] == 1
    report["text_images_video_audio_joint"] = full["budget"]
    ids = [doc.id for doc in repo.documents("default") if doc.kind == "document"]
    for task in ["classification", "clustering", "similarity"]:
        result = semantic.organize(
            "default",
            ids,
            task,
            ["computer architecture", "cooking recipes"],
            2,
            0.95 if task == "similarity" else 0,
            768,
        )
        if task == "similarity":
            assert result["pairs"] and result["pairs"][0]["score"] > 0.99
        elif task == "classification":
            assert all(
                row["label"] == "computer architecture" for row in result["assignments"]
            )
        else:
            assert sum(len(group) for group in result["groups"]) == len(ids)
        report[task] = "passed"
        print(f"Real {task} task passed", flush=True)
    item = EmbeddingInput(text="context budget " * 10000, images=(image,) * 12)
    budget = embedder.budget(item)
    try:
        embedder.encode_input(item)
        raise AssertionError("oversize input was not rejected")
    except AppError as failure:
        assert failure.code == "context_budget_exceeded"
    parts = embedder.split_text("上下文预算管理。" * 6000)
    assert "".join(parts) == "上下文预算管理。" * 6000
    assert all(
        embedder.budget(EmbeddingInput(text=part), "document").total <= 8192
        for part in parts
    )
    report["context_budget"] = {
        "rejected_tokens": budget.total,
        "lossless_text_segments": len(parts),
        "limit": 8192,
    }
    report["scope"] = (
        "Runtime acceptance on local demo samples, not a general retrieval-quality benchmark"
    )
    assert all(
        math.isfinite(value)
        for value in embedder.encode_input(EmbeddingInput(text="finite vector"))
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    Path("docs/multimodal-acceptance.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
