import json
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path

from edge_knowledge.domain.models import AppError, Asset, OCRResult, PreparedImage, TextRegion


class FileAssetStore:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, library_id: str, document_id: str) -> Path:
        if library_id != "default":
            try:
                uuid.UUID(library_id)
            except ValueError as exc:
                raise AppError("知识库不存在。", 404) from exc
        if not re.fullmatch(r"[a-f0-9]{64}", document_id):
            raise AppError("图片不存在。", 404)
        return self.directory / library_id / document_id

    def put(self, library_id: str, document_id: str, image: PreparedImage, ocr: OCRResult) -> None:
        target = self._path(library_id, document_id)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = Path(tempfile.mkdtemp(prefix=".ingest-", dir=target.parent))
        try:
            files = {
                "image.png": image.data,
                "thumbnail.png": image.thumbnail,
                "ocr.json": json.dumps(asdict(ocr), ensure_ascii=False).encode(),
            }
            for name, content in files.items():
                with os.fdopen(
                    os.open(temporary / name, os.O_WRONLY | os.O_CREAT, 0o600), "wb"
                ) as handle:
                    handle.write(content)
            if target.exists():
                shutil.rmtree(target)
            temporary.replace(target)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def get(self, library_id: str, document_id: str, thumbnail: bool = False) -> Asset:
        path = self._path(library_id, document_id) / ("thumbnail.png" if thumbnail else "image.png")
        try:
            return Asset(path.read_bytes())
        except FileNotFoundError as exc:
            raise AppError("图片不存在，可能已被删除。", 404, "asset_not_found") from exc

    def delete(self, library_id: str, document_id: str) -> None:
        path = self._path(library_id, document_id)
        if path.exists():
            shutil.rmtree(path)

    def snapshot(self, library_id: str, document_id: str) -> tuple[PreparedImage, OCRResult]:
        target = self._path(library_id, document_id)
        try:
            from io import BytesIO

            from PIL import Image

            data = (target / "image.png").read_bytes()
            with Image.open(BytesIO(data)) as image:
                width, height = image.size
            values = json.loads((target / "ocr.json").read_text())
            ocr = OCRResult(
                values["status"],
                values.get("text", ""),
                [
                    TextRegion(item["text"], item["confidence"], tuple(item["bbox"]))
                    for item in values.get("regions", [])
                ],
                values.get("message", ""),
            )
            return PreparedImage(data, (target / "thumbnail.png").read_bytes(), width, height), ocr
        except (OSError, ValueError, KeyError) as exc:
            raise AppError("图片素材不完整，无法备份。", 409, "backup_asset_missing") from exc
