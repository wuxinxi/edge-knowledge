"""Device transcript schemas, separate from bounded model context and portable backup limits."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from edge_knowledge.domain.query import QuerySpec


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ReferenceBody(Strict):
    id: str = Field(min_length=1, max_length=100)
    filename: str = Field(max_length=255)


class SourceBody(Strict):
    path: str | None = Field(default=None, max_length=4096)
    document_id: str = Field(min_length=1, max_length=100)
    filename: str = Field(max_length=255)
    text: str
    section: str
    index: int = Field(ge=0)
    score: float
    kind: Literal["document", "image", "audio", "video", "bundle"] | None = None
    ocr_status: str | None = None
    start: float | None = None
    end: float | None = None


class ComparisonBody(Strict):
    left: SourceBody
    right: SourceBody
    score: float = Field(ge=-1, le=1)
    exact: bool
    body_exact: bool | None = None
    content_similarity: float | None = Field(default=None, ge=0, le=1)


class AnswerVersion(Strict):
    content: str
    sources: list[SourceBody]
    error: str | None = None
    notice: str | None = None
    savedAt: str
    planner: Literal["local", "local_model", "deepseek"] | None = None
    generator: Literal["local", "deepseek"] | None = None
    comparisons: list[ComparisonBody] | None = Field(default=None, max_length=50)


class MessageBody(Strict):
    id: str = Field(min_length=1, max_length=100)
    role: Literal["user", "assistant"]
    content: str
    sources: list[SourceBody]
    references: list[ReferenceBody] | None = None
    mode: Literal["search", "chat"] | None = None
    error: str | None = None
    notice: str | None = None
    versions: list[AnswerVersion] | None = None
    status: Literal["streaming", "complete", "stopped", "error"] | None = None
    queryPlan: dict | None = None
    planner: Literal["local", "local_model", "deepseek"] | None = None
    generator: Literal["local", "deepseek"] | None = None
    comparisons: list[ComparisonBody] | None = Field(default=None, max_length=50)

    @field_validator("queryPlan")
    @classmethod
    def valid_query_plan(cls, value):
        return QuerySpec.parse(value).mapping() if value is not None else None


class ConversationBody(Strict):
    id: str = Field(min_length=1, max_length=100)
    library: str = Field(min_length=1, max_length=100)
    title: str = Field(max_length=80)
    titleSource: Literal["auto", "manual"] | None = None
    createdAt: str = Field(max_length=100)
    updatedAt: str = Field(max_length=100)
    messages: list[MessageBody]
    references: list[ReferenceBody]


class ConversationSnapshot(Strict):
    lastLibrary: str | None = None
    revision: int = Field(ge=0)
    version: Literal[1]
    sessions: list[ConversationBody]
    active: dict[str, str]

    @model_validator(mode="after")
    def identities(self):
        ids = {chat.id: chat.library for chat in self.sessions}
        if len(ids) != len(self.sessions):
            raise ValueError("Duplicate conversation")
        for library, id in self.active.items():
            if ids.get(id) != library:
                raise ValueError("Invalid active conversation")
        for chat in self.sessions:
            if len({m.id for m in chat.messages}) != len(chat.messages):
                raise ValueError("Duplicate message")
        return self
