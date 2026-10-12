"""Portable corpus backups; restore into new libraries and leave originals intact."""

from dataclasses import asdict

from edge_knowledge.domain.backup import BackupItem, BackupLibrary, BackupSnapshot
from edge_knowledge.domain.models import AppError

from .knowledge import KnowledgeService
from .ports import ArchiveStore, BackupCodec


class BackupService:
    def __init__(
        self,
        knowledge: KnowledgeService,
        archive: ArchiveStore,
        codec: BackupCodec,
        model: str,
        dimension: int = 768,
    ):
        self.knowledge, self.archive, self.codec = knowledge, archive, codec
        self.model, self.dimension = model, dimension

    def _item(self, library: str, record, archived: bool) -> BackupItem:
        image, ocr, payload = None, None, None
        if record.document.kind == "image":
            if not self.knowledge.images:
                raise AppError("图片存储不可用。", 503)
            image, ocr = self.knowledge.images.assets.snapshot(library, record.document.id)
        if self.knowledge.payloads:
            try:
                payload = self.knowledge.payloads.get(library, record.document.id)
            except AppError as exc:
                if exc.status != 404 or record.document.kind in {"audio", "video", "bundle"}:
                    raise
        return BackupItem(record, archived, image, ocr, payload)

    def export(self, frontend: dict) -> bytes:
        with self.knowledge.transaction():
            libraries = []
            for library in self.knowledge.repository.libraries():
                records = self.knowledge.repository.snapshot(library.id)
                active = [self._item(library.id, record, False) for record in records]
                archived = [
                    self._item(library.id, self.archive.get(library.id, doc.id), True)
                    for doc in self.archive.list(library.id)
                ]
                libraries.append(BackupLibrary(library, active + archived))
            return self.codec.encode(
                BackupSnapshot(self.model, self.dimension, libraries, frontend)
            )

    def inspect(self, content: bytes) -> dict:
        snapshot = self.codec.decode(content)
        return {
            "model": snapshot.model,
            "compatible": snapshot.model == self.model and snapshot.dimension == self.dimension,
            "libraries": len(snapshot.libraries),
            "documents": sum(len(group.items) for group in snapshot.libraries),
            "archived": sum(item.archived for group in snapshot.libraries for item in group.items),
            "missing_originals": sum(
                item.record.document.kind == "document" and item.payload is None
                for group in snapshot.libraries
                for item in group.items
            ),
            "frontend": snapshot.frontend,
        }

    def restore(self, content: bytes) -> dict:
        snapshot = self.codec.decode(content)
        if snapshot.model != self.model or snapshot.dimension != self.dimension:
            raise AppError(
                "备份的嵌入模型或向量维度与当前应用不一致。", 409, "backup_model_mismatch"
            )
        with self.knowledge.transaction():
            created, mapping, installed = [], {}, []
            try:
                for group in snapshot.libraries:
                    library = self.knowledge.repository.create_library(
                        group.library.name[:48] + "（恢复副本）"
                    )
                    created.append(library)
                    mapping[group.library.id] = library.id
                    for item in group.items:
                        record, id = item.record, item.record.document.id
                        installed.append((library.id, id))
                        if item.image and item.ocr:
                            if not self.knowledge.images:
                                raise AppError("图片存储不可用。", 503)
                            self.knowledge.images.assets.put(library.id, id, item.image, item.ocr)
                        if item.payload is not None:
                            if not self.knowledge.payloads:
                                raise AppError("原件存储不可用。", 503)
                            self.knowledge.payloads.put(library.id, id, *item.payload)
                        if item.archived:
                            self.archive.put(library.id, record)
                        else:
                            self.knowledge.repository.add(
                                library.id, record.document, record.chunks, record.vectors
                            )
                return {
                    "libraries": [
                        asdict(library)
                        for library in self.knowledge.repository.libraries()
                        if library.id in mapping.values()
                    ],
                    "mapping": mapping,
                    "frontend": snapshot.frontend,
                }
            except Exception:
                for library, id in installed:
                    if self.knowledge.images:
                        self.knowledge.images.assets.delete(library, id)
                    if self.knowledge.payloads:
                        self.knowledge.payloads.delete(library, id)
                    self.archive.delete(library, id)
                for library in created:
                    self.knowledge.repository.remove_library(library.id)
                raise
