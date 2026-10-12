import importlib.util
import json
from io import BytesIO
from pathlib import Path
from threading import RLock

from edge_knowledge.domain.models import AppError
from edge_knowledge.domain.multimodal import (
    CONTEXT_LIMIT,
    TASKS,
    ContextBudget,
    EmbeddingInput,
    budget_for,
    unit,
)


class SentenceTransformerEmbedder:
    def __init__(
        self,
        model_name: str,
        offline: bool,
        enable_images: bool = True,
        model_path: Path | None = None,
        prepared_path: Path | None = None,
    ):
        self.model_name, self.offline = model_name, offline
        self._model = None
        self.enable_images = enable_images
        self.model_path = model_path
        self.prepared_path = prepared_path
        self._lock = RLock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _local_source(self) -> Path | None:
        if self.model_path:
            return self.model_path
        if self.prepared_path:
            marker = self.prepared_path / "edge-model.json"
            try:
                manifest = json.loads(marker.read_text())
                if manifest.get("model") == self.model_name:
                    return self.prepared_path
            except (OSError, ValueError, AttributeError):
                pass
        from huggingface_hub.constants import HF_HUB_CACHE

        root = Path(HF_HUB_CACHE) / ("models--" + self.model_name.replace("/", "--"))
        reference = root / "refs/main"
        if reference.is_file():
            revision = reference.read_text().strip()
            if len(revision) == 40 and all(char in "0123456789abcdef" for char in revision):
                return root / "snapshots" / revision
        return None

    @property
    def ready(self) -> bool:
        if self.loaded:
            return True
        if not all(
            importlib.util.find_spec(name)
            for name in ["torch", "torchvision", "sentence_transformers"]
        ):
            return False
        source = self._local_source()
        return bool(
            source
            and all(
                (source / name).is_file()
                for name in ["model.safetensors", "tokenizer.json", "modules.json", "config.json"]
            )
        )

    def _load(self):
        if self._model is not None:
            return
        if not self.ready:
            raise AppError(
                "本地检索模型尚未准备，请先完成模型下载。图片识字可独立使用。",
                503,
                "model_not_ready",
            )
        try:
            import torch
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                str(self._local_source()),
                local_files_only=True,
                config_kwargs={} if self.enable_images else {"vision_config": None},
                model_kwargs={"torch_dtype": torch.float32},
            )
            self._model.max_seq_length = CONTEXT_LIMIT
        except ImportError as exc:
            raise AppError("请安装完整嵌入依赖。", 503, "embedding_unavailable") from exc
        except Exception as exc:
            raise AppError(
                "嵌入模型加载失败，请检查模型文件与可用内存。", 503, "embedding_unavailable"
            ) from exc

    def _prompt(self, item: EmbeddingInput, task: str) -> str:
        if task not in TASKS:
            raise AppError("未知的嵌入任务。")
        # Media receive no text task prefix; a mixed input retains its text instruction.
        return self._model.prompts.get(TASKS[task], "") if item.text else ""

    def budget(self, item: EmbeddingInput, task: str = "search") -> ContextBudget:
        with self._lock:
            self._load()
            tokens = len(
                self._model.tokenizer.encode(
                    self._prompt(item, task) + item.text, add_special_tokens=True
                )
            )
            return budget_for(item, tokens)

    def split_text(self, text: str, task: str = "document") -> list[str]:
        # Split on character boundaries, guided by actual tokenizer counts: no lost tokens or text.
        with self._lock:
            self._load()
            result = []
            while text:
                low, high = 1, min(len(text), 32000)
                while low < high:
                    mid = (low + high + 1) // 2
                    if self.budget(EmbeddingInput(text[:mid]), task).total <= CONTEXT_LIMIT:
                        low = mid
                    else:
                        high = mid - 1
                result.append(text[:low])
                text = text[low:]
            return result

    def encode_input(
        self, item: EmbeddingInput, task: str = "search", dimension: int = 768
    ) -> list[float]:
        if dimension not in (128, 256, 512, 768):
            raise AppError("仅支持 128、256、512、768 维。")
        if not item.text and not item.has_media:
            raise AppError("请提供文字或媒体。")
        if (item.images or item.frames) and not self.enable_images:
            raise AppError("图片编码已关闭。", 503)
        with self._lock:
            budget = self.budget(item, task)
            budget.ensure()
            try:
                import numpy as np
                import torch
                from PIL import Image
                from sentence_transformers.util import batch_to_device

                inputs = {}
                if item.text:
                    # Placeholders belong to the adapter, never accept mismatched user placeholders.
                    if any(
                        marker in item.text for marker in ("<|image|>", "<|video|>", "<|audio|>")
                    ):
                        raise AppError("文字中请勿使用模型媒体占位符。")
                    inputs["text"] = item.text
                if item.images:
                    inputs["image"] = [
                        Image.open(BytesIO(data)).convert("RGB") for data in item.images
                    ]
                if item.frames:
                    inputs["video"] = np.stack(
                        [
                            np.asarray(Image.open(BytesIO(data)).convert("RGB"))
                            for data in item.frames
                        ]
                    )
                if item.audio:
                    inputs["audio"] = np.frombuffer(item.audio, dtype="<f4").copy()
                raw = inputs if item.has_media else item.text
                features = self._model.preprocess(
                    [raw],
                    prompt=self._prompt(item, task),
                    processing_kwargs={
                        "text": {"truncation": False},
                        "video": {"do_sample_frames": False, "max_frames": 32},
                    },
                )
                actual = int(features["attention_mask"].sum().item())
                if actual > CONTEXT_LIMIT:
                    raise AppError(
                        f"处理后的输入为 {actual} tokens，超过 8192 上限。",
                        413,
                        "context_budget_exceeded",
                    )
                features = batch_to_device(features, self._model.device)
                with torch.inference_mode():
                    output = self._model(features)["sentence_embedding"][0].float().cpu().tolist()
                return unit(output, dimension)
            except AppError:
                raise
            except Exception as exc:
                raise AppError(
                    "多模态编码失败，请检查媒体内容、依赖和可用内存。", 503, "embedding_failed"
                ) from exc

    def _encode(self, inputs: list, prompt: str | None) -> list[list[float]]:
        task = "document" if prompt == "Document" else "search"
        return [self.encode_input(EmbeddingInput(text=text), task) for text in inputs]

    def documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts, "Document")

    def query(self, text: str) -> list[float]:
        return self._encode([text], "SearchQuery")[0]

    def image(self, content: bytes) -> list[float]:
        return self.encode_input(EmbeddingInput(images=(content,)))
