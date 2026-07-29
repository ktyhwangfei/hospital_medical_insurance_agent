"""P8.4 长文档分片提取测试。

长文档（如 9000+ 字政策细则）全文提取时，LLM 输出的 JSON 会超 max_tokens
被截断（finish_reason=length）。解法：按段落分片，逐片提取后合并 facts，
每片输出可控、不截断、不超时。

依据：docs/steering/政策知识管线开发计划.md P8.4。
"""
from __future__ import annotations

from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
    PipelineOrchestrator,
)


def test_split_text_short_returns_single_chunk():
    """短文本（<= 片长）不切分，原样返回单片。"""
    orch = PipelineOrchestrator()
    assert orch._split_text("短文本") == ["短文本"]


def test_split_text_long_splits_into_multiple_chunks():
    """长文本按段落切分为多片，每片不超过片长（段落粒度）。"""
    orch = PipelineOrchestrator()
    # 10 段 × ~300 字 ≈ 3000 字，超过默认片长 1500
    text = "\n".join(f"段{i}：" + "政" * 300 for i in range(10))
    chunks = orch._split_text(text)
    assert len(chunks) > 1
    # 每片不超片长 + 一个段落的容差
    assert all(len(c) <= 2000 for c in chunks)


def test_split_text_no_content_loss():
    """切分不丢内容：所有片拼接后字符数不少于原文（去换行）。"""
    orch = PipelineOrchestrator()
    text = "\n".join(f"段{i}：" + "政" * 300 for i in range(10))
    chunks = orch._split_text(text)
    joined = "".join(chunks)
    original_no_newline = text.replace("\n", "")
    # 容差 = 切分引入的换行差异
    assert len(joined) >= len(original_no_newline) - len(chunks)


def test_split_text_respects_paragraph_boundary():
    """按段落切分，不在段落中间断裂（完整性）。"""
    orch = PipelineOrchestrator()
    para = "不可在中间切断的完整政策段落内容"
    text = "\n".join([para] * 30)
    chunks = orch._split_text(text, max_len=len(para) * 2)
    for c in chunks:
        # 若出现段落开头片段，则该段落必须完整存在于片中
        assert para[:5] not in c or para in c
