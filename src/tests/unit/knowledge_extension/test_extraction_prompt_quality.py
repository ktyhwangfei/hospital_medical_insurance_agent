"""提取提示词质量增强测试（迭代 19，修改 5）。

背景：修改5 反馈典型失败案例——单元「（四）退休人员个人支付比例为
职工支付比例的60%」连 60% 关键数字、退休人员关键人群、与（一）单元的
跨单元引用关系都没提取出来。

根因：legacy 19 字段与 schema 提示词都**已含** psn_type / payment_ratio /
rule_value 字段，失败是**提取质量**而非字段缺口——提示词缺少对
①相对比例/系数 ②跨单元引用 ③关键人群强调 ④多条件拆条 的显式约束。

本测试：断言增强后的提示词（legacy + schema 两路真实模板）包含上述提取
约束，修复前应红（提示词无约束），修复后绿。
"""
from __future__ import annotations

from src.knowledge_extension.rule_explanation.knowledge_build_models import (
    ExtractionOverride,
)
from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
    PipelineOrchestrator,
)

# 修改5 典型失败单元：相对比例 + 关键人群 + 跨单元引用
RETIREE_UNIT_TEXT = "（四）退休人员个人支付比例为职工支付比例的60%。"
RETIREE_UNIT_TITLE = "北京市基本医疗保险规定 第四章 第三十六条"

# 增强后提示词必须包含的提取约束（针对修改5 三类失败）
EXPECTED_CONSTRAINTS = [
    "相对比例",   # ① 相对比例/系数（…的60%）
    "跨单元",     # ② 跨单元引用（职工支付比例 → 前款）
    "关键人群",   # ③ 人群强调（退休人员即使出现一次也要提取）
    "多条件",     # ④ 多条件拆条（一段多条件 → 多条规则）
]


def _assert_enhanced(prompt: str) -> None:
    for keyword in EXPECTED_CONSTRAINTS:
        assert keyword in prompt, f"提示词缺少提取约束: {keyword}"


def test_legacy_prompt_includes_extraction_quality_constraints() -> None:
    """legacy 19 字段提示词（当前运行路径，因 zcgz 指标未发布）必须含提取约束。"""
    orch = PipelineOrchestrator()
    prompt = orch._legacy_fact_extraction_prompt(RETIREE_UNIT_TEXT, RETIREE_UNIT_TITLE)
    _assert_enhanced(prompt)


def test_schema_prompt_includes_extraction_quality_constraints(monkeypatch) -> None:
    """schema 模式走真实 build_prompt_from_schema 模板，必须含提取约束。"""
    from src.semantic_layer import extraction_contract as ec
    from src.semantic_layer import registry as reg
    from src.semantic_layer.extraction_contract import ExtractionSchema, FieldContract

    schema = ExtractionSchema(
        fields=[FieldContract(code="payment_ratio", name="支付比例")]
    )
    monkeypatch.setattr(reg, "create_registry", lambda: object())
    monkeypatch.setattr(ec, "build_extraction_schema", lambda r, code: schema)

    orch = PipelineOrchestrator()
    prompt = orch._build_fact_extraction_prompt(
        RETIREE_UNIT_TEXT,
        RETIREE_UNIT_TITLE,
        ExtractionOverride(prompt_mode="schema"),
    )
    _assert_enhanced(prompt)


def test_custom_prompt_is_not_mutated_by_quality_constraints() -> None:
    """custom 模式完全由用户控制，系统不得追加提取约束。"""
    orch = PipelineOrchestrator()
    ov = ExtractionOverride(prompt_mode="custom", custom_prompt="请提取 {title} {text}")
    prompt = orch._build_fact_extraction_prompt("正文", "标题", ov)
    assert prompt == "请提取 标题 正文"
