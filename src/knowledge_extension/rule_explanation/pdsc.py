"""政策—数据语义协同发现（PDSC）核心模型与服务。

[来源: docs/superpowers/specs/2026-08-21-policy-data-semantic-co-discovery-design.md]

职责边界（设计 §3）：
- 机器发现线索、聚合语义簇、全政策交叉验证、评分与影响计算 —— 本模块；
- 人工一次性裁决 —— decide()/decide 动作由 API 层触发，理由要求在此强制；
- 发布激活流水线（§11.2 重提取/编译/建索引）不在本期范围。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from threading import RLock
from typing import Any, Callable, Protocol, Sequence

from pydantic import BaseModel, Field

from src.knowledge_extension.rule_explanation.semantic_alignment import (
    DiscoveryEvidence,
    DiscoverySignal,
)
from src.security.desensitization.detection import detect_sensitive_patterns
from src.semantic_layer.models import Metric
from src.semantic_layer.registry import SemanticRegistry

logger = logging.getLogger(__name__)

POLICY_OBJECT_CODE = "zcgz"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.strip().casefold()).strip("_") or "concept"


# ── 模型 ─────────────────────────────────────────────────────────


class CrossPolicyKind(StrEnum):
    """全政策交叉验证归类（设计 §5.1）。"""

    SUPPORTING = "supporting"
    EXTENDING = "extending"
    TEMPORAL_VARIANT = "temporal_variant"
    CONFLICTING = "conflicting"
    IRRELEVANT = "irrelevant"


class ClusterStatus(StrEnum):
    PENDING = "pending"                      # 待验证/待裁决
    ACCEPTED = "accepted"                    # 完整方案已批准（含业务指标）
    POLICY_ONLY_ACCEPTED = "policy_only_accepted"
    NOT_ISSUE = "not_issue"                  # 归档，相同指纹不再进簇


class DecisionAction(StrEnum):
    ACCEPT_FULL_PLAN = "accept_full_plan"    # 正常接受不要求理由
    POLICY_ONLY = "policy_only"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_ISSUE = "not_issue"                  # 驳回必须给理由


class SemanticRole(StrEnum):
    DIMENSION = "dimension"
    MEASURE = "measure"
    OTHER = "other"


class PolicyUnitEvidence(BaseModel):
    """单个政策单元的交叉验证证据（由 corpus port 返回，服务负责归类）。"""

    doc_id: str
    doc_title: str = ""
    unit_id: str = ""
    excerpt: str = ""
    found_values: list[str] = Field(default_factory=list)
    effective_period: str | None = None
    version_stage: str = "current"  # historical / current / candidate
    concept_matched: bool = False
    semantic_role: SemanticRole | None = None  # corpus 能识别角色时用于冲突检测
    kind: CrossPolicyKind | None = None
    note: str | None = None


class CrossValidationSummary(BaseModel):
    counts: dict[str, int] = Field(default_factory=dict)
    items: list[PolicyUnitEvidence] = Field(default_factory=list)
    extension_values: list[str] = Field(default_factory=list)
    blocked: bool = False  # 存在未解决冲突 → 阻止一键批准（设计 §7.5）
    error: str | None = None  # corpus 不可用时的降级说明


class DatabaseValueObservation(BaseModel):
    value: str
    definition: str | None = None
    classification: str | None = None  # value_extension / db_only / undecidable / aligned


class ValueDomainAlignment(BaseModel):
    """值域符合度（设计 §8）：四层值 + 对齐量化。"""

    trigger_values: list[str] = Field(default_factory=list)
    full_policy_values: list[str] = Field(default_factory=list)
    business_standard_values: list[str] = Field(default_factory=list)
    database_values: list[DatabaseValueObservation] = Field(default_factory=list)
    policy_coverage_rate: float | None = None
    db_definition_rate: float | None = None
    mapping_evidence_confidence: float | None = None
    alignment_score: float | None = None  # None = 不可计算（不得伪造分数）
    notes: list[str] = Field(default_factory=list)


class GovernanceValueScore(BaseModel):
    """治理价值分（设计 §7）：总分 + 三个可解释子分。"""

    credibility: float = Field(ge=0.0, le=1.0)
    landing_support: float = Field(ge=0.0, le=1.0)
    policy_impact: float = Field(ge=0.0, le=1.0)
    total: float = Field(ge=0.0, le=1.0)
    explanations: list[str] = Field(default_factory=list)


class RelationValueMappingItem(BaseModel):
    """政策条件值 ↔ 一个或多个业务标准值（设计 §10.2）。"""

    policy_value: str
    business_values: list[str]
    sources: list[str] = Field(default_factory=list)


class PolicyApplicabilityRelation(BaseModel):
    """政策适用关系：业务事实值 → 政策适用条件。

    本期唯一关系语义；值映射结构化保存，为未来图谱边保留边界（设计 §12）。
    """

    relation_id: str
    policy_metric_code: str  # 必须 zcgz.*，指向 Milvus 政策规则字段
    business_metric_code: str  # 必须属于可由 Business Facts Builder 查询的业务对象
    policy_value_domain_code: str | None = None
    business_value_domain_code: str | None = None
    value_mappings: list[RelationValueMappingItem] = Field(default_factory=list)
    source_cluster_id: str
    status: str = "draft"  # draft / published
    revision: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class SemanticDiscoveryCluster(BaseModel):
    """一卡一簇（设计 §6.2）：身份只含语义签名，证据附着其上。"""

    cluster_id: str
    normalized_concept: str
    semantic_role: SemanticRole
    semantic_type: str
    policy_value_signature: list[str] = Field(default_factory=list)
    concept: str  # 展示用原名（取最近一次信号）；干净业务名，供交叉验证取词
    diagnosis: str = ""  # 机器诊断句（仅供展示，不参与聚类/取词）
    status: ClusterStatus = ClusterStatus.PENDING
    evidence: list[DiscoveryEvidence] = Field(default_factory=list)
    evidence_fingerprints: list[str] = Field(default_factory=list)
    suggested_merge_cluster_ids: list[str] = Field(default_factory=list)
    policy_metric_code: str | None = None
    business_metric_code: str | None = None
    cross_validation: CrossValidationSummary | None = None
    value_alignment: ValueDomainAlignment | None = None
    score: GovernanceValueScore | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class PolicyFilter(BaseModel):
    policy_metric_code: str
    policy_value: str


class ActivationStatus(StrEnum):
    """激活流水线状态（设计 §11.2）：任一步失败不影响活动版本。"""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ActivationStepResult(BaseModel):
    step: str
    passed: bool
    detail: str = ""


class ClusterActivation(BaseModel):
    """语义治理决策包的原子变更集执行记录。"""

    activation_id: str
    cluster_id: str
    status: ActivationStatus = ActivationStatus.RUNNING
    steps: list[ActivationStepResult] = Field(default_factory=list)
    failed_step: str | None = None
    error: str | None = None
    activated_by: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# ── 端口 ─────────────────────────────────────────────────────────


class PolicyCorpusPort(Protocol):
    """全政策语料检索端口：覆盖全部文档/单元/版本（设计 §5.1）。"""

    def find_unit_evidence(
        self, concept: str, aliases: Sequence[str], values: Sequence[str],
    ) -> list[PolicyUnitEvidence]: ...


class NullPolicyCorpus:
    """语料不可用时的降级实现：返回空并记录说明，不阻断线索聚合。"""

    def find_unit_evidence(
        self, concept: str, aliases: Sequence[str], values: Sequence[str],
    ) -> list[PolicyUnitEvidence]:
        logger.warning("PDSC 全政策语料不可用，交叉验证降级为空 concept=%s", concept)
        return []


class PipelineStorePolicyCorpus:
    """基于 pipeline_store 提取结果的语料适配器。

    匹配规则（确定性，不调用模型）：concept/别名/政策值命中 source_text 或
    extracted_fields 的值即视为相关单元。历史/候选状态按提取 status 映射。
    ponytail: 全表分页扫描 O(n)，单元数超万级时改 SQL 全文索引。
    """

    _PAGE = 200

    def __init__(self, pipeline_store: Any) -> None:
        self._store = pipeline_store

    def find_unit_evidence(
        self, concept: str, aliases: Sequence[str], values: Sequence[str],
    ) -> list[PolicyUnitEvidence]:
        terms = [concept, *aliases]
        results: list[PolicyUnitEvidence] = []
        page = 1
        while True:
            batch = self._store.list_extractions(page=page, page_size=self._PAGE)
            items = batch.get("items", [])
            if not items:
                break
            for row in items:
                evidence = self._match_row(row, terms, list(values))
                if evidence is not None:
                    results.append(evidence)
            if page * self._PAGE >= batch.get("total", 0):
                break
            page += 1
        return results

    def _match_row(
        self, row: dict[str, Any], terms: list[str], values: list[str],
    ) -> PolicyUnitEvidence | None:
        text = row.get("source_text") or ""
        field_values: list[str] = []

        def _collect(obj: Any) -> None:
            """递归收集标量字段值（含 rules[] 内每条规则的维度值）。"""
            if not isinstance(obj, dict):
                return
            for key, val in obj.items():
                if key == "rules" and isinstance(val, list):
                    for rule in val:
                        _collect(rule)
                elif isinstance(val, (str, int, float)) and str(val).strip():
                    field_values.append(str(val))

        _collect(row.get("extracted_fields") or {})
        concept_matched = any(term and term in text for term in terms)
        found_values = [value for value in values if value in text or value in field_values]
        if not concept_matched and not found_values:
            return None
        status = row.get("status") or ""
        stage = "candidate" if "candidate" in status else (
            "historical" if "historical" in status or "superseded" in status else "current"
        )
        return PolicyUnitEvidence(
            doc_id=row.get("doc_id") or "",
            doc_title=row.get("doc_title") or "",
            unit_id=row.get("unit_id") or "",
            excerpt=text[:400],
            found_values=found_values,
            version_stage=stage,
            concept_matched=concept_matched,
        )


class PdscStore(Protocol):
    def save_cluster(self, cluster: SemanticDiscoveryCluster) -> SemanticDiscoveryCluster: ...
    def get_cluster(self, cluster_id: str) -> SemanticDiscoveryCluster | None: ...
    def list_clusters(self, statuses: list[ClusterStatus] | None = None) -> list[SemanticDiscoveryCluster]: ...
    def save_relation(self, relation: PolicyApplicabilityRelation) -> PolicyApplicabilityRelation: ...
    def get_relation(self, relation_id: str) -> PolicyApplicabilityRelation | None: ...
    def list_relations(self, business_metric_code: str | None = None) -> list[PolicyApplicabilityRelation]: ...
    def save_activation(self, activation: ClusterActivation) -> ClusterActivation: ...
    def get_activation(self, activation_id: str) -> ClusterActivation | None: ...
    def list_activations(self, cluster_id: str | None = None) -> list[ClusterActivation]: ...


@dataclass
class InMemoryPdscStore:
    clusters: dict[str, SemanticDiscoveryCluster] = field(default_factory=dict)
    relations: dict[str, PolicyApplicabilityRelation] = field(default_factory=dict)
    activations: dict[str, ClusterActivation] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock, repr=False)

    def save_cluster(self, cluster: SemanticDiscoveryCluster) -> SemanticDiscoveryCluster:
        with self._lock:
            self.clusters[cluster.cluster_id] = cluster
        return cluster

    def get_cluster(self, cluster_id: str) -> SemanticDiscoveryCluster | None:
        with self._lock:
            return self.clusters.get(cluster_id)

    def list_clusters(
        self, statuses: list[ClusterStatus] | None = None,
    ) -> list[SemanticDiscoveryCluster]:
        with self._lock:
            items = list(self.clusters.values())
        if statuses:
            items = [item for item in items if item.status in statuses]
        return items

    def save_relation(self, relation: PolicyApplicabilityRelation) -> PolicyApplicabilityRelation:
        with self._lock:
            self.relations[relation.relation_id] = relation
        return relation

    def get_relation(self, relation_id: str) -> PolicyApplicabilityRelation | None:
        with self._lock:
            return self.relations.get(relation_id)

    def list_relations(self, business_metric_code: str | None = None) -> list[PolicyApplicabilityRelation]:
        with self._lock:
            items = list(self.relations.values())
        if business_metric_code:
            items = [item for item in items if item.business_metric_code == business_metric_code]
        return items

    def save_activation(self, activation: ClusterActivation) -> ClusterActivation:
        with self._lock:
            self.activations[activation.activation_id] = activation
        return activation

    def get_activation(self, activation_id: str) -> ClusterActivation | None:
        with self._lock:
            return self.activations.get(activation_id)

    def list_activations(self, cluster_id: str | None = None) -> list[ClusterActivation]:
        with self._lock:
            items = list(self.activations.values())
        if cluster_id:
            items = [item for item in items if item.cluster_id == cluster_id]
        return items


# ── 指纹与签名 ───────────────────────────────────────────────────


def _normalize_excerpt(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "").casefold()


def evidence_fingerprint(evidence: DiscoveryEvidence) -> str:
    """证据级精确去重指纹（设计 §6.1）：同任务重跑/重复上报不产生新证据。

    不含 source_ref 与 extraction_id：同任务重跑会换运行标签/新提取行，
    稳定身份是 文档/单元/表字段 + 规范化片段；内容变化则指纹变化。
    """
    payload = json.dumps({
        "evidence_kind": evidence.evidence_kind,
        "doc_id": evidence.doc_id,
        "unit_id": evidence.unit_id,
        "table_name": evidence.table_name,
        "field_name": evidence.field_name,
        "gap_signature": evidence.gap_signature,
        "excerpt": _normalize_excerpt(evidence.excerpt),
        "rule_ids": sorted(evidence.rule_ids),
        "sample_values": sorted(evidence.sample_values),
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _normalized_concept(concept: str) -> str:
    return re.sub(r"\s+", "", concept).casefold()


def _semantic_signature(
    normalized_concept: str, role: SemanticRole, semantic_type: str, values: list[str],
) -> str:
    return "|".join([
        normalized_concept, role.value, semantic_type.casefold(),
        ",".join(sorted(set(values))),
    ])


def _default_role(signal: DiscoverySignal) -> SemanticRole:
    if signal.semantic_type == "Enum" or signal.value_domain:
        return SemanticRole.DIMENSION
    if signal.semantic_type in {"Amount", "Ratio", "Count"}:
        return SemanticRole.MEASURE
    return SemanticRole.OTHER


class ReextractionPort(Protocol):
    """受影响政策单元重提取端口（设计 §11.2 步骤 2）。"""

    def reextract_docs(self, doc_ids: list[str]) -> dict[str, Any]: ...


class CompileCheckPort(Protocol):
    """受影响单元编译门禁（§11.2 步骤 3 / §11.3）。"""

    def check_docs(self, doc_ids: list[str]) -> dict[str, Any]: ...


class SkillVerificationPort(Protocol):
    """受影响 Skill 能否从业务事实解析政策过滤条件（§11.3）。"""

    def verify(self, relation: PolicyApplicabilityRelation) -> dict[str, Any]: ...


@dataclass
class ActivationPorts:
    """激活流水线依赖集合；生产默认适配，测试可整体替换。"""

    reextractor: ReextractionPort | None = None
    compile_checker: CompileCheckPort | None = None
    skill_verifier: SkillVerificationPort | None = None


class _NoopReextractor:
    """无 LLM 配置时的默认重提取：明确失败而不是静默跳过。"""

    def reextract_docs(self, doc_ids: list[str]) -> dict[str, Any]:
        if not doc_ids:
            return {"passed": True, "detail": "无受影响文档，跳过重提取"}
        import os
        if not os.environ.get("MODEL_API_KEY"):
            return {"passed": False,
                    "detail": "重提取需要 MODEL_API_KEY（模型服务不可用），激活中止"}
        from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
            PipelineOrchestrator,
        )
        errors: list[str] = []
        done: list[str] = []
        for doc_id in doc_ids:
            try:
                PipelineOrchestrator().run_extraction(doc_id)
                done.append(doc_id)
            except Exception as exc:  # noqa: BLE001 — 单元失败需聚合上报
                errors.append(f"{doc_id}: {exc}")
        return {"passed": not errors, "detail": f"重提取 {len(done)}/{len(doc_ids)}", "errors": errors}


class _DefaultCompileChecker:
    """纯函数编译门禁：把受影响文档的当前提取行重建为事实并重新编译。"""

    def __init__(self, store: Any) -> None:
        self._store = store

    def check_docs(self, doc_ids: list[str]) -> dict[str, Any]:
        from src.knowledge_extension.rule_explanation.policy_compiler.compiler import (
            PolicyRuleCompiler,
        )
        from src.knowledge_extension.rule_explanation.policy_compiler.models import PolicyFact
        issues: list[str] = []
        total = 0
        for doc_id in doc_ids:
            page = 1
            while True:
                batch = self._store.list_extractions(doc_id=doc_id, page=page, page_size=200)
                items = batch.get("items", [])
                if not items:
                    break
                for item in items:
                    total += 1
                    facts = [
                        PolicyFact(
                            fact_id=item.get("extraction_id", ""),
                            subject="待验证单元",
                            evidence=[item.get("source_text", "") or "-"],
                            document_id=item.get("doc_id"),
                            unit_id=item.get("unit_id") or None,
                            extraction_id=item.get("extraction_id"),
                        ),
                    ]
                    result = PolicyRuleCompiler().compile(facts, run_id="pdsc_gate")
                    issues.extend(
                        f"{doc_id}: {issue.message}"
                        for issue in result.issues if issue.severity == "FAIL"
                    )
                if page * 200 >= batch.get("total", 0):
                    break
                page += 1
        return {"passed": not issues, "detail": f"编译检查 {total} 单元", "issues": issues[:10]}


class _DefaultSkillVerifier:
    """默认 Skill 验证：关系的每条值映射都能双向解析（发布后即可命中）。

    注：不能走 resolve_policy_filters —— 它只返回已发布关系，激活时关系
    还是 draft，验证会永远失败；改为直接检查值映射完整性。
    """

    def __init__(self, service: "PdscService") -> None:
        self._service = service

    def verify(self, relation: PolicyApplicabilityRelation) -> dict[str, Any]:
        del self._service  # 仅保留构造对称性；验证不依赖发布状态
        incomplete: list[str] = [
            item.policy_value
            for item in relation.value_mappings
            if not item.policy_value or not item.business_values
        ]
        return {
            "passed": bool(relation.value_mappings) and not incomplete,
            "detail": (
                f"值映射不完整: {incomplete}" if incomplete
                else f"{len(relation.value_mappings)} 条值映射可解析政策过滤条件"
                if relation.value_mappings
                else "无值映射，Skill 无法解析政策过滤条件"
            ),
        }


def _milvus_schema_fields() -> set[str]:
    """候选 Milvus 标量字段集（§11.3 门禁 1）。"""
    from src.knowledge_extension.rule_explanation.policy_retrieval import policy_rules_schema_v2
    return set(policy_rules_schema_v2.CORE_DIM_FIELDS)


# ── 服务 ─────────────────────────────────────────────────────────


class PdscService:
    """政策—数据语义协同发现服务：聚合、交叉验证、评分、裁决、适用关系、激活。"""

    def __init__(
        self, registry: SemanticRegistry, store: PdscStore, corpus: PolicyCorpusPort,
        db_value_loader: "Callable[[str, str], list[DatabaseValueObservation]] | None" = None,
        db_profile_loader: "Callable[[str, str], dict[str, Any] | None] | None" = None,
    ) -> None:
        self._registry = registry
        self._store = store
        self._corpus = corpus
        self._db_value_loader = db_value_loader
        self._db_profile_loader = db_profile_loader

    # ── 线索接入与聚类 ──

    def intake_signal(
        self,
        signal: DiscoverySignal,
        *,
        semantic_role: SemanticRole | None = None,
        policy_values: list[str] | None = None,
    ) -> SemanticDiscoveryCluster:
        """接收发现信号 → 证据去重 → 语义签名聚类（只自动合并完全一致签名）。"""
        if detect_sensitive_patterns(signal.model_dump_json()):
            raise ValueError("信号包含敏感信息，请脱敏后重试")

        fingerprint = evidence_fingerprint(signal.evidence)
        holder = self._cluster_holding_fingerprint(fingerprint)
        if holder is not None:
            if holder.status == ClusterStatus.NOT_ISSUE:
                return holder  # 归档相同指纹（设计 §9.2「不是问题」）
            # 同内容重跑：按指纹定位替换，不增加出现次数/分数（§6.1）
            merged = holder.model_copy(deep=True)
            index = merged.evidence_fingerprints.index(fingerprint)
            merged.evidence[index] = signal.evidence
            merged.concept = signal.concept
            merged.diagnosis = signal.diagnosis or merged.diagnosis
            merged.updated_at = _now()
            return self._store.save_cluster(merged)

        normalized = _normalized_concept(signal.concept)
        role = semantic_role or _default_role(signal)
        semantic_type = signal.semantic_type or "String"
        values = sorted(set(policy_values or signal.evidence.sample_values))
        signature = _semantic_signature(normalized, role, semantic_type, values)

        # 同一来源（source_ref+类型）重报但内容变化 → 替换旧观察，不新增证据
        holder = self._cluster_holding_source(signal.evidence.source_ref, signal.evidence.evidence_kind)
        if holder is not None and holder.status == ClusterStatus.PENDING:
            merged = holder.model_copy(deep=True)
            for i, item in enumerate(merged.evidence):
                if item.source_ref == signal.evidence.source_ref \
                        and item.evidence_kind == signal.evidence.evidence_kind:
                    merged.evidence[i] = signal.evidence
                    merged.evidence_fingerprints[i] = fingerprint
                    break
            merged.concept = signal.concept
            merged.diagnosis = signal.diagnosis or merged.diagnosis
            merged.cross_validation = None
            merged.score = None
            merged.updated_at = _now()
            return self._store.save_cluster(merged)

        open_clusters = self._store.list_clusters([ClusterStatus.PENDING])
        same_signature = next((c for c in open_clusters if self._signature_of(c) == signature), None)
        if same_signature is not None:
            merged = same_signature.model_copy(deep=True)
            merged.evidence.append(signal.evidence)
            merged.evidence_fingerprints.append(fingerprint)
            merged.concept = signal.concept
            merged.diagnosis = signal.diagnosis or merged.diagnosis
            merged.cross_validation = None  # 证据变化后需重新验证
            merged.score = None
            merged.updated_at = _now()
            return self._store.save_cluster(merged)

        candidate_id = f"sdc_{hashlib.sha1(signature.encode()).hexdigest()[:16]}"
        # 同签名簇已归档后，新证据重建同名簇会覆盖归档指纹 → 加后缀隔离
        if self._store.get_cluster(candidate_id) is not None:
            candidate_id = f"{candidate_id}_{hashlib.sha1(fingerprint.encode()).hexdigest()[:8]}"
        cluster = SemanticDiscoveryCluster(
            cluster_id=candidate_id,
            normalized_concept=normalized,
            semantic_role=role,
            semantic_type=semantic_type,
            policy_value_signature=values,
            concept=signal.concept,
            diagnosis=signal.diagnosis,
            evidence=[signal.evidence],
            evidence_fingerprints=[fingerprint],
            policy_metric_code=signal.metric_code if signal.object_code == POLICY_OBJECT_CODE else None,
        )
        # 近似概念（同 normalized_concept、不同签名）→ 建议合并，不自动合并（§6.1）
        cluster.suggested_merge_cluster_ids = [
            c.cluster_id for c in open_clusters
            if c.normalized_concept == normalized and self._signature_of(c) != signature
        ]
        return self._store.save_cluster(cluster)

    def merge_clusters(
        self, source_id: str, into_id: str, reviewer: str, reason: str,
    ) -> SemanticDiscoveryCluster:
        """人工处理聚类歧义：合并两个簇（理由必填，设计 §6.1）。"""
        if not reason.strip():
            raise ValueError("合并发现必须填写理由")
        source = self._require_cluster(source_id)
        target = self._require_cluster(into_id)
        if source.status != ClusterStatus.PENDING or target.status != ClusterStatus.PENDING:
            raise ValueError("只能合并待验证状态的发现簇")
        merged = target.model_copy(deep=True)
        known = set(merged.evidence_fingerprints)
        for item, fp in zip(source.evidence, source.evidence_fingerprints):
            if fp not in known:
                merged.evidence.append(item)
                merged.evidence_fingerprints.append(fp)
                known.add(fp)
        merged.policy_value_signature = sorted(set(
            merged.policy_value_signature + source.policy_value_signature
        ))
        merged.cross_validation = None
        merged.score = None
        merged.review_note = f"合并 {source_id}: {reason}（by {reviewer}）"
        merged.updated_at = _now()
        result = self._store.save_cluster(merged)
        # 源簇标记归档，指纹保留阻止重复进入
        archived = source.model_copy(update={
            "status": ClusterStatus.NOT_ISSUE,
            "review_note": f"已合并至 {into_id}: {reason}（by {reviewer}）",
            "updated_at": _now(),
        })
        self._store.save_cluster(archived)
        return result

    def split_cluster(
        self,
        cluster_id: str,
        source_refs: list[str],
        reviewer: str,
        reason: str,
        *,
        new_concept: str | None = None,
    ) -> SemanticDiscoveryCluster:
        """人工拆分聚类歧义（设计 §6.1/§9.2）：把指定证据移入新簇。

        按时间或业务场景拆分都由人指定要移出的证据来源，系统不猜测拆分轴。
        """
        if not reason.strip():
            raise ValueError("拆分发现必须填写理由")
        if not source_refs:
            raise ValueError("拆分必须指定至少一条证据来源")
        cluster = self._require_cluster(cluster_id)
        if cluster.status != ClusterStatus.PENDING:
            raise ValueError("只能拆分待验证状态的发现簇")
        movable = {
            e.source_ref: (i, e, fp)
            for i, (e, fp) in enumerate(
                zip(cluster.evidence, cluster.evidence_fingerprints)
            )
        }
        unknown = [ref for ref in source_refs if ref not in movable]
        if unknown:
            raise ValueError(f"证据来源不存在于簇内: {unknown}")
        if len(source_refs) >= len(cluster.evidence):
            raise ValueError("拆分不能移出全部证据，源簇至少保留一条")
        remaining_idx = [i for i in range(len(cluster.evidence))
                         if cluster.evidence[i].source_ref not in set(source_refs)]
        moved = [movable[ref] for ref in source_refs]

        new_cluster = cluster.model_copy(deep=True)
        new_cluster.cluster_id = f"{cluster.cluster_id}_split_{hashlib.sha1(reason.encode()).hexdigest()[:6]}"
        new_cluster.concept = new_concept or cluster.concept
        new_cluster.evidence = [item[1] for item in moved]
        new_cluster.evidence_fingerprints = [item[2] for item in moved]
        new_cluster.cross_validation = None
        new_cluster.score = None
        new_cluster.review_note = f"拆分自 {cluster_id}: {reason}（by {reviewer}）"
        new_cluster.updated_at = _now()
        self._store.save_cluster(new_cluster)

        shrunk = cluster.model_copy(deep=True)
        shrunk.evidence = [cluster.evidence[i] for i in remaining_idx]
        shrunk.evidence_fingerprints = [cluster.evidence_fingerprints[i] for i in remaining_idx]
        shrunk.cross_validation = None
        shrunk.score = None
        shrunk.review_note = f"拆分出 {new_cluster.cluster_id}: {reason}（by {reviewer}）"
        shrunk.updated_at = _now()
        return self._store.save_cluster(shrunk)

    # ── 全政策交叉验证 + 评分 + 值域对齐 ──

    def refresh_cluster(
        self,
        cluster_id: str,
        *,
        database_values: list[DatabaseValueObservation] | None = None,
        aliases: list[str] | None = None,
    ) -> SemanticDiscoveryCluster:
        """重新执行全政策交叉验证、评分与值域对齐。

        database_values 未显式提供时，若装配了库值画像加载器（§5.2 自动取数），
        则按业务指标 source_field 自动加载，不再依赖调用方手工传值。
        """
        cluster = self._require_cluster(cluster_id)
        cluster.cross_validation = self._cross_validate(cluster, aliases or [])
        if database_values is None and self._db_value_loader is not None:
            database_values = self._load_database_values(cluster)
        cluster.value_alignment = self._compute_alignment(cluster, database_values or [])
        cluster.score = self._score(cluster)
        cluster.updated_at = _now()
        return self._store.save_cluster(cluster)

    def _load_database_values(
        self, cluster: SemanticDiscoveryCluster,
    ) -> list[DatabaseValueObservation]:
        """按业务指标绑定的物理字段自动拉取 bjyb 值域画像；失败时降级为空。"""
        if not cluster.business_metric_code:
            return []
        metric = self._registry.get_metric(cluster.business_metric_code)
        if metric is None or not metric.source_field:
            return []
        try:
            return self._db_value_loader(  # type: ignore[misc]
                cluster.business_metric_code, metric.source_field,
            )
        except Exception:
            logger.warning("PDSC 库值画像加载失败 metric=%s", cluster.business_metric_code, exc_info=True)
            return []

    def _cross_validate(
        self, cluster: SemanticDiscoveryCluster, aliases: list[str],
    ) -> CrossValidationSummary:
        summary = CrossValidationSummary()
        try:
            records = self._corpus.find_unit_evidence(
                cluster.concept, aliases, cluster.policy_value_signature,
            )
        except Exception:
            logger.warning("PDSC 全政策交叉验证失败", exc_info=True)
            summary.error = "政策语料暂不可用，交叉验证未完成"
            return summary
        extension: list[str] = []
        for record in records:
            record.kind = self._classify(record, cluster)
            if record.kind == CrossPolicyKind.EXTENDING:
                extension.extend(
                    v for v in record.found_values if v not in cluster.policy_value_signature
                )
        summary.items = records
        summary.counts = {
            kind.value: sum(1 for r in records if r.kind == kind)
            for kind in CrossPolicyKind
        }
        summary.extension_values = sorted(set(extension))
        summary.blocked = summary.counts[CrossPolicyKind.CONFLICTING.value] > 0
        return summary

    @staticmethod
    def _classify(record: PolicyUnitEvidence, cluster: SemanticDiscoveryCluster) -> CrossPolicyKind:
        # 归类顺序：冲突 → 时间变体 → 扩展/支持（概念或政策值命中即可）→ 无关。
        # 枚举维度的发现，概念词几乎从不在原文出现，政策值同现即独立证据。
        if record.concept_matched and record.semantic_role is not None \
                and record.semantic_role != cluster.semantic_role:
            return CrossPolicyKind.CONFLICTING
        matched_values = [v for v in record.found_values if v in cluster.policy_value_signature]
        if record.concept_matched and record.version_stage == "historical" \
                and record.effective_period and matched_values:
            return CrossPolicyKind.TEMPORAL_VARIANT
        if record.concept_matched or matched_values:
            has_new = any(v not in cluster.policy_value_signature for v in record.found_values)
            return CrossPolicyKind.EXTENDING if has_new else CrossPolicyKind.SUPPORTING
        return CrossPolicyKind.IRRELEVANT

    def _score(self, cluster: SemanticDiscoveryCluster) -> GovernanceValueScore:
        """治理价值分（设计 §7.1）：可信度 40% + 落地支持 35% + 影响力 25%。"""
        explanations: list[str] = []
        evidence = cluster.evidence
        replayable = sum(
            1 for e in evidence
            if (e.excerpt and e.doc_id) or (e.table_name and e.field_name)
        )
        replay_ratio = replayable / len(evidence) if evidence else 0.0
        docs = {e.doc_id for e in evidence if e.doc_id}
        doc_factor = min(1.0, len(docs) / 3)
        validation = cluster.cross_validation
        conflict_ratio = 0.0
        if validation and validation.counts:
            classified = sum(validation.counts.values())
            if classified:
                conflict_ratio = validation.counts[CrossPolicyKind.CONFLICTING.value] / classified
        credibility = round((0.5 * replay_ratio + 0.5 * doc_factor) * (1 - 0.5 * conflict_ratio), 3)
        explanations.append(
            f"可信度={credibility}（可重放证据比 {replay_ratio:.2f}，独立文档 {len(docs)}，冲突比 {conflict_ratio:.2f}）"
        )

        domain_complete = self._policy_domain_complete(cluster)
        business_metric = (
            self._registry.get_metric(cluster.business_metric_code)
            if cluster.business_metric_code else None
        )
        db_rate = (
            cluster.value_alignment.db_definition_rate
            if cluster.value_alignment else None
        )
        if business_metric is not None:
            bound = 0.4 if (business_metric.source_field or business_metric.source_object) else 0.0
            # 库画像单一取值 → 绑定不计落地支持：数据无区分度，摆事实入解释而非硬驳回
            profile = self._load_business_profile(business_metric)
            if profile is not None \
                    and profile.get("distinct_count") is not None \
                    and profile["distinct_count"] <= 1:
                bound = 0.0
                explanations.append(
                    f"业务字段仅单一取值（distinct={profile['distinct_count']}），绑定暂不计落地支持"
                )
            landing = round(0.3 * domain_complete + bound + 0.3 * (db_rate or 0.0), 3)
            explanations.append(f"落地支持={landing}（业务指标已绑定，值域完整 {domain_complete}，库值释义率 {db_rate}）")
        else:
            # policy_only 不因此否定政策语义，但明确降低可自动查询部分得分（§7.3）
            landing = round(0.6 * domain_complete, 3)
            explanations.append(f"落地支持={landing}（无业务指标，仅政策值域完整 {domain_complete}）")

        units = {e.unit_id for e in evidence if e.unit_id}
        if validation:
            units.update(item.unit_id for item in validation.items if item.unit_id)
        rules = {rule for e in evidence for rule in e.rule_ids}
        skills = 1 if business_metric is not None and business_metric.usage_count > 0 else 0
        impact = round(
            0.6 * min(1.0, len(units) / 5) + 0.25 * min(1.0, len(rules) / 10) + 0.15 * skills, 3,
        )
        explanations.append(f"影响力={impact}（政策单元 {len(units)}，规则 {len(rules)}，Skill 依赖 {skills}）")

        total = round(0.4 * credibility + 0.35 * landing + 0.25 * impact, 3)
        return GovernanceValueScore(
            credibility=credibility, landing_support=landing,
            policy_impact=impact, total=total, explanations=explanations,
        )

    def _policy_domain_complete(self, cluster: SemanticDiscoveryCluster) -> int:
        if not cluster.policy_metric_code:
            return 0
        metric = self._registry.get_metric(cluster.policy_metric_code)
        if metric is None:
            return 0
        if metric.value_domain:
            return 1 if self._registry.get_value_domain(metric.value_domain) is not None else 0
        return 1

    def _compute_alignment(
        self, cluster: SemanticDiscoveryCluster, database_values: list[DatabaseValueObservation],
    ) -> ValueDomainAlignment:
        """值域符合度（设计 §8）：库值无可靠释义 → 不可计算，不伪造分数。"""
        validation = cluster.cross_validation
        full_policy_values = sorted(set(
            cluster.policy_value_signature + (validation.extension_values if validation else [])
        ))
        business_metric = (
            self._registry.get_metric(cluster.business_metric_code)
            if cluster.business_metric_code else None
        )
        standard_values: list[str] = []
        domain_code = business_metric.value_domain if business_metric else None
        if domain_code:
            domain = self._registry.get_value_domain(domain_code)
            standard_values = list(domain.standard_values) if domain else []

        mapped = set(standard_values)
        if domain_code:
            for mapping in self._registry.get_value_mappings(domain_code):
                mapped.add(mapping.standard_value)
        coverage = (
            sum(1 for v in full_policy_values if v in mapped) / len(full_policy_values)
            if full_policy_values else None
        )
        mapping_confidence = coverage  # Phase 1：映射证据以标准值/映射覆盖近似

        observations = self._classify_database_values(database_values, mapped, validation)
        total_db = len(observations)
        defined_db = sum(1 for o in observations if o.definition)
        db_rate = round(defined_db / total_db, 3) if total_db else None

        alignment: float | None = None
        notes: list[str] = []
        if total_db and defined_db == 0:
            notes.append("数据库代码无可靠中文释义，值域对齐度不可计算（设计 §7.5）")
        elif coverage is not None:
            alignment = round(
                coverage * 0.6 + (db_rate or 0.0) * 0.25 + (mapping_confidence or 0.0) * 0.15, 3,
            )
        return ValueDomainAlignment(
            trigger_values=cluster.policy_value_signature,
            full_policy_values=full_policy_values,
            business_standard_values=standard_values,
            database_values=observations,
            policy_coverage_rate=coverage,
            db_definition_rate=db_rate,
            mapping_evidence_confidence=mapping_confidence,
            alignment_score=alignment,
            notes=notes,
        )

    @staticmethod
    def _classify_database_values(
        database_values: list[DatabaseValueObservation],
        business_standard: set[str],
        validation: CrossValidationSummary | None,
    ) -> list[DatabaseValueObservation]:
        """库额外值反向验证（设计 §5.2）：无释义 → 不可判断；有释义未命中政策 → 数据库专用。"""
        policy_supported: set[str] = set()
        if validation:
            policy_supported = {v for item in validation.items for v in item.found_values}
        result: list[DatabaseValueObservation] = []
        for obs in database_values:
            classification = "aligned" if obs.value in business_standard else None
            if classification is None:
                if not obs.definition:
                    classification = "undecidable"
                elif obs.value in policy_supported:
                    classification = "value_extension"
                else:
                    classification = "db_only"
            result.append(obs.model_copy(update={"classification": classification}))
        return result

    # ── 人工裁决（设计 §9.2 / §7.5）──

    def decide(
        self,
        cluster_id: str,
        action: DecisionAction,
        reviewer: str,
        reason: str | None = None,
    ) -> SemanticDiscoveryCluster:
        cluster = self._require_cluster(cluster_id)
        if cluster.status != ClusterStatus.PENDING:
            raise ValueError(f"发现簇已裁决: {cluster.status}")
        if action == DecisionAction.NOT_ISSUE and not (reason or "").strip():
            raise ValueError("驳回发现必须填写理由")
        if action == DecisionAction.ACCEPT_FULL_PLAN:
            if cluster.cross_validation is None or cluster.score is None:
                cluster = self.refresh_cluster(cluster_id)
            validation = cluster.cross_validation
            if validation is not None and validation.blocked:
                raise ValueError("存在未解决语义冲突，不能一键批准（设计 §7.5）")
            single_source = len({e.source_ref for e in cluster.evidence}) <= 1
            supporting = validation.counts.get(CrossPolicyKind.SUPPORTING.value, 0) \
                if validation else 0
            if single_source and supporting == 0 and not (reason or "").strip():
                raise ValueError("单一来源且无独立政策支持，需补证据或填写裁决理由")
            if not cluster.business_metric_code:
                raise ValueError("无业务指标绑定，请改用 policy_only 或先调整方案")
            new_status = ClusterStatus.ACCEPTED
        elif action == DecisionAction.POLICY_ONLY:
            new_status = ClusterStatus.POLICY_ONLY_ACCEPTED
        elif action == DecisionAction.INSUFFICIENT_EVIDENCE:
            new_status = ClusterStatus.PENDING  # 保留待补证据状态
        else:
            new_status = ClusterStatus.NOT_ISSUE
        updated = cluster.model_copy(update={
            "status": new_status,
            "reviewed_by": reviewer,
            "reviewed_at": _now(),
            "review_note": reason,
            "updated_at": _now(),
        })
        return self._store.save_cluster(updated)

    def adjust_cluster(
        self,
        cluster_id: str,
        reviewer: str,
        reason: str,
        *,
        business_metric_code: str | None = None,
        policy_metric_code: str | None = None,
        policy_values: list[str] | None = None,
    ) -> SemanticDiscoveryCluster:
        """调整方案：任何修改后重新计算交叉验证、分数与影响（设计 §9.2）。"""
        if not reason.strip():
            raise ValueError("调整方案必须填写理由")
        cluster = self._require_cluster(cluster_id)
        if cluster.status != ClusterStatus.PENDING:
            raise ValueError("只能调整待验证状态的发现簇")
        if business_metric_code and self._registry.get_metric(business_metric_code) is None:
            raise ValueError(f"业务指标不存在: {business_metric_code}")
        if business_metric_code:
            bound = self._registry.get_metric(business_metric_code)
            if bound is not None and bound.object_code == POLICY_OBJECT_CODE:
                raise ValueError("业务指标不能挂在政策规则对象上（设计 §10.1）")
        if policy_metric_code and not policy_metric_code.startswith(f"{POLICY_OBJECT_CODE}."):
            raise ValueError(f"政策指标必须属于 {POLICY_OBJECT_CODE}: {policy_metric_code}")
        update: dict[str, Any] = {
            "review_note": f"调整: {reason}（by {reviewer}）",
            "updated_at": _now(),
            "cross_validation": None,
            "score": None,
        }
        if business_metric_code is not None:
            update["business_metric_code"] = business_metric_code
        if policy_metric_code is not None:
            update["policy_metric_code"] = policy_metric_code
        if policy_values is not None:
            update["policy_value_signature"] = sorted(set(policy_values))
        return self._store.save_cluster(cluster.model_copy(update=update, deep=True))

    # ── 政策适用关系（设计 §10.2 / §10.3）──

    def build_applicability_relation(
        self,
        cluster_id: str,
        reviewer: str,
        value_mappings: list[RelationValueMappingItem] | None = None,
    ) -> PolicyApplicabilityRelation:
        cluster = self._require_cluster(cluster_id)
        if cluster.status != ClusterStatus.ACCEPTED:
            raise ValueError("只有接受完整方案的发现簇才能构建适用关系")
        policy_code = cluster.policy_metric_code
        business_code = cluster.business_metric_code
        if not policy_code or not policy_code.startswith(f"{POLICY_OBJECT_CODE}."):
            raise ValueError(f"政策指标缺失或非法: {policy_code}")
        if not business_code:
            raise ValueError("业务指标缺失；无业务字段应使用 policy_only 裁决")
        policy_metric = self._registry.get_metric(policy_code)
        business_metric = self._registry.get_metric(business_code)
        if policy_metric is None or business_metric is None:
            raise ValueError("政策指标或业务指标未注册")
        if business_metric.object_code == POLICY_OBJECT_CODE:
            raise ValueError("业务指标不能挂在政策规则对象上（设计 §10.1）")
        mappings = value_mappings or self._infer_mappings(cluster, policy_metric, business_metric)
        self._validate_mappings(mappings, policy_metric, business_metric)
        relation = PolicyApplicabilityRelation(
            relation_id=f"par_{hashlib.sha1(f'{policy_code}:{business_code}'.encode()).hexdigest()[:16]}",
            policy_metric_code=policy_code,
            business_metric_code=business_code,
            policy_value_domain_code=policy_metric.value_domain,
            business_value_domain_code=business_metric.value_domain,
            value_mappings=mappings,
            source_cluster_id=cluster.cluster_id,
        )
        relation = self._store.save_relation(relation)
        logger.info("构建政策适用关系 %s: %s ← %s（by %s）",
                    relation.relation_id, policy_code, business_code, reviewer)
        return relation

    def _infer_mappings(
        self, cluster: SemanticDiscoveryCluster,
        policy_metric: Metric, business_metric: Metric,
    ) -> list[RelationValueMappingItem]:
        """默认值映射：同值直配 + registry 已有人工映射；只用有业务释义的值（§10.2）。"""
        policy_values = set(cluster.policy_value_signature)
        standard: set[str] = set()
        if business_metric.value_domain:
            domain = self._registry.get_value_domain(business_metric.value_domain)
            if domain:
                standard = set(domain.standard_values)
        mapped_sources: dict[str, str] = {}
        if business_metric.value_domain:
            for mapping in self._registry.get_value_mappings(business_metric.value_domain):
                mapped_sources.setdefault(mapping.standard_value, mapping.source_value)
        items: list[RelationValueMappingItem] = []
        for value in sorted(policy_values):
            if value in standard:
                items.append(RelationValueMappingItem(
                    policy_value=value, business_values=[value],
                    sources=[f"standard:{business_metric.value_domain}"],
                ))
            elif value in mapped_sources:
                items.append(RelationValueMappingItem(
                    policy_value=value, business_values=[mapped_sources[value]],
                    sources=[f"mapping:{business_metric.value_domain}"],
                ))
        return items

    def _validate_mappings(
        self, mappings: list[RelationValueMappingItem],
        policy_metric: Metric, business_metric: Metric,
    ) -> None:
        policy_domain = (
            self._registry.get_value_domain(policy_metric.value_domain)
            if policy_metric.value_domain else None
        )
        business_domain = (
            self._registry.get_value_domain(business_metric.value_domain)
            if business_metric.value_domain else None
        )
        for item in mappings:
            if policy_domain and item.policy_value not in policy_domain.standard_values:
                raise ValueError(f"政策值不在政策值域: {item.policy_value}")
            if not item.business_values:
                raise ValueError(f"政策值 {item.policy_value} 缺少业务标准值映射")
            for value in item.business_values:
                if business_domain and value not in business_domain.standard_values:
                    raise ValueError(f"业务值不在业务值域: {value}")

    def publish_relation(self, relation_id: str, reviewer: str) -> PolicyApplicabilityRelation:
        """关系发布门禁（设计 §11.3）：两端指标必须已发布且值域版本一致。"""
        relation = self._store.get_relation(relation_id)
        if relation is None:
            raise ValueError(f"适用关系不存在: {relation_id}")
        if relation.status == "published":
            return relation
        policy_metric = self._registry.get_metric(relation.policy_metric_code)
        business_metric = self._registry.get_metric(relation.business_metric_code)
        if policy_metric is None or policy_metric.status != "published":
            raise ValueError("政策指标未发布，不能发布适用关系")
        if business_metric is None or business_metric.status != "published":
            raise ValueError("业务指标未发布，不能发布适用关系")
        updated = relation.model_copy(update={
            "status": "published",
            "revision": relation.revision + 1,
            "updated_at": _now(),
        })
        del reviewer
        return self._store.save_relation(updated)

    def execute_activation(
        self,
        cluster_id: str,
        reviewer: str,
        ports: ActivationPorts | None = None,
    ) -> ClusterActivation:
        """执行激活流水线（设计 §11.2/§11.3）：任一步失败不改活动版本。

        步骤：语义资产门禁 → 重提取 → 编译门禁 → Milvus schema 门禁 →
        Skill 验证 → 发布关系（唯一的活动版本变更点）。
        """
        cluster = self._require_cluster(cluster_id)
        if cluster.status not in (ClusterStatus.ACCEPTED, ClusterStatus.POLICY_ONLY_ACCEPTED):
            raise ValueError("只能激活已接受完整方案或政策专用的发现簇")
        if any(
            a.status == ActivationStatus.RUNNING
            for a in self._store.list_activations(cluster_id)
        ):
            raise ValueError("该发现簇已有进行中的激活")
        ports = ports or ActivationPorts()
        reextractor = ports.reextractor or _NoopReextractor()
        compile_checker: CompileCheckPort | None = ports.compile_checker
        skill_verifier = ports.skill_verifier or _DefaultSkillVerifier(self)

        activation = ClusterActivation(
            activation_id="act_" + hashlib.sha1(
                (cluster_id + ":" + _now().isoformat()).encode()
            ).hexdigest()[:16],
            cluster_id=cluster_id, activated_by=reviewer,
        )

        def _run(step: str, outcome: dict[str, Any]) -> bool:
            activation.steps.append(ActivationStepResult(
                step=step, passed=bool(outcome.get("passed")),
                detail=str(outcome.get("detail", "")),
            ))
            return bool(outcome.get("passed"))

        try:
            if compile_checker is None:
                compile_checker = _DefaultCompileChecker(self._corpus_store())
            # 步骤 1：语义资产门禁（§11.3）
            asset_ok, asset_detail = self._check_semantic_assets(cluster)
            if not _run("semantic_assets", {"passed": asset_ok, "detail": asset_detail}):
                raise ValueError(asset_detail)

            # 步骤 2：受影响单元重提取
            doc_ids = sorted({e.doc_id for e in cluster.evidence if e.doc_id})
            if not _run("reextract", reextractor.reextract_docs(doc_ids)):
                raise ValueError("重提取失败")

            # 步骤 3：编译门禁
            if not _run("compile", compile_checker.check_docs(doc_ids)):
                raise ValueError("受影响政策单元编译未通过")

            # 步骤 4：候选 Milvus schema 门禁（政策指标已进标量字段集）
            schema_fields = _milvus_schema_fields()
            policy_field = (cluster.policy_metric_code or "").split(".", 1)[-1]
            if not _run("milvus_schema", {
                "passed": bool(policy_field) and policy_field in schema_fields,
                "detail": f"政策指标字段 {policy_field or '未设置'} ∈ 候选 schema"
                          if policy_field in schema_fields else
                          f"政策指标字段 {policy_field or '未设置'} 不在候选 Milvus schema",
            }):
                raise ValueError("政策指标未进入候选 Milvus schema")

            # 步骤 5：Skill 验证（仅适用关系存在时）
            relations = [
                r for r in self._store.list_relations()
                if r.source_cluster_id == cluster_id and r.status != "published"
            ]
            for relation in relations:
                if not _run("skill_verification", skill_verifier.verify(relation)):
                    raise ValueError("Skill 无法从业务事实解析政策过滤条件")

            # 步骤 6：激活 = 发布关系（唯一活动版本变更点）
            for relation in relations:
                self.publish_relation(relation.relation_id, reviewer)
            activation.status = ActivationStatus.SUCCEEDED
        except Exception as exc:  # noqa: BLE001 — 任一异常都落激活记录，不丢状态
            activation.status = ActivationStatus.FAILED
            activation.failed_step = activation.steps[-1].step if activation.steps else None
            activation.error = str(exc)
        activation.updated_at = _now()
        return self._store.save_activation(activation)

    def _check_semantic_assets(
        self, cluster: SemanticDiscoveryCluster,
    ) -> tuple[bool, str]:
        policy_metric = (
            self._registry.get_metric(cluster.policy_metric_code)
            if cluster.policy_metric_code else None
        )
        if policy_metric is None or policy_metric.status != "published":
            return False, f"政策指标未发布: {cluster.policy_metric_code}"
        if cluster.status == ClusterStatus.POLICY_ONLY_ACCEPTED:
            return True, "policy_only：无适用关系要求"
        business_metric = (
            self._registry.get_metric(cluster.business_metric_code)
            if cluster.business_metric_code else None
        )
        if business_metric is None or business_metric.status != "published":
            return False, f"业务指标未发布: {cluster.business_metric_code}"
        return True, "两端指标均已发布"

    def _corpus_store(self) -> Any:
        """编译门禁读取提取行的存储句柄；PipelineStorePolicyCorpus 携带原 store。"""
        store = getattr(self._corpus, "_store", None)
        if store is None:
            raise ValueError("激活需要可读提取行的语料适配器")
        return store

    def get_activation(self, activation_id: str) -> ClusterActivation | None:
        return self._store.get_activation(activation_id)

    def list_activations(self, cluster_id: str | None = None) -> list[ClusterActivation]:
        return self._store.list_activations(cluster_id)

    def resolve_policy_filters(
        self, business_metric_code: str, business_standard_value: str,
    ) -> list[PolicyFilter]:
        """最小解析接口（设计 §10.3）：业务事实值 → 政策适用条件。"""
        filters: list[PolicyFilter] = []
        for relation in self._store.list_relations(business_metric_code):
            if relation.status != "published":
                continue
            for item in relation.value_mappings:
                if business_standard_value in item.business_values:
                    filters.append(PolicyFilter(
                        policy_metric_code=relation.policy_metric_code,
                        policy_value=item.policy_value,
                    ))
        return filters

    # ── 扫描接入（§4.2）──

    def scan_and_intake(
        self,
        extractions: list[dict[str, Any]],
        db_fields: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """运行六类确定性检测器并全部接入发现簇（§4.2 → §6 聚合）。"""
        from src.knowledge_extension.rule_explanation.pdsc_detectors import detect_signals

        detected = detect_signals(extractions, self._registry, db_fields)
        before = {c.cluster_id for c in self._store.list_clusters()}
        rejected = 0
        for signals in detected.values():
            for signal in signals:
                try:
                    self.intake_signal(signal)
                except ValueError:
                    rejected += 1
                    logger.warning("PDSC 扫描：信号被拒 concept=%s", signal.concept)
        return {
            "scanned_extractions": len(extractions),
            "intaked_clusters": len(
                {c.cluster_id for c in self._store.list_clusters()} - before
            ),
            "rejected_signals": rejected,
            "detectors": {kind: len(sigs) for kind, sigs in detected.items()},
        }

    # ── 查询 ──

    def get_cluster(self, cluster_id: str) -> SemanticDiscoveryCluster | None:
        return self._store.get_cluster(cluster_id)

    def list_clusters(
        self, statuses: list[ClusterStatus] | None = None,
    ) -> list[SemanticDiscoveryCluster]:
        """默认按治理价值分降序；同分优先冲突多/单元多/最近更新（设计 §9.1）。"""
        items = self._store.list_clusters(statuses)

        def sort_key(c: SemanticDiscoveryCluster) -> tuple:
            total = c.score.total if c.score else 0.0
            conflicts = (
                c.cross_validation.counts.get(CrossPolicyKind.CONFLICTING.value, 0)
                if c.cross_validation else 0
            )
            units = len({e.unit_id for e in c.evidence if e.unit_id})
            return (-total, -conflicts, -units, -c.updated_at.timestamp())

        return sorted(items, key=sort_key)

    def list_relations(self, business_metric_code: str | None = None) -> list[PolicyApplicabilityRelation]:
        return self._store.list_relations(business_metric_code)

    def get_business_metric_usage(self, business_metric_code: str | None) -> int:
        """决策包展示用：业务指标的 Skill 引用次数。"""
        if not business_metric_code:
            return 0
        metric = self._registry.get_metric(business_metric_code)
        return metric.usage_count if metric else 0

    def _load_business_profile(self, metric: Metric) -> dict[str, Any] | None:
        """按指标物理字段拉库画像（非空率/distinct/样本值）；失败降级为 None，不影响打分。"""
        if self._db_profile_loader is None or not metric.source_field:
            return None
        try:
            return self._db_profile_loader(metric.metric_code, metric.source_field)
        except Exception:
            logger.warning("PDSC 库画像加载失败 metric=%s", metric.metric_code, exc_info=True)
            return None

    def get_business_field_profile(
        self, cluster: SemanticDiscoveryCluster,
        candidates: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """决策包展示用：已绑定指标的库画像；未绑定时取最佳候选的画像。"""
        metric_code = cluster.business_metric_code
        if not metric_code and candidates:
            metric_code = candidates[0].get("metric_code")
        if not metric_code:
            return None
        metric = self._registry.get_metric(metric_code)
        if metric is None:
            return None
        profile = self._load_business_profile(metric)
        if profile is None:
            return None
        return {
            "metric_code": metric_code,
            "source_field": metric.source_field,
            **profile,
        }

    def suggest_business_metric_candidates(
        self, cluster: SemanticDiscoveryCluster, limit: int = 3,
    ) -> list[dict[str, Any]]:
        """候选业务指标：名称相似 + 值域重合打分（确定性，不调模型）。

        取代手填编码：适用关系只对 Enum 维度有意义，只逃非 zcgz 的 Enum 指标。
        """
        import difflib

        concept = cluster.concept or ""
        signature = set(cluster.policy_value_signature)
        candidates: list[dict[str, Any]] = []
        for metric in self._registry.list_metrics():
            if metric.object_code == POLICY_OBJECT_CODE or metric.semantic_type != "Enum":
                continue
            ratio = difflib.SequenceMatcher(None, concept, metric.name or "").ratio()
            overlap: list[str] = []
            if metric.value_domain:
                domain = self._registry.get_value_domain(metric.value_domain)
                if domain:
                    overlap = [v for v in domain.standard_values if v in signature]
            # 相似度计入实分（并列时 80% 应胜 60%）；已发布微加成（免二次流转）
            score = (2.0 * ratio if ratio >= 0.5 else 0.0) \
                + min(3, len(overlap)) + (0.2 if metric.status == "published" else 0.0)
            if score <= 0:
                continue
            reasons: list[str] = []
            if ratio >= 0.5:
                reasons.append(f"名称匹配度 {ratio:.0%}")
            if overlap:
                reasons.append(f"值域重合 {len(overlap)} 值（{'、'.join(overlap[:3])}）")
            candidates.append({
                "metric_code": metric.metric_code,
                "name": metric.name,
                "status": metric.status,
                "source_object": metric.source_object,
                "source_field": metric.source_field,
                "value_domain": metric.value_domain,
                "value_overlap": overlap,
                "match_reasons": reasons,
                "_score": score,
            })
        candidates.sort(key=lambda c: -c["_score"])
        for item in candidates:
            item.pop("_score", None)
        return candidates[:limit]

    # ── 内部 ──

    def _require_cluster(self, cluster_id: str) -> SemanticDiscoveryCluster:
        cluster = self._store.get_cluster(cluster_id)
        if cluster is None:
            raise ValueError(f"发现簇不存在: {cluster_id}")
        return cluster

    def _cluster_holding_fingerprint(self, fingerprint: str) -> SemanticDiscoveryCluster | None:
        for cluster in self._store.list_clusters():
            if fingerprint in cluster.evidence_fingerprints:
                return cluster
        return None

    def _cluster_holding_source(
        self, source_ref: str, evidence_kind: str,
    ) -> SemanticDiscoveryCluster | None:
        for cluster in self._store.list_clusters([ClusterStatus.PENDING]):
            if any(
                e.source_ref == source_ref and e.evidence_kind == evidence_kind
                for e in cluster.evidence
            ):
                return cluster
        return None

    @staticmethod
    def _signature_of(cluster: SemanticDiscoveryCluster) -> str:
        return _semantic_signature(
            cluster.normalized_concept, cluster.semantic_role,
            cluster.semantic_type, cluster.policy_value_signature,
        )


# ── 单例装配 ─────────────────────────────────────────────────────

_pdsc_service: PdscService | None = None
_pdsc_service_lock = RLock()


def _load_db_values_from_discovery(
    metric_code: str, source_field: str,
) -> list[DatabaseValueObservation]:
    """按业务指标物理字段拉 bjyb 值域画像（§5.2 自动取数）。"""
    from src.runtime.api.semantic_routes import _get_discovery_store

    store = _get_discovery_store()
    latest = store.get_latest_result()
    if not latest:
        return []
    # source_field 形如 bjybdb.m_institution.H_TYPE 或直接列名
    parts = source_field.split(".")
    field_name = parts[-1]
    table_name = parts[-2] if len(parts) >= 2 else ""
    descriptions = store.get_all_field_descriptions()
    observations: list[DatabaseValueObservation] = []
    for raw in latest.get("fields", []):
        if raw.get("field_name") != field_name:
            continue
        if table_name and raw.get("table_name") not in (table_name, f"dbo.{table_name}"):
            continue
        key = f"{raw.get('table_name', '')}:{field_name}".casefold()
        description = descriptions.get(key, {}).get("description") or raw.get("description")
        for value in (raw.get("sample_values") or [])[:50]:
            observations.append(DatabaseValueObservation(
                value=str(value), definition=description,
            ))
        if observations:
            break
    return observations


def _load_field_profile_from_discovery(metric_code: str, source_field: str) -> dict | None:
    """按指标物理字段拉库画像（非空率/distinct/样本值/释义，取自最近一次发现扫描）。"""
    from src.runtime.api.semantic_routes import _get_discovery_store

    store = _get_discovery_store()
    latest = store.get_latest_result()
    if not latest:
        return None
    # source_field 形如 bjybdb.m_institution.H_TYPE / m_institution.H_LEVEL / 列名
    parts = source_field.split(".")
    field_name = parts[-1]
    table_name = parts[-2] if len(parts) >= 2 else ""
    descriptions = store.get_all_field_descriptions()
    for raw in latest.get("fields", []):
        if raw.get("field_name") != field_name:
            continue
        if table_name and raw.get("table_name") not in (table_name, f"dbo.{table_name}"):
            continue
        key = f"{raw.get('table_name', '')}:{field_name}".casefold()
        description = descriptions.get(key, {}).get("description") or raw.get("description")
        return {
            "table_name": raw.get("table_name"),
            "field_name": field_name,
            "non_null_rate": raw.get("non_null_rate"),
            "distinct_count": raw.get("distinct_count"),
            "sample_values": (raw.get("sample_values") or [])[:8],
            "has_description": bool(description),
            "last_updated": raw.get("last_updated"),
        }
    return None


def get_pdsc_service() -> PdscService:
    global _pdsc_service
    if _pdsc_service is None:
        with _pdsc_service_lock:
            if _pdsc_service is None:
                from src.semantic_layer.registry import get_semantic_registry

                loader = None
                profile_loader = None
                if os.environ.get("USE_MEMORY_STORAGE") != "1":
                    loader = _load_db_values_from_discovery  # best-effort，失败自动降级为空
                    profile_loader = _load_field_profile_from_discovery
                if os.environ.get("USE_MEMORY_STORAGE") == "1":
                    store: PdscStore = InMemoryPdscStore()
                else:
                    from src.data_platform.storage.postgresql.pdsc_store import PostgresPdscStore
                    store = PostgresPdscStore()
                corpus = _build_corpus()
                _pdsc_service = PdscService(
                    get_semantic_registry(), store, corpus, loader, profile_loader,
                )
    return _pdsc_service


def _build_corpus() -> PolicyCorpusPort:
    """默认语料适配器；PG 不可用时降级为 Null 语料（交叉验证标记未完成）。"""
    if os.environ.get("USE_MEMORY_STORAGE") == "1":
        return NullPolicyCorpus()
    try:
        from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore
        return PipelineStorePolicyCorpus(PipelineStore())
    except Exception:
        logger.warning("PDSC 语料适配器初始化失败，降级 NullPolicyCorpus", exc_info=True)
        return NullPolicyCorpus()
