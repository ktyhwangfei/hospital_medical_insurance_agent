"""政策知识重提取端到端流程测试（迭代 18 S4）。

覆盖设计文档 §2 验收标准 R3/R4/R5 + 安全边界（§2 安全边界硬性）：

- R3 单条重提：POST /change-sets/{id}/reextract → extraction 更新 → 候选原地刷新
  → 行状态回到待审（PENDING_REVIEW）。
- R4 批量重提：对多条统一重提，返回逐条结果；部分失败可定位。
- R5 指标实时生效：schema 模式重提时，gateway 收到的提示词包含语义层实时指标。
- 安全边界：APPROVED 变更集不可重提（409）；重提不触碰已发布快照。
- 发布门禁回归：重提后的变更集仍可审核通过并进入发布。

真实链路：API → ChangeSetService.reextract → PipelineOrchestrator.reextract_unit
→ ModelGateway.generate（patched）→ 共享 store 更新 → build_for_document 原地刷新。
工作台与编排器共享同一 store（模拟生产中两者指向同一 PostgreSQL）。
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.knowledge_extension.rule_explanation.change_set_service import (
    ChangeSetService,
    change_set_id_for,
)
from src.knowledge_extension.rule_explanation.change_set_store import InMemoryChangeSetStore
from src.knowledge_extension.rule_explanation.knowledge_build_models import (
    ExtractionOverride,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
    KnowledgeWorkbenchService,
)
from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
    PipelineOrchestrator,
)
from src.model_service.gateway import ModelGateway
from src.model_service.models import ModelResponse, TokenUsage
from src.runtime.api.app import create_app
from src.tests.unit.knowledge_extension.test_knowledge_workbench import (
    FakePipelineStore,
    POLICY_TEXT,
    _leaf_ids,
)

PREFIX = "/api/v1/medical-insurance-ai-agent/policy-workbench"


class SharedFakeStore(FakePipelineStore):
    """工作台（list_extractions/get_document）+ 编排器（get_extraction/update_extraction）共享存储。

    update_extraction 原地修改 self.extractions，使后续 list_extractions 立即反映新内容
    （模拟生产 PostgreSQL：工作台与编排器指向同一库）。
    """

    def get_extraction(self, extraction_id: str) -> dict[str, Any] | None:
        for ext in self.extractions:
            if ext["extraction_id"] == extraction_id:
                return ext
        return None

    def update_extraction(self, extraction_id: str, data: dict[str, Any]) -> dict[str, Any]:
        for ext in self.extractions:
            if ext["extraction_id"] == extraction_id:
                ext.update(data)
                return ext
        raise KeyError(extraction_id)


def _ext(extraction_id: str, unit_id: str, rules: list[dict[str, Any]],
         status: str = "reviewed") -> dict[str, Any]:
    return {
        "extraction_id": extraction_id,
        "doc_id": "doc_1",
        "doc_title": "职工医保待遇政策",
        "unit_id": unit_id,
        "source_text": "（一）在职职工住院费用，统筹基金支付百分之八十。",
        "extracted_fields": {"fact_text": "在职职工住院支付比例。", "rules": rules},
        "confidence": 0.86,
        "status": status,
        "reviewed_by": "reviewer_1",
        "reviewed_at": "2026-08-03T09:00:00+08:00",
    }


def _rule(rule_type: str = "payment_ratio") -> dict[str, Any]:
    return {
        "rule_type": rule_type,
        "psn_type": "在职职工",
        "med_type": "住院",
        "payment_ratio": "80%",
        "source_text": "在职职工住院费用，统筹基金支付百分之八十。",
        "confidence": 0.9,
    }


def _gateway_response(rules: list[dict[str, Any]], model: str = "reextract-model") -> ModelResponse:
    payload = [{"fact_text": "重提后结论", "rules": rules}]
    return ModelResponse(
        content=json.dumps(payload, ensure_ascii=False),
        model_name=model,
        usage=TokenUsage(0, 0),
        finish_reason="stop",
    )


def _wire_client(
    monkeypatch,
    store: SharedFakeStore,
    generate_fn,
) -> tuple[TestClient, ChangeSetService]:
    """共享 store 同时喂给工作台与编排器，经 API 注入真实 service。"""
    from src.runtime.api import policy_workbench_routes

    workbench = KnowledgeWorkbenchService(store)
    orchestrator = PipelineOrchestrator(store=store)
    cs_store = InMemoryChangeSetStore()
    service = ChangeSetService(workbench, cs_store, orchestrator=orchestrator)

    monkeypatch.setattr(ModelGateway, "generate", generate_fn)
    monkeypatch.setattr(policy_workbench_routes, "_change_set_service", None)
    monkeypatch.setattr(
        policy_workbench_routes, "_get_change_set_service", lambda: service
    )
    return TestClient(create_app()), service


def _seed_two_extractions() -> SharedFakeStore:
    leaves = _leaf_ids()
    return SharedFakeStore([
        _ext("ext_1", leaves[0], [_rule("payment_ratio"), _rule("eligibility")]),
        _ext("ext_2", leaves[1], [_rule("payment_ratio")]),
    ])


# ── R3 单条重提：extraction 更新 + 候选原地刷新 + 状态回待审 ────────


def test_single_reextract_updates_extraction_and_refreshes_candidate(monkeypatch):
    store = _seed_two_extractions()
    # 重提 ext_1 → 只返回 1 条规则（原 2 条），候选 item 数应随之变化
    client, service = _wire_client(
        monkeypatch, store,
        lambda self, messages, model_type, scene, max_tokens=None, model_override=None:
            _gateway_response([_rule("payment_ratio")]),
    )
    cs_id = change_set_id_for("doc_1")
    service.build_for_document("doc_1")  # 初始候选：ext_1(2) + ext_2(1) = 3 items
    before = service.get_change_set(cs_id)
    assert before is not None
    assert len(before.items) == 3
    item_ext1 = next(it for it in before.items if it.after["extraction_id"] == "ext_1")

    resp = client.post(
        f"{PREFIX}/change-sets/{cs_id}/reextract",
        json={
            "item_ids": [item_ext1.item_id],
            "override": {"prompt_mode": "custom", "custom_prompt": "重提 {title}|{text}",
                         "model_name": "my-model", "operator": "rev1"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["succeeded"] == 1
    assert body["items"][0]["extraction_id"] == "ext_1"
    assert body["items"][0]["model_used"] == "my-model"

    # 体系 A：extraction 已更新（rules 变 1 条，status=reviewed 保持可见）
    updated = store.get_extraction("ext_1")
    assert updated["extracted_fields"]["total_rules"] == 1
    assert updated["status"] == "reviewed"
    # 来源可追溯：last_override 审计字段已写入
    assert updated["last_override"]["model_name"] == "my-model"

    # 体系 B：候选原地刷新（ext_1 现 1 条 → 总 2 items），状态保持待审
    after = service.get_change_set(cs_id)
    assert after is not None
    assert len(after.items) == 2
    assert after.status == "PENDING_REVIEW"
    assert after.review_decision["action"] == "reextracted"


# ── R4 批量重提：逐条结果 ─────────────────────────────────────────


def test_batch_reextract_reports_per_extraction(monkeypatch):
    store = _seed_two_extractions()
    call_count = {"n": 0}

    def generate(self, messages, model_type, scene, max_tokens=None, model_override=None):
        call_count["n"] += 1
        # 第一次（ext_1）成功，第二次（ext_2）返回空 → 触发"LLM 未返回结果"
        return _gateway_response([_rule()]) if call_count["n"] == 1 else ModelResponse(
            content="[]", model_name="x", usage=TokenUsage(0, 0), finish_reason="stop",
        )

    client, service = _wire_client(monkeypatch, store, generate)
    cs_id = change_set_id_for("doc_1")
    service.build_for_document("doc_1")

    resp = client.post(f"{PREFIX}/change-sets/{cs_id}/reextract", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2  # 按 extraction 计
    assert body["succeeded"] == 1
    assert body["failed"] == 1
    failed = next(r for r in body["items"] if not r["success"])
    assert "LLM 未返回结果" in (failed["error"] or "")


# ── 安全边界：APPROVED 变更集不可重提（409）─────────────────────────


def test_reextract_rejected_for_approved_change_set(monkeypatch):
    store = _seed_two_extractions()
    client, service = _wire_client(
        monkeypatch, store,
        lambda self, *a, **k: _gateway_response([_rule()]),
    )
    cs_id = change_set_id_for("doc_1")
    cs = service.build_for_document("doc_1")
    service.approve(cs_id, "rev1")  # 置为 APPROVED

    resp = client.post(f"{PREFIX}/change-sets/{cs_id}/reextract", json={})
    assert resp.status_code == 409
    assert "APPROVED" in resp.json()["detail"]["message"]


# ── 发布门禁回归：重提后仍可审核通过 ────────────────────────────────


def test_change_set_approvable_after_reextract(monkeypatch):
    store = _seed_two_extractions()
    client, service = _wire_client(
        monkeypatch, store,
        lambda self, *a, **k: _gateway_response([_rule()]),
    )
    cs_id = change_set_id_for("doc_1")
    service.build_for_document("doc_1")

    # 重提后审核通过（发布门禁回归：approve 仍可用）
    reextracted = client.post(f"{PREFIX}/change-sets/{cs_id}/reextract", json={})
    assert reextracted.status_code == 200

    approved = client.post(
        f"{PREFIX}/change-sets/{cs_id}/approve",
        json={"reviewer": "rev1", "note": "重提后通过"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"


# ── R5 指标实时生效：schema 模式重提的提示词含语义层实时指标 ──────────


def test_schema_mode_reextract_prompt_includes_live_metric(monkeypatch):
    from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
        _BASE_POLICY_FIELD_CODES,
    )
    from src.semantic_layer import extraction_contract as ec
    from src.semantic_layer import registry as reg
    from src.semantic_layer.extraction_contract import (
        ExtractionSchema,
        FieldContract,
    )

    live_schema = ExtractionSchema(
        schema_version=3,
        fields=[
            *[
                FieldContract(code=code, name=code)
                for code in sorted(_BASE_POLICY_FIELD_CODES)
            ],
            FieldContract(
                code="live_metric", name="起付金额实时指标",
                extraction_hint="起付标准", value_domain="金额",
            ),
        ],
    )
    monkeypatch.setattr(reg, "create_registry", lambda: object())
    monkeypatch.setattr(ec, "build_extraction_schema", lambda r, code: live_schema)
    monkeypatch.setattr(
        ec, "build_prompt_from_schema",
        lambda text, title, schema: f"PROMPT含{schema.fields[-1].name}|{title}|{text}",
    )

    captured: dict[str, Any] = {}

    def generate(self, messages, model_type, scene, max_tokens=None, model_override=None):
        # messages 为 Message 对象列表，取最后一条的 .content
        captured["prompt"] = messages[-1].content if messages else ""
        return _gateway_response([_rule()])

    store = SharedFakeStore([_ext("ext_1", _leaf_ids()[0], [_rule()])])
    client, service = _wire_client(monkeypatch, store, generate)
    cs_id = change_set_id_for("doc_1")
    service.build_for_document("doc_1")

    resp = client.post(
        f"{PREFIX}/change-sets/{cs_id}/reextract",
        json={"override": {"prompt_mode": "schema", "operator": "rev1"}},
    )
    assert resp.status_code == 200, resp.text
    # gateway 收到的提示词实时包含语义层指标
    assert "起付金额实时指标" in captured["prompt"]
