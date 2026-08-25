"""PDSC（政策—数据语义协同发现）服务单元测试。

对应设计 §13 最小验证范围：1 证据去重、2 语义聚类、3 全政策验证、
4 值域反向验证、5 价值评分、7 关系边界、8 Skill Flow、9 policy_only。
"""
from __future__ import annotations

import pytest

from src.knowledge_extension.rule_explanation.pdsc import (
    ClusterStatus,
    CrossPolicyKind,
    DatabaseValueObservation,
    DecisionAction,
    InMemoryPdscStore,
    PdscService,
    PolicyUnitEvidence,
    RelationValueMappingItem,
    SemanticRole,
)
from src.knowledge_extension.rule_explanation.semantic_alignment import (
    DiscoveryEvidence,
    DiscoverySignal,
    TriggerSource,
)
from src.semantic_layer.models import BusinessObject, Metric, ValueDomain, ValueDomainMapping
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry


class FakeCorpus:
    def __init__(self, records: list[PolicyUnitEvidence]) -> None:
        self.records = records

    def find_unit_evidence(self, concept, aliases, values):
        return self.records


def _registry() -> SemanticRegistry:
    store = InMemoryRegistryStore()
    store.save_object(BusinessObject(object_code="zcgz", domain_code="policy", name="政策规则"))
    store.save_object(BusinessObject(object_code="djxx", domain_code="ybdy", name="参保人登记"))
    store.save_value_domain(ValueDomain(domain_code="HOSP_TYPE", name="机构类别",
                                        standard_values=["三级医院", "二级医院", "一级医院"]))
    store.save_value_domain(ValueDomain(domain_code="POLICY_HOSP", name="政策机构类别",
                                        standard_values=["三级医院", "二级医院", "一级医院"]))
    store.save_metric(Metric(
        metric_code="zcgz.hosp_type", object_code="zcgz", name="机构类别",
        semantic_type="Enum", value_domain="POLICY_HOSP", status="published",
    ))
    store.save_metric(Metric(
        metric_code="djxx.hosp_type", object_code="djxx", name="医疗机构类别",
        semantic_type="Enum", value_domain="HOSP_TYPE",
        source_object="Institution", source_field="category", status="published",
    ))
    store.save_value_mapping(ValueDomainMapping(
        domain_code="HOSP_TYPE", source_value="三级", standard_value="三级医院",
    ))
    return SemanticRegistry(store)


def _service(corpus_records: list[PolicyUnitEvidence] | None = None) -> PdscService:
    return PdscService(_registry(), InMemoryPdscStore(), FakeCorpus(corpus_records or []))


def _policy_signal(
    source_ref: str, concept: str = "医疗机构类别",
    doc_id: str = "doc_1", unit_id: str = "unit_1", excerpt: str = "三级医院支付比例85%",
    values: list[str] | None = None, rule_ids: list[str] | None = None,
) -> DiscoverySignal:
    return DiscoverySignal(
        trigger_source=TriggerSource.EXTRACTION_UNKNOWN,
        evidence=DiscoveryEvidence(
            source_ref=source_ref, evidence_kind="policy",
            doc_id=doc_id, unit_id=unit_id, extraction_id=f"ext_{source_ref}",
            excerpt=excerpt, sample_values=values or ["三级医院", "二级医院"],
            rule_ids=rule_ids or [],
        ),
        concept=concept,
        semantic_type="Enum",
        metric_code="zcgz.hosp_type",
    )


def test_same_detector_same_concept_merges_across_values():
    """同维度同检测器的不同越界值是同一发现：合并为一张卡，值域并集。

    线上4张「医疗类别」卡（购药/住院/急诊/门诊）即此根因。
    """
    service = _service()
    sigs = [
        DiscoverySignal(
            trigger_source=TriggerSource.EXTRACTION_UNKNOWN,
            evidence=DiscoveryEvidence(
                source_ref=f"t_{v}", evidence_kind="policy",
                doc_id="doc_1", unit_id=f"u_{v}", extraction_id=f"e_{v}",
                excerpt=f"医疗类别出现值域外取值「{v}」", sample_values=[v],
                observations=["detector:value_domain_violation"],
            ),
            concept="医疗类别", semantic_type="Enum", metric_code="zcgz.med_type",
        )
        for v in ("购药", "住院", "急诊", "门诊")
    ]
    first = service.intake_signal(sigs[0])
    for s in sigs[1:]:
        merged = service.intake_signal(s)
        assert merged.cluster_id == first.cluster_id
    cluster = service.get_cluster(first.cluster_id)
    assert len(cluster.evidence) == 4
    assert set(cluster.policy_value_signature) == {"购药", "住院", "急诊", "门诊"}


def test_same_concept_different_detector_stays_separate():
    """同维度不同检测器是不同发现：不自动合并，只建议合并。"""
    service = _service()
    a = service.intake_signal(DiscoverySignal(
        trigger_source=TriggerSource.EXTRACTION_UNKNOWN,
        evidence=DiscoveryEvidence(
            source_ref="t1", evidence_kind="policy", doc_id="d", unit_id="u",
            extraction_id="e1", excerpt="x",
            observations=["detector:value_domain_violation"],
        ),
        concept="医疗类别", semantic_type="Enum",
    ))
    b = service.intake_signal(DiscoverySignal(
        trigger_source=TriggerSource.EXTRACTION_UNKNOWN,
        evidence=DiscoveryEvidence(
            source_ref="t2", evidence_kind="policy", doc_id="d", unit_id="u2",
            extraction_id="e2", excerpt="x",
            observations=["detector:structure_compression"],
        ),
        concept="医疗类别", semantic_type="Enum",
    ))
    assert b.cluster_id != a.cluster_id
    assert a.cluster_id in b.suggested_merge_cluster_ids


# ── §13.1 证据精确去重 ──


def test_same_task_rerun_does_not_duplicate_evidence_or_score():
    service = _service()
    first = service.intake_signal(_policy_signal("task_1/run_1"), policy_values=["三级医院", "二级医院"])
    scored = service.refresh_cluster(first.cluster_id)
    evidence_before = len(scored.evidence)
    score_before = scored.score.total

    rerun = service.intake_signal(_policy_signal("task_1/run_2"), policy_values=["三级医院", "二级医院"])
    # 同一 extraction 的重跑：source_ref 不同但内容指纹一致 → 替换不新增
    assert rerun.cluster_id == first.cluster_id
    assert len(rerun.evidence) == evidence_before
    rescored = service.refresh_cluster(rerun.cluster_id)
    assert rescored.score.total == score_before


def test_rerun_with_same_source_ref_replaces_evidence():
    service = _service()
    first = service.intake_signal(_policy_signal("task_1"), policy_values=["三级医院"])
    updated = service.intake_signal(_policy_signal("task_1", excerpt="三级医院支付比例86%"))
    assert updated.cluster_id == first.cluster_id
    assert len(updated.evidence) == 1


# ── §13.2 语义聚类 ──


def test_same_concept_multiple_expressions_form_one_cluster():
    service = _service()
    a = service.intake_signal(
        _policy_signal("task_1", concept="医疗机构类别"), policy_values=["三级医院"])
    b = service.intake_signal(
        _policy_signal("task_2", concept="医疗机构类别", doc_id="doc_2"),
        policy_values=["三级医院"])
    assert b.cluster_id == a.cluster_id
    assert len(b.evidence) == 2


def test_conflicting_signature_not_auto_merged_only_suggested():
    service = _service()
    a = service.intake_signal(
        _policy_signal("task_1", concept="医疗机构类别"),
        semantic_role=SemanticRole.DIMENSION, policy_values=["三级医院"])
    b = service.intake_signal(
        _policy_signal("task_2", concept="医疗机构类别", doc_id="doc_2"),
        semantic_role=SemanticRole.MEASURE, policy_values=["三级医院"])
    # 签名不同（角色冲突）→ 不自动合并，只建议合并
    assert b.cluster_id != a.cluster_id
    assert a.cluster_id in b.suggested_merge_cluster_ids


def test_merge_clusters_requires_reason_and_moves_evidence():
    service = _service()
    a = service.intake_signal(_policy_signal("task_1"), policy_values=["三级医院"])
    b = service.intake_signal(_policy_signal("task_2", doc_id="doc_2"),
                              semantic_role=SemanticRole.MEASURE, policy_values=["二级医院"])
    with pytest.raises(ValueError, match="理由"):
        service.merge_clusters(b.cluster_id, a.cluster_id, "r1", " ")
    merged = service.merge_clusters(b.cluster_id, a.cluster_id, "r1", "角色判定相同")
    assert len(merged.evidence) == 2
    assert merged.policy_value_signature == ["三级医院", "二级医院"]
    assert service.get_cluster(b.cluster_id).status == ClusterStatus.NOT_ISSUE


# ── §13.3 全政策交叉验证 ──


def _unit(doc_id: str, unit_id: str, *, values: list[str], matched: bool = True,
          stage: str = "current", role: SemanticRole | None = None,
          period: str | None = None) -> PolicyUnitEvidence:
    return PolicyUnitEvidence(
        doc_id=doc_id, unit_id=unit_id, excerpt=f"{doc_id}/{unit_id} 原文",
        found_values=values, version_stage=stage, concept_matched=matched,
        semantic_role=role, effective_period=period,
    )


def test_cross_validation_classifies_all_five_kinds():
    records = [
        _unit("doc_1", "u1", values=["三级医院"]),                                   # supporting
        _unit("doc_2", "u2", values=["三级医院", "社区医院"]),                        # extending
        _unit("doc_3", "u3", values=["三级医院"], stage="historical",
              period="2019年"),                                                      # temporal_variant
        _unit("doc_4", "u4", values=[], matched=True,
              role=SemanticRole.MEASURE),                                            # conflicting
        _unit("doc_5", "u5", values=[], matched=False),                     # irrelevant
    ]
    service = _service(records)
    cluster = service.intake_signal(_policy_signal("t1"), policy_values=["三级医院"])
    refreshed = service.refresh_cluster(cluster.cluster_id)
    counts = refreshed.cross_validation.counts
    assert counts[CrossPolicyKind.SUPPORTING.value] == 1
    assert counts[CrossPolicyKind.EXTENDING.value] == 1
    assert counts[CrossPolicyKind.TEMPORAL_VARIANT.value] == 1
    assert counts[CrossPolicyKind.CONFLICTING.value] == 1
    assert counts[CrossPolicyKind.IRRELEVANT.value] == 1
    assert refreshed.cross_validation.extension_values == ["社区医院"]
    assert refreshed.cross_validation.blocked


def test_value_only_match_counts_as_supporting():
    """枚举维度的发现：概念词不在原文、但政策值同现 → 应计 supporting 而非 irrelevant。

    线上田4 ： supporting 全 0、irrelevant 46，根因是拿诊断句做子串匹配。
    """
    records = [_unit("doc_9", "u9", values=["三级医院"], matched=False)]
    service = _service(records)
    cluster = service.intake_signal(_policy_signal("t1"), policy_values=["三级医院"])
    refreshed = service.refresh_cluster(cluster.cluster_id)
    counts = refreshed.cross_validation.counts
    assert counts[CrossPolicyKind.SUPPORTING.value] == 1
    assert counts[CrossPolicyKind.IRRELEVANT.value] == 0


def test_business_metric_candidates_by_name_and_value_overlap():
    """候选业务指标：名称相似 + 值域重合打分，取代手填编码。"""
    service = _service()
    cluster = service.intake_signal(_policy_signal("t1", concept="医疗机构类别"),
                                    policy_values=["三级医院", "二级医院"])
    candidates = service.suggest_business_metric_candidates(cluster)
    assert candidates, "应至少给出 djxx.hosp_type 候选"
    top = candidates[0]
    assert top["metric_code"] == "djxx.hosp_type"
    assert top["value_overlap"] == ["三级医院", "二级医院"]
    assert any("名称" in r or "值域" in r for r in top["match_reasons"])


def test_score_penalizes_single_value_business_field():
    """库画像 distinct_count≤1 → 绑定不计落地支持（数据无区分度，摆事实入解释）。"""
    service = _service()
    cluster = service.intake_signal(_policy_signal("t1"), policy_values=["三级医院"])
    service.adjust_cluster(cluster.cluster_id, "r", "绑定",
                           business_metric_code="djxx.hosp_type")
    service._db_profile_loader = lambda code, field: {"distinct_count": 1}
    refreshed = service.refresh_cluster(cluster.cluster_id)
    # 惩罚只清零绑定项（0.4）：landing = 0.3×值域完整 + 0×绑定 + 0×释义
    assert refreshed.score.landing_support == pytest.approx(0.3)
    assert any("单一取值" in e for e in refreshed.score.explanations)


# ── §13.4 值域反向验证 ──


def test_database_extra_value_reverse_validation():
    records = [_unit("doc_2", "u2", values=["社区医院"], matched=True)]
    service = _service(records)
    cluster = service.intake_signal(_policy_signal("t1"), policy_values=["三级医院"])
    service.adjust_cluster(cluster.cluster_id, "r", "绑定业务指标",
                           business_metric_code="djxx.hosp_type")
    refreshed = service.refresh_cluster(cluster.cluster_id, database_values=[
        DatabaseValueObservation(value="三级医院", definition="三级"),
        DatabaseValueObservation(value="社区医院", definition="社区卫生服务中心"),
        DatabaseValueObservation(value="A01", definition=None),
        DatabaseValueObservation(value="B02", definition="内部代码"),
    ])
    alignment = refreshed.value_alignment
    classes = {o.value: o.classification for o in alignment.database_values}
    assert classes["三级医院"] == "aligned"
    assert classes["社区医院"] == "value_extension"  # 有释义且政策找到支持
    assert classes["A01"] == "undecidable"           # 无释义 → 不可判断
    assert classes["B02"] == "db_only"               # 有释义但政策未找到 → 数据库专用值
    assert alignment.alignment_score is not None


def test_alignment_not_computable_without_db_definitions():
    service = _service()
    cluster = service.intake_signal(_policy_signal("t1"), policy_values=["三级医院"])
    refreshed = service.refresh_cluster(cluster.cluster_id, database_values=[
        DatabaseValueObservation(value="A01"),
        DatabaseValueObservation(value="A02"),
    ])
    assert refreshed.value_alignment.alignment_score is None
    assert any("不可计算" in note for note in refreshed.value_alignment.notes)


# ── §13.5 价值评分 ──


def test_score_has_three_explainable_subscores():
    records = [
        _unit("doc_1", "u1", values=["三级医院"]),
        _unit("doc_2", "u2", values=["三级医院"]),
    ]
    service = _service(records)
    cluster = service.intake_signal(_policy_signal("t1"), policy_values=["三级医院"])
    service.adjust_cluster(cluster.cluster_id, "r", "绑定业务指标",
                           business_metric_code="djxx.hosp_type")
    refreshed = service.refresh_cluster(cluster.cluster_id)
    score = refreshed.score
    assert 0 <= score.credibility <= 1 and 0 <= score.landing_support <= 1 and 0 <= score.policy_impact <= 1
    expected = round(0.4 * score.credibility + 0.35 * score.landing_support + 0.25 * score.policy_impact, 3)
    assert score.total == expected
    assert len(score.explanations) == 3  # 每个子分一条解释


# ── §7.5 门禁 ──


def test_conflict_blocks_one_click_accept():
    records = [_unit("doc_4", "u4", values=[], matched=True, role=SemanticRole.MEASURE)]
    service = _service(records)
    cluster = service.intake_signal(_policy_signal("t1"), policy_values=["三级医院"])
    with pytest.raises(ValueError, match="不能一键批准"):
        service.decide(cluster.cluster_id, DecisionAction.ACCEPT_FULL_PLAN, "reviewer")


def test_single_source_without_support_requires_reason():
    service = _service()  # corpus 无支持证据
    cluster = service.intake_signal(_policy_signal("t1"), policy_values=["三级医院"])
    with pytest.raises(ValueError, match="补证据"):
        service.decide(cluster.cluster_id, DecisionAction.ACCEPT_FULL_PLAN, "reviewer")


def test_not_issue_requires_reason_and_archives_fingerprint():
    service = _service()
    cluster = service.intake_signal(_policy_signal("t1"), policy_values=["三级医院"])
    with pytest.raises(ValueError, match="理由"):
        service.decide(cluster.cluster_id, DecisionAction.NOT_ISSUE, "reviewer")
    archived = service.decide(cluster.cluster_id, DecisionAction.NOT_ISSUE, "reviewer", reason="字段混用")
    assert archived.status == ClusterStatus.NOT_ISSUE
    # 归档后同指纹信号不再进入新簇
    again = service.intake_signal(_policy_signal("t1"), policy_values=["三级医院"])
    assert again.cluster_id == archived.cluster_id
    assert len(again.evidence) == 1


def test_new_evidence_after_archive_does_not_overwrite_archived_cluster():
    """归档簇后，同签名新证据不得覆盖归档簇（簇 ID 冲突防护）。"""
    service = _service()
    cluster = service.intake_signal(_policy_signal("t1"), policy_values=["三级医院"])
    service.decide(cluster.cluster_id, DecisionAction.NOT_ISSUE, "reviewer", reason="文字相似")

    # 同签名、不同内容（新指纹）→ 新簇，归档簇保持不变
    revived = service.intake_signal(
        _policy_signal("t2", excerpt="三级医院起付标准不同段落"),
        policy_values=["三级医院"],
    )
    assert revived.cluster_id != cluster.cluster_id
    assert service.get_cluster(cluster.cluster_id).status == ClusterStatus.NOT_ISSUE
    assert len(service.get_cluster(cluster.cluster_id).evidence) == 1


# ── §13.7 关系边界 ──


def test_relation_boundary_constraints():
    records = [_unit("doc_1", "u1", values=["三级医院"])]
    service = _service(records)
    cluster = service.intake_signal(_policy_signal("t1"), policy_values=["三级医院"])
    # 未接受完整方案 → 不能建关系
    with pytest.raises(ValueError, match="只有接受完整方案"):
        service.build_applicability_relation(cluster.cluster_id, "r")
    # 无业务指标 → accept 拒绝，须用 policy_only
    with pytest.raises(ValueError, match="业务指标"):
        service.decide(cluster.cluster_id, DecisionAction.ACCEPT_FULL_PLAN, "r", reason="补")


def test_business_metric_cannot_live_on_policy_object():
    store = InMemoryRegistryStore()
    store.save_object(BusinessObject(object_code="zcgz", domain_code="policy", name="政策规则"))
    store.save_value_domain(ValueDomain(domain_code="HOSP_TYPE", name="机构类别",
                                        standard_values=["三级医院"]))
    store.save_metric(Metric(metric_code="zcgz.biz_hosp", object_code="zcgz",
                             name="非法业务指标", semantic_type="Enum", value_domain="HOSP_TYPE",
                             source_field="x"))
    service = PdscService(SemanticRegistry(store), InMemoryPdscStore(), FakeCorpus([]))
    cluster = service.intake_signal(_policy_signal("t1"), policy_values=["三级医院"])
    # 业务指标挂在政策规则对象上 → 绑定阶段即拦截（设计 §10.1）
    with pytest.raises(ValueError, match="政策规则对象"):
        service.adjust_cluster(cluster.cluster_id, "r", "错挂业务指标",
                               business_metric_code="zcgz.biz_hosp")


# ── §13.8 Skill Flow ──


def test_resolve_policy_filters_full_flow():
    records = [_unit("doc_1", "u1", values=["三级医院"])]
    service = _service(records)
    cluster = service.intake_signal(_policy_signal("t1"), policy_values=["三级医院"])
    service.adjust_cluster(cluster.cluster_id, "r", "绑定业务指标",
                           business_metric_code="djxx.hosp_type")
    accepted = service.decide(cluster.cluster_id, DecisionAction.ACCEPT_FULL_PLAN, "reviewer")
    assert accepted.status == ClusterStatus.ACCEPTED
    relation = service.build_applicability_relation(cluster.cluster_id, "reviewer")
    assert relation.policy_metric_code == "zcgz.hosp_type"
    assert relation.business_metric_code == "djxx.hosp_type"
    # 值映射只使用有业务释义的标准值
    assert [m.policy_value for m in relation.value_mappings] == ["三级医院"]

    # 未发布关系 → 无过滤条件
    assert service.resolve_policy_filters("djxx.hosp_type", "三级医院") == []
    service.publish_relation(relation.relation_id, "reviewer")
    filters = service.resolve_policy_filters("djxx.hosp_type", "三级医院")
    assert [(f.policy_metric_code, f.policy_value) for f in filters] == [("zcgz.hosp_type", "三级医院")]
    # 非映射值 → 空
    assert service.resolve_policy_filters("djxx.hosp_type", "未知值") == []


def test_explicit_mappings_validate_against_domains():
    records = [_unit("doc_1", "u1", values=["三级医院"])]
    service = _service(records)
    cluster = service.intake_signal(_policy_signal("t1"), policy_values=["三级医院"])
    service.adjust_cluster(cluster.cluster_id, "r", "绑定", business_metric_code="djxx.hosp_type")
    service.decide(cluster.cluster_id, DecisionAction.ACCEPT_FULL_PLAN, "reviewer")
    with pytest.raises(ValueError, match="业务值不在业务值域"):
        service.build_applicability_relation(
            cluster.cluster_id, "reviewer",
            value_mappings=[RelationValueMappingItem(
                policy_value="三级医院", business_values=["四级医院"])],
        )


# ── §13.9 policy_only ──


def test_policy_only_publishes_metric_without_relation():
    records = [_unit("doc_1", "u1", values=["三级医院"])]
    service = _service(records)
    cluster = service.intake_signal(_policy_signal("t1"), policy_values=["三级医院"])
    decided = service.decide(cluster.cluster_id, DecisionAction.POLICY_ONLY, "reviewer")
    assert decided.status == ClusterStatus.POLICY_ONLY_ACCEPTED
    with pytest.raises(ValueError, match="只有接受完整方案"):
        service.build_applicability_relation(cluster.cluster_id, "reviewer")


# ── §9.1 排序 ──


def test_clusters_sorted_by_total_score_desc():
    records = [
        _unit("doc_1", "u1", values=["三级医院"]),
        _unit("doc_2", "u2", values=["三级医院"]),
    ]
    service = _service(records)
    low = service.intake_signal(_policy_signal("t1", concept="医疗机构类别"),
                                policy_values=["三级医院"])
    high = service.intake_signal(
        DiscoverySignal(
            trigger_source=TriggerSource.EXTRACTION_UNKNOWN,
            evidence=DiscoveryEvidence(
                source_ref="t2", evidence_kind="policy", doc_id="doc_9",
                unit_id="u9", extraction_id="e9", excerpt="原文",
                sample_values=["起付金额"],
            ),
            concept="起付标准", semantic_type="Enum", metric_code="zcgz.hosp_type",
        ), policy_values=["三级医院"])
    for cid in (low.cluster_id, high.cluster_id):
        service.adjust_cluster(cid, "r", "绑定业务指标", business_metric_code="djxx.hosp_type")
        service.refresh_cluster(cid)
    ordered = service.list_clusters()
    totals = [c.score.total for c in ordered]
    assert totals == sorted(totals, reverse=True)
    assert len(ordered) == 2
