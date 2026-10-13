"""A rebuildable catalogue mirrors immutable corpus records through ports."""

import hashlib
import json
from dataclasses import asdict
from pathlib import PurePosixPath

from edge_knowledge.domain.metadata import calendar_date, normalize_metadata, path_month
from edge_knowledge.domain.models import AppError, Document

from .ports import (
    AssetStore,
    DocumentCatalog,
    KnowledgeRepository,
    MetadataReader,
    PayloadStore,
    SourceStore,
)

INDEX_VERSION = 2


class CatalogMirror:
    def __init__(
        self,
        repository: KnowledgeRepository,
        catalog: DocumentCatalog,
        reader: MetadataReader,
        payloads: PayloadStore | None = None,
        sources: SourceStore | None = None,
        assets: AssetStore | None = None,
    ):
        self.repository, self.catalog, self.reader = repository, catalog, reader
        self.payloads, self.sources = payloads, sources
        self.assets = assets

    def _version(self, document: Document, path: str) -> str:
        return hashlib.sha256(
            json.dumps([INDEX_VERSION, asdict(document), path], sort_keys=True).encode()
        ).hexdigest()

    def refresh(self, library: str, document: Document, path: str = ""):
        path = document.source_path or path or document.filename
        text, complete = "", False
        if self.payloads:
            try:
                text = self.payloads.text(library, document.id)
                complete = True
            except AppError as exc:
                if exc.code != "payload_not_found":
                    raise
        if not complete and document.kind in {"document", "image", "bundle"}:
            chunks = self.repository.chunks(library, document.id)
            # Partial legacy inputs may supply metadata, but never full-text exact counts.
            text = chunks[0].text if chunks else ""
        if document.kind == "image" and document.ocr_status != "ready":
            text = ""
        if document.kind == "image" and self.assets:
            try:
                ocr = self.assets.recognition(library, document.id)
                text = ocr.text if ocr.status == "ready" else ""
                complete = ocr.status in {"ready", "empty"}
            except AppError as exc:
                if exc.code != "asset_not_found":
                    raise
                complete = False
        meta = normalize_metadata(self.reader.read(text) if document.kind == "document" else {})
        record = {
            **meta,
            "document_id": document.id,
            "filename": document.filename,
            "title": meta["title"] or document.filename,
            "path": path,
            "folder": str(PurePosixPath(path).parent),
            "extension": PurePosixPath(document.filename).suffix.lower(),
            "kind": document.kind,
            "size": document.size,
            "duration": document.duration,
            "chunks": document.chunks,
            "imported_date": calendar_date(document.created_at),
            "imported_at": document.created_at,
            "folder_month": path_month(path),
            "text_complete": complete,
            "ocr_status": document.ocr_status,
        }
        self.catalog.upsert(library, document.id, self._version(document, path), record, text)

    def ensure(self, library: str, documents: list[Document]):
        paths = self.sources.paths(library) if self.sources else {}
        versions = self.catalog.versions(library)
        for document in documents:
            path = document.source_path or paths.get(document.id, document.filename)
            if versions.get(document.id) != self._version(document, path):
                self.refresh(library, document, path)
        self.catalog.prune(library, [doc.id for doc in documents])


class IndexedKnowledgeRepository:
    """Every corpus writer—including backup restore—uses the same mutation boundary."""

    def __init__(self, repository: KnowledgeRepository, mirror: CatalogMirror):
        self.repository, self.mirror = repository, mirror

    def __getattr__(self, name):
        return getattr(self.repository, name)

    def add(self, library, document, chunks, embeddings):
        existed = any(doc.id == document.id for doc in self.repository.documents(library))
        self.repository.add(library, document, chunks, embeddings)
        try:
            self.mirror.refresh(library, document)
        except Exception:
            if not existed:
                self.repository.delete(library, document.id)
                self.mirror.catalog.delete(library, [document.id])
            raise

    def delete(self, library, document):
        self.repository.delete(library, document)
        self.mirror.catalog.delete(library, [document])

    def delete_many(self, library, documents):
        self.repository.delete_many(library, documents)
        self.mirror.catalog.delete(library, documents)

    def remove_library(self, library):
        self.repository.remove_library(library)
        self.mirror.catalog.prune(library, [])
