import json
from types import SimpleNamespace

import pytest

from edge_knowledge.domain.models import AppError
from edge_knowledge.infrastructure.planner import DeepSeekQueryPlanner


def test_planner_adapter_sends_only_question_and_contract_in_json_mode(system, monkeypatch):
    _, knowledge, _, _ = system
    knowledge.settings.update({"api_key": "test-key"})
    captured = []

    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def create(self, **kwargs):
            captured.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=json.dumps({"operation": "aggregate"}))
                    )
                ]
            )

    monkeypatch.setattr("edge_knowledge.infrastructure.planner.OpenAI", Client)
    result = DeepSeekQueryPlanner(knowledge.settings).plan(
        "统计笔记", {"today": "2026-10-13", "contract": {"version": 1}}
    )
    assert result == {"operation": "aggregate"}
    assert captured[0]["response_format"] == {"type": "json_object"}
    assert captured[0]["messages"][-1]["content"] == "统计笔记"
    assert "test-key" not in json.dumps(captured)
    assert captured[0]["stream"] is False


def test_empty_planner_output_is_a_terminal_failure(system, monkeypatch):
    _, knowledge, _, _ = system

    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def create(self, **kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=""))])

    monkeypatch.setattr("edge_knowledge.infrastructure.planner.OpenAI", Client)
    with pytest.raises(AppError) as exc:
        DeepSeekQueryPlanner(knowledge.settings).plan("问题", {})
    assert exc.value.code == "invalid_planner_output"
