"""提取截断自适应测试：输出被 max_tokens 截断时对半细分重提取。

线上场景：便民待遇表格页 803 字 1 片 → 模型输出 25858 字符被截断 → JSON 解析失败。
分片防截断是既有设计意图（_split_text 注释），缺的只是粒度自适应。
"""
from __future__ import annotations


def test_extract_facts_rechops_chunk_on_truncation(monkeypatch):
    from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
        PipelineOrchestrator,
    )

    o = PipelineOrchestrator.__new__(PipelineOrchestrator)
    calls: list[str] = []

    class FakeResp:
        def __init__(self, content, finish):
            self.content = content
            self.finish_reason = finish

    # 短路 prompt 模板：桩直接以传入原文长度判定是否截断
    monkeypatch.setattr(
        o, "_build_fact_extraction_prompt", lambda text, title, override=None: text,
    )

    class FakeGateway:
        def generate(self, messages, model_type, scene, max_tokens=None, **kw):
            text = messages[0].content
            calls.append(text)
            if len(text) > 300:
                return FakeResp('[{"fact_text": "在职职工门诊起付18', "length")
            return FakeResp('[{"fact_text": "短片段事实"}]', "stop")

    monkeypatch.setattr(
        "src.knowledge_extension.rule_explanation.pipeline_orchestrator.ModelGateway",
        lambda: FakeGateway(),
    )
    facts = o._extract_policy_facts_adaptive(
        "A" * 600 + "\n" + "B" * 400, "测试", min_chunk=150,
    )
    assert facts and facts[0]["fact_text"] == "短片段事实"
    assert len(calls) > 1, "长片截断后必须细分重试"


def test_adaptive_extracts_both_halves(monkeypatch):
    """对半细分后两半都要提取，不得丢弃后半（线上丢失住院表）。"""
    from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
        PipelineOrchestrator,
    )

    o = PipelineOrchestrator.__new__(PipelineOrchestrator)
    monkeypatch.setattr(
        o, "_build_fact_extraction_prompt", lambda text, title, override=None: text,
    )

    class FakeResp:
        def __init__(self, content, finish):
            self.content = content
            self.finish_reason = finish

    class FakeGateway:
        def generate(self, messages, *a, **kw):
            text = messages[0].content
            if len(text) > 300:  # 长片截断
                return FakeResp('[{"fact_text": "trunc', "length")
            # 短片：按内容开头标识返回对应事实，两半可区分
            marker = text[:10]
            return FakeResp(
                json.dumps([{"fact_text": f"事实-{marker}"}]), "stop",
            )

    monkeypatch.setattr(
        "src.knowledge_extension.rule_explanation.pipeline_orchestrator.ModelGateway",
        lambda: FakeGateway(),
    )
    import json
    facts = o._extract_policy_facts_adaptive(
        "门诊段" + "A" * 400 + "\n" + "住院段" + "B" * 400, "测试", min_chunk=150,
    )
    texts = {f["fact_text"] for f in facts}
    assert any("门诊段" in t for t in texts), "前半事实必须保留"
    assert any("住院段" in t for t in texts), "后半事实不得丢弃"

    """细分到下限仍截断：拋提取错误而不是死循环。"""
    from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
        PipelineOrchestrator,
        PolicyFactExtractionError,
    )

    o = PipelineOrchestrator.__new__(PipelineOrchestrator)
    monkeypatch.setattr(
        o, "_build_fact_extraction_prompt", lambda text, title, override=None: text,
    )

    class FakeResp:
        content = '[{"fact_text": "trunc'
        finish_reason = "length"

    class FakeGateway:
        def generate(self, *a, **kw):
            return FakeResp()

    monkeypatch.setattr(
        "src.knowledge_extension.rule_explanation.pipeline_orchestrator.ModelGateway",
        lambda: FakeGateway(),
    )
    import pytest
    with pytest.raises(PolicyFactExtractionError):
        o._extract_policy_facts_adaptive("X" * 500, "测试", min_chunk=150)


def test_adaptive_stops_at_min_chunk(monkeypatch):
    """细分到下限仍截断：抛提取错误而不是死循环。"""
    from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
        PipelineOrchestrator,
        PolicyFactExtractionError,
    )

    o = PipelineOrchestrator.__new__(PipelineOrchestrator)
    monkeypatch.setattr(
        o, "_build_fact_extraction_prompt", lambda text, title, override=None: text,
    )

    class FakeResp:
        content = '[{"fact_text": "trunc'
        finish_reason = "length"

    class FakeGateway:
        def generate(self, *a, **kw):
            return FakeResp()

    monkeypatch.setattr(
        "src.knowledge_extension.rule_explanation.pipeline_orchestrator.ModelGateway",
        lambda: FakeGateway(),
    )
    import pytest
    with pytest.raises(PolicyFactExtractionError):
        o._extract_policy_facts_adaptive("X" * 500, "测试", min_chunk=150)
