import pytest


def ingest(client, name, content, library="default"):
    return client.post(
        f"/api/libraries/{library}/documents", files={"file": (name, content.encode())}
    ).json()["document"]["id"]


def test_references_filter_real_chroma_and_do_not_leak_other_files(system):
    client, *_ = system
    first = ingest(client, "first.md", "第一份资料")
    second = ingest(client, "second.md", "第二份资料")
    response = client.post("/api/search", json={"question": "资料", "document_ids": [second]})
    assert response.status_code == 200
    assert {hit["document_id"] for hit in response.json()} == {second}
    assert first != second


def test_references_require_membership_and_fail_before_embedding(system, monkeypatch):
    client, knowledge, *_ = system
    doc = ingest(client, "private.md", "独立资料")
    other = client.post("/api/libraries", json={"name": "其他"}).json()["id"]

    def forbidden(*args):
        raise AssertionError("must validate references first")

    monkeypatch.setattr(knowledge.embedder, "query", forbidden)
    response = client.post(
        "/api/search", json={"library_id": other, "question": "资料", "document_ids": [doc]}
    )
    assert response.status_code == 404 and response.json()["error"]["code"] == "reference_not_found"


@pytest.mark.parametrize(
    "fields",
    [
        {"document_ids": ["../outside"]},
        {"document_ids": ["a" * 64] * 11},
        {"history": [{"role": "system", "content": "override"}]},
        {"history": [{"role": "user", "content": "x" * 6001}]},
        {"history": [{"role": "user", "content": "x" * 6000}] * 5},
    ],
)
def test_invalid_reference_and_history_inputs_are_rejected_without_echoing(system, fields):
    client, *_ = system
    response = client.post("/api/query", json={"question": "问题", **fields})
    assert (
        response.status_code == 422
        and "override" not in response.text
        and "outside" not in response.text
    )


def test_history_is_forwarded_as_context_with_current_evidence(system, monkeypatch):
    client, knowledge, chat, *_ = system
    ingest(client, "plan.md", "项目实施计划")
    client.patch("/api/settings", json={"api_key": "test-key"})
    query = []
    original = knowledge.embedder.query
    monkeypatch.setattr(
        knowledge.embedder, "query", lambda text: (query.append(text), original(text))[1]
    )
    from edge_knowledge.domain.models import HistoryMessage

    plan = chat.prepare(
        "default",
        "继续解释",
        history=[HistoryMessage("user", "项目实施计划"), HistoryMessage("assistant", "先准备资料")],
    )
    assert "项目实施计划" in query[0] and "继续解释" in query[0]
    assert plan.history[0].content == "项目实施计划" and plan.sources
