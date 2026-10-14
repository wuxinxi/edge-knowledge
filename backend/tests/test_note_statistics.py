import json
from dataclasses import replace
from datetime import date

import pytest

from edge_knowledge.domain.metadata import (
    calendar_date,
    path_month,
)
from edge_knowledge.domain.query_parser import local_plan
from edge_knowledge.infrastructure.metadata import YAMLMetadataReader

frontmatter = YAMLMetadataReader().read

QUESTION = "帮我查一下我 2026 年 9 月份写了多少篇笔记"


def ingest(client, name, metadata):
    response = client.post(
        "/api/libraries/default/documents",
        files={"file": (name, (f"---\n{metadata}\n---\n\n# 笔记\n正文。" * 2).encode())},
    )
    assert response.status_code == 201
    return response.json()["document"]["id"]


def test_month_count_answers_the_question_without_embeddings_or_cloud(system):
    client, knowledge, _, generator = system
    for i in range(12):
        ingest(client, f"note-{i}.md", "createdAt: 2026-09-15\nupdatedAt: 2026-10-07")
    ingest(client, "other.md", "createdAt: 2026-08-15\nupdatedAt: 2026-09-03")
    ingest(client, "unknown.md", "updatedAt: 2026-09-03")
    client.patch("/api/settings", json={"api_key": "configured-test-key"})
    response = client.post("/api/query", json={"question": QUESTION, "top_k": 1})
    assert response.status_code == 200
    events = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    answer = "".join(event.get("delta", "") for event in events)
    assert "12 篇" in answer
    assert "1 篇" in answer and "无法确认" in answer
    assert {"type": "execution", "location": "local", "result_kind": "catalog"} in events
    assert generator.calls == 0
    knowledge.embedder.query = lambda _: (_ for _ in ()).throw(AssertionError("vector search"))
    client.patch("/api/settings", json={"api_key": ""})
    result = client.post("/api/local-query", json={"question": QUESTION, "top_k": 1})
    assert result.status_code == 200 and "12 篇" in result.json()["content"]
    assert len(result.json()["sources"]) == 12
    assert generator.calls == 0
    response = client.post("/api/query", json={"question": QUESTION, "top_k": 1})
    assert response.status_code == 200 and "12 篇" in response.text
    assert generator.calls == 0


def test_counts_are_document_scoped_not_chunks_and_isolated_by_library_and_reference(system):
    client, knowledge, _, generator = system
    a = ingest(client, "a.md", "created: 2026-09-01")
    ingest(client, "b.md", "date: 2026-09-02")
    other = knowledge.repository.create_library("另一资料库").id
    knowledge.ingest(other, "private.md", b"---\ncreated: 2026-09-01\n---\nOther")
    result = client.post("/api/local-query", json={"question": QUESTION, "document_ids": [a]})
    assert "1 篇" in result.json()["content"]
    assert {row["document_id"] for row in result.json()["sources"]} == {a}
    assert (
        client.post(
            "/api/local-query",
            json={"question": QUESTION, "library_id": other, "document_ids": [a]},
        ).status_code
        == 404
    )
    assert generator.calls == 0


def test_missing_authored_dates_do_not_become_import_or_update_dates(system):
    client, knowledge, _, _ = system
    knowledge.ingest(
        "default",
        "index.md",
        b"---\nupdatedAt: 2026-10-07\n---\nNote",
        source_path="2026-09/topic/index.md",
    )
    result = client.post("/api/local-query", json={"question": QUESTION}).json()
    assert "无法确认" in result["content"] and "归档" in result["content"]
    assert "1 篇" in result["content"]
    assert "匹配 **1 篇**" not in result["content"]
    assert "目录/文件名月份" in result["sources"][0]["section"]
    modified = client.post(
        "/api/local-query", json={"question": "2026 年 10 月修改了多少篇笔记"}
    ).json()
    assert "修改日期" in modified["content"] and "匹配 **1 篇**" in modified["content"]


def test_preview_limit_never_limits_the_complete_count(system):
    client, _, _, _ = system
    for i in range(23):
        ingest(client, f"note-{i}.md", "createdAt: 2026-09-15")
    result = client.post("/api/local-query", json={"question": QUESTION, "top_k": 1}).json()
    assert "23 篇" in result["content"] and "前 20" in result["content"]
    assert len(result["sources"]) == 20


def test_import_dates_are_used_only_for_explicit_import_counts_and_deleted_docs_are_excluded(
    system,
):
    client, knowledge, _, _ = system
    document = ingest(client, "note.md", "created: 2026-08-01")
    record = knowledge.repository.record("default", document)
    knowledge.repository.delete("default", document)
    knowledge.repository.add(
        "default",
        replace(record.document, created_at="2026-09-15T10:00:00Z"),
        record.chunks,
        record.vectors,
    )
    body = {"question": "2026 年 9 月导入了多少篇笔记"}
    assert "匹配 **1 篇**" in client.post("/api/local-query", json=body).json()["content"]
    assert (
        "匹配 **0 篇**"
        in client.post("/api/local-query", json={"question": QUESTION}).json()["content"]
    )
    knowledge.delete("default", document)
    assert "匹配 **0 篇**" in client.post("/api/local-query", json=body).json()["content"]


@pytest.mark.parametrize(
    "question",
    [
        "9 月写了多少篇笔记",
        "2026 年 13 月写了多少篇笔记",
        "2026 年 9 月写了多少篇 Python 笔记",
        "2026 年 9 月 3 日写了多少篇笔记",
        "2026 年 9 月和 10 月写了多少篇笔记",
    ],
)
def test_ambiguous_or_unsupported_statistics_do_not_silently_count_the_wrong_scope(
    system, question
):
    client, knowledge, _, generator = system
    knowledge.embedder.query = lambda _: (_ for _ in ()).throw(AssertionError("vector search"))
    response = client.post("/api/local-query", json={"question": question})
    assert response.status_code == 200 and not response.json()["sources"]
    assert "匹配" not in response.json()["content"]
    assert generator.calls == 0


def test_metadata_and_path_dates_are_validated_without_reading_body_mentions():
    fields = frontmatter(
        '---\ncreated_at: "2026-09-15T09:00:00+08:00"\n'
        "updatedAt: 2026-10-07\n---\ncreated: 2026-09-20"
    )
    assert calendar_date(fields["created_at"]) == "2026-09-15"
    assert "created" not in fields
    assert calendar_date("2026-02-30") is None
    assert not frontmatter("---\ncreated: 2026-09-01")
    assert not frontmatter("---\ncreated: 2026-09-01\ncreated: 2026-10-01\n---")
    assert path_month("2026-09/topic/index.md") == "2026-09"
    assert path_month("2026-09/2026-10/note.md") is None
    assert (
        local_plan("帮我查询资料里的地址和用户名是多少", date(2026, 10, 13)).operation == "search"
    )
