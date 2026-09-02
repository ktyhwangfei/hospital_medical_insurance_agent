"""PDSC 政策过滤桥测试（§10.3 下游消费）。"""
from __future__ import annotations

from src.knowledge_extension.rule_explanation.pdsc import (
    InMemoryPdscStore,
    PdscService,
    PolicyApplicabilityRelation,
    RelationValueMappingItem,
)
from src.runtime.policy_qa.pdsc_filter_bridge import build_pdsc_filters
from src.tests.unit.knowledge_extension.test_pdsc_phase2 import _registry


class FakeCorpus:
    def find_unit_evidence(self, concept, aliases, values):
        return []


class _BrokenService:
    def resolve_policy_filters(self, metric_code, value):
        raise RuntimeError("pdsc down")


def test_bridge_without_resolvable_service_returns_empty() -> None:
    # 服务异常 → 空 dict，检索行为与旧路径一致（不阻断政策问答）
    assert build_pdsc_filters({"hosp_lv": "三级医院"}, _BrokenService()) == {}


def test_bridge_resolves_published_relation() -> None:
    service = PdscService(_registry(), InMemoryPdscStore(), FakeCorpus())
    service._store.save_relation(PolicyApplicabilityRelation(
        relation_id="par_test",
        policy_metric_code="zcgz.hosp_lv",
        business_metric_code="djxx.hospital_level",
        value_mappings=[RelationValueMappingItem(
            policy_value="三级医院", business_values=["三级医院", "三级"],
        )],
        source_cluster_id="sdc_x", status="published",
    ))

    # 业务原始值（非政策标准值）经关系转换为政策条件值
    assert build_pdsc_filters({"hosp_lv": "三级"}, service) == {"hosp_lv": "三级医院"}
    # 未映射值 → 不产生过滤
    assert build_pdsc_filters({"hosp_lv": "未知"}, service) == {}
    # 空上下文 → 空
    assert build_pdsc_filters({}, service) == {}


def test_draft_relation_not_consumed() -> None:
    service = PdscService(_registry(), InMemoryPdscStore(), FakeCorpus())
    service._store.save_relation(PolicyApplicabilityRelation(
        relation_id="par_draft",
        policy_metric_code="zcgz.hosp_lv",
        business_metric_code="djxx.hospital_level",
        value_mappings=[RelationValueMappingItem(
            policy_value="三级医院", business_values=["三级"],
        )],
        source_cluster_id="sdc_x", status="draft",
    ))
    assert build_pdsc_filters({"hosp_lv": "三级"}, service) == {}


def test_service_init_failure_returns_empty(monkeypatch) -> None:
    """PDSC 初始化失败不得阻断政策问答（信任边界）。"""
    import src.knowledge_extension.rule_explanation.pdsc as pdsc_mod

    def _boom():
        raise RuntimeError("pg down")

    monkeypatch.setattr(pdsc_mod, "get_pdsc_service", _boom)
    assert build_pdsc_filters({"hosp_lv": "三级医院"}) == {}
