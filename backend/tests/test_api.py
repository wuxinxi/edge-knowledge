import json


def upload(client, name="guide.md", text="# 指南\n文档检索在本地进行。"):
    return client.post(
        "/api/libraries/default/documents", files={"file": (name, text.encode(), "text/markdown")}
    )


def events(response):
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


def test_authentication_required(system):
    client, *_ = system
    response = client.get("/api/health", headers={"Authorization": ""})
    assert response.status_code == 401
    assert client.get("/api/health").json()["embedding_loaded"] is False


def test_desktop_dev_cors_allows_only_configured_local_origin(system):
    client, *_ = system
    local = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert local.headers["access-control-allow-origin"] == "http://localhost:5173"
    foreign = client.get("/api/health", headers={"Origin": "https://example.com"})
    assert "access-control-allow-origin" not in foreign.headers
    preflight = client.options(
        "/api/query",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert preflight.status_code == 200


def test_ingest_deduplicate_search_delete(system):
    client, _, _, _ = system
    first = upload(client)
    assert first.status_code == 201
    doc = first.json()["document"]
    assert upload(client).json()["duplicate"] is True
    docs = client.get("/api/libraries/default/documents").json()
    assert len(docs) == 1 and docs[0]["id"] == doc["id"]
    hits = client.post("/api/search", json={"question": "在哪里检索？"}).json()
    assert len(hits) == 1 and hits[0]["section"] == "指南"
    assert hits[0]["score"] == 1.0
    assert client.delete(f"/api/libraries/default/documents/{doc['id']}").status_code == 200
    assert client.post("/api/search", json={"question": "在哪里检索？"}).json() == []
    assert client.delete(f"/api/libraries/default/documents/{doc['id']}").status_code == 404


def test_libraries_are_isolated(system):
    client, *_ = system
    library = client.post("/api/libraries", json={"name": "项目资料"}).json()
    upload(client)
    hits = client.post("/api/search", json={"library_id": library["id"], "question": "指南"}).json()
    assert hits == []
    assert client.get("/api/libraries/nope/documents").status_code == 404


def test_secrets_never_return_and_invalid_patch_is_atomic(system):
    client, knowledge, *_ = system
    response = client.patch("/api/settings", json={"api_key": "secret-for-testing"})
    assert response.status_code == 200
    assert "secret-for-testing" not in response.text
    assert response.json()["api_key_configured"] is True
    assert "api_key" not in client.get("/api/settings").json()
    bad = client.patch(
        "/api/settings", json={"api_key": "new-secret", "chunk_size": 100, "chunk_overlap": 200}
    )
    assert bad.status_code == 400
    assert knowledge.settings.api_key() == "secret-for-testing"
    invalid = client.patch("/api/settings", json={"api_key": "do-not-echo", "top_k": 0})
    assert invalid.status_code == 422 and "do-not-echo" not in invalid.text
    assert (
        client.patch("/api/settings", json={"base_url": "https://evil.example"}).status_code == 400
    )


def test_empty_library_avoids_model_and_cloud(system):
    client, knowledge, _, generator = system
    response = client.post("/api/query", json={"question": "内容是什么？"})
    payloads = events(response)
    assert [event["type"] for event in payloads] == ["sources", "delta", "done"]
    assert knowledge.embedder.loaded is False and generator.calls == 0


def test_query_requires_key_and_includes_sources(system):
    client, _, _, generator = system
    upload(client)
    assert client.post("/api/query", json={"question": "在哪里检索？"}).status_code == 409
    client.patch("/api/settings", json={"api_key": "test-key"})
    response = client.post("/api/query", json={"question": "在哪里检索？"})
    payloads = events(response)
    assert payloads[0]["sources"][0]["filename"] == "guide.md"
    assert payloads[-1] == {"type": "done"}
    assert generator.calls == 1
    assert "test-key" not in response.text


def test_invalid_files_and_questions(system):
    client, *_ = system
    assert upload(client, name="script.exe").status_code == 415
    assert upload(client, text="").status_code == 400
    assert upload(client, name="broken.pdf", text="bad pdf").status_code == 400
    assert client.post("/api/query", json={"question": "  "}).status_code == 422
    assert client.post("/api/query", json={"question": "x", "top_k": 21}).status_code == 422


def test_cloud_failure_is_a_terminal_sse_error(system):
    from edge_knowledge.domain.models import AppError

    client, _, chat, _ = system
    upload(client)
    client.patch("/api/settings", json={"api_key": "test-key"})

    class BrokenGenerator:
        async def generate(self, plan):
            yield "部分回答"
            raise AppError("服务超时", 504, "upstream_timeout")

    chat.generator = BrokenGenerator()
    payloads = events(client.post("/api/query", json={"question": "问题"}))
    assert payloads[-1] == {"type": "error", "message": "服务超时", "code": "upstream_timeout"}
    assert not any(event["type"] == "done" for event in payloads)
