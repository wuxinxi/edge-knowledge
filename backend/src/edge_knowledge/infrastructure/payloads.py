"""Atomic, private original inputs; user filenames never become filesystem paths."""

import json
import os
import shutil
import tempfile

from edge_knowledge.domain.models import AppError
from edge_knowledge.domain.multimodal import InputAsset

from .assets import FileAssetStore


class FilePayloadStore(FileAssetStore):
    def text(self, library: str, document: str) -> str:
        try:
            return json.loads((self._path(library, document) / "manifest.json").read_text())["text"]
        except (FileNotFoundError, ValueError, KeyError) as exc:
            raise AppError("原始素材不存在。", 404, "payload_not_found") from exc

    def put(self, library: str, document: str, text: str, assets: list[InputAsset]) -> None:
        target = self._path(library, document)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = type(target)(tempfile.mkdtemp(prefix=".payload-", dir=target.parent))
        try:
            manifest = {"text": text, "assets": []}
            for index, asset in enumerate(assets):
                path = temporary / str(index)
                path.write_bytes(asset.content)
                os.chmod(path, 0o600)
                manifest["assets"].append(
                    {"filename": asset.filename, "kind": asset.kind, "media_type": asset.media_type}
                )
            path = temporary / "manifest.json"
            path.write_text(json.dumps(manifest, ensure_ascii=False))
            os.chmod(path, 0o600)
            if target.exists():
                shutil.rmtree(target)
            temporary.replace(target)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def get(self, library: str, document: str) -> tuple[str, list[InputAsset]]:
        target = self._path(library, document)
        try:
            manifest = json.loads((target / "manifest.json").read_text())
            return manifest["text"], [
                InputAsset(**meta, content=(target / str(index)).read_bytes())
                for index, meta in enumerate(manifest["assets"])
            ]
        except (FileNotFoundError, ValueError, KeyError) as exc:
            raise AppError("原始素材不存在。", 404, "payload_not_found") from exc
