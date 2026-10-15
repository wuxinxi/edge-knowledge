import asyncio
import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from edge_knowledge.domain.models import AppError, QueryPlan
from edge_knowledge.domain.planning import calendar_constraints, ground_calendar_plan
from edge_knowledge.domain.query import Predicate, QuerySpec, query_contract
from edge_knowledge.infrastructure.generators import SelectedGenerator
from edge_knowledge.infrastructure.local_llm import (
    LlamaRuntime,
    LocalGenerator,
    LocalQueryPlanner,
    LocalSession,
)
from edge_knowledge.infrastructure.settings import JsonSettingsStore


class Planner:
    def __init__(self, output):
        self.output, self.calls = output, []

    def plan(self, question, context):
        self.calls.append(context)
        return self.output


def test_local_is_default_and_model_paths_are_explicit(tmp_path):
    settings = JsonSettingsStore(tmp_path)
    assert settings.read()["generation_provider"] == "local"
    assert not settings.read()["api_key_configured"]
    for change in [
        {"generation_provider": "other"},
        {"local_model_path": "relative.gguf"},
        {"local_model_path": "/tmp/model.py"},
        {"local_context_size": 99999},
    ]:
        with pytest.raises(AppError):
            settings.update(change)


def test_local_runtime_missing_model_does_not_start_process_or_read_cloud_key(
    tmp_path, monkeypatch
):
    settings = JsonSettingsStore(tmp_path)
    runtime = LlamaRuntime(settings)
    monkeypatch.setattr("subprocess.Popen", lambda *_args, **_kw: pytest.fail("must not spawn"))
    with pytest.raises(AppError) as exc:
        runtime.session()
    assert exc.value.code == "local_model_missing"
    assert not runtime.status()["loaded"]
    runtime.close()


def test_runtime_owns_authenticated_child_and_cleans_up_on_failure(tmp_path, monkeypatch):
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    settings = JsonSettingsStore(tmp_path, local_model_path=str(model))
    runtime = LlamaRuntime(settings)
    monkeypatch.setattr(runtime, "_binary", lambda _: "/trusted/llama-server")
    captured = []

    class FailedChild:
        def __init__(self, args, **kwargs):
            captured.append((args, kwargs))

        def poll(self):
            return 1

    monkeypatch.setattr("subprocess.Popen", FailedChild)
    with pytest.raises(AppError) as exc:
        runtime.session()
    assert exc.value.code == "local_start_failed"
    args, options = captured[0]
    assert args[args.index("--host") + 1] == "127.0.0.1"
    assert "--offline" in args and "--log-disable" in args
    assert args[args.index("--reasoning") + 1] == "auto"
    assert args[args.index("--reasoning-format") + 1] == "deepseek"
    assert args[args.index("--reasoning-budget") + 1] == "256"
    assert "--api-key-file" in args and "--api-key" not in args
    assert not options.get("shell")
    assert not Path(args[args.index("--api-key-file") + 1]).exists()
    assert runtime.current is None and runtime.process is None


def test_actual_tokenizer_budget_rejects_before_generation(tmp_path, monkeypatch):
    runtime = LlamaRuntime(JsonSettingsStore(tmp_path))
    captured = []

    def respond(request):
        captured.append(request.url.path)
        return httpx.Response(
            200,
            json={"prompt": "formatted"}
            if request.url.path == "/apply-template"
            else {"tokens": list(range(7000))},
        )

    real = httpx.Client
    monkeypatch.setattr(
        "edge_knowledge.infrastructure.local_llm.httpx.Client",
        lambda **kwargs: real(transport=httpx.MockTransport(respond), **kwargs),
    )
    with pytest.raises(AppError) as exc:
        runtime.check_budget(LocalSession("http://127.0.0.1:1/v1", "token", 8192), [], 1536)
    assert exc.value.code == "local_context_exceeded"
    assert captured == ["/apply-template", "/tokenize"]
    runtime.close()


def test_local_planner_uses_schema_and_rejects_truncated_or_invalid_plans(monkeypatch):
    requests = []
    output = {"operation": "aggregate", "group_by": "tags"}
    finish = "stop"
    runtime = SimpleNamespace(
        session=lambda: LocalSession("http://127.0.0.1:1/v1", "local-token", 8192),
        check_budget=lambda *_: None,
    )

    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)
            kwargs["http_client"].close()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def create(self, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason=finish, message=SimpleNamespace(content=json.dumps(output))
                    )
                ]
            )

    monkeypatch.setattr("edge_knowledge.infrastructure.local_llm.OpenAI", Client)
    planner = LocalQueryPlanner(runtime)
    context = {
        "contract": query_contract(),
        "today": "2026-10-13",
        "custom_fields": [],
        "allow_answer": False,
    }
    assert planner.plan("按标签分组", context)["group_by"] == "tags"
    assert requests[0]["response_format"]["schema"]["additionalProperties"] is False
    assert "local-token" not in json.dumps(requests)
    finish = "length"
    with pytest.raises(AppError) as exc:
        planner.plan("问题", context)
    assert exc.value.code == "invalid_local_plan"
    finish, output = "stop", {"operation": "delete", "sql": "DELETE"}
    with pytest.raises(AppError):
        planner.plan("问题", context)


@pytest.mark.parametrize("goal", ["answer_current", "other", "invalid"])
def test_reference_goal_is_bounded_and_precedes_complex_query_planning(monkeypatch, goal):
    requests, budgets = [], []
    runtime = SimpleNamespace(
        session=lambda: LocalSession("http://127.0.0.1:1/v1", "local-token", 8192),
        check_budget=lambda _, messages, tokens, *thinking: budgets.append(tokens),
    )

    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)
            kwargs["http_client"].close()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def create(self, **kwargs):
            requests.append(kwargs)
            value = (
                {"goal": goal}
                if len(requests) == 1
                else {"operation": "search", "text_query": "原文"}
            )
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content=json.dumps(value)),
                    )
                ]
            )

    monkeypatch.setattr("edge_knowledge.infrastructure.local_llm.OpenAI", Client)
    context = {
        "contract": query_contract(),
        "allow_answer": True,
        "current_documents": [
            {
                "title": "对比说明",
                "filename": "note.md",
                "path": "notes/note.md",
                "body": "must not send",
                "document_id": "private-id",
            }
        ],
    }
    planner = LocalQueryPlanner(runtime)
    if goal == "invalid":
        with pytest.raises(AppError) as exc:
            planner.plan("任意选择问题", context)
        assert exc.value.code == "invalid_local_plan" and len(requests) == 1
    else:
        result = planner.plan("任意选择问题", context)
        assert result["operation"] == ("answer" if goal == "answer_current" else "search")
        if goal == "answer_current":
            assert result["use_context"] and result["source_scope"] == "full_document"
            assert budgets == [512] and len(requests) == 1
        else:
            assert budgets == [512, 1400] and len(requests) == 2
    encoded = json.dumps(requests[0]["messages"])
    assert "must not send" not in encoded and "private-id" not in encoded
    assert requests[0]["response_format"]["schema"]["additionalProperties"] is False


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("empty_attempts", [0, 1, 2])
@pytest.mark.parametrize(
    "content_format", ["plain", "orphan_close", "inline_thought", "unterminated_thought", "literal"]
)
def test_local_reasoning_is_budgeted_but_only_final_content_is_emitted(
    monkeypatch, stream, empty_attempts, content_format
):
    requests, budgets = [], []
    runtime = SimpleNamespace(
        session=lambda: LocalSession("http://127.0.0.1:1/v1", "local-token", 8192),
        check_budget=lambda *args: budgets.append(args),
    )

    class Response:
        def __init__(self, content):
            self.content = content
            self.choices = [
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=content, reasoning_content="private reasoning"),
                )
            ]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def __aiter__(self):
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=None, reasoning_content="private reasoning"),
                        finish_reason=None,
                    )
                ]
            )
            # Exercise every possible split inside the native template markers.
            for character in self.content or "":
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content=character),
                            finish_reason=None,
                        )
                    ]
                )
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=None),
                        finish_reason="stop",
                    )
                ]
            )

    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)
            self.http_client = kwargs["http_client"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            await self.http_client.aclose()

        async def create(self, **kwargs):
            requests.append(kwargs)
            content = "" if len(requests) <= empty_attempts else expected
            if content_format == "orphan_close":
                content = "</think>" + content
            elif content_format == "inline_thought":
                content = "<think>private reasoning</think>" + content
            elif content_format == "unterminated_thought" and not content:
                content = "<think>private reasoning without final answer"
            return Response(content)

    monkeypatch.setattr("edge_knowledge.infrastructure.local_llm.AsyncOpenAI", Client)
    plan = QueryPlan([], "给定依据", "edge-local", "", "", stream, provider="local")
    expected = (
        "示例：`<think>literal</think>` [1]" if content_format == "literal" else "\n  最终答案 [1]"
    )

    async def collect():
        return [part async for part in LocalGenerator(runtime).generate(plan)]

    if empty_attempts == 2:
        with pytest.raises(AppError) as exc:
            asyncio.run(collect())
        assert exc.value.code == "local_empty_answer"
    else:
        assert "".join(asyncio.run(collect())) == expected
    assert len(requests) == (1 if empty_attempts == 0 else 2)
    assert all(request["messages"] == requests[0]["messages"] for request in requests)
    assert requests[0]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
    assert budgets[0][-2:] == (1536, True)
    if empty_attempts:
        assert requests[1]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


def test_local_planning_in_search_mode_never_uses_cloud_even_if_cloud_is_selected(system):
    client, knowledge, chat, cloud = system
    knowledge.ingest("default", "note.md", b"---\ncreatedAt: 2026-09-10\ntags: [work]\n---\nhello")
    local = chat.queries.local_planner = Planner({"operation": "aggregate", "group_by": "tags"})
    remote = chat.queries.planner = Planner({"operation": "answer"})
    response = client.post(
        "/api/local-query",
        json={"question": "统计2026年9月份创建的笔记，按标签分组", "allow_planning": True},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["query"]["planner"] == "local_model" and result["query"]["result"]["total"] == 1
    assert local.calls and not remote.calls and cloud.calls == 0
    assert result["query"]["result"]["groups"][0]["key"] == "work"
    assert "hello" not in json.dumps(local.calls)
    assert not knowledge.settings.api_key()


def test_missing_year_is_clarified_before_model_and_changed_year_is_rejected(system):
    client, knowledge, chat, _ = system
    knowledge.ingest("default", "note.md", b"---\ncreatedAt: 2026-09-10\n---\nnote")
    local = chat.queries.local_planner = Planner({"operation": "aggregate"})
    r = client.post(
        "/api/local-query", json={"question": "统计九月份创建的笔记，按标签分组"}
    ).json()
    assert r["kind"] == "clarification" and not local.calls
    local.output = {
        "operation": "aggregate",
        "where": {"field": "created_date", "op": "gte", "value": "2025-09-01"},
    }
    r = client.post("/api/local-query", json={"question": "统计2026年9月份创建的笔记，按标签分组"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "ungrounded_plan_date"


def test_explicit_calendar_slots_are_preserved_for_both_local_and_cloud_plans():
    constraints = calendar_constraints("统计2026年九月份创建的笔记，按标签分组", date(2026, 10, 13))
    grounded = ground_calendar_plan(QuerySpec("aggregate", group_by="tags"), constraints)
    predicates = grounded.where.all
    assert Predicate("created_date", "gte", "2026-09-01") in predicates
    assert Predicate("created_date", "lt", "2026-10-01") in predicates
    assert Predicate("kind", "eq", "document") in predicates


def test_provider_snapshot_routes_generation_and_never_falls_back(system):
    _, knowledge, *_ = system

    class Generator:
        def __init__(self, fail=False):
            self.calls, self.fail = 0, fail

        async def generate(self, _):
            self.calls += 1
            if self.fail:
                raise AppError("local failed", 503)
            yield "answer"

    local, cloud = Generator(True), Generator()
    router = SelectedGenerator(knowledge.settings, local, cloud)
    plan = QueryPlan([], "question", "edge-local", "", "", True, provider="local")

    async def run(value):
        return [part async for part in router.generate(value)]

    with pytest.raises(AppError):
        asyncio.run(run(plan))
    assert local.calls == 1 and cloud.calls == 0
    assert asyncio.run(run(replace(plan, provider="deepseek"))) == ["answer"]
    assert cloud.calls == 1


def test_local_generation_execution_event_has_provider_without_cloud_key(system):
    client, knowledge, chat, generator = system
    knowledge.ingest(
        "default", "deployment.md", "# 部署步骤\n安装依赖，启动服务，检查健康状态。".encode()
    )
    knowledge.settings.update({"generation_provider": "local"})
    chat.queries.local_planner = Planner({"operation": "answer", "text_query": "部署步骤"})
    result = client.post("/api/query", json={"question": "总结部署步骤", "allow_planning": True})
    assert result.status_code == 200
    events = [
        json.loads(line[6:]) for line in result.text.splitlines() if line.startswith("data: ")
    ]
    assert {
        "type": "execution",
        "location": "local",
        "planner": "local_model",
        "generator": "local",
        "result_kind": "answer",
    } in events
    assert generator.calls == 1 and "没有调用 DeepSeek" in result.text
    assert not knowledge.settings.api_key()


@pytest.mark.parametrize(
    "question",
    [
        "2026-09-03的笔记",
        "2026年9月3号创建的笔记",
        "2026年第三季度的笔记",
        "2026年9月和10月的笔记",
        "2025年或2026年9月的笔记",
    ],
)
def test_calendar_grounding_only_claims_unambiguous_month_or_year(question):
    assert calendar_constraints(question, date(2026, 10, 13)) == {}
