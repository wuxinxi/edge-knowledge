"""Generic read and evidence-scope contracts, independent of request phrasing."""

import json
from dataclasses import asdict

import pytest

from edge_knowledge.domain.models import AppError
from edge_knowledge.domain.query import QuerySpec


def article(knowledge, title="工程实践说明", name="index.md"):
    text = (
        f"---\ntitle: {title}\n---\n\n# {title}\n\n"
        + "\n\n".join(f"## 第{n}节\n" + f"第{n}节独立内容。" * 100 for n in range(8))
        + "\n\n## 最后章节\n全文结尾验收标记。"
    )
    document = knowledge.ingest("default", name, text.encode())["document"]
    return document["id"], text


class Planner:
    def __init__(self, output):
        self.output, self.contexts = output, []

    def plan(self, question, context):
        self.contexts.append(context)
        return self.output


@pytest.mark.parametrize(
    "question", ["给我看完整说明", "打开这份资料", "全文浏览", "换一种表达也应读取全文"]
)
def test_read_plan_returns_all_saved_text_regardless_of_question(system, monkeypatch, question):
    _, knowledge, chat, generator = system
    id, text = article(knowledge)
    monkeypatch.setattr(knowledge.embedder, "query", lambda *_: pytest.fail("read must not embed"))
    result = chat.local_query(
        "default", question, document_ids=[id], query_plan={"operation": "read"}
    )
    assert len(result["sources"]) == 1 and result["sources"][0].text == text
    assert result["sources"][0].content_scope == "full_document" and generator.calls == 0


def test_read_by_title_contract_is_independent_of_any_specific_title(system):
    _, knowledge, chat, _ = system
    for title, name in [
        ("项目部署流程", "deployment.md"),
        ("每周采购清单", "shopping.md"),
        ("会议纪要", "meeting.md"),
    ]:
        id, text = article(knowledge, title, name)
        result = chat.local_query(
            "default",
            "任意界面请求",
            query_plan={
                "operation": "read",
                "where": {"field": "title", "op": "eq", "value": title},
            },
        )
        assert result["sources"][0].document_id == id and result["sources"][0].text == text


def test_natural_language_planner_can_select_read_tool(system, monkeypatch):
    _, knowledge, chat, _ = system
    _, text = article(knowledge, "项目部署说明")
    planner = chat.queries.local_planner = Planner(
        {"operation": "read", "text_query": "项目部署说明"}
    )
    monkeypatch.setattr(knowledge.embedder, "query", lambda *_: pytest.fail("read must not embed"))
    result = chat.local_query("default", "把部署说明完整展开给我")
    assert result["sources"][0].text == text and planner.contexts


def test_read_requires_identity_resolution_not_first_semantic_hit(system):
    _, knowledge, chat, _ = system
    first, _ = article(knowledge, "项目部署", "first.md")
    article(knowledge, "项目部署补充", "second.md")
    result = chat.local_query(
        "default", "阅读", query_plan={"operation": "read", "text_query": "项目部署"}
    )
    assert result["kind"] == "clarification" and len(result["sources"]) == 2
    selected = chat.local_query(
        "default", "阅读全文", document_ids=[first], query_plan={"operation": "read"}
    )
    assert [h.document_id for h in selected["sources"]] == [first]


@pytest.mark.parametrize(
    "question", ["总结它", "列出步骤", "改写成清单", "做个对比", "不用“总结”关键词也应获得全文"]
)
def test_answer_full_scope_uses_all_original_text(system, monkeypatch, question):
    _, knowledge, chat, _ = system
    id, text = article(knowledge)
    monkeypatch.setattr(
        knowledge.embedder, "query", lambda *_: pytest.fail("full answer must not embed")
    )
    plan = chat.prepare(
        "default",
        question,
        document_ids=[id],
        query_plan={"operation": "answer", "source_scope": "full_document"},
        allow_planning=True,
        local_generation_only=True,
    )
    assert text in plan.prompt and plan.local_answer is None and plan.provider == "local"


def test_context_is_a_hint_and_only_plan_can_activate_its_scope(system, monkeypatch):
    _, knowledge, chat, _ = system
    first, text = article(knowledge, "部署说明", "first.md")
    second, _ = article(knowledge, "采购清单", "second.md")
    planner = chat.queries.local_planner = Planner(
        {"operation": "answer", "use_context": True, "source_scope": "full_document"}
    )
    config = knowledge.settings.read()
    config["generation_provider"] = "local"
    monkeypatch.setattr(knowledge.settings, "read", lambda: config)
    plan = chat.prepare(
        "default",
        "列个重点清单",
        context_document_ids=[first],
        allow_planning=True,
        local_generation_only=True,
        lookup_mode=True,
    )
    assert [h.document_id for h in plan.sources] == [first] and text in plan.prompt
    current = planner.contexts[-1]["current_documents"]
    assert [row["document_id"] for row in current] == [first]
    assert all("body" not in row for row in current)
    planner.output = {
        "operation": "answer",
        "where": {"field": "title", "op": "eq", "value": "采购清单"},
        "source_scope": "full_document",
        "use_context": False,
    }
    plan = chat.prepare(
        "default",
        "新话题",
        context_document_ids=[first],
        allow_planning=True,
        local_generation_only=True,
        lookup_mode=True,
    )
    assert [h.document_id for h in plan.sources] == [second]


def test_missing_context_and_scope_conflicts_fail_closed(system):
    _, knowledge, chat, _ = system
    first, _ = article(knowledge, "one", "first.md")
    second, _ = article(knowledge, "two", "second.md")
    result = chat.queries.resolve(
        "default", "这份资料", explicit={"operation": "read", "use_context": True}
    )
    assert result["kind"] == "clarification" and result["sources"] == []
    with pytest.raises(AppError) as error:
        chat.prepare(
            "default",
            "上下文",
            document_ids=[first],
            context_document_ids=[second],
            query_plan={"operation": "answer", "use_context": True},
            allow_planning=True,
        )
    assert error.value.code == "context_scope_conflict"


def test_missing_original_is_not_reconstructed_from_overlapping_chunks(system):
    client, knowledge, _, _ = system
    id, _ = article(knowledge)
    knowledge.payloads.delete("default", id)
    result = client.post(
        "/api/local-query",
        json={"question": "read", "document_ids": [id], "query_plan": {"operation": "read"}},
    )
    assert result.status_code == 409 and result.json()["error"]["code"] == "original_missing"


def test_read_and_context_membership_are_checked_before_original_access(system, monkeypatch):
    client, knowledge, _, _ = system
    id, _ = article(knowledge)
    other = knowledge.repository.create_library("other").id
    monkeypatch.setattr(
        knowledge.payloads, "text", lambda *_: pytest.fail("must not read outside scope")
    )
    for fields in [{"document_ids": [id]}, {"context_document_ids": [id]}]:
        result = client.post(
            "/api/query",
            json={
                "library_id": other,
                "question": "read",
                "query_plan": {"operation": "read"},
                **fields,
            },
        )
        assert result.status_code == 404 and result.json()["error"]["code"] == "reference_not_found"


@pytest.mark.parametrize("progress", [False, True])
def test_local_execution_policy_does_not_depend_on_selected_cloud_provider(
    system, monkeypatch, progress
):
    client, knowledge, _, _ = system
    id, _ = article(knowledge)
    config = knowledge.settings.read()
    monkeypatch.setattr(
        knowledge.settings, "api_key", lambda: pytest.fail("must not read cloud key")
    )
    monkeypatch.setattr(knowledge.settings, "read", lambda: config)
    result = client.post(
        "/api/query",
        json={
            "question": "全文解读",
            "document_ids": [id],
            "query_plan": {"operation": "answer", "source_scope": "full_document"},
            "allow_planning": True,
            "local_generation_only": True,
            "progress": progress,
        },
    )
    events = [
        json.loads(line[6:]) for line in result.text.splitlines() if line.startswith("data: ")
    ]
    assert any(event.get("generator") == "local" for event in events)
    assert not any(event["type"] == "error" for event in events)


def test_full_text_survives_device_snapshot(system, tmp_path):
    from edge_knowledge.api.conversations import ConversationSnapshot
    from edge_knowledge.infrastructure.conversations import SQLiteConversationStore

    _, knowledge, chat, _ = system
    id, text = article(knowledge)
    source = asdict(chat.queries.reading.source("default", id))
    snapshot = ConversationSnapshot.model_validate(
        {
            "version": 1,
            "revision": 0,
            "active": {"default": "chat"},
            "sessions": [
                {
                    "id": "chat",
                    "library": "default",
                    "title": "全文阅读",
                    "createdAt": "2026",
                    "updatedAt": "2026",
                    "references": [],
                    "messages": [
                        {
                            "id": "answer",
                            "role": "assistant",
                            "content": "已打开资料",
                            "sources": [source],
                            "mode": "search",
                            "status": "complete",
                            "contextReferences": [{"id": id, "filename": "index.md"}],
                        }
                    ],
                }
            ],
        }
    )
    store = SQLiteConversationStore(tmp_path / "conversations.sqlite3")
    value = snapshot.model_dump(exclude_none=True)
    value.pop("revision")
    store.write(value, 0)
    restored = SQLiteConversationStore(tmp_path / "conversations.sqlite3").read()["sessions"][0][
        "messages"
    ][0]
    assert (
        restored["sources"][0]["text"] == text
        and restored["sources"][0]["content_scope"] == "full_document"
    )
    assert restored["contextReferences"][0]["id"] == id


@pytest.mark.parametrize(
    "invalid",
    [
        {"source_scope": []},
        {"use_context": "yes"},
        {"operation": "aggregate", "source_scope": "full_document"},
    ],
)
def test_invalid_evidence_scope_is_rejected(invalid):
    with pytest.raises(AppError):
        QuerySpec.parse({"operation": "answer", **invalid})


def test_single_explicit_resource_defaults_to_complete_evidence_even_if_planner_omits_scope(
    system, monkeypatch
):
    _, knowledge, chat, _ = system
    id, text = article(knowledge, "会议纪要")
    config = knowledge.settings.read()
    config["generation_provider"] = "local"
    monkeypatch.setattr(knowledge.settings, "read", lambda: config)
    chat.queries.local_planner = Planner(
        {"operation": "answer", "text_query": "重点", "use_context": False}
    )
    plan = chat.prepare(
        "default",
        "整理重点",
        document_ids=[id],
        allow_planning=True,
        local_generation_only=True,
        lookup_mode=True,
    )
    assert text in plan.prompt and [source.document_id for source in plan.sources] == [id]


def test_read_identity_is_not_lost_to_catalog_pagination(system):
    _, knowledge, chat, _ = system
    id, text = article(knowledge)
    result = chat.local_query(
        "default",
        "完整资料",
        document_ids=[id],
        query_plan={"operation": "read", "offset": 10, "limit": 1},
    )
    assert result["sources"][0].text == text and result["query"]["plan"]["offset"] == 0
