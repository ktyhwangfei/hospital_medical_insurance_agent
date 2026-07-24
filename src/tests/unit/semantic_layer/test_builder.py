"""Tests for Business Facts Builder.

语义层编码统一后（zydyxx.* 物理编码），metric 的 source_field 为物理「表.列」，
Builder._extract_field 按点分层访问 adapter data；facts key 为 metric_code 短名。
"""
import pytest
from unittest.mock import MagicMock
from src.semantic_layer.models import (
    BusinessFactsRequest, ObjectMetricRequest, BusinessFactsResponse,
    BusinessObject, Metric,
)
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer
from src.semantic_layer.builder import BusinessFactsBuilder


@pytest.fixture
def registry():
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    reg = SemanticRegistry(store)
    # 阶段3：get_metric_mapping 只读已发布版本，故预先发布测试涉及的对象
    reg.publish_object("zydyxx")
    reg.publish_object("zyjyxx")
    return reg


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

    def test_metric_without_source_adapter_port_warns_not_routes_to_default(self):
        """空 source_adapter_port 不应静默路由到 'default'，而应精确告警并跳过。

        回归 P0-3：原先 `port = metric.source_adapter_port or "default"` 会让
        未配置端口的指标悄悄走到名为 'default' 的适配器，可能拿到错来源的数据。
        修正后应 fail-fast：精确指出哪个 metric 缺端口配置。
        """
        store = InMemoryRegistryStore()
        store.save_object(BusinessObject(
            object_code="testobj", domain_code="test", name="测试对象",
            source_adapter_port=None,
        ))
        store.save_metric(Metric(
            metric_code="testobj.nomapping", object_code="testobj", name="无端口指标",
            source_adapter_port=None, default_value=None, importance="optional",
        ))
        reg = SemanticRegistry(store)
        reg.publish_object("testobj")

        builder = BusinessFactsBuilder(reg, {})  # 不注册任何 adapter
        result = builder.build(BusinessFactsRequest(
            objects=[ObjectMetricRequest(
                object_code="testobj", metric_codes=["nomapping"])],
            context={"patient_id": "P001"},
        ))

        # 不应出现误导性的 'default' 适配器告警
        assert not any("default" in w for w in result.meta.warnings), result.meta.warnings
        # 应精确指出该 metric 未配置端口
        assert any("nomapping" in w for w in result.meta.warnings), result.meta.warnings
        # facts 中不应出现该指标
        assert "nomapping" not in result.facts.get("testobj", {})

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


def test_publish_object_promotes_metric_status():
    """publish_object 发布对象时，metric.status 应同步 draft→published（契约读取的前置）。"""
    store = InMemoryRegistryStore()
    reg = SemanticRegistry(store)
    store.save_object(BusinessObject(object_code="t_pub", domain_code="d", name="测试"))
    store.save_metric(Metric(metric_code="t_pub.f1", object_code="t_pub", name="字段1"))
    assert store.list_metrics("t_pub")[0].status == "draft"  # 发布前 draft
    reg.publish_object("t_pub")
    assert store.list_metrics("t_pub")[0].status == "published"  # 发布后 published


def test_publish_object_rejects_empty_object():
    """空对象（无 metric）不能发布（§5：空指标不能发布）。"""
    store = InMemoryRegistryStore()
    reg = SemanticRegistry(store)
    store.save_object(BusinessObject(object_code="t_empty", domain_code="d", name="空对象"))
    with pytest.raises(ValueError, match="无.*指标|metric|空"):
        reg.publish_object("t_empty")
