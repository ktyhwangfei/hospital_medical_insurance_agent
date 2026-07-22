"""Tests for Business Facts Builder.

语义层编码统一后（zydyxx.* 物理编码），metric 的 source_field 为物理「表.列」，
Builder._extract_field 按点分层访问 adapter data；facts key 为 metric_code 短名。
"""
import pytest
from unittest.mock import MagicMock
from src.semantic_layer.models import (
    BusinessFactsRequest, ObjectMetricRequest, BusinessFactsResponse,
)
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer
from src.semantic_layer.builder import BusinessFactsBuilder


@pytest.fixture
def registry():
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    return SemanticRegistry(store)


@pytest.fixture
def mock_insurance_adapter():
    """mock adapter 返回嵌套 data，匹配 metric.source_field 的「表.列」结构。

    value_domain 字段（PER_TYPE/FUND_TYPE/yllb）给原始码，由 Builder 解析为标准值。
    """
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
            "yb_zyjyxx": {"PER_TYPE": "2"},      # 退休人员（PERSON_TYPE 解析）
            "yb_brdjxx": {"FUND_TYPE": "3", "yllb": "21"},  # 城镇职工 / 普通住院
        },
        "data_quality": type("Quality", (), {"value": "complete"})(),
    })()
    return adapter


class TestBuilderBasic:
    def test_build_single_object_facts(self, registry, mock_insurance_adapter):
        builders = {"InsuranceInterfacePort": mock_insurance_adapter}
        builder = BusinessFactsBuilder(registry, builders)
        request = BusinessFactsRequest(
            objects=[ObjectMetricRequest(
                object_code="zydyxx", metric_codes=["bcqfje", "bcybnje"])],
            context={"patient_id": "P001", "encounter_id": "E001"},
        )
        result = builder.build(request)
        assert isinstance(result, BusinessFactsResponse)
        assert "zydyxx" in result.facts
        assert result.facts["zydyxx"]["bcqfje"] == 1300
        assert result.facts["zydyxx"]["bcybnje"] == 35000

    def test_build_applies_value_domain(self, registry, mock_insurance_adapter):
        """Enum 指标经 value_domain 解析：PER_TYPE '2' → '退休人员'。"""
        builders = {"InsuranceInterfacePort": mock_insurance_adapter}
        builder = BusinessFactsBuilder(registry, builders)
        request = BusinessFactsRequest(
            objects=[ObjectMetricRequest(
                object_code="zyjyxx", metric_codes=["rylb"])],
            context={"patient_id": "P001", "encounter_id": "E001"},
        )
        result = builder.build(request)
        assert result.facts["zyjyxx"]["rylb"] == "退休人员"

    def test_build_missing_optional_metric_does_not_block(self, registry, mock_insurance_adapter):
        builders = {"InsuranceInterfacePort": mock_insurance_adapter}
        builder = BusinessFactsBuilder(registry, builders)
        request = BusinessFactsRequest(
            objects=[ObjectMetricRequest(
                object_code="zydyxx", metric_codes=["bcqfje", "nonexistent_field"])],
            context={"patient_id": "P001"},
        )
        result = builder.build(request)
        assert result.facts["zydyxx"]["bcqfje"] == 1300

    def test_adapters_called_with_context(self, registry, mock_insurance_adapter):
        builders = {"InsuranceInterfacePort": mock_insurance_adapter}
        builder = BusinessFactsBuilder(registry, builders)
        request = BusinessFactsRequest(
            objects=[ObjectMetricRequest(
                object_code="zydyxx", metric_codes=["bcqfje"])],
            context={"patient_id": "P001", "encounter_id": "E001", "settlement_id": "1671213"},
        )
        builder.build(request)
        mock_insurance_adapter.query_transaction.assert_called_once()
        call_args = mock_insurance_adapter.query_transaction.call_args
        assert call_args.kwargs.get("patient_id") == "P001"
        assert call_args.kwargs.get("encounter_id") == "E001"
