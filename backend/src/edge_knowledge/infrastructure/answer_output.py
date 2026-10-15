"""Native-model answer transport, rendered as an ordinary Markdown stream."""

import json

from pydantic_core import from_json

from edge_knowledge.domain.models import AppError

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "minLength": 1, "maxLength": 300},
        "details": {"type": "string", "maxLength": 3500},
    },
    "required": ["answer", "details"],
    "additionalProperties": False,
}
ANSWER_FORMAT = (
    "\n本轮必须输出 JSON 对象，只有 answer 和 details 两个字符串字段。"
    "answer 是直接回应本轮问题的一句结论，先完成所有条件核对，再给出结论，不要先逐项罗列资料。"
    "用户只要一个且已有符合者时，选择一个即可，不必证明唯一最优。"
    "details 是带来源编号的依据、条件核对与限制。不能把 JSON 格式说明写进字段。"
)


def invalid_answer() -> AppError:
    return AppError("本地回答未完整生成，请重试。没有调用云端。", 503, "invalid_local_answer")


def unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate answer field")
        result[key] = value
    return result


class AnswerOutput:
    """Decode only answer text; partial JSON syntax never crosses the port.

    A details-first object must still display its answer first. Do not append
    details until the answer string is closed, or subsequent answer characters
    could be inserted ahead of already-emitted text. Unicode escapes and split
    surrogate pairs are decoded by the JSON parser, not by text substitutions.
    """

    def __init__(self):
        self.raw = ""
        self.delivered = ""

    @staticmethod
    def check(value):
        if not isinstance(value, dict) or set(value) - {"answer", "details"}:
            raise invalid_answer()
        for field, limit in (("answer", 300), ("details", 3500)):
            if field in value and (not isinstance(value[field], str) or len(value[field]) > limit):
                raise invalid_answer()

    def delta(self, answer: str) -> str:
        if not answer.startswith(self.delivered):
            raise invalid_answer()
        delta = answer[len(self.delivered) :]
        self.delivered = answer
        return delta

    def feed(self, content: str) -> str:
        self.raw += content
        if len(self.raw) > 65536:
            raise invalid_answer()
        try:
            partial = from_json(self.raw, allow_partial="trailing-strings")
            closed = from_json(self.raw, allow_partial=True)
        except ValueError:
            return ""
        self.check(partial)
        answer = partial.get("answer", "")
        if not answer.strip():
            return ""
        if "answer" in closed and partial.get("details"):
            answer += "\n\n" + partial["details"]
        return self.delta(answer)

    def finish(self, truncated: bool = False) -> str:
        # A thought-only completion still uses the existing single local retry.
        if not self.raw.strip():
            return ""
        if truncated:
            raise AppError(
                "本地回答达到生成长度上限，尚未完成。请重试或缩小本次问题范围。没有调用云端。",
                503,
                "local_answer_incomplete",
            )
        try:
            value = json.loads(self.raw, object_pairs_hook=unique_object)
        except ValueError as exc:
            raise invalid_answer() from exc
        self.check(value)
        if set(value) != {"answer", "details"} or not value["answer"].strip():
            raise invalid_answer()
        answer = value["answer"] + ("\n\n" + value["details"] if value["details"] else "")
        return self.delta(answer)
