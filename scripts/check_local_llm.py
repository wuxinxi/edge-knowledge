"""Opt-in acceptance on synthetic notes using real local GGUF and embedding weights."""

import argparse
import io
import json
import tempfile
import time
from pathlib import Path

from edge_knowledge.bootstrap import build_app
from edge_knowledge.infrastructure.config import RuntimeConfig
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--embedding-path", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {
        "scope": "Real local model + real embedding, isolated synthetic corpus; no cloud calls",
        "cases": {},
    }
    with tempfile.TemporaryDirectory(prefix="edge-local-acceptance-") as directory:
        app = build_app(
            RuntimeConfig(
                data_dir=Path(directory),
                backend_token="local-acceptance-token",
                local_model_path=args.model_path.resolve(),
                prepared_model_dir=args.embedding_path.resolve(),
            )
        )
        with TestClient(
            app, headers={"Authorization": "Bearer local-acceptance-token"}
        ) as client:
            assert client.get("/api/settings").json()["generation_provider"] == "local"
            for filename, text in [
                (
                    "部署流程.md",
                    "---\ncreatedAt: 2026-09-02\ntags: [工作, 技术]\n---\n# 部署步骤\n1. 安装项目依赖。\n2. 启动本地服务。\n3. 检查服务健康状态。",
                ),
                (
                    "学习笔记.md",
                    "---\ncreatedAt: 2026-09-30\ntags: [学习]\n---\n# 读书笔记\n阅读小说，记录读后感。",
                ),
                (
                    "十月随记.md",
                    "---\ncreatedAt: 2026-10-01\ntags: [生活]\n---\n# 日常\n去公园散步。",
                ),
                ("没有日期.md", "# 未标日期的笔记\n记录一份未标注创建日期的资料。"),
            ]:
                r = client.post(
                    "/api/libraries/default/documents",
                    files={"file": (filename, text.encode())},
                )
                assert r.status_code == 201, r.text
            start = time.monotonic()
            r = client.post("/api/local-model/load")
            assert r.status_code == 200, r.text
            report["load_seconds"] = round(time.monotonic() - start, 2)

            question = "统计2026年9月份创建的笔记，按标签分组。"
            start = time.monotonic()
            r = client.post("/api/local-query", json={"question": question})
            assert r.status_code == 200, r.text
            result = r.json()
            assert result["query"]["result"]["total"] == 2, result
            assert {
                g["key"]: g["count"] for g in result["query"]["result"]["groups"]
            } == {"工作": 1, "技术": 1, "学习": 1}, result
            assert "缺少创建日期" in result["content"], result
            report["cases"]["grouped_month_count"] = {
                "seconds": round(time.monotonic() - start, 2),
                "count": 2,
                "missing_dates_reported": True,
                "planner": result["query"]["planner"],
                "plan": result["query"]["plan"],
            }

            r = client.post(
                "/api/local-query",
                json={"question": "统计九月份创建的笔记，按标签分组。"},
            )
            assert r.status_code == 200 and r.json()["kind"] == "clarification", r.text
            report["cases"]["missing_year"] = "clarified_without_model_or_cloud"

            r = client.post(
                "/api/query",
                json={"question": "找到我以前记录的部署步骤。", "allow_planning": True},
            )
            assert r.status_code == 200, r.text
            events = [
                json.loads(line[6:])
                for line in r.text.splitlines()
                if line.startswith("data: ")
            ]
            hits = next(
                event["sources"] for event in events if event["type"] == "sources"
            )
            assert any(hit["filename"] == "部署流程.md" for hit in hits), events
            assert not any(e["type"] == "error" for e in events), events
            report["cases"]["find_deployment"] = {
                "filenames": [hit["filename"] for hit in hits],
                "location": "local",
            }

            start = time.monotonic()
            r = client.post(
                "/api/query",
                json={"question": "总结部署步骤。", "allow_planning": True},
            )
            events = [
                json.loads(line[6:])
                for line in r.text.splitlines()
                if line.startswith("data: ")
            ]
            assert not any(e["type"] == "error" for e in events), events
            assert any(e.get("generator") == "local" for e in events), events
            answer = "".join(e.get("delta", "") for e in events)
            assert "安装" in answer and "启动" in answer and "健康" in answer, answer
            report["cases"]["local_summary"] = {
                "seconds": round(time.monotonic() - start, 2),
                "answer": answer,
                "generator": "local",
            }

            image = Image.new("RGB", (900, 220), "white")
            draw = ImageDraw.Draw(image)
            draw.text(
                (30, 40),
                "Massive Audio Embedding Benchmark",
                fill="black",
                font_size=38,
            )
            draw.text(
                (30, 115), "EmbeddingGemma 2     Score 49", fill="black", font_size=30
            )
            content = io.BytesIO()
            image.save(content, format="PNG")
            r = client.post(
                "/api/libraries/default/documents",
                files={"file": ("benchmark.png", content.getvalue())},
            )
            assert r.status_code == 201, r.text
            r = client.post(
                "/api/query",
                json={
                    "question": "找到那张 Massive Audio Embedding Benchmark 图。",
                    "allow_planning": True,
                },
            )
            events = [
                json.loads(line[6:])
                for line in r.text.splitlines()
                if line.startswith("data: ")
            ]
            hits = next(
                event["sources"] for event in events if event["type"] == "sources"
            )
            assert hits and all(
                hit["kind"] == "image" and hit["filename"] == "benchmark.png"
                for hit in hits
            ), events
            report["cases"]["find_image"] = {
                "matches": len(hits),
                "kind": "image",
                "location": "local",
            }
            assert not client.get("/api/settings").json()["api_key_configured"]
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
