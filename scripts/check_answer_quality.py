"""Opt-in local-model quality probes on isolated, explicitly synthetic reference notes."""

import argparse
import inspect
import json
import re
import tempfile
import time
from pathlib import Path

from edge_knowledge.bootstrap import build_app
from edge_knowledge.infrastructure.config import RuntimeConfig
from fastapi.testclient import TestClient

CASES = [
    {
        "id": "voice_two_conditions",
        "text": "# 演示声音方案\n"
        "DemoVoice 支持中文和声音克隆。PlainVoice 支持中文，不支持声音克隆。"
        "CloneVoice 支持声音克隆，但仅支持英文。",
        "question": "帮我找出一款支持中文并且支持克隆的模型",
        "candidates": ["DemoVoice", "PlainVoice", "CloneVoice"],
        "expected": "DemoVoice",
    },
    {
        "id": "database_two_conditions",
        "text": "# 演示数据库对比\n"
        "LocalDB 支持 JSON 且适合单机。ClusterDB 支持 JSON，必须集群部署。"
        "TinyDB 适合单机，但不支持 JSON。",
        "question": "帮我找出一个支持 JSON 并且适合单机的数据库",
        "candidates": ["LocalDB", "ClusterDB", "TinyDB"],
        "expected": "LocalDB",
    },
    {
        "id": "hotel_two_conditions",
        "text": "# Synthetic hotel comparison\n"
        "GreenHotel has parking and accessible rooms. BlueHotel has parking but no accessible rooms."
        "RedHotel has accessible rooms but no parking.",
        "question": "find one hotel with parking and accessible rooms",
        "candidates": ["GreenHotel", "BlueHotel", "RedHotel"],
        "expected": "GreenHotel",
    },
]


def evaluate(case: dict, events: list[dict], document: str) -> dict:
    answer = "".join(event.get("delta", "") for event in events)
    execution = next((event for event in events if event["type"] == "execution"), {})
    sources = next(
        (event.get("sources", []) for event in events if event["type"] == "sources"), []
    )
    matches = [
        (answer.casefold().find(name.casefold()), name)
        for name in case["candidates"]
        if name.casefold() in answer.casefold()
    ]
    first = min(matches)[1] if matches else ""
    citations = [int(value) for value in re.findall(r"\[(\d+)\]", answer)]
    checks = {
        "local_answer": execution.get("generator") == "local"
        and execution.get("result_kind") == "answer",
        "selected_reference_only": bool(sources)
        and all(source["document_id"] == document for source in sources),
        "full_original": bool(sources)
        and all(source.get("content_scope") == "full_document" for source in sources),
        "expected_first_named_candidate": first == case["expected"],
        "does_not_decline_supported_choice": not re.search(
            r"没有同时|无法确定|没有符合|no (?:matching|suitable)|cannot (?:determine|identify)",
            answer,
            re.IGNORECASE,
        ),
        "legal_citations": bool(citations)
        and all(1 <= value <= len(sources) for value in citations),
        "no_error": not any(event["type"] == "error" for event in events),
        "not_truncated": "达到本次生成长度上限" not in answer,
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "answer_characters": len(answer),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--embedding-path", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", choices=[case["id"] for case in CASES])
    args = parser.parse_args()
    report = {
        "scope": "isolated synthetic notes; actual local models; no cloud",
        "cases": [],
    }
    with tempfile.TemporaryDirectory(prefix="edge-answer-quality-") as directory:
        app = build_app(
            RuntimeConfig(
                data_dir=Path(directory),
                backend_token="quality-acceptance-token",
                deepseek_api_key="",
                model_offline=True,
                local_model_path=args.model_path.resolve(),
                prepared_model_dir=args.embedding_path.resolve(),
            )
        )
        with TestClient(
            app, headers={"Authorization": "Bearer quality-acceptance-token"}
        ) as client:
            assert client.get("/api/settings").json()["generation_provider"] == "local"
            route = next(
                route
                for route in app.routes
                if getattr(route, "path", "") == "/api/query"
            )
            chat = inspect.getclosurevars(route.endpoint).nonlocals["chat"]
            planned = []
            original = chat.queries.local_planner.plan

            def observe_plan(question, context):
                plan = original(question, context)
                planned.append(
                    {
                        **{
                            key: plan.get(key)
                            for key in ("operation", "source_scope", "use_context")
                        },
                        "context_count": len(context.get("current_documents", [])),
                        "explicit_reference": context.get("references_explicit"),
                        "allow_answer": context.get("allow_answer"),
                    }
                )
                return plan

            chat.queries.local_planner.plan = observe_plan
            for case in CASES:
                if args.case and case["id"] != args.case:
                    continue
                response = client.post(
                    "/api/libraries/default/documents",
                    files={"file": (case["id"] + ".md", case["text"].encode())},
                )
                assert response.status_code == 201, "fixture import failed"
                document = response.json()["document"]["id"]
                planned.clear()
                start = time.monotonic()
                response = client.post(
                    "/api/query",
                    json={
                        "question": case["question"],
                        "document_ids": [document],
                        "allow_planning": True,
                        "local_generation_only": True,
                        "lookup_mode": True,
                    },
                )
                if response.status_code != 200:
                    result = {"passed": False, "http_status": response.status_code}
                else:
                    events = [
                        json.loads(line[6:])
                        for line in response.text.splitlines()
                        if line.startswith("data: ")
                    ]
                    result = evaluate(case, events, document)
                report["cases"].append(
                    {
                        "id": case["id"],
                        "seconds": round(time.monotonic() - start, 2),
                        **result,
                        "plan": planned[-1] if planned else None,
                    }
                )
    report["passed"] = all(case["passed"] for case in report["cases"])
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n")
    print(encoded)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
