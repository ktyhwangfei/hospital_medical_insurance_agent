"""PDSC Phase 2 单元测试：检测器（§4.2）、拆分（§6.1）、自动库值（§5.2）、
激活流水线（§11.2/§11.3，含失败不改活动版本 §13.10）。"""
from __future__ import annotations

from typing import Any

import pytest

from src.knowledge_extension.rule_explanation.pdsc import (
    ActivationPorts,
    ClusterStatus,
    DatabaseValueObservation,
    DecisionAction,
    InMemoryPdscStore,
    PdscService,
    PolicyUnitEvidence,
    SemanticDiscoveryCluster,
)
from src.knowledge_extension.rule_explanation.pdsc_detectors import detect_signals
from src.knowledge_extension.rule_explanation.semantic_alignment import (
    DiscoverySignal,
    TriggerSource,
)
from src.semantic_layer.models import BusinessObject, Metric, ValueDomain
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry


class FakeCorpus:
    def __init__(self, records=None, store=None):
        self.records = records or []
        self._store = store

    def find_unit_evidence(self, concept, aliases, values):
        return self.records


def _registry() -> SemanticRegistry:
    store = InMemoryRegistryStore()
    store.save_object(BusinessObject(object_code="zcgz", domain_code="policy", name="政策规则"))
    store.save_object(BusinessObject(object_code="djxx", domain_code="ybdy", name="参保人登记"))
    store.save_value_domain(ValueDomain(domain_code="HOSP_LV", name="医院等级",
                                        standard_values=["三级医院", "二级医院", "一级医院"]))
    store.save_value_domain(ValueDomain(domain_code="INST_CAT", name="机构类别",
                                        standard_values=["三级医院", "社区卫生服务中心"]))
    store.save_value_domain(ValueDomain(domain_code="PSN_TYPE", name="人员类别",
                                        standard_values=["在职", "退休"]))
    store.save_value_domain(ValueDomain(domain_code="JJGS", name="基金归属",
                                        standard_values=["统筹基金", "大额医疗互助资金"]))
    store.save_metric(Metric(metric_code="zcgz.hosp_lv", object_code="zcgz", name="医院等级",
                             semantic_type="Enum", value_domain="HOSP_LV", status="published"))
    store.save_metric(Metric(metric_code="zcgz.inst_cat", object_code="zcgz", name="机构类别",
                             semantic_type="Enum", value_domain="INST_CAT", status="published"))
    store.save_metric(Metric(metric_code="zcgz.psn_type", object_code="zcgz", name="人员类别",
                             semantic_type="Enum", value_domain="PSN_TYPE", status="published"))
    store.save_metric(Metric(metric_code="zcgz.jjgs", object_code="zcgz", name="基金归属",
                             semantic_type="Enum", value_domain="JJGS", status="published"))
    store.save_metric(Metric(metric_code="djxx.hospital_level", object_code="djxx",
                             name="医院等级", semantic_type="Enum", value_domain="HOSP_LV",
                             source_object="Institution", source_field="bjybdb.m_institution.H_TYPE",
                             status="published"))
    return SemanticRegistry(store)


def _ext(ext_id: str, doc_id: str, unit_id: str, text: str, fields: dict) -> dict:
    return {
        "extraction_id": ext_id, "doc_id": doc_id, "unit_id": unit_id,
        "source_text": text, "extracted_fields": fields,
    }


def _accepted_cluster(service: PdscService) -> SemanticDiscoveryCluster:
    cluster = service.intake_signal(_signal("t1"), policy_values=["三级医院"])
    service.adjust_cluster(cluster.cluster_id, "r", "绑定", business_metric_code="djxx.hospital_level")
    service.decide(cluster.cluster_id, DecisionAction.ACCEPT_FULL_PLAN, "reviewer",
                   reason="单源补裁决理由")
    service.build_applicability_relation(cluster.cluster_id, "reviewer")
    return service.get_cluster(cluster.cluster_id)


def _signal(source_ref: str, values: list[str] | None = None) -> DiscoverySignal:
    return DiscoverySignal(
        trigger_source=TriggerSource.EXTRACTION_UNKNOWN,
        evidence={
            "source_ref": source_ref, "evidence_kind": "policy",
            "doc_id": f"doc_{source_ref}", "unit_id": f"unit_{source_ref}",
            "extraction_id": f"ext_{source_ref}",
            "excerpt": f"三级医院住院支付比例（{source_ref}）",
            "sample_values": values or ["三级医院"],
        },
        concept="医院等级", semantic_type="Enum", metric_code="zcgz.hosp_lv",
    )


# ── §4.2 检测器 ──


def test_detector_axis_value_conflict_and_domain_violation():
    registry = _registry()
    extractions = [
        # inst_cat 字段落了 HOSP_LV 值 → 轴角色冲突
        _ext("e1", "d1", "u1", "社区卫生服务中心报销", {"inst_cat": "二级医院"}),
        # psn_type 值域越界
        _ext("e2", "d1", "u2", "在职人员起付", {"psn_type": "灵活就业人员"}),
    ]
    detected = detect_signals(extractions, registry)
    assert any("业务口径冲突" in s.diagnosis for s in detected["axis_value_conflict"])
    assert any("值域外取值" in s.diagnosis for s in detected["value_domain_violation"])


def test_detector_reads_rules_array_not_toplevel():
    """回归（线上 4 条误报根因）：提取值位于 extracted_fields.rules[]，顶层无字段键。

    rules[] 已保留全部区分值时不得报结构压缩；部分丢失时报压缩并记录提取落值。
    """
    registry = _registry()
    kept = [
        _ext("e1", "d1", "u1", "一级医院和二级医院起付标准不同",
             {"rules": [
                 {"rule_id": "r1", "hosp_lv": "一级医院"},
                 {"rule_id": "r2", "hosp_lv": "二级医院"},
             ], "fact_text": "-", "total_rules": 2}),
    ]
    assert detect_signals(kept, registry)["structure_compression"] == []

    partial = [
        _ext("e2", "d1", "u2", "一级医院和二级医院起付标准不同",
             {"rules": [{"rule_id": "r1", "hosp_lv": "一级医院"}],
                "fact_text": "-", "total_rules": 1}),
    ]
    signals = detect_signals(partial, registry)["structure_compression"]
    assert len(signals) == 1
    assert signals[0].evidence.extracted_values == ["一级医院"]


def test_detector_concept_clean_and_diagnosis_separate():
    """概念与诊断分离：concept 存干净业务名，诊断句进 diagnosis（供交叉验证取词）。"""
    registry = _registry()
    extractions = [
        _ext("e1", "d1", "u1", "一级医院和二级医院起付标准不同", {"hosp_lv": ""}),
    ]
    signals = detect_signals(extractions, registry)["structure_compression"]
    assert signals[0].concept == "医院等级"
    assert "作了明确区分" in signals[0].diagnosis


def test_detector_value_violation_inside_rules():
    """值域越界检测需读 rules[] 内的字段值（此前只读顶层导致漏检）。"""
    registry = _registry()
    extractions = [
        _ext("e1", "d1", "u1", "实习生起付标准",
             {"rules": [{"rule_id": "r1", "psn_type": "实习生"}]}),
    ]
    signals = detect_signals(extractions, registry)["value_domain_violation"]
    assert any("值域外取值「实习生」" in s.diagnosis for s in signals)


def test_detector_structure_compression():
    registry = _registry()
    extractions = [
        # 原文区分两个等级，但字段为空 → 压缩
        _ext("e1", "d1", "u1", "一级医院和二级医院起付标准不同", {"hosp_lv": ""}),
    ]
    detected = detect_signals(extractions, registry)
    assert any("作了明确区分" in s.diagnosis for s in detected["structure_compression"])


def test_detector_cross_unit_inconsistency():
    registry = _registry()
    text = "三级医院住院报销比例为85%，二级医院为75%"
    extractions = [
        _ext("e1", "d1", "u1", text, {"hosp_lv": "三级医院"}),
        _ext("e2", "d2", "u2", text, {"inst_cat": "三级医院"}),
    ]
    detected = detect_signals(extractions, registry)
    assert any("映射到不同字段" in s.diagnosis for s in detected["cross_unit_inconsistency"])


def test_detector_subject_pollution_and_business_role_conflict():
    registry = _registry()
    extractions = [
        _ext("e1", "d1", "u1", "支付比例", {"hosp_lv": "85%"}),
    ]
    db_fields = [
        # H_TYPE 样本值跨两个值域 → 业务角色冲突
        {"table_name": "m_institution", "field_name": "H_TYPE",
         "sample_values": ["三级医院", "社区卫生服务中心"],
         "non_null_rate": 0.98, "distinct_count": 4},
    ]
    detected = detect_signals(extractions, registry, db_fields)
    assert any("结果值" in s.diagnosis for s in detected["subject_pollution"])
    assert any("角色冲突" in s.diagnosis for s in detected["business_role_conflict"])
    # 无库画像时检测器 6 不产信号
    assert detect_signals(extractions, registry, None)["business_role_conflict"] == []


def test_detected_signals_flow_into_clusters_with_dedup():
    registry = _registry()
    service = PdscService(registry, InMemoryPdscStore(), FakeCorpus())
    extractions = [
        _ext("e1", "d1", "u1", "在职人员起付", {"psn_type": "灵活就业人员"}),
    ]
    signals = detect_signals(extractions, registry)
    for sig in signals["value_domain_violation"]:
        service.intake_signal(sig)
    clusters = service.list_clusters([ClusterStatus.PENDING])
    assert len(clusters) == 1
    # 重跑扫描不新增簇/证据
    for sig in detect_signals(extractions, registry)["value_domain_violation"]:
        service.intake_signal(sig)
    assert len(service.list_clusters([ClusterStatus.PENDING])) == 1
    assert len(service.list_clusters([ClusterStatus.PENDING])[0].evidence) == 1


def test_detector_structure_compression_ignores_amount_boundaries():
    """金额边界短语不算轴值：'XX基金最高支付限额'是区间描述，非规则取值。

    线上误报：jjgs 簇声称压缩丢失了统筹基金，实际该词只作为区间边界出现。
    """
    registry = _registry()
    text = ("超过基本医疗保险统筹基金最高支付限额以上，大额医疗互助资金最高支付限额以下的"
            "医疗费用，在职职工报销比例为85%。")
    extractions = [
        _ext("e1", "d1", "u1", text,
             {"rules": [
                 {"rule_id": "r1", "jjgs": "大额医疗互助资金", "psn_type": "在职"},
             ]}),
    ]
    assert detect_signals(extractions, registry)["structure_compression"] == []


def test_detector_cross_unit_limited_to_cross_document():
    """同文档近似重复单元不是跨条款不一致；跨文档才报，且不拿字段名当政策值。"""
    registry = _registry()
    text = "三级医院住院报销比例为85%，二级医院为75%，在职人员起付线不同"
    same_doc = [
        _ext("e1", "d1", "u1", text, {"hosp_lv": "三级医院", "psn_type": "在职"}),
        _ext("e2", "d1", "u2", text + "。", {"hosp_lv": "三级医院", "psn_type": "在职",
                                             "setl_type": "按项目付费"}),
    ]
    assert detect_signals(same_doc, registry)["cross_unit_inconsistency"] == []

    cross_doc = same_doc + [
        _ext("e3", "d2", "u3", text + "！", {"hosp_lv": "三级医院"}),
    ]
    signals = detect_signals(cross_doc, registry)["cross_unit_inconsistency"]
    assert len(signals) == 1
    assert all(not v.startswith(("hosp_lv", "setl_type")) for v in signals[0].evidence.sample_values)


# ── §6.1 拆分 ──


def test_split_moves_evidence_to_new_cluster():
    service = PdscService(_registry(), InMemoryPdscStore(), FakeCorpus())
    service.intake_signal(_signal("t1"), policy_values=["三级医院"])
    service.intake_signal(_signal("t2"), policy_values=["三级医院"])
    service.intake_signal(_signal("t3"), policy_values=["三级医院"])
    cluster = service.list_clusters([ClusterStatus.PENDING])[0]
    assert len(cluster.evidence) == 3

    with pytest.raises(ValueError, match="理由"):
        service.split_cluster(cluster.cluster_id, ["t1"], "r", " ")
    with pytest.raises(ValueError, match="至少保留一条"):
        service.split_cluster(cluster.cluster_id, ["t1", "t2", "t3"], "r", "按时间拆分")

    shrunk = service.split_cluster(cluster.cluster_id, ["t1", "t2"], "r", "按时间拆分",
                                   new_concept="医院等级(历史)")
    assert len(shrunk.evidence) == 1
    assert shrunk.cross_validation is None and shrunk.score is None
    new = [c for c in service.list_clusters([ClusterStatus.PENDING])
           if c.cluster_id != cluster.cluster_id][0]
    assert len(new.evidence) == 2
    assert new.concept == "医院等级(历史)"


# ── §5.2 自动库值 ──


def test_refresh_auto_loads_database_values_via_loader():
    def loader(metric_code: str, source_field: str) -> list[DatabaseValueObservation]:
        return [DatabaseValueObservation(value="三级医院", definition="定点三级")]

    service = PdscService(_registry(), InMemoryPdscStore(), FakeCorpus(), loader)
    cluster = service.intake_signal(_signal("t1"), policy_values=["三级医院"])
    service.adjust_cluster(cluster.cluster_id, "r", "绑定",
                           business_metric_code="djxx.hospital_level")
    refreshed = service.refresh_cluster(cluster.cluster_id)  # 未传 database_values
    values = refreshed.value_alignment.database_values
    assert values and values[0].value == "三级医院" and values[0].classification == "aligned"


def test_loader_failure_degrades_to_empty_not_error():
    def loader(metric_code, source_field):
        raise RuntimeError("discovery store down")

    service = PdscService(_registry(), InMemoryPdscStore(), FakeCorpus(), loader)
    cluster = service.intake_signal(_signal("t1"), policy_values=["三级医院"])
    service.adjust_cluster(cluster.cluster_id, "r", "绑定",
                           business_metric_code="djxx.hospital_level")
    refreshed = service.refresh_cluster(cluster.cluster_id)
    assert refreshed.value_alignment.database_values == []


# ── §11.2/§11.3 激活流水线 ──


class StubReextractor:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.called: list[list[str]] = []

    def reextract_docs(self, doc_ids: list[str]) -> dict[str, Any]:
        self.called.append(list(doc_ids))
        return {"passed": not self.fail, "detail": "stub 重提取"}


class StubCompileChecker:
    def __init__(self, fail: bool = False):
        self.fail = fail

    def check_docs(self, doc_ids: list[str]) -> dict[str, Any]:
        return {"passed": not self.fail, "detail": "stub 编译"}


def _ports(reextract_fail=False, compile_fail=False) -> ActivationPorts:
    return ActivationPorts(
        reextractor=StubReextractor(reextract_fail),
        compile_checker=StubCompileChecker(compile_fail),
    )


def test_activation_success_publishes_relation():
    service = PdscService(_registry(), InMemoryPdscStore(), FakeCorpus())
    cluster = _accepted_cluster(service)
    ports = _ports()
    activation = service.execute_activation(cluster.cluster_id, "reviewer", ports)

    assert activation.status.value == "succeeded"
    step_names = [s.step for s in activation.steps]
    assert step_names == ["semantic_assets", "reextract", "compile",
                          "milvus_schema", "skill_verification"]
    assert all(s.passed for s in activation.steps)
    assert ports.reextractor.called == [["doc_t1"]]  # 受影响文档已重提取
    relation = service.list_relations()[0]
    assert relation.status == "published"


def test_activation_compile_failure_keeps_active_versions_unchanged():
    """§13.10：候选构建/验证失败不改变活动版本（关系保持 draft）。"""
    service = PdscService(_registry(), InMemoryPdscStore(), FakeCorpus())
    cluster = _accepted_cluster(service)
    activation = service.execute_activation(
        cluster.cluster_id, "reviewer", _ports(compile_fail=True),
    )

    assert activation.status.value == "failed"
    assert activation.failed_step == "compile"
    assert not activation.steps[-1].passed
    relation = service.list_relations()[0]
    assert relation.status == "draft"  # 活动版本未变


def test_activation_reextract_failure_blocks_pipeline():
    service = PdscService(_registry(), InMemoryPdscStore(), FakeCorpus())
    cluster = _accepted_cluster(service)
    activation = service.execute_activation(
        cluster.cluster_id, "reviewer", _ports(reextract_fail=True),
    )
    assert activation.status.value == "failed"
    assert activation.failed_step == "reextract"
    # 编译等后续步骤未执行
    assert [s.step for s in activation.steps] == ["semantic_assets", "reextract"]


def test_activation_rejects_unpublished_metrics():
    store = InMemoryRegistryStore()
    registry = _registry()
    # zcgz 指标改为 draft
    draft = registry.get_metric("zcgz.hosp_lv").model_copy(update={"status": "draft"})
    registry.save_metric_draft(draft)
    service = PdscService(registry, InMemoryPdscStore(), FakeCorpus())
    cluster = service.intake_signal(_signal("t1"), policy_values=["三级医院"])
    service.adjust_cluster(cluster.cluster_id, "r", "绑定",
                           business_metric_code="djxx.hospital_level")
    service.decide(cluster.cluster_id, DecisionAction.ACCEPT_FULL_PLAN, "reviewer",
                   reason="单源补裁决理由")
    activation = service.execute_activation(cluster.cluster_id, "reviewer", _ports())
    assert activation.status.value == "failed"
    assert activation.failed_step == "semantic_assets"


def test_activation_requires_accepted_status():
    service = PdscService(_registry(), InMemoryPdscStore(), FakeCorpus())
    cluster = service.intake_signal(_signal("t1"), policy_values=["三级医院"])
    with pytest.raises(ValueError, match="只能激活"):
        service.execute_activation(cluster.cluster_id, "reviewer", _ports())


def test_policy_only_activation_skips_skill_verification():
    records = [PolicyUnitEvidence(doc_id="doc_1", unit_id="u1", excerpt="原文",
                                  found_values=["三级医院"], concept_matched=True)]
    service = PdscService(_registry(), InMemoryPdscStore(), FakeCorpus(records))
    cluster = service.intake_signal(_signal("t1"), policy_values=["三级医院"])
    service.decide(cluster.cluster_id, DecisionAction.POLICY_ONLY, "reviewer")
    activation = service.execute_activation(cluster.cluster_id, "reviewer", _ports())
    assert activation.status.value == "succeeded"
    assert "skill_verification" not in [s.step for s in activation.steps]
    assert service.list_relations() == []  # policy_only 不建关系（§13.9）


def test_default_reextractor_passes_without_docs(monkeypatch):
    """无受影响文档时重提取平凡通过，不被 MODEL_API_KEY 拦截。"""
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    from src.knowledge_extension.rule_explanation.pdsc import _NoopReextractor

    outcome = _NoopReextractor().reextract_docs([])
    assert outcome["passed"] is True


def test_activation_records_unexpected_exceptions():
    """非 ValueError 异常也落激活记录（不丢状态），不改活动版本。"""
    class ExplodingReextractor:
        def reextract_docs(self, doc_ids):
            raise RuntimeError("orchestrator crashed")

    service = PdscService(_registry(), InMemoryPdscStore(), FakeCorpus())
    cluster = _accepted_cluster(service)
    activation = service.execute_activation(cluster.cluster_id, "reviewer", ActivationPorts(
        reextractor=ExplodingReextractor(), compile_checker=StubCompileChecker(),
    ))
    assert activation.status.value == "failed"
    assert activation.error == "orchestrator crashed"
    assert service.list_relations()[0].status == "draft"
