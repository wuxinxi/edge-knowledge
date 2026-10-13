"""Ground unambiguous calendar slots before executing any model's plan."""

import re
from dataclasses import replace
from datetime import date

from .models import AppError
from .query import DATE_FIELDS, Predicate, QuerySpec

MONTHS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
}


def normalize_calendar_text(question: str) -> str:
    return re.sub(
        r"(十二|十一|[一二三四五六七八九十])\s*月", lambda m: f"{MONTHS[m[1]]}月", question
    )


def calendar_constraints(question: str, today: date) -> dict:
    text = normalize_calendar_text(question)
    if re.search(
        r"\d+\s*(?:日|号)|\d{4}[-/]\d{1,2}[-/]\d{1,2}|季度|第[一二三四1-4]季|\bQ[1-4]\b", text
    ):
        return {}
    months = re.findall(r"(?<!\d)(\d{1,2})\s*月", text)
    explicit = re.findall(r"(\d{4})\s*(?:年|[-/])\s*(\d{1,2})(?:\s*月)?", text)
    years = re.findall(r"(\d{4})\s*年", text)
    if len(months) > 1 or len(explicit) > 1 or len(set(years)) > 1:
        return {}
    basis = (
        "imported_date"
        if re.search(r"导入|添加", text)
        else "modified_date"
        if re.search(r"修改|更新|编辑", text)
        else "published_date"
        if "发布" in text
        else "created_date"
        if "创建" in text
        else "authored_date"
    )
    start = end = None
    try:
        if len(explicit) == 1 and len(months) <= 1:
            year, month = map(int, explicit[0])
            start = date(year, month, 1)
            end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
        elif len(months) == 1 and not explicit:
            if not years and not re.search(r"今年|去年", text):
                return {"clarification": "请问是哪一年的这个月份？"}
            year = int(years[0]) if len(years) == 1 else today.year - ("去年" in text)
            month = int(months[0])
            start = date(year, month, 1)
            end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
        elif not explicit and not months and len(years) == 1:
            start = date(int(years[0]), 1, 1)
            end = date(int(years[0]) + 1, 1, 1)
        elif re.search(r"上个月|本月|这个月", text):
            year, month = today.year, today.month
            if "上个月" in text:
                year, month = (year - 1, 12) if month == 1 else (year, month - 1)
            start = date(year, month, 1)
            end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    except ValueError:
        return {"clarification": "请提供有效的年份和月份。"}
    if not start or not end:
        return {}
    return {
        "required_kind": "document" if re.search(r"笔记|文章|文档", text) else "",
        "required_date_conditions": [
            {"field": basis, "op": "gte", "value": start.isoformat()},
            {"field": basis, "op": "lt", "value": end.isoformat()},
        ],
    }


def ground_calendar_plan(plan: QuerySpec, constraints: dict) -> QuerySpec:
    if plan.operation == "clarify" or not constraints:
        return plan
    if constraints.get("clarification"):
        raise AppError("时间条件缺少年份，请补充后查询。", 422, "ambiguous_plan_date")

    def leaves(p: Predicate):
        return [p.mapping()] if p.field else [v for item in p.all or p.any for v in leaves(item)]

    expected = constraints.get("required_date_conditions", [])
    dates = [p for p in leaves(plan.where) if p["field"] in DATE_FIELDS]
    if any(p not in expected for p in dates):
        raise AppError(
            "模型计划改变了问题中的日期范围，未执行查询。请补充条件或使用筛选面板。",
            422,
            "ungrounded_plan_date",
        )
    required = [Predicate.parse(p) for p in expected]
    if constraints.get("required_kind"):
        required.append(Predicate("kind", "eq", constraints["required_kind"]))
    return replace(plan, where=Predicate(all=(plan.where, *required)))
