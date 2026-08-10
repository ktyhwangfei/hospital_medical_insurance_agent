"""ExtractionOverride 模型校验测试（迭代 18 S1）。

重提取覆盖配置：提示词模式（schema/legacy/custom）、自定义提示词、模型覆盖、
最大 tokens、操作人。frozen 不可变；custom 模式必须带非空 custom_prompt。
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.knowledge_extension.rule_explanation.knowledge_build_models import (
    ExtractionOverride,
)


def test_extraction_override_defaults_all_none():
    """不传任何字段 → 全部 None（等同默认行为：schema 提示词 + 默认模型路由）。"""
    ov = ExtractionOverride()
    assert ov.prompt_mode is None
    assert ov.custom_prompt is None
    assert ov.model_name is None
    assert ov.max_tokens is None
    assert ov.operator is None


def test_extraction_override_custom_requires_prompt():
    """custom 模式必须带非空 custom_prompt（否则无意义）。"""
    with pytest.raises(ValidationError):
        ExtractionOverride(prompt_mode="custom")
    with pytest.raises(ValidationError):
        ExtractionOverride(prompt_mode="custom", custom_prompt="   ")


def test_extraction_override_custom_accepts_nonblank_prompt():
    ov = ExtractionOverride(prompt_mode="custom", custom_prompt="自定义提示词")
    assert ov.prompt_mode == "custom"
    assert ov.custom_prompt == "自定义提示词"


def test_extraction_override_schema_and_legacy_modes_need_no_prompt():
    """schema / legacy 模式不需要 custom_prompt（由系统构建提示词）。"""
    assert ExtractionOverride(prompt_mode="schema").prompt_mode == "schema"
    assert ExtractionOverride(prompt_mode="legacy").prompt_mode == "legacy"


def test_extraction_override_is_frozen():
    """frozen=True：实例不可变（与 CreateKnowledgeBuildTaskRequest 一致）。"""
    ov = ExtractionOverride(model_name="deepseek-chat")
    with pytest.raises(ValidationError):
        ov.model_name = "other-model"  # type: ignore[misc]


def test_extraction_override_max_tokens_and_operator_optional():
    ov = ExtractionOverride(
        model_name="deepseek-chat",
        max_tokens=4096,
        operator="reviewer-001",
    )
    assert ov.max_tokens == 4096
    assert ov.operator == "reviewer-001"
