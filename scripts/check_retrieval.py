"""Real-model Chinese retrieval quality smoke check. Uses an isolated temporary corpus."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from edge_knowledge.application.knowledge import KnowledgeService
from edge_knowledge.infrastructure.chroma import ChromaKnowledgeRepository
from edge_knowledge.infrastructure.config import RuntimeConfig
from edge_knowledge.infrastructure.embedding import SentenceTransformerEmbedder
from edge_knowledge.infrastructure.parsers import FileDocumentParser
from edge_knowledge.infrastructure.settings import JsonSettingsStore

config = RuntimeConfig()
embedder = SentenceTransformerEmbedder(
    config.embedding_model,
    True,
    model_path=config.embedding_model_path,
    prepared_path=config.prepared_model_dir
    or config.data_dir / "models/embeddinggemma-2",
)
fixtures = {
    "rongcheng.md": "# 威海荣成数据中心\n威海荣成数据中心的 FTP 地址是 ftp://rongcheng.example.invalid:26。此处仅为演示配置。",
    "hangzhou.md": "# 杭州数据中心\n杭州数据中心的 FTP 地址是 ftp://hangzhou.example.invalid:21。备份与运维计划。",
    "ftp-guide.md": "# FTP 使用说明\nFTP 是文件传输协议，用于上传和下载文件。连接前需要配置地址、用户名和密码。",
    "alpha.md": "# 服务 ALPHA-17\n服务 ALPHA-17 的 FTP 地址是 ftp://alpha.example.invalid:21。",
    "bravo.md": "# 服务 BRAVO-42\n服务 BRAVO-42 的 FTP 地址是 ftp://bravo.example.invalid:21。",
    "recipe.md": "# 食谱\n番茄炒蛋，先炒鸡蛋，再加入番茄。",
    "architecture.md": "# 本地助手架构\n资料解析与索引在本机进行，生成服务接收文字证据。",
}
queries = [
    ("荣成数据中心的 FTP 地址是什么？", "rongcheng.md"),
    ("帮我查询出威海荣成的 fpt 地址和用户名和密码是多少", "rongcheng.md"),
    ("服务 ALPHA-17 的 FTP 地址是什么？", "alpha.md"),
    ("资料在哪里进行检索？", "architecture.md"),
    ("怎样制作西红柿炒鸡蛋？", "recipe.md"),
]
with TemporaryDirectory(prefix="edge-retrieval-check-") as directory:
    path = Path(directory)
    repository = ChromaKnowledgeRepository(path / "chroma", config.embedding_model)
    knowledge = KnowledgeService(
        FileDocumentParser(), embedder, repository, JsonSettingsStore(path)
    )
    for filename, text in fixtures.items():
        knowledge.ingest("default", filename, text.encode())
    results = []
    for question, expected in queries:
        vector = embedder.query(question)
        dense = repository.search("default", vector, 5)
        hits = knowledge.search("default", question, 5)
        assert hits and hits[0].filename == expected, (
            expected,
            [(h.filename, h.score) for h in hits],
        )
        if expected in {"rongcheng.md", "alpha.md"}:
            assert not any(
                h.filename in {"hangzhou.md", "bravo.md", "recipe.md"} for h in hits
            ), [(h.filename, h.score) for h in hits]
        results.append(
            {
                "expected": expected,
                "dense": [{"file": h.filename, "cosine": h.score} for h in dense],
                "hybrid": [{"file": h.filename, "cosine": h.score} for h in hits],
            }
        )
    Path("docs/retrieval-acceptance.json").write_text(
        json.dumps({"sample_only": True, "results": results}, indent=2)
    )
    print(json.dumps(results, ensure_ascii=False), flush=True)
