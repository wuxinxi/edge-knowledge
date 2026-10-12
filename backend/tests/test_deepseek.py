import asyncio
import base64
import json
from dataclasses import replace

import httpx
import pytest
from openai import AsyncOpenAI

from edge_knowledge.domain.models import (
    AppError,
    HistoryMessage,
    ImageAttachment,
    QueryPlan,
    SearchHit,
)
from edge_knowledge.infrastructure import deepseek


def plan(stream):
    return QueryPlan(
        [], "问题与引用", "deepseek-chat", "https://api.deepseek.com", "test-key", stream
    )


def test_real_sdk_nonstream_and_stream_decoding(monkeypatch):
    async def run(stream):
        def upstream(request):
            body = json.loads(request.content)
            assert body["stream"] is stream
            assert body["messages"][0]["role"] == "system"
            assert body["messages"][1] == {"role": "user", "content": "上一问"}
            assert body["messages"][2] == {"role": "assistant", "content": "上一答"}
            assert body["messages"][3]["content"] == "问题与引用"
            if not stream:
                return httpx.Response(
                    200,
                    json={
                        "id": "chat-1",
                        "object": "chat.completion",
                        "created": 0,
                        "model": "deepseek-chat",
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": "答案 [1]"},
                                "finish_reason": "stop",
                            }
                        ],
                    },
                )
            chunks = [
                {
                    "id": "chat-1",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "deepseek-chat",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                }
                for delta in [
                    {"reasoning_content": "推理内容"},
                    {"content": "答案"},
                    {"content": " [1]"},
                ]
            ]
            data = (
                "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
            )
            return httpx.Response(200, text=data, headers={"Content-Type": "text/event-stream"})

        monkeypatch.setattr(
            deepseek,
            "AsyncOpenAI",
            lambda **kwargs: AsyncOpenAI(
                **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(upstream))
            ),
        )
        return [
            delta
            async for delta in deepseek.DeepSeekGenerator().generate(
                replace(
                    plan(stream),
                    history=[
                        HistoryMessage("user", "上一问"),
                        HistoryMessage("assistant", "上一答"),
                    ],
                )
            )
        ]

    assert asyncio.run(run(False)) == ["答案 [1]"]
    assert asyncio.run(run(True)) == ["答案", " [1]"]


def test_upstream_error_does_not_echo_secret(monkeypatch):
    def upstream(request):
        return httpx.Response(401, json={"error": {"message": "secret-test-key", "type": "auth"}})

    monkeypatch.setattr(
        deepseek,
        "AsyncOpenAI",
        lambda **kwargs: AsyncOpenAI(
            **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        ),
    )

    async def run():
        return [delta async for delta in deepseek.DeepSeekGenerator().generate(plan(True))]

    with pytest.raises(AppError) as caught:
        asyncio.run(run())
    assert "secret-test-key" not in caught.value.message


def test_real_sdk_vision_payload_is_user_content_with_source_mapping(monkeypatch):
    observed = []

    def upstream(request):
        body = json.loads(request.content)
        observed.append(body)
        content = body["messages"][1]["content"]
        assert content[0]["type"] == "text"
        assert content[1]["text"] == "资料 [2] 的图片：ticket.png"
        assert (
            content[2]["image_url"]["url"]
            == "data:image/png;base64," + base64.b64encode(b"test-image").decode()
        )
        assert isinstance(body["messages"][0]["content"], str)
        return httpx.Response(
            200,
            json={
                "id": "vision-1",
                "object": "chat.completion",
                "created": 0,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "图片答案 [2]"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    monkeypatch.setattr(
        deepseek,
        "AsyncOpenAI",
        lambda **kwargs: AsyncOpenAI(
            **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        ),
    )
    request = replace(
        plan(False),
        model="deepseek-flash",
        sources=[
            SearchHit("doc", "guide.md", "文字", "", 0, 0.9),
            SearchHit("image", "ticket.png", "", "", 0, 0.8, "image", "empty"),
        ],
        images=[ImageAttachment("image", "ticket.png", b"test-image", "image/png")],
    )

    async def run():
        return [delta async for delta in deepseek.DeepSeekGenerator().generate(request)]

    assert asyncio.run(run()) == ["图片答案 [2]"]
    assert len(observed) == 1


def test_text_model_guard_runs_before_cloud_client_creation(monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError("Should not create a cloud client")

    monkeypatch.setattr(deepseek, "AsyncOpenAI", forbidden)
    request = replace(plan(True), images=[ImageAttachment("id", "image.png", b"image")])

    async def run():
        return [delta async for delta in deepseek.DeepSeekGenerator().generate(request)]

    with pytest.raises(AppError) as error:
        asyncio.run(run())
    assert error.value.code == "image_model_unsupported"
