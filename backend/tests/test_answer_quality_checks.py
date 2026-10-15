"""Quality probes must reject answers that merely mention the expected option."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "answer_quality", Path(__file__).resolve().parents[2] / "scripts/check_answer_quality.py"
)
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("首选 DemoVoice，同时支持中文与克隆 [1]。", True),
        ("首选 PlainVoice，DemoVoice 也有记载 [1]。", False),
        ("没有同时满足要求的方案，资料中提到了 DemoVoice [1]。", False),
        ("首选 DemoVoice [2]。", False),
    ],
)
def test_quality_signal_requires_choice_and_valid_evidence(answer, expected):
    events = [
        {"type": "sources", "sources": [{"document_id": "doc", "content_scope": "full_document"}]},
        {"type": "execution", "generator": "local", "result_kind": "answer"},
        {"type": "delta", "delta": answer},
        {"type": "done"},
    ]
    assert quality.evaluate(quality.CASES[0], events, "doc")["passed"] is expected


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("没有符合全部条件的模型。PlainVoice 不支持克隆 [1]；CloneVoice 仅支持英文 [1]。", True),
        ("没有同时满足的模型。PlainVoice 不支持克隆 [1]；CloneVoice 不支持中文 [1]。", True),
        ("首选 PlainVoice。PlainVoice 不支持克隆 [1]；CloneVoice 仅支持英文 [1]。", False),
        ("没有符合条件的模型。", False),
    ],
)
def test_quality_signal_rejects_recommendation_when_no_joint_match(answer, expected):
    case = next(case for case in quality.CASES if case["id"] == "voice_no_joint_match")
    events = [
        {"type": "sources", "sources": [{"document_id": "doc", "content_scope": "full_document"}]},
        {"type": "execution", "generator": "local", "result_kind": "answer"},
        {"type": "delta", "delta": answer},
        {"type": "done"},
    ]
    assert quality.evaluate(case, events, "doc")["passed"] is expected


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("当前依据不足。", False),
        ("推荐 LocalPad，资料没有记录导出能力。CloudPad 未记载离线能力 [1]。", False),
        ("无法确认哪款同时满足。LocalPad 不支持导出；CloudPad 未记载离线能力 [1]。", False),
        ("无法确认。LocalPad 不具备导出能力；CloudPad 未记录离线能力 [1]。", False),
        ("没有同时满足的工具。LocalPad 未记载导出能力；CloudPad 未记载离线能力 [1]。", False),
        ("无法确认哪款同时满足。LocalPad 未记载导出能力；CloudPad 未记载离线能力 [1]。", True),
    ],
)
def test_quality_signal_requires_missing_facts_and_evidence(answer, expected):
    case = next(case for case in quality.CASES if case["id"] == "tool_missing_evidence")
    events = [
        {"type": "sources", "sources": [{"document_id": "doc", "content_scope": "full_document"}]},
        {"type": "execution", "generator": "local", "result_kind": "answer"},
        {"type": "delta", "delta": answer},
        {"type": "done"},
    ]
    assert quality.evaluate(case, events, "doc")["passed"] is expected


def test_quality_signal_requires_completed_response():
    events = [
        {"type": "sources", "sources": [{"document_id": "doc", "content_scope": "full_document"}]},
        {"type": "execution", "generator": "local", "result_kind": "answer"},
        {"type": "delta", "delta": "首选 DemoVoice [1]。"},
    ]
    assert not quality.evaluate(quality.CASES[0], events, "doc")["passed"]


def test_quality_signal_rejects_native_thinking_framing():
    events = [
        {"type": "sources", "sources": [{"document_id": "doc", "content_scope": "full_document"}]},
        {"type": "execution", "generator": "local", "result_kind": "answer"},
        {"type": "delta", "delta": "</think>首选 DemoVoice [1]。"},
        {"type": "done"},
    ]
    assert not quality.evaluate(quality.CASES[0], events, "doc")["passed"]


def test_quality_signal_recognizes_structured_generation_length_error():
    events = [
        {"type": "delta", "delta": "partial"},
        {"type": "error", "code": "local_answer_incomplete"},
    ]
    result = quality.evaluate(quality.CASES[0], events, "doc")
    assert not result["checks"]["not_truncated"]
    assert not result["passed"]
