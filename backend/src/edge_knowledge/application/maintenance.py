from edge_knowledge.domain.models import AppError

from .folders import FolderService
from .knowledge import KnowledgeService
from .ports import ArchiveStore


class LibraryMaintenance:
    """Recoverable corpus operations; originals and other libraries are never touched."""

    def __init__(
        self,
        knowledge: KnowledgeService,
        archive: ArchiveStore,
        folders: FolderService | None = None,
    ):
        self.knowledge, self.archive, self.folders = knowledge, archive, folders

    def archive_documents(self, library: str, ids: list[str], all_documents: bool = False):
        with self.knowledge.transaction():
            active = {doc.id: doc for doc in self.knowledge.repository.documents(library)}
            selected = list(active) if all_documents else ids
            if not set(selected) <= active.keys():
                raise AppError("部分资料已改变或不属于此知识库，请刷新后重试。", 409)
            if len(selected) > 10000:
                raise AppError("单次最多处理 10000 份资料，请分批选择。", 413)
            if all_documents and self.folders:
                # Reject late file submissions, including those already queued before pause.
                self.folders.suspend_library(library)
            previous = {doc.id for doc in self.archive.list(library)}
            saved_previous = {
                id: self.archive.get(library, id) for id in selected if id in previous
            }
            staged = []
            try:
                for id in selected:
                    staged.append(id)
                    self.archive.put(library, self.knowledge.repository.record(library, id))
                self.knowledge.repository.delete_many(library, selected)
            except Exception as exc:
                failed = False
                current = {doc.id for doc in self.knowledge.repository.documents(library)}
                for id in staged:
                    try:
                        if id not in current:
                            record = self.archive.get(library, id)
                            self.knowledge.repository.add(
                                library, record.document, record.chunks, record.vectors
                            )
                        if id in saved_previous:
                            self.archive.put(library, saved_previous[id])
                        else:
                            self.archive.delete(library, id)
                    except Exception:
                        failed = True
                raise AppError(
                    "批量移入失败，部分资料需要检查回收站。"
                    if failed
                    else "批量移入失败，原有资料已保留，请重试。",
                    500,
                    "batch_archive_failed",
                ) from exc
            return {
                "archived": len(selected),
                "document_ids": selected,
                "folder_sync_paused": all_documents,
            }

    def restore_documents(self, library: str, ids: list[str]):
        with self.knowledge.transaction():
            active = {doc.id for doc in self.knowledge.repository.documents(library)}
            archived = {doc.id for doc in self.archive.list(library)}
            if not set(ids) <= active | archived:
                raise AppError("部分回收站资料不存在，请刷新后重试。", 409)
            added, removed = [], []
            try:
                for id in ids:
                    if id not in active:
                        record = self.archive.get(library, id)
                        added.append(id)
                        self.knowledge.repository.add(
                            library, record.document, record.chunks, record.vectors
                        )
                for id in ids:
                    if id in archived:
                        removed.append(id)
                        self.archive.delete(library, id)
            except Exception as exc:
                failed = False
                for id in removed:
                    try:
                        self.archive.put(library, self.knowledge.repository.record(library, id))
                    except Exception:
                        failed = True
                # Keep successfully restored copies if the archive cannot be repaired.
                if not failed:
                    self.knowledge.repository.delete_many(library, added)
                raise AppError(
                    "恢复未完成，请检查资料列表与回收站后重试。", 500, "batch_restore_failed"
                ) from exc
            return {"restored": len(ids)}
