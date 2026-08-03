from __future__ import annotations

from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
    PipelineOrchestrator,
)


def test_coverage_empty_document_returns_zero():
    cov = PipelineOrchestrator._calculate_coverage("")
    assert cov == {"ratio": 0, "kept_units": 0, "total_units": 0}


def test_coverage_normal_policy_doc_is_full():
    """正常政策文档结构拆分无遗漏，去重产出率应为 1.0。

    覆盖率语义 = kept_units / all_units（结构单元产出率），与 LLM 事实无关。
    """
    text = (
        "第一条 根据《北京市城乡居民基本医疗保险办法》制定本实施细则。\n"
        "第二条 参保人员在定点医疗机构发生的住院医疗费用，起付标准为1300元。\n"
        "第三条 起付标准以上至3万元的部分，统筹基金支付85%。"
    )
    cov = PipelineOrchestrator._calculate_coverage(text, "测试细则")
    assert cov["total_units"] > 0
    assert cov["kept_units"] == cov["total_units"], "正常文档去重后应无单元丢失"
    assert cov["ratio"] == 1.0


def test_coverage_returns_unit_counts():
    cov = PipelineOrchestrator._calculate_coverage("第一条 测试内容。", "测试")
    assert set(cov.keys()) == {"ratio", "kept_units", "total_units"}
    assert 0 <= cov["ratio"] <= 1.0
    assert cov["kept_units"] <= cov["total_units"]
