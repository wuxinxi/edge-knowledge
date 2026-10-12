import pytest
from fastapi.testclient import TestClient

from edge_knowledge.api.app import create_app
from edge_knowledge.application.chat import ChatService
from edge_knowledge.application.images import ImageService
from edge_knowledge.application.knowledge import KnowledgeService
from edge_knowledge.domain.models import ModelCapabilities, OCRResult, TextRegion
from edge_knowledge.infrastructure.assets import FileAssetStore
from edge_knowledge.infrastructure.chroma import ChromaKnowledgeRepository
from edge_knowledge.infrastructure.images import PillowImageProcessor
from edge_knowledge.infrastructure.parsers import FileDocumentParser
from edge_knowledge.infrastructure.settings import JsonSettingsStore


class MemoryCredentials:
    backend_name = "test-memory"

    def __init__(self):
        self.value = None

    def get(self):
        return self.value

    def set(self, value):
        self.value = value

    def delete(self):
        self.value = None


class TestEmbedder:
    """Deterministic test double: production never substitutes the real model."""

    loaded = False
    ready = True
    enable_images = True

    def documents(self, texts):
        self.loaded = True
        return [[1.0, 0.0, 0.0] for _ in texts]

    def query(self, text):
        self.loaded = True
        return [1.0, 0.0, 0.0]

    def image(self, content):
        self.loaded = True
        return [1.0, 0.0, 0.0]


class TestOCR:
    available = True

    def recognize(self, content):
        return OCRResult(
            "ready", "快递取件码 6583", [TextRegion("6583", 0.98, (0.1, 0.2, 0.3, 0.1))]
        )


class TestGenerator:
    calls = 0

    def capabilities(self, model):
        return ModelCapabilities(images=model == "deepseek-flash")

    async def generate(self, plan):
        self.calls += 1
        yield "根据资料"
        yield "，答案见 [1]。"


@pytest.fixture
def system(tmp_path):
    settings = JsonSettingsStore(tmp_path, credentials=MemoryCredentials())
    repository = ChromaKnowledgeRepository(tmp_path / "chroma", "test-model")
    embedder = TestEmbedder()
    images = ImageService(PillowImageProcessor(), TestOCR(), FileAssetStore(tmp_path / "assets"))
    knowledge = KnowledgeService(FileDocumentParser(), embedder, repository, settings, images)
    generator = TestGenerator()
    chat = ChatService(knowledge, settings, generator)
    app = create_app(knowledge, chat, "test-session-token", "http://localhost:5173")
    with TestClient(app, headers={"Authorization": "Bearer test-session-token"}) as client:
        yield client, knowledge, chat, generator
