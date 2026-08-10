"""PipelineOrchestrator 提示词覆盖与重提取 override 测试（迭代 18 S1）。

覆盖三件事：
1. `_build_fact_extraction_prompt` 三模式（schema 实时读契约 / custom 自定义 / legacy 回退）。
2. `_extract_policy_facts` 把 override 透传给 gateway（model_override + max_tokens）。
3. `reextract_unit(extraction_id, override)` 调用链 + 审计字段 last_override。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.knowledge_extension.rule_explanation.knowledge_build_models import (
    ExtractionOverride,
)
from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
    PipelineOrchestrator,
)
from src.model_service.gateway import ModelGateway
from src.model_service.models import ModelResponse, TokenUsage


# ── _build_fact_extraction_prompt 三模式 ──────────────────────────


def test_build_prompt_custom_mode_replaces_placeholders():
    """custom 模式：用自定义文本，替换 {title}/{text} 占位符，不注入指标。"""
    orch = PipelineOrchestrator()
    ov = ExtractionOverride(prompt_mode="custom", custom_prompt="自定义|{title}|{text}")
    prompt = orch._build_fact_extraction_prompt("政策正文", "政策标题", ov)
    assert prompt == "自定义|政策标题|政策正文"


def test_build_prompt_custom_mode_without_override_is_schema_or_legacy():
    """不传 override → 默认 schema/legacy（必含原文，不抛异常）。"""
    orch = PipelineOrchestrator()
    prompt = orch._build_fact_extraction_prompt("某政策正文片段", "标题")
    assert "某政策正文片段" in prompt


def test_build_prompt_legacy_mode_skips_schema(monkeypatch):
    """legacy 模式：跳过 schema 契约，直接走硬编码 19 字段 prompt。"""
    from src.semantic_layer import extraction_contract as ec
    from src.semantic_layer import registry as reg

    # 即便 registry 可用，legacy 模式也不应调用 schema 构建
    called = {"schema": 0}

    def _fail_schema(*args, **kwargs):  # pragma: no cover - 不应被调用
        called["schema"] += 1
        raise AssertionError("legacy 模式不应调用 build_extraction_schema")

    monkeypatch.setattr(reg, "create_registry", _fail_schema)
    monkeypatch.setattr(ec, "build_extraction_schema", _fail_schema)

    orch = PipelineOrchestrator()
    ov = ExtractionOverride(prompt_mode="legacy")
    prompt = orch._build_fact_extraction_prompt("政策正文", "标题", ov)
    assert called["schema"] == 0
    # legacy prompt 含固定标志与原文
    assert "医保政策分析专家" in prompt
    assert "政策正文" in prompt


def test_build_prompt_schema_mode_uses_live_contract(monkeypatch):
    """schema 模式：实时读语义层 published 指标契约拼提示词（R5 核心）。"""
    from src.semantic_layer import extraction_contract as ec
    from src.semantic_layer import registry as reg
    from src.semantic_layer.extraction_contract import ExtractionSchema, FieldContract

    fake_schema = ExtractionSchema(
        fields=[FieldContract(code="payment_ratio", name="支付比例")]
    )
    monkeypatch.setattr(reg, "create_registry", lambda: object())
    monkeypatch.setattr(ec, "build_extraction_schema", lambda r, code: fake_schema)
    monkeypatch.setattr(
        ec, "build_prompt_from_schema", lambda text, title, schema: f"SCHEMA({title})"
    )

    orch = PipelineOrchestrator()
    prompt = orch._build_fact_extraction_prompt(
        "政策正文", "标题", ExtractionOverride(prompt_mode="schema")
    )
    assert prompt == "SCHEMA(标题)"


def test_build_prompt_schema_falls_back_when_contract_empty(monkeypatch):
    """schema 模式但契约为空（registry 无 published 指标）→ 回退 legacy。"""
    from src.semantic_layer import extraction_contract as ec
    from src.semantic_layer import registry as reg

    monkeypatch.setattr(reg, "create_registry", lambda: object())
    monkeypatch.setattr(
        ec, "build_extraction_schema", lambda r, code: ec.ExtractionSchema()
    )

    orch = PipelineOrchestrator()
    prompt = orch._build_fact_extraction_prompt(
        "政策正文", "标题", ExtractionOverride(prompt_mode="schema")
    )
    assert "医保政策分析专家" in prompt  # legacy 回退标志


# ── _extract_policy_facts 透传 override ──────────────────────────


def test_extract_policy_facts_passes_override_to_gateway(monkeypatch):
    """override.model_name → gateway.generate(model_override=...)；max_tokens 同步覆盖。"""
    captured: dict = {}

    def fake_generate(self, messages, model_type, scene, max_tokens=None, model_override=None):
        captured["model_override"] = model_override
        captured["max_tokens"] = max_tokens
        captured["scene"] = scene
        return ModelResponse(
            content='[{"fact_text": "事实", "rules": [{"confidence": 0.9}]}]',
            model_name=model_override or "default",
            usage=TokenUsage(0, 0),
            finish_reason="stop",
        )

    monkeypatch.setattr(ModelGateway, "generate", fake_generate)
    orch = PipelineOrchestrator()
    ov = ExtractionOverride(model_name="my-model", max_tokens=2048)

    facts = orch._extract_policy_facts("政策正文", "标题", override=ov)

    assert captured["model_override"] == "my-model"
    assert captured["max_tokens"] == 2048
    assert len(facts) == 1


def test_extract_policy_facts_no_override_uses_defaults(monkeypatch):
    """不传 override → model_override=None，max_tokens=8192（向后兼容）。"""
    captured: dict = {}

    def fake_generate(self, messages, model_type, scene, max_tokens=None, model_override=None):
        captured["model_override"] = model_override
        captured["max_tokens"] = max_tokens
        return ModelResponse(
            content="[]", model_name="default", usage=TokenUsage(0, 0), finish_reason="stop"
        )

    monkeypatch.setattr(ModelGateway, "generate", fake_generate)
    orch = PipelineOrchestrator()
    orch._extract_policy_facts("政策正文", "标题")
    assert captured["model_override"] is None
    assert captured["max_tokens"] == 8192


# ── reextract_unit(override) ─────────────────────────────────────


class _FakeStore:
    """最小内存 store，仅供 reextract_unit 测试。"""

    def __init__(self, extraction: dict, doc_title: str = "政策标题"):
        self._ext = extraction
        self._doc_title = doc_title
        self.updated: dict | None = None

    def get_extraction(self, extraction_id):
        return self._ext if self._ext.get("extraction_id") == extraction_id else None

    def get_document(self, doc_id):
        return {"title": self._doc_title} if self._ext.get("doc_id") == doc_id else None

    def update_extraction(self, extraction_id, data):
        self._ext.update(data)
        self.updated = data
        return self._ext


def test_reextract_unit_passes_override_and_records_last_override(monkeypatch):
    """reextract_unit(extraction_id, override)：透传 override 给提取，并写入 last_override 审计字段。"""
    extraction = {
        "extraction_id": "ext_001",
        "doc_id": "doc_001",
        "source_text": "起付标准 1300 元",
        "extracted_fields": {"fact_text": "旧", "rules": [], "total_rules": 0},
        "confidence": 0.5,
        "status": "reviewed",
    }
    store = _FakeStore(extraction)
    orch = PipelineOrchestrator(store=store)
    ov = ExtractionOverride(model_name="my-model", operator="reviewer-1")

    monkeypatch.setattr(
        ModelGateway,
        "generate",
        lambda self, messages, model_type, scene, max_tokens=None, model_override=None: ModelResponse(
            content='[{"fact_text": "新事实", "rules": [{"confidence": 0.9}]}]',
            model_name=model_override or "default",
            usage=TokenUsage(0, 0),
            finish_reason="stop",
        ),
    )

    result = orch.reextract_unit("ext_001", override=ov)

    assert result["success"] is True
    # 状态回退为 draft，需重新审核
    assert store.updated["status"] == "draft"
    # 审计字段 last_override 记录了本次覆盖配置
    assert store.updated["last_override"] == ov.model_dump()
    assert result["override_applied"] == ov.model_dump()


def test_reextract_unit_without_override_no_last_override(monkeypatch):
    """不传 override（默认重提取）：last_override=None，行为与旧版一致。"""
    extraction = {
        "extraction_id": "ext_001",
        "doc_id": "doc_001",
        "source_text": "起付标准 1300 元",
        "extracted_fields": {"fact_text": "旧", "rules": []},
        "confidence": 0.5,
        "status": "rejected",
    }
    store = _FakeStore(extraction)
    orch = PipelineOrchestrator(store=store)

    monkeypatch.setattr(
        ModelGateway,
        "generate",
        lambda self, messages, model_type, scene, max_tokens=None, model_override=None: ModelResponse(
            content='[{"fact_text": "新", "rules": []}]',
            model_name="default",
            usage=TokenUsage(0, 0),
            finish_reason="stop",
        ),
    )

    result = orch.reextract_unit("ext_001")
    assert result["success"] is True
    assert "last_override" not in store.updated or store.updated["last_override"] is None
    assert result["override_applied"] is None


def test_reextract_unit_missing_extraction_returns_error():
    orch = PipelineOrchestrator(store=_FakeStore({"extraction_id": "other"}))
    result = orch.reextract_unit("ext_missing")
    assert result["success"] is False
