"""Identity browsing is metadata-only, bounded and independent of model execution."""

import pytest


def note(knowledge, title, path):
    return knowledge.ingest(
        "default",
        "index.md",
        f"---\ntitle: {title}\n---\n正文不应出现在选择结果。".encode(),
        source_path=path,
    )["document"]["id"]


def test_choices_search_titles_filenames_and_paths_without_model_or_body(system, monkeypatch):
    client, knowledge, chat, generator = system
    first = note(knowledge, "项目部署手册", "项目/部署/index.md")
    second = note(knowledge, "采购清单", "生活/采购/index.md")
    other = knowledge.repository.create_library("其他库")
    knowledge.ingest(other.id, "index.md", b"other library")
    monkeypatch.setattr(knowledge.embedder, "query", lambda *_: pytest.fail("must not embed"))
    monkeypatch.setattr(chat, "prepare", lambda *_: pytest.fail("must not generate"))
    for query, ids in [
        ("部署", {first}),
        ("生活/", {second}),
        ("index.md", {first, second}),
        ("不存在", set()),
    ]:
        response = client.get("/api/libraries/default/reference-choices", params={"q": query})
        assert response.status_code == 200
        result = response.json()
        assert {row["document_id"] for row in result["items"]} == ids
        assert result["total"] == len(ids)
        assert all(
            set(row) == {"document_id", "filename", "title", "path", "kind"}
            for row in result["items"]
        )
    assert generator.calls == 0


def test_choices_are_stably_paged_and_reflect_deletion(system):
    client, knowledge, *_ = system
    ids = [note(knowledge, f"笔记 {index:02}", f"笔记/{index:02}/index.md") for index in range(23)]
    path = "/api/libraries/default/reference-choices"
    first = client.get(path).json()
    second = client.get(path, params={"offset": 20}).json()
    assert len(first["items"]) == 20 and len(second["items"]) == 3
    assert first["total"] == second["total"] == 23
    assert [row["document_id"] for row in first["items"] + second["items"]] == ids
    knowledge.delete("default", ids[0])
    result = client.get(path).json()
    assert result["total"] == 22 and ids[0] not in {row["document_id"] for row in result["items"]}


@pytest.mark.parametrize("params", [{"limit": 51}, {"limit": 0}, {"offset": -1}, {"q": "a" * 401}])
def test_choices_reject_unbounded_requests(system, params):
    client, *_ = system
    assert client.get("/api/libraries/default/reference-choices", params=params).status_code == 422


def test_choices_require_authentication_and_valid_library(system):
    client, *_ = system
    path = "/api/libraries/default/reference-choices"
    assert client.get(path, headers={"Authorization": ""}).status_code == 401
    assert client.get("/api/libraries/missing/reference-choices").status_code == 404
