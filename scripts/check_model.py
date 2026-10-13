"""Real local model and image retrieval check; prepare weights first, no cloud generation."""

import math
from pathlib import Path
from tempfile import TemporaryDirectory

from edge_knowledge.application.images import ImageService
from edge_knowledge.application.knowledge import KnowledgeService
from edge_knowledge.infrastructure.assets import FileAssetStore
from edge_knowledge.infrastructure.chroma import ChromaKnowledgeRepository
from edge_knowledge.infrastructure.config import RuntimeConfig
from edge_knowledge.infrastructure.embedding import SentenceTransformerEmbedder
from edge_knowledge.infrastructure.images import PillowImageProcessor
from edge_knowledge.infrastructure.ocr import LocalOCR
from edge_knowledge.infrastructure.parsers import FileDocumentParser
from edge_knowledge.infrastructure.settings import JsonSettingsStore

config = RuntimeConfig()
prepared = config.prepared_model_dir or config.data_dir / "models/embeddinggemma-2"
embedder = SentenceTransformerEmbedder(
    config.embedding_model,
    config.model_offline,
    model_path=config.embedding_model_path,
    prepared_path=prepared,
)
with TemporaryDirectory(prefix="edge-assistant-model-check-") as directory:
    path = Path(directory)
    repository = ChromaKnowledgeRepository(path / "chroma", config.embedding_model)
    knowledge = KnowledgeService(
        FileDocumentParser(),
        embedder,
        repository,
        JsonSettingsStore(path),
        ImageService(
            PillowImageProcessor(), LocalOCR(), FileAssetStore(path / "assets")
        ),
    )
    knowledge.ingest(
        "default", "architecture.md", "# 架构\n资料解析与检索在本机进行。".encode()
    )
    knowledge.ingest(
        "default", "recipe.md", "# 食谱\n番茄切块，与鸡蛋一起炒熟。".encode()
    )
    hits = knowledge.search("default", "资料在哪里进行检索？", 5)
    assert hits and hits[0].filename == "architecture.md"
    assert math.isfinite(hits[0].score)
    print(
        f"Real embedding + persistent Chroma retrieval passed. Score: {hits[0].score}",
        flush=True,
    )
    image = (
        Path(__file__).resolve().parents[1] / "backend/tests/fixtures/parcel-demo.png"
    )
    result = knowledge.ingest("default", image.name, image.read_bytes())
    assert result["document"]["kind"] == "image"
    hits = knowledge.search(
        "default", "Find the delivery note with pickup code 6583", 3
    )
    assert hits and hits[0].filename == image.name
    assert math.isfinite(hits[0].score)
    assert knowledge.asset("default", result["document"]["id"], True).data
    print(
        f"Real image embedding + OCR retrieval passed. Score: {hits[0].score}",
        flush=True,
    )

    image_vector = embedder.image(image.read_bytes())
    related = embedder.query("delivery note with pickup code")
    unrelated = embedder.query("tomato and scrambled egg recipe")
    visual_score = sum(a * b for a, b in zip(image_vector, related, strict=True))
    other_score = sum(a * b for a, b in zip(image_vector, unrelated, strict=True))
    assert visual_score > other_score
    print(
        f"Image-only semantic check passed ({len(image_vector)} dimensions): {visual_score:.4f} > {other_score:.4f}",
        flush=True,
    )
