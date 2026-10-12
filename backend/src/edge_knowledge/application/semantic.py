"""Multimodal search, joint indexing and corpus organization through ports only."""

import hashlib
from collections import OrderedDict
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import PurePosixPath
from threading import RLock

from edge_knowledge.domain.models import AppError, Asset, Chunk, Document
from edge_knowledge.domain.multimodal import (
    EmbeddingInput,
    InputAsset,
    cosine,
    unit,
)

from .knowledge import KnowledgeService
from .ports import ArchiveStore, MediaDecoder, MultimodalEmbedder, PayloadStore

AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
VIDEO = {".mp4", ".mov", ".mkv", ".webm"}
IMAGES = {".png", ".jpg", ".jpeg", ".webp"}
TASKS = {"classification", "clustering", "similarity"}


class SemanticService:
    def __init__(
        self,
        knowledge: KnowledgeService,
        embedder: MultimodalEmbedder,
        decoder: MediaDecoder,
        payloads: PayloadStore,
        archive: ArchiveStore | None = None,
    ):
        self.knowledge, self.embedder, self.decoder, self.payloads = (
            knowledge,
            embedder,
            decoder,
            payloads,
        )
        self.archive = archive
        self._lock = RLock()
        self._cache: OrderedDict = OrderedDict()

    def inputs(self, text: str, files: list[tuple[str, bytes]]) -> tuple[str, list[InputAsset]]:
        if len(files) > 12 or len(text) > 32000:
            raise AppError("最多联合 12 份素材，文字最多 32000 字符。", 413)
        assets = []
        for name, data in files:
            name = PurePosixPath(name.replace("\\", "/")).name
            suffix = PurePosixPath(name).suffix.lower()
            if not name or len(name) > 255 or not data:
                raise AppError("素材文件名或内容无效。")
            limit = 200 if suffix in AUDIO | VIDEO else 20
            if len(data) > limit * 1024 * 1024:
                raise AppError(f"{name} 超过 {limit} MB 限制。", 413)
            if suffix in IMAGES:
                if not self.knowledge.images:
                    raise AppError("图片处理不可用。", 503)
                image = self.knowledge.images.processor.prepare(data)
                assets.append(InputAsset(name, "image", image.data, "image/png"))
            elif suffix in AUDIO | VIDEO:
                kind = "audio" if suffix in AUDIO else "video"
                mime = {
                    ".wav": "audio/wav",
                    ".mp3": "audio/mpeg",
                    ".m4a": "audio/mp4",
                    ".aac": "audio/aac",
                    ".flac": "audio/flac",
                    ".ogg": "audio/ogg",
                    ".mp4": "video/mp4",
                    ".mov": "video/quicktime",
                    ".webm": "video/webm",
                    ".mkv": "video/x-matroska",
                }[suffix]
                asset = InputAsset(name, kind, data, mime)
                self.decoder.probe(asset)
                assets.append(asset)
            else:
                text += "\n" + self.knowledge.parser.parse(name, data)
        if not text.strip() and not assets:
            raise AppError("请提供文字或文件。")
        if sum(asset.kind in {"audio", "video"} for asset in assets) > 1:
            raise AppError("一次联合编码支持一段音视频与多张图片；多个音视频请分别导入。")
        return text.strip(), assets

    def segments(self, text: str, assets: list[InputAsset], task: str):
        images = tuple(asset.content for asset in assets if asset.kind == "image")
        medium = next((asset for asset in assets if asset.kind in {"audio", "video"}), None)
        if medium:
            for item in self.decoder.segments(medium):
                yield replace(item, text=text, images=images)
        elif images:
            yield EmbeddingInput(text=text, images=images)
        else:
            for part in self.embedder.split_text(text, task):
                yield EmbeddingInput(text=part)

    def inspect(self, text: str, files: list[tuple[str, bytes]], task: str) -> dict:
        text, assets = self.inputs(text, files)
        rows = []
        for item in self.segments(text, assets, task):
            budget = self.embedder.budget(item, task)
            rows.append(
                {**asdict(budget), "total": budget.total, "start": item.start, "end": item.end}
            )
        return {
            "limit": 8192,
            "max_tokens": max(row["total"] for row in rows),
            "segments": len(rows),
            "fits": all(row["total"] <= 8192 for row in rows),
            "details": rows,
        }

    def ingest(
        self,
        library: str,
        name: str,
        text: str,
        files: list[tuple[str, bytes]],
        namespace: str = "",
    ) -> dict:
        name = PurePosixPath(name.replace("\\", "/")).name.strip()
        if not name or len(name) > 255:
            raise AppError("请提供有效的素材名称。")
        text, assets = self.inputs(text, files)
        digest = hashlib.sha256(name.encode() + b"\0" + text.encode())
        if namespace:
            digest.update(namespace.encode() + b"\0")
        for asset in assets:
            digest.update(asset.filename.encode() + b"\0" + asset.content)
        document_id = digest.hexdigest()
        with self.knowledge.transaction(), self._lock:
            docs = self.knowledge.repository.documents(library)
            if any(doc.id == document_id for doc in docs):
                return {
                    "document": asdict(next(doc for doc in docs if doc.id == document_id)),
                    "duplicate": True,
                }
            vectors, chunks, budgets = [], [], []
            for index, item in enumerate(self.segments(text, assets, "document")):
                budget = self.embedder.budget(item, "document")
                budget.ensure()
                budgets.append(budget.total)
                vectors.append(self.embedder.encode_input(item, "document"))
                section = f"{item.start:.1f}–{item.end:.1f} 秒" if item.end else "联合素材"
                # Media labels are navigation only, never evidence or transcripts.
                chunks.append(Chunk(item.text, index, section, item.start, item.end))
                if index >= 9999:
                    raise AppError("素材片段过多，请拆分后导入。", 413)
            kind = (
                assets[0].kind
                if len(assets) == 1 and not text and assets[0].kind in {"audio", "video"}
                else "bundle"
                if assets
                else "document"
            )
            duration = max((chunk.end for chunk in chunks), default=0)
            document = Document(
                document_id,
                name,
                len(chunks),
                len(text.encode()) + sum(len(a.content) for a in assets),
                datetime.now(UTC).isoformat(),
                kind,
                assets[0].media_type if len(assets) == 1 else "application/octet-stream",
                duration=duration,
                assets=len(assets),
            )
            self.payloads.put(library, document_id, text, assets)
            try:
                self.knowledge.repository.add(library, document, chunks, vectors)
            except Exception:
                self.payloads.delete(library, document_id)
                raise
            return {
                "document": asdict(document),
                "duplicate": False,
                "budget": {"limit": 8192, "max_tokens": max(budgets), "segments": len(chunks)},
            }

    def search(
        self,
        library: str,
        text: str,
        files: list[tuple[str, bytes]],
        top_k: int,
        ids: list[str],
        kinds: list[str],
        task: str,
        dimension: int,
    ) -> dict:
        # Validate membership before decoding or inference.
        with self.knowledge.transaction():
            docs = self.knowledge.repository.documents(library)
            if ids and not set(ids) <= {doc.id for doc in docs}:
                raise AppError("引用资料已删除或不属于当前知识库。", 404, "reference_not_found")
            text, assets = self.inputs(text, files)
            vectors, budgets = [], []
            for item in self.segments(text, assets, task):
                budget = self.embedder.budget(item, task)
                budget.ensure()
                budgets.append(budget.total)
                vectors.append(self.embedder.encode_input(item, task, dimension))
            query = unit([sum(v[i] for v in vectors) / len(vectors) for i in range(dimension)])
            # MRL compares equal-dimensional, renormalized prefixes of stored full vectors.
            hits = []
            for hit, vector in self.knowledge.repository.vectors(library):
                if ids and hit.document_id not in ids or kinds and hit.kind not in kinds:
                    continue
                hits.append(replace(hit, score=round(cosine(query, unit(vector, dimension)), 4)))
            hits.sort(key=lambda hit: (-hit.score, hit.document_id, hit.index))
            filtered, seen_images = [], set()
            for hit in hits:
                if hit.kind == "image" and hit.document_id in seen_images:
                    continue
                if hit.kind == "image":
                    seen_images.add(hit.document_id)
                filtered.append(hit)
            return {
                "sources": [asdict(hit) for hit in filtered[:top_k]],
                "budget": {"limit": 8192, "max_tokens": max(budgets), "segments": len(vectors)},
                "dimension": dimension,
                "aggregation": "joint" if len(vectors) == 1 else "mean_of_segments",
            }

    def archived(self, library: str) -> list[dict]:
        self.knowledge.repository.documents(library)
        return [asdict(doc) for doc in self.archive.list(library)] if self.archive else []

    def archive_document(self, library: str, document_id: str) -> dict:
        if not self.archive:
            raise AppError("暂存能力不可用。", 503)
        with self.knowledge.transaction(), self._lock:
            docs = self.knowledge.repository.documents(library)
            document = next((doc for doc in docs if doc.id == document_id), None)
            if not document:
                raise AppError("资料不存在。", 404)
            record = self.knowledge.repository.record(library, document_id)
            self.archive.put(library, record)
            self.knowledge.repository.delete(library, document_id)
            # Active-library membership blocks access to archived originals.
            return {"archived": True, "document": asdict(document)}

    def restore_document(self, library: str, document_id: str) -> dict:
        if not self.archive:
            raise AppError("暂存能力不可用。", 503)
        with self.knowledge.transaction(), self._lock:
            docs = self.knowledge.repository.documents(library)
            record = self.archive.get(library, document_id)
            if not any(doc.id == document_id for doc in docs):
                self.knowledge.repository.add(
                    library, record.document, record.chunks, record.vectors
                )
            self.archive.delete(library, document_id)
            return {"restored": True}

    def manifest(self, library: str, document: str) -> list[dict]:
        with self.knowledge.transaction():
            if not any(doc.id == document for doc in self.knowledge.repository.documents(library)):
                raise AppError("资料不存在。", 404)
            _, assets = self.payloads.get(library, document)
            return [
                {
                    "index": index,
                    "filename": asset.filename,
                    "kind": asset.kind,
                    "media_type": asset.media_type,
                }
                for index, asset in enumerate(assets)
            ]

    def original(self, library: str, document: str, index: int) -> Asset:
        with self.knowledge.transaction():
            if not any(doc.id == document for doc in self.knowledge.repository.documents(library)):
                raise AppError("资料不存在。", 404)
            _, assets = self.payloads.get(library, document)
            if not 0 <= index < len(assets):
                raise AppError("素材不存在。", 404)
            return Asset(assets[index].content, assets[index].media_type)

    def _fingerprint(self, library: str, doc: Document) -> str:
        try:
            text, assets = self.payloads.get(library, doc.id)
        except AppError as exc:
            if exc.code != "payload_not_found":
                raise
            text = (
                ""
                if doc.kind == "image"
                else "\n".join(
                    chunk.text for chunk in self.knowledge.repository.chunks(library, doc.id)
                )
            )
            assets = (
                [InputAsset("", "image", self.knowledge.asset(library, doc.id).data)]
                if doc.kind == "image"
                else []
            )
        digest = hashlib.sha256(text.encode())
        for asset in assets:
            digest.update(asset.kind.encode() + b"\0" + asset.content)
        return digest.hexdigest()

    def _document_vector(
        self, library: str, doc: Document, task: str, dimension: int
    ) -> list[float]:
        key = library, doc.id, task, dimension
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        try:
            text, assets = self.payloads.get(library, doc.id)
        except AppError as exc:
            if exc.code != "payload_not_found":
                raise
            if doc.kind == "image":
                text, assets = (
                    "",
                    [
                        InputAsset(
                            doc.filename,
                            "image",
                            self.knowledge.asset(library, doc.id).data,
                            "image/png",
                        )
                    ],
                )
            elif doc.kind == "document":
                parts = self.knowledge.repository.chunks(library, doc.id)
                text, assets = "\n".join(part.text for part in parts), []
            else:
                raise
        vectors = [
            self.embedder.encode_input(item, task, dimension)
            for item in self.segments(text, assets, task)
        ]
        vector = unit([sum(v[i] for v in vectors) / len(vectors) for i in range(dimension)])
        self._cache[key] = vector
        if len(self._cache) > 512:
            self._cache.popitem(last=False)
        return vector

    def organize(
        self,
        library: str,
        ids: list[str],
        task: str,
        labels: list[str],
        clusters: int,
        threshold: float,
        dimension: int,
    ) -> dict:
        with self.knowledge.transaction(), self._lock:
            documents = self.knowledge.repository.documents(library)
            if ids and not set(ids) <= {doc.id for doc in documents}:
                raise AppError("所选资料不存在或属于其他知识库。", 404, "reference_not_found")
            docs = [doc for doc in documents if not ids or doc.id in ids]
            if not docs:
                raise AppError("请先导入资料。")
            if len(docs) > 200:
                raise AppError("一次整理最多 200 份资料，请选择一部分。", 413)
            vectors = [self._document_vector(library, doc, task, dimension) for doc in docs]
            base = {
                "task": task,
                "dimension": dimension,
                "documents": [asdict(doc) for doc in docs],
            }
            if task == "classification":
                if not labels:
                    raise AppError("请填写分类标签。")
                label_vectors = [
                    self.embedder.encode_input(EmbeddingInput(text=label), task, dimension)
                    for label in labels
                ]
                rows = []
                for doc, vector in zip(docs, vectors, strict=True):
                    scores = sorted(
                        [
                            {"label": label, "score": round(cosine(vector, target), 4)}
                            for label, target in zip(labels, label_vectors, strict=True)
                        ],
                        key=lambda item: -item["score"],
                    )
                    rows.append(
                        {
                            "document_id": doc.id,
                            "label": scores[0]["label"]
                            if scores[0]["score"] >= threshold
                            else "未分类",
                            "scores": scores,
                        }
                    )
                return {**base, "assignments": rows}
            if task == "similarity":
                pairs = []
                fingerprints = [self._fingerprint(library, doc) for doc in docs]
                for i, left in enumerate(vectors):
                    for j in range(i + 1, len(vectors)):
                        score = (
                            1.0 if fingerprints[i] == fingerprints[j] else cosine(left, vectors[j])
                        )
                        if score >= threshold:
                            pairs.append(
                                {
                                    "left": docs[i].id,
                                    "right": docs[j].id,
                                    "score": round(score, 4),
                                    "exact": fingerprints[i] == fingerprints[j],
                                }
                            )
                return {
                    **base,
                    "pairs": sorted(pairs, key=lambda pair: -pair["score"]),
                    "threshold": threshold,
                }
            if task != "clustering":
                raise AppError("未知整理任务。")
            groups = self._cluster(vectors, min(clusters, len(vectors)))
            return {**base, "groups": [[docs[index].id for index in group] for group in groups]}

    @staticmethod
    def _cluster(vectors: list[list[float]], count: int) -> list[list[int]]:
        # Deterministic farthest-first spherical k-means; no invented semantic group names.
        centers = [vectors[0]]
        while len(centers) < count:
            index = min(
                range(len(vectors)),
                key=lambda i: max(cosine(vectors[i], center) for center in centers),
            )
            if any(cosine(vectors[index], center) > 0.999999 for center in centers):
                break
            centers.append(vectors[index])
        previous = None
        for _ in range(40):
            groups = [[] for _ in centers]
            for index, vector in enumerate(vectors):
                chosen = max(range(len(centers)), key=lambda i: cosine(vector, centers[i]))
                groups[chosen].append(index)
            if groups == previous:
                break
            previous = groups
            for index, group in enumerate(groups):
                if group:
                    mean = [
                        sum(vectors[row][dim] for row in group) for dim in range(len(vectors[0]))
                    ]
                    if sum(value * value for value in mean) > 1e-12:
                        centers[index] = unit(mean)
        return [group for group in groups if group]
