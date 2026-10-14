"""Topic questions in assistant mode must reach grounded answer generation."""

import json
from hashlib import sha256

import pytest

from edge_knowledge.domain.models import Chunk, Document, SearchHit
from edge_knowledge.domain.retrieval import rank_hits


class SearchPlanner:
    def __init__(self, query="ASR 方案"):
        self.query = query

    def plan(self, question, context):
        return {"operation": "search", "text_query": self.query}


def test_assistant_topic_question_is_answered_after_model_search(system):
    _, knowledge, chat, _ = system
    knowledge.settings.update({"generation_provider": "local"})
    knowledge.repository.add(
        "default",
        Document("a" * 64, "sensevoice.md", 1, 100, "2026"),
        [Chunk("ASR：SenseVoice 本地语音识别方案与部署步骤。", 0, "端侧实战")],
        [[1.0, 0.0, 0.0]],
    )
    chat.queries.local_planner = SearchPlanner()
    plan = chat.prepare("default", "asr 方案有哪些", allow_planning=True)
    assert plan.sources
    assert plan.local_answer is None, "助手模式仅返回资料数量，没有生成方案回答"
    assert plan.result_kind == "answer"


def test_topic_retrieval_excludes_unrelated_generic_solution_notes(system):
    _, knowledge, _, _ = system
    rows = [
        ("a", "ASR SenseVoice 端侧实战：语音识别方案。", [0.75, 0.66, 0.0]),
        ("b", "ASR 语音识别：转写方案。", [0.76, 0.65, 0.0]),
        ("c", "最后采用的方案", [0.79, 0.61, 0.0]),
        ("d", "标题方案", [0.75, 0.66, 0.0]),
        ("e", "百分比布局方案", [0.72, 0.69, 0.0]),
    ]
    # ASR is common within this corpus; IDF alone makes the generic word “方案” stronger.
    for n in range(12):
        rows.append((str(n), "ASR 识别测试记录", [0.4, 0.92, 0.0]))
    for id, text, vector in rows:
        knowledge.repository.add(
            "default",
            Document(sha256(id.encode()).hexdigest(), id + ".md", 1, 100, "2026"),
            [Chunk(text, 0, "")],
            [vector],
        )
    hits = knowledge.search("default", "asr 方案有哪些", 5)
    assert hits
    assert all("asr" in h.text.lower() for h in hits), "无关方案笔记挤入主题回答依据"


@pytest.mark.parametrize(
    "question,query,evidence",
    [
        ("缓存实现有哪些", "缓存实现", "缓存实现：内存缓存与磁盘缓存。"),
        ("RAG 有哪些方案", "RAG", "RAG：全文检索与向量检索。"),
        ("比较两种部署方式", "部署方式", "部署方式：单机和容器。"),
    ],
)
def test_assistant_search_step_generates_grounded_response(system, question, query, evidence):
    client, knowledge, chat, generator = system
    knowledge.ingest("default", "note.md", evidence.encode())
    knowledge.settings.update({"generation_provider": "local"})
    chat.queries.local_planner = SearchPlanner(query)
    response = client.post("/api/query", json={"question": question, "allow_planning": True})
    assert response.status_code == 200
    events = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    execution = next(event for event in events if event["type"] == "execution")
    assert execution["generator"] == "local" and execution["result_kind"] == "answer"
    assert generator.calls == 1
    assert not knowledge.settings.api_key()


@pytest.mark.parametrize(
    "case", ["lookup", "local_only", "explicit_plan", "no_answer_consent", "media_only", "empty"]
)
def test_search_boundaries_still_do_not_generate(system, case):
    _, knowledge, chat, generator = system
    knowledge.settings.update({"generation_provider": "local"})
    knowledge.repository.add(
        "default",
        Document(
            "a" * 64,
            "note.md",
            1,
            100,
            "2026",
            kind="image" if case == "media_only" else "document",
        ),
        [Chunk("ASR：SenseVoice 本地语音识别方案。", 0, "")],
        [[1.0, 0.0, 0.0]],
    )
    chat.queries.local_planner = SearchPlanner()
    if case == "local_only":
        assert chat.local_query("default", "asr 方案有哪些")["kind"] == "retrieval"
    else:
        if case == "empty":
            knowledge.repository.delete_many("default", ["a" * 64])
        plan = chat.prepare(
            "default",
            "查找 ASR 方案" if case == "lookup" else "asr 方案有哪些",
            allow_planning=case != "no_answer_consent",
            query_plan={"operation": "search", "text_query": "ASR"}
            if case == "explicit_plan"
            else None,
        )
        assert plan.local_answer is not None
        assert plan.result_kind == "retrieval"
    assert generator.calls == 0


@pytest.mark.parametrize("topic", ["ASR", "RAG", "Redis", "SQLite"])
def test_latin_topic_filters_generic_solution_match_without_special_cases(topic):
    hits = [
        SearchHit("a", "topic.md", f"{topic} 工程方案", "", 0, 0.76),
        SearchHit("b", "layout.md", "网页布局方案", "", 0, 0.79),
    ]
    hits += [SearchHit(str(n), "log.md", f"{topic} 测试记录", "", 0, 0.4) for n in range(12)]
    result = rank_hits(f"{topic} 方案有哪些", hits, 5, 0.2)
    assert result and all(topic.lower() in h.text.lower() for h in result)


def test_latin_topic_without_literal_evidence_keeps_semantic_paraphrase():
    hits = [SearchHit("a", "note.md", "端侧语音转写模型与离线识别", "", 0, 0.76)]
    assert rank_hits("ASR 方案有哪些", hits, 5, 0.2) == hits


@pytest.mark.parametrize("word", ["方案", "方法", "方式", "solutions", "methods", "options"])
def test_topic_overview_keeps_relevant_note_without_generic_question_word(word):
    hits = [
        SearchHit("overview", "overview.md", f"ASR {word}选择", "", 0, 0.7538),
        SearchHit("practical", "practical.md", "SenseVoice ASR 端侧部署实战", "", 0, 0.7481),
    ]
    hits += [SearchHit(str(n), "log.md", "ASR 测试", "", 0, 0.4) for n in range(12)]
    result = rank_hits(f"ASR {word}有哪些", hits, 5, 0.2)
    assert "practical" in {h.document_id for h in result}, "实战笔记不应因未写通用问句词被排除"


def test_general_text_answer_prefers_native_note_over_ocr_thumbnail(system):
    _, knowledge, chat, _ = system
    knowledge.settings.update({"generation_provider": "local", "top_k": 1})
    for id, kind, text, vector in [
        ("a", "document", "ASR SenseVoice 端侧实战笔记", [0.7481, 0.66, 0.0]),
        ("b", "image", "ASR 架构示意图", [0.7664, 0.64, 0.0]),
    ]:
        knowledge.repository.add(
            "default",
            Document(
                id * 64,
                id + ".md",
                1,
                100,
                "2026",
                kind=kind,
                ocr_status="ready" if kind == "image" else "not_applicable",
            ),
            [Chunk(text, 0, "")],
            [vector],
        )
    chat.queries.local_planner = SearchPlanner()
    plan = chat.prepare("default", "asr 方案有哪些", allow_planning=True)
    assert [h.kind for h in plan.sources] == ["document"], "完整笔记被略高分的图片 OCR 挤出回答依据"


@pytest.mark.parametrize("scope", ["reference", "kind_filter", "explicit_plan", "lookup"])
def test_deliberate_media_scope_is_not_reordered_as_text_answer(system, scope):
    _, knowledge, chat, _ = system
    knowledge.settings.update({"generation_provider": "local", "top_k": 1})
    for id, kind, vector in [
        ("a", "document", [0.75, 0.66, 0.0]),
        ("b", "image", [0.9, 0.43, 0.0]),
    ]:
        knowledge.repository.add(
            "default",
            Document(id * 64, id + ".md", 1, 100, "2026", kind=kind, ocr_status="ready"),
            [Chunk("ASR 语音识别", 0, "")],
            [vector],
        )

    class ScopedPlanner:
        def plan(self, question, context):
            return {
                "operation": "search",
                "text_query": "ASR",
                "where": {"field": "kind", "op": "eq", "value": "image"}
                if scope == "kind_filter"
                else {"all": []},
            }

    chat.queries.local_planner = ScopedPlanner()
    plan = chat.prepare(
        "default",
        "查找 ASR 资料" if scope == "lookup" else "ASR 方案有哪些",
        allow_planning=True,
        document_ids=["a" * 64, "b" * 64] if scope == "reference" else None,
        query_plan={"operation": "search", "text_query": "ASR"}
        if scope == "explicit_plan"
        else None,
    )
    assert [h.kind for h in plan.sources] == ["image"]


def test_native_note_shortage_still_keeps_ocr_supplement(system):
    _, knowledge, chat, _ = system
    knowledge.settings.update({"generation_provider": "local", "top_k": 2})
    for id, kind in [("a", "document"), ("b", "image")]:
        knowledge.repository.add(
            "default",
            Document(id * 64, id + ".md", 1, 100, "2026", kind=kind, ocr_status="ready"),
            [Chunk("ASR " + id, 0, "")],
            [[1.0, 0.0, 0.0]],
        )
    chat.queries.local_planner = SearchPlanner()
    plan = chat.prepare("default", "ASR 方案有哪些", allow_planning=True)
    assert [h.kind for h in plan.sources] == ["document", "image"]
    assert len({(h.document_id, h.index) for h in plan.sources}) == 2


def test_irrelevant_native_note_does_not_hide_matching_ocr(system):
    _, knowledge, chat, _ = system
    knowledge.settings.update({"generation_provider": "local", "top_k": 1, "min_score": 0.6})
    for id, kind, text, vector in [
        ("a", "document", "风景日记", [0.1, 0.99, 0.0]),
        ("b", "image", "ASR 示意图", [1.0, 0.0, 0.0]),
    ]:
        knowledge.repository.add(
            "default",
            Document(id * 64, id + ".md", 1, 100, "2026", kind=kind, ocr_status="ready"),
            [Chunk(text, 0, "")],
            [vector],
        )
    chat.queries.local_planner = SearchPlanner()
    plan = chat.prepare("default", "ASR 方案有哪些", allow_planning=True)
    assert [h.kind for h in plan.sources] == ["image"]
