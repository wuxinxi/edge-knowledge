from dataclasses import dataclass, field

from .models import Library, OCRResult, PreparedImage
from .multimodal import ArchivedRecord, InputAsset


@dataclass(frozen=True)
class BackupItem:
    record: ArchivedRecord
    archived: bool = False
    image: PreparedImage | None = field(default=None, repr=False)
    ocr: OCRResult | None = None
    payload: tuple[str, list[InputAsset]] | None = field(default=None, repr=False)


@dataclass(frozen=True)
class BackupLibrary:
    library: Library
    items: list[BackupItem]


@dataclass(frozen=True)
class BackupSnapshot:
    model: str
    dimension: int
    libraries: list[BackupLibrary]
    frontend: dict = field(default_factory=dict, repr=False)
