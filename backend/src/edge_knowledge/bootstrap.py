from edge_knowledge.api.app import create_app
from edge_knowledge.application.backup import BackupService
from edge_knowledge.application.catalog import CatalogMirror, IndexedKnowledgeRepository
from edge_knowledge.application.chat import ChatService
from edge_knowledge.application.conversations import ConversationService
from edge_knowledge.application.folders import FolderService
from edge_knowledge.application.images import ImageService
from edge_knowledge.application.knowledge import KnowledgeService
from edge_knowledge.application.maintenance import LibraryMaintenance
from edge_knowledge.application.semantic import SemanticService
from edge_knowledge.infrastructure.archive import FileArchiveStore
from edge_knowledge.infrastructure.assets import FileAssetStore
from edge_knowledge.infrastructure.backup import ZipBackupCodec
from edge_knowledge.infrastructure.catalog import SQLiteDocumentCatalog
from edge_knowledge.infrastructure.chroma import ChromaKnowledgeRepository
from edge_knowledge.infrastructure.config import RuntimeConfig
from edge_knowledge.infrastructure.conversations import SQLiteConversationStore
from edge_knowledge.infrastructure.credentials import SystemCredentialStore
from edge_knowledge.infrastructure.deepseek import DeepSeekGenerator
from edge_knowledge.infrastructure.embedding import SentenceTransformerEmbedder
from edge_knowledge.infrastructure.images import PillowImageProcessor
from edge_knowledge.infrastructure.media import AVMediaDecoder
from edge_knowledge.infrastructure.metadata import YAMLMetadataReader
from edge_knowledge.infrastructure.ocr import LocalOCR
from edge_knowledge.infrastructure.parsers import FileDocumentParser
from edge_knowledge.infrastructure.payloads import FilePayloadStore
from edge_knowledge.infrastructure.planner import DeepSeekQueryPlanner
from edge_knowledge.infrastructure.settings import JsonSettingsStore
from edge_knowledge.infrastructure.sources import SQLiteSourceStore


def build_app(config: RuntimeConfig):
    """The single composition root: only here are concrete adapters wired to use cases."""
    directory = config.data_dir.resolve()
    settings = JsonSettingsStore(
        directory,
        config.deepseek_api_key,
        SystemCredentialStore(directory),
    )
    repository = ChromaKnowledgeRepository(directory / "chroma", config.embedding_model)
    prepared = config.prepared_model_dir or directory / "models/embeddinggemma-2"
    embedder = SentenceTransformerEmbedder(
        config.embedding_model,
        config.model_offline,
        config.image_embeddings,
        config.embedding_model_path,
        prepared_path=prepared,
    )
    images = ImageService(
        PillowImageProcessor(),
        LocalOCR(),
        FileAssetStore(directory / "assets" / repository.prefix),
    )
    payloads = FilePayloadStore(directory / "payloads" / repository.prefix)
    source_store = SQLiteSourceStore(directory / "sources" / (repository.prefix + ".sqlite3"))
    catalog = CatalogMirror(
        repository,
        SQLiteDocumentCatalog(directory / "catalog" / (repository.prefix + ".sqlite3")),
        YAMLMetadataReader(),
        payloads,
        source_store,
        images.assets,
    )
    repository = IndexedKnowledgeRepository(repository, catalog)
    knowledge = KnowledgeService(
        FileDocumentParser(), embedder, repository, settings, images, payloads
    )
    archive = FileArchiveStore(directory / "archive" / repository.prefix)
    semantic = SemanticService(
        knowledge,
        embedder,
        AVMediaDecoder(),
        payloads,
        archive,
    )
    chat = ChatService(
        knowledge,
        settings,
        DeepSeekGenerator(),
        semantic,
        source_store,
        catalog,
        DeepSeekQueryPlanner(settings),
    )
    backup = BackupService(knowledge, archive, ZipBackupCodec(), config.embedding_model)
    folders = FolderService(
        knowledge,
        semantic,
        source_store,
    )
    return create_app(
        knowledge,
        chat,
        config.backend_token,
        config.renderer_origin,
        semantic,
        backup,
        folders,
        LibraryMaintenance(knowledge, archive, folders),
        ConversationService(SQLiteConversationStore(directory / "conversations.sqlite3")),
    )
