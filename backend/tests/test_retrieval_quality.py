"""Controlled vector fixtures expose retrieval noise; never a production embedder."""

from edge_knowledge.domain.models import Chunk, Document, HistoryMessage


def add(knowledge, id, text, vector):
    knowledge.repository.add(
        "default", Document(id * 64, id + ".md", 1, 100, "2026"), [Chunk(text, 0, "")], [vector]
    )


def test_search_does_not_fill_results_with_below_threshold_neighbors(system):
    client, knowledge, *_ = system
    add(knowledge, "a", "项目资料", [0.1, 0.995, 0.0])
    client.patch("/api/settings", json={"min_score": 0.6})
    assert client.post("/api/search", json={"question": "项目资料"}).json() == []


def test_explicit_question_does_not_search_previous_topic(system, monkeypatch):
    _, knowledge, chat, *_ = system
    add(knowledge, "a", "资料", [1.0, 0.0, 0.0])
    knowledge.settings.update({"api_key": "test-key"})
    captured = []
    monkeypatch.setattr(
        knowledge.embedder, "query", lambda question: captured.append(question) or [1.0, 0.0, 0.0]
    )
    chat.prepare(
        "default",
        "荣成数据中心的 FTP 地址是什么？",
        history=[HistoryMessage("user", "杭州部署计划")],
    )
    assert captured == ["荣成数据中心的 FTP 地址是什么？"]


def test_identifier_match_outranks_similar_but_wrong_entity(system):
    _, knowledge, *_ = system
    add(knowledge, "a", "服务 BRAVO-42 的 FTP 地址配置。", [1.0, 0.0, 0.0])
    add(knowledge, "b", "服务 ALPHA-17 的 FTP 地址配置。", [0.8, 0.6, 0.0])
    hits = knowledge.search("default", "服务 ALPHA-17 的 FTP 地址是什么？", 5)
    assert [hit.document_id for hit in hits] == ["b" * 64]


def test_user_typo_and_chinese_entity_do_not_return_other_locations(system, monkeypatch):
    _, knowledge, *_ = system
    add(knowledge, "a", "杭州的数据中心 FTP 地址和用户名和密码。", [1.0, 0.0, 0.0])
    add(knowledge, "b", "威海荣成 FTP 地址和用户名和密码。", [0.88, 0.475, 0.0])
    questions = []
    monkeypatch.setattr(
        knowledge.embedder, "query", lambda q: questions.append(q) or [1.0, 0.0, 0.0]
    )
    hits = knowledge.search("default", "帮我查询出威海荣成的 fpt 地址和用户名和密码是多少", 5)
    assert [h.document_id for h in hits] == ["b" * 64]
    assert "FTP" in questions[0] and "fpt" not in questions[0]


def test_lexical_recall_finds_matching_identifier_beyond_dense_candidate_window(system):
    _, knowledge, *_ = system
    from hashlib import sha256

    for n in range(45):
        id = sha256(str(n).encode()).hexdigest()
        knowledge.repository.add(
            "default",
            Document(id, f"{n}.md", 1, 10, "2026"),
            [Chunk("服务 BRAVO 的 FTP 地址。", 0, "")],
            [[1.0, 0.0, 0.0]],
        )
    add(knowledge, "b", "服务 ALPHA-17 的 FTP 地址。", [0.7, 0.714, 0.0])
    assert knowledge.search("default", "ALPHA-17 FTP 地址", 5)[0].document_id == "b" * 64


def test_missing_explicit_identifier_returns_no_wrong_entity(system):
    _, knowledge, *_ = system
    add(knowledge, "a", "服务 BRAVO-42 的 FTP 地址。", [1.0, 0.0, 0.0])
    assert knowledge.search("default", "服务 ALPHA-17 的 FTP 地址", 5) == []


def test_paraphrase_still_uses_semantic_retrieval_without_exact_words(system):
    _, knowledge, *_ = system
    add(knowledge, "a", "番茄和鸡蛋翻炒。", [1.0, 0.0, 0.0])
    assert knowledge.search("default", "西红柿如何烹饪", 5)[0].document_id == "a" * 64


def test_retrieval_preserves_relative_note_path_without_changing_saved_vectors(system):
    client, knowledge, *_ = system
    from dataclasses import replace

    document = Document("a" * 64, "index.md", 1, 100, "2026", source_path="项目/部署/index.md")
    knowledge.repository.add(
        "default", document, [Chunk("部署步骤", 0, "上线流程")], [[1.0, 0.0, 0.0]]
    )
    other = knowledge.repository.create_library("其他资料")
    knowledge.repository.add(
        other.id,
        replace(document, source_path="私人/index.md"),
        [Chunk("部署步骤", 0, "")],
        [[1.0, 0.0, 0.0]],
    )
    response = client.post("/api/search", json={"library_id": "default", "question": "部署步骤"})
    assert response.status_code == 200
    assert response.json()[0]["path"] == "项目/部署/index.md"
    assert response.json()[0]["section"] == "上线流程"
    assert "私人" not in response.text
    assert knowledge.repository.vectors("default")[0][1] == [1.0, 0.0, 0.0]
