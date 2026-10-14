"""Answer evidence must preserve the facts outside a matching introductory excerpt."""

import pytest

from edge_knowledge.application.evidence import AnswerEvidence
from edge_knowledge.domain.models import AppError, SearchHit


class Planner:
    def plan(self, question, context):
        return {"operation": "answer", "text_query": "选择依据"}


@pytest.mark.parametrize(
    "question,entity",
    [
        ("中文通知播报应该选择哪款？", "DemoVoice"),
        ("单机服务适合哪个数据库？", "DemoDatabase"),
        ("周末短途旅行选哪个目的地？", "DemoDestination"),
    ],
)
def test_answer_reads_small_parent_note_beyond_generic_matching_passages(
    system, monkeypatch, question, entity
):
    _, knowledge, chat, _ = system
    raw = (
        "---\ntitle: 选择依据\n---\n\n# 选择依据\n\n"
        "## 判断场景\n先确认用途、语言与资源。\n\n"
        "## 选择步骤\n按场景匹配能力，优先基础能力。\n\n"
        f"## 具体选项\n{entity} 支持上述用途；另一款仅支持不同用途。\n"
    )
    id = knowledge.ingest("default", "index.md", raw.encode())["document"]["id"]
    hits = [
        SearchHit(id, "index.md", "先确认用途、语言与资源。", "判断场景", 1, 0.9),
        SearchHit(id, "index.md", "按场景匹配能力，优先基础能力。", "选择步骤", 2, 0.85),
    ]
    monkeypatch.setattr(knowledge, "search", lambda *_: hits)
    knowledge.settings.update({"generation_provider": "local"})
    chat.queries.local_planner = Planner()
    plan = chat.prepare("default", question, allow_planning=True)
    assert entity in plan.prompt, "只提供匹配的泛化建议片段，遗漏了同一篇笔记的具体选项"
    assert len(plan.sources) == 1
    assert plan.sources[0].text == raw
    assert plan.sources[0].content_scope == "full_document"
    assert plan.sources[0].score == 0.9
    assert plan.sources[0].section == "选择依据"
    assert plan.local_answer is None and plan.provider == "local"


def test_plain_lookup_keeps_original_excerpts_without_reading_parents(system, monkeypatch):
    _, knowledge, chat, _ = system
    id = knowledge.ingest("default", "note.md", b"original")["document"]["id"]
    hit = SearchHit(id, "note.md", "excerpt", "section", 2, 0.9)
    monkeypatch.setattr(knowledge, "search", lambda *_: [hit])
    monkeypatch.setattr(knowledge, "read_document", lambda *_: pytest.fail("lookup read parent"))
    plan = chat.prepare("default", "查找原文")
    assert plan.sources == [hit] and plan.local_answer is not None


def hit(id, text, **fields):
    return SearchHit(id, id + ".md", text, "章节", 2, 0.9, **fields)


def test_parent_expansion_reserves_all_other_matches_and_does_not_clip_large_originals():
    originals = {
        "a": hit("a", "a" * 6000, content_scope="full_document"),
        "b": hit("b", "b" * 6000, content_scope="full_document"),
        "c": hit("c", "c" * 6001, content_scope="full_document"),
    }
    matches = [hit("a", "a" * 3000), hit("b", "b" * 3000), hit("c", "c" * 3000)]
    result = AnswerEvidence(lambda _, id: originals[id]).expand("default", matches)
    assert result[0].content_scope == "full_document" and len(result[0].text) == 6000
    assert result[1:] == matches[1:]
    assert sum(len(h.text) for h in result) == 12000


def test_expansion_skips_media_and_already_explicit_full_sources():
    matches = [
        hit("image", "图中文字", kind="image"),
        hit("bundle", "联合素材", kind="bundle"),
        hit("full", "原文", content_scope="full_document"),
    ]
    result = AnswerEvidence(lambda *_: pytest.fail("no parent read needed")).expand(
        "default", matches
    )
    assert result == matches


def test_missing_original_keeps_excerpts_but_membership_errors_propagate():
    matches = [hit("doc", "保存的节选")]

    def missing(*_):
        raise AppError("原文缺失", 409, "original_missing")

    assert AnswerEvidence(missing).expand("default", matches) == matches

    def forbidden(*_):
        raise AppError("跨库", 404, "reference_not_found")

    with pytest.raises(AppError) as exc:
        AnswerEvidence(forbidden).expand("other", matches)
    assert exc.value.code == "reference_not_found"


def test_parent_expansion_never_reads_an_unmatched_document(system, monkeypatch):
    _, knowledge, chat, _ = system
    first = knowledge.ingest("default", "first.md", b"first original")["document"]["id"]
    knowledge.ingest("default", "second.md", b"different original")
    matches = [hit(first, "first excerpt")]
    monkeypatch.setattr(knowledge, "search", lambda *_: matches)
    knowledge.settings.update({"generation_provider": "local"})
    plan = chat.prepare("default", "任意知识问题")
    assert [s.document_id for s in plan.sources] == [first]
    assert "different original" not in plan.prompt


def test_explicit_excerpt_contract_is_preserved_for_answering(system, monkeypatch):
    _, knowledge, chat, _ = system
    id = knowledge.ingest("default", "note.md", b"complete original")["document"]["id"]
    matches = [hit(id, "chosen excerpt")]
    monkeypatch.setattr(knowledge, "search", lambda *_: matches)
    monkeypatch.setattr(knowledge, "read_document", lambda *_: pytest.fail("explicit excerpt"))
    knowledge.settings.update({"generation_provider": "local"})
    plan = chat.prepare(
        "default",
        "回答",
        query_plan={"operation": "answer", "source_scope": "excerpt"},
        allow_planning=True,
    )
    assert plan.sources == matches and "complete original" not in plan.prompt
