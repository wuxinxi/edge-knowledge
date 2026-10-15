"""Exercise the native generator seam, including streaming JSON transport boundaries."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from edge_knowledge.domain.models import AppError, HistoryMessage, QueryPlan
from edge_knowledge.infrastructure.local_llm import LocalGenerator, LocalSession


def native(monkeypatch, raw, reason="stop"):
    state = SimpleNamespace(
        requests=[], budgets=[], position=0, response_closed=False, client_closed=False
    )
    runtime = SimpleNamespace(
        session=lambda: LocalSession("http://127.0.0.1:1/v1", "private-token", 8192),
        check_budget=lambda *args: state.budgets.append(args),
    )

    class Response:
        choices = [SimpleNamespace(message=SimpleNamespace(content=raw), finish_reason=reason)]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            state.response_closed = True

        async def __aiter__(self):
            for position, character in enumerate(raw, 1):
                state.position = position
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
                        finish_reason=reason,
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
            state.client_closed = True

        async def create(self, **kwargs):
            state.requests.append(kwargs)
            return Response()

    monkeypatch.setattr("edge_knowledge.infrastructure.local_llm.AsyncOpenAI", Client)
    return LocalGenerator(runtime), state


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("escape", [False, True])
def test_native_envelope_displays_conclusion_before_details(monkeypatch, stream, reverse, escape):
    answer, details = (
        "首选最后一项 🚀 [1]。",
        '依据 [1]。\n代码：`{"answer":"a\\b","details":"引号"}` [1]。',
    )
    fields = {"answer": answer, "details": details}
    if reverse:
        fields = dict(reversed(list(fields.items())))
    raw = json.dumps(fields, ensure_ascii=escape)
    generator, state = native(monkeypatch, raw)
    history = [HistoryMessage("user", "保留前一轮要求"), HistoryMessage("assistant", "此前回答")]
    plan = QueryPlan(
        [], "本轮证据与要求", "edge-local", "", "", stream, history=history, provider="local"
    )
    parts, positions = [], []

    async def collect():
        async for part in generator.generate(plan):
            parts.append(part)
            positions.append(state.position)

    asyncio.run(collect())
    assert "".join(parts) == answer + "\n\n" + details
    assert state.client_closed
    if stream:
        assert state.response_closed
        assert positions[0] < len(raw), "正常正文必须持续流出，不能等待整个 JSON 完成"
    request = state.requests[0]
    assert request["response_format"]["schema"]["additionalProperties"] is False
    assert request["messages"][1:3] == [
        {"role": item.role, "content": item.content} for item in history
    ]
    assert request["messages"][-1]["content"] == plan.prompt
    assert state.budgets[0][1] == request["messages"]
    assert "private-token" not in json.dumps(request["messages"])


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "raw,reason",
    [
        ('{"answer": 5, "details": "body"}', "stop"),
        ('{"answer": " ", "details": "body"}', "stop"),
        ('{"answer": "ok", "details": "body", "extra": true}', "stop"),
        ('{"answer": "ok"}', "stop"),
        ('{"answer": "ok", "answer": "ok", "details": "body"}', "stop"),
        pytest.param(json.dumps({"answer": "x" * 301, "details": ""}), "stop", id="answer_limit"),
        ("plain unstructured text", "stop"),
        ('{"answer": "ok", "details": "unfinished', "stop"),
        ('{"answer": "partial", "details": "unfinished', "length"),
    ],
)
def test_invalid_or_incomplete_envelope_cannot_succeed(monkeypatch, stream, raw, reason):
    generator, state = native(monkeypatch, raw, reason)
    plan = QueryPlan([], "evidence", "edge-local", "", "", stream, provider="local")
    parts = []

    async def collect():
        async for part in generator.generate(plan):
            parts.append(part)

    with pytest.raises(AppError) as exc:
        asyncio.run(collect())
    assert exc.value.code in {"invalid_local_answer", "local_answer_incomplete"}
    assert state.client_closed
    if stream:
        assert state.response_closed
    assert not any('"answer"' in part or '"details"' in part for part in parts)


@pytest.mark.parametrize("stream", [False, True])
def test_incomplete_native_answer_has_error_event_without_done(system, monkeypatch, stream):
    client, knowledge, chat, _ = system
    document = knowledge.ingest("default", "note.md", b"original evidence")["document"]["id"]
    knowledge.settings.update({"generation_provider": "local", "stream": stream})
    chat.generator, _ = native(monkeypatch, '{"answer":"partial [1]","details":"cut', "length")
    response = client.post(
        "/api/query",
        json={
            "question": "说明本轮资料",
            "document_ids": [document],
            "allow_planning": True,
            "query_plan": {"operation": "answer", "source_scope": "full_document"},
        },
    )
    events = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert any(event["type"] == "error" for event in events)
    assert not any(event["type"] == "done" for event in events)
