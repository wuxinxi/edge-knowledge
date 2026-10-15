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
    {
        "id": "tool_answer_last",
        "text": "# 合成工具对比\n"
        "CloudPad 支持导出，但不支持离线。LocalPad 支持离线，但不支持导出。"
        "PocketPad 支持离线，也支持导出。",
        "question": "帮我选一个既能离线使用又能导出的工具",
        "candidates": ["CloudPad", "LocalPad", "PocketPad"],
        "expected": "PocketPad",
    },
    {
        "id": "voice_no_joint_match",
        "text": "# 合成声音能力清单\n"
        "PlainVoice 支持中文，不支持声音克隆。CloneVoice 支持声音克隆，但仅支持英文。",
        "question": "帮我选一款同时支持中文和声音克隆的模型",
        "candidates": ["PlainVoice", "CloneVoice"],
        "expected": None,
        "required_patterns": [
            r"PlainVoice",
            r"CloneVoice",
            r"不支持.*克隆",
            r"(?:仅|只).*英(?:文|语)|(?:不支持|未满足).*中文",
        ],
    },
    {
        "id": "tool_missing_evidence",
        "text": "# 合成工具记录\n"
        "LocalPad 支持离线。CloudPad 支持导出。资料没有记录 LocalPad 的导出能力，"
        "也没有记录 CloudPad 的离线能力。",
        "question": "选一个既支持离线又支持导出的工具",
        "candidates": ["LocalPad", "CloudPad"],
        "expected": None,
        "required_patterns": [
            r"LocalPad",
            r"CloudPad",
            r"未(?:记录|记载|提及|知)|没有记录|不足|无法确认",
            r"(?:不能|无法|尚未).*确认|待确认|需(?:要|进一步)?确认",
        ],
        "forbidden_patterns": [
            r"LocalPad[^。；！？\n]{0,16}不(?:支持|具备|提供)[^。；！？\n]{0,6}导出",
            r"CloudPad[^。；！？\n]{0,16}不(?:支持|具备|提供)[^。；！？\n]{0,6}离线",
        ],
    },
    {
        "id": "database_followup_conditions",
        "text": "# 合成数据库选型\n"
        "FirstDB 支持 JSON、适合单机，不支持加密。SafeDB 支持 JSON、适合单机，也支持加密。"
        "OtherDB 支持加密，但不支持 JSON，且必须集群部署。",
        "previous_question": "选一个支持 JSON 并且适合单机部署的数据库",
        "previous_expected": ["FirstDB", "SafeDB"],
        "question": "那如果还要求支持加密呢？",
        "candidates": ["FirstDB", "SafeDB", "OtherDB"],
        "expected": "SafeDB",
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
    decline = bool(
        re.search(
            r"没有同时|无法确定|没有符合|no (?:matching|suitable)|cannot (?:determine|identify)",
            answer,
            re.IGNORECASE,
        )
    )
    # These are bounded fixture signals, not a general semantic truth grader.
    # Naming the expected entities and their limitations cannot excuse a
    # contradictory recommendation in an unsupported-choice case.
    plain = re.sub(r"[*`#]", "", answer)
    unsupported_recommendation = any(
        re.search(
            r"(?:^|[。！？\n])\s*(?:[-\d.]+\s*)?(?:可以|建议|优先|首选|推荐)"
            r"[^。！？\n]{0,30}" + re.escape(name),
            plain,
            re.IGNORECASE,
        )
        for name in case["candidates"]
    )
    abstains = bool(
        re.search(
            r"(?:没有|暂无|不能|无法|不足以|尚未|不应)[^。！？\n]{0,30}"
            r"(?:同时|满足|符合|确定|推荐|选出|选择|确认)",
            plain,
        )
    )
    checks = {
        "local_answer": execution.get("generator") == "local"
        and execution.get("result_kind") == "answer",
        "selected_reference_only": bool(sources)
        and all(source["document_id"] == document for source in sources),
        "full_original": bool(sources)
        and all(source.get("content_scope") == "full_document" for source in sources),
        "expected_first_named_candidate": first == case["expected"]
        if case["expected"] is not None
        else True,
        "does_not_decline_supported_choice": not decline
        if case["expected"] is not None
        else True,
        "evidence_limit_explained": all(
            re.search(pattern, answer, re.IGNORECASE)
            for pattern in case.get("required_patterns", [])
        ),
        "unsupported_choice_not_recommended": case["expected"] is not None
        or (abstains and not unsupported_recommendation),
        "missing_facts_not_negated": not any(
            re.search(pattern, plain, re.IGNORECASE)
            for pattern in case.get("forbidden_patterns", [])
        ),
        "legal_citations": bool(citations)
        and all(1 <= value <= len(sources) for value in citations),
        "no_error": not any(event["type"] == "error" for event in events),
        "completed": any(event["type"] == "done" for event in events),
        "no_native_thinking_framing": not re.search(r"</?think>", answer),
        "not_truncated": "达到本次生成长度上限" not in answer,
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "answer_characters": len(answer),
    }


def query(client: TestClient, payload: dict) -> tuple[int, list[dict]]:
    response = client.post("/api/query", json=payload)
    if response.status_code != 200:
        return response.status_code, []
    return response.status_code, [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


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
                payload = {
                    "question": case["question"],
                    "document_ids": [document],
                    "allow_planning": True,
                    "local_generation_only": True,
                    "lookup_mode": True,
                }
                previous_ok = True
                if previous_question := case.get("previous_question"):
                    status, previous_events = query(
                        client, {**payload, "question": previous_question}
                    )
                    previous_answer = "".join(
                        event.get("delta", "") for event in previous_events
                    )
                    previous_sources = next(
                        (
                            event.get("sources", [])
                            for event in previous_events
                            if event["type"] == "sources"
                        ),
                        [],
                    )
                    previous_ok = status == 200 and any(
                        evaluate(
                            {**case, "expected": expected}, previous_events, document
                        )["passed"]
                        for expected in case["previous_expected"]
                    )
                    payload["history"] = [
                        {"role": "user", "content": previous_question},
                        {"role": "assistant", "content": previous_answer},
                    ]
                    # Like a normal follow-up, these are optional previous
                    # documents, not manually pinned references.
                    payload["document_ids"] = []
                    payload["context_document_ids"] = list(
                        dict.fromkeys(
                            source["document_id"] for source in previous_sources
                        )
                    )
                    planned.clear()
                status, events = query(client, payload) if previous_ok else (0, [])
                if status != 200:
                    result = {"passed": False, "http_status": status}
                else:
                    result = evaluate(case, events, document)
                report["cases"].append(
                    {
                        "id": case["id"],
                        "seconds": round(time.monotonic() - start, 2),
                        **result,
                        **(
                            {"previous_passed": previous_ok}
                            if case.get("previous_question")
                            else {}
                        ),
                        "history_messages": len(payload.get("history", [])),
                        "plan": planned[-1] if planned else None,
                    }
                )
                print(
                    json.dumps({"case": case["id"], "passed": result["passed"]}),
                    flush=True,
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
