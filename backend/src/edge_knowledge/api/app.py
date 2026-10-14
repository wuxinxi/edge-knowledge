import asyncio
import json
import logging
import secrets
from contextlib import aclosing, asynccontextmanager, suppress
from dataclasses import asdict
from typing import Annotated

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from edge_knowledge.application.backup import BackupService
from edge_knowledge.application.chat import ChatService
from edge_knowledge.application.conversations import ConversationService
from edge_knowledge.application.folders import FolderService
from edge_knowledge.application.knowledge import KnowledgeService
from edge_knowledge.application.maintenance import LibraryMaintenance
from edge_knowledge.application.semantic import SemanticService
from edge_knowledge.domain.models import AppError, HistoryMessage

from .conversations import ConversationSnapshot
from .schemas import (
    DocumentBatch,
    LibraryCreate,
    OrganizeRequest,
    QueryRequest,
    SemanticRequest,
    SettingsUpdate,
)

logger = logging.getLogger(__name__)


def create_app(
    knowledge: KnowledgeService,
    chat: ChatService,
    token: str,
    renderer_origin: str = "",
    semantic: SemanticService | None = None,
    backup: BackupService | None = None,
    folders: FolderService | None = None,
    maintenance: LibraryMaintenance | None = None,
    conversations: ConversationService | None = None,
) -> FastAPI:
    if not token:
        raise RuntimeError("EDGE_BACKEND_TOKEN is required for a standalone backend.")

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            await run_in_threadpool(chat.close)

    app = FastAPI(
        lifespan=lifespan,
        title="Edge Knowledge",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        if request.method != "OPTIONS":
            received = request.headers.get("authorization", "")
            if not secrets.compare_digest(received.encode(), f"Bearer {token}".encode()):
                return JSONResponse(
                    {"error": {"code": "unauthorized", "message": "本地服务连接未授权。"}},
                    status_code=401,
                )
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["null", *([renderer_origin] if renderer_origin else [])],
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(AppError)
    async def app_error(_request: Request, exc: AppError):
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exc: RequestValidationError):
        # Pydantic's default error response echoes input, including secrets.
        return JSONResponse(
            {"error": {"code": "validation_error", "message": "提交参数无效，请检查输入。"}},
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, exc: Exception):
        logger.error("Unexpected backend failure: %s", type(exc).__name__)
        return JSONResponse(
            {"error": {"code": "internal_error", "message": "本地服务发生错误，请重试。"}},
            status_code=500,
        )

    @app.get("/api/health")
    def health():
        return {"status": "ok", "embedding_loaded": knowledge.embedder.loaded}

    @app.get("/api/libraries")
    def libraries():
        with knowledge.transaction():
            return [asdict(item) for item in knowledge.repository.libraries()]

    @app.post("/api/libraries", status_code=201)
    def create_library(body: LibraryCreate):
        with knowledge.transaction():
            return asdict(knowledge.repository.create_library(body.name))

    if conversations:

        @app.get("/api/chat-state")
        def read_chats():
            return conversations.read()

        @app.post("/api/chat-state")
        def save_chats(body: ConversationSnapshot):
            value = body.model_dump(exclude_unset=True)
            revision = value.pop("revision")
            return conversations.save(value, revision)

    @app.get("/api/libraries/{library_id}/documents")
    def documents(library_id: str):
        with knowledge.transaction():
            return [asdict(item) for item in knowledge.repository.documents(library_id)]

    @app.get("/api/libraries/{library_id}/reference-choices")
    def reference_choices(
        library_id: str,
        q: Annotated[str, Query(max_length=400)] = "",
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
        offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
    ):
        return chat.queries.reference_choices(library_id, q, limit, offset)

    @app.post("/api/libraries/{library_id}/documents", status_code=201)
    async def ingest(library_id: str, file: Annotated[UploadFile, File()]):
        try:
            if semantic and (file.filename or "").lower().endswith(
                (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".mp4", ".mov", ".mkv", ".webm")
            ):
                content = await file.read(200 * 1024 * 1024 + 1)
                return await run_in_threadpool(
                    semantic.ingest,
                    library_id,
                    file.filename or "",
                    "",
                    [(file.filename or "", content)],
                )
            content = await file.read(20 * 1024 * 1024 + 1)
            return await run_in_threadpool(
                knowledge.ingest, library_id, file.filename or "", content
            )
        finally:
            await file.close()

    @app.delete("/api/libraries/{library_id}/documents/{document_id}")
    def delete_document(library_id: str, document_id: str):
        knowledge.delete(library_id, document_id)
        return {"deleted": True}

    @app.get("/api/settings")
    def settings():
        return knowledge.settings.read()

    if maintenance:

        @app.post("/api/libraries/{library_id}/documents/archive-batch")
        def archive_batch(library_id: str, body: DocumentBatch):
            if (not body.all_documents and not body.document_ids) or (
                body.all_documents and body.document_ids
            ):
                raise AppError("请选择资料或明确清空整个知识库。", 422)
            return maintenance.archive_documents(library_id, body.document_ids, body.all_documents)

        @app.post("/api/libraries/{library_id}/archive/restore-batch")
        def restore_batch(library_id: str, body: DocumentBatch):
            if body.all_documents or not body.document_ids:
                raise AppError("请选择需要恢复的资料。", 422)
            return maintenance.restore_documents(library_id, body.document_ids)

    if folders:

        @app.get("/api/libraries/{library_id}/folders/{source_id}/lease")
        def folder_lease(library_id: str, source_id: str):
            return folders.lease(library_id, source_id)

        @app.post("/api/libraries/{library_id}/folders/{source_id}/activate")
        def folder_activate(library_id: str, source_id: str):
            return folders.activate(library_id, source_id)

        @app.get("/api/libraries/{library_id}/folders/{source_id}/files")
        def folder_files(library_id: str, source_id: str):
            return folders.files(library_id, source_id)

        @app.post("/api/libraries/{library_id}/folders/{source_id}/files")
        async def folder_upsert(
            library_id: str,
            source_id: str,
            path: Annotated[str, Form(min_length=1, max_length=1024)],
            file: Annotated[UploadFile, File()],
            epoch: Annotated[int, Form(ge=0, le=2147483647)] = 0,
        ):
            try:
                content = await file.read(200 * 1024 * 1024 + 1)
                return await run_in_threadpool(
                    folders.upsert, library_id, source_id, path, content, epoch
                )
            finally:
                await file.close()

        @app.post("/api/libraries/{library_id}/folders/{source_id}/reconcile")
        async def folder_reconcile(library_id: str, source_id: str, request: Request):
            data = bytearray()
            async for part in request.stream():
                data.extend(part)
                if len(data) > 6 * 1024 * 1024:
                    raise AppError("扫描清单过大。", 413)
            try:
                body = json.loads(data)
                if (
                    not {"paths", "complete"} <= set(body)
                    or set(body) - {"paths", "complete", "epoch"}
                    or body["complete"] is not True
                ):
                    raise ValueError
                paths = body["paths"]
                if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
                    raise ValueError
                epoch = body.get("epoch", 0)
                if type(epoch) is not int or not 0 <= epoch <= 2147483647:
                    raise ValueError
            except (TypeError, ValueError, KeyError) as exc:
                raise AppError("只接受完整扫描清单。", 422) from exc
            return await run_in_threadpool(folders.reconcile, library_id, source_id, paths, epoch)

    @app.get("/api/capabilities")
    def capabilities(model: Annotated[str | None, Query(min_length=1, max_length=100)] = None):
        return chat.capabilities(model)

    @app.post("/api/ocr")
    async def extract_image_text(file: Annotated[UploadFile, File()]):
        try:
            content = await file.read(20 * 1024 * 1024 + 1)
            return await run_in_threadpool(knowledge.extract_image_text, content)
        finally:
            await file.close()

    @app.get("/api/libraries/{library_id}/documents/{document_id}/thumbnail")
    def thumbnail(library_id: str, document_id: str):
        asset = knowledge.asset(library_id, document_id, thumbnail=True)
        return Response(
            asset.data,
            media_type=asset.media_type,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @app.get("/api/libraries/{library_id}/documents/{document_id}/image")
    def image(library_id: str, document_id: str):
        asset = knowledge.asset(library_id, document_id)
        return Response(
            asset.data,
            media_type=asset.media_type,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @app.patch("/api/settings")
    def update_settings(body: SettingsUpdate):
        return knowledge.settings.update(body.model_dump(exclude_none=True))

    @app.post("/api/local-model/load")
    async def load_local_model():
        return await run_in_threadpool(chat.load_local_model)

    @app.post("/api/search")
    def search(body: QueryRequest):
        config = knowledge.settings.read()
        return [
            asdict(hit)
            for hit in chat.search(
                body.library_id, body.question, body.top_k or config["top_k"], body.document_ids
            )
        ]

    @app.post("/api/query")
    async def query(body: QueryRequest, request: Request):
        arguments = (
            body.library_id,
            body.question,
            body.top_k,
            body.stream,
            body.allow_image_upload,
            body.document_ids,
            [HistoryMessage(item.role, item.content) for item in body.history],
            body.query_plan,
            body.allow_planning,
            body.timezone,
        )
        # Existing clients keep preflight HTTP errors. Opt-in clients receive preparation
        # progress immediately and any preparation failure as a terminal SSE error.
        plan = (
            None
            if body.progress
            else await run_in_threadpool(
                chat.prepare,
                *arguments,
                local_generation_only=body.local_generation_only,
                context_document_ids=body.context_document_ids,
                lookup_mode=body.lookup_mode,
            )
        )

        async def events():
            producer = None
            accepting = True
            try:
                current = plan
                if body.progress:
                    loop = asyncio.get_running_loop()
                    queue = asyncio.Queue()

                    def deliver(stage):
                        if accepting:
                            queue.put_nowait({"type": "progress", "stage": stage})

                    def report(stage):
                        loop.call_soon_threadsafe(deliver, stage)

                    async def prepare():
                        try:
                            return await run_in_threadpool(
                                chat.prepare,
                                *arguments,
                                progress=report,
                                local_generation_only=body.local_generation_only,
                                context_document_ids=body.context_document_ids,
                                lookup_mode=body.lookup_mode,
                            )
                        finally:
                            queue.put_nowait(None)

                    producer = asyncio.create_task(prepare())
                    while (event := await queue.get()) is not None:
                        if await request.is_disconnected():
                            return
                        yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                    current = await producer
                if body.progress:
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "type": "progress",
                                "stage": "presenting"
                                if current.local_answer is not None
                                else "generating",
                            }
                        )
                        + "\n\n"
                    )
                async with aclosing(chat.events(current)) as iterator:
                    async for event in iterator:
                        if await request.is_disconnected():
                            return
                        yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
            except AppError as exc:
                yield (
                    "data: "
                    + json.dumps(
                        {"type": "error", "message": exc.message, "code": exc.code},
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )
            except Exception as exc:
                logger.error("Streaming failure: %s", type(exc).__name__)
                yield 'data: {"type":"error","message":"回答中断，请重试。"}\n\n'
            finally:
                accepting = False
                if producer is not None:
                    if not producer.done():
                        producer.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await producer

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/local-query")
    def local_query(body: QueryRequest):
        result = chat.local_query(
            body.library_id,
            body.question,
            body.top_k,
            body.document_ids,
            body.query_plan,
            body.timezone,
        )
        return {**result, "sources": [asdict(hit) for hit in result["sources"]]}

    @app.get("/api/catalog/contract")
    def catalog_contract():
        from edge_knowledge.domain.query import query_contract

        return query_contract()

    @app.get("/api/catalog/schema")
    def catalog_schema(library_id: str = "default"):
        if not chat.queries:
            raise AppError("本地查询执行器尚未配置。", 503)
        return chat.queries.schema(library_id, [])

    @app.post("/api/catalog/query")
    def catalog_query(body: QueryRequest):
        if body.query_plan is None:
            raise AppError("请提供结构化查询条件。", 422)
        result = chat.local_query(
            body.library_id,
            body.question,
            body.top_k,
            body.document_ids,
            body.query_plan,
            body.timezone,
        )
        return {**result, "sources": [asdict(hit) for hit in result["sources"]]}

    if semantic:

        async def uploaded(files: list[UploadFile]):
            try:
                if len(files) > 12:
                    raise AppError("最多选择 12 份素材。", 413)
                result, total = [], 0
                for file in files:
                    content = await file.read(200 * 1024 * 1024 + 1)
                    total += len(content)
                    if total > 240 * 1024 * 1024:
                        raise AppError("联合素材总大小不能超过 240 MB。", 413)
                    result.append((file.filename or "", content))
                return result
            finally:
                for file in files:
                    await file.close()

        def options_body(options: str) -> SemanticRequest:
            try:
                return SemanticRequest.model_validate_json(options)
            except ValueError as exc:
                raise AppError("多模态参数无效。", 422) from exc

        @app.post("/api/multimodal/budget")
        async def multimodal_budget(
            options: Annotated[str, Form(max_length=50000)],
            files: Annotated[list[UploadFile] | None, File()] = None,
        ):
            body = options_body(options)
            data = await uploaded(files or [])
            return await run_in_threadpool(semantic.inspect, body.text, data, body.task)

        @app.post("/api/multimodal/search")
        async def multimodal_search(
            options: Annotated[str, Form(max_length=50000)],
            files: Annotated[list[UploadFile] | None, File()] = None,
        ):
            body = options_body(options)
            data = await uploaded(files or [])
            return await run_in_threadpool(
                semantic.search,
                body.library_id,
                body.text,
                data,
                body.top_k,
                body.document_ids,
                body.kinds,
                body.task,
                body.dimension,
                body.match_mode,
                body.min_score,
            )

        @app.post("/api/multimodal/ingest", status_code=201)
        async def multimodal_ingest(
            options: Annotated[str, Form(max_length=50000)],
            files: Annotated[list[UploadFile] | None, File()] = None,
        ):
            body = options_body(options)
            data = await uploaded(files or [])
            return await run_in_threadpool(
                semantic.ingest, body.library_id, body.name, body.text, data
            )

        @app.post("/api/organize")
        def organize(body: OrganizeRequest):
            return semantic.organize(
                body.library_id,
                body.document_ids,
                body.task,
                body.labels,
                body.clusters,
                body.threshold,
                body.dimension,
            )

        @app.get("/api/libraries/{library_id}/archive")
        def archived(library_id: str):
            return semantic.archived(library_id)

        @app.post("/api/libraries/{library_id}/documents/{document_id}/archive")
        def archive_document(library_id: str, document_id: str):
            return semantic.archive_document(library_id, document_id)

        @app.post("/api/libraries/{library_id}/archive/{document_id}/restore")
        def restore_document(library_id: str, document_id: str):
            return semantic.restore_document(library_id, document_id)

        @app.get("/api/libraries/{library_id}/documents/{document_id}/media")
        def media_manifest(library_id: str, document_id: str):
            return semantic.manifest(library_id, document_id)

        @app.get("/api/libraries/{library_id}/documents/{document_id}/media/{index}")
        def media(library_id: str, document_id: str, index: int):
            asset = semantic.original(library_id, document_id, index)
            return Response(
                asset.data,
                media_type=asset.media_type,
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )

    if backup:

        @app.post("/api/backup/export")
        async def export_backup(request: Request):
            raw = bytearray()
            async for part in request.stream():
                raw.extend(part)
                if len(raw) > 3 * 1024 * 1024:
                    raise AppError("对话备份不能超过 3 MB。", 413)
            try:
                frontend = json.loads(raw)
            except ValueError as exc:
                raise AppError("备份参数无效。", 422) from exc
            content = await run_in_threadpool(backup.export, frontend)
            return Response(
                content,
                media_type="application/zip",
                headers={
                    "Cache-Control": "no-store",
                    "Content-Disposition": 'attachment; filename="edge-assistant-backup.zip"',
                },
            )

        @app.post("/api/backup/inspect")
        async def inspect_backup(file: Annotated[UploadFile, File()]):
            try:
                content = await file.read(512 * 1024 * 1024 + 1)
                return await run_in_threadpool(backup.inspect, content)
            finally:
                await file.close()

        @app.post("/api/backup/restore")
        async def restore_backup(file: Annotated[UploadFile, File()]):
            try:
                content = await file.read(512 * 1024 * 1024 + 1)
                return await run_in_threadpool(backup.restore, content)
            finally:
                await file.close()

    return app
