import hashlib
from dataclasses import asdict
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from edge_knowledge.domain.folders import SourceFile
from edge_knowledge.domain.models import AppError

from .knowledge import KnowledgeService
from .ports import SourceStore
from .semantic import AUDIO, VIDEO, SemanticService


class FolderService:
    def __init__(self, knowledge: KnowledgeService, semantic: SemanticService, store: SourceStore):
        self.knowledge, self.semantic, self.store = knowledge, semantic, store

    def _scope(self, library: str, source: str):
        try:
            if str(UUID(source)) != source:
                raise ValueError
        except ValueError as exc:
            raise AppError("文件夹来源无效。", 422) from exc
        self.knowledge.repository.documents(library)

    @staticmethod
    def validate_path(path: str):
        if (
            not path
            or len(path) > 1024
            or "\\" in path
            or "\0" in path
            or PurePosixPath(path).is_absolute()
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or ":" in path
        ):
            raise AppError("来源相对路径无效。", 422)

    def files(self, library: str, source: str):
        with self.knowledge.transaction():
            self._scope(library, source)
            return [asdict(entry) for entry in self.store.files(library, source)]

    def lease(self, library: str, source: str):
        with self.knowledge.transaction():
            self._scope(library, source)
            epoch, enabled = self.store.lease(library, source)
            return {"epoch": epoch, "enabled": enabled}

    def activate(self, library: str, source: str):
        with self.knowledge.transaction():
            self._scope(library, source)
            self.store.activate(library, source)
            return self.lease(library, source)

    def suspend_library(self, library: str):
        self.knowledge.repository.documents(library)
        self.store.suspend_library(library)

    def _check_lease(self, library: str, source: str, epoch: int):
        current, enabled = self.store.lease(library, source)
        if not enabled or current != epoch:
            raise AppError(
                "资料清空后文件夹同步已暂停，请重新开启自动同步。", 409, "folder_sync_paused"
            )

    def upsert(self, library: str, source: str, path: str, content: bytes, epoch: int = 0):
        self.validate_path(path)
        fingerprint = hashlib.sha256(content).hexdigest()
        with self.knowledge.transaction():
            self._scope(library, source)
            self._check_lease(library, source, epoch)
            old = self.store.get(library, source, path)
            if old and old.fingerprint == fingerprint:
                return {"changed": False, "document_id": old.document_id}
            # Every replacement is an immutable revision, including a return to older bytes.
            namespace = "folder:" + source + ":" + path + ":" + str(uuid4())
            if PurePosixPath(path).suffix.lower() in AUDIO | VIDEO:
                result = self.semantic.ingest(library, path, "", [(path, content)], namespace)
            else:
                result = self.knowledge.ingest(library, path, content, namespace)
            new_id = result["document"]["id"]
            archived_old = False
            try:
                if old and any(
                    d.id == old.document_id for d in self.knowledge.repository.documents(library)
                ):
                    self.semantic.archive_document(library, old.document_id)
                    archived_old = True
                self.store.put(library, source, SourceFile(path, fingerprint, new_id))
            except Exception:
                if archived_old:
                    self.semantic.restore_document(library, old.document_id)
                if not result["duplicate"]:
                    self.knowledge.delete(library, new_id)
                raise
            return {"changed": True, "document_id": new_id}

    def reconcile(self, library: str, source: str, paths: list[str], epoch: int = 0):
        if len(paths) > 10000 or len(set(paths)) != len(paths):
            raise AppError("扫描清单无效或超限。", 422)
        for path in paths:
            self.validate_path(path)
        with self.knowledge.transaction():
            self._scope(library, source)
            self._check_lease(library, source, epoch)
            present = set(paths)
            removed = 0
            for entry in self.store.files(library, source):
                if entry.path in present:
                    continue
                archived = any(
                    d.id == entry.document_id for d in self.knowledge.repository.documents(library)
                )
                if archived:
                    self.semantic.archive_document(library, entry.document_id)
                try:
                    self.store.remove(library, source, entry.path)
                except Exception:
                    if archived:
                        self.semantic.restore_document(library, entry.document_id)
                    raise
                removed += 1
            return {"removed": removed}
