import hashlib
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import PurePosixPath
from threading import RLock

from edge_knowledge.domain.chunking import split_document
from edge_knowledge.domain.models import AppError, Asset, Chunk, Document, SearchHit
from edge_knowledge.domain.multimodal import InputAsset
from edge_knowledge.domain.retrieval import anchors, rank_hits, retrieval_text, terms

from .images import IMAGE_SUFFIXES, ImageService
from .ports import DocumentParser, Embedder, KnowledgeRepository, PayloadStore, SettingsStore


class KnowledgeService:
    def __init__(
        self,
        parser: DocumentParser,
        embedder: Embedder,
        repository: KnowledgeRepository,
        settings: SettingsStore,
        images: ImageService | None = None,
        payloads: PayloadStore | None = None,
    ):
        self.parser, self.embedder = parser, embedder
        self.repository, self.settings = repository, settings
        self.images = images
        self.payloads = payloads
        self._lock = RLock()

    @contextmanager
    def transaction(self):
        """Coordinate corpus changes and source reads across application use cases."""
        with self._lock:
            yield

    def ingest(self, library_id: str, filename: str, content: bytes, namespace: str = "") -> dict:
        filename = PurePosixPath(filename.replace("\\", "/")).name
        if not filename or len(filename) > 255:
            raise AppError("文件名不合法。")
        if not content:
            raise AppError("不能导入空文件。")
        if len(content) > 20 * 1024 * 1024:
            raise AppError("单个文件不能超过 20 MB。", 413, "file_too_large")
        identity = namespace.encode() + b"\0" if namespace else b""
        doc_id = hashlib.sha256(identity + filename.encode() + b"\0" + content).hexdigest()
        with self._lock:
            existing = self.repository.documents(library_id)
            for doc in existing:
                if doc.id == doc_id:
                    return {"document": asdict(doc), "duplicate": True}
            config = self.settings.read()
            if PurePosixPath(filename).suffix.lower() in IMAGE_SUFFIXES:
                return self._ingest_image(library_id, doc_id, filename, content, config)
            text = self.parser.parse(filename, content)
            chunks = split_document(text, config["chunk_size"], config["chunk_overlap"])
            if len(chunks) > 10_000:
                raise AppError("文档切片过多，请拆分文档后再导入。")
            if hasattr(self.embedder, "split_text"):
                chunks = [
                    Chunk(part, index, chunk.section)
                    for index, (chunk, part) in enumerate(
                        (chunk, part)
                        for chunk in chunks
                        for part in self.embedder.split_text(chunk.text)
                    )
                ]
            embeddings = self.embedder.documents([chunk.text for chunk in chunks])
            document = Document(
                doc_id, filename, len(chunks), len(content), datetime.now(UTC).isoformat()
            )
            if self.payloads:
                self.payloads.put(
                    library_id, doc_id, text, [InputAsset(filename, "document", content)]
                )
            try:
                self.repository.add(library_id, document, chunks, embeddings)
            except Exception:
                if self.payloads:
                    self.payloads.delete(library_id, doc_id)
                raise
            return {"document": asdict(document), "duplicate": False}

    def _ingest_image(
        self, library_id: str, doc_id: str, filename: str, content: bytes, config: dict
    ) -> dict:
        if not self.images:
            raise AppError("图片处理能力未配置。", 503, "image_unavailable")
        image, ocr = self.images.prepare(content)
        chunks = [Chunk(ocr.text[:12000] or f"图片：{filename}", 0, "图片")]
        embeddings = [self.embedder.image(image.data)]
        if ocr.status == "ready" and ocr.text.strip():
            text_chunks = split_document(ocr.text, config["chunk_size"], config["chunk_overlap"])
            if len(text_chunks) > 1000:
                raise AppError("图片中文字过多，请拆分后再导入。")
            chunks.extend(Chunk(item.text, item.index + 1, "图片文字") for item in text_chunks)
            embeddings.extend(self.embedder.documents([item.text for item in text_chunks]))
        document = Document(
            doc_id,
            filename,
            len(chunks),
            len(content),
            datetime.now(UTC).isoformat(),
            "image",
            image.media_type,
            image.width,
            image.height,
            ocr.status,
            ocr.message,
        )
        self.images.assets.put(library_id, doc_id, image, ocr)
        try:
            self.repository.add(library_id, document, chunks, embeddings)
        except Exception:
            self.images.assets.delete(library_id, doc_id)
            raise
        return {"document": asdict(document), "duplicate": False}

    def delete(self, library_id: str, document_id: str) -> None:
        with self._lock:
            self.repository.delete(library_id, document_id)
            if self.images:
                self.images.assets.delete(library_id, document_id)
            if self.payloads:
                self.payloads.delete(library_id, document_id)

    def search(
        self,
        library_id: str,
        question: str,
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[SearchHit]:
        with self._lock:
            documents = self.repository.documents(library_id)
            if document_ids and not set(document_ids) <= {doc.id for doc in documents}:
                raise AppError(
                    "引用资料已删除或不属于当前知识库，请重新选择。", 404, "reference_not_found"
                )
            if not documents:
                return []
            vector = self.embedder.query(retrieval_text(question))
            candidate_limit = min(100, max(40, top_k * 5))
            hits = self.repository.search(library_id, vector, candidate_limit, document_ids)
            words = anchors(question) or terms(question)
            if words:
                hits += self.repository.lexical_candidates(
                    library_id, vector, words, candidate_limit, document_ids
                )
            return rank_hits(question, hits, top_k, self.settings.read()["min_score"])

    def asset(self, library_id: str, document_id: str, thumbnail: bool = False) -> Asset:
        with self._lock:
            documents = self.repository.documents(library_id)
            if not any(doc.id == document_id and doc.kind == "image" for doc in documents):
                raise AppError("图片不存在。", 404, "asset_not_found")
            if not self.images:
                raise AppError("图片处理能力未配置。", 503)
            return self.images.assets.get(library_id, document_id, thumbnail)

    def extract_image_text(self, content: bytes) -> dict:
        if not self.images:
            raise AppError("图片处理能力未配置。", 503)
        image, ocr = self.images.prepare(content)
        return {**asdict(ocr), "width": image.width, "height": image.height}
