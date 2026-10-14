"""A validated answer plan must survive lookup-shaped wording and reference scope."""

import json

import pytest

from edge_knowledge.domain.models import HistoryMessage


class ReferenceAnswerPlanner:
    def __init__(self):
        self.contexts = []

    def plan(self, question, context):
        self.contexts.append(context)
        return {"operation": "answer", "use_context": True, "source_scope": "full_document"}


@pytest.mark.parametrize(
    "question,text,expected",
    [
        (
            "帮我找出一款支持中文并且支持克隆的模型",
            "# 能力对比\nDemoVoice 支持中文和声音克隆。PlainVoice 支持中文，不支持克隆。",
            "DemoVoice",
        ),
        (
            "帮我找出一个支持 JSON 并且适合单机的数据库",
            "# 数据库对比\nLocalDB 支持 JSON 且适合单机。ClusterDB 支持 JSON，需要集群。",
            "LocalDB",
        ),
        (
            "find one hotel with parking and accessible rooms",
            "# Hotels\nGreenHotel has parking and accessible rooms. BlueHotel has parking only.",
            "GreenHotel",
        ),
    ],
)
def test_reference_selection_reaches_local_generation_even_with_find_wording(
    system, question, text, expected
):
    client, knowledge, chat, generator = system
    id = knowledge.ingest("default", "comparison.md", text.encode())["document"]["id"]
    knowledge.settings.update({"generation_provider": "local"})
    planner = chat.queries.local_planner = ReferenceAnswerPlanner()
    response = client.post(
        "/api/query",
        json={
            "question": question,
            "document_ids": [id],
            "allow_planning": True,
            "lookup_mode": True,
            "local_generation_only": True,
        },
    )
    assert response.status_code == 200
    events = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    execution = next(event for event in events if event["type"] == "execution")
    assert execution.get("generator") == "local", "内容选择被‘找’字误降级成只返回资料数量"
    assert execution["result_kind"] == "answer" and generator.calls == 1
    sources = next(event["sources"] for event in events if event["type"] == "sources")
    assert len(sources) == 1 and sources[0]["text"] == text
    assert expected in sources[0]["text"]
    assert sources[0]["content_scope"] == "full_document"
    assert [row["document_id"] for row in planner.contexts[0]["current_documents"]] == [id]


def test_explicit_answer_contract_is_not_overridden_by_lookup_prefix(system):
    _, knowledge, chat, _ = system
    id = knowledge.ingest("default", "comparison.md", b"Specific choices in original")["document"][
        "id"
    ]
    knowledge.settings.update({"generation_provider": "local"})
    plan = chat.prepare(
        "default",
        "find one suitable choice",
        document_ids=[id],
        query_plan={"operation": "answer", "source_scope": "full_document"},
        allow_planning=True,
        history=[
            HistoryMessage("user", "先看看这些选项"),
            HistoryMessage("assistant", "历史仅供指代"),
        ],
    )
    assert plan.local_answer is None and plan.result_kind == "answer"
    assert "Specific choices" in plan.prompt
