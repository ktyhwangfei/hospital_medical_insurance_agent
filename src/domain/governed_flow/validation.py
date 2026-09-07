"""治理数据流图与契约校验 — Phase 0 冻结版。

校验分两层：
- validate_flow_definition：图结构 + 白名单 + 契约引用（draft 保存即可跑）。
- validate_flow_for_publish：在前者基础上叠加发布门禁（口径句签核、依赖已发布）。

校验上下文（registered_datasets 等）由调用方注入；集合为空时跳过对应
外部登记检查，纯图结构规则始终执行。任何 blocking 问题存在时
has_blocking 为 True，发布必须 fail closed。
"""
from __future__ import annotations

import ast
from typing import Optional

from pydantic import BaseModel, Field, computed_field

from src.domain.governed_flow.models import (
    AggregateNode,
    ConsumerNode,
    DerivedMetricNode,
    FilterNode,
    FlowDefinition,
    FlowFilterCondition,
    FlowNode,
    FlowNodeType,
    JoinNode,
    MaterializationStrategy,
    MetricOutputBinding,
    QualityCheck,
    QualityGateNode,
    QualityCheckType,
    SourceNode,
    ValidationSeverity,
)

# ── 校验上下文（Phase 1 服务层从语义层/知识签核注入）──────────────


class FlowValidationContext(BaseModel):
    """外部登记事实；集合为空表示调用方未提供，对应检查跳过。"""

    registered_datasets: set[str] = Field(default_factory=set)
    registered_relations: set[str] = Field(default_factory=set)
    published_metrics: set[str] = Field(default_factory=set)
    value_domains: dict[str, set[str]] = Field(default_factory=dict)
    signed_calibers: set[str] = Field(default_factory=set, description="已签核口径句全文集合")


class FlowValidationIssue(BaseModel):
    code: str
    message: str
    node_id: Optional[str] = None
    severity: ValidationSeverity = ValidationSeverity.BLOCKING


class FlowValidationReport(BaseModel):
    issues: list[FlowValidationIssue] = Field(default_factory=list)

    @computed_field  # 序列化进 API 响应（路由直接返回本模型）
    @property
    def has_blocking(self) -> bool:
        return any(i.severity == ValidationSeverity.BLOCKING for i in self.issues)

    @property
    def codes(self) -> set[str]:
        return {i.code for i in self.issues}


# T_CureType 过滤必须显式走 MZ_CURE_TYPE 值域（#62 签核：两域不混用）
_CURE_TYPE_FIELD = "T_CureType"
_CURE_TYPE_DOMAIN = "MZ_CURE_TYPE"


def _issue(code: str, message: str, node_id: Optional[str] = None,
           severity: ValidationSeverity = ValidationSeverity.BLOCKING) -> FlowValidationIssue:
    return FlowValidationIssue(code=code, message=message, node_id=node_id, severity=severity)


# ── 表达式 AST 白名单（与 FormulaEvaluator 同域：算术 + 依赖变量）──

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)
_ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)


def validate_derived_expression(expression: str, dependencies: list[str]) -> Optional[str]:
    """校验派生公式语法；返回错误消息或 None。禁止任何函数调用、属性访问与未声明变量。"""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        return f"公式语法错误: {exc.msg}"

    errors: list[str] = []
    allowed_names = set(dependencies)

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Expression):
            visit(node.body)
        elif isinstance(node, ast.BinOp):
            if not isinstance(node.op, _ALLOWED_BINOPS):
                errors.append(f"不支持的二元算子: {type(node.op).__name__}")
            visit(node.left)
            visit(node.right)
        elif isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, _ALLOWED_UNARYOPS):
                errors.append(f"不支持的一元算子: {type(node.op).__name__}")
            visit(node.operand)
        elif isinstance(node, ast.Name):
            if node.id not in allowed_names:
                errors.append(f"未声明的变量: {node.id}")
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
                errors.append("常量只允许数值")
        else:
            errors.append(f"不支持的语法节点: {type(node).__name__}")

    visit(tree)
    return "; ".join(errors) if errors else None


# ── 条件级检查 ─────────────────────────────────────────────────────


def _check_condition(condition: FlowFilterCondition, context: FlowValidationContext,
                     contract_fields: set[str], issues: list[FlowValidationIssue],
                     node_id: str) -> None:
    if condition.field_code not in contract_fields:
        issues.append(_issue(
            "FLOW_FIELD_NOT_IN_CONTRACT",
            f"字段 {condition.field_code} 不在 source contract 内",
            node_id,
        ))
    # T_CureType / med_type 两域不混用：过滤 T_CureType 必须显式 MZ_CURE_TYPE
    if condition.field_code.endswith(_CURE_TYPE_FIELD) and condition.value_domain != _CURE_TYPE_DOMAIN:
        issues.append(_issue(
            "FLOW_CURE_TYPE_DOMAIN_INVALID",
            f"{condition.field_code} 过滤必须显式声明 value_domain={_CURE_TYPE_DOMAIN}；"
            "med_type 是政策知识管线医疗类别维度，不得与 MZ_CURE_TYPE 混用",
            node_id,
        ))
    # 声明值域时，in 类算子的值必须 ⊆ 值域
    if condition.value_domain and condition.value_domain in context.value_domains:
        if isinstance(condition.value, list):
            domain_values = {str(v) for v in context.value_domains[condition.value_domain]}
            bad = [v for v in condition.value if str(v) not in domain_values]
            if bad:
                issues.append(_issue(
                    "FLOW_VALUE_NOT_IN_DOMAIN",
                    f"值 {bad} 不在值域 {condition.value_domain} 内",
                    node_id,
                ))


# ── 主校验 ─────────────────────────────────────────────────────────


def validate_flow_definition(
    flow: FlowDefinition,
    context: Optional[FlowValidationContext] = None,
) -> FlowValidationReport:
    """图结构 + 节点白名单 + 契约引用校验（draft 保存即可执行）。"""
    ctx = context or FlowValidationContext()
    issues: list[FlowValidationIssue] = []

    # 1. node_id 唯一 + 类型白名单（union 解析已挡非法类型，这里防御程序化构造）
    node_by_id: dict[str, FlowNode] = {}
    for node in flow.nodes:
        if node.node_id in node_by_id:
            issues.append(_issue("FLOW_NODE_DUPLICATE", f"node_id 重复: {node.node_id}", node.node_id))
            continue
        if node.node_type not in {t.value for t in FlowNodeType}:
            issues.append(_issue("FLOW_NODE_TYPE_INVALID", f"节点类型不在白名单: {node.node_type}", node.node_id))
            continue
        node_by_id[node.node_id] = node

    # 2. 边端点存在
    for edge in flow.edges:
        if edge.from_node not in node_by_id or edge.to_node not in node_by_id:
            issues.append(_issue(
                "FLOW_EDGE_DANGLING",
                f"边 {edge.edge_id} 引用了不存在的节点",
                edge.from_node if edge.from_node not in node_by_id else edge.to_node,
            ))

    # 3. 无环（Kahn）
    indegree = {nid: 0 for nid in node_by_id}
    adj: dict[str, list[str]] = {nid: [] for nid in node_by_id}
    for edge in flow.edges:
        if edge.from_node in node_by_id and edge.to_node in node_by_id:
            adj[edge.from_node].append(edge.to_node)
            indegree[edge.to_node] += 1
    queue = [nid for nid, d in indegree.items() if d == 0]
    visited = 0
    while queue:
        current = queue.pop()
        visited += 1
        for nxt in adj[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if visited != len(node_by_id):
        issues.append(_issue("FLOW_GRAPH_CYCLE", "Flow 图存在环路，必须是 DAG"))

    # 4. source/consumer 拓扑约束
    incoming = {edge.to_node for edge in flow.edges}
    outgoing = {edge.from_node for edge in flow.edges}
    sources = [n for n in flow.nodes if isinstance(n, SourceNode)]
    consumers = [n for n in flow.nodes if isinstance(n, ConsumerNode)]
    if not sources:
        issues.append(_issue("FLOW_SOURCE_INVALID", "Flow 缺少 source 节点"))
    for node in sources:
        if node.node_id in incoming:
            issues.append(_issue("FLOW_SOURCE_INVALID", f"source 节点 {node.node_id} 不允许有入边", node.node_id))
        if ctx.registered_datasets and node.dataset_code not in ctx.registered_datasets:
            issues.append(_issue(
                "FLOW_DATASET_NOT_REGISTERED",
                f"数据集 {node.dataset_code} 未在语义层登记",
                node.node_id,
            ))
    if not consumers:
        issues.append(_issue("FLOW_CONSUMER_INVALID", "Flow 缺少 consumer 节点"))
    for node in consumers:
        if node.node_id in outgoing:
            issues.append(_issue("FLOW_CONSUMER_INVALID", f"consumer 节点 {node.node_id} 不允许有出边", node.node_id))

    # 5. 契约字段集合 + filter/dimension/aggregate 字段引用
    contract_fields: set[str] = set()
    for contract in flow.source_contracts:
        contract_fields.update(contract.fields)
        if ctx.registered_datasets and contract.dataset_code not in ctx.registered_datasets:
            issues.append(_issue(
                "FLOW_DATASET_NOT_REGISTERED",
                f"source contract 数据集 {contract.dataset_code} 未在语义层登记",
            ))
    for node in flow.nodes:
        if isinstance(node, FilterNode):
            for condition in node.conditions:
                _check_condition(condition, ctx, contract_fields, issues, node.node_id)
        elif isinstance(node, AggregateNode):
            for measure in node.measures:
                if measure.source_field != "*" and measure.source_field not in contract_fields:
                    issues.append(_issue(
                        "FLOW_FIELD_NOT_IN_CONTRACT",
                        f"度量源字段 {measure.source_field} 不在 source contract 内",
                        node.node_id,
                    ))
            for dim in node.group_by:
                if dim not in contract_fields:
                    issues.append(_issue(
                        "FLOW_FIELD_NOT_IN_CONTRACT",
                        f"分组字段 {dim} 不在 source contract 内",
                        node.node_id,
                    ))
        elif isinstance(node, DerivedMetricNode):
            for spec in node.metrics:
                error = validate_derived_expression(spec.expression, spec.dependencies)
                if error:
                    issues.append(_issue("FLOW_EXPRESSION_INVALID", f"{spec.output_code}: {error}", node.node_id))
                if ctx.published_metrics:
                    missing = [d for d in spec.dependencies if d not in ctx.published_metrics]
                    if missing:
                        issues.append(_issue(
                            "FLOW_DEPENDENCY_NOT_PUBLISHED",
                            f"派生指标 {spec.output_code} 依赖未发布: {missing}",
                            node.node_id,
                        ))

    # 6. join 关系登记
    for node in flow.nodes:
        if isinstance(node, JoinNode) and ctx.registered_relations \
                and node.relation_code not in ctx.registered_relations:
            issues.append(_issue(
                "FLOW_RELATION_NOT_REGISTERED",
                f"join 关系 {node.relation_code} 未登记（禁止笛卡尔积）",
                node.node_id,
            ))

    # 7. metric_outputs 挂载与口径句
    output_codes: set[str] = set()
    for node in flow.nodes:
        if isinstance(node, AggregateNode):
            output_codes.update(m.output_code for m in node.measures)
        elif isinstance(node, DerivedMetricNode):
            output_codes.update(m.output_code for m in node.metrics)
    for binding in flow.metric_outputs:
        target = node_by_id.get(binding.node_id)
        if not isinstance(target, (AggregateNode, DerivedMetricNode)):
            issues.append(_issue(
                "FLOW_METRIC_OUTPUT_NODE_INVALID",
                f"指标 {binding.metric_code} 的 node_id={binding.node_id} 不是 aggregate/derived_metric 节点",
                binding.node_id,
            ))
        elif binding.metric_code not in output_codes:
            issues.append(_issue(
                "FLOW_METRIC_OUTPUT_NODE_INVALID",
                f"指标 {binding.metric_code} 未在节点 {binding.node_id} 的输出中声明",
                binding.node_id,
            ))
        if not binding.policy_definition.strip():
            issues.append(_issue("FLOW_CALIBER_MISSING", f"指标 {binding.metric_code} 缺少口径句"))

    # 8. 质量门禁勾稽恒等目标存在
    for node in flow.nodes:
        if not isinstance(node, QualityGateNode):
            continue
        for check in node.checks:
            if check.check_type != QualityCheckType.IDENTITY_ASSERTION:
                continue
            targets = [check.params.get("left")] + list(check.params.get("right", []))
            missing = [t for t in targets if t and t not in output_codes]
            if missing:
                issues.append(_issue(
                    "FLOW_IDENTITY_TARGET_INVALID",
                    f"勾稽恒等引用了不存在的输出: {missing}",
                    node.node_id,
                ))

    # 9. consumer 引用的指标必须由本 flow 产出
    for node in consumers:
        missing = [m for m in node.consumes if m not in {b.metric_code for b in flow.metric_outputs}]
        if missing:
            issues.append(_issue(
                "FLOW_CONSUMES_UNKNOWN_METRIC",
                f"consumer 引用了 flow 未产出的指标: {missing}",
                node.node_id,
            ))

    # 10. 物化策略白名单（Phase 0 仅 view）
    if flow.materialization != MaterializationStrategy.VIEW:
        issues.append(_issue(
            "FLOW_MATERIALIZATION_UNSUPPORTED",
            f"物化策略 {flow.materialization} 不在 Phase 0 白名单（仅 view）",
        ))

    return FlowValidationReport(issues=issues)


def validate_flow_for_publish(
    flow: FlowDefinition,
    context: Optional[FlowValidationContext] = None,
) -> FlowValidationReport:
    """发布门禁：完整校验 + 口径句签核 fail closed。"""
    ctx = context or FlowValidationContext()
    report = validate_flow_definition(flow, ctx)
    issues = report.issues

    for binding in flow.metric_outputs:
        if ctx.signed_calibers and binding.policy_definition not in ctx.signed_calibers:
            issues.append(_issue(
                "FLOW_CALIBER_NOT_SIGNED",
                f"指标 {binding.metric_code} 的口径句未签核，禁止发布",
                binding.node_id,
            ))

    return FlowValidationReport(issues=issues)
