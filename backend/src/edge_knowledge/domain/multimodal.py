"""Framework-free multimodal inputs and bounded embedding operations."""

import math
from dataclasses import dataclass, field

from .models import AppError, Chunk, Document

CONTEXT_LIMIT = 8192
CONTEXT_RESERVE = 64
TASKS = {
    "search": "SearchQuery",
    "document": "Document",
    "classification": "Classification",
    "clustering": "Clustering",
    "similarity": "SentenceSimilarity",
    "code": "CodeRetrieval",
    "qa": "QuestionAnswering",
    "fact": "FactChecking",
}


@dataclass(frozen=True)
class EmbeddingInput:
    text: str = ""
    images: tuple[bytes, ...] = field(default_factory=tuple, repr=False)
    audio: bytes = field(default=b"", repr=False)  # mono 16kHz float32 PCM
    frames: tuple[bytes, ...] = field(default_factory=tuple, repr=False)
    start: float = 0
    end: float = 0

    @property
    def has_media(self) -> bool:
        return bool(self.images or self.audio or self.frames)


@dataclass(frozen=True)
class InputAsset:
    filename: str
    kind: str
    content: bytes = field(repr=False)
    media_type: str = "application/octet-stream"


@dataclass(frozen=True)
class MediaInfo:
    kind: str
    duration: float
    media_type: str
    has_audio: bool = False


@dataclass(frozen=True)
class ContextBudget:
    text_tokens: int
    image_tokens: int
    video_tokens: int
    audio_tokens: int
    reserve: int = CONTEXT_RESERVE
    limit: int = CONTEXT_LIMIT

    @property
    def total(self) -> int:
        return (
            self.text_tokens
            + self.image_tokens
            + self.video_tokens
            + self.audio_tokens
            + self.reserve
        )

    def ensure(self) -> None:
        if self.total > self.limit:
            raise AppError(
                f"联合输入需要约 {self.total} tokens，超过 8192 上限。"
                "请减少图片或缩短文字/媒体片段。",
                413,
                "context_budget_exceeded",
            )


def budget_for(item: EmbeddingInput, text_tokens: int) -> ContextBudget:
    # Include separators around media blocks; final processor length is checked too.
    return ContextBudget(
        text_tokens,
        len(item.images) * 282,
        len(item.frames) * 142,
        math.ceil(len(item.audio) / 4 / 16000 * 25) + (4 if item.audio else 0),
    )


def unit(vector: list[float], dimension: int | None = None) -> list[float]:
    values = vector[:dimension] if dimension else vector
    norm = math.sqrt(sum(value * value for value in values))
    if not values or not math.isfinite(norm) or norm <= 0:
        raise AppError("模型返回无效向量。", 503, "invalid_embedding")
    return [value / norm for value in values]


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise AppError("向量维度不一致。", 409, "dimension_mismatch")
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(left, right, strict=True))))


@dataclass(frozen=True)
class ArchivedRecord:
    document: Document
    chunks: list[Chunk]
    vectors: list[list[float]] = field(repr=False)
