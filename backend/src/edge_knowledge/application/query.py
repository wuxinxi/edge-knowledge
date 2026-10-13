"""Plan, validate, execute and present queries through separate application ports."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from edge_knowledge.domain.models import AppError, SearchHit
from edge_knowledge.domain.planning import calendar_constraints, ground_calendar_plan
from edge_knowledge.domain.query import Predicate, QuerySpec, query_contract
from edge_knowledge.domain.query_parser import local_plan

from .catalog import CatalogMirror
from .knowledge import KnowledgeService
from .ports import QueryPlanner

LABELS = {
    "authored_date": "写作/发布日期",
    "created_date": "创建日期",
    "published_date": "发布日期",
    "modified_date": "修改日期",
    "imported_date": "导入日期",
    "folder_month": "目录归档月份",
    "kind": "资料类型",
    "tags": "标签",
    "title": "标题",
    "filename": "文件名",
    "path": "相对路径",
    "text": "全文文字",
    "extension": "文件类型",
    "size": "文件大小（字节）",
    "duration": "时长（秒）",
    "chunks": "片段数",
}


def safe_text(value: object) -> str:
    return "".join(
        "\\" + char if char in "\\`*_{}[]<>()#!|" else char
        for char in str(value).replace("\n", " ")[:500]
    )


def leaves(predicate: Predicate) -> list[Predicate]:
    return (
        [predicate]
        if predicate.field
        else [item for p in predicate.all + predicate.any for item in leaves(p)]
    )


def describe(predicate: Predicate) -> str:
    if predicate.field:
        label = LABELS.get(predicate.field, predicate.field)
        value = predicate.value
        if predicate.field == "kind":
            labels = {
                "document": "文档",
                "image": "图片",
                "audio": "音频",
                "video": "视频",
                "bundle": "联合素材",
            }
            value = (
                "、".join(labels.get(v, str(v)) for v in value)
                if isinstance(value, list)
                else labels.get(value, value)
            )
        operator = {
            "eq": "等于",
            "ne": "不等于",
            "contains": "包含",
            "in": "属于",
            "gt": ">",
            "gte": "≥",
            "lt": "<",
            "lte": "≤",
            "exists": "已标注",
            "missing": "未标注",
        }[predicate.op]
        return (
            label
            + " "
            + operator
            + (" " + str(value) if predicate.op not in {"exists", "missing"} else "")
        )
    return (
        "（"
        + (" 或 " if predicate.any else " 且 ").join(
            describe(p) for p in predicate.any or predicate.all
        )
        + "）"
        if predicate.all or predicate.any
        else "全部已导入资料"
    )


class QueryService:
    def __init__(
        self,
        knowledge: KnowledgeService,
        mirror: CatalogMirror,
        search: Callable,
        planner: QueryPlanner | None = None,
        local_planner: QueryPlanner | None = None,
        compare: Callable | None = None,
    ):
        self.knowledge, self.mirror, self.search, self.planner = knowledge, mirror, search, planner
        self.local_planner = local_planner
        self.compare = compare

    def schema(self, library: str, ids: list[str]):
        with self.knowledge.transaction():
            docs = self.knowledge.repository.documents(library)
            if not set(ids) <= {doc.id for doc in docs}:
                raise AppError("引用资料不属于当前知识库。", 404, "reference_not_found")
            self.mirror.ensure(library, docs)
            return {
                "contract": query_contract(),
                "custom_fields": self.mirror.catalog.fields(library, ids),
            }

    def resolve(
        self,
        library: str,
        question: str,
        ids: list[str] | None = None,
        explicit: dict | None = None,
        allow_planner: bool = False,
        timezone: str = "Asia/Shanghai",
        local_only: bool = False,
    ) -> dict | None:
        ids = ids or []
        with self.knowledge.transaction():
            documents = self.knowledge.repository.documents(library)
            if not set(ids) <= {doc.id for doc in documents}:
                raise AppError("引用资料已删除或不属于当前知识库。", 404, "reference_not_found")
            now = datetime.now(ZoneInfo(timezone))
            spec = (
                QuerySpec.parse(explicit)
                if explicit is not None
                else local_plan(question, now.date())
            )
            planned = "local"
            local_provider = (
                local_only
                or self.knowledge.settings.read().get("generation_provider", "deepseek") == "local"
            )
            planner = self.local_planner if local_provider else self.planner
            metadata_required = spec is not None and spec.operation in {"aggregate", "clarify"}
            if (
                explicit is None
                and (spec is None or spec.operation == "clarify")
                and (allow_planner or local_provider)
                and planner
                and documents
            ):
                if not local_provider and not self.knowledge.settings.api_key():
                    raise AppError(
                        "AI 规划需要在设置中填写 DeepSeek API Key；也可以直接设置本地筛选条件。",
                        409,
                        "missing_api_key",
                    )
                constraints = (
                    calendar_constraints(question, now.date()) if metadata_required else {}
                )
                if constraints.get("clarification"):
                    spec = QuerySpec("clarify", clarification=constraints["clarification"])
                    return {
                        "kind": "clarification",
                        "content": spec.clarification,
                        "sources": [],
                        "notice": self._notice("local"),
                        "query": {"plan": spec.mapping(), "planner": "local"},
                    }
                self.mirror.ensure(library, documents)
                spec = QuerySpec.parse(
                    planner.plan(
                        question,
                        {
                            "contract": query_contract(),
                            "today": now.date().isoformat(),
                            "timezone": timezone,
                            "allow_answer": not local_only,
                            **constraints,
                            "custom_fields": [
                                {"field": item["field"], "type": item["type"]}
                                for item in self.mirror.catalog.fields(library, ids)
                            ],
                        },
                    )
                )
                planned = "local_model" if local_provider else "deepseek"
                if metadata_required and spec.operation in {"search", "answer"}:
                    raise AppError(
                        "这是统计需求，AI 计划不能改为根据检索片段生成数量。"
                        "请明确文字、标签或日期条件。",
                        422,
                        "invalid_planner_operation",
                    )
                spec = ground_calendar_plan(spec, constraints)
            if spec is None:
                return None
            spec = QuerySpec.parse(spec.mapping())
            if spec.operation == "clarify":
                return {
                    "kind": "clarification",
                    "content": "尚未执行查询，需要补充条件。\n\n"
                    + safe_text(spec.clarification or "请补充日期、筛选条件或统计口径。"),
                    "sources": [],
                    "notice": self._notice(planned),
                    "query": {
                        "plan": spec.mapping(),
                        "planner": planned,
                    },
                }
            if spec.operation == "answer" and (local_only or not allow_planner):
                return {
                    "kind": "clarification",
                    "content": "解释和总结请切换到助手模式；查找模式展示原文、筛选和统计结果。",
                    "sources": [],
                    "notice": self._notice(planned),
                }
            if spec.operation == "duplicates":
                return self._duplicates(library, documents, spec, ids, timezone, planned)
            self.mirror.ensure(library, documents)
            result = self.mirror.catalog.query(library, spec, ids, timezone)
            if spec.operation in {"search", "answer"}:
                selected = result.pop("selected_ids", [])
                if not selected:
                    hits = []
                else:
                    selected_set = set(selected)
                    kinds = sorted({doc.kind for doc in documents if doc.id in selected_set})
                    hits = self.search(
                        library,
                        spec.text_query or question,
                        min(spec.limit, self.knowledge.settings.read()["top_k"]),
                        selected,
                        kinds,
                    )
                return {
                    "kind": "answer" if spec.operation == "answer" else "retrieval",
                    "sources": hits,
                    "content": (
                        f"找到 {len({hit.document_id for hit in hits})} 份相关资料，结果如下。"
                    )
                    if hits
                    else "没有找到相关资料，请换个描述或调整筛选条件。",
                    "notice": self._notice(planned),
                    "query": {
                        "plan": spec.mapping(),
                        "summary": describe(spec.where),
                        "planner": planned,
                        "result": result,
                    },
                }
            alternatives = self._date_evidence(library, spec, ids, timezone)
            content = self._present(spec, result, alternatives)
            rows = result["rows"] + [
                row
                for alternative in alternatives
                if alternative["basis"] == "folder_month"
                for row in alternative["rows"]
            ]
            seen, sources = set(), []
            for row in rows:
                if row["document_id"] in seen or len(sources) >= 50:
                    continue
                seen.add(row["document_id"])
                provenance = (
                    row.get("authored_basis") or "目录/文件名月份"
                    if row.get("folder_month")
                    else row.get("authored_basis") or "元数据"
                )
                sources.append(
                    SearchHit(
                        row["document_id"],
                        row["filename"],
                        row["excerpt"],
                        "日期依据/元数据：" + provenance,
                        0,
                        0,
                        row["kind"],
                        row["ocr_status"],
                    )
                )
            return {
                "kind": "catalog",
                "content": content,
                "sources": sources,
                "notice": self._notice(planned),
                "query": {
                    "plan": spec.mapping(),
                    "summary": describe(spec.where),
                    "planner": planned,
                    "result": result,
                    "date_alternatives": alternatives,
                },
            }

    def _duplicates(self, library, documents, spec, ids, timezone, planned):
        if not self.compare:
            raise AppError("文档查重执行器尚未配置。", 503, "duplicate_tool_unavailable")
        # This tool's declared scope is document notes, not arbitrary media or a top-k search.
        spec = replace(spec, where=Predicate(all=(spec.where, Predicate("kind", "eq", "document"))))
        self.mirror.ensure(library, documents)
        selected = self.mirror.catalog.query(library, spec, ids, timezone)["selected_ids"]
        result = self.compare(library, selected, spec.threshold, spec.limit, spec.offset)
        content = f"已比较 **{result['scanned']} 份**文档笔记。"
        if result["total"]:
            content += (
                f"发现 **{result['total']} 对**重复或相似候选，"
                f"涉及 {result['candidate_documents']} 份资料。"
            )
            if result["pairs"]:
                content += (
                    "\n\n当前展示第 "
                    f"{spec.offset + 1}–{spec.offset + len(result['pairs'])} 对；"
                    f"相似度阈值 {spec.threshold:g}。"
                )
            else:
                content += "\n\n当前页没有候选，请在筛选面板中调整跳过数量。"
        else:
            content += f"没有找到达到相似度阈值 {spec.threshold:g} 的候选。"
        content += (
            "\n\n正文一致的候选直接保留；其余候选同时核对向量与正文文字。"
            "相似度不是重复概率，请对照判断。此次未修改资料。"
        )
        return {
            "kind": "comparison",
            "content": content,
            "sources": [],
            "comparisons": result["pairs"],
            "notice": self._notice(planned)
            + " 查重读取当前资料的已有向量，不重新嵌入；仅比较文档笔记。",
            "query": {
                "plan": spec.mapping(),
                "planner": planned,
                "result": {key: value for key, value in result.items() if key != "pairs"},
            },
        }

    @staticmethod
    def _notice(planned: str) -> str:
        return (
            (
                "本次已调用 DeepSeek 规划，仅发送问题与查询字段定义，不发送资料原文。"
                "结果由本机执行器计算。"
            )
            if planned == "deepseek"
            else "本次由本地模型理解问题，查询与统计在本机执行，没有调用 DeepSeek。"
            if planned == "local_model"
            else "本次仅在本机检索、筛选或统计，不调用 DeepSeek。精确统计不调用嵌入模型。"
        )

    def _date_evidence(self, library, spec, ids, timezone):
        fields = leaves(spec.where)
        authored = [p for p in fields if p.field == "authored_date"]
        if (
            spec.operation != "aggregate"
            or not authored
            or any(
                p.op not in {"gte", "lt"}
                or not isinstance(p.value, str)
                or not p.value.endswith("-01")
                for p in authored
            )
        ):
            return []

        # Only conjunctions admit a reliable alternative date cohort.
        def has_or(p):
            return bool(p.any) or any(has_or(child) for child in p.all)

        if has_or(spec.where):
            return []
        base = [p for p in fields if p.field != "authored_date"] + [
            Predicate("authored_date", "missing")
        ]
        alternatives = []
        for field in ["folder_month", "modified_date"]:
            filters = tuple(
                base
                + [
                    Predicate(field, p.op, p.value[:7] if field == "folder_month" else p.value)
                    for p in authored
                ]
            )
            alternate = replace(
                spec, where=Predicate(all=filters), metric="count", group_by="", offset=0
            )
            result = self.mirror.catalog.query(library, alternate, ids, timezone)
            if result["total"]:
                alternatives.append({"basis": field, **result})
        return alternatives

    def _present(self, spec, result, alternatives):
        if spec.operation == "aggregate":
            if spec.metric == "count":
                content = f"按查询条件匹配 **{result['total']} 篇**资料。"
            else:
                label = {"sum": "合计", "avg": "平均值", "min": "最小值", "max": "最大值"}[
                    spec.metric
                ]
                amount = result["value"] if result["value"] is not None else "无可用数值"
                field_label = LABELS.get(
                    spec.metric_field, spec.metric_field.removeprefix("metadata.")
                )
                content = f"{field_label}{label}：**{amount}**。覆盖 {result['total']} 份资料。"
        else:
            content = f"找到 **{result['total']} 份**符合条件的资料。"
        content += "\n\n查询条件：" + safe_text(describe(spec.where)) + "。"
        content += (
            f"\n\n范围：当前知识库/引用集合，共 {result['scope_total']} 份资料；"
            "每份文档只计一次，不按片段数统计。"
        )
        for field, count in result["missing_dates"].items():
            if count:
                content += (
                    f"\n\n范围内有 **{count} 篇**缺少{LABELS[field]}，"
                    "无法确认这些资料是否属于指定时间，未将其他日期冒充该日期。"
                )
        for alternative in alternatives:
            basis = LABELS[alternative["basis"]]
            content += (
                f"\n\n缺少写作日期的资料中，另有 **{alternative['total']} 篇**按{basis}"
                "符合时间条件。"
                "归档或修改日期不能证明实际写作日期。"
            )
        if result["missing_numeric"]:
            content += f"\n\n{result['missing_numeric']} 份资料缺少有效数值，未作为零参与计算。"
        if result["groups"]:
            content += "\n\n| 分组 | 文档数 | 统计结果 |\n| --- | ---: | ---: |\n" + "\n".join(
                f"| {safe_text(row['key'])} | {row['count']} | "
                f"{row['value'] if row['value'] is not None else '无数值'} |"
                for row in result["groups"]
            )
            if result["group_total"] > len(result["groups"]):
                content += (
                    f"\n\n共 {result['group_total']} 组，当前展示 {len(result['groups'])} 组。"
                )
            if spec.group_by == "tags":
                content += "\n\n一份资料可有多个标签，各标签组数量不能直接相加当作总数。"
        if result["rows"]:
            content += "\n\n" + "\n".join(
                f"{i}. {safe_text(row['title'])} · {safe_text(row['path'])}"
                for i, row in enumerate(result["rows"], result["offset"] + 1)
            )
        if result["total"] > len(result["rows"]):
            content += f"\n\n仅预览前 {spec.limit} 份依据，完整计算覆盖全部匹配文档。"
        return content
