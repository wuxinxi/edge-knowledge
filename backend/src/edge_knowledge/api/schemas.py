from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from edge_knowledge.domain.query import QuerySpec


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LibraryCreate(StrictBody):
    name: str = Field(min_length=1, max_length=60)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("知识库名称不能为空。")
        return value.strip()


class DocumentBatch(StrictBody):
    document_ids: list[str] = Field(default_factory=list, max_length=10000)
    all_documents: bool = False

    @field_validator("document_ids")
    @classmethod
    def valid_ids(cls, values: list[str]):
        if len(set(values)) != len(values) or any(
            len(value) != 64 or any(c not in "0123456789abcdef" for c in value) for value in values
        ):
            raise ValueError("Invalid document IDs")
        return values


class HistoryEntry(StrictBody):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=6000)


class QueryRequest(StrictBody):
    library_id: str = "default"
    question: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    stream: bool | None = None
    allow_image_upload: bool = False
    document_ids: list[str] = Field(default_factory=list, max_length=10)
    history: list[HistoryEntry] = Field(default_factory=list, max_length=10)
    query_plan: dict | None = None
    allow_planning: bool = False
    timezone: str = Field(default="Asia/Shanghai", max_length=100)

    @field_validator("query_plan")
    @classmethod
    def valid_plan(cls, value):
        return QuerySpec.parse(value).mapping() if value is not None else None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Invalid timezone") from exc
        return value

    @field_validator("document_ids")
    @classmethod
    def valid_document_ids(cls, values: list[str]) -> list[str]:
        if any(
            len(value) != 64 or any(c not in "0123456789abcdef" for c in value) for value in values
        ):
            raise ValueError("Invalid document reference")
        return list(dict.fromkeys(values))

    @field_validator("history")
    @classmethod
    def bounded_history(cls, values: list[HistoryEntry]) -> list[HistoryEntry]:
        if sum(len(item.content) for item in values) > 24000:
            raise ValueError("Conversation history too large")
        return values

    @field_validator("question")
    @classmethod
    def clean_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("问题不能为空。")
        return value.strip()


class SettingsUpdate(StrictBody):
    generation_provider: Literal["local", "deepseek"] | None = None
    local_model_path: str | None = Field(default=None, max_length=4096)
    local_server_path: str | None = Field(default=None, max_length=4096)
    local_context_size: int | None = Field(default=None, ge=2048, le=32768)
    api_key: str | None = Field(default=None, max_length=500)
    base_url: str | None = None
    model: str | None = Field(default=None, min_length=1, max_length=100)
    image_qa_mode: Literal["local_ocr", "cloud_vision"] | None = None
    stream: bool | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)
    min_score: float | None = Field(default=None, ge=-1, le=1)
    chunk_size: int | None = Field(default=None, ge=100, le=4000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=1000)


class SemanticRequest(StrictBody):
    library_id: str = "default"
    text: str = Field(default="", max_length=32000)
    name: str = Field(default="联合素材", min_length=1, max_length=255)
    task: Literal["search", "document", "code", "qa", "fact"] = "search"
    dimension: Literal[128, 256, 512, 768] = 768
    top_k: int = Field(default=10, ge=1, le=50)
    match_mode: Literal["auto", "image_text", "broad"] = "auto"
    min_score: float = Field(default=0.55, ge=-1, le=1)
    document_ids: list[str] = Field(default_factory=list, max_length=200)
    kinds: list[Literal["document", "image", "audio", "video", "bundle"]] = Field(
        default_factory=list, max_length=5
    )

    _valid_ids = field_validator("document_ids")(QueryRequest.valid_document_ids.__func__)


class OrganizeRequest(StrictBody):
    library_id: str = "default"
    task: Literal["classification", "clustering", "similarity"]
    document_ids: list[str] = Field(default_factory=list, max_length=200)
    dimension: Literal[128, 256, 512, 768] = 768
    labels: list[str] = Field(default_factory=list, max_length=30)
    clusters: int = Field(default=3, ge=1, le=20)
    threshold: float = Field(default=0.8, ge=-1, le=1)
    _valid_ids = field_validator("document_ids")(QueryRequest.valid_document_ids.__func__)

    @field_validator("labels")
    @classmethod
    def valid_labels(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 200 for value in values):
            raise ValueError("Invalid labels")
        return list(dict.fromkeys(value.strip() for value in values))
