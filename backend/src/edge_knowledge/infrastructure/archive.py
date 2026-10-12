import json
import os
from dataclasses import asdict

from edge_knowledge.domain.models import AppError, Chunk, Document
from edge_knowledge.domain.multimodal import ArchivedRecord

from .assets import FileAssetStore


class FileArchiveStore(FileAssetStore):
    def put(self, library: str, record: ArchivedRecord) -> None:
        directory = self._path(library, record.document.id)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = directory / "record.tmp"
        temporary.write_text(json.dumps(asdict(record), ensure_ascii=False))
        os.chmod(temporary, 0o600)
        temporary.replace(directory / "record.json")

    def get(self, library: str, document: str) -> ArchivedRecord:
        try:
            record = json.loads((self._path(library, document) / "record.json").read_text())
            return ArchivedRecord(
                Document(**record["document"]),
                [Chunk(**chunk) for chunk in record["chunks"]],
                record["vectors"],
            )
        except (FileNotFoundError, ValueError, KeyError) as exc:
            raise AppError("暂存资料不存在。", 404) from exc

    def list(self, library: str) -> list[Document]:
        directory = self._path(library, "0" * 64).parent
        return [
            self.get(library, path.name).document
            for path in sorted(directory.glob("[a-f0-9]" * 64))
            if (path / "record.json").exists()
        ]
