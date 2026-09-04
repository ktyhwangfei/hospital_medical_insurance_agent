"""Phase ⑤ Step 1 单测：值域转换（码→标签）+ 医保字典 ensure。

锁住两条纯逻辑：
1. ensure_yb_dictionary_mappings 幂等注入 FUND_TYPE/YLLB/PERSON_TYPE 码→标签映射
2. SemanticDataSource._apply_value_domains 对声明 value_domain 的指标做转换
"""
import pytest

from src.semantic_layer.registry import SemanticRegistry, InMemoryRegistryStore
from src.semantic_layer.seed import ensure_yb_dictionary_mappings
from src.semantic_layer.models import Metric


# ── ensure_yb_dictionary_mappings ────────────────────────────────

@pytest.fixture
def store_with_dicts():
    store = InMemoryRegistryStore()
    ensure_yb_dictionary_mappings(store)
    return store


def test_ensure_creates_yllb_domain(store_with_dicts):
    """YLLB 值域及其码→标签映射应被注入。"""
    vd = store_with_dicts.get_value_domain("YLLB")
    assert vd is not None
    assert vd.name == "医疗类别"
    # 码 21 → 普通住院（从历史 SQL CASE 迁移）
    reg = SemanticRegistry(store_with_dicts)
    assert reg.resolve_value("YLLB", "21") == "普通住院"
    assert reg.resolve_value("YLLB", "11") == "普通门诊"


def test_ensure_creates_fund_type_mappings(store_with_dicts):
    """FUND_TYPE 码→标签映射应齐全（与 business_sql CASE 一致）。"""
    reg = SemanticRegistry(store_with_dicts)
    assert reg.resolve_value("FUND_TYPE", "3") == "城镇职工"
    assert reg.resolve_value("FUND_TYPE", "31") == "离休统筹"


def test_ensure_person_type_code_mappings(store_with_dicts):
    """PERSON_TYPE 应含 PER_TYPE 原始码→中文标签（1→在职人员 等）。"""
    reg = SemanticRegistry(store_with_dicts)
    assert reg.resolve_value("PERSON_TYPE", "1") == "在职人员"
    assert reg.resolve_value("PERSON_TYPE", "2") == "退休人员"
    assert reg.resolve_value("MZ_PERSON_TYPE", "175") == "退休高端人才A类"
    assert reg.resolve_value("MZ_CURE_TYPE", "19") == "普通急诊"
    assert reg.resolve_value("MILITARY_DISABILITY_LEVEL", "3") == "享受三级伤残待遇"


def test_ensure_is_idempotent(store_with_dicts):
    """重复调用 ensure 不应报错，映射不变（幂等 upsert 语义）。"""
    before = SemanticRegistry(store_with_dicts).resolve_value("YLLB", "21")
    ensure_yb_dictionary_mappings(store_with_dicts)  # 再跑一次
    after = SemanticRegistry(store_with_dicts).resolve_value("YLLB", "21")
    assert before == after == "普通住院"


def test_resolve_unmapped_code_passthrough(store_with_dicts):
    """未映射的码（如测试数据 410）原样返回，不报错。"""
    reg = SemanticRegistry(store_with_dicts)
    assert reg.resolve_value("FUND_TYPE", "410") == "410"


# ── _apply_value_domains（纯转换逻辑，mock registry）──────────────

class _FakeMetric:
    """轻量假指标，仅含 value_domain 与必要属性。"""
    def __init__(self, value_domain):
        self.value_domain = value_domain


class _FakeRegistry:
    """假 registry：resolve_value 走内存映射；get_metric 返回 _FakeMetric。"""
    def __init__(self):
        self._maps = {
            "YLLB": {"21": "普通住院", "11": "普通门诊"},
            "FUND_TYPE": {"3": "城镇职工"},
        }
        self._metric_domains = {"m.yllb": "YLLB", "m.fund": "FUND_TYPE", "m.amount": None}

    def get_metric(self, code):
        return _FakeMetric(self._metric_domains.get(code))

    def resolve_value(self, domain_code, source_value):
        return self._maps.get(domain_code, {}).get(source_value, source_value)


def _make_source():
    """构造 SemanticDataSource 但替换 registry 为假实现。"""
    from src.runtime.discovery.semantic_source import SemanticDataSource
    src = SemanticDataSource.__new__(SemanticDataSource)
    src._registry = _FakeRegistry()
    return src


def test_apply_value_domains_transforms_enum():
    """声明 value_domain 的枚举指标应被转为标准标签。"""
    src = _make_source()
    results = {"m.yllb": "21", "m.fund": "3", "m.amount": 1000.0}
    src._apply_value_domains(["m.yllb", "m.fund", "m.amount"], results)
    assert results["m.yllb"] == "普通住院"
    assert results["m.fund"] == "城镇职工"
    assert results["m.amount"] == 1000.0  # 非枚举不变


def test_apply_value_domains_skips_none():
    """None 值不应触发转换（避免无意义查找）。"""
    src = _make_source()
    results = {"m.yllb": None}
    src._apply_value_domains(["m.yllb"], results)
    assert results["m.yllb"] is None
