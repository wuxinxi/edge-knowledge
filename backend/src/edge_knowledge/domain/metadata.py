"""Normalized, provenance-aware metadata; import time is never an authored date."""

import re
from datetime import date


def calendar_date(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.match(r"^(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})(?:日)?(?=$|[T\s])", value)
    if not match:
        return None
    try:
        return date(*map(int, match.groups())).isoformat()
    except ValueError:
        return None


def path_month(path: str) -> str | None:
    values = {
        f"{int(m[1]):04d}-{int(m[2]):02d}"
        for m in re.finditer(r"(?<!\d)(\d{4})[-/年](\d{1,2})(?=月|[-/_.\s]|$)", path)
        if 1 <= int(m[2]) <= 12
    }
    return next(iter(values)) if len(values) == 1 else None


def normalize_metadata(raw: dict) -> dict:
    values = {re.sub(r"[-_\s]", "", key).casefold(): value for key, value in raw.items()}

    def stamp(names):
        return next(
            (calendar_date(values.get(key)) for key in names if calendar_date(values.get(key))),
            None,
        )

    created = stamp(["createdat", "created", "creationdate", "写作日期", "创建日期"])
    published = stamp(["publishedat", "publishdate", "published", "发布日期", "date", "日期"])
    modified = stamp(
        ["updatedat", "updated", "modifiedat", "modified", "lastmodified", "修改日期", "更新日期"]
    )
    tags = values.get("tags", values.get("标签", []))
    if isinstance(tags, str):
        tags = [tag for tag in re.split(r"[,，\s]+", tags) if tag]
    tags = list(dict.fromkeys(str(tag)[:100] for tag in tags)) if isinstance(tags, list) else []
    title = values.get("title", values.get("标题", ""))
    return {
        "title": str(title)[:500] if isinstance(title, (str, int, float)) else "",
        "created_date": created,
        "published_date": published,
        "authored_date": created or published,
        "modified_date": modified,
        "authored_basis": "创建日期" if created else "发布日期/date" if published else "",
        "tags": tags[:100],
        "metadata": raw,
    }
