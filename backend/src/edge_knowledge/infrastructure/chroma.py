import hashlib
import uuid
from pathlib import Path

import chromadb
from chromadb.config import Settings

from edge_knowledge.domain.models import AppError, Chunk, Document, Library, SearchHit
from edge_knowledge.domain.multimodal import ArchivedRecord


class ChromaKnowledgeRepository:
    def __init__(self, directory: Path, model_name: str):
        self.client = chromadb.PersistentClient(
            path=str(directory), settings=Settings(anonymized_telemetry=False)
        )
        self.model_name = model_name
        # Model-specific namespaces prevent mixing embeddings when the model is changed.
        self.prefix = "ek_" + hashlib.sha256(model_name.encode()).hexdigest()[:12] + "_"
        self.client.get_or_create_collection(
            name=self.prefix + "default",
            embedding_function=None,
            metadata={"display_name": "我的知识库", "embedding_model": model_name},
            configuration={"hnsw": {"space": "cosine"}},
        )

    def _collection(self, library_id: str):
        if library_id != "default":
            try:
                uuid.UUID(library_id)
            except ValueError as exc:
                raise AppError("知识库不存在。", 404, "library_not_found") from exc
        try:
            return self.client.get_collection(self.prefix + library_id, embedding_function=None)
        except chromadb.errors.NotFoundError as exc:
            raise AppError("知识库不存在。", 404, "library_not_found") from exc

    def libraries(self) -> list[Library]:
        return sorted(
            [
                Library(
                    collection.name.removeprefix(self.prefix),
                    (collection.metadata or {}).get("display_name", collection.name),
                    collection.count(),
                )
                for collection in self.client.list_collections()
                if collection.name.startswith(self.prefix)
            ],
            key=lambda item: item.id != "default",
        )

    def create_library(self, name: str) -> Library:
        library_id = str(uuid.uuid4())
        self.client.create_collection(
            name=self.prefix + library_id,
            embedding_function=None,
            metadata={"display_name": name, "embedding_model": self.model_name},
            configuration={"hnsw": {"space": "cosine"}},
        )
        return Library(library_id, name, 0)

    def documents(self, library_id: str) -> list[Document]:
        records = self._collection(library_id).get(include=["metadatas"])
        docs = {}
        for meta in records["metadatas"] or []:
            if meta:
                docs[meta["document_id"]] = Document(
                    meta["document_id"],
                    meta["filename"],
                    meta["chunks"],
                    meta["size"],
                    meta["created_at"],
                    meta.get("kind", "document"),
                    meta.get("media_type", "text/plain"),
                    meta.get("width", 0),
                    meta.get("height", 0),
                    meta.get("ocr_status", "not_applicable"),
                    meta.get("ocr_message", ""),
                    meta.get("duration", 0),
                    meta.get("assets", 0),
                    meta.get("source_path", ""),
                )
        return sorted(docs.values(), key=lambda item: item.created_at, reverse=True)

    def record(self, library_id: str, document_id: str) -> ArchivedRecord:
        records = self._collection(library_id).get(
            where={"document_id": document_id}, include=["documents", "metadatas", "embeddings"]
        )
        if not records["ids"]:
            raise AppError("资料不存在。", 404, "document_not_found")
        meta = records["metadatas"][0]
        document = Document(
            document_id,
            meta["filename"],
            meta["chunks"],
            meta["size"],
            meta["created_at"],
            meta.get("kind", "document"),
            meta.get("media_type", "text/plain"),
            meta.get("width", 0),
            meta.get("height", 0),
            meta.get("ocr_status", "not_applicable"),
            meta.get("ocr_message", ""),
            meta.get("duration", 0),
            meta.get("assets", 0),
            meta.get("source_path", ""),
        )
        rows = sorted(
            [
                (
                    Chunk(
                        text,
                        item["index"],
                        item["section"],
                        item.get("start", 0),
                        item.get("end", 0),
                    ),
                    vector.tolist(),
                )
                for text, item, vector in zip(
                    records["documents"], records["metadatas"], records["embeddings"], strict=True
                )
            ],
            key=lambda row: row[0].index,
        )
        return ArchivedRecord(document, [row[0] for row in rows], [row[1] for row in rows])

    def delete_many(self, library_id: str, document_ids: list[str]) -> None:
        if document_ids:
            self._collection(library_id).delete(where={"document_id": {"$in": document_ids}})

    def add(
        self,
        library_id: str,
        document: Document,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> None:
        collection = self._collection(library_id)
        if len(chunks) != len(embeddings):
            raise AppError("嵌入数量与文档切片不一致。", 500)
        try:
            for offset in range(0, len(chunks), 256):
                batch = chunks[offset : offset + 256]
                collection.add(
                    ids=[f"{document.id}:{chunk.index}" for chunk in batch],
                    documents=[chunk.text for chunk in batch],
                    embeddings=embeddings[offset : offset + 256],
                    metadatas=[
                        {
                            "document_id": document.id,
                            "filename": document.filename,
                            "chunks": document.chunks,
                            "size": document.size,
                            "created_at": document.created_at,
                            "section": chunk.section,
                            "index": chunk.index,
                            "kind": document.kind,
                            "media_type": document.media_type,
                            "width": document.width,
                            "height": document.height,
                            "ocr_status": document.ocr_status,
                            "ocr_message": document.ocr_message,
                            "duration": document.duration,
                            "assets": document.assets,
                            "source_path": document.source_path,
                            "start": chunk.start,
                            "end": chunk.end,
                        }
                        for chunk in batch
                    ],
                )
        except Exception:
            collection.delete(where={"document_id": document.id})
            raise

    def delete(self, library_id: str, document_id: str) -> None:
        collection = self._collection(library_id)
        if not collection.get(where={"document_id": document_id}, limit=1)["ids"]:
            raise AppError("文档不存在。", 404, "document_not_found")
        collection.delete(where={"document_id": document_id})

    def lexical_candidates(
        self,
        library_id: str,
        embedding: list[float],
        terms: list[str],
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[SearchHit]:
        # Chroma full-text filtering runs inside the current collection and reference scope.
        variants = list(
            dict.fromkeys(v for term in terms for v in (term, term.upper(), term.title()))
        )
        filters = [{"$contains": term} for term in variants]
        return self.search(
            library_id,
            embedding,
            top_k,
            document_ids,
            filters[0] if len(filters) == 1 else {"$or": filters},
        )

    def search(
        self,
        library_id: str,
        embedding: list[float],
        top_k: int,
        document_ids: list[str] | None = None,
        where_document: dict | None = None,
    ) -> list[SearchHit]:
        collection = self._collection(library_id)
        count = collection.count()
        if count == 0:
            return []
        result = collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k, count),
            include=["documents", "metadatas", "distances"],
            **({"where_document": where_document} if where_document else {}),
            **({"where": {"document_id": {"$in": document_ids}}} if document_ids else {}),
        )
        return [
            SearchHit(
                meta["document_id"],
                meta["filename"],
                text,
                meta["section"],
                meta["index"],
                round(max(-1.0, min(1.0, 1 - distance)), 4),
                meta.get("kind", "document"),
                meta.get("ocr_status", "not_applicable"),
                meta.get("start", 0),
                meta.get("end", 0),
            )
            for text, meta, distance in zip(
                result["documents"][0], result["metadatas"][0], result["distances"][0], strict=True
            )
        ]

    def chunks(self, library_id: str, document_id: str) -> list[Chunk]:
        records = self._collection(library_id).get(
            where={"document_id": document_id}, include=["documents", "metadatas"]
        )
        return sorted(
            [
                Chunk(
                    text, meta["index"], meta["section"], meta.get("start", 0), meta.get("end", 0)
                )
                for text, meta in zip(records["documents"], records["metadatas"], strict=True)
            ],
            key=lambda chunk: chunk.index,
        )

    def iter_vectors(self, library_id: str, document_ids: list[str]):
        """Paged, explicitly scoped vector reads; empty IDs never mean the full library."""
        collection = self._collection(library_id)
        for start in range(0, len(document_ids), 256):
            ids = document_ids[start : start + 256]
            offset = 0
            while True:
                result = collection.get(
                    where={"document_id": {"$in": ids}},
                    limit=500,
                    offset=offset,
                    include=["documents", "metadatas", "embeddings"],
                )
                if not result["ids"]:
                    break
                for text, meta, vector in zip(
                    result["documents"], result["metadatas"], result["embeddings"], strict=True
                ):
                    yield (
                        SearchHit(
                            meta["document_id"],
                            meta["filename"],
                            text,
                            meta["section"],
                            meta["index"],
                            0,
                            meta.get("kind", "document"),
                            meta.get("ocr_status", "not_applicable"),
                        ),
                        vector.tolist(),
                    )
                offset += len(result["ids"])

    def vectors(self, library_id: str) -> list[tuple[SearchHit, list[float]]]:
        collection = self._collection(library_id)
        if collection.count() > 10000:
            raise AppError("多模态精确检索一次最多 10000 个片段，请拆分知识库。", 413)
        result = collection.get(include=["documents", "metadatas", "embeddings"])
        if not result["ids"]:
            return []
        return [
            (
                SearchHit(
                    meta["document_id"],
                    meta["filename"],
                    text,
                    meta["section"],
                    meta["index"],
                    0,
                    meta.get("kind", "document"),
                    meta.get("ocr_status", "not_applicable"),
                    meta.get("start", 0),
                    meta.get("end", 0),
                ),
                vector.tolist(),
            )
            for text, meta, vector in zip(
                result["documents"], result["metadatas"], result["embeddings"], strict=True
            )
        ]

    def remove_library(self, library_id: str) -> None:
        if library_id == "default":
            raise AppError("默认知识库不能移除。", 409)
        collection = self._collection(library_id)
        self.client.delete_collection(collection.name)

    def snapshot(self, library_id: str) -> list[ArchivedRecord]:
        collection = self._collection(library_id)
        documents = {doc.id: doc for doc in self.documents(library_id)}
        grouped: dict[str, list[tuple[Chunk, list[float]]]] = {id: [] for id in documents}
        for offset in range(0, collection.count(), 500):
            records = collection.get(
                limit=500, offset=offset, include=["documents", "metadatas", "embeddings"]
            )
            for text, meta, vector in zip(
                records["documents"], records["metadatas"], records["embeddings"], strict=True
            ):
                grouped[meta["document_id"]].append(
                    (
                        Chunk(
                            text,
                            meta["index"],
                            meta["section"],
                            meta.get("start", 0),
                            meta.get("end", 0),
                        ),
                        vector.tolist(),
                    )
                )
        return [
            ArchivedRecord(
                documents[id],
                [pair[0] for pair in sorted(values, key=lambda pair: pair[0].index)],
                [pair[1] for pair in sorted(values, key=lambda pair: pair[0].index)],
            )
            for id, values in grouped.items()
        ]
