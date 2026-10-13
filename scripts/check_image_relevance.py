"""Real-model image relevance acceptance in temporary storage; never print OCR contents."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from edge_knowledge.application.images import ImageService
from edge_knowledge.application.knowledge import KnowledgeService
from edge_knowledge.application.semantic import SemanticService
from edge_knowledge.infrastructure.assets import FileAssetStore
from edge_knowledge.infrastructure.chroma import ChromaKnowledgeRepository
from edge_knowledge.infrastructure.embedding import SentenceTransformerEmbedder
from edge_knowledge.infrastructure.images import PillowImageProcessor
from edge_knowledge.infrastructure.media import AVMediaDecoder
from edge_knowledge.infrastructure.ocr import LocalOCR
from edge_knowledge.infrastructure.parsers import FileDocumentParser
from edge_knowledge.infrastructure.payloads import FilePayloadStore
from edge_knowledge.infrastructure.settings import JsonSettingsStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument(
        "--expect", required=True, help="Expected single image filename"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    images = sorted(
        path
        for path in args.images.iterdir()
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    )
    if not 2 <= len(images) <= 50 or args.expect not in {path.name for path in images}:
        parser.error("Provide 2–50 images including the expected filename.")
    project = Path(__file__).resolve().parents[1]
    model = "google/embeddinggemma-2"
    embedder = SentenceTransformerEmbedder(
        model, True, prepared_path=project / "data/models/embeddinggemma-2"
    )
    with TemporaryDirectory(prefix="edge-image-relevance-") as directory:
        root = Path(directory)
        repo = ChromaKnowledgeRepository(root / "chroma", model)
        payloads = FilePayloadStore(root / "payloads")
        knowledge = KnowledgeService(
            FileDocumentParser(),
            embedder,
            repo,
            JsonSettingsStore(root),
            ImageService(
                PillowImageProcessor(),
                LocalOCR(),
                FileAssetStore(root / "assets"),
            ),
            payloads,
        )
        semantic = SemanticService(knowledge, embedder, AVMediaDecoder(), payloads)
        for path in images:
            knowledge.ingest("default", path.name, path.read_bytes())
        report = {
            "query": args.query,
            "expected": args.expect,
            "corpus_size": len(images),
            "cases": {},
        }
        for mode in ("broad", "auto", "image_text"):
            result = semantic.search(
                "default", args.query, [], 50, [], ["image"], "search", 768, mode
            )
            names = [row["filename"] for row in result["sources"]]
            if mode != "broad":
                assert names == [args.expect], f"{mode}: expected the title image only"
            report["cases"][mode] = {
                "hits": [
                    {"filename": row["filename"], "score": row["score"]}
                    for row in result["sources"]
                ],
                "relevance": result["relevance"],
            }
        missing = semantic.search(
            "default",
            "unlisted_title_987654321",
            [],
            50,
            [],
            ["image"],
            "search",
            768,
            "image_text",
        )
        assert not missing["sources"]
        reference = next(path for path in images if path.name == args.expect)
        visual = semantic.search(
            "default",
            "",
            [(reference.name, reference.read_bytes())],
            10,
            [],
            ["image"],
            "search",
            768,
        )
        assert (
            visual["sources"][0]["filename"] == args.expect
            and visual["sources"][0]["score"] > 0.99
        )
        report["missing_title_returns_empty"] = True
        report["image_reference_retrieval_passed"] = True
        serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(serialized)
        print(serialized)


if __name__ == "__main__":
    main()
