"""Flow 定义 → View DDL 编译器 — Phase 1。

将声明式 FlowDefinition 编译为受控 View DDL（与 #62
docs/processing/outpatient_processed_view.sql 同构的 SELECT/WHERE 语义），
产出 artifact_hash 供发布原子锁定。Phase 1 只编译线性管道
（source → filter* → join* → aggregate → derived_metric*），
dimension/quality_gate 不生成 SQL（分别注入 GROUP BY / 计划断言段）。

方言（2026-09-07 架构裁决）：产物为 PostgreSQL 落地库方言
（CREATE OR REPLACE VIEW）——加工一律在 PG 落地库执行，禁止在
SQL Server 源库上执行 DDL（防腐层纪律）。落地视图列名保留大小写
（AS "T_TradeNo"），裸标识符会被 PG 折叠为小写导致 column does not
exist，故所有标识符统一渲染为双引号形式（"public"."mz_trade"）。

安全边界（Phase 0 威胁模型 T5）：所有标识符过白名单正则，
字面量走参数化渲染（数字原样、字符串转义单引号），
派生表达式经 AST 白名单重新序列化，杜绝 SQL 注入面。
"""
from __future__ import annotations

import ast
import hashlib
import re
from typing import Callable, Optional

from pydantic import BaseModel, Field

from src.domain.governed_flow.models import (
    AggregateMeasure,
    AggregateNode,
    AggregateOperator,
    DerivedMetricNode,
    DerivedMetricSpec,
    DimensionNode,
    FilterNode,
    FlowDefinition,
    FlowFilterCondition,
    FlowNode,
    FlowNodeType,
    JoinNode,
    QualityGateNode,
    SourceNode,
    FilterOperator,
)

# 标识符白名单：列/表/视图名（允许 a.b 点分），其余一律拒绝（防注入）
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_VIEW_NAME_RE = re.compile(r"^[a-z0-9_]+$")

# dataset_code → 物理表名（含 schema）；默认原样返回
DatasetPhysicalResolver = Callable[[str], str]
# relation_code → JOIN ON 子句（如 "a.T_TradeNo = b.TradeNo"）
JoinClauseResolver = Callable[[str], str]

_SIGNED_CALIBER_MARKER = "口径句v4："

# mz_trade 落地契约（2026-09-07 §9 裁决 / #62 视图 28-42 行）：以下状态列
# 以 text 落地（payload 抽取）但承载数值语义，数值比较必须先
# NULLIF(col,'')::NUMERIC，否则 PG 报 operator does not exist: text = integer。
# 白名单按源数据集登记；转型必须发生在编译期（进入 artifact_hash），
# 部署期改写会破坏发布证据的防篡改锁定。
_TEXT_ENCODED_NUMERIC_FIELDS: dict[str, frozenset[str]] = {
    "mz_trade": frozenset({"T_State", "NP_Settle_State", "T_HasRefundmented", "T_CureType"}),
}


class FlowCompileError(ValueError):
    """编译失败；args[0] 为 FLOW_* 错误码。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class CompileStep(BaseModel):
    """查询计划单步；Phase 2 画布预览与 Phase 3 消费契约的对接载体。"""

    step_index: int
    node_id: str
    node_type: FlowNodeType
    description: str


class CompiledFlowArtifact(BaseModel):
    """编译产物：View DDL + 计划 + 产物哈希（发布证据三锁之一）。"""

    view_name: str
    view_sql: str
    query_plan: list[CompileStep] = Field(default_factory=list)
    artifact_hash: str = Field(min_length=64, max_length=64)


def compute_artifact_hash(view_sql: str) -> str:
    return hashlib.sha256(view_sql.encode("utf-8")).hexdigest()


def derive_view_name(flow_id: str) -> str:
    """flow_id → 合法视图名 v_flow_<slug>；非法字符折叠为下划线。"""
    slug = re.sub(r"[^a-z0-9_]", "_", flow_id.lower())
    slug = re.sub(r"_+", "_", slug).strip("_") or "flow"
    name = f"v_flow_{slug}"
    if len(name) > 60:
        name = name[:60]
    return name


def _identifier(value: str, what: str) -> str:
    """校验白名单并渲染为 PG 双引号标识符（点分段各自包裹）。

    落地视图列名保留大小写（AS "T_TradeNo"），裸引用会被 PG 折叠成
    小写而找不到列；先过白名单正则（拒绝引号/分号等注入面）再逐段
    加双引号，语义不变且可执行。
    """
    if not _IDENTIFIER_RE.match(value):
        raise FlowCompileError("FLOW_EXPRESSION_INVALID", f"{what} 标识符非法: {value!r}")
    return ".".join(f'"{segment}"' for segment in value.split("."))


def _literal(value) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise FlowCompileError("FLOW_EXPRESSION_INVALID", f"不支持的字面量类型: {type(value).__name__}")


def _numeric_cast_field(
    field_sql: str, field_code: str, values, source_dataset: Optional[str]
) -> str:
    """text 落地数值列在「全数值比较值」时渲染为 NULLIF(col,'')::NUMERIC。

    字符串值（如 IN ('')）保持 text 比较不转型；IS NULL 分支由调用方
    保留原列（col IS NULL 与 NULLIF(col,'') IS NULL 语义不同：后者含空串）。
    """
    registered = _TEXT_ENCODED_NUMERIC_FIELDS.get(source_dataset or "", frozenset())
    if field_code.rsplit(".", 1)[-1] not in registered:
        return field_sql
    candidates = values if isinstance(values, list) else [values]
    if not candidates:
        return field_sql
    if all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in candidates
    ):
        return f"NULLIF({field_sql}, '')::NUMERIC"
    return field_sql


def _render_filter(
    cond: FlowFilterCondition, source_dataset: Optional[str] = None
) -> str:
    field = _identifier(cond.field_code, "过滤字段")
    op = cond.operator
    if op is FilterOperator.IS_NULL:
        return f"{field} IS NULL"
    if op is FilterOperator.IS_NOT_NULL:
        return f"{field} IS NOT NULL"
    values = cond.value
    cast_field = _numeric_cast_field(field, cond.field_code, values, source_dataset)
    if op in {FilterOperator.IN, FilterOperator.NOT_IN, FilterOperator.IN_OR_NULL}:
        if not isinstance(values, list) or not values:
            raise FlowCompileError("FLOW_EXPRESSION_INVALID", f"{field} 的 {op.value} 需要非空列表")
        rendered = ", ".join(_literal(v) for v in values)
        if op is FilterOperator.IN:
            return f"{cast_field} IN ({rendered})"
        if op is FilterOperator.NOT_IN:
            return f"{cast_field} NOT IN ({rendered})"
        return f"({cast_field} IN ({rendered}) OR {field} IS NULL)"
    rendered = _literal(values)
    symbol = {
        FilterOperator.EQ: "=", FilterOperator.NE: "!=", FilterOperator.GT: ">",
        FilterOperator.GTE: ">=", FilterOperator.LT: "<", FilterOperator.LTE: "<=",
    }[op]
    return f"{cast_field} {symbol} {rendered}"


def _render_measure(measure: AggregateMeasure) -> str:
    field = _identifier(measure.source_field, "聚合字段")
    op = measure.operator
    if op is AggregateOperator.COUNT_DISTINCT:
        key = _identifier(measure.distinct_key or "", "去重键")
        return f"COUNT(DISTINCT {key})"
    if op is AggregateOperator.COUNT:
        return f"COUNT({field})"
    if op is AggregateOperator.SUM:
        return f"SUM({field})"
    if op is AggregateOperator.AVG:
        return f"AVG({field})"
    raise FlowCompileError("FLOW_OPERATOR_INVALID", f"聚合算子不在白名单: {op}")


def _render_derived(spec: DerivedMetricSpec) -> str:
    """派生表达式经 AST 白名单重新序列化（输入即使已过校验也不信任原文）。"""
    try:
        tree = ast.parse(spec.expression, mode="eval")
    except SyntaxError as exc:
        raise FlowCompileError("FLOW_EXPRESSION_INVALID", f"派生公式语法错误: {spec.expression!r}") from exc

    def walk(node: ast.AST) -> str:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
        ):
            symbol = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}[type(node.op)]
            return f"({walk(node.left)} {symbol} {walk(node.right)})"
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            symbol = "+" if isinstance(node.op, ast.UAdd) else "-"
            return f"({symbol}{walk(node.operand)})"
        if isinstance(node, ast.Name):
            return _identifier(node.id, "派生公式变量")
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            return str(node.value)
        raise FlowCompileError(
            "FLOW_EXPRESSION_INVALID",
            f"派生公式含白名单外语法: {ast.dump(node)[:80]}",
        )

    return walk(tree)


def _linear_pipeline(flow: FlowDefinition) -> list[FlowNode]:
    """提取 source→consumer 主链；Phase 1 仅支持单链线性管道。"""
    by_id = {n.node_id: n for n in flow.nodes}
    out_edges: dict[str, list[str]] = {}
    in_degree: dict[str, int] = {n.node_id: 0 for n in flow.nodes}
    for edge in flow.edges:
        out_edges.setdefault(edge.from_node, []).append(edge.to_node)
        in_degree[edge.to_node] += 1

    sources = [n for n in flow.nodes if isinstance(n, SourceNode)]
    if len(sources) != 1:
        raise FlowCompileError(
            "FLOW_COMPILE_UNSUPPORTED", f"Phase 1 编译要求单一 source 节点，实际 {len(sources)} 个"
        )
    chain: list[FlowNode] = []
    current: Optional[FlowNode] = sources[0]
    while current is not None:
        chain.append(current)
        nexts = out_edges.get(current.node_id, [])
        if len(nexts) > 1:
            raise FlowCompileError(
                "FLOW_COMPILE_UNSUPPORTED", f"节点 {current.node_id} 分叉，Phase 1 不支持分支编译"
            )
        current = by_id[nexts[0]] if nexts else None
    return chain


def compile_flow_view(
    flow: FlowDefinition,
    *,
    dataset_resolver: Optional[DatasetPhysicalResolver] = None,
    join_resolver: Optional[JoinClauseResolver] = None,
) -> CompiledFlowArtifact:
    """编译 FlowDefinition 为 PostgreSQL 落地库的 CREATE OR REPLACE VIEW 语句与查询计划。"""
    materialization = str(
        getattr(flow.materialization, "value", flow.materialization)
    )
    if materialization != "view":
        raise FlowCompileError("FLOW_MATERIALIZATION_UNSUPPORTED", "Phase 1 仅支持 view 物化")

    resolve = dataset_resolver or (lambda code: _identifier(code, "数据集"))
    chain = _linear_pipeline(flow)
    steps: list[CompileStep] = []

    from_table: Optional[str] = None
    source_dataset: Optional[str] = None
    where_parts: list[str] = []
    select_parts: list[str] = []
    group_by: list[str] = []
    quality_notes: list[str] = []

    for index, node in enumerate(chain):
        if isinstance(node, SourceNode):
            table = _identifier(
                resolve(node.dataset_code) if dataset_resolver else node.dataset_code,
                "来源表",
            )
            from_table = table
            source_dataset = node.dataset_code
            steps.append(CompileStep(
                step_index=index, node_id=node.node_id, node_type=node.node_type,
                description=f"FROM {table}（投影 {len(node.fields)} 字段）",
            ))
        elif isinstance(node, FilterNode):
            where_parts.extend(
                _render_filter(c, source_dataset) for c in node.conditions
            )
            steps.append(CompileStep(
                step_index=index, node_id=node.node_id, node_type=node.node_type,
                description=f"WHERE 追加 {len(node.conditions)} 个 AND 条件",
            ))
        elif isinstance(node, JoinNode):
            if join_resolver is None:
                raise FlowCompileError(
                    "FLOW_RELATION_NOT_REGISTERED",
                    f"join 节点 {node.node_id} 需要已登记关系解析器",
                )
            clause = join_resolver(node.relation_code)
            if from_table is None:
                raise FlowCompileError("FLOW_SOURCE_INVALID", "join 出现在 source 之前")
            from_table = f"{from_table}\n  {node.join_type.value.upper()} JOIN <{node.relation_code}> ON {clause}"
            steps.append(CompileStep(
                step_index=index, node_id=node.node_id, node_type=node.node_type,
                description=f"{node.join_type.value.upper()} JOIN 关系 {node.relation_code}",
            ))
        elif isinstance(node, DimensionNode):
            group_by.extend(_identifier(d.field_code, "维度字段") for d in node.dimensions)
            steps.append(CompileStep(
                step_index=index, node_id=node.node_id, node_type=node.node_type,
                description=f"GROUP BY 追加 {len(node.dimensions)} 个维度",
            ))
        elif isinstance(node, AggregateNode):
            group_by.extend(_identifier(g, "分组字段") for g in node.group_by)
            select_parts.extend(
                f"{_render_measure(m)} AS {_identifier(m.output_code, '输出编码')}"
                for m in node.measures
            )
            steps.append(CompileStep(
                step_index=index, node_id=node.node_id, node_type=node.node_type,
                description=f"聚合输出 {len(node.measures)} 个度量"
                + (f"，分组 {len(group_by)} 维" if group_by else "，全局单行快照"),
            ))
        elif isinstance(node, DerivedMetricNode):
            select_parts.extend(
                f"{_render_derived(m)} AS {_identifier(m.output_code, '输出编码')}"
                for m in node.metrics
            )
            steps.append(CompileStep(
                step_index=index, node_id=node.node_id, node_type=node.node_type,
                description=f"派生输出 {len(node.metrics)} 个指标",
            ))
        elif isinstance(node, QualityGateNode):
            for check in node.checks:
                if check.check_type.value == "identity_assertion":
                    right = " + ".join(str(r) for r in check.params.get("right", []))
                    quality_notes.append(
                        f"{check.params.get('left')} = {right}"
                        f"（容差 {check.params.get('tolerance', 0)}）"
                    )
            steps.append(CompileStep(
                step_index=index, node_id=node.node_id, node_type=node.node_type,
                description=f"质量门禁 {len(node.checks)} 项（运行时断言，不入 SQL）"
                + (f"：{'；'.join(quality_notes)}" if quality_notes else ""),
            ))

    if from_table is None:
        raise FlowCompileError("FLOW_SOURCE_INVALID", "管道缺少 source 节点")
    if not select_parts:
        raise FlowCompileError("FLOW_COMPILE_UNSUPPORTED", "管道没有聚合/派生输出，无可编译 SELECT")

    view_name = derive_view_name(flow.flow_id)
    sql_lines = [f"CREATE OR REPLACE VIEW {view_name} AS", "SELECT"]
    sql_lines.append("  " + ",\n  ".join(select_parts))
    sql_lines.append(f"FROM {from_table}")
    if where_parts:
        sql_lines.append("WHERE " + "\n  AND ".join(where_parts))
    if group_by:
        sql_lines.append("GROUP BY " + ", ".join(dict.fromkeys(group_by)))
    view_sql = "\n".join(sql_lines) + ";"

    return CompiledFlowArtifact(
        view_name=view_name,
        view_sql=view_sql,
        query_plan=steps,
        artifact_hash=compute_artifact_hash(view_sql),
    )


def compile_model_materialization(
    model_code: str,
    mappings: list,
) -> str:
    """数据模型物化 SQL（V3.0 Slice 2）：按已确认映射把物理列直通重命名为模型字段。

    首期仅支持直通映射（transform_rule 为空）；带转换规则的映射拒绝编译
    （fail closed，不静默忽略转换逻辑）。
    多映射表（同一模型字段映射多个物理来源）按源分 UNION ALL 合并。
    """
    confirmed = [m for m in mappings if getattr(m, "status", None) == "confirmed"
                 or str(getattr(m, "status", "")) == "confirmed"]
    if not confirmed:
        raise FlowCompileError(
            "FLOW_MATERIALIZE_NO_MAPPING",
            f"模型 {model_code} 无已确认映射，不可物化",
        )
    by_table: dict[str, list] = {}
    for mapping in confirmed:
        if mapping.transform_rule:
            raise FlowCompileError(
                "FLOW_MATERIALIZE_TRANSFORM_UNSUPPORTED",
                f"映射 {mapping.field_code}@{mapping.source_id} 带转换规则，首期仅支持直通",
            )
        by_table.setdefault(mapping.physical_table, []).append(mapping)

    def _quote(name: str) -> str:
        return '"' + name.replace('"', '""') + '"'

    # 模型编码自带分层前缀（如 dwd_mz_settlement），视图名即模型编码，不再叠加
    view_name = model_code
    selects = []
    for table, items in sorted(by_table.items()):
        parts = ",\n  ".join(
            f"{_quote(m.physical_column)} AS {_quote(m.field_code)}" for m in items
        )
        selects.append(f"SELECT\n  {parts}\nFROM {_quote(table)}")
    return f"CREATE OR REPLACE VIEW {view_name} AS\n" + "\nUNION ALL\n".join(selects) + ";"
