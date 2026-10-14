"""Resolve document identities before reading immutable originals through ports."""

from dataclasses import replace

from edge_knowledge.domain.models import SearchHit
from edge_knowledge.domain.query import QuerySpec

from .catalog import CatalogMirror
from .knowledge import KnowledgeService


class DocumentReading:
    def __init__(self, knowledge: KnowledgeService, catalog: CatalogMirror):
        self.knowledge, self.catalog = knowledge, catalog

    def source(self, library: str, document: str) -> SearchHit:
        with self.knowledge.transaction():
            source = self.knowledge.read_document(library, document)
            self.catalog.ensure(library, self.knowledge.repository.documents(library))
            rows = self.catalog.catalog.query(library, QuerySpec("list", limit=1), [document])[
                "rows"
            ]
            if rows:
                source = replace(source, section=rows[0]["title"], path=rows[0]["path"])
            return source

    def read(self, library: str, rows: list[dict], total: int) -> dict:
        if total != 1:
            return {
                "kind": "clarification",
                "sources": [
                    SearchHit(
                        row["document_id"],
                        row["filename"],
                        "",
                        row["title"],
                        0,
                        0,
                        path=row["path"],
                    )
                    for row in rows[:10]
                ],
                "content": "没有匹配的完整资料，请调整范围。"
                if not total
                else "匹配到多份资料，请点击“阅读全文”选择要读取的一份。",
                "notice": "未猜测当前资料，未调用生成模型。",
            }
        source = self.source(library, rows[0]["document_id"])
        return {
            "kind": "retrieval",
            "sources": [source],
            "content": "已打开文章，下面是保存的完整原文。",
            "notice": "从本机保存的原文读取完整资料，不使用检索片段拼接。",
        }
