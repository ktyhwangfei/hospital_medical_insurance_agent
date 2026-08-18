"""SkillInputService 单元测试（P4）。

用 FakeRegistry 测试输入指标校验门禁、查询计划、选择器树。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.domain.skill.draft_models import (
    InputSpec,
    MetricResolutionType,
    MetricUnavailableReason,
)
from src.runtime.skill_management.skill_input_service import SkillInputService


def _metric(
    code: str,
    *,
    object_code="zydyxx",
    status="published",
    adapter="InsuranceInterfacePort",
    field="t.col",
    default=None,
    importance="core",
):
    return SimpleNamespace(
        metric_code=code,
        object_code=object_code,
        name=code,
        definition="d",
        status=status,
        source_adapter_port=adapter,
        source_field=field,
        default_value=default,
        importance=importance,
        quality_score=0.9,
        usage_count=1,
        unit=None,
        semantic_type="Amount",
    )


def _object(code="zydyxx", *, status="published", current_version="1"):
    return SimpleNamespace(
        object_code=code,
        domain_code="settle",
        name="住院待遇",
        definition="d",
        status=status,
        current_version=current_version,
    )


class FakeRegistry:
    """实现 SkillInputService 所需的 registry 子集。"""

    def __init__(self, metrics: dict[str, SimpleNamespace], objects: dict[str, SimpleNamespace]):
        self._metrics = metrics
        self._objects = objects

    def get_metric(self, code):
        return self._metrics.get(code)

    def get_object(self, code):
        return self._objects.get(code)

    def list_metrics(self, object_code=None):
        ms = list(self._metrics.values())
        return [m for m in ms if object_code is None or m.object_code == object_code]

    def list_objects(self, domain_code=None):
        return list(self._objects.values())

    def list_domains(self):
        return [SimpleNamespace(domain_code="settle", name="结算域")]


def _registry():
    return FakeRegistry(
        metrics={
            "zydyxx.bcqfje": _metric("zydyxx.bcqfje"),
            "zydyxx.constant": _metric("zydyxx.constant", adapter=None, field=None, default="X"),
            "zydyxx.draft": _metric("zydyxx.draft", status="draft"),
            "zydyxx.noimpl": _metric("zydyxx.noimpl", adapter=None, field=None, default=None),
            "zydyxx.nofield": _metric("zydyxx.nofield", adapter="X", field="", default=None),
        },
        objects={"zydyxx": _object()},
    )


# ── 校验门禁 ──────────────────────────────────────────────────────


def test_validate_published_structured_metric_passes():
    svc = SkillInputService(_registry())
    report = svc.validate_inputs([InputSpec(metric_code="zydyxx.bcqfje")])
    assert report.blocking_ok


def test_validate_constant_metric_passes():
    svc = SkillInputService(_registry())
    report = svc.validate_inputs([InputSpec(metric_code="zydyxx.constant")])
    assert report.blocking_ok


def test_validate_metric_not_found_blocking():
    svc = SkillInputService(_registry())
    report = svc.validate_inputs([InputSpec(metric_code="missing.x")])
    assert "METRIC_NOT_FOUND" in [i.code for i in report.issues]
    assert not report.blocking_ok


def test_validate_metric_not_published_blocking():
    svc = SkillInputService(_registry())
    report = svc.validate_inputs([InputSpec(metric_code="zydyxx.draft")])
    assert "METRIC_NOT_PUBLISHED" in [i.code for i in report.issues]


def test_validate_no_query_implementation_blocking():
    svc = SkillInputService(_registry())
    report = svc.validate_inputs([InputSpec(metric_code="zydyxx.noimpl")])
    assert "OBJECT_NO_QUERY_IMPLEMENTATION" in [i.code for i in report.issues]


def test_validate_structured_no_field_blocking():
    svc = SkillInputService(_registry())
    report = svc.validate_inputs([InputSpec(metric_code="zydyxx.nofield")])
    assert "STRUCTURED_METRIC_NO_FIELD_MAPPING" in [i.code for i in report.issues]


def test_validate_duplicate_input_blocking():
    svc = SkillInputService(_registry())
    report = svc.validate_inputs(
        [InputSpec(metric_code="zydyxx.bcqfje"), InputSpec(metric_code="zydyxx.bcqfje")]
    )
    assert "DUPLICATE_INPUT" in [i.code for i in report.issues]


def test_validate_optional_metric_failure_still_reported():
    # 可选指标的 blocking 问题仍报告（设计：必填失败阻止执行，可选记 uncertainties；
    # 校验门禁阶段两者都需可见，blocking 由调用方按 required 解读）
    svc = SkillInputService(_registry())
    report = svc.validate_inputs(
        [InputSpec(metric_code="zydyxx.noimpl", required=False)]
    )
    assert any(i.code == "OBJECT_NO_QUERY_IMPLEMENTATION" for i in report.issues)


# ── 查询计划 ──────────────────────────────────────────────────────


def test_query_plan_groups_by_object():
    svc = SkillInputService(_registry())
    plan = svc.build_query_plan(
        [
            InputSpec(metric_code="zydyxx.bcqfje", alias="deductible"),
            InputSpec(metric_code="zydyxx.constant"),
        ]
    )
    assert len(plan) == 1
    group = plan[0]
    assert group["object_code"] == "zydyxx"
    assert group["source_type"] in {"structured", "constant", "policy_or_external"}
    codes = {m["metric_code"] for m in group["metrics"]}
    assert codes == {"zydyxx.bcqfje", "zydyxx.constant"}


def test_query_plan_unknown_metric_grouped():
    svc = SkillInputService(_registry())
    plan = svc.build_query_plan([InputSpec(metric_code="missing.x")])
    assert plan[0]["source_type"] == "unknown"
    assert plan[0]["metrics"][0]["available"] is False


# ── 选择器树 ──────────────────────────────────────────────────────


def test_selector_tree_structure():
    svc = SkillInputService(_registry())
    tree = svc.input_selector_tree()
    assert len(tree) == 1
    domain = tree[0]
    assert domain["domain_code"] == "settle"
    assert len(domain["objects"]) == 1
    obj = domain["objects"][0]
    assert obj["object_code"] == "zydyxx"
    assert len(obj["metrics"]) == 5
    metric = obj["metrics"][0]
    assert "source_type" in metric
    assert "status" in metric


# ── 样例取数 ──────────────────────────────────────────────────────


def test_test_query_returns_dict():
    svc = SkillInputService(_registry())
    result = svc.test_query([InputSpec(metric_code="zydyxx.bcqfje")])
    assert "ok" in result
    assert "facts" in result


# ── runtime_resolvable 统一判定（执行契约 §11-§14）──────────────


def _registry_with_unpublished_object():
    """含一个对象 current_version=None（未发布）。"""
    return FakeRegistry(
        metrics={
            "zydyxx.bcqfje": _metric("zydyxx.bcqfje"),
            "zydyxx.constant": _metric("zydyxx.constant", adapter=None, field=None, default="X"),
        },
        objects={
            "zydyxx": _object(),
            "unpub": _object(code="unpub", current_version=None),
        },
    )


def test_capability_resolvable_source_field():
    svc = SkillInputService(_registry())
    m = _metric("zydyxx.bcqfje")
    obj = _object()
    cap = svc.resolve_metric_capability(m, obj)
    assert cap.runtime_resolvable is True
    assert cap.resolution_type == MetricResolutionType.SOURCE_FIELD
    assert cap.unavailable_reason is None


def test_capability_resolvable_default_value():
    svc = SkillInputService(_registry())
    m = _metric("zydyxx.constant", adapter=None, field=None, default="X")
    cap = svc.resolve_metric_capability(m, _object())
    assert cap.runtime_resolvable is True
    assert cap.resolution_type == MetricResolutionType.DEFAULT_VALUE


def test_capability_not_published():
    svc = SkillInputService(_registry())
    m = _metric("zydyxx.draft", status="draft")
    cap = svc.resolve_metric_capability(m, _object())
    assert cap.runtime_resolvable is False
    assert cap.unavailable_reason == MetricUnavailableReason.NOT_PUBLISHED


def test_capability_object_not_published():
    svc = SkillInputService(_registry_with_unpublished_object())
    m = _metric("unpub.field", object_code="unpub")
    obj = _object(code="unpub", current_version=None)
    cap = svc.resolve_metric_capability(m, obj)
    assert cap.runtime_resolvable is False
    assert cap.unavailable_reason == MetricUnavailableReason.OBJECT_NOT_PUBLISHED


def test_capability_no_runtime_resolver():
    svc = SkillInputService(_registry())
    m = _metric("zydyxx.noimpl", adapter=None, field=None, default=None)
    cap = svc.resolve_metric_capability(m, _object())
    assert cap.runtime_resolvable is False
    assert cap.unavailable_reason == MetricUnavailableReason.NO_RUNTIME_RESOLVER


def test_capability_invalid_mapping():
    svc = SkillInputService(_registry())
    m = _metric("zydyxx.nofield", adapter="X", field="", default=None)
    cap = svc.resolve_metric_capability(m, _object())
    assert cap.runtime_resolvable is False
    assert cap.unavailable_reason == MetricUnavailableReason.INVALID_MAPPING


# ── get_runtime_resolvable_metrics（§38 AI 推荐输入集合）─────────


def test_resolvable_metrics_excludes_unresolvable():
    svc = SkillInputService(_registry())
    # _registry 含 5 个指标，仅 bcqfje 和 constant resolvable
    resolvable = svc.get_runtime_resolvable_metrics()
    codes = {m["metric_code"] for m in resolvable}
    assert "zydyxx.bcqfje" in codes
    assert "zydyxx.constant" in codes
    # draft / noimpl / nofield 不可解析，不出现
    assert "zydyxx.draft" not in codes
    assert "zydyxx.noimpl" not in codes
    assert "zydyxx.nofield" not in codes


def test_resolvable_metrics_payload_shape():
    svc = SkillInputService(_registry())
    resolvable = svc.get_runtime_resolvable_metrics()
    target = next(m for m in resolvable if m["metric_code"] == "zydyxx.bcqfje")
    assert target["runtime_resolvable"] is True
    assert target["resolution_type"] == "SOURCE_FIELD"
    assert target["unavailable_reason"] is None
    assert target["business_object"] == "zydyxx"


# ── 选择器树增强字段（§34）───────────────────────────────────────


def test_selector_tree_metric_has_runtime_resolvable_fields():
    svc = SkillInputService(_registry())
    tree = svc.input_selector_tree()
    metrics = tree[0]["objects"][0]["metrics"]
    # 每个指标节点都应含三字段
    for m in metrics:
        assert "runtime_resolvable" in m
        assert "resolution_type" in m
        assert "unavailable_reason" in m


def test_selector_tree_resolvable_metric_marked_true():
    svc = SkillInputService(_registry())
    tree = svc.input_selector_tree()
    by_code = {
        m["metric_code"]: m for m in tree[0]["objects"][0]["metrics"]
    }
    assert by_code["zydyxx.bcqfje"]["runtime_resolvable"] is True
    assert by_code["zydyxx.bcqfje"]["resolution_type"] == "SOURCE_FIELD"
    assert by_code["zydyxx.constant"]["runtime_resolvable"] is True
    assert by_code["zydyxx.constant"]["resolution_type"] == "DEFAULT_VALUE"


def test_selector_tree_unresolvable_metric_marked_false_with_reason():
    svc = SkillInputService(_registry())
    tree = svc.input_selector_tree()
    by_code = {
        m["metric_code"]: m for m in tree[0]["objects"][0]["metrics"]
    }
    assert by_code["zydyxx.draft"]["runtime_resolvable"] is False
    assert by_code["zydyxx.draft"]["unavailable_reason"] == "NOT_PUBLISHED"
    assert by_code["zydyxx.noimpl"]["runtime_resolvable"] is False
    assert by_code["zydyxx.noimpl"]["unavailable_reason"] == "NO_RUNTIME_RESOLVER"
