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
    ]
    assert quality.evaluate(quality.CASES[0], events, "doc")["passed"] is expected
