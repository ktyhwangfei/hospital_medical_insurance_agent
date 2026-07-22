"""A-轻：assembler 版本准入守卫测试（阶段3 锁定对 skill 生效）。"""
import pytest

import src.semantic_layer.registry as reg_mod
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer
from skills.settlement_explain_skill.assembler import BenefitPoolingSelfPayAssembler


@pytest.fixture
def assembler_with_registry(monkeypatch):
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    reg = SemanticRegistry(store)
    # assembler._verify_skill_dependencies 内部 from ...registry import get_semantic_registry，
    # monkeypatch 模块属性后每次调用都会取到内存 registry。
    monkeypatch.setattr(reg_mod, "get_semantic_registry", lambda: reg)
    return BenefitPoolingSelfPayAssembler(), reg


class TestSkillVersionGuard:
    def test_unpublished_objects_warn(self, assembler_with_registry):
        """所有依赖对象未发布 → warnings 含每个对象的未发布提示。"""
        assembler, _ = assembler_with_registry
        warnings = assembler._verify_skill_dependencies()
        # _FACT_FIELD_MAP 涉及 zydyxx/zyfdxx/zyjyxx/djxx，seed 后全未发布
        assert any("zydyxx" in w and "未发布" in w for w in warnings)
        assert any("zyfdxx" in w and "未发布" in w for w in warnings)
        assert any("djxx" in w and "未发布" in w for w in warnings)

    def test_published_objects_pass(self, assembler_with_registry):
        """发布所有依赖对象 → 无版本守卫警告。"""
        assembler, reg = assembler_with_registry
        for obj in ["zydyxx", "zyfdxx", "zyjyxx", "djxx"]:
            reg.publish_object(obj)
        assert assembler._verify_skill_dependencies() == []

    def test_partial_publish_warns_only_missing(self, assembler_with_registry):
        """部分发布 → 仅未发布的对象告警。"""
        assembler, reg = assembler_with_registry
        reg.publish_object("zydyxx")
        warnings = assembler._verify_skill_dependencies()
        assert any("zyfdxx" in w and "未发布" in w for w in warnings)
        assert not any("zydyxx" in w for w in warnings)  # zydyxx 已发布不告警
