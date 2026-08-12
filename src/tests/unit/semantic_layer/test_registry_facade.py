"""SemanticRegistry facade 回归测试。

SkillInputService.input_selector_tree() 经真实 SemanticRegistry 调用
list_domains()。facade 曾遗漏 list_domains 委托（store/Protocol 均有），
导致 /semantic/skill-inputs/selector 端点 500，前端"已发布输入指标"加载失败。
单测若用 FakeRegistry 永远绿，测不到此缺口——必须用真实 SemanticRegistry。
"""

from __future__ import annotations

from src.semantic_layer.models import BusinessDomain
from src.semantic_layer.registry import create_registry


def test_list_domains_delegates_to_store():
    reg = create_registry(use_memory=True)
    reg._store.save_domain(BusinessDomain(domain_code="d1", name="域1"))  # noqa: SLF001
    domains = reg.list_domains()
    assert [d.domain_code for d in domains] == ["d1"]
