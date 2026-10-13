"""Parameterized SQLite execution of a closed read-only query algebra."""

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from edge_knowledge.domain.models import AppError
from edge_knowledge.domain.query import DATE_FIELDS, FIELDS, Predicate, QuerySpec


class SQLiteDocumentCatalog:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS documents (library TEXT, document_id TEXT, "
                "version TEXT, record TEXT, body TEXT, PRIMARY KEY(library, document_id))"
            )
            for field in [
                "kind",
                "authored_date",
                "modified_date",
                "imported_date",
                "folder_month",
            ]:
                db.execute(
                    f"CREATE INDEX IF NOT EXISTS catalog_{field} "
                    f"ON documents(library, json_extract(record, '$.{field}'))"
                )
        os.chmod(path, 0o600)

    def _connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def versions(self, library):
        with self._connect() as db:
            return dict(
                db.execute("SELECT document_id, version FROM documents WHERE library=?", (library,))
            )

    def upsert(self, library, document, version, record, text):
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO documents VALUES (?, ?, ?, ?, ?)",
                (
                    library,
                    document,
                    version,
                    json.dumps(record, ensure_ascii=False, allow_nan=False),
                    text,
                ),
            )

    def prune(self, library, active):
        with self._connect() as db:
            db.execute(
                "DELETE FROM documents WHERE library=? AND document_id NOT IN "
                "(SELECT value FROM json_each(?))",
                (library, json.dumps(active)),
            )

    def delete(self, library, ids):
        with self._connect() as db:
            db.execute(
                "DELETE FROM documents WHERE library=? AND document_id IN "
                "(SELECT value FROM json_each(?))",
                (library, json.dumps(ids)),
            )

    def fields(self, library, ids):
        scope, params = "library=?", [library]
        if ids:
            scope += " AND document_id IN (SELECT value FROM json_each(?))"
            params.append(json.dumps(ids))
        with self._connect() as db:
            rows = db.execute(
                "SELECT m.key, m.type, COUNT(DISTINCT document_id) "
                "FROM documents JOIN json_each(record, '$.metadata') m ON 1 "
                "WHERE " + scope + " GROUP BY m.key, m.type ORDER BY m.key LIMIT 200",
                params,
            )
            return [
                {"field": "metadata." + key, "type": kind, "documents": count}
                for key, kind, count in rows
            ]

    @staticmethod
    def _expr(name: str, params: list):
        if name == "text":
            return "body"
        if name == "imported_date":
            return "local_import_date(json_extract(record, '$.imported_at'))"
        if name in FIELDS:
            return f"json_extract(record, '$.{name}')"
        params.append("$." + name)
        return "json_extract(record, ?)"

    def _where(self, predicate: Predicate, params: list):
        if not predicate.field:
            rows = predicate.any or predicate.all
            if not rows:
                return "1"
            return (
                "("
                + (" OR " if predicate.any else " AND ").join(self._where(p, params) for p in rows)
                + ")"
            )
        expr = self._expr(predicate.field, params)
        if predicate.op in {"exists", "missing"}:
            if predicate.field == "tags":
                return f"json_array_length({expr}) " + (
                    "> 0" if predicate.op == "exists" else "= 0"
                )
            return expr + (" IS NOT NULL" if predicate.op == "exists" else " IS NULL")
        if predicate.field == "tags" and predicate.op in {"eq", "contains", "in", "ne"}:
            items = predicate.value if predicate.op == "in" else [predicate.value]
            params.append(json.dumps(items))
            return (
                ("NOT " if predicate.op == "ne" else "")
                + f"EXISTS(SELECT 1 FROM json_each({expr}) t WHERE t.value IN "
                "(SELECT value FROM json_each(?)))"
            )
        if predicate.op == "contains":
            params.append(str(predicate.value))
            return f"instr(lower(COALESCE({expr}, '')), lower(?)) > 0"
        if predicate.op == "in":
            params.append(json.dumps(predicate.value))
            return f"{expr} IN (SELECT value FROM json_each(?))"
        if (
            predicate.field.startswith("metadata.")
            and type(predicate.value) in {int, float}
            and predicate.op in {"gt", "gte", "lt", "lte"}
        ):
            expr = f"CASE WHEN json_type(record, ?) IN ('integer','real') THEN {expr} END"
            params.append("$." + predicate.field)
        params.append(predicate.value)
        operator = {"eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[
            predicate.op
        ]
        return f"{expr} {operator} ?"

    @staticmethod
    def _fields(predicate: Predicate):
        return (
            {predicate.field}
            if predicate.field
            else set().union(
                *(SQLiteDocumentCatalog._fields(p) for p in predicate.all + predicate.any)
            )
        )

    def query(
        self, library: str, plan: QuerySpec, ids: list[str], timezone: str = "Asia/Shanghai"
    ) -> dict:
        zone = ZoneInfo(timezone)

        def imported_date(value):
            try:
                stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return stamp.replace(tzinfo=stamp.tzinfo or UTC).astimezone(zone).date().isoformat()
            except (ValueError, TypeError, AttributeError):
                return None

        # Validate again even for callers bypassing API and planner boundaries.
        plan = QuerySpec.parse(plan.mapping())
        scope, params = "library=?", [library]
        if ids:
            scope += " AND document_id IN (SELECT value FROM json_each(?))"
            params.append(json.dumps(ids))
        where_params = []
        where = self._where(plan.where, where_params)
        selection = scope + " AND " + where
        args = params + where_params
        with self._connect() as db:
            db.create_function("local_import_date", 1, imported_date, deterministic=True)
            total = db.execute(
                "SELECT COUNT(*) FROM documents WHERE " + selection, args
            ).fetchone()[0]
            scope_total = db.execute(
                "SELECT COUNT(*) FROM documents WHERE " + scope, params
            ).fetchone()[0]
            custom = self._fields(plan.where) | {plan.metric_field, plan.order_by, plan.group_by}
            for name in custom:
                if name.startswith("metadata.") and scope_total:
                    present = db.execute(
                        "SELECT COUNT(*) FROM documents WHERE "
                        + scope
                        + " AND json_type(record, ?) IS NOT NULL",
                        params + ["$." + name],
                    ).fetchone()[0]
                    if not present:
                        raise AppError(
                            "查询使用了当前资料范围中不存在的自定义字段，请检查字段定义。",
                            422,
                            "unknown_metadata_field",
                        )
            dates = self._fields(plan.where) & DATE_FIELDS
            if plan.group_by in {"month", "year"}:
                dates.add(plan.group_date)
            missing_dates = {}
            for field in sorted(dates):
                date_params = []
                date_expr = self._expr(field, date_params)
                missing_dates[field] = db.execute(
                    "SELECT COUNT(*) FROM documents WHERE "
                    + scope
                    + " AND "
                    + date_expr
                    + " IS NULL",
                    params + date_params,
                ).fetchone()[0]
            text_missing = db.execute(
                "SELECT COUNT(*) FROM documents WHERE "
                + scope
                + " AND json_extract(record, '$.text_complete')=0",
                params,
            ).fetchone()[0]
            if "text" in self._fields(plan.where) and text_missing:
                raise AppError(
                    "部分旧资料缺少完整原文，无法保证全文筛选的完整性；请重新同步或导入这些资料。",
                    409,
                    "incomplete_text_index",
                )
            order_params = []
            expr = self._expr(plan.order_by, order_params)
            # Stable paging, nulls last, including dynamic metadata fields.
            ordered = (
                f" ORDER BY ({expr} IS NULL), {expr} {'DESC' if plan.descending else 'ASC'}, "
                "document_id LIMIT ? OFFSET ?"
            )
            rows = db.execute(
                "SELECT record, substr(body,1,1200) FROM documents WHERE " + selection + ordered,
                args + order_params + order_params + [plan.limit, plan.offset],
            ).fetchall()
            documents = [{**json.loads(record), "excerpt": excerpt} for record, excerpt in rows]
            for document in documents:
                document["imported_date"] = imported_date(document.get("imported_at"))
            value, groups, group_total, missing_numeric = None, [], 0, 0
            if plan.operation == "aggregate":
                select_params = []
                if plan.metric == "count":
                    metric = "COUNT(DISTINCT document_id)"
                    missing_metric = "0"
                else:
                    numeric = (
                        "CASE WHEN json_type(record, ?) IN ('integer','real') "
                        "THEN json_extract(record, ?) END"
                    )
                    select_params.extend(["$." + plan.metric_field] * 2)
                    metric = plan.metric.upper() + "(" + numeric + ")"
                    missing_metric = (
                        "SUM(CASE WHEN json_type(record, ?) NOT IN ('integer','real') "
                        "OR json_type(record, ?) IS NULL THEN 1 ELSE 0 END)"
                    )
                    select_params.extend(["$." + plan.metric_field] * 2)
                value, missing_numeric = db.execute(
                    "SELECT "
                    + metric
                    + ", "
                    + missing_metric
                    + " FROM documents WHERE "
                    + selection,
                    select_params + args,
                ).fetchone()
                missing_numeric = missing_numeric or 0
                if plan.group_by:
                    group_params, join = [], ""
                    if plan.group_by in {"month", "year"}:
                        group = (
                            "substr("
                            + self._expr(plan.group_date, group_params)
                            + ", 1, "
                            + ("7" if plan.group_by == "month" else "4")
                            + ")"
                        )
                    elif plan.group_by == "tags":
                        group, join = "tag.value", " LEFT JOIN json_each(record, '$.tags') tag ON 1"
                    else:
                        group = "json_extract(record, ?)"
                        group_params = ["$." + plan.group_by]
                    sql = (
                        "SELECT "
                        + group
                        + " AS bucket, "
                        + metric
                        + " AS value"
                        + ", "
                        + missing_metric
                        + ", COUNT(DISTINCT document_id) AS count FROM documents"
                        + join
                        + " WHERE "
                        + selection
                        + " GROUP BY bucket ORDER BY "
                        + ({"value": "value", "count": "count"}.get(plan.order_by, "bucket"))
                        + (" DESC" if plan.descending else " ASC")
                        + ", bucket"
                    )
                    all_groups = db.execute(sql, group_params + select_params + args).fetchall()
                    group_total = len(all_groups)
                    groups = [
                        {
                            "key": key or "未标注",
                            "value": amount,
                            "missing_numeric": absent or 0,
                            "count": count,
                        }
                        for key, amount, absent, count in all_groups[
                            plan.offset : plan.offset + plan.limit
                        ]
                    ]
            return {
                "total": total,
                "rows": documents,
                "value": value,
                "groups": groups,
                "group_total": group_total,
                "scope_total": scope_total,
                "missing_dates": missing_dates,
                "missing_numeric": missing_numeric,
                "text_incomplete": text_missing,
                "offset": plan.offset,
                "limit": plan.limit,
                **(
                    {
                        "selected_ids": [
                            row[0]
                            for row in db.execute(
                                "SELECT document_id FROM documents WHERE " + selection, args
                            )
                        ]
                    }
                    if plan.operation in {"search", "answer", "duplicates"}
                    else {}
                ),
            }
