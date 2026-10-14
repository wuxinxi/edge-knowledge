import sqlite3

import pytest
from fastapi.testclient import TestClient

from edge_knowledge.api.app import create_app
from edge_knowledge.application.conversations import ConversationService
from edge_knowledge.domain.models import AppError
from edge_knowledge.infrastructure.conversations import SQLiteConversationStore


def snapshot(content="  文本\n\n结尾  "):
    return {
        "version": 1,
        "sessions": [
            {
                "id": "chat",
                "library": "default",
                "title": "主题",
                "titleSource": "auto",
                "createdAt": "2026",
                "updatedAt": "2026",
                "references": [],
                "messages": [
                    {
                        "id": "message",
                        "role": "assistant",
                        "content": content,
                        "sources": [],
                        "status": "streaming",
                        "versions": [{"content": "旧回答", "sources": [], "savedAt": "2026"}],
                    }
                ],
            }
        ],
        "active": {"default": "chat"},
    }


def test_durable_full_content_after_reopen_and_beyond_browser_quota(tmp_path):
    p = tmp_path / "conversations.sqlite3"
    store = SQLiteConversationStore(p)
    assert not store.read()["initialized"]
    state = snapshot("  大段落\n" * 800000)
    assert store.write(state, 0) == 1
    read = SQLiteConversationStore(p).read()
    assert read["sessions"] == state["sessions"] and read["active"] == state["active"]
    assert p.stat().st_mode & 0o777 == 0o600


def test_delete_all_then_new_chat_does_not_resurrect_old_records(tmp_path):
    p = tmp_path / "conversations.sqlite3"
    store = SQLiteConversationStore(p)
    original = snapshot()
    store.write(original, 0)
    store.write({"version": 1, "sessions": [], "active": {}}, 1)
    store = SQLiteConversationStore(p)
    assert store.read()["initialized"] and not store.read()["sessions"]
    with sqlite3.connect(p) as db:
        assert db.execute("SELECT count(*) FROM deleted").fetchone()[0] == 1
    store.write(original, 2)
    assert store.read()["sessions"] == original["sessions"]


def test_stale_writer_cannot_replace_more_recent_transcript(tmp_path):
    store = SQLiteConversationStore(tmp_path / "state.sqlite3")
    value = snapshot()
    store.write(value, 0)
    with pytest.raises(AppError) as error:
        store.write(snapshot("stale"), 0)
    assert error.value.code == "chat_conflict" and store.read()["sessions"] == value["sessions"]


def test_api_preserves_draft_on_reopen_and_rejects_upload_permission(system, tmp_path):
    _, knowledge, chat, *_ = system
    path = tmp_path / "draft.sqlite3"
    service = ConversationService(SQLiteConversationStore(path))
    app = create_app(knowledge, chat, "test-token", conversations=service)
    state = snapshot()
    draft = {"content": "  还没写完\n\n下一段  ", "mode": "search"}
    state["sessions"][0]["draft"] = draft
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer test-token"
        assert client.post("/api/chat-state", json={**state, "revision": 0}).status_code == 200
        assert SQLiteConversationStore(path).read()["sessions"][0]["draft"] == draft
        draft["allowImageUpload"] = True
        assert client.post("/api/chat-state", json={**state, "revision": 1}).status_code == 422
        assert client.get("/api/chat-state").json()["sessions"][0]["draft"] == {
            "content": "  还没写完\n\n下一段  ",
            "mode": "search",
        }


def test_api_authentication_validation_and_lossless_fields(system, tmp_path):
    _, knowledge, chat, *_ = system
    service = ConversationService(SQLiteConversationStore(tmp_path / "state.sqlite3"))
    app = create_app(knowledge, chat, "test-token", conversations=service)
    with TestClient(app) as client:
        assert client.get("/api/chat-state").status_code == 401
        client.headers["Authorization"] = "Bearer test-token"
        state = snapshot()
        assert client.post("/api/chat-state", json={**state, "revision": 0}).status_code == 200
        assert client.get("/api/chat-state").json()["sessions"] == state["sessions"]
        invalid = {**snapshot(), "revision": 1, "api_key": "secret-not-echoed"}
        response = client.post("/api/chat-state", json=invalid)
        assert response.status_code == 422 and "secret-not-echoed" not in response.text
        assert client.post("/api/chat-state", json={**state, "revision": 0}).status_code == 409
        assert client.get("/api/chat-state").json()["sessions"] == state["sessions"]
