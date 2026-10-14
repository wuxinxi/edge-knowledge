from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import asdict

from edge_knowledge.domain.lookup import local_lookup
from edge_knowledge.domain.models import AppError, HistoryMessage, QueryPlan, SearchHit
from edge_knowledge.domain.retrieval import contextual_question

from .catalog import CatalogMirror
from .knowledge import KnowledgeService
from .ports import Generator, LocalModelRuntime, QueryPlanner, SettingsStore, SourceStore
from .query import QueryService
from .semantic import SemanticService

MAX_CLOUD_IMAGES = 3


class ChatService:
    def __init__(
        self,
        knowledge: KnowledgeService,
        settings: SettingsStore,
        generator: Generator,
        semantic: SemanticService | None = None,
        sources: SourceStore | None = None,
        catalog: CatalogMirror | None = None,
        planner: QueryPlanner | None = None,
        local_planner: QueryPlanner | None = None,
        local_runtime: LocalModelRuntime | None = None,
    ):
        self.knowledge, self.settings, self.generator = knowledge, settings, generator
        self.semantic = semantic
        self.local_runtime = local_runtime
        self.queries = (
            QueryService(
                knowledge,
                catalog,
                self._retrieve,
                planner,
                local_planner,
                semantic.duplicates if semantic else None,
            )
            if catalog
            else None
        )

    def _retrieve(self, library: str, text: str, limit: int, ids: list[str], kinds: list[str]):
        if kinds and set(kinds) <= {"image", "audio", "video"} and self.semantic:
            result = self.semantic.search(library, text, [], limit, ids, kinds, "search", 768)
            return [SearchHit(**row) for row in result["sources"]]
        return self.knowledge.search(library, text, limit, ids)

    def local_query(
        self,
        library_id: str,
        question: str,
        top_k: int | None = None,
        document_ids: list[str] | None = None,
        query_plan: dict | None = None,
        timezone: str = "Asia/Shanghai",
    ) -> dict:
        if query_plan is not None and not self.queries:
            raise AppError("本地查询执行器尚未配置。", 503)
        result = (
            self.queries.resolve(
                library_id, question, document_ids, query_plan, timezone=timezone, local_only=True
            )
            if self.queries
            else None
        )
        if result is not None:
            return result
        hits = self.search(library_id, question, top_k, document_ids)
        count = len({hit.document_id for hit in hits})
        return {
            "kind": "retrieval",
            "sources": hits,
            "content": f"找到 {count} 份相关资料，结果如下。"
            if hits
            else "暂时没有找到相关资料。请先导入文档，或换一种描述。",
            "notice": "本次仅在本机检索并展示原文，不调用 DeepSeek，也不发送图片或文字。",
        }

    def search(
        self,
        library_id: str,
        question: str,
        top_k: int | None = None,
        document_ids: list[str] | None = None,
    ) -> list[SearchHit]:
        lookup = local_lookup(question)
        limit = top_k or self.settings.read()["top_k"]
        if lookup and lookup.kinds and self.semantic:
            with self.knowledge.transaction():
                docs = self.knowledge.repository.documents(library_id)
                if document_ids and not set(document_ids) <= {doc.id for doc in docs}:
                    raise AppError("引用资料已删除或不属于当前知识库。", 404, "reference_not_found")
                if not any(
                    doc.kind in lookup.kinds and (not document_ids or doc.id in document_ids)
                    for doc in docs
                ):
                    return []
                result = self.semantic.search(
                    library_id,
                    lookup.query,
                    [],
                    limit,
                    document_ids or [],
                    list(lookup.kinds),
                    "search",
                    768,
                )
            return [SearchHit(**row) for row in result["sources"]]
        hits = self.knowledge.search(
            library_id, lookup.query if lookup else question, limit, document_ids
        )
        return [hit for hit in hits if not lookup or not lookup.kinds or hit.kind in lookup.kinds]

    def load_local_model(self) -> dict:
        if not self.local_runtime:
            raise AppError("本地模型运行器未配置。", 503, "local_runtime_missing")
        return self.local_runtime.load()

    def close(self):
        if self.local_runtime:
            self.local_runtime.close()

    def capabilities(self, model: str | None = None) -> dict:
        config = self.settings.read()
        provider = config.get("generation_provider", "deepseek")
        model = model or config["model"]
        return {
            "embedding": {
                "ready": self.knowledge.embedder.ready,
                "images": self.knowledge.embedder.enable_images,
                "audio": hasattr(self.knowledge.embedder, "encode_input"),
                "video": self.knowledge.embedder.enable_images
                and hasattr(self.knowledge.embedder, "encode_input"),
                "joint": hasattr(self.knowledge.embedder, "encode_input"),
                "context_limit": 8192,
                "dimensions": [128, 256, 512, 768],
            },
            "generator": {
                "model": model if provider == "deepseek" else "edge-local",
                "images": self.generator.capabilities(model).images,
                "provider": provider,
            },
            "local_model": self.local_runtime.status() if self.local_runtime else None,
            "ocr": {
                "available": bool(self.knowledge.images and self.knowledge.images.ocr.available),
                "engine": getattr(self.knowledge.images.ocr, "engine_name", "")
                if self.knowledge.images
                else "",
            },
            "image_qa_mode": config["image_qa_mode"],
            "max_cloud_images": MAX_CLOUD_IMAGES,
        }

    def prepare(
        self,
        library_id: str,
        question: str,
        top_k: int | None = None,
        stream: bool | None = None,
        allow_image_upload: bool = False,
        document_ids: list[str] | None = None,
        history: list[HistoryMessage] | None = None,
        query_plan: dict | None = None,
        allow_planning: bool = False,
        timezone: str = "Asia/Shanghai",
        progress: Callable[[str], None] | None = None,
        local_generation_only: bool = False,
        context_document_ids: list[str] | None = None,
        lookup_mode: bool = False,
    ) -> QueryPlan:
        report = progress or (lambda stage: None)
        report("validating")
        config = self.settings.read()
        provider = (
            "local" if local_generation_only else config.get("generation_provider", "deepseek")
        )
        history = history or []
        if len(history) > 10 or sum(len(item.content) for item in history) > 24000:
            raise AppError("对话上下文过长，请新建对话。")
        resolved = (
            self.queries.resolve(
                library_id,
                question,
                document_ids,
                query_plan,
                allow_planning,
                timezone,
                progress=report,
                local_model_only=local_generation_only,
                context_ids=context_document_ids,
                lookup_mode=lookup_mode,
            )
            if self.queries
            else None
        )
        if query_plan is not None and not self.queries:
            raise AppError("本地查询执行器尚未配置。", 503)
        if resolved is not None and resolved["kind"] != "answer":
            return QueryPlan(
                resolved["sources"],
                "",
                config["model"],
                config["base_url"],
                "",
                True,
                resolved["content"],
                notice=resolved["notice"],
                planner=resolved.get("query", {}).get("planner", "local"),
                provider=provider,
                comparisons=resolved.get("comparisons", []),
                result_kind=resolved["kind"],
            )
        previous = next((item.content for item in reversed(history) if item.role == "user"), "")
        retrieval_question = contextual_question(question, previous)
        if not resolved:
            report("retrieving")
        hits = (
            resolved["sources"]
            if resolved
            else self.search(library_id, retrieval_question, top_k or config["top_k"], document_ids)
        )
        hits = [
            hit
            for hit in hits
            if hit.content_scope == "full_document" or hit.score >= config["min_score"]
        ]
        if local_lookup(question):
            count = len({hit.document_id for hit in hits})
            return QueryPlan(
                hits,
                "",
                config["model"],
                config["base_url"],
                "",
                True,
                f"找到 {count} 份相关资料，结果如下。"
                if hits
                else "没有找到相关资料，请换个描述或缩小资料范围。",
                notice="本次仅在本机检索并展示原文，不调用 DeepSeek，也不发送图片或文字。",
                result_kind="retrieval",
            )
        report("preparing")
        image_hits = [hit for hit in hits if hit.kind == "image"]
        attachments, notice = [], ""
        usable = [
            hit
            for hit in hits
            if (hit.kind == "document" or hit.kind == "bundle")
            and hit.text.strip()
            or hit.kind == "image"
            and hit.ocr_status == "ready"
            and hit.text.strip()
        ]
        if image_hits and config["image_qa_mode"] == "cloud_vision" and provider == "deepseek":
            if not self.generator.capabilities(config["model"]).images:
                raise AppError(
                    "当前模型不支持图片输入，请选择支持图片的模型或本地 OCR 模式。",
                    409,
                    "image_model_unsupported",
                )
            if not allow_image_upload:
                raise AppError(
                    "云端看图会发送相关图片，请先勾选本次允许发送图片。",
                    409,
                    "image_upload_required",
                )
            if not self.knowledge.images:
                raise AppError("图片处理能力未配置。", 503)
            chosen = image_hits[:MAX_CLOUD_IMAGES]
            attachments = [
                self.knowledge.images.attachment(library_id, hit.document_id, hit.filename)
                for hit in chosen
            ]
            chosen_ids = {hit.document_id for hit in chosen}
            usable = [
                hit
                for hit in hits
                if hit in usable or hit.kind == "image" and hit.document_id in chosen_ids
            ]
            notice = f"本次将 {len(attachments)} 张相关图片发送至 DeepSeek 进行解读。"
            if len(image_hits) > len(chosen):
                notice += "其余图片未发送，也不作为本次回答依据。"
        elif image_hits:
            notice = (
                "本地模型依据本地 OCR 文字解读，原图与文字均不上传。"
                if provider == "local"
                else "AI 解读会将相关的本地 OCR 文字发送至 DeepSeek，不发送原图。"
            )
            skipped = sum(hit.ocr_status != "ready" or not hit.text.strip() for hit in image_hits)
            if skipped:
                notice += f"其中 {skipped} 张图片未提取到可用文字，不参与文本回答。"
        if any(hit.kind in {"audio", "video"} for hit in hits):
            notice += "音视频检索结果可本地播放，嵌入向量不提供转录或画面描述，未将媒体发送到云端。"
        key = self.settings.api_key() if provider == "deepseek" else ""
        if usable and provider == "deepseek" and not key:
            raise AppError("请先在设置中填写 DeepSeek API Key。", 409, "missing_api_key")
        sources = []
        for i, hit in enumerate(hits, 1):
            if hit not in usable:
                continue
            label = "文档文字"
            text = hit.text if hit.content_scope == "full_document" else hit.text[:4000]
            if hit.content_scope == "full_document":
                label = "完整文档原文"
            if hit.kind == "image":
                label = "图片已附在本次请求中" if attachments else "本地 OCR 提取文字"
                if hit.ocr_status != "ready":
                    text = "未提取到文字，请依据对应的图片内容回答。"
            sources.append(
                f"[{i}] 文件：{hit.filename}；依据：{label}；章节：{hit.section or '正文'}\n{text}"
            )
        prompt = (
            "<资料>\n" + "\n\n".join(sources) + f"\n</资料>\n\n用户问题：{question}\n\n"
            "回答要求：直接回答用户问题，只使用上面的资料。"
            "列举方案时合并重复方案，写清已记载的用途与区别。"
            "每个方案或事实结论后必须写支持它的资料编号，例如 [1]；"
            "只引用本次实际提供且支持该结论的编号。"
            "没有依据的信息写‘资料未记载’，不要凭常识补全或声称覆盖全部方案。"
        )
        media_hits = [hit for hit in hits if hit.kind in {"audio", "video", "bundle"}]
        local_answer = None
        if not usable:
            if image_hits:
                notice = (
                    "本次仅展示本地检索结果，未调用 DeepSeek 生成解读；没有可用于解读的图片文字。"
                )
            local_answer = (
                "找到了相关图片，但没有可用的 OCR 文字。可以展开图片查看原图，"
                "或在设置中选择支持图片的模型与云端看图模式。"
                if image_hits
                else "找到了相关音视频或联合素材，请展开来源查看本地原件。未生成转录或画面描述。"
                if media_hits
                else "知识库中没有找到相关资料。请先导入文档，或换一种问法。"
            )
        return QueryPlan(
            hits,
            prompt,
            config["model"] if provider == "deepseek" else "edge-local",
            config["base_url"] if provider == "deepseek" else "",
            key,
            config["stream"] if stream is None else stream,
            local_answer,
            attachments,
            (resolved["notice"] + " " if resolved else "")
            + notice
            + (
                " 回答由本地模型生成，没有调用 DeepSeek。" if provider == "local" and usable else ""
            ),
            history,
            resolved.get("query", {}).get("planner", "local") if resolved else "local",
            provider,
            result_kind="retrieval" if local_answer is not None else "answer",
        )

    async def events(self, plan: QueryPlan) -> AsyncIterator[dict]:
        yield {"type": "sources", "sources": [asdict(hit) for hit in plan.sources]}
        yield {
            "type": "execution",
            "location": "local" if plan.local_answer or plan.provider == "local" else "cloud",
            **({"planner": plan.planner} if plan.planner != "local" else {}),
            **({"generator": plan.provider} if plan.local_answer is None else {}),
            **({"result_kind": plan.result_kind} if plan.result_kind else {}),
        }
        if plan.comparisons:
            yield {"type": "comparisons", "comparisons": plan.comparisons}
        if plan.notice:
            yield {"type": "notice", "message": plan.notice}
        if plan.local_answer:
            yield {"type": "delta", "delta": plan.local_answer}
        else:
            async with aclosing(self.generator.generate(plan)) as response:
                async for delta in response:
                    yield {"type": "delta", "delta": delta}
        yield {"type": "done"}
