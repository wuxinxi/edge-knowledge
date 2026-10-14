"""Owned, authenticated loopback llama.cpp process; never falls back to the cloud."""

import atexit
import json
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock

import httpx
from openai import APIError, AsyncOpenAI, OpenAI

from edge_knowledge.application.ports import SettingsStore
from edge_knowledge.domain.models import AppError, ModelCapabilities, QueryPlan
from edge_knowledge.domain.query import FIELDS, OPS, QuerySpec
from edge_knowledge.infrastructure.deepseek import SYSTEM_PROMPT


def local_planning_messages(question: str, context: dict) -> list:
    prompt = (
        "只输出只读查询 JSON 计划，不直接回答。统计用 aggregate，查找原文用 search。"
        "allow_answer=true 时，知识问题、有哪些选择、解释、比较、总结都用 answer；"
        "search 只是查找资料，不会生成答案。text_query 保留核心主题和专业词，去掉问句套话，"
        "例如‘缓存实现有哪些’检索‘缓存实现’，不要只检索‘实现’或‘方案’。"
        "检查笔记/文档重复内容用 duplicates；threshold 默认0.9，禁止删除。"
        "duplicates 的 text_query 必须为空，日期、标签、文件夹范围用 where。"
        "月份筛选用 gte 起始日和 lt 次月1日，不能用 in 列表。"
        "created_date 创建日期，authored_date 写作日期，modified_date 修改日期。"
        "必须完整保留 required_date_conditions；未提供年份须 clarify，禁止猜测。"
        "标签分组为 group_by tags。图片上的文字通过 text_query 搜索，不用 title 或 filename 筛选。"
        "不要添加未要求的条件，默认 limit=20；不要翻译关键词。"
        "allow_answer=false 时只查找资料，不能用 answer。禁止 SQL、文件操作、自编结果。"
    )
    definitions = {
        "today": context.get("today"),
        "timezone": context.get("timezone"),
        "fields": context["contract"]["fields"],
        "custom_fields": context.get("custom_fields", []),
        "allow_answer": context.get("allow_answer", True),
        "required_date_conditions": context.get("required_date_conditions", []),
    }
    messages = [{"role": "system", "content": prompt + json.dumps(definitions, ensure_ascii=False)}]
    examples = [
        (
            "统计2025年2月创建的笔记，按标签分组。",
            {
                "operation": "aggregate",
                "metric": "count",
                "group_by": "tags",
                "where": {
                    "all": [
                        {"field": "kind", "op": "eq", "value": "document"},
                        {"field": "created_date", "op": "gte", "value": "2025-02-01"},
                        {"field": "created_date", "op": "lt", "value": "2025-03-01"},
                    ]
                },
            },
        ),
        (
            "九月份写了多少篇笔记？",
            {"operation": "clarify", "clarification": "请问是哪一年的九月？"},
        ),
        (
            "找出海边日落图片",
            {
                "operation": "search",
                "text_query": "海边日落",
                "where": {"field": "kind", "op": "eq", "value": "image"},
            },
        ),
    ]
    examples.append(
        (
            "这些笔记有没有重复的？",
            {
                "operation": "duplicates",
                "where": {"field": "kind", "op": "eq", "value": "document"},
            },
        )
    )
    if context.get("allow_answer", True):
        examples.append(
            (
                "概括部署流程",
                {"operation": "answer", "text_query": "部署流程", "where": {"all": []}},
            )
        )
        examples.append(
            (
                "数据库备份方式有哪些？",
                {"operation": "answer", "text_query": "数据库备份", "where": {"all": []}},
            )
        )
    for q, answer in examples:
        messages.extend(
            [
                {"role": "user", "content": q},
                {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)},
            ]
        )
    messages.append({"role": "user", "content": question})
    return messages


@dataclass(frozen=True)
class LocalSession:
    base_url: str
    api_key: str = field(repr=False)
    context_size: int


class LlamaRuntime:
    def __init__(self, settings: SettingsStore):
        self.settings = settings
        self.lock = RLock()
        self.process: subprocess.Popen | None = None
        self.configuration = None
        self.current: LocalSession | None = None
        self.key_path: Path | None = None
        atexit.register(self.close)

    def status(self) -> dict:
        config = self.settings.read()
        path = Path(config.get("local_model_path") or "/__missing_model__")
        return {
            "configured": bool(config.get("local_model_path")),
            "model_available": path.is_file(),
            "runtime_available": bool(self._binary(config)),
            "loaded": bool(self.process and self.process.poll() is None),
            "model": path.name if config.get("local_model_path") else "未选择本地模型",
            "context_size": config.get("local_context_size", 8192),
        }

    @staticmethod
    def _binary(config):
        explicit = config.get("local_server_path")
        if explicit:
            return explicit if Path(explicit).is_file() and os.access(explicit, os.X_OK) else None
        return shutil.which("llama-server") or shutil.which("llama-server.exe")

    def load(self) -> dict:
        self.session()
        return self.status()

    def session(self) -> LocalSession:
        with self.lock:
            config = self.settings.read()
            model = config.get("local_model_path", "")
            binary = self._binary(config)
            if not model or not Path(model).is_file():
                raise AppError(
                    "请在模型设置中选择存在的本地 GGUF 文件。", 409, "local_model_missing"
                )
            if Path(model).suffix.lower() != ".gguf":
                raise AppError("本地模型需要 GGUF 文件。", 409, "local_model_invalid")
            if not binary:
                raise AppError(
                    "未找到 llama-server，请安装或在模型设置中填写运行程序路径。",
                    409,
                    "local_runtime_missing",
                )
            stat = Path(model).stat()
            signature = (
                model,
                binary,
                config.get("local_context_size", 8192),
                stat.st_size,
                stat.st_mtime_ns,
            )
            if (
                self.current
                and signature == self.configuration
                and self.process
                and self.process.poll() is None
            ):
                return self.current
            self.close()
            # A bind conflict terminates our child; we never attach to another process on this port.
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            token = secrets.token_urlsafe(32)
            fd, key_file = tempfile.mkstemp(prefix="edge-local-", suffix=".key")
            self.key_path = Path(key_file)
            with os.fdopen(fd, "w") as handle:
                handle.write(token)
            env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith(("LLAMA_", "HF_", "DEEPSEEK_", "OPENAI_"))
            }
            try:
                self.process = subprocess.Popen(
                    [
                        binary,
                        "-m",
                        model,
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "-c",
                        str(signature[2]),
                        "-np",
                        "1",
                        "--alias",
                        "edge-local",
                        "--api-key-file",
                        key_file,
                        "--offline",
                        "--reasoning",
                        "off",
                        "--log-disable",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                )
                base = f"http://127.0.0.1:{port}"
                deadline = time.monotonic() + 90
                with httpx.Client(trust_env=False, timeout=1, follow_redirects=False) as client:
                    while time.monotonic() < deadline:
                        if self.process.poll() is not None:
                            raise AppError(
                                "本地模型启动失败，请检查 GGUF 与 llama-server 版本是否兼容。",
                                503,
                                "local_start_failed",
                            )
                        try:
                            if (
                                client.get(
                                    base + "/health", headers={"Authorization": "Bearer " + token}
                                ).status_code
                                == 200
                            ):
                                self.configuration = signature
                                self.current = LocalSession(base + "/v1", token, signature[2])
                                return self.current
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.2)
                raise AppError(
                    "本地模型加载超时，请检查内存与运行程序。", 504, "local_start_timeout"
                )
            except (OSError, AppError) as exc:
                self.close()
                if isinstance(exc, AppError):
                    raise
                raise AppError("无法启动本地推理程序。", 503, "local_start_failed") from exc

    def close(self):
        with self.lock:
            process, self.process = self.process, None
            self.current, self.configuration = None, None
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if self.key_path:
                self.key_path.unlink(missing_ok=True)
                self.key_path = None

    def check_budget(self, session: LocalSession, messages: list, output_tokens: int):
        try:
            with httpx.Client(
                trust_env=False,
                timeout=15,
                follow_redirects=False,
                headers={"Authorization": "Bearer " + session.api_key},
            ) as client:
                template = client.post(
                    session.base_url.removesuffix("/v1") + "/apply-template",
                    json={"messages": messages, "chat_template_kwargs": {"enable_thinking": False}},
                )
                template.raise_for_status()
                response = client.post(
                    session.base_url.removesuffix("/v1") + "/tokenize",
                    json={"content": template.json()["prompt"], "add_special": True},
                )
                response.raise_for_status()
                count = len(response.json()["tokens"])
                if count + output_tokens + 32 > session.context_size:
                    raise AppError(
                        "本地模型上下文不足，请减少引用、检索条数或增大本地上下文。原始会话仍完整保存。",
                        409,
                        "local_context_exceeded",
                    )
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise AppError(
                "无法检查本地模型上下文，请更新 llama-server。", 503, "local_runtime_unavailable"
            ) from exc


def planning_schema(context: dict) -> dict:
    fields = sorted(FIELDS) + [x["field"] for x in context.get("custom_fields", [])]
    leaf = {
        "type": "object",
        "properties": {
            "field": {"type": "string", "enum": fields},
            "op": {"type": "string", "enum": sorted(OPS)},
            "value": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "number"},
                    {"type": "boolean"},
                    {"type": "null"},
                    {
                        "type": "array",
                        "items": {"anyOf": [{"type": "string"}, {"type": "number"}]},
                        "maxItems": 50,
                    },
                ]
            },
        },
        "required": ["field", "op"],
        "additionalProperties": False,
    }
    predicate = {
        "oneOf": [
            leaf,
            *[
                {
                    "type": "object",
                    "properties": {
                        key: {
                            "type": "array",
                            "items": {"$ref": "#/$defs/predicate"},
                            "maxItems": 16,
                        }
                    },
                    "required": [key],
                    "additionalProperties": False,
                }
                for key in ("all", "any")
            ],
        ]
    }
    return {
        "type": "object",
        "$defs": {"predicate": predicate},
        "properties": {
            "threshold": {"type": "number", "minimum": 0, "maximum": 1},
            "version": {"const": 1},
            "operation": {
                "type": "string",
                "enum": ["search", "answer", "aggregate", "list", "clarify", "duplicates"],
            },
            "where": {"$ref": "#/$defs/predicate"},
            "text_query": {"type": "string"},
            "clarification": {"type": "string"},
            "metric": {"enum": ["count", "sum", "avg", "min", "max"]},
            "metric_field": {"type": "string"},
            "group_by": {"type": "string"},
            "group_date": {"type": "string"},
            "order_by": {"type": "string"},
            "descending": {"type": "boolean"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "offset": {"type": "integer", "minimum": 0, "maximum": 10000},
        },
        "required": ["operation"],
        "additionalProperties": False,
    }


class LocalQueryPlanner:
    def __init__(self, runtime: LlamaRuntime):
        self.runtime = runtime

    def plan(self, question: str, context: dict) -> dict:
        session = self.runtime.session()
        messages = local_planning_messages(question, context)
        self.runtime.check_budget(session, messages, 1400)
        try:
            with OpenAI(
                api_key=session.api_key,
                base_url=session.base_url,
                timeout=90,
                max_retries=0,
                http_client=httpx.Client(trust_env=False, follow_redirects=False),
            ) as client:
                response = client.chat.completions.create(
                    model="edge-local",
                    messages=messages,
                    temperature=0,
                    max_tokens=1400,
                    response_format={"type": "json_object", "schema": planning_schema(context)},
                    extra_body={
                        "chat_template_kwargs": {"enable_thinking": False},
                        "min_p": 0,
                        "repeat_penalty": 1.05,
                    },
                    reasoning_effort="none",
                )
            choice = response.choices[0]
            if choice.finish_reason == "length":
                raise ValueError("truncated")
            raw = choice.message.content or ""
            if len(raw) > 24000:
                raise ValueError("oversized")
            return QuerySpec.parse(json.loads(raw)).mapping()
        except (ValueError, IndexError, AttributeError) as exc:
            raise AppError(
                "本地模型未返回完整有效计划，请补充条件或使用筛选与统计。没有调用云端。",
                422,
                "invalid_local_plan",
            ) from exc
        except APIError as exc:
            raise AppError(
                "本地规划未完成，请检查模型运行状态。没有自动调用 DeepSeek。",
                503,
                "local_planner_unavailable",
            ) from exc


class LocalGenerator:
    def __init__(self, runtime: LlamaRuntime):
        self.runtime = runtime

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(images=False)

    async def generate(self, plan: QueryPlan) -> AsyncIterator[str]:
        if plan.images:
            raise AppError(
                "当前本地 GGUF 是文字模型，请使用本地 OCR 文字。", 409, "local_images_unsupported"
            )
        import asyncio

        session = await asyncio.to_thread(self.runtime.session)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *[{"role": m.role, "content": m.content} for m in plan.history],
            {"role": "user", "content": plan.prompt},
        ]
        await asyncio.to_thread(self.runtime.check_budget, session, messages, 1536)
        try:
            async with AsyncOpenAI(
                api_key=session.api_key,
                base_url=session.base_url,
                timeout=120,
                max_retries=0,
                http_client=httpx.AsyncClient(trust_env=False, follow_redirects=False),
            ) as client:
                response = await client.chat.completions.create(
                    model="edge-local",
                    messages=messages,
                    stream=plan.stream,
                    max_tokens=1536,
                    temperature=0.4,
                    top_p=0.95,
                    reasoning_effort="none",
                    extra_body={
                        "chat_template_kwargs": {"enable_thinking": False},
                        "min_p": 0,
                        "repeat_penalty": 1.05,
                    },
                )
                if not plan.stream:
                    choice = response.choices[0]
                    yield choice.message.content or "本地模型未返回回答。"
                    if choice.finish_reason == "length":
                        yield "\n\n（达到本次生成长度上限，回答可能未完整。）"
                else:
                    async with response:
                        async for chunk in response:
                            if chunk.choices:
                                if chunk.choices[0].delta.content:
                                    yield chunk.choices[0].delta.content
                                if chunk.choices[0].finish_reason == "length":
                                    yield "\n\n（达到本次生成长度上限，回答可能未完整。）"
        except APIError as exc:
            raise AppError(
                "本地回答未完成，请检查模型与内存。没有自动调用 DeepSeek。",
                503,
                "local_generation_unavailable",
            ) from exc
