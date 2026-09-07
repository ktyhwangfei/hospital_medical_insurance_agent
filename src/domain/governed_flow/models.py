"""治理数据流（Governed Data Flow）DSL 契约 — Phase 0 冻结版。

依据：docs/research/治理中心全流程可视化配置-开源调研与落地方案-V1.0.md §4.2/§4.3，
GitHub issue #65 Phase 0（契约冻结）。

核心约束（安全边界，Phase 0 冻结）：
- 画布只编辑本声明式定义；不允许任意 SQL/Python、连接串、脚本与循环节点。
- 节点与聚合算子均为白名单；字段必须来自 source contract。
- T_CureType 过滤必须显式声明 MZ_CURE_TYPE 值域；med_type 是政策知识管线
  医疗类别维度，与 MZ_CURE_TYPE 两域不混用（#62 签核结论）。
- 发布原子锁定 flow revision、semantic revision 与产物 hash（Phase 1 落地存储）。
"""
from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

# ── 白名单枚举（Phase 0 冻结，扩充需过评审）──────────────────────────


class FlowNodeType(StrEnum):
    """Flow 节点类型白名单（方案 §4.2 八类）。"""

    SOURCE = "source"
    FILTER = "filter"
    JOIN = "join"
    AGGREGATE = "aggregate"
    DERIVED_METRIC = "derived_metric"
    DIMENSION = "dimension"
    QUALITY_GATE = "quality_gate"
    CONSUMER = "consumer"


class FlowStatus(StrEnum):
    """Flow 状态机：draft → validating → pending_review → published → deprecated。"""

    DRAFT = "draft"
    VALIDATING = "validating"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"


class AggregateOperator(StrEnum):
    """聚合算子白名单（方案 §4.2 #4；首批 Golden Flow 使用 count_distinct/sum）。"""

    COUNT = "count"
    COUNT_DISTINCT = "count_distinct"
    SUM = "sum"
    AVG = "avg"


class FilterOperator(StrEnum):
    """过滤算子；in_or_null 精确表达口径句 v4 的 `IN (...) OR IS NULL` 分支。"""

    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    IN_OR_NULL = "in_or_null"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


class NullPolicy(StrEnum):
    """度量空值策略（显式声明，禁止隐式）。"""

    IGNORE = "ignore"  # SQL 聚合默认语义（SUM/COUNT 忽略 NULL）
    FAIL = "fail"  # 出现 NULL 即质量门禁失败
    ZERO = "zero"  # 视为 0 参与聚合


class ReversalPolicy(StrEnum):
    """负数/冲正策略。首批 Golden Flow 通过口径句过滤排除冲正行（excluded_by_filter）。"""

    EXCLUDED_BY_FILTER = "excluded_by_filter"
    NET = "net"  # 负数净额参与累加


class JoinType(StrEnum):
    INNER = "inner"
    LEFT = "left"


class ConsumerKind(StrEnum):
    """消费方类型；只读引用已发布指标（方案 §4.2 #8）。"""

    QUERY_PLANNER = "query_planner"
    SKILL = "skill"
    DASHBOARD_CARD = "dashboard_card"
    WEEKLY_REPORT = "weekly_report"
    ASSISTANT = "assistant"


class QualityCheckType(StrEnum):
    """质量门禁检查类型白名单。"""

    CALIBER_SIGNOFF = "caliber_signoff"  # 口径句已签核
    IDENTITY_ASSERTION = "identity_assertion"  # 勾稽恒等（如 总费用=基金+个人）
    ROW_COUNT = "row_count"
    NULL_RATE = "null_rate"
    FRESHNESS = "freshness"
    PERMISSION = "permission"  # 消费方权限级别检查


class PermissionLevel(StrEnum):
    """维度权限级别（下钻边界，方案 §4.2 #6）。"""

    SUMMARY = "summary"
    DETAIL = "detail"


class MaterializationStrategy(StrEnum):
    """物化策略；Phase 0/1 仅 view（方案 §7，性能实测后再议物化表）。"""

    VIEW = "view"


class ValidationSeverity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"


# ── 状态机与异常 ────────────────────────────────────────────────────

FLOW_STATUS_TRANSITIONS: dict[FlowStatus, frozenset[FlowStatus]] = {
    # 已发布 flow 再编辑 = 新 revision 从 draft 开始，active revision 不受影响
    FlowStatus.DRAFT: frozenset({FlowStatus.VALIDATING}),
    FlowStatus.VALIDATING: frozenset({FlowStatus.DRAFT, FlowStatus.PENDING_REVIEW}),
    FlowStatus.PENDING_REVIEW: frozenset({FlowStatus.DRAFT, FlowStatus.PUBLISHED}),
    FlowStatus.PUBLISHED: frozenset({FlowStatus.DEPRECATED}),
    FlowStatus.DEPRECATED: frozenset(),  # 终态；不删除历史证据
}


class FlowStateInvalidError(ValueError):
    """非法状态流转。"""


class FlowArtifactMismatchError(FlowStateInvalidError):
    """发布证据 artifact_hash 与定义重编译产物不一致（T8 防篡改拦截）。"""


class FlowRevisionConflictError(ValueError):
    """乐观锁冲突：expected_revision 与当前不符。"""


class FlowNotFoundError(LookupError):
    """Flow 不存在。"""


def transition_flow_status(current: FlowStatus, target: FlowStatus) -> FlowStatus:
    """校验状态流转合法性，非法抛 FlowStateInvalidError。"""
    if target not in FLOW_STATUS_TRANSITIONS[current]:
        raise FlowStateInvalidError(
            f"不允许的状态流转: {current.value} -> {target.value}"
        )
    return target


# ── 冻结错误码（API/校验统一引用；Phase 1 路由按此映射 HTTP 状态）──

FLOW_ERROR_CODES: frozenset[str] = frozenset({
    # 定义/校验类（422 域）
    "FLOW_NODE_DUPLICATE",             # node_id 重复
    "FLOW_EDGE_DANGLING",              # 边引用不存在的节点
    "FLOW_GRAPH_CYCLE",                # 图有环
    "FLOW_NODE_TYPE_INVALID",          # 节点类型不在白名单
    "FLOW_SOURCE_INVALID",             # 缺 source 或 source 带入边
    "FLOW_CONSUMER_INVALID",           # 缺 consumer 或 consumer 带出边
    "FLOW_FIELD_NOT_IN_CONTRACT",      # 字段不在 source contract 内
    "FLOW_DATASET_NOT_REGISTERED",     # 数据集未在语义层登记
    "FLOW_RELATION_NOT_REGISTERED",    # join 关系未登记
    "FLOW_OPERATOR_INVALID",           # 聚合算子不在白名单
    "FLOW_EXPRESSION_INVALID",         # 派生公式含 AST 白名单外语法
    "FLOW_DEPENDENCY_NOT_PUBLISHED",   # 派生指标依赖未发布
    "FLOW_VALUE_NOT_IN_DOMAIN",        # 过滤值不在声明值域内
    "FLOW_CURE_TYPE_DOMAIN_INVALID",   # T_CureType 未显式走 MZ_CURE_TYPE 值域（med_type 不混用）
    "FLOW_METRIC_OUTPUT_NODE_INVALID", # metric_output 挂载节点不是 aggregate/derived_metric
    "FLOW_CALIBER_MISSING",            # 指标输出口径句缺失
    "FLOW_CALIBER_NOT_SIGNED",         # 口径句未签核（发布门禁）
    "FLOW_IDENTITY_TARGET_INVALID",    # 勾稽恒等引用了不存在的输出
    "FLOW_CONSUMES_UNKNOWN_METRIC",    # consumer 引用了 flow 未产出的指标
    "FLOW_MATERIALIZATION_UNSUPPORTED",# 物化策略不在 Phase 0 白名单
    "FLOW_COMPILE_UNSUPPORTED",      # 图形态超出 Phase 1 编译能力（分叉/缺输出）
    # 生命周期/存储类（Phase 1 API：404/409）
    "FLOW_NOT_FOUND",
    "FLOW_REVISION_CONFLICT",
    "FLOW_STATE_INVALID",
    # Phase 3 消费契约接线新增（24 → 26）
    "FLOW_ARTIFACT_MISMATCH",          # 发布证据与重编译产物哈希不一致（T8 防篡改）
    "FLOW_CONSUME_DIMENSION_FORBIDDEN",# 消费维度不在维度节点绑定白名单（T11 越权拦截）
    "FLOW_CONSUME_AMBIGUOUS",          # 多个已发布消费契约覆盖同一组指标，拒绝猜测（26 → 27）
})


# ── 值对象 ─────────────────────────────────────────────────────────


class FlowNodePosition(BaseModel):
    """画布坐标（展示元数据，不参与 content_hash）。"""

    x: float = 0.0
    y: float = 0.0


class FlowFilterCondition(BaseModel):
    """过滤条件；同一 FilterNode 内条件按 AND 组合。"""

    field_code: str = Field(..., min_length=1, max_length=256)
    operator: FilterOperator
    value: Union[list[str], list[int], list[float], str, int, float, None] = None
    # 声明值域时（如 MZ_CURE_TYPE），in/not_in/in_or_null 的值必须 ⊆ 值域
    value_domain: Optional[str] = Field(None, max_length=128)

    @model_validator(mode="after")
    def _check_value_required(self) -> "FlowFilterCondition":
        needs_value = self.operator in {
            FilterOperator.EQ, FilterOperator.NE, FilterOperator.GT, FilterOperator.GTE,
            FilterOperator.LT, FilterOperator.LTE, FilterOperator.IN,
            FilterOperator.NOT_IN, FilterOperator.IN_OR_NULL,
        }
        if needs_value and self.value is None:
            raise ValueError(f"算子 {self.operator.value} 需要 value")
        if not needs_value and self.value is not None:
            raise ValueError(f"算子 {self.operator.value} 不接受 value")
        if self.operator in {FilterOperator.IN, FilterOperator.NOT_IN, FilterOperator.IN_OR_NULL} \
                and not isinstance(self.value, list):
            raise ValueError(f"算子 {self.operator.value} 的 value 必须是列表")
        return self


class PolicyCarrier(BaseModel):
    """政策载体（复用 #60 结构：doc_number/region_scope/effective_*）。"""

    doc_number: Optional[str] = Field(None, max_length=128, description="政策文号")
    region_scope: Optional[str] = Field(None, max_length=128, description="统筹区划/地域")
    effective_start: Optional[str] = Field(None, description="生效起（ISO 日期）")
    effective_end: Optional[str] = Field(None, description="生效止（ISO 日期，可空=长期）")
    policy_rule_ref: Optional[str] = Field(None, max_length=256, description="政策规则引用")


class AggregateMeasure(BaseModel):
    """聚合度量：算子 + 空值/冲正策略显式声明（方案 §4.2 #4）。"""

    output_code: str = Field(..., min_length=1, max_length=128, description="输出字段编码，如 op_total_fee")
    source_field: str = Field(..., min_length=1, max_length=256)
    operator: AggregateOperator
    distinct_key: Optional[str] = Field(
        None, max_length=256,
        description="去重键（count_distinct 必填；#62：T_TradeNo 跨险种同 trade_no 只计 1 笔）",
    )
    null_policy: NullPolicy = NullPolicy.IGNORE
    reversal_policy: ReversalPolicy = ReversalPolicy.EXCLUDED_BY_FILTER

    @model_validator(mode="after")
    def _check_distinct_key(self) -> "AggregateMeasure":
        if self.operator == AggregateOperator.COUNT_DISTINCT and not self.distinct_key:
            raise ValueError("count_distinct 算子必须显式声明 distinct_key")
        return self


class DerivedMetricSpec(BaseModel):
    """派生指标：AST 白名单算术公式，禁止 eval/任意 SQL（方案 §4.2 #5）。"""

    output_code: str = Field(..., min_length=1, max_length=128)
    expression: str = Field(..., min_length=1, max_length=1024, description="算术表达式，仅 + - * / 与依赖变量")
    dependencies: list[str] = Field(default_factory=list, description="依赖的已发布指标编码")


class DimensionBinding(BaseModel):
    """维度绑定：值域 + 权限级别，保留下钻边界（方案 §4.2 #6）。"""

    field_code: str = Field(..., min_length=1, max_length=256)
    value_domain: Optional[str] = Field(None, max_length=128)
    permission_level: PermissionLevel = PermissionLevel.SUMMARY


class QualityCheck(BaseModel):
    """质量门禁检查项。identity_assertion 参数示例（#62 勾稽恒等）：
    {"left": "op_total_fee", "right": ["op_fund_pay", "op_self_pay"], "relation": "add", "tolerance": 0.0}
    """

    check_type: QualityCheckType
    params: dict[str, Union[str, int, float, list]] = Field(default_factory=dict)
    severity: ValidationSeverity = ValidationSeverity.BLOCKING


class MetricOutputBinding(BaseModel):
    """Flow 产出指标与语义层的绑定：口径句必填，发布前必须已签核。"""

    metric_code: str = Field(..., min_length=1, max_length=256)
    name: str = Field(..., min_length=1, max_length=256)
    node_id: str = Field(..., min_length=1, max_length=128, description="产出该指标的 aggregate/derived 节点")
    policy_definition: str = Field(..., min_length=1, description="口径句（知识公式签核输入，发布门禁必填）")
    policy_carrier: Optional[PolicyCarrier] = None


class SourceContract(BaseModel):
    """来源契约：本 flow 实际引用的字段白名单；数据集必须已登记。"""

    dataset_code: str = Field(..., min_length=1, max_length=128)
    object_code: str = Field(..., min_length=1, max_length=64)
    fields: list[str] = Field(..., min_length=1)


# ── 节点（discriminated union on node_type）────────────────────────


class FlowNodeBase(BaseModel):
    node_id: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=256)
    position: Optional[FlowNodePosition] = None


class SourceNode(FlowNodeBase):
    """Source：只引用已登记数据集/语义对象，禁止连接串（方案 §4.2 #1）。"""

    node_type: Literal[FlowNodeType.SOURCE] = FlowNodeType.SOURCE
    dataset_code: str = Field(..., min_length=1, max_length=128)
    object_code: str = Field(..., min_length=1, max_length=64)
    fields: list[str] = Field(..., min_length=1, description="投影白名单；空=契约全部字段")


class FilterNode(FlowNodeBase):
    node_type: Literal[FlowNodeType.FILTER] = FlowNodeType.FILTER
    conditions: list[FlowFilterCondition] = Field(..., min_length=1)


class JoinNode(FlowNodeBase):
    """Join：仅允许已登记关系，默认禁止笛卡尔积（方案 §4.2 #3）。"""

    node_type: Literal[FlowNodeType.JOIN] = FlowNodeType.JOIN
    relation_code: str = Field(..., min_length=1, max_length=128)
    join_type: JoinType = JoinType.INNER


class AggregateNode(FlowNodeBase):
    node_type: Literal[FlowNodeType.AGGREGATE] = FlowNodeType.AGGREGATE
    group_by: list[str] = Field(default_factory=list, description="分组维度；空=全局单行快照（#62 形态）")
    measures: list[AggregateMeasure] = Field(..., min_length=1)


class DerivedMetricNode(FlowNodeBase):
    node_type: Literal[FlowNodeType.DERIVED_METRIC] = FlowNodeType.DERIVED_METRIC
    metrics: list[DerivedMetricSpec] = Field(..., min_length=1)


class DimensionNode(FlowNodeBase):
    node_type: Literal[FlowNodeType.DIMENSION] = FlowNodeType.DIMENSION
    dimensions: list[DimensionBinding] = Field(..., min_length=1)


class QualityGateNode(FlowNodeBase):
    node_type: Literal[FlowNodeType.QUALITY_GATE] = FlowNodeType.QUALITY_GATE
    checks: list[QualityCheck] = Field(..., min_length=1)


class ConsumerNode(FlowNodeBase):
    node_type: Literal[FlowNodeType.CONSUMER] = FlowNodeType.CONSUMER
    consumer_kind: ConsumerKind
    consumes: list[str] = Field(..., min_length=1, description="消费的 metric_code 列表")


FlowNode = Annotated[
    Union[
        SourceNode, FilterNode, JoinNode, AggregateNode,
        DerivedMetricNode, DimensionNode, QualityGateNode, ConsumerNode,
    ],
    Field(discriminator="node_type"),
]


class FlowEdge(BaseModel):
    edge_id: str = Field(..., min_length=1, max_length=128)
    from_node: str = Field(..., min_length=1, max_length=128)
    to_node: str = Field(..., min_length=1, max_length=128)


# ── 聚合根 ─────────────────────────────────────────────────────────

# T13 大 payload DoS 上限（Phase 0 §4 威胁缓解；金标 Flow 5 节点/4 边）
MAX_FLOW_NODES = 50
MAX_FLOW_EDGES = 100


class FlowDefinition(BaseModel):
    """Flow 声明式定义（版本化治理资产，方案 §4.3）。

    content_hash 覆盖除 revision/status/发布元数据/画布坐标外的全部内容；
    任何口径、节点、边、契约变更都会改变 hash，发布原子锁定
    flow revision + semantic revision + 产物 hash（Phase 1 落地）。
    """

    flow_id: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=256)
    owner: str = Field(..., min_length=1, max_length=128)
    status: FlowStatus = FlowStatus.DRAFT
    nodes: list[FlowNode] = Field(..., min_length=1, max_length=MAX_FLOW_NODES)
    edges: list[FlowEdge] = Field(default_factory=list, max_length=MAX_FLOW_EDGES)
    source_contracts: list[SourceContract] = Field(..., min_length=1)
    metric_outputs: list[MetricOutputBinding] = Field(..., min_length=1)
    materialization: MaterializationStrategy = MaterializationStrategy.VIEW
    revision: int = Field(default=1, ge=1, description="乐观锁修订号")
    content_hash: str = Field(default="", max_length=64)
    published_at: Optional[str] = None
    published_by: Optional[str] = None
    lineage_refs: list[str] = Field(default_factory=list, description="上游资产引用（dataset/flow revision）")
    consumer_refs: list[str] = Field(default_factory=list, description="消费方登记引用（Phase 3 接线）")


class FlowPublishedRevision(BaseModel):
    """不可变发布证据：Phase 0 契约冻结，Phase 1 落存储与回滚切换。"""

    revision_id: str = Field(..., min_length=1, max_length=64)
    flow_id: str = Field(..., min_length=1, max_length=128)
    flow_revision: int = Field(..., ge=1)
    content_hash: str = Field(..., min_length=64, max_length=64)
    semantic_revision: str = Field(..., min_length=1, description="发布时锁定的语义层版本")
    artifact_hash: str = Field(..., min_length=64, max_length=64, description="编译产物（View DDL）hash")
    published_at: str
    published_by: str
    definition: FlowDefinition


class FlowGateResult(BaseModel):
    """消费时质量门禁单项运行时评估结果。"""

    check_type: str = Field(..., description="quality_check.check_type（identity_assertion 等）")
    passed: bool
    detail: str = Field(..., description="通过/失败说明；失败必须携带差异事实")


# 消费行值域：指标数值或维度编码；Decimal 由服务层统一转 float 出参
FlowQueryCell = Union[int, float, str, None]


class FlowQueryResult(BaseModel):
    """受控问数消费结果（Phase 3）：数值 + 发布证据 + 门禁评估三件套。

    勾稽恒等失败时 quality_status=unavailable 且 rows 扣发（fail closed），
    数值不可见但证据与门禁事实完整可审计。
    """

    flow_id: str
    revision_id: str
    flow_revision: int
    artifact_hash: str = Field(..., min_length=64, max_length=64)
    view_name: str
    metrics: list[str]
    dimensions: list[str]
    rows: list[dict[str, FlowQueryCell]]
    quality_status: str = Field(..., description="passed | unavailable")
    gate_results: list[FlowGateResult] = Field(default_factory=list)
    published_at: str
    published_by: str


# ── content_hash ───────────────────────────────────────────────────

# 不参与 hash 的展示/生命周期字段
_HASH_EXCLUDED_FIELDS = {"revision", "status", "content_hash", "published_at", "published_by"}


def compute_flow_content_hash(flow: FlowDefinition) -> str:
    """规范化 JSON 的 sha256。

    排除展示/生命周期字段（revision/status/发布元数据/画布坐标）；
    nodes/edges/contracts/outputs 按自然键排序 —— 节点排列顺序与画布拖拽
    不改变内容 hash，拓扑由 edges 决定。
    """
    data = flow.model_dump(exclude=_HASH_EXCLUDED_FIELDS)
    for node in data["nodes"]:
        node.pop("position", None)
    data["nodes"].sort(key=lambda n: n["node_id"])
    data["edges"].sort(key=lambda e: e["edge_id"])
    data["source_contracts"].sort(key=lambda c: c["dataset_code"])
    data["metric_outputs"].sort(key=lambda m: m["metric_code"])
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
