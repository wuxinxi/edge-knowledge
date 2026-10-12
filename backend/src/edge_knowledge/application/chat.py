from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import asdict

from edge_knowledge.domain.models import AppError, HistoryMessage, QueryPlan
from edge_knowledge.domain.retrieval import contextual_question

from .knowledge import KnowledgeService
from .ports import Generator, SettingsStore

MAX_CLOUD_IMAGES = 3


class ChatService:
    def __init__(self, knowledge: KnowledgeService, settings: SettingsStore, generator: Generator):
        self.knowledge, self.settings, self.generator = knowledge, settings, generator

    def capabilities(self, model: str | None = None) -> dict:
        config = self.settings.read()
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
            "generator": {"model": model, "images": self.generator.capabilities(model).images},
            "ocr": {
                "available": bool(self.knowledge.images and self.knowledge.images.ocr.available)
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
    ) -> QueryPlan:
        config = self.settings.read()
        history = history or []
        if len(history) > 10 or sum(len(item.content) for item in history) > 24000:
            raise AppError("对话上下文过长，请新建对话。")
        previous = next((item.content for item in reversed(history) if item.role == "user"), "")
        retrieval_question = contextual_question(question, previous)
        hits = self.knowledge.search(
            library_id, retrieval_question, top_k or config["top_k"], document_ids
        )
        hits = [hit for hit in hits if hit.score >= config["min_score"]]
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
        if image_hits and config["image_qa_mode"] == "cloud_vision":
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
            notice = "图片依据来自本地 OCR 文字，未向 DeepSeek 发送图片。"
            skipped = sum(hit.ocr_status != "ready" or not hit.text.strip() for hit in image_hits)
            if skipped:
                notice += f"其中 {skipped} 张图片未提取到可用文字，不参与文本回答。"
        if any(hit.kind in {"audio", "video"} for hit in hits):
            notice += "音视频检索结果可本地播放，嵌入向量不提供转录或画面描述，未将媒体发送到云端。"
        key = self.settings.api_key()
        if usable and not key:
            raise AppError("请先在设置中填写 DeepSeek API Key。", 409, "missing_api_key")
        sources = []
        for i, hit in enumerate(hits, 1):
            if hit not in usable:
                continue
            label = "文档文字"
            text = hit.text[:4000]
            if hit.kind == "image":
                label = "图片已附在本次请求中" if attachments else "本地 OCR 提取文字"
                if hit.ocr_status != "ready":
                    text = "未提取到文字，请依据对应的图片内容回答。"
            sources.append(
                f"[{i}] 文件：{hit.filename}；依据：{label}；章节：{hit.section or '正文'}\n{text}"
            )
        prompt = "<资料>\n" + "\n\n".join(sources) + f"\n</资料>\n\n用户问题：{question}"
        media_hits = [hit for hit in hits if hit.kind in {"audio", "video", "bundle"}]
        local_answer = None
        if not usable:
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
            config["model"],
            config["base_url"],
            key,
            config["stream"] if stream is None else stream,
            local_answer,
            attachments,
            notice,
            history,
        )

    async def events(self, plan: QueryPlan) -> AsyncIterator[dict]:
        yield {"type": "sources", "sources": [asdict(hit) for hit in plan.sources]}
        if plan.notice:
            yield {"type": "notice", "message": plan.notice}
        if plan.local_answer:
            yield {"type": "delta", "delta": plan.local_answer}
        else:
            async with aclosing(self.generator.generate(plan)) as response:
                async for delta in response:
                    yield {"type": "delta", "delta": delta}
        yield {"type": "done"}
