"""Versioned, read-only query algebra. Neither SQL nor filesystem commands enter a plan."""

import json
import math
import re
from dataclasses import asdict, dataclass, field

from .metadata import calendar_date
from .models import AppError

FIELDS = {
    "title",
    "filename",
    "path",
    "kind",
    "extension",
    "tags",
    "text",
    "size",
    "duration",
    "chunks",
    "authored_date",
    "created_date",
    "published_date",
    "modified_date",
    "imported_date",
    "folder_month",
}
DATE_FIELDS = {name for name in FIELDS if name.endswith("_date")} | {"folder_month"}
NUMERIC_FIELDS = {"size", "duration", "chunks"}
OPS = {"eq", "ne", "contains", "in", "gt", "gte", "lt", "lte", "exists", "missing"}


def finite(value):
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def valid_field(name: str) -> bool:
    return name in FIELDS or bool(re.fullmatch(r"metadata\.[\w\-]{1,64}", name))


@dataclass(frozen=True)
class Predicate:
    field: str = ""
    op: str = "eq"
    value: object = None
    all: tuple["Predicate", ...] = ()
    any: tuple["Predicate", ...] = ()

    @classmethod
    def parse(cls, value: object, depth: int = 0) -> "Predicate":
        if not isinstance(value, dict) or depth > 4:
            raise AppError("筛选条件格式无效或嵌套过深。", 422, "invalid_query_plan")
        if set(value) <= {"all", "any"}:
            if "all" in value and "any" in value:
                raise AppError("每组条件只能使用 all 或 any。", 422, "invalid_query_plan")
            key = "any" if "any" in value else "all"
            rows = value.get(key, [])
            if not isinstance(rows, list) or len(rows) > 16 or key == "any" and not rows:
                raise AppError("筛选条件数量超限。", 422, "invalid_query_plan")
            return cls(**{key: tuple(cls.parse(row, depth + 1) for row in rows)})
        if set(value) - {"field", "op", "value"}:
            raise AppError("查询包含未允许的筛选字段。", 422, "invalid_query_plan")
        name, op, item = value.get("field"), value.get("op"), value.get("value")
        if (
            not isinstance(name, str)
            or not valid_field(name)
            or not isinstance(op, str)
            or op not in OPS
        ):
            raise AppError("筛选字段或操作不支持。", 422, "invalid_query_plan")
        if op not in {"exists", "missing"}:
            values = item if op == "in" else [item]
            if not isinstance(values, list) or not values or len(values) > 50:
                raise AppError("筛选值无效。", 422, "invalid_query_plan")
            if any(
                not isinstance(v, (str, int, float, bool))
                or isinstance(v, str)
                and len(v) > 2000
                or isinstance(v, (int, float))
                and not finite(v)
                for v in values
            ):
                raise AppError("筛选值无效。", 422, "invalid_query_plan")
            if name in NUMERIC_FIELDS and any(type(v) not in {int, float} for v in values):
                raise AppError("数值字段需要数值条件。", 422, "invalid_query_plan")
            if name in DATE_FIELDS:
                for v in values:
                    valid = isinstance(v, str) and (
                        bool(re.fullmatch(r"\d{4}-\d{2}", v)) and calendar_date(v + "-01")
                        if name == "folder_month"
                        else bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)) and calendar_date(v)
                    )
                    if not valid:
                        raise AppError(
                            "日期条件无效，请使用有效的日历日期。", 422, "invalid_query_plan"
                        )
            if name == "kind" and any(
                v not in {"document", "image", "audio", "video", "bundle"} for v in values
            ):
                raise AppError("资料类型无效。", 422, "invalid_query_plan")
        return cls(name, op, item)

    def mapping(self) -> dict:
        if self.field:
            return {"field": self.field, "op": self.op, "value": self.value}
        return {"any" if self.any else "all": [p.mapping() for p in self.any or self.all]}


@dataclass(frozen=True)
class QuerySpec:
    operation: str = "list"
    where: Predicate = field(default_factory=Predicate)
    metric: str = "count"
    metric_field: str = "size"
    group_by: str = ""
    group_date: str = "authored_date"
    order_by: str = "title"
    descending: bool = False
    limit: int = 20
    offset: int = 0
    text_query: str = ""
    clarification: str = ""
    threshold: float = 0.9
    version: int = 1
    use_context: bool = False
    source_scope: str = "excerpt"

    @classmethod
    def parse(cls, raw: object) -> "QuerySpec":
        try:
            bounded = len(json.dumps(raw, allow_nan=False)) <= 24000
        except (TypeError, ValueError, RecursionError):
            bounded = False
        if not bounded:
            raise AppError("查询计划过大或包含无效数值。", 422, "invalid_query_plan")
        if not isinstance(raw, dict) or set(raw) - set(cls.__dataclass_fields__):
            raise AppError("查询计划格式或版本不支持。", 422, "invalid_query_plan")
        values = {**raw, "where": Predicate.parse(raw.get("where", {}))}
        try:
            plan = cls(**values)
        except TypeError as exc:
            raise AppError("查询计划格式无效。", 422, "invalid_query_plan") from exc
        if any(
            not isinstance(getattr(plan, key), str)
            for key in ["operation", "metric", "metric_field", "group_by", "group_date", "order_by"]
        ):
            raise AppError("查询字段类型无效。", 422, "invalid_query_plan")
        if (
            type(plan.version) is not int
            or plan.version != 1
            or plan.operation
            not in {
                "list",
                "aggregate",
                "search",
                "read",
                "answer",
                "clarify",
                "duplicates",
            }
        ):
            raise AppError("查询操作不支持。", 422, "invalid_query_plan")
        if (
            type(plan.use_context) is not bool
            or not isinstance(plan.source_scope, str)
            or plan.source_scope
            not in {
                "excerpt",
                "full_document",
            }
        ):
            raise AppError("资料范围参数无效。", 422, "invalid_query_plan")
        if plan.operation not in {"read", "answer"} and plan.source_scope != "excerpt":
            raise AppError("这个操作不能读取全文。", 422, "invalid_query_plan")
        if plan.metric not in {"count", "sum", "avg", "min", "max"} or not isinstance(
            plan.metric_field, str
        ):
            raise AppError("统计操作无效。", 422, "invalid_query_plan")
        if plan.metric_field not in NUMERIC_FIELDS and not re.fullmatch(
            r"metadata\.[\w\-]{1,64}", plan.metric_field
        ):
            raise AppError("只能聚合数值字段。", 422, "invalid_query_plan")
        if plan.group_by not in {"", "month", "year", "folder"} and (
            not valid_field(plan.group_by) or plan.group_by == "text"
        ):
            raise AppError("分组维度无效。", 422, "invalid_query_plan")
        if (
            plan.group_date not in DATE_FIELDS
            or not isinstance(plan.order_by, str)
            or not (
                valid_field(plan.order_by)
                or plan.operation == "aggregate"
                and plan.group_by
                and plan.order_by in {"key", "value", "count"}
            )
        ):
            raise AppError("日期或排序字段无效。", 422, "invalid_query_plan")
        if (
            type(plan.limit) is not int
            or not 1 <= plan.limit <= 50
            or type(plan.offset) is not int
            or not 0 <= plan.offset <= 10000
        ):
            raise AppError("分页范围无效。", 422, "invalid_query_plan")
        if (
            type(plan.descending) is not bool
            or not isinstance(plan.text_query, str)
            or len(plan.text_query) > 4000
        ):
            raise AppError("查询参数无效。", 422, "invalid_query_plan")
        if not isinstance(plan.clarification, str) or len(plan.clarification) > 1000:
            raise AppError("澄清信息无效。", 422, "invalid_query_plan")
        if (
            type(plan.threshold) not in {int, float}
            or not finite(plan.threshold)
            or not 0 <= plan.threshold <= 1
        ):
            raise AppError("查重相似度需要 0–1 的有效数值。", 422, "invalid_query_plan")
        if plan.operation == "duplicates" and plan.text_query:
            raise AppError(
                "查重范围需要明确筛选条件，不能用语义前几条代替全库范围。",
                422,
                "invalid_query_plan",
            )
        if plan.operation == "aggregate" and plan.text_query:
            raise AppError(
                "语义相似度不能作为全量精确统计条件，请使用明确的文字或标签筛选。",
                422,
                "semantic_count_ambiguous",
            )
        return plan

    def mapping(self) -> dict:
        return {**asdict(self), "where": self.where.mapping()}


def query_contract() -> dict:
    """Shared planner contract; the executor still validates every returned field."""
    return {
        "version": 1,
        "operations": ["list", "aggregate", "search", "read", "answer", "clarify", "duplicates"],
        "use_context": "boolean; use only when the question refers to current_documents",
        "source_scope": ["excerpt", "full_document"],
        "read": (
            "Read complete saved text by selected IDs or title/filename/path filters; "
            "ambiguous identity requires clarification"
        ),
        "fields": sorted(FIELDS) + ["metadata.<flat scalar key>"],
        "kind_values": ["document", "image", "audio", "video", "bundle"],
        "where": {
            "all or any": [
                {"field": "allowed field", "op": sorted(OPS), "value": "scalar or list for in"}
            ]
        },
        "duplicates": "Read-only note comparison in full filtered scope; cutoff 0.9; no deletion",
        "threshold": "0..1 similarity cutoff, not a probability",
        "metric": ["count", "sum", "avg", "min", "max"],
        "metric_field": sorted(NUMERIC_FIELDS) + ["metadata.<numeric key>"],
        "group_by": [
            "",
            "month",
            "year",
            "kind",
            "extension",
            "tags",
            "folder",
            "metadata.<flat scalar key>",
        ],
        "group_date": sorted(DATE_FIELDS),
        "order_by": "allowed field",
        "descending": "boolean",
        "limit": "1..50",
        "offset": "0..10000",
        "text_query": "semantic search text; must be empty for aggregates",
        "clarification": "ask user when date, subject, or precision is uncertain",
        "example": QuerySpec(
            "aggregate", Predicate(all=(Predicate("kind", "eq", "document"),))
        ).mapping(),
    }
