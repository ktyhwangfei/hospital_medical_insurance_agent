"""治理 Flow 服务层 — Phase 1。

编排存储/校验/编译三件套，落地 Phase 0 冻结的生命周期：
draft → validating → pending_review → published → deprecated，
发布原子锁定 flow revision + semantic revision + artifact hash，
回滚只切换活跃发布版本（不可变证据不动）。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

from src.data_platform.storage.flow.flow_ports import FlowViewDeployer, GovernedFlowStorage
from src.domain.governed_flow.compiler import (
    CompiledFlowArtifact,
    compile_flow_view,
)
from src.domain.governed_flow.models import (
    FlowArtifactMismatchError,
    FlowDefinition,
    FlowNotFoundError,
    FlowPublishedRevision,
    FlowStatus,
    FlowStateInvalidError,
    compute_flow_content_hash,
    transition_flow_status,
)
from src.domain.governed_flow.validation import (
    FlowValidationContext,
    FlowValidationReport,
    validate_flow_definition,
    validate_flow_for_publish,
)

_CALIBER_MARKER = "口径句v4："


class FlowPublishBlockedError(ValueError):
    """校验阻断（含完整报告）；API 层映射 422 fail closed。"""

    def __init__(self, report: FlowValidationReport) -> None:
        blocking = [i.code for i in report.issues if i.severity.value == "blocking"]
        super().__init__(f"校验阻断: {blocking}")
        self.report = report


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_validation_context(flow: FlowDefinition) -> FlowValidationContext:
    """从语义层注册中心注入登记事实；注册中心不可用时退化为纯图结构校验。"""
    try:
        from src.semantic_layer.registry import get_semantic_registry

        store = get_semantic_registry()._store
    except Exception:
        return FlowValidationContext()

    domain_codes: set[str] = set()
    from src.domain.governed_flow.models import DimensionNode, FilterNode, JoinNode

    for node in flow.nodes:
        if isinstance(node, FilterNode):
            domain_codes.update(c.value_domain for c in node.conditions if c.value_domain)
        elif isinstance(node, DimensionNode):
            domain_codes.update(d.value_domain for d in node.dimensions if d.value_domain)
        elif isinstance(node, JoinNode):
            pass

    value_domains: dict[str, set[str]] = {}
    for code in sorted(domain_codes):
        domain = store.get_value_domain(code)
        if domain is None:
            continue  # 未登记值域：按冻结语义跳过值检查（结构声明已强制）
        values = set(domain.standard_values) or {
            m.source_value for m in store.get_value_mappings(code)
        }
        if values:
            value_domains[code] = values

    signed_calibers = set()
    for metric in store.list_metrics():
        if metric.status != "published" or not metric.definition:
            continue
        if _CALIBER_MARKER not in metric.definition:
            continue
        # 定义形态有两种：#62 加工注册的纯口径句「…口径句v4：<caliber>」与
        # 批次二治理的散文「…口径句v4：<签核说明>。<caliber>」；把尾巴整体
        # 及其句级切分都收入，发布门禁按口径句全文精确匹配仍成立。
        tail = metric.definition.split(_CALIBER_MARKER, 1)[1].strip()
        signed_calibers.add(tail)
        signed_calibers.update(piece.strip() for piece in tail.split("。") if piece.strip())

    return FlowValidationContext(
        registered_datasets={d.dataset_code for d in store.list_datasets()},
        registered_relations={r.relation_code for r in store.list_dataset_relations()},
        published_metrics={
            m.metric_code for m in store.list_metrics() if m.status == "published"
        },
        value_domains=value_domains,
        signed_calibers=signed_calibers,
    )


def _dataset_physical_resolver():
    """dataset_code → schema.table（语义层登记优先，未登记回退原码）。"""
    from src.semantic_layer.registry import get_semantic_registry

    store = get_semantic_registry()._store

    def resolve(code: str) -> str:
        dataset = store.get_dataset(code)
        if dataset is None:
            return code
        return (
            f"{dataset.schema_name}.{dataset.table_name}"
            if dataset.schema_name
            else dataset.table_name
        )

    return resolve


def compute_semantic_revision(flow: FlowDefinition) -> str:
    """发布时锁定的语义层锚点哈希：数据集/关系/指标口径/派生依赖。"""
    from src.domain.governed_flow.models import DerivedMetricNode, JoinNode

    facts = [f"dataset:{c.dataset_code}:{c.object_code}" for c in flow.source_contracts]
    for node in flow.nodes:
        if isinstance(node, JoinNode):
            facts.append(f"relation:{node.relation_code}")
        elif isinstance(node, DerivedMetricNode):
            for spec in node.metrics:
                facts.append(
                    f"derived:{spec.output_code}:{spec.expression}:{','.join(sorted(spec.dependencies))}"
                )
    facts.extend(f"metric:{b.metric_code}:{b.policy_definition}" for b in flow.metric_outputs)
    payload = "|".join(sorted(facts))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _NullViewDeployer:
    """未注入部署器时的退化实现：不部署（纯登记模式，仅测试用）。"""

    def deploy_view(self, view_sql: str) -> None:
        return None


class FlowGovernanceService:
    """治理 Flow 生命周期服务（草稿 CRUD → 校验 → 发布 → 回滚 → 退役）。

    view_deployer 未注入时退化为纯登记模式（不部署视图，仅测试用）；
    生产 wiring 由 routes 注入工厂部署器：publish/rollback 先部署 DDL
    再落/切发布证据，部署失败 fail closed。
    """

    def __init__(
        self,
        storage: GovernedFlowStorage,
        view_deployer: Optional[FlowViewDeployer] = None,
    ) -> None:
        self._storage = storage
        self._view_deployer = view_deployer or _NullViewDeployer()

    # ── 草稿 CRUD ──────────────────────────────────────────────────

    def create_flow(self, definition: FlowDefinition) -> FlowDefinition:
        draft = definition.model_copy(deep=True, update={
            "status": FlowStatus.DRAFT,
            "revision": 1,
            "content_hash": "",
            "published_at": None,
            "published_by": None,
        })
        draft.content_hash = compute_flow_content_hash(draft)
        report = validate_flow_definition(draft)
        if report.has_blocking:
            raise FlowPublishBlockedError(report)
        return self._storage.create_flow(draft)

    def get_flow(self, flow_id: str) -> FlowDefinition:
        flow = self._storage.get_flow(flow_id)
        if flow is None:
            raise FlowNotFoundError(flow_id)
        return flow

    def list_flows(self) -> list[FlowDefinition]:
        return self._storage.list_flows()

    def update_flow(
        self, flow_id: str, definition: FlowDefinition, expected_revision: int
    ) -> FlowDefinition:
        current = self.get_flow(flow_id)
        if definition.flow_id != flow_id:
            raise FlowStateInvalidError(f"flow_id 不可变更：{definition.flow_id} != {flow_id}")
        if current.status is FlowStatus.DEPRECATED:
            raise FlowStateInvalidError("deprecated 为终态，不可编辑；请新建 flow")
        # published 再编辑 = 从活跃定义开新修订（draft 起步，活跃发布版本不受影响）
        # validating/pending_review 编辑视为退回草稿（合法流转）
        updated = definition.model_copy(deep=True, update={
            "status": FlowStatus.DRAFT,
            "revision": current.revision + 1,
            "published_at": None,
            "published_by": None,
        })
        updated.content_hash = compute_flow_content_hash(updated)
        report = validate_flow_definition(updated)
        if report.has_blocking:
            raise FlowPublishBlockedError(report)
        return self._storage.update_flow(updated, expected_revision)

    def delete_flow(self, flow_id: str, expected_revision: int) -> None:
        current = self.get_flow(flow_id)
        if current.status in {FlowStatus.PUBLISHED, FlowStatus.DEPRECATED}:
            raise FlowStateInvalidError(
                f"{current.status.value} flow 存在发布证据，只能 deprecate，不能删除"
            )
        self._storage.delete_flow(flow_id, expected_revision)

    # ── 校验与评审 ──────────────────────────────────────────────────

    def validate_flow(self, flow_id: str) -> FlowValidationReport:
        """全量校验（图结构 + 语义层登记事实）；validating 为瞬态直达 draft。"""
        flow = self.get_flow(flow_id)
        if flow.status in {FlowStatus.PUBLISHED, FlowStatus.DEPRECATED}:
            raise FlowStateInvalidError(f"{flow.status.value} flow 不可再校验，请新建修订")
        report = validate_flow_definition(flow, build_validation_context(flow))
        if flow.status is not FlowStatus.DRAFT:
            # validating/pending_review 归位 draft（合法流转），revision 递增
            normalized = flow.model_copy(deep=True, update={
                "status": FlowStatus.DRAFT,
                "revision": flow.revision + 1,
            })
            self._storage.update_flow(normalized, flow.revision)
        return report

    def submit_review(self, flow_id: str) -> FlowDefinition:
        """draft →（瞬态 validating）→ pending_review；存在阻断问题则原地 fail closed。"""
        flow = self.get_flow(flow_id)
        if flow.status not in {FlowStatus.DRAFT, FlowStatus.VALIDATING}:
            raise FlowStateInvalidError(
                f"submit-review 仅允许 draft/validating，当前 {flow.status.value}"
            )
        report = validate_flow_definition(flow, build_validation_context(flow))
        if report.has_blocking:
            raise FlowPublishBlockedError(report)
        transition_flow_status(flow.status, FlowStatus.VALIDATING)
        transition_flow_status(FlowStatus.VALIDATING, FlowStatus.PENDING_REVIEW)
        submitted = flow.model_copy(deep=True, update={
            "status": FlowStatus.PENDING_REVIEW,
            "revision": flow.revision + 1,
        })
        return self._storage.update_flow(submitted, flow.revision)

    # ── 发布/回滚/退役 ─────────────────────────────────────────────

    def publish_flow(self, flow_id: str, published_by: str) -> FlowPublishedRevision:
        """pending_review → published；原子锁 flow revision + semantic revision + artifact hash。"""
        flow = self.get_flow(flow_id)
        if flow.status is not FlowStatus.PENDING_REVIEW:
            raise FlowStateInvalidError(
                f"publish 仅允许 pending_review，当前 {flow.status.value}"
            )
        context = build_validation_context(flow)
        report = validate_flow_for_publish(flow, context)
        if report.has_blocking:
            raise FlowPublishBlockedError(report)
        try:
            artifact = compile_flow_view(flow, dataset_resolver=_dataset_physical_resolver())
        except ValueError as exc:  # FlowCompileError 及标识符拒绝
            raise FlowStateInvalidError(f"编译失败: {exc}") from exc

        # 先部署 DDL 再落发布证据：部署失败 → 无新版本、状态留在
        # pending_review（fail closed，禁止"证据已发布但视图不存在"）
        self._view_deployer.deploy_view(artifact.view_sql)

        published_at = _utc_now_iso()
        revision = FlowPublishedRevision(
            revision_id=f"{flow_id}-rev{flow.revision}",
            flow_id=flow_id,
            flow_revision=flow.revision,
            content_hash=compute_flow_content_hash(flow),
            semantic_revision=compute_semantic_revision(flow),
            artifact_hash=artifact.artifact_hash,
            published_at=published_at,
            published_by=published_by,
            definition=flow.model_copy(deep=True),
        )
        self._storage.save_published_revision(revision)
        self._storage.update_flow(
            flow.model_copy(deep=True, update={
                "status": FlowStatus.PUBLISHED,
                "revision": flow.revision + 1,
                "published_at": published_at,
                "published_by": published_by,
            }),
            expected_revision=flow.revision,
        )
        return revision

    def rollback_flow(self, flow_id: str, revision_id: str) -> FlowPublishedRevision:
        """回滚只切活跃发布版本；主表同步回放目标定义，不产生新发布证据。"""
        flow = self.get_flow(flow_id)
        if flow.status is not FlowStatus.PUBLISHED:
            raise FlowStateInvalidError(f"rollback 仅允许 published，当前 {flow.status.value}")
        target = self._storage.get_published_revision(revision_id)
        if target is None or target.flow_id != flow_id:
            raise FlowNotFoundError(f"发布版本 {revision_id} 不属于 flow {flow_id}")

        # T8 防篡改：重编译目标定义必须复现锁定时的 artifact_hash，
        # 不一致说明证据被改过，拒绝回滚（不部署、不切活跃指针）
        try:
            artifact = compile_flow_view(
                target.definition, dataset_resolver=_dataset_physical_resolver()
            )
        except ValueError as exc:
            raise FlowStateInvalidError(f"回滚重编译失败: {exc}") from exc
        if artifact.artifact_hash != target.artifact_hash:
            raise FlowArtifactMismatchError(
                "FLOW_ARTIFACT_MISMATCH: "
                f"发布版本 {revision_id} 的定义重编译产物与锁定 artifact_hash 不一致，拒绝回滚"
            )
        self._view_deployer.deploy_view(artifact.view_sql)

        self._storage.set_active_revision(flow_id, revision_id)
        restored = target.definition.model_copy(deep=True, update={
            "status": FlowStatus.PUBLISHED,
            "revision": flow.revision + 1,
            "published_at": target.published_at,
            "published_by": target.published_by,
        })
        restored.content_hash = compute_flow_content_hash(restored)
        self._storage.update_flow(restored, flow.revision)
        return target

    def deprecate_flow(self, flow_id: str) -> FlowDefinition:
        flow = self.get_flow(flow_id)
        transition_flow_status(flow.status, FlowStatus.DEPRECATED)
        deprecated = flow.model_copy(deep=True, update={
            "status": FlowStatus.DEPRECATED,
            "revision": flow.revision + 1,
        })
        return self._storage.update_flow(deprecated, flow.revision)

    # ── 版本证据与预览 ─────────────────────────────────────────────

    def list_revisions(self, flow_id: str) -> list[FlowPublishedRevision]:
        self.get_flow(flow_id)
        return self._storage.list_published_revisions(flow_id)

    def get_active_revision(self, flow_id: str) -> FlowPublishedRevision | None:
        self.get_flow(flow_id)
        return self._storage.get_active_revision(flow_id)

    def preview_flow(self, flow_id: str) -> CompiledFlowArtifact:
        """编译产物预览（不落库不发布）；draft 及之后任意状态可预览。"""
        flow = self.get_flow(flow_id)
        try:
            return compile_flow_view(
                flow, dataset_resolver=_dataset_physical_resolver()
            )
        except ValueError as exc:
            raise FlowStateInvalidError(f"编译失败: {exc}") from exc
