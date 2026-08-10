"""政策工作台重提取 API 测试（迭代 18 S2）。

覆盖 4 个端点：
- POST /change-sets/{id}/reextract（200 / 409）
- GET /extraction-config（200）
- GET /extraction-config/models（200，排除 embedding）
- GET /extraction-config/prompt-preview（schema / custom / 400）
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app

PREFIX = "/api/v1/medical-insurance-ai-agent/policy-workbench"


# ── POST /change-sets/{id}/reextract ──────────────────────────────


def test_test_extract_previews_without_persisting(monkeypatch):
    """迭代19 修改2：test-extract 用当前配置跑提取并返回预览，不写存储。"""
    from src.runtime.api import policy_workbench_routes

    captured: dict = {}

    class Service:
        def test_extract(self, change_set_id, item_id, override=None):
            captured["change_set_id"] = change_set_id
            captured["item_id"] = item_id
            captured["override"] = override
            return {
                "change_set_id": change_set_id,
                "item_id": item_id,
                "extraction_id": "ext_1",
                "fact_count": 1,
                "rule_count": 2,
                "fields_extracted": ["payment_ratio", "psn_type"],
                "facts": [{"fact_text": "退休人员个人支付比例为职工支付比例的60%",
                           "rules": [{"payment_ratio": "60%"}, {"psn_type": "退休人员"}]}],
                "override_applied": {"prompt_mode": "schema"},
            }

    monkeypatch.setattr(policy_workbench_routes, "_change_set_service", None)
    monkeypatch.setattr(policy_workbench_routes, "_get_change_set_service", lambda: Service())
    client = TestClient(create_app())

    resp = client.post(
        f"{PREFIX}/change-sets/CS_test/test-extract",
        json={"item_id": "ci_1", "override": {"prompt_mode": "schema", "operator": "rev1"}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fact_count"] == 1
    assert body["rule_count"] == 2
    assert "payment_ratio" in body["fields_extracted"]
    assert captured["item_id"] == "ci_1"
    assert captured["override"].prompt_mode == "schema"


def test_test_extract_409_on_missing_item(monkeypatch):
    from src.runtime.api import policy_workbench_routes

    class Service:
        def test_extract(self, change_set_id, item_id, override=None):
            raise ValueError(f"变更集 {change_set_id} 不含变更项: {item_id}")

    monkeypatch.setattr(policy_workbench_routes, "_change_set_service", None)
    monkeypatch.setattr(policy_workbench_routes, "_get_change_set_service", lambda: Service())
    client = TestClient(create_app())

    resp = client.post(
        f"{PREFIX}/change-sets/CS_test/test-extract",
        json={"item_id": "ci_missing"},
    )
    assert resp.status_code == 409


# ── POST /change-sets/{id}/reextract ──────────────────────────────


def test_reextract_change_set_200(monkeypatch):
    from src.runtime.api import policy_workbench_routes
    from src.knowledge_extension.rule_explanation.knowledge_build_models import (
        ReextractItemResult,
        ReextractReport,
    )

    captured: dict = {}

    class Service:
        def reextract(self, change_set_id, item_ids=None, override=None):
            captured["change_set_id"] = change_set_id
            captured["item_ids"] = item_ids
            captured["override"] = override
            return ReextractReport(
                change_set_id=change_set_id,
                total=1,
                succeeded=1,
                failed=0,
                items=[ReextractItemResult(
                    extraction_id="ext_1", item_ids=["ci_1"], success=True,
                    model_used="my-model", new_knowledge_count=2,
                )],
                override_applied={"model_name": "my-model"},
            )

    monkeypatch.setattr(policy_workbench_routes, "_change_set_service", None)
    monkeypatch.setattr(policy_workbench_routes, "_get_change_set_service", lambda: Service())
    client = TestClient(create_app())

    resp = client.post(
        f"{PREFIX}/change-sets/CS_test/reextract",
        json={"item_ids": ["ci_1"], "override": {"model_name": "my-model"}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["change_set_id"] == "CS_test"
    assert body["succeeded"] == 1
    assert body["items"][0]["extraction_id"] == "ext_1"
    # override 透传到 service
    assert captured["override"].model_name == "my-model"
    assert captured["item_ids"] == ["ci_1"]


def test_reextract_change_set_409_on_invalid_state(monkeypatch):
    from src.runtime.api import policy_workbench_routes

    class Service:
        def reextract(self, change_set_id, item_ids=None, override=None):
            raise ValueError("变更集状态为 APPROVED，不可重新提取")

    monkeypatch.setattr(policy_workbench_routes, "_change_set_service", None)
    monkeypatch.setattr(policy_workbench_routes, "_get_change_set_service", lambda: Service())
    client = TestClient(create_app())

    resp = client.post(f"{PREFIX}/change-sets/CS_test/reextract", json={})
    assert resp.status_code == 409


# ── GET /extraction-config / models / prompt-preview ─────────────


def _patch_schema(monkeypatch, schema):
    from src.semantic_layer import extraction_contract as ec
    from src.semantic_layer import registry as reg

    monkeypatch.setattr(reg, "create_registry", lambda: object())
    monkeypatch.setattr(ec, "build_extraction_schema", lambda r, code: schema)


def test_get_extraction_config_200(monkeypatch):
    from src.semantic_layer.extraction_contract import (
        ExtractionSchema,
        FieldContract,
    )

    schema = ExtractionSchema(
        schema_version=3,
        fields=[FieldContract(
            code="payment_ratio", name="支付比例",
            extraction_hint="支付比例", value_domain="0-100%",
        )],
    )
    _patch_schema(monkeypatch, schema)
    client = TestClient(create_app())

    resp = client.get(f"{PREFIX}/extraction-config")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["default_prompt_mode"] == "schema"
    # 默认模型来自路由配置（不依赖具体环境值，只断言非空且为路由中的 LLM 模型）
    assert body["default_model"]
    from src.config.model_routing import ROUTING_TABLE
    assert body["default_model"] == ROUTING_TABLE[("default", "llm")]
    assert body["default_max_tokens"] == 8192
    assert body["schema_version"] == 3
    assert any(m["code"] == "payment_ratio" for m in body["metrics"])


def test_list_extraction_models_excludes_embedding():
    client = TestClient(create_app())
    resp = client.get(f"{PREFIX}/extraction-config/models")
    assert resp.status_code == 200
    names = [m["model_name"] for m in resp.json()]
    assert "deepseek-chat" in names
    assert "text-embedding-3-small" not in names


def test_prompt_preview_schema_200(monkeypatch):
    from src.semantic_layer.extraction_contract import (
        ExtractionSchema,
        FieldContract,
    )

    _patch_schema(monkeypatch, ExtractionSchema(fields=[FieldContract(code="x", name="x")]))
    client = TestClient(create_app())

    resp = client.get(
        f"{PREFIX}/extraction-config/prompt-preview",
        params={"prompt_mode": "schema"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["field_count"] == 1
    assert body["prompt"]  # 非空


def test_prompt_preview_custom_requires_prompt(monkeypatch):
    client = TestClient(create_app())
    resp = client.get(
        f"{PREFIX}/extraction-config/prompt-preview",
        params={"prompt_mode": "custom"},
    )
    assert resp.status_code == 400


def test_prompt_preview_custom_returns_replaced_template(monkeypatch):
    _patch_schema(monkeypatch, None)  # custom 模式不读 schema，但 route 顶部仍读
    # custom 模式 route 顶部仍调 build_extraction_schema；给一个空 schema 即可
    from src.semantic_layer.extraction_contract import ExtractionSchema
    _patch_schema(monkeypatch, ExtractionSchema())
    client = TestClient(create_app())

    resp = client.get(
        f"{PREFIX}/extraction-config/prompt-preview",
        params={"prompt_mode": "custom", "custom_prompt": "自定义提示 {title}|{text}"},
    )
    assert resp.status_code == 200, resp.text
    prompt = resp.json()["prompt"]
    # 占位符被替换
    assert "自定义提示 （政策标题）|（政策原文）" == prompt
