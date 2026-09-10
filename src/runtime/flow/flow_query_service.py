"""受控问数消费服务 — Phase 3（issue #65 消费契约接线）。

消费纪律（fail closed）：
- 只消费 published flow 的活跃发布版本（草稿/评审中/退役一律拒止）；
- 消费前重编译活跃定义并校验 artifact_hash（T8：证据被篡改即拒止）；
- 请求指标 ⊆ consumer.consumes 白名单（FLOW_CONSUMES_UNKNOWN_METRIC）；
- 请求维度 ⊆ 维度节点绑定白名单（T11 越权拒止 FLOW_CONSUME_DIMENSION_FORBIDDEN）；
- T11 消费侧强制：绑定 permission_level=detail 的维度只对 detail 级调用方开放
  （FLOW_CONSUME_DIMENSION_PERMISSION_DENIED）；角色→级别映射冻结在
  FLOW_CALLER_ROLE_LEVELS，缺省/未知角色按 summary 收紧。caller_role 是
  已解析角色串的传入 seam（生产须来自认证主体，不信任客户端自报）；
- 勾稽恒等门禁在结果行上运行时评估，失败 → 200 + unavailable + 数值扣发。

结果与既有路径一致（issue #65 验收）：与 /semantic/query/processed-snapshot
同读一个已部署视图，数值必须逐字段一致。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from src.data_platform.storage.flow.flow_ports import FlowViewReader, GovernedFlowStorage
from src.domain.governed_flow.compiler import compile_flow_view
from src.domain.governed_flow.models import (
    ConsumerNode,
    DimensionNode,
    FlowArtifactMismatchError,
    FlowDefinition,
    FlowGateResult,
    FlowNotFoundError,
    FlowPublishedRevision,
    FlowQueryCell,
    FlowQueryResult,
    FlowStatus,
    FlowStateInvalidError,
    PermissionLevel,
    QualityCheckType,
    QualityGateNode,
    SourceNode,
    caller_permission_level,
)


class FlowConsumeMetricUnknownError(ValueError):
    """请求消费的指标不在 consumer.consumes 白名单内。"""


class FlowConsumeDimensionForbiddenError(ValueError):
    """请求下钻的维度未在维度节点绑定白名单内（T11 越权拦截）。"""


class FlowConsumeDimensionPermissionDeniedError(ValueError):
    """请求下钻 detail 级维度，但调用方角色只具备 summary 级（T11 消费侧强制）。"""


class FlowConsumeAmbiguousError(FlowStateInvalidError):
    """多个已发布消费契约覆盖同一组指标，拒绝猜测（指标码驱动解析 fail closed）。"""


def _num(value: Any) -> float:
    """门禁算术：None 按 0（空数据集 SUM 为 NULL，口径上等价 0）；Decimal 归一 float。"""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _cell(value: Any) -> FlowQueryCell:
    """出参值归一：Decimal → float（JSON 可序列化），其余原样。"""
    if isinstance(value, Decimal):
        return float(value)
    return value


class FlowQueryService:
    """flow 发布版本的受控问数执行器（只读已部署视图）。"""

    def __init__(
        self,
        storage: GovernedFlowStorage,
        reader: FlowViewReader,
        dataset_resolver: Optional[Any] = None,
    ) -> None:
        self._storage = storage
        self._reader = reader
        self._dataset_resolver = dataset_resolver

    def query(
        self,
        flow_id: str,
        metrics: Optional[list[str]] = None,
        dimensions: Optional[list[str]] = None,
        caller_role: Optional[str] = None,
    ) -> FlowQueryResult:
        flow = self._storage.get_flow(flow_id)
        if flow is None:
            raise FlowNotFoundError(flow_id)
        if flow.status is not FlowStatus.PUBLISHED:
            raise FlowStateInvalidError(
                f"仅 published flow 可消费，当前 {flow.status.value}"
            )
        active = self._storage.get_active_revision(flow_id)
        if active is None:
            raise FlowStateInvalidError("flow 无活跃发布版本，不可消费")

        definition = active.definition
        artifact = self._compile_verified(definition, active)

        consumer = next(
            (n for n in definition.nodes if isinstance(n, ConsumerNode)), None
        )
        if consumer is None:  # 发布校验已强制存在，防御性兜底
            raise FlowStateInvalidError("发布定义缺少 consumer 节点")

        requested_metrics = list(metrics) if metrics else list(consumer.consumes)
        unknown = [m for m in requested_metrics if m not in consumer.consumes]
        if unknown:
            raise FlowConsumeMetricUnknownError(
                f"指标不在消费白名单内: {unknown}，允许: {consumer.consumes}"
            )

        requested_dimensions = list(dimensions or [])
        bindings = {
            d.field_code: d.permission_level
            for n in definition.nodes
            if isinstance(n, DimensionNode)
            for d in n.dimensions
        }
        forbidden = [d for d in requested_dimensions if d not in bindings]
        if forbidden:
            raise FlowConsumeDimensionForbiddenError(
                f"维度不在绑定白名单内: {forbidden}，允许: {sorted(bindings) or '（无）'}"
            )

        # T11 消费侧强制：detail 级维度只对 detail 级调用方开放，
        # 缺省/未知角色按 summary 收紧（角色→级别映射冻结在 FLOW_CALLER_ROLE_LEVELS）
        caller_level = caller_permission_level(caller_role)
        denied = [
            d for d in requested_dimensions
            if bindings[d] is PermissionLevel.DETAIL
            and caller_level is not PermissionLevel.DETAIL
        ]
        if denied:
            raise FlowConsumeDimensionPermissionDeniedError(
                f"维度为 detail 级，调用方角色 '{caller_role or '（未声明）'}'"
                f" 仅具备 summary 级，禁止下钻: {denied}"
            )

        # 勾稽门禁引用的列必须一并读取（按全口径评估），出参再投影回请求列；
        # 否则子集消费时未选指标列缺失，恒等式会被误判失败
        columns = requested_metrics + requested_dimensions
        gate_columns = self._identity_gate_columns(definition)
        read_columns = list(dict.fromkeys(columns + gate_columns))
        raw_rows = self._reader.read(artifact.view_name, read_columns)

        gate_results = self._evaluate_gates(definition, raw_rows)
        quality_passed = all(g.passed for g in gate_results)

        rows = (
            [{c: row.get(c) for c in columns} for row in raw_rows]
            if quality_passed
            else []
        )
        return FlowQueryResult(
            flow_id=flow_id,
            revision_id=active.revision_id,
            flow_revision=active.flow_revision,
            artifact_hash=active.artifact_hash,
            view_name=artifact.view_name,
            metrics=requested_metrics,
            dimensions=requested_dimensions,
            rows=[{k: _cell(v) for k, v in row.items()} for row in rows],
            quality_status="passed" if quality_passed else "unavailable",
            gate_results=gate_results,
            published_at=active.published_at,
            published_by=active.published_by,
        )

    def query_by_metrics(
        self,
        metric_codes: list[str],
        dimensions: Optional[list[str]] = None,
        caller_role: Optional[str] = None,
    ) -> FlowQueryResult:
        """指标码驱动的消费契约解析（query_planner / 问数层接入点）。

        消费方只知语义指标码（接受 `<object_code>.<短码>` 全码或契约短码），
        不感知 flow_id：在已发布 flow 的活跃版本中解析「consumer 契约
        consumes ⊇ 请求码」的唯一契约；无契约覆盖拒止、多契约拒绝猜测。
        解析成功后仍走 query() 的 T8 防篡改、白名单与勾稽门禁链路，不设旁路。
        """
        if not metric_codes:
            raise FlowConsumeMetricUnknownError("请求消费的指标码为空")
        matches: list[tuple[str, list[str]]] = []  # (flow_id, 归一化短码)
        for flow in self._storage.list_flows():
            if flow.status is not FlowStatus.PUBLISHED:
                continue
            active = self._storage.get_active_revision(flow.flow_id)
            if active is None:
                continue
            short_codes = self._normalize_metric_codes(
                active.definition, metric_codes
            )
            if any(
                isinstance(n, ConsumerNode)
                and set(short_codes).issubset(set(n.consumes))
                for n in active.definition.nodes
            ):
                matches.append((flow.flow_id, short_codes))
        if not matches:
            raise FlowConsumeMetricUnknownError(
                f"指标不在任何已发布消费契约内: {sorted(metric_codes)}"
            )
        if len(matches) > 1:
            raise FlowConsumeAmbiguousError(
                "多个已发布 flow 的消费契约覆盖请求指标，拒绝猜测: "
                f"{sorted(flow_id for flow_id, _ in matches)}"
            )
        flow_id, short_codes = matches[0]
        return self.query(
            flow_id, metrics=short_codes, dimensions=dimensions,
            caller_role=caller_role,
        )

    # ── 内部 ────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_metric_codes(
        definition: FlowDefinition, metric_codes: list[str]
    ) -> list[str]:
        """全码 `<object_code>.<短码>` → 契约短码（按该 flow 的来源对象域归一）。

        对象域不符的全码（如 `other_object.op_total_fee`）保持原样 → 无法匹配
        契约 → fail closed；裸短码原样透传。
        """
        prefixes = tuple(
            f"{node.object_code}."
            for node in definition.nodes
            if isinstance(node, SourceNode)
        )
        codes = []
        for code in metric_codes:
            if prefixes and code.startswith(prefixes):
                code = code.split(".", 1)[1]
            codes.append(code)
        return codes

    @staticmethod
    def _identity_gate_columns(definition: FlowDefinition) -> list[str]:
        """勾稽恒等引用的全部输出编码（left + right）。"""
        columns: list[str] = []
        for node in definition.nodes:
            if not isinstance(node, QualityGateNode):
                continue
            for check in node.checks:
                if check.check_type is not QualityCheckType.IDENTITY_ASSERTION:
                    continue
                params = check.params
                columns.append(str(params.get("left", "")))
                columns.extend(str(r) for r in params.get("right", []))
        return [c for c in dict.fromkeys(columns) if c]

    def _compile_verified(self, definition: FlowDefinition, revision: FlowPublishedRevision):
        """重编译活跃定义并校验产物哈希与发布证据一致（T8 防篡改）。"""
        from src.runtime.flow.flow_service import _dataset_physical_resolver

        try:
            artifact = compile_flow_view(
                definition,
                dataset_resolver=self._dataset_resolver or _dataset_physical_resolver(),
            )
        except ValueError as exc:
            raise FlowStateInvalidError(f"消费前重编译失败: {exc}") from exc
        if artifact.artifact_hash != revision.artifact_hash:
            raise FlowArtifactMismatchError(
                "FLOW_ARTIFACT_MISMATCH: "
                f"发布版本 {revision.revision_id} 的定义重编译产物与锁定 "
                "artifact_hash 不一致，拒绝消费"
            )
        return artifact

    def _evaluate_gates(
        self, definition: FlowDefinition, rows: list[dict]
    ) -> list[FlowGateResult]:
        results: list[FlowGateResult] = []
        for node in definition.nodes:
            if not isinstance(node, QualityGateNode):
                continue
            for check in node.checks:
                if check.check_type is QualityCheckType.IDENTITY_ASSERTION:
                    results.append(self._assert_identity(check.params, rows))
                else:
                    # 签核类门禁在发布时已强制；运行时透传通过事实
                    results.append(FlowGateResult(
                        check_type=str(check.check_type.value),
                        passed=True,
                        detail="发布门禁已校验（运行时无逐行断言）",
                    ))
        return results

    @staticmethod
    def _assert_identity(params: dict, rows: list[dict]) -> FlowGateResult:
        left_code = str(params.get("left", ""))
        right_codes = [str(r) for r in params.get("right", [])]
        tolerance = float(params.get("tolerance", 0.0))
        for row in rows:
            left = _num(row.get(left_code))
            right = sum(_num(row.get(c)) for c in right_codes)
            if abs(left - right) > tolerance:
                diff = round(left - right, 4)
                return FlowGateResult(
                    check_type="identity_assertion",
                    passed=False,
                    detail=(
                        f"{left_code}={left} != {'+'.join(right_codes)}={right}，"
                        f"差异 {diff} 超容差 {tolerance}"
                    ),
                )
        return FlowGateResult(
            check_type="identity_assertion",
            passed=True,
            detail=f"{left_code} = {'+'.join(right_codes)}（{len(rows)} 行全通过，容差 {tolerance}）",
        )
