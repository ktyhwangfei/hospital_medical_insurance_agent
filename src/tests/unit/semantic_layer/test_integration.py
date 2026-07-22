"""End-to-end integration test: Registry → Builder → Facts.

语义层编码统一后（zydyxx.* 物理编码），skill 声明的指标分散在多个对象
（zydyxx/zyfdxx/zyjyxx/djxx），Builder 跨对象聚合 facts。
"""
import pytest
from unittest.mock import MagicMock
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer
from src.semantic_layer.builder import BusinessFactsBuilder
from src.semantic_layer.models import BusinessFactsRequest, ObjectMetricRequest


@pytest.fixture
def full_chain():
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    registry = SemanticRegistry(store)
    adapter = MagicMock()
    adapter.query_transaction.return_value = type("Result", (), {
        "status": type("Status", (), {"value": "success"})(),
        "source_system": "insurance",
        "capability": "query_transaction",
        "data": {
            "yb_dyxxzy": {"bcqfje": 1300, "bcybnje": 35000},
            "yb_zyfdxx": {
                "bdtczfje": 28560, "bdtczf": 4520,
                "bddegwyzfje": 5000, "bddegwyzf": 800, "bdgryf": 5820,
            },
            "yb_zyjyxx": {"PER_TYPE": "2"},      # 退休人员
            "yb_brdjxx": {"FUND_TYPE": "3", "yllb": "21"},  # 城镇职工 / 普通住院
        },
        "data_quality": type("Quality", (), {"value": "complete"})(),
    })()
    builder = BusinessFactsBuilder(registry, {"InsuranceInterfacePort": adapter})
    return registry, builder


class TestFullChain:
    def test_settlement_explain_skill_facts(self, full_chain):
        """模拟 settlement_explain_skill 请求其声明的多对象指标。"""
        registry, builder = full_chain
        request = BusinessFactsRequest(
            objects=[
                ObjectMetricRequest(object_code="zydyxx", metric_codes=["bcqfje", "bcybnje"]),
                ObjectMetricRequest(object_code="zyfdxx",
                                    metric_codes=["bdtczfje", "bdtczf", "bdgryf"]),
                ObjectMetricRequest(object_code="zyjyxx", metric_codes=["rylb"]),
            ],
            context={"patient_id": "P001", "encounter_id": "E001", "settlement_id": "1671213"},
        )
        result = builder.build(request)
        assert result.facts["zydyxx"]["bcqfje"] == 1300
        assert result.facts["zyfdxx"]["bdtczfje"] == 28560
        assert result.facts["zyfdxx"]["bdtczf"] == 4520
        assert result.facts["zyfdxx"]["bdgryf"] == 5820
        assert result.facts["zyjyxx"]["rylb"] == "退休人员"
        assert result.meta.warnings == []

    def test_missing_core_metric_produces_warning(self, full_chain):
        """core required 指标在 adapter 数据中缺失时，应产生 warning。"""
        registry, builder = full_chain
        adapter = builder._adapter_builders["InsuranceInterfacePort"]
        # 只返回 zydyxx 数据，缺 zyfdxx（bdtczfje 为 core+required）
        adapter.query_transaction.return_value.data = {"yb_dyxxzy": {"bcqfje": 1300}}
        request = BusinessFactsRequest(
            objects=[
                ObjectMetricRequest(object_code="zydyxx", metric_codes=["bcqfje"]),
                ObjectMetricRequest(object_code="zyfdxx", metric_codes=["bdtczfje"]),
            ],
            context={"patient_id": "P001", "encounter_id": "E001"},
        )
        result = builder.build(request)
        assert "bcqfje" in result.facts["zydyxx"]
        assert len(result.meta.warnings) >= 1

    def test_multiple_objects_request(self, full_chain):
        """Builder 应处理对多个对象的请求。"""
        registry, builder = full_chain
        request = BusinessFactsRequest(
            objects=[
                ObjectMetricRequest(object_code="zydyxx", metric_codes=["bcqfje"]),
                ObjectMetricRequest(object_code="zyfdxx", metric_codes=["bdtczfje"]),
            ],
            context={"patient_id": "P001", "encounter_id": "E001"},
        )
        result = builder.build(request)
        assert "zydyxx" in result.facts
        assert "zyfdxx" in result.facts
        assert result.facts["zydyxx"]["bcqfje"] == 1300
