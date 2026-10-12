"""Versioned ZIP format with bounded reads, hashes and explicit data schemas.

No archive member is ever extracted as a filesystem path.
"""

import hashlib
import json
import math
import re
import stat
from dataclasses import asdict, fields
from io import BytesIO
from typing import Literal
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from edge_knowledge.domain.backup import BackupItem, BackupLibrary, BackupSnapshot
from edge_knowledge.domain.models import (
    AppError,
    Chunk,
    Document,
    Library,
    OCRResult,
    PreparedImage,
)
from edge_knowledge.domain.multimodal import ArchivedRecord, InputAsset

MAX_BACKUP_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024 * 1024


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class BlobRef(StrictModel):
    path: str = Field(pattern=r"^blobs/[0-9]+$", max_length=30)
    size: int = Field(ge=0, le=200 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ImageValue(StrictModel):
    image: BlobRef
    thumbnail: BlobRef
    width: int = Field(ge=1, le=20000)
    height: int = Field(ge=1, le=20000)
    ocr: dict


class PayloadAsset(StrictModel):
    filename: str = Field(min_length=1, max_length=255)
    kind: Literal["document", "image", "audio", "video"]
    media_type: str = Field(min_length=1, max_length=100)
    blob: BlobRef


class PayloadValue(StrictModel):
    text: str = Field(max_length=20 * 1024 * 1024)
    assets: list[PayloadAsset] = Field(max_length=12)


class ItemValue(StrictModel):
    document: dict
    chunks: list[dict] = Field(min_length=1, max_length=10000)
    vectors: list[list[float]] = Field(min_length=1, max_length=10000)
    archived: bool
    image: ImageValue | None = None
    payload: PayloadValue | None = None


class LibraryValue(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=60)
    items: list[ItemValue] = Field(max_length=5000)


class Manifest(StrictModel):
    format: Literal["edge-assistant-backup"]
    version: Literal[1]
    model: str = Field(min_length=1, max_length=200)
    dimension: int = Field(ge=1, le=768)
    libraries: list[LibraryValue] = Field(min_length=1, max_length=100)
    frontend: dict


class ReferenceValue(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    filename: str = Field(min_length=1, max_length=255)


class SourceValue(StrictModel):
    document_id: str = Field(min_length=1, max_length=100)
    filename: str = Field(min_length=1, max_length=255)
    text: str = Field(max_length=200000)
    section: str = Field(max_length=20000)
    index: int = Field(ge=0)
    score: float = Field(ge=-1, le=1)
    kind: Literal["document", "image", "audio", "video", "bundle"] | None = None
    ocr_status: str | None = Field(default=None, max_length=100)
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, ge=0)


class MessageValue(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    role: Literal["user", "assistant"]
    content: str = Field(max_length=200000)
    sources: list[SourceValue] = Field(max_length=50)
    references: list[ReferenceValue] | None = Field(default=None, max_length=10)
    mode: Literal["search", "chat"] | None = None
    error: str | None = Field(default=None, max_length=2000)
    notice: str | None = Field(default=None, max_length=4000)


class ConversationValue(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    library: str = Field(min_length=1, max_length=100)
    title: str = Field(max_length=80)
    createdAt: str = Field(max_length=100)
    updatedAt: str = Field(max_length=100)
    messages: list[MessageValue] = Field(max_length=2000)
    references: list[ReferenceValue] = Field(max_length=10)


class ChatsValue(StrictModel):
    version: Literal[1]
    sessions: list[ConversationValue] = Field(max_length=500)
    active: dict[str, str] = Field(default_factory=dict)


def frontend_data(value: dict) -> dict:
    # Credentials, filesystem grants and backend configuration are never portable.
    if not isinstance(value, dict) or set(value) - {"chats", "preferences"}:
        raise AppError("备份界面数据无效。", 422, "invalid_backup")
    if len(json.dumps(value, ensure_ascii=False).encode()) > 3 * 1024 * 1024:
        raise AppError("对话与界面偏好备份不能超过 3 MB，请先分开导出较长对话。", 413)
    for key, item in value.items():
        if item is not None and not isinstance(item, dict):
            raise AppError("备份界面数据无效。", 422, "invalid_backup")
        if (
            key == "preferences"
            and item
            and set(item)
            - {
                "theme",
                "accent",
                "language",
                "fontSize",
                "fontFamily",
                "sendKey",
                "typographyVersion",
            }
        ):
            raise AppError("备份偏好包含不支持的字段。", 422, "invalid_backup")
        if key == "chats" and item and set(item) - {"version", "sessions", "active"}:
            raise AppError("备份对话包含不支持的字段。", 422, "invalid_backup")
    if value.get("chats"):
        chats = ChatsValue.model_validate(value["chats"])
        if len({chat.id for chat in chats.sessions}) != len(chats.sessions):
            raise AppError("对话备份包含重复记录。", 422, "invalid_backup")
    return value


class ZipBackupCodec:
    def encode(self, snapshot: BackupSnapshot) -> bytes:
        try:
            return self._encode(snapshot)
        except AppError:
            raise
        except (ValueError, TypeError, KeyError) as exc:
            raise AppError("备份数据格式无效，未生成文件。", 422, "invalid_backup") from exc

    def _encode(self, snapshot: BackupSnapshot) -> bytes:
        output = BytesIO()
        total, index = 0, 0
        with ZipFile(output, "w", ZIP_DEFLATED, compresslevel=3) as archive:

            def blob(data: bytes) -> dict:
                nonlocal total, index
                total += len(data)
                if len(data) > 200 * 1024 * 1024 or total > MAX_BACKUP_BYTES:
                    raise AppError("备份超过 512 MB 上限，请减少资料后再备份。", 413)
                path = f"blobs/{index}"
                index += 1
                archive.writestr(path, data)
                return {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

            groups = []
            for group in snapshot.libraries:
                items = []
                for item in group.items:
                    values = {
                        "document": asdict(item.record.document),
                        "chunks": [asdict(chunk) for chunk in item.record.chunks],
                        "vectors": item.record.vectors,
                        "archived": item.archived,
                    }
                    if item.image and item.ocr:
                        values["image"] = {
                            "image": blob(item.image.data),
                            "thumbnail": blob(item.image.thumbnail),
                            "width": item.image.width,
                            "height": item.image.height,
                            "ocr": asdict(item.ocr),
                        }
                    if item.payload is not None:
                        text, assets = item.payload
                        values["payload"] = {
                            "text": text,
                            "assets": [
                                {
                                    "filename": asset.filename,
                                    "kind": asset.kind,
                                    "media_type": asset.media_type,
                                    "blob": blob(asset.content),
                                }
                                for asset in assets
                            ],
                        }
                    items.append(values)
                groups.append({"id": group.library.id, "name": group.library.name, "items": items})
            manifest = {
                "format": "edge-assistant-backup",
                "version": 1,
                "model": snapshot.model,
                "dimension": snapshot.dimension,
                "libraries": groups,
                "frontend": frontend_data(snapshot.frontend),
            }
            content = json.dumps(manifest, ensure_ascii=False, allow_nan=False).encode()
            if len(content) > MAX_MANIFEST_BYTES or total + len(content) > MAX_BACKUP_BYTES:
                raise AppError("备份索引或总体积超过上限。", 413)
            archive.writestr("manifest.json", content)
        data = output.getvalue()
        if len(data) > MAX_BACKUP_BYTES:
            raise AppError("备份文件超过 512 MB 上限。", 413)
        # Apply the same validation to exports as imports.
        self.decode(data)
        return data

    def decode(self, data: bytes) -> BackupSnapshot:
        if len(data) > MAX_BACKUP_BYTES:
            raise AppError("备份文件超过 512 MB 上限。", 413)
        try:
            return self._decode(data)
        except AppError:
            raise
        except (
            ValueError,
            TypeError,
            KeyError,
            BadZipFile,
            OSError,
            RuntimeError,
            OverflowError,
        ) as exc:
            raise AppError(
                "备份损坏、格式不支持或完整性校验失败，未导入资料。", 422, "invalid_backup"
            ) from exc

    def _decode(self, data: bytes) -> BackupSnapshot:
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if (
                len(entries) > 30000
                or len(set(names)) != len(names)
                or "manifest.json" not in names
            ):
                raise ValueError("Invalid archive members")
            for entry in entries:
                mode = entry.external_attr >> 16
                if (
                    entry.flag_bits & 1
                    or stat.S_ISLNK(mode)
                    or not (
                        entry.filename == "manifest.json"
                        or re.fullmatch(r"blobs/[0-9]+", entry.filename)
                    )
                ):
                    raise ValueError("Invalid archive member")
                if entry.file_size > (
                    MAX_MANIFEST_BYTES if entry.filename == "manifest.json" else 200 * 1024 * 1024
                ):
                    raise ValueError("Oversized archive member")
            if sum(entry.file_size for entry in entries) > MAX_BACKUP_BYTES:
                raise ValueError("Archive expansion exceeds limit")
            manifest = Manifest.model_validate_json(archive.read("manifest.json"))
            frontend_data(manifest.frontend)
            used = {"manifest.json"}

            def read(ref: BlobRef) -> bytes:
                if ref.path in used or archive.getinfo(ref.path).file_size != ref.size:
                    raise ValueError("Invalid blob reference")
                used.add(ref.path)
                content = archive.read(ref.path)
                if hashlib.sha256(content).hexdigest() != ref.sha256:
                    raise ValueError("Hash mismatch")
                return content

            groups, library_ids, count = [], set(), 0
            for group in manifest.libraries:
                if group.id in library_ids:
                    raise ValueError("Duplicate library")
                library_ids.add(group.id)
                items, ids = [], set()
                for value in group.items:
                    count += len(value.chunks)
                    if count > 50000:
                        raise ValueError("Too many excerpts")
                    if set(value.document) - {field.name for field in fields(Document)}:
                        raise ValueError("Unknown document fields")
                    if any(
                        set(chunk) - {field.name for field in fields(Chunk)}
                        for chunk in value.chunks
                    ):
                        raise ValueError("Unknown excerpt fields")
                    document = TypeAdapter(Document).validate_python(value.document)
                    if (
                        not re.fullmatch(r"[a-f0-9]{64}", document.id)
                        or document.id in ids
                        or not document.filename
                        or len(document.filename) > 255
                        or document.size < 0
                        or document.kind not in {"document", "image", "audio", "video", "bundle"}
                    ):
                        raise ValueError("Invalid document")
                    ids.add(document.id)
                    chunks = [TypeAdapter(Chunk).validate_python(chunk) for chunk in value.chunks]
                    if (
                        document.chunks != len(chunks)
                        or len(chunks) != len(value.vectors)
                        or [chunk.index for chunk in chunks] != list(range(len(chunks)))
                    ):
                        raise ValueError("Incomplete index")
                    if any(
                        len(chunk.text) > 20000
                        or not math.isfinite(chunk.start)
                        or not math.isfinite(chunk.end)
                        or chunk.start < 0
                        or chunk.end < chunk.start
                        for chunk in chunks
                    ):
                        raise ValueError("Invalid excerpt")
                    if any(
                        len(vector) != manifest.dimension
                        or not all(math.isfinite(number) for number in vector)
                        or not math.isfinite(sum(number * number for number in vector))
                        or sum(number * number for number in vector) <= 0
                        for vector in value.vectors
                    ):
                        raise ValueError("Invalid vector")
                    image, ocr, payload = None, None, None
                    if value.image:
                        from PIL import Image

                        image_data, thumbnail = read(value.image.image), read(value.image.thumbnail)
                        for content, expected in [
                            (image_data, (value.image.width, value.image.height)),
                            (thumbnail, None),
                        ]:
                            with Image.open(BytesIO(content)) as opened:
                                if (
                                    opened.format != "PNG"
                                    or opened.width * opened.height > 40_000_000
                                    or (expected and opened.size != expected)
                                ):
                                    raise ValueError("Invalid backup image")
                                opened.verify()
                        image = PreparedImage(
                            image_data, thumbnail, value.image.width, value.image.height
                        )
                        ocr = TypeAdapter(OCRResult).validate_python(value.image.ocr)
                    if document.kind == "image" and not image:
                        raise ValueError("Missing image")
                    if value.payload:
                        payload = (
                            value.payload.text,
                            [
                                InputAsset(
                                    asset.filename, asset.kind, read(asset.blob), asset.media_type
                                )
                                for asset in value.payload.assets
                            ],
                        )
                    if document.kind in {"audio", "video", "bundle"} and payload is None:
                        raise ValueError("Missing media originals")
                    items.append(
                        BackupItem(
                            ArchivedRecord(document, chunks, value.vectors),
                            value.archived,
                            image,
                            ocr,
                            payload,
                        )
                    )
                groups.append(
                    BackupLibrary(
                        Library(
                            group.id,
                            group.name,
                            sum(item.record.document.chunks for item in items if not item.archived),
                        ),
                        items,
                    )
                )
            if used != set(names):
                raise ValueError("Unreferenced archive members")
            return BackupSnapshot(manifest.model, manifest.dimension, groups, manifest.frontend)
