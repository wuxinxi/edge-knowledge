import json

import pytest

from edge_knowledge.domain.lookup import local_lookup


@pytest.mark.parametrize(
    "question,query,kinds",
    [
        (
            "帮我检索Massive Audio Embedding Benchmark图片",
            "Massive Audio Embedding Benchmark",
            ("image",),
        ),
        ("请帮我查找一张性能对比图片", "性能对比", ("image",)),
        (
            "帮我查询出威海荣成的 fpt 地址和用户名和密码是多少",
            "威海荣成的 fpt 地址和用户名和密码是多少",
            (),
        ),
        ("取件码是多少？", "取件码是多少？", ()),
        ("find audio of birds", "audio of birds", ("audio", "video")),
    ],
)
def test_lookup_intents(question, query, kinds):
    lookup = local_lookup(question)
    assert lookup and lookup.query == query and lookup.kinds == kinds


@pytest.mark.parametrize(
    "question",
    [
        "请总结这份报告",
        "帮我解释密码安全的风险",
        "查找并分析图片",
        "why is this result different?",
        "解释一下这张图片",
    ],
)
def test_interpretation_is_not_silently_presented_as_retrieval(question):
    assert local_lookup(question) is None


def test_direct_information_lookup_is_local_with_or_without_a_key(system):
    client, _, _, generator = system
    client.post(
        "/api/libraries/default/documents",
        files={"file": ("guide.md", b"# Endpoint\n\nAddress: demo.example\nUsername: demo-user")},
    )
    for key in ("", "configured-test-key"):
        client.patch("/api/settings", json={"api_key": key})
        response = client.post("/api/query", json={"question": "帮我查询地址和用户名是多少"})
        assert response.status_code == 200
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        assert {"type": "execution", "location": "local", "result_kind": "retrieval"} in events
        assert events[0]["sources"][0]["filename"] == "guide.md"
        assert generator.calls == 0
    client.patch("/api/settings", json={"api_key": "configured-test-key"})
    response = client.post("/api/query", json={"question": "请总结这份资料"})
    assert response.status_code == 200 and generator.calls == 1


def test_empty_lookup_does_not_fall_back_to_cloud(system):
    client, _, _, generator = system
    response = client.post("/api/query", json={"question": "请查找没有的笔记"})
    assert response.status_code == 200 and generator.calls == 0
    assert "没有找到相关资料" in response.text
    events = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert {"type": "execution", "location": "local", "result_kind": "retrieval"} in events


def test_empty_statistics_and_clarification_keep_their_distinct_result_kinds(system):
    client, _, _, generator = system
    for spec, kind in [
        ({"operation": "aggregate"}, "catalog"),
        ({"operation": "clarify", "clarification": "请提供年份"}, "clarification"),
    ]:
        response = client.post("/api/query", json={"question": "执行查询", "query_plan": spec})
        assert response.status_code == 200
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        assert {"type": "execution", "location": "local", "result_kind": kind} in events
    assert generator.calls == 0


def test_picture_classifier_handles_bare_tu_and_demonstratives():
    from edge_knowledge.domain.lookup import local_lookup

    for question, expected in [
        ("找到那张 Massive Audio Embedding Benchmark 图。", "Massive Audio Embedding Benchmark"),
        ("找到这张海边落日图", "海边落日"),
    ]:
        lookup = local_lookup(question)
        assert lookup.kinds == ("image",) and lookup.query == expected
