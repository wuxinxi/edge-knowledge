"""Bounded local compiler for explicit operations and date slots, not a sentence whitelist.

Open-ended interpretation belongs to the optional planner port. Ambiguity never becomes a count.
"""

import re
from datetime import date

from .lookup import local_lookup
from .planning import calendar_constraints, normalize_calendar_text
from .query import Predicate, QuerySpec


def local_plan(question: str, today: date) -> QuerySpec | None:
    question = normalize_calendar_text(question)
    aggregate = re.search(
        r"多少\s*[篇份个]|几篇|几份|数量|总数|统计|(?:笔记|文章|文档|资料)(?:的|有|共|一共|总共|\s)*多少",
        question,
    )
    if not aggregate:
        lookup = local_lookup(question)
        return (
            QuerySpec(
                "search",
                Predicate(
                    all=tuple(
                        Predicate("kind", "in", list(lookup.kinds))
                        for _ in [0]
                        if lookup and lookup.kinds
                    )
                ),
                text_query=lookup.query if lookup else question,
            )
            if lookup
            else None
        )
    if not re.search(r"笔记|文章|文档|资料", question):
        return None
    constraints = calendar_constraints(question, today)
    dates = re.findall(r"(\d{4})\s*(?:年|[-/])\s*(\d{1,2})(?:\s*月)?", question)
    # A local date slot cannot safely absorb topic predicates, several months, or day ranges.
    form = re.sub(r"\d{4}\s*(?:年|[-/])\s*\d{1,2}\s*月?|\d{4}\s*年|\d{1,2}\s*月", "", question)
    simple = re.fullmatch(
        r"(?:请|帮我|帮忙|查一下|查询|查找|查|统计|我|在|的|写|修改|更新|编辑|导入|添加|创建|发布|新增|了|过|共|总共|一共|有|多少|几|篇|份|个|笔记|文章|文档|资料|数量|总数|月份|今年|去年|上个月|本月|这个月|出|[\s，。？！,?.!:：])*",
        form,
    )
    if (
        re.search(
            r"关于|包含|提到|标签|主题|分类|[A-Za-z]|\d+\s*日|\d+\s*月.*\d+\s*月|季度|每月|按月|按年|分别",
            question,
        )
        or len(dates) > 1
        or not simple
    ):
        return QuerySpec(
            "clarify",
            clarification=(
                "请在“筛选与统计”中设置组合条件，或明确开启 AI 模式规划这次查询。"
                "本地模式不会调用 DeepSeek。"
            ),
        )
    if not constraints.get("required_date_conditions"):
        return QuerySpec(
            "clarify",
            clarification=constraints.get("clarification")
            or "请提供完整年份和月份，或在“筛选与统计”中选择时间范围。",
        )
    predicates = tuple(Predicate.parse(p) for p in constraints["required_date_conditions"])
    return QuerySpec(
        "aggregate",
        Predicate(all=(Predicate("kind", "eq", "document"), *predicates)),
        group_date=predicates[0].field,
    )
