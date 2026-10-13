import json
from dataclasses import replace

import pytest

from edge_knowledge.application.backup import BackupService
from edge_knowledge.application.maintenance import LibraryMaintenance
from edge_knowledge.domain.models import AppError
from edge_knowledge.domain.query import QuerySpec
from edge_knowledge.infrastructure.archive import FileArchiveStore
from edge_knowledge.infrastructure.backup import ZipBackupCodec
from edge_knowledge.infrastructure.catalog import SQLiteDocumentCatalog
from edge_knowledge.infrastructure.metadata import YAMLMetadataReader


def upload(client, name, meta, text="shared phrase"):
    return client.post(
        "/api/libraries/default/documents",
        files={"file": (name, f"---\n{meta}\n---\n\n{text}".encode())},
    ).json()["document"]["id"]


def execute(client, plan, **scope):
    return client.post(
        "/api/catalog/query", json={"question": "查询本地资料", "query_plan": plan, **scope}
    )


@pytest.fixture
def inventory(system):
    client, knowledge, chat, generator = system
    upload(
        client,
        "one.md",
        "title: First\ncreatedAt: 2026-09-02\nupdatedAt: 2026-10-12\n"
        "tags: [python, work]\nhours: 2.5",
    )
    upload(client, "two.md", "title: Second\ncreatedAt: 2026-09-30\ntags:\n  - python\nhours: 3.5")
    upload(
        client,
        "three.md",
        "title: Third\ncreatedAt: 2026-10-01\ntags: [personal]\nhours: not-recorded",
    )
    knowledge.embedder.query = lambda _: (_ for _ in ()).throw(
        AssertionError("Statistics must not embed")
    )
    return system


def test_count_boolean_conditions_and_range_are_not_limited_by_preview(inventory):
    client, _, _, generator = inventory
    plan = {
        "operation": "aggregate",
        "limit": 1,
        "where": {
            "all": [
                {"field": "tags", "op": "eq", "value": "python"},
                {"field": "authored_date", "op": "gte", "value": "2026-09-01"},
                {"field": "authored_date", "op": "lt", "value": "2026-10-01"},
                {
                    "any": [
                        {"field": "title", "op": "contains", "value": "first"},
                        {"field": "title", "op": "eq", "value": "Second"},
                    ]
                },
            ]
        },
    }
    result = execute(client, plan).json()
    assert result["query"]["result"]["value"] == 2
    assert len(result["sources"]) == 1
    assert generator.calls == 0


@pytest.mark.parametrize("metric,expected", [("sum", 6), ("avg", 3), ("min", 2.5), ("max", 3.5)])
def test_numeric_aggregations_ignore_missing_numbers_instead_of_zero(inventory, metric, expected):
    client, *_ = inventory
    result = execute(
        client, {"operation": "aggregate", "metric": metric, "metric_field": "metadata.hours"}
    ).json()
    assert result["query"]["result"]["value"] == expected
    assert result["query"]["result"]["missing_numeric"] == 1


def test_group_by_month_and_multi_tag_deduplication(inventory):
    client, *_ = inventory
    result = execute(client, {"operation": "aggregate", "group_by": "month"}).json()
    assert result["query"]["result"]["groups"] == [
        {"key": "2026-09", "value": 2, "count": 2, "missing_numeric": 0},
        {"key": "2026-10", "value": 1, "count": 1, "missing_numeric": 0},
    ]
    tags = execute(client, {"operation": "aggregate", "group_by": "tags"}).json()
    assert tags["query"]["result"]["value"] == 3
    assert {g["key"]: g["count"] for g in tags["query"]["result"]["groups"]} == {
        "personal": 1,
        "python": 2,
        "work": 1,
    }
    assert "不能直接相加" in tags["content"]


def test_literal_text_filter_sort_and_stable_paging(inventory):
    client, *_ = inventory
    result = execute(
        client,
        {
            "operation": "list",
            "order_by": "title",
            "descending": True,
            "limit": 1,
            "offset": 1,
            "where": {"field": "text", "op": "contains", "value": "shared phrase"},
        },
    ).json()
    assert result["query"]["result"]["total"] == 3
    assert result["query"]["result"]["rows"][0]["title"] == "Second"


def test_derived_index_survives_restart_and_is_rebuilt_without_reembedding(inventory, monkeypatch):
    client, knowledge, chat, _ = inventory
    mirror = chat.queries.mirror
    reloaded = SQLiteDocumentCatalog(mirror.catalog.path)
    assert len(reloaded.versions("default")) == 3
    mirror.catalog = reloaded
    monkeypatch.setattr(
        mirror.reader, "read", lambda _: (_ for _ in ()).throw(AssertionError("No reparsing"))
    )
    assert execute(client, {"operation": "aggregate"}).json()["query"]["result"]["total"] == 3
    monkeypatch.undo()
    mirror.catalog.prune("default", [])
    assert execute(client, {"operation": "aggregate"}).json()["query"]["result"]["total"] == 3
    id = knowledge.repository.documents("default")[0].id
    knowledge.delete("default", id)
    assert execute(client, {"operation": "aggregate"}).json()["query"]["result"]["total"] == 2


def test_schema_is_scoped_and_has_types_but_no_document_content(inventory):
    client, knowledge, *_ = inventory
    schema = client.get("/api/catalog/schema").json()
    assert {x["field"] for x in schema["custom_fields"]} >= {"metadata.hours", "metadata.tags"}
    assert "shared phrase" not in json.dumps(schema)
    other = knowledge.repository.create_library("Other").id
    assert (
        client.get("/api/catalog/schema", params={"library_id": other}).json()["custom_fields"]
        == []
    )
    assert client.get("/api/catalog/schema", headers={"Authorization": ""}).status_code == 401


def test_numeric_range_does_not_include_unrecorded_text_and_empty_tags_are_missing(inventory):
    client, *_ = inventory
    result = execute(
        client,
        {"operation": "aggregate", "where": {"field": "metadata.hours", "op": "gt", "value": 3}},
    ).json()
    assert result["query"]["result"]["total"] == 1
    upload(client, "untagged.md", "title: Untagged")
    result = execute(
        client, {"operation": "aggregate", "where": {"field": "tags", "op": "missing"}}
    ).json()
    assert result["query"]["result"]["total"] == 1
    assert (
        execute(
            client,
            {
                "operation": "aggregate",
                "where": {"field": "authored_date", "op": "gte", "value": "2026-02-30"},
            },
        ).status_code
        == 422
    )


def test_grouping_custom_metadata_and_sorting_group_counts(inventory):
    client, *_ = inventory
    result = execute(
        client,
        {"operation": "aggregate", "group_by": "tags", "order_by": "count", "descending": True},
    ).json()
    assert result["query"]["result"]["groups"][0]["key"] == "python"
    result = execute(client, {"operation": "aggregate", "group_by": "metadata.hours"}).json()
    assert result["query"]["result"]["group_total"] == 3


@pytest.mark.parametrize(
    "plan",
    [
        {"operation": "delete"},
        {"operation": "aggregate", "sql": "DROP TABLE documents"},
        {"operation": "aggregate", "library_id": "another"},
        {
            "operation": "aggregate",
            "where": {"field": "path);DROP TABLE documents", "op": "eq", "value": "x"},
        },
        {"operation": "aggregate", "where": {"field": "title", "op": {}, "value": "x"}},
        {"operation": []},
        {"operation": "aggregate", "where": {"any": []}},
        {"operation": "aggregate", "text_query": "about Python"},
        {"operation": "aggregate", "metric": "eval"},
        {"operation": "list", "limit": 51},
    ],
)
def test_invalid_or_permission_expanding_plans_fail_closed(inventory, plan):
    client, *_ = inventory
    assert execute(client, plan).status_code == 422
    assert execute(client, {"operation": "aggregate"}).json()["query"]["result"]["total"] == 3


def test_values_are_bound_and_unknown_metadata_keys_do_not_become_false_zero_counts(inventory):
    client, *_ = inventory
    result = execute(
        client,
        {
            "operation": "aggregate",
            "where": {"field": "title", "op": "contains", "value": "');DROP TABLE documents;--"},
        },
    )
    assert result.status_code == 200 and result.json()["query"]["result"]["total"] == 0
    assert (
        execute(
            client,
            {"operation": "aggregate", "metric": "sum", "metric_field": "metadata.not_a_field"},
        ).status_code
        == 422
    )


class PlannerDouble:
    def __init__(self, spec):
        self.spec, self.calls, self.contexts = spec, 0, []

    def plan(self, question, context):
        self.calls += 1
        self.contexts.append(context)
        return self.spec


def test_cloud_planner_is_explicit_ai_only_and_cannot_supply_its_own_count(inventory):
    client, _, chat, generator = inventory
    planner = chat.queries.planner = PlannerDouble(
        {
            "operation": "aggregate",
            "metric": "sum",
            "metric_field": "metadata.hours",
            "where": {"field": "tags", "op": "eq", "value": "python"},
        }
    )
    question = "按 python 标签汇总所有投入的工时"
    local = client.post(
        "/api/local-query",
        json={"question": "2026 年 9 月写了多少篇 Python 笔记", "allow_planning": True},
    )
    assert local.status_code == 200 and planner.calls == 0
    client.patch("/api/settings", json={"api_key": "test-key"})
    result = client.post("/api/query", json={"question": question, "allow_planning": True})
    assert result.status_code == 200 and planner.calls == 1 and generator.calls == 0
    assert "**6.0**" in result.text and "已调用 DeepSeek 规划" in result.text
    assert "shared phrase" not in json.dumps(planner.contexts)
    planner.spec = {"operation": "aggregate", "result": 999999}
    bad = client.post("/api/query", json={"question": question, "allow_planning": True})
    assert bad.status_code == 422 and generator.calls == 0


def test_scope_validation_happens_before_ai_planning(inventory):
    client, knowledge, chat, _ = inventory
    planner = chat.queries.planner = PlannerDouble({"operation": "aggregate"})
    doc = knowledge.repository.documents("default")[0].id
    other = knowledge.repository.create_library("Other").id
    client.patch("/api/settings", json={"api_key": "test-key"})
    result = client.post(
        "/api/query",
        json={
            "question": "复杂问题",
            "library_id": other,
            "document_ids": [doc],
            "allow_planning": True,
        },
    )
    assert result.status_code == 404 and planner.calls == 0


def test_planner_cannot_downgrade_known_statistics_to_a_generated_answer(inventory):
    client, _, chat, generator = inventory
    chat.queries.planner = PlannerDouble({"operation": "answer", "text_query": "Python"})
    client.patch("/api/settings", json={"api_key": "test-key"})
    response = client.post(
        "/api/query",
        json={"question": "2026 年 9 月写了多少篇 Python 笔记", "allow_planning": True},
    )
    assert response.status_code == 422 and generator.calls == 0
    assert response.json()["error"]["code"] == "invalid_planner_operation"


def test_metadata_reader_rejects_aliases_tags_duplicates_and_keeps_flat_arrays():
    reader = YAMLMetadataReader()
    assert reader.read("---\ntags: [work, notes]\nhours: 2.5\n---") == {
        "tags": ["work", "notes"],
        "hours": 2.5,
    }
    for body in [
        "x: &x [a]\ny: *x",
        "x: !!python/object/apply:os.system [echo]",
        "created: 2026-09-01\ncreated: 2026-10-01",
    ]:
        assert reader.read("---\n" + body + "\n---") == {}
    with pytest.raises(AppError):
        QuerySpec.parse(
            {
                "operation": "aggregate",
                "where": {"field": "size", "op": "gt", "value": float("nan")},
            }
        )


def test_archive_restore_and_backup_restore_keep_catalog_consistent(inventory):
    client, knowledge, chat, _ = inventory
    archive = FileArchiveStore(chat.queries.mirror.catalog.path.parent / "archive")
    maintenance = LibraryMaintenance(knowledge, archive)
    id = knowledge.repository.documents("default")[0].id
    maintenance.archive_documents("default", [id])
    assert execute(client, {"operation": "aggregate"}).json()["query"]["result"]["total"] == 2
    maintenance.restore_documents("default", [id])
    assert execute(client, {"operation": "aggregate"}).json()["query"]["result"]["total"] == 3
    backup = BackupService(knowledge, archive, ZipBackupCodec(), "test-model", 3)
    restored = backup.restore(backup.export({}))["mapping"]["default"]
    result = execute(
        client,
        {"operation": "aggregate", "metric": "sum", "metric_field": "metadata.hours"},
        library_id=restored,
    )
    assert result.status_code == 200 and result.json()["query"]["result"]["value"] == 6
    assert len(chat.queries.mirror.catalog.versions(restored)) == 3


def test_import_month_uses_requested_timezone_at_the_month_boundary(inventory):
    client, knowledge, *_ = inventory
    doc = knowledge.repository.documents("default")[0]
    record = knowledge.repository.record("default", doc.id)
    knowledge.repository.delete("default", doc.id)
    knowledge.repository.add(
        "default", replace(doc, created_at="2026-09-30T18:00:00Z"), record.chunks, record.vectors
    )
    plan = {
        "operation": "aggregate",
        "where": {
            "all": [
                {"field": "imported_date", "op": "gte", "value": "2026-10-01"},
                {"field": "imported_date", "op": "lt", "value": "2026-10-02"},
            ]
        },
    }
    asia = execute(client, plan, timezone="Asia/Shanghai", document_ids=[doc.id]).json()
    utc = execute(client, plan, timezone="UTC", document_ids=[doc.id]).json()
    assert asia["query"]["result"]["total"] == 1
    assert utc["query"]["result"]["total"] == 0


def test_failed_catalog_write_rolls_back_new_document_without_losing_existing_data(
    inventory, monkeypatch
):
    client, knowledge, chat, _ = inventory
    ids = {doc.id for doc in knowledge.repository.documents("default")}

    def fail(*args):
        raise OSError("fixture failure")

    monkeypatch.setattr(chat.queries.mirror.catalog, "upsert", fail)
    with pytest.raises(OSError):
        knowledge.ingest("default", "new.md", b"New document")
    assert {doc.id for doc in knowledge.repository.documents("default")} == ids


def test_media_search_routes_from_typed_selection_without_reparsing_the_query(system):
    client, _, chat, _ = system
    from dataclasses import asdict
    from pathlib import Path

    from edge_knowledge.domain.models import SearchHit

    image = client.post(
        "/api/libraries/default/documents",
        files={
            "file": ("chart.png", (Path(__file__).parent / "fixtures/parcel-demo.png").read_bytes())
        },
    ).json()["document"]["id"]
    calls = []

    class Semantic:
        def search(self, *args):
            calls.append(args)
            return {
                "sources": [
                    asdict(
                        SearchHit(
                            image, "chart.png", "fixture OCR", "图片文字", 1, 0.81, "image", "ready"
                        )
                    )
                ]
            }

    chat.semantic = Semantic()
    response = client.post("/api/local-query", json={"question": "查找快递图片"})
    assert response.status_code == 200
    assert calls[0][1] == "快递" and calls[0][4] == [image] and calls[0][5] == ["image"]
