"""受限语义查询、逻辑计划、SQLAlchemy Core 编译和质量判定。"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field
from sqlalchemy import and_, bindparam, column, func, literal, select, table
from sqlalchemy.dialects import mssql

from src.semantic_layer.models import (
    BusinessObjectVersion,
    DatasetKey,
    DatasetRelation,
    ObjectVersionMetric,
    SemanticDataset,
    SemanticField,
)
from src.semantic_layer.registry import (
    SemanticRegistry,
    _DEFERRED_OUTPATIENT_METRICS,
    _DEFERRED_OUTPATIENT_REASON,
)


QueryScopeName = Literal["whole_admission", "segment", "whole_settlement", "fee_item"]


class SemanticQueryPlanningError(ValueError):
    """查询无法由已发布语义模型安全、唯一地规划。"""


class QueryAnchor(BaseModel):
    field_code: str
    value: str | int | float


class QueryScope(BaseModel):
    entity_code: str
    anchor: QueryAnchor
    query_scope: QueryScopeName = "whole_admission"


class QueryFilter(BaseModel):
    field_code: str
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "is_null", "is_not_null"]
    value: Any = None


class QueryOrder(BaseModel):
    field_code: str
    direction: Literal["asc", "desc"] = "asc"


class SemanticQuery(BaseModel):
    object_code: str
    scope: QueryScope
    metrics: list[str] = Field(min_length=1)
    group_by: list[str] = Field(default_factory=list)
    filters: list[QueryFilter] = Field(default_factory=list)
    order_by: list[QueryOrder] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=100)


class PlanScope(BaseModel):
    entity: str
    anchor_field: str


class PlanBranch(BaseModel):
    branch_id: str
    dataset: str
    source_grain: list[str]
    aggregate_to: list[str]
    metrics: list[str]
    preaggregate_before_join: bool = True


class PlanJoin(BaseModel):
    left: str
    right: str
    type: Literal["left"] = "left"
    on: list[str]


class LogicalQueryPlan(BaseModel):
    model_version: str
    root_object: str
    scope: PlanScope
    query_scope: QueryScopeName
    result_grain: list[str]
    common_grain: list[str]
    branches: list[PlanBranch]
    joins: list[PlanJoin]
    quality_checks: list[str]
    datasets_used: list[str]
    plan_hash: str = ""


class QueryEvidence(BaseModel):
    plan_hash: str
    datasets_used: list[str]
    anchor_count: int = 1
    segment_count: int = 0
    matched_segment_count: int = 0
    extra_segment_count: int = 0
    reference_count: int = 0
    matched_reference_count: int = 0
    extra_reference_count: int = 0
    duplicate_key_count: int = 0
    stay_start_date: str | None = None
    stay_end_date: str | None = None
    duration_ms: int = 0


class SemanticQueryResult(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    model_version: str
    result_grain: list[str]
    query_scope: QueryScopeName
    quality_status: Literal["complete", "partial", "unavailable"]
    evidence: QueryEvidence
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class CompiledSemanticQuery:
    sql: str
    params: dict[str, Any]
    positiontup: tuple[str, ...]
    plan: LogicalQueryPlan


class SemanticQueryPlanner:
    """只消费已发布查询模型并生成确定性 SQL Server 查询。"""

    def __init__(self, registry: SemanticRegistry):
        self._registry = registry

    def plan(self, query: SemanticQuery) -> LogicalQueryPlan:
        version = self._published_version(query.object_code)
        if query.scope.query_scope in {"whole_settlement", "fee_item"}:
            return self._plan_flat_query(query, version)
        datasets = {item.dataset_code: item for item in version.datasets}
        if len({item.datasource_id for item in datasets.values()}) != 1:
            raise SemanticQueryPlanningError("查询模型只能使用一个数据源")
        fields = {item.field_code: item for item in version.fields}
        keys = {item.key_code: item for item in version.keys}
        relations = version.relations
        requested_metrics = self._resolve_metrics(query, version)
        metrics = self._base_metrics(requested_metrics, version, query.object_code)

        anchor_field = fields.get(query.scope.anchor.field_code)
        if anchor_field is None or anchor_field.field_role != "identifier":
            raise SemanticQueryPlanningError("锚点字段未在已发布模型登记为 identifier")
        anchor_dataset = datasets.get(anchor_field.dataset_code)
        if anchor_dataset is None:
            raise SemanticQueryPlanningError("锚点数据集不存在")
        if not any(
            key.dataset_code == anchor_dataset.dataset_code
            and key.entity_code == query.scope.entity_code
            and anchor_field.column_name in key.columns
            for key in keys.values()
        ):
            raise SemanticQueryPlanningError("锚点字段不能定位目标实体")

        target_datasets: set[str] = set()
        for metric in metrics:
            field = fields.get(metric.fact_field_code or "")
            if field is None:
                raise SemanticQueryPlanningError(f"指标 '{metric.metric_code}' 缺少已发布事实字段")
            target_datasets.add(field.dataset_code)

        for target in target_datasets:
            self._resolve_unique_path(
                anchor_dataset.dataset_code,
                target,
                relations,
                version.snapshot.get("preferred_relation_paths", []),
            )

        coverage_rule = next(
            (rule for rule in version.quality_rules if rule.rule_type == "coverage"),
            None,
        )
        if coverage_rule is None:
            raise SemanticQueryPlanningError("已发布模型缺少 coverage reference")
        coverage_dataset = coverage_rule.parameters.get("reference_dataset")
        if coverage_dataset not in datasets:
            raise SemanticQueryPlanningError("coverage reference 数据集不存在")
        coverage_relation = next(
            (item for item in relations if item.relation_code == coverage_rule.target_dataset_or_relation),
            None,
        )
        if coverage_relation is None:
            raise SemanticQueryPlanningError("coverage relation 不存在")

        coverage_key_code = (
            coverage_relation.from_key
            if coverage_relation.from_dataset == coverage_dataset
            else coverage_relation.to_key
        )
        coverage_key = keys[coverage_key_code]
        group_codes = list(query.group_by)
        if query.scope.query_scope == "segment":
            for column_name in coverage_key.columns[1:]:
                field = next(
                    (
                        item for item in fields.values()
                        if item.dataset_code == coverage_dataset and item.column_name == column_name
                    ),
                    None,
                )
                if field is None:
                    raise SemanticQueryPlanningError("分段范围缺少可公开的分段键字段")
                if field.field_code not in group_codes:
                    group_codes.append(field.field_code)
        group_fields = []
        for code in group_codes:
            field = fields.get(code)
            if field is None or field.field_role == "fact":
                raise SemanticQueryPlanningError(f"分组字段 '{code}' 未登记为维度或标识")
            if field.dataset_code != coverage_dataset:
                raise SemanticQueryPlanningError("当前分组只允许 coverage reference 字段")
            group_fields.append(field)
        for metric in [*requested_metrics, *metrics]:
            if metric.non_additive_dimensions and not set(metric.non_additive_dimensions) <= set(group_codes):
                raise SemanticQueryPlanningError(
                    f"指标 '{metric.metric_code}' 跨不可加维度聚合"
                )
        if {
            self._short_code(field.field_code) for field in group_fields
        } & {
            self._short_code(metric.metric_code) for metric in requested_metrics
        }:
            raise SemanticQueryPlanningError("分组字段与指标输出编码冲突")
        for item in query.filters:
            field = fields.get(item.field_code)
            if field is None:
                raise SemanticQueryPlanningError(f"过滤字段 '{item.field_code}' 未登记")
            if field.dataset_code not in {anchor_dataset.dataset_code, coverage_dataset}:
                raise SemanticQueryPlanningError("普通过滤只允许锚点或 coverage reference 字段")
            self._validate_filter(item)
        allowed_order_codes = {
            *(metric.metric_code for metric in requested_metrics),
            *(self._short_code(metric.metric_code) for metric in requested_metrics),
            *(field.field_code for field in group_fields),
            *(self._short_code(field.field_code) for field in group_fields),
        }
        if any(item.field_code not in allowed_order_codes for item in query.order_by):
            raise SemanticQueryPlanningError("排序字段必须是已选指标或分组字段")

        common_grain = self._common_grain(query.scope.entity_code, coverage_relation, keys, fields)
        branches: list[PlanBranch] = []
        relation_dataset_codes = {coverage_relation.from_dataset, coverage_relation.to_dataset}
        for dataset_code in sorted(relation_dataset_codes):
            primary = next(
                (key for key in keys.values() if key.dataset_code == dataset_code and key.key_type == "primary"),
                None,
            )
            if primary is None:
                raise SemanticQueryPlanningError(f"dataset '{dataset_code}' missing primary key")
            branch_metrics = [
                self._short_code(metric.metric_code)
                for metric in metrics
                if fields[metric.fact_field_code].dataset_code == dataset_code
            ]
            branches.append(PlanBranch(
                branch_id=dataset_code,
                dataset=dataset_code,
                source_grain=self._semantic_columns(dataset_code, primary.columns, fields),
                aggregate_to=common_grain,
                metrics=branch_metrics,
            ))

        joins = [
            PlanJoin(left="segment_spine", right=branch.dataset, on=common_grain)
            for branch in branches
        ]
        used = sorted({anchor_dataset.dataset_code, *target_datasets, *relation_dataset_codes})
        plan = LogicalQueryPlan(
            model_version=version.version,
            root_object=query.object_code,
            scope=PlanScope(entity=query.scope.entity_code, anchor_field=anchor_field.field_code),
            query_scope=query.scope.query_scope,
            result_grain=(
                group_codes if query.group_by
                else ["admission_segment"] if query.scope.query_scope == "segment"
                else [query.scope.entity_code]
            ),
            common_grain=common_grain,
            branches=branches,
            joins=joins,
            quality_checks=[item.rule_code for item in version.quality_rules],
            datasets_used=used,
        )
        plan.plan_hash = hashlib.sha256(
            json.dumps(plan.model_dump(exclude={"plan_hash"}), sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]
        return plan

    @classmethod
    def _assert_read_only_select(cls, sql_text: str) -> None:
        """#36 缺口3：compile 出口 SQL 白名单终检——只允许只读 SELECT 查询。

        planner 用 SQLAlchemy Core 组装，正常只产生聚合 SELECT；此为 defence-in-depth 出口断言：
        一旦任何路径把 DML/DDL/注释/分号/临时表等带出编译结果即拦截（仅 SELECT+聚合+WHERE，无副作用语句）。
        """
        lower = sql_text.lower()
        for kw in ("insert", "update", "delete", "drop", "alter", "create",
                   "truncate", "exec", "execute", "merge", "grant", "revoke",
                   "shutdown", "bulk"):
            if re.search(rf"\b{kw}\b", lower):
                raise SemanticQueryPlanningError(f"SQL 含受限语句关键字 '{kw}'，仅允许只读 SELECT")
        if any(tok in sql_text for tok in ("/*", "--", ";")):
            raise SemanticQueryPlanningError("SQL 含注释/多条语句分号，仅允许单条只读 SELECT")
        if not re.match(r"(?is)^\s*(WITH\b|SELECT\b)", sql_text):
            raise SemanticQueryPlanningError("SQL 必须以 SELECT(或只读 WITH…SELECT)开头")

    def compile(self, query: SemanticQuery) -> CompiledSemanticQuery:
        plan = self.plan(query)
        version = self._published_version(query.object_code)
        statement = (
            self._build_flat_statement(query, version, plan)
            if query.scope.query_scope in {"whole_settlement", "fee_item"}
            else self._build_statement(query, version)
        )
        compiled = statement.compile(
            dialect=mssql.dialect(paramstyle="qmark"),
            compile_kwargs={"render_postcompile": True},
        )
        sql_text = str(compiled)
        self._assert_read_only_select(sql_text)
        params = dict(compiled.params)
        params["anchor_value"] = query.scope.anchor.value
        return CompiledSemanticQuery(
            sql=str(compiled),
            params=params,
            positiontup=tuple(compiled.positiontup or ()),
            plan=plan,
        )

    def result_from_row(
        self,
        query: SemanticQuery,
        plan: LogicalQueryPlan,
        raw_row: dict[str, Any] | None,
        duration_ms: int,
    ) -> SemanticQueryResult:
        row = raw_row or {}
        anchor_count = int(row.get("_anchor_count") or 0)
        reference_count = int(row.get("_reference_count", row.get("_segment_count")) or 0)
        matched_count = int(
            row.get("_matched_reference_count", row.get("_matched_segment_count")) or 0
        )
        extra_count = int(
            row.get("_extra_reference_count", row.get("_extra_segment_count")) or 0
        )
        duplicate_count = sum(
            int(value or 0)
            for key, value in row.items()
            if key.startswith("_") and key.endswith("_duplicate_count")
        )
        warnings: list[str] = []
        if query.scope.query_scope in {"whole_settlement", "fee_item"}:
            if anchor_count != 1:
                status: Literal["complete", "partial", "unavailable"] = "unavailable"
                warnings.append("结算标识未唯一定位到一笔有效门诊交易。")
            elif duplicate_count > 0:
                status = "unavailable"
                warnings.append("门诊交易或费用明细存在重复键，无法形成可靠金额。")
            elif query.scope.query_scope == "fee_item" and reference_count == 0:
                status = "partial"
                warnings.append("未匹配到门诊费用明细，只能核验交易汇总。")
            elif matched_count != reference_count or extra_count > 0:
                status = "partial"
                warnings.append("门诊费用明细关联不完整。")
            else:
                status = "complete"
        else:
            if anchor_count != 1:
                status = "unavailable"
                warnings.append("结算单未唯一定位到一次住院。")
            elif reference_count == 0 or duplicate_count > 0:
                status = "unavailable"
                warnings.append("结算分段缺失或存在重复键，无法形成可靠金额。")
            elif matched_count != reference_count or extra_count > 0:
                status = "partial"
                warnings.append(
                    f"发现 {reference_count} 个结算分段，目前仅匹配 {matched_count} 个；结果不代表整次住院费用。"
                )
            else:
                status = "complete"

        public_row = {key: value for key, value in row.items() if not key.startswith("_")}
        return SemanticQueryResult(
            rows=(
                [public_row]
                if status != "unavailable" and any(value is not None for value in public_row.values())
                else []
            ),
            model_version=plan.model_version,
            result_grain=plan.result_grain,
            query_scope=query.scope.query_scope,
            quality_status=status,
            evidence=QueryEvidence(
                plan_hash=plan.plan_hash,
                datasets_used=plan.datasets_used,
                anchor_count=anchor_count,
                segment_count=reference_count,
                matched_segment_count=matched_count,
                extra_segment_count=extra_count,
                reference_count=reference_count,
                matched_reference_count=matched_count,
                extra_reference_count=extra_count,
                duplicate_key_count=duplicate_count,
                stay_start_date=(
                    str(row["_stay_start_date"])
                    if row.get("_stay_start_date") is not None else None
                ),
                stay_end_date=(
                    str(row["_stay_end_date"])
                    if row.get("_stay_end_date") is not None else None
                ),
                duration_ms=duration_ms,
            ),
            warnings=warnings,
        )

    def result_from_rows(
        self,
        query: SemanticQuery,
        plan: LogicalQueryPlan,
        raw_rows: list[dict[str, Any]],
        duration_ms: int,
    ) -> SemanticQueryResult:
        result = self.result_from_row(
            query, plan, raw_rows[0] if raw_rows else None, duration_ms
        )
        if result.quality_status == "unavailable":
            return result
        result.rows = [
            {key: value for key, value in row.items() if not key.startswith("_")}
            for row in raw_rows
            if any(value is not None for key, value in row.items() if not key.startswith("_"))
        ]
        return result

    def _plan_flat_query(
        self,
        query: SemanticQuery,
        version: BusinessObjectVersion,
    ) -> LogicalQueryPlan:
        datasets = {item.dataset_code: item for item in version.datasets}
        if len({item.datasource_id for item in datasets.values()}) != 1:
            raise SemanticQueryPlanningError("查询模型只能使用一个数据源")
        fields = {item.field_code: item for item in version.fields}
        keys = {item.key_code: item for item in version.keys}
        requested_metrics = self._resolve_metrics(query, version)
        metrics = self._base_metrics(requested_metrics, version, query.object_code)
        anchor_field = fields.get(query.scope.anchor.field_code)
        if anchor_field is None or anchor_field.field_role != "identifier":
            raise SemanticQueryPlanningError("锚点字段未在已发布模型登记为 identifier")
        anchor_dataset = datasets.get(anchor_field.dataset_code)
        if anchor_dataset is None or not any(
            key.dataset_code == anchor_dataset.dataset_code
            and key.entity_code == query.scope.entity_code
            and anchor_field.column_name in key.columns
            for key in keys.values()
        ):
            raise SemanticQueryPlanningError("锚点字段不能定位目标实体")

        metric_datasets = {fields[item.fact_field_code].dataset_code for item in metrics}
        group_fields = []
        for code in query.group_by:
            field = fields.get(code)
            if field is None or field.field_role == "fact":
                raise SemanticQueryPlanningError(f"分组字段 '{code}' 未登记为维度或标识")
            group_fields.append(field)
        for metric in [*requested_metrics, *metrics]:
            if metric.non_additive_dimensions and not set(metric.non_additive_dimensions) <= set(query.group_by):
                raise SemanticQueryPlanningError(f"指标 '{metric.metric_code}' 跨不可加维度聚合")
        # #36 缺口2：permission_level=summary 的指标禁止明细行输出（须在分组聚合后再返回）
        if query.scope.query_scope != "whole_settlement" and not query.group_by:
            for metric in [*requested_metrics, *metrics]:
                if metric.permission_level == "summary":
                    raise SemanticQueryPlanningError(
                        f"指标 '{metric.metric_code}' 仅授权汇总口径，禁止明细行输出（需分组聚合）"
                    )


        if query.scope.query_scope == "whole_settlement":
            if metric_datasets != {anchor_dataset.dataset_code}:
                raise SemanticQueryPlanningError("整笔结算查询只允许交易汇总指标")
            if any(field.dataset_code != anchor_dataset.dataset_code for field in group_fields):
                raise SemanticQueryPlanningError("整笔结算分组只允许交易字段")
            target_dataset = anchor_dataset
            joins: list[PlanJoin] = []
            common_grain = [query.scope.entity_code]
        else:
            detail_codes = {
                *metric_datasets,
                *(field.dataset_code for field in group_fields),
            } - {anchor_dataset.dataset_code}
            if len(detail_codes) != 1 or anchor_dataset.dataset_code in metric_datasets:
                raise SemanticQueryPlanningError("费用明细查询必须且只能选择一个明细数据集")
            target_dataset = datasets[next(iter(detail_codes))]
            path = self._resolve_unique_path(
                anchor_dataset.dataset_code,
                target_dataset.dataset_code,
                version.relations,
                version.snapshot.get("preferred_relation_paths", []),
            )
            if len(path) != 1:
                raise SemanticQueryPlanningError("费用明细查询只允许与交易数据集直接关联")
            relation = path[0]
            relation_key = keys[
                relation.from_key
                if relation.from_dataset == target_dataset.dataset_code
                else relation.to_key
            ]
            common_grain = [relation_key.entity_code]
            joins = [PlanJoin(
                left=anchor_dataset.dataset_code,
                right=target_dataset.dataset_code,
                on=self._semantic_columns(target_dataset.dataset_code, relation_key.columns, fields),
            )]

        allowed_datasets = {anchor_dataset.dataset_code, target_dataset.dataset_code}
        for item in query.filters:
            field = fields.get(item.field_code)
            if field is None or field.dataset_code not in allowed_datasets:
                raise SemanticQueryPlanningError("过滤字段未在当前门诊查询范围登记")
            self._validate_filter(item)
        allowed_order_codes = {
            *(metric.metric_code for metric in requested_metrics),
            *(self._short_code(metric.metric_code) for metric in requested_metrics),
            *(field.field_code for field in group_fields),
            *(self._short_code(field.field_code) for field in group_fields),
        }
        if any(item.field_code not in allowed_order_codes for item in query.order_by):
            raise SemanticQueryPlanningError("排序字段必须是已选指标或分组字段")
        primary = next(
            (
                key for key in keys.values()
                if key.dataset_code == target_dataset.dataset_code and key.key_type == "primary"
            ),
            None,
        )
        if primary is None:
            raise SemanticQueryPlanningError(f"dataset '{target_dataset.dataset_code}' missing primary key")
        plan = LogicalQueryPlan(
            model_version=version.version,
            root_object=query.object_code,
            scope=PlanScope(entity=query.scope.entity_code, anchor_field=anchor_field.field_code),
            query_scope=query.scope.query_scope,
            result_grain=(
                list(query.group_by)
                if query.scope.query_scope == "whole_settlement" and query.group_by
                else [query.scope.entity_code]
                if query.scope.query_scope == "whole_settlement"
                else [primary.entity_code]
            ),
            common_grain=common_grain,
            branches=[PlanBranch(
                branch_id=target_dataset.dataset_code,
                dataset=target_dataset.dataset_code,
                source_grain=self._semantic_columns(
                    target_dataset.dataset_code, primary.columns, fields,
                ),
                aggregate_to=common_grain,
                metrics=[self._short_code(item.metric_code) for item in metrics],
            )],
            joins=joins,
            quality_checks=[item.rule_code for item in version.quality_rules],
            datasets_used=sorted(allowed_datasets),
        )
        plan.plan_hash = hashlib.sha256(
            json.dumps(plan.model_dump(exclude={"plan_hash"}), sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]
        return plan

    def _build_flat_statement(
        self,
        query: SemanticQuery,
        version: BusinessObjectVersion,
        plan: LogicalQueryPlan,
    ):
        datasets = {item.dataset_code: item for item in version.datasets}
        fields = {item.field_code: item for item in version.fields}
        keys = {item.key_code: item for item in version.keys}
        requested_metrics = self._resolve_metrics(query, version)
        metrics = self._base_metrics(requested_metrics, version, query.object_code)
        anchor_field = fields[query.scope.anchor.field_code]
        anchor_dataset = datasets[anchor_field.dataset_code]
        tables = {
            code: self._sql_table(
                dataset,
                [item for item in fields.values() if item.dataset_code == code],
                [item for item in keys.values() if item.dataset_code == code],
            )
            for code, dataset in datasets.items()
        }
        anchor_table = tables[anchor_dataset.dataset_code]
        anchor_param = bindparam("anchor_value", value=query.scope.anchor.value)
        anchor_cte = select(anchor_table).where(and_(
            anchor_table.c[anchor_field.column_name] == anchor_param,
            *self._filter_conditions(query, anchor_dataset.dataset_code, anchor_table, fields),
        )).cte("settlement_anchor")
        source = anchor_cte
        target_dataset = anchor_dataset
        if query.scope.query_scope == "fee_item":
            target_dataset = datasets[next(
                code for code in plan.datasets_used if code != anchor_dataset.dataset_code
            )]
            relation = next(
                item for item in version.relations
                if {item.from_dataset, item.to_dataset}
                == {anchor_dataset.dataset_code, target_dataset.dataset_code}
            )
            anchor_key = keys[
                relation.from_key
                if relation.from_dataset == anchor_dataset.dataset_code
                else relation.to_key
            ]
            target_key = keys[
                relation.to_key
                if relation.from_dataset == anchor_dataset.dataset_code
                else relation.from_key
            ]
            target_table = tables[target_dataset.dataset_code]
            join_condition = and_(
                *(
                    anchor_cte.c[left] == target_table.c[right]
                    for left, right in zip(anchor_key.columns, target_key.columns)
                ),
                *self._filter_conditions(query, target_dataset.dataset_code, target_table, fields),
            )
            source = anchor_cte.outerjoin(target_table, join_condition)

        group_fields = [fields[code] for code in query.group_by]
        group_columns = [
            (
                anchor_cte.c[field.column_name]
                if field.dataset_code == anchor_dataset.dataset_code
                else tables[field.dataset_code].c[field.column_name]
            ).label(self._short_code(field.field_code))
            for field in group_fields
        ]
        selected = list(group_columns)
        for metric in metrics:
            field = fields[metric.fact_field_code]
            value = (
                anchor_cte.c[field.column_name]
                if field.dataset_code == anchor_dataset.dataset_code
                else tables[field.dataset_code].c[field.column_name]
            )
            selected.append(
                self._aggregate(metric.aggregation, value).label(self._short_code(metric.metric_code))
            )

        anchor_count = select(func.count()).select_from(anchor_cte).scalar_subquery()
        reference_count = anchor_count
        duplicate_labels = []
        for dataset in {anchor_dataset.dataset_code, target_dataset.dataset_code}:
            primary = next(
                key for key in keys.values()
                if key.dataset_code == dataset and key.key_type == "primary"
            )
            dataset_source = anchor_cte if dataset == anchor_dataset.dataset_code else source
            dataset_columns = (
                [anchor_cte.c[name] for name in primary.columns]
                if dataset == anchor_dataset.dataset_code
                else [tables[dataset].c[name] for name in primary.columns]
            )
            duplicates = (
                select(*dataset_columns)
                .select_from(dataset_source)
                .group_by(*dataset_columns)
                .having(func.count() > 1)
                .subquery()
            )
            duplicate_labels.append(
                select(func.count()).select_from(duplicates).scalar_subquery().label(
                    f"_{dataset}_duplicate_count"
                )
            )
        if query.scope.query_scope == "fee_item":
            target_primary = next(
                key for key in keys.values()
                if key.dataset_code == target_dataset.dataset_code and key.key_type == "primary"
            )
            target_table = tables[target_dataset.dataset_code]
            reference_count = select(func.count(target_table.c[target_primary.columns[0]])).select_from(
                source
            ).scalar_subquery()
        evidence_columns = [
            anchor_count.label("_anchor_count"),
            reference_count.label("_reference_count"),
            reference_count.label("_matched_reference_count"),
            literal(0).label("_extra_reference_count"),
            *duplicate_labels,
        ]
        base_statement = select(*selected, *evidence_columns).select_from(source)
        if group_columns:
            base_statement = base_statement.group_by(*group_columns)
        base = base_statement.cte("semantic_base_result")
        by_code = {item.metric_code: item for item in version.metrics}
        output_columns = [base.c[self._short_code(field.field_code)] for field in group_fields]
        output_columns.extend([
            (
                self._derived_expression(metric, base, by_code, query.object_code)
                if metric.expression else base.c[self._short_code(metric.metric_code)]
            ).label(self._short_code(metric.metric_code))
            for metric in requested_metrics
        ])
        output_columns.extend(base.c[name] for name in base.c.keys() if name.startswith("_"))
        output = select(*output_columns).select_from(base).cte("semantic_output")
        statement = select(*output.c)
        for item in query.order_by:
            name = self._short_code(item.field_code)
            statement = statement.order_by(
                output.c[name].desc() if item.direction == "desc" else output.c[name].asc()
            )
        return statement.limit(query.limit)

    def _build_statement(self, query: SemanticQuery, version: BusinessObjectVersion):
        datasets = {item.dataset_code: item for item in version.datasets}
        fields = {item.field_code: item for item in version.fields}
        keys = {item.key_code: item for item in version.keys}
        requested_metrics = self._resolve_metrics(query, version)
        metrics = self._base_metrics(requested_metrics, version, query.object_code)
        anchor_field = fields[query.scope.anchor.field_code]
        anchor_dataset = datasets[anchor_field.dataset_code]
        tables = {
            code: self._sql_table(dataset, [item for item in fields.values() if item.dataset_code == code],
                                  [item for item in keys.values() if item.dataset_code == code])
            for code, dataset in datasets.items()
        }
        anchor_table = tables[anchor_dataset.dataset_code]
        anchor_param = bindparam("anchor_value", value=query.scope.anchor.value)
        anchor_cte = select(anchor_table).where(and_(
            anchor_table.c[anchor_field.column_name] == anchor_param,
            *self._filter_conditions(query, anchor_dataset.dataset_code, anchor_table, fields),
        )).cte("admission_anchor")

        coverage_rule = next(rule for rule in version.quality_rules if rule.rule_type == "coverage")
        coverage_code = coverage_rule.parameters["reference_dataset"]
        coverage_relation = next(
            item for item in version.relations
            if item.relation_code == coverage_rule.target_dataset_or_relation
        )
        coverage_key_code = (
            coverage_relation.from_key
            if coverage_relation.from_dataset == coverage_code
            else coverage_relation.to_key
        )
        coverage_key = keys[coverage_key_code]
        coverage_table = tables[coverage_code]
        coverage_end_field = next(
            (
                item for item in fields.values()
                if item.dataset_code == coverage_code
                and item.field_code.rsplit(".", 1)[-1] == "segment_end_date"
            ),
            None,
        )
        if coverage_end_field is None:
            raise SemanticQueryPlanningError("coverage reference 缺少 segment_end_date 字段")
        coverage_admission_key = self._entity_key(
            coverage_code, query.scope.entity_code, keys.values()
        )
        coverage_filter = and_(
            coverage_table.c[coverage_admission_key.columns[0]] == anchor_param,
            *self._filter_conditions(query, coverage_code, coverage_table, fields),
        )
        group_fields = [fields[code] for code in query.group_by]
        if query.scope.query_scope == "segment":
            for column_name in coverage_key.columns[1:]:
                field = next(
                    item for item in fields.values()
                    if item.dataset_code == coverage_code and item.column_name == column_name
                )
                if field not in group_fields:
                    group_fields.append(field)
        spine_columns = [
            coverage_table.c[name].label(f"grain_{index}")
            for index, name in enumerate(coverage_key.columns)
        ]
        for field in group_fields:
            if field.column_name not in coverage_key.columns:
                spine_columns.append(
                    coverage_table.c[field.column_name].label(f"group_{self._short_code(field.field_code)}")
                )
        spine = select(*spine_columns).where(coverage_filter).distinct().cte("segment_spine")

        metrics_by_dataset: dict[str, list[ObjectVersionMetric]] = {}
        for metric in metrics:
            metrics_by_dataset.setdefault(fields[metric.fact_field_code].dataset_code, []).append(metric)

        relation_dataset_codes = {coverage_relation.from_dataset, coverage_relation.to_dataset}
        branch_ctes: dict[str, Any] = {}
        for dataset_code in sorted(relation_dataset_codes):
            dataset_table = tables[dataset_code]
            relation_key_code = (
                coverage_relation.from_key
                if coverage_relation.from_dataset == dataset_code
                else coverage_relation.to_key
            )
            relation_key = keys[relation_key_code]
            admission_key = self._entity_key(dataset_code, query.scope.entity_code, keys.values())
            grain_columns = [
                dataset_table.c[name].label(f"grain_{index}")
                for index, name in enumerate(relation_key.columns)
            ]
            selected = list(grain_columns)
            for metric in metrics_by_dataset.get(dataset_code, []):
                field = fields[metric.fact_field_code]
                selected.append(
                    self._aggregate(metric.aggregation, dataset_table.c[field.column_name]).label(
                        self._short_code(metric.metric_code)
                    )
                )
            conditions = [dataset_table.c[admission_key.columns[0]] == anchor_param]
            if dataset_code == coverage_code:
                conditions.extend(self._filter_conditions(query, dataset_code, dataset_table, fields))
            branch_ctes[dataset_code] = (
                select(*selected)
                .where(and_(*conditions))
                .group_by(*(dataset_table.c[name] for name in relation_key.columns))
                .cte(dataset_code)
            )

        joined_from = spine
        for dataset_code in sorted(branch_ctes):
            branch = branch_ctes[dataset_code]
            joined_from = joined_from.outerjoin(
                branch,
                and_(*(
                    spine.c[f"grain_{index}"] == branch.c[f"grain_{index}"]
                    for index in range(len(coverage_key.columns))
                )),
            )
        joined_group_columns = []
        for field in group_fields:
            if field.column_name in coverage_key.columns:
                index = coverage_key.columns.index(field.column_name)
                source = spine.c[f"grain_{index}"]
            else:
                source = spine.c[f"group_{self._short_code(field.field_code)}"]
            joined_group_columns.append(source.label(self._short_code(field.field_code)))
        joined = select(
            *[spine.c[f"grain_{index}"] for index in range(len(coverage_key.columns))],
            *joined_group_columns,
            *[
                branch.c[name]
                for branch in branch_ctes.values()
                for name in branch.c.keys()
                if not name.startswith("grain_")
            ],
        ).select_from(joined_from).cte("joined_segments")

        result_columns = []
        for metric in metrics:
            field = fields[metric.fact_field_code]
            short = self._short_code(metric.metric_code)
            if field.dataset_code in relation_dataset_codes:
                result_columns.append(func.sum(func.coalesce(joined.c[short], 0)).label(short))
            else:
                dataset_table = tables[field.dataset_code]
                admission_key = self._entity_key(field.dataset_code, query.scope.entity_code, keys.values())
                scalar = select(self._aggregate(metric.aggregation, dataset_table.c[field.column_name])).where(and_(
                    dataset_table.c[admission_key.columns[0]] == anchor_param,
                    *self._filter_conditions(query, field.dataset_code, dataset_table, fields),
                )).scalar_subquery()
                result_columns.append(scalar.label(short))

        payment_code = (
            coverage_relation.to_dataset
            if coverage_relation.from_dataset == coverage_code
            else coverage_relation.from_dataset
        )
        payment_branch = branch_ctes[payment_code]
        match_condition = and_(*(
            spine.c[f"grain_{index}"] == payment_branch.c[f"grain_{index}"]
            for index in range(len(coverage_key.columns))
        ))
        matched_count = select(func.count()).select_from(
            spine.join(payment_branch, match_condition)
        ).scalar_subquery()
        has_coverage_filters = any(
            fields[item.field_code].dataset_code == coverage_code for item in query.filters
        )
        extra_count = (
            select(literal(0)).scalar_subquery()
            if has_coverage_filters else
            select(func.count()).select_from(
                payment_branch.outerjoin(spine, match_condition)
            ).where(spine.c.grain_0.is_(None)).scalar_subquery()
        )

        evidence_columns = [
            select(func.count()).select_from(anchor_cte).scalar_subquery().label("_anchor_count"),
            select(func.count()).select_from(spine).scalar_subquery().label("_segment_count"),
            matched_count.label("_matched_segment_count"),
            extra_count.label("_extra_segment_count"),
            select(func.min(coverage_table.c[coverage_key.columns[1]]))
            .where(coverage_filter).scalar_subquery().label("_stay_start_date"),
            select(func.max(coverage_table.c[coverage_end_field.column_name]))
            .where(coverage_filter).scalar_subquery().label("_stay_end_date"),
        ]
        for dataset_code, label in [
            (coverage_code, "_benefit_duplicate_count"),
            (payment_code, "_payment_duplicate_count"),
        ]:
            dataset_table = tables[dataset_code]
            primary = next(
                key for key in keys.values()
                if key.dataset_code == dataset_code and key.key_type == "primary"
            )
            admission_key = self._entity_key(dataset_code, query.scope.entity_code, keys.values())
            duplicates = (
                select(*[dataset_table.c[name] for name in primary.columns])
                .where(dataset_table.c[admission_key.columns[0]] == anchor_param)
                .group_by(*(dataset_table.c[name] for name in primary.columns))
                .having(func.count() > 1)
                .subquery()
            )
            evidence_columns.append(
                select(func.count()).select_from(duplicates).scalar_subquery().label(label)
            )
        base_group_columns = [joined.c[self._short_code(field.field_code)] for field in group_fields]
        base_statement = select(*base_group_columns, *result_columns, *evidence_columns).select_from(joined)
        if base_group_columns:
            base_statement = base_statement.group_by(*base_group_columns)
        base = base_statement.cte("semantic_base_result")
        by_code = {item.metric_code: item for item in version.metrics}
        output_columns = [base.c[self._short_code(field.field_code)] for field in group_fields]
        output_columns.extend([
            (
                self._derived_expression(metric, base, by_code, query.object_code)
                if metric.expression else base.c[self._short_code(metric.metric_code)]
            ).label(self._short_code(metric.metric_code))
            for metric in requested_metrics
        ])
        output_columns.extend(base.c[name] for name in base.c.keys() if name.startswith("_"))
        output = select(*output_columns).select_from(base).cte("semantic_output")
        statement = select(*output.c)
        for item in query.order_by:
            name = self._short_code(item.field_code)
            statement = statement.order_by(
                output.c[name].desc() if item.direction == "desc" else output.c[name].asc()
            )
        return statement.limit(query.limit)

    def _published_version(self, object_code: str) -> BusinessObjectVersion:
        versions = self._registry.list_object_versions(object_code)
        if not versions:
            raise SemanticQueryPlanningError(f"对象 '{object_code}' 没有已发布查询模型")
        version = versions[-1]
        if not version.datasets or not version.fields or not version.keys:
            raise SemanticQueryPlanningError(f"对象 '{object_code}' 的已发布版本不是可查询模型")
        return version

    @staticmethod
    def _resolve_metrics(query: SemanticQuery, version: BusinessObjectVersion) -> list[ObjectVersionMetric]:
        by_code = {item.metric_code: item for item in version.metrics}
        resolved = []
        for code in query.metrics:
            full_code = code if "." in code else f"{query.object_code}.{code}"
            # 指标级暂缓/草稿门禁：禁止请求口径未定的暂缓/草稿指标（如就医人次/次均费用）
            if full_code in _DEFERRED_OUTPATIENT_METRICS:
                raise SemanticQueryPlanningError(
                    f"指标 '{code}' 不可查询: {_DEFERRED_OUTPATIENT_REASON}"
                )
            metric = by_code.get(full_code)
            if metric is None or not (metric.fact_field_code or metric.expression):
                raise SemanticQueryPlanningError(f"指标 '{code}' 未在已发布查询模型中定义")
            resolved.append(metric)
        return resolved

    @classmethod
    def _base_metrics(
        cls,
        requested: list[ObjectVersionMetric],
        version: BusinessObjectVersion,
        object_code: str,
    ) -> list[ObjectVersionMetric]:
        by_code = {item.metric_code: item for item in version.metrics}
        resolved: dict[str, ObjectVersionMetric] = {}

        def visit(metric: ObjectVersionMetric, visiting: set[str]) -> None:
            if metric.metric_code in visiting:
                raise SemanticQueryPlanningError(f"指标 '{metric.metric_code}' 存在循环依赖")
            if not metric.expression:
                if not metric.fact_field_code:
                    raise SemanticQueryPlanningError(f"指标 '{metric.metric_code}' 缺少事实字段")
                resolved[metric.metric_code] = metric
                return
            cls._validate_expression(metric)
            next_visiting = {*visiting, metric.metric_code}
            for code in metric.dependencies:
                full_code = code if "." in code else f"{object_code}.{code}"
                dependency = by_code.get(full_code)
                if dependency is None:
                    raise SemanticQueryPlanningError(f"指标 '{metric.metric_code}' 依赖未登记指标 '{code}'")
                visit(dependency, next_visiting)

        for item in requested:
            visit(item, set())
        return list(resolved.values())

    @classmethod
    def _derived_expression(cls, metric, base, by_code, object_code: str):
        dependencies = {}
        for code in metric.dependencies:
            full_code = code if "." in code else f"{object_code}.{code}"
            dependency = by_code[full_code]
            dependencies[cls._short_code(code)] = (
                cls._derived_expression(dependency, base, by_code, object_code)
                if dependency.expression else base.c[cls._short_code(dependency.metric_code)]
            )
        tree = ast.parse(metric.expression or "", mode="eval")

        def render(node):
            if isinstance(node, ast.Expression):
                return render(node.body)
            if isinstance(node, ast.Name):
                return dependencies[node.id]
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, ast.UnaryOp):
                value = render(node.operand)
                return value if isinstance(node.op, ast.UAdd) else -value
            left, right = render(node.left), render(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right

        return render(tree)

    @staticmethod
    def _resolve_unique_path(
        source: str,
        target: str,
        relations: list[DatasetRelation],
        preferred: list[dict[str, Any]],
    ) -> list[DatasetRelation]:
        if source == target:
            return []
        found: list[list[DatasetRelation]] = []

        def walk(current: str, visited: set[str], path: list[DatasetRelation]) -> None:
            for relation in relations:
                if relation.from_dataset == current:
                    nxt = relation.to_dataset
                elif relation.to_dataset == current:
                    nxt = relation.from_dataset
                else:
                    continue
                if nxt in visited:
                    continue
                candidate = [*path, relation]
                if nxt == target:
                    found.append(candidate)
                else:
                    walk(nxt, {*visited, nxt}, candidate)

        walk(source, {source}, [])
        if not found:
            raise SemanticQueryPlanningError(f"数据集 '{source}' 到 '{target}' 不连通")
        if len(found) == 1:
            return found[0]
        preferred_codes = next(
            (
                item.get("relation_codes", [])
                for item in preferred
                if item.get("from_dataset") == source and item.get("to_dataset") == target
            ),
            None,
        )
        if preferred_codes:
            for path in found:
                if [item.relation_code for item in path] == preferred_codes:
                    return path
        raise SemanticQueryPlanningError(f"数据集 '{source}' 到 '{target}' 存在关系路径歧义")

    @staticmethod
    def _common_grain(
        entity_code: str,
        relation: DatasetRelation,
        keys: dict[str, DatasetKey],
        fields: dict[str, SemanticField],
    ) -> list[str]:
        key = keys[relation.from_key]
        semantic_columns = SemanticQueryPlanner._semantic_columns(key.dataset_code, key.columns, fields)
        result = [entity_code]
        for name in semantic_columns[1:]:
            if "start_date" in name and "fiscal_year" not in result:
                result.extend(["fiscal_year", "segment_start_date"])
            elif name not in result:
                result.append(name)
        return result

    @staticmethod
    def _semantic_columns(dataset_code: str, columns: list[str], fields: dict[str, SemanticField]) -> list[str]:
        by_column = {
            item.column_name: item.field_code.rsplit(".", 1)[-1]
            for item in fields.values()
            if item.dataset_code == dataset_code
        }
        return [by_column.get(name, name) for name in columns]

    @staticmethod
    def _entity_key(dataset_code: str, entity_code: str, keys) -> DatasetKey:
        candidates = [
            key for key in keys
            if key.dataset_code == dataset_code and key.entity_code == entity_code
        ]
        if not candidates:
            raise SemanticQueryPlanningError(
                f"dataset '{dataset_code}' 缺少实体 '{entity_code}' 锚点键"
            )
        return min(candidates, key=lambda item: len(item.columns))

    @staticmethod
    def _aggregate(name: str | None, value):
        allowed = {
            "sum": func.sum,
            "min": func.min,
            "max": func.max,
            "avg": func.avg,
            "count": func.count,
        }
        if name == "count_distinct":
            return func.count(value.distinct())
        aggregate = allowed.get(name or "")
        if aggregate is None:
            raise SemanticQueryPlanningError(f"不支持的聚合函数 '{name}'")
        return aggregate(value)

    @staticmethod
    def _validate_filter(item: QueryFilter) -> None:
        if item.operator in {"is_null", "is_not_null"}:
            return
        if item.operator == "in":
            if not isinstance(item.value, list) or not item.value:
                raise SemanticQueryPlanningError("in 过滤必须提供非空数组")
            return
        if item.value is None:
            raise SemanticQueryPlanningError(f"过滤操作 '{item.operator}' 必须提供值")

    @staticmethod
    def _filter_conditions(query: SemanticQuery, dataset_code: str, dataset_table, fields):
        conditions = []
        for index, item in enumerate(query.filters):
            field = fields[item.field_code]
            if field.dataset_code != dataset_code:
                continue
            value = dataset_table.c[field.column_name]
            if item.operator == "is_null":
                conditions.append(value.is_(None))
            elif item.operator == "is_not_null":
                conditions.append(value.is_not(None))
            elif item.operator == "in":
                conditions.append(value.in_(bindparam(f"filter_{index}", value=item.value, expanding=True)))
            else:
                parameter = bindparam(f"filter_{index}", value=item.value)
                conditions.append({
                    "eq": value == parameter,
                    "ne": value != parameter,
                    "gt": value > parameter,
                    "gte": value >= parameter,
                    "lt": value < parameter,
                    "lte": value <= parameter,
                }[item.operator])
        return conditions

    @staticmethod
    def _sql_table(dataset: SemanticDataset, fields: list[SemanticField], keys: list[DatasetKey]):
        names = {item.column_name for item in fields}
        names.update(name for key in keys for name in key.columns)
        return table(dataset.table_name, *(column(name) for name in sorted(names)), schema=dataset.schema_name)

    @staticmethod
    def _validate_expression(metric: ObjectVersionMetric) -> None:
        try:
            tree = ast.parse(metric.expression or "", mode="eval")
        except SyntaxError as exc:
            raise SemanticQueryPlanningError(f"指标 '{metric.metric_code}' 派生表达式无效") from exc
        allowed = (
            ast.Expression, ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
            ast.UnaryOp, ast.UAdd, ast.USub, ast.Constant, ast.Name, ast.Load,
        )
        if any(not isinstance(node, allowed) for node in ast.walk(tree)):
            raise SemanticQueryPlanningError(f"指标 '{metric.metric_code}' 派生表达式包含未登记函数或 SQL")
        if any(
            isinstance(node, ast.Constant) and not isinstance(node.value, (int, float))
            for node in ast.walk(tree)
        ):
            raise SemanticQueryPlanningError(f"指标 '{metric.metric_code}' 派生表达式只允许数值常量")
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        allowed_names = {item.rsplit(".", 1)[-1] for item in metric.dependencies}
        if names - allowed_names:
            raise SemanticQueryPlanningError(f"指标 '{metric.metric_code}' 派生表达式引用未登记指标")

    @staticmethod
    def _short_code(code: str) -> str:
        return code.rsplit(".", 1)[-1]


class SemanticQueryService:
    """运行已编译只读查询；连接由既有 SQL Server 防腐通道注入。"""

    def __init__(
        self,
        registry: SemanticRegistry,
        connect: Callable[[str], Any],
    ) -> None:
        self._planner = SemanticQueryPlanner(registry)
        self._connect = connect

    def execute(self, query: SemanticQuery) -> SemanticQueryResult:
        started = time.perf_counter()
        compiled = self._planner.compile(query)
        datasource_id = self._planner._published_version(query.object_code).datasets[0].datasource_id
        connection = self._connect(datasource_id)
        try:
            cursor = connection.cursor()
            values = [compiled.params[name] for name in compiled.positiontup]
            cursor.execute(compiled.sql, *values)
            rows = cursor.fetchall()
            columns = [item[0] for item in cursor.description] if cursor.description else []
            raw_rows = [dict(zip(columns, row)) for row in rows]
        finally:
            connection.close()
        return self._planner.result_from_rows(
            query,
            compiled.plan,
            raw_rows,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )

    def sample_anchor(
        self,
        object_code: str,
        entity_code: str,
        field_code: str,
    ) -> str | int | float | None:
        """从已发布 identifier 字段随机读取一个非空锚点值。"""
        version = self._planner._published_version(object_code)
        field = next((item for item in version.fields if item.field_code == field_code), None)
        if field is None or field.field_role != "identifier":
            raise SemanticQueryPlanningError("锚点字段未在已发布模型登记为 identifier")
        if not any(
            key.dataset_code == field.dataset_code
            and key.entity_code == entity_code
            and field.column_name in key.columns
            for key in version.keys
        ):
            raise SemanticQueryPlanningError("锚点字段不能定位目标实体")
        dataset = next(
            (item for item in version.datasets if item.dataset_code == field.dataset_code),
            None,
        )
        if dataset is None:
            raise SemanticQueryPlanningError("锚点数据集不存在")

        source = table(
            dataset.table_name,
            column(field.column_name),
            schema=dataset.schema_name,
        )
        # ponytail: 管理员验证低频取样；大表实测变慢时改为有界候选集随机。
        statement = (
            select(source.c[field.column_name])
            .where(source.c[field.column_name].is_not(None))
            .order_by(func.newid())
            .limit(1)
        )
        compiled = statement.compile(
            dialect=mssql.dialect(paramstyle="qmark"),
            compile_kwargs={"render_postcompile": True},
        )
        connection = self._connect(dataset.datasource_id)
        try:
            cursor = connection.cursor()
            values = [compiled.params[name] for name in (compiled.positiontup or ())]
            cursor.execute(str(compiled), *values)
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            connection.close()
