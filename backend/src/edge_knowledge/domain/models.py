from dataclasses import dataclass, field


@dataclass(frozen=True)
class Chunk:
    text: str
    index: int
    section: str
    start: float = 0
    end: float = 0


@dataclass(frozen=True)
class Document:
    id: str
    filename: str
    chunks: int
    size: int
    created_at: str
    kind: str = "document"
    media_type: str = "text/plain"
    width: int = 0
    height: int = 0
    ocr_status: str = "not_applicable"
    ocr_message: str = ""
    duration: float = 0
    assets: int = 0


@dataclass(frozen=True)
class Library:
    id: str
    name: str
    chunks: int


@dataclass(frozen=True)
class SearchHit:
    document_id: str
    filename: str
    text: str
    section: str
    index: int
    score: float
    kind: str = "document"
    ocr_status: str = "not_applicable"
    start: float = 0
    end: float = 0


@dataclass(frozen=True)
class TextRegion:
    text: str
    confidence: float
    # Normalized top-left x, y, width, height in the oriented image.
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class OCRResult:
    status: str
    text: str = ""
    regions: list[TextRegion] = field(default_factory=list)
    message: str = ""


@dataclass(frozen=True)
class PreparedImage:
    data: bytes = field(repr=False)
    thumbnail: bytes = field(repr=False)
    width: int
    height: int
    media_type: str = "image/png"


@dataclass(frozen=True)
class Asset:
    data: bytes = field(repr=False)
    media_type: str = "image/png"


@dataclass(frozen=True)
class ImageAttachment:
    document_id: str
    filename: str
    data: bytes = field(repr=False)
    media_type: str = "image/jpeg"


@dataclass(frozen=True)
class ModelCapabilities:
    images: bool = False


@dataclass(frozen=True)
class HistoryMessage:
    role: str
    content: str


@dataclass(frozen=True)
class QueryPlan:
    sources: list[SearchHit]
    prompt: str
    model: str
    base_url: str
    api_key: str = field(repr=False)
    stream: bool
    local_answer: str | None = None
    images: list[ImageAttachment] = field(default_factory=list, repr=False)
    notice: str = ""
    history: list[HistoryMessage] = field(default_factory=list, repr=False)


class AppError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "invalid_request"):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code
