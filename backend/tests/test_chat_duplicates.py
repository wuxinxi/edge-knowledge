import json
import math

import pytest

from edge_knowledge.application.semantic import SemanticService
from edge_knowledge.domain.models import AppError
from edge_knowledge.domain.query import QuerySpec
from edge_knowledge.infrastructure.media import AVMediaDecoder
from edge_knowledge.infrastructure.similarity import NumpySimilarityMatcher


@pytest.fixture
def comparison_system(system):
    client, knowledge, chat, generator = system
    semantic = SemanticService(
        knowledge,
        knowledge.embedder,
        AVMediaDecoder(),
        knowledge.payloads,
        matcher=NumpySimilarityMatcher(),
    )
    chat.semantic = semantic
    chat.queries.compare = semantic.duplicates
    return system


def post(client, **scope):
    return client.post(
        "/api/local-query",
        json={
            "question": "检查重复笔记",
            "query_plan": {"operation": "duplicates", "threshold": 0.99, "limit": 1},
            **scope,
        },
    )


def test_scoped_duplicate_comparison_uses_saved_vectors_without_cloud_or_reembedding(
    comparison_system,
):
    client, knowledge, _, generator = comparison_system
    ids = [
        knowledge.ingest("default", name, "# 部署流程\n安装依赖，启动服务。".encode())["document"][
            "id"
        ]
        for name in ["left.md", "right.md", "excluded.md"]
    ]
    knowledge.embedder.documents = knowledge.embedder.query = lambda *_: pytest.fail(
        "must reuse index"
    )
    response = post(client, document_ids=ids[:2])
    assert response.status_code == 200
    data = response.json()
    assert data["kind"] == "comparison" and data["query"]["result"]["scanned"] == 2
    assert data["query"]["result"]["total"] == 1 and generator.calls == 0
    pair = data["comparisons"][0]
    assert {pair["left"]["document_id"], pair["right"]["document_id"]} == set(ids[:2])
    assert pair["exact"] and pair["score"] == 1
    assert "安装依赖" in pair["left"]["text"] and "excluded.md" not in json.dumps(data)
    assert not knowledge.settings.api_key()


def test_whole_scope_count_is_not_limited_by_preview_or_the_workbench_200_note_limit(
    comparison_system,
):
    client, knowledge, _, generator = comparison_system
    for index in range(205):
        knowledge.ingest("default", f"note-{index}.md", b"shared original note")
    knowledge.embedder.query = lambda *_: pytest.fail("no retrieval")
    result = post(client).json()
    assert result["query"]["result"]["scanned"] == 205
    assert result["query"]["result"]["total"] == math.comb(205, 2)
    assert len(result["comparisons"]) == 1 and generator.calls == 0


def test_empty_filter_does_not_widen_scope_and_invalid_reference_is_rejected(comparison_system):
    client, knowledge, *_ = comparison_system
    doc = knowledge.ingest("default", "a.md", b"one")["document"]["id"]
    knowledge.ingest("default", "b.md", b"one")
    empty = client.post(
        "/api/local-query",
        json={
            "question": "check",
            "query_plan": {
                "operation": "duplicates",
                "where": {"field": "filename", "op": "eq", "value": "absent.md"},
            },
        },
    ).json()
    assert empty["query"]["result"]["scanned"] == 0 and not empty["comparisons"]
    other = knowledge.repository.create_library("other").id
    assert post(client, library_id=other, document_ids=[doc]).status_code == 404


def test_natural_language_plan_calls_comparison_instead_of_text_generation(comparison_system):
    client, knowledge, chat, generator = comparison_system
    for name in ["a.md", "b.md"]:
        knowledge.ingest("default", name, b"the same note")
    knowledge.settings.update({"generation_provider": "local"})

    class Planner:
        def plan(self, *_):
            return {"operation": "duplicates"}

    chat.queries.local_planner = Planner()
    response = client.post(
        "/api/query", json={"question": "这些笔记有没有重复的？", "allow_planning": True}
    )
    events = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert any(e["type"] == "comparisons" and len(e["comparisons"]) == 1 for e in events)
    assert not any(e.get("generator") for e in events) and generator.calls == 0


def test_native_matcher_counts_all_pairs_and_has_stable_pagination():
    matcher = NumpySimilarityMatcher()
    vectors = [[1.0, 0.0]] * 240
    fingerprints = [str(i) for i in range(240)]
    page = matcher.match(vectors, fingerprints, 0.99, 2, 1)
    assert page["total"] == math.comb(240, 2) and page["candidate_documents"] == 240
    assert [(p["left"], p["right"]) for p in page["pairs"]] == [(0, 2), (0, 3)]
    assert not any(p["exact"] for p in page["pairs"])
    with pytest.raises(AppError):
        matcher.match([[0, 0]], ["a"], 0.9, 1, 0)
    with pytest.raises(AppError):
        matcher.match([[1, 0], [1, 0, 0]], ["a", "b"], 0.9, 1, 0)


def test_comparison_rejects_unbounded_or_semantic_top_k_scope():
    for plan in [
        {"operation": "duplicates", "threshold": float("nan")},
        {"operation": "duplicates", "threshold": True},
        {"operation": "duplicates", "threshold": 1.1},
        {"operation": "duplicates", "text_query": "类似部署的笔记"},
    ]:
        with pytest.raises(AppError):
            QuerySpec.parse(plan)


def test_comparison_excerpts_and_paths_survive_conversation_and_backup_roundtrip(tmp_path):
    from test_conversations import snapshot

    from edge_knowledge.api.conversations import ConversationSnapshot
    from edge_knowledge.application.conversations import ConversationService
    from edge_knowledge.domain.backup import BackupLibrary, BackupSnapshot
    from edge_knowledge.domain.models import Library
    from edge_knowledge.infrastructure.backup import ZipBackupCodec
    from edge_knowledge.infrastructure.conversations import SQLiteConversationStore

    source = {
        "document_id": "left",
        "filename": "index.md",
        "path": "notes/项目/index.md",
        "text": "  完整对比摘录\n\n结尾  ",
        "section": "查重",
        "index": 0,
        "score": 1.0,
    }
    pair = {
        "left": source,
        "right": {**source, "document_id": "right", "path": "archive/项目/index.md"},
        "score": 1.0,
        "exact": True,
    }
    state = snapshot()
    message = state["sessions"][0]["messages"][0]
    message["processing"] = {
        "startedAt": 100,
        "finishedAt": 500,
        "steps": [{"stage": "comparing", "startedAt": 100}],
    }
    message["comparisons"] = [pair]
    message["versions"] = [
        {"content": "旧结果", "sources": [], "savedAt": "2026-10-13", "comparisons": [pair]}
    ]
    validated = ConversationSnapshot.model_validate({**state, "revision": 0}).model_dump(
        exclude_unset=True
    )
    validated.pop("revision")
    service = ConversationService(SQLiteConversationStore(tmp_path / "chats.sqlite3"))
    assert validated["sessions"][0]["messages"][0]["processing"] == message["processing"]
    service.save(validated, 0)
    assert service.read()["sessions"][0]["messages"][0]["comparisons"] == [pair]
    assert service.read()["sessions"][0]["messages"][0]["processing"] == message["processing"]
    codec = ZipBackupCodec()
    restored = codec.decode(
        codec.encode(
            BackupSnapshot(
                "test", 3, [BackupLibrary(Library("default", "测试", 0), [])], {"chats": state}
            )
        )
    )
    assert restored.frontend["chats"]["sessions"][0]["messages"][0]["versions"][0][
        "comparisons"
    ] == [pair]


def test_body_verification_rejects_metadata_similarity_and_preserves_changed_frontmatter_copies():
    matcher = NumpySimilarityMatcher()
    unrelated = matcher.match(
        [[1, 0], [1, 0]],
        ["a", "b"],
        0.9,
        10,
        0,
        [
            "---\ncreatedAt: 2026-09-01\n---\n安装依赖，启动服务。",
            "---\ncreatedAt: 2026-09-01\n---\n阅读小说，写读后感。",
        ],
    )
    assert unrelated["total"] == 0
    copies = matcher.match(
        [[1, 0], [0, 1]],
        ["a", "b"],
        0.9,
        10,
        0,
        [
            "---\ncreatedAt: 2026-09-01\n---\n# 部署\n安装依赖。",
            "---\ncreatedAt: 2026-10-01\n---\n# 部署\n安装依赖。",
        ],
    )
    assert copies["total"] == 1 and copies["pairs"][0]["body_exact"]
    assert copies["pairs"][0]["score"] == 0 and copies["pairs"][0]["content_similarity"] == 1
