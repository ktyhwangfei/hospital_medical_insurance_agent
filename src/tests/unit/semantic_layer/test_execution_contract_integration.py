"""执行契约端到端集成测试（设计 §17/§18/§54）。

跨层一致性核对：
- structured_config.execution_contract JSON 结构 ↔ SkillExecutionContract 模型
- SkillDraftValidator(注入 SkillInputService) ↔ 真实 SemanticRegistry
- runtime_resolvable 判定贯穿 selector / validator / capability

用真实 SemanticRegistry（use_memory）种入已发布指标，确认整个链路在
真实 registry 上工作，而非仅 FakeRegistry（参见 test_registry_facade 的教训）。
"""

from __future__ import annotations

from src.domain.skill.draft_models import (
    SkillDraft,
    SkillDraftSourceType,
    SkillExecutionContract,
)
from src.runtime.skill_management.draft_validator import SkillDraftValidator
from src.runtime.skill_management.skill_input_service import SkillInputService
from src.semantic_layer.models import (
    BusinessDomain,
    BusinessObject,
    Metric,
)
from src.semantic_layer.registry import create_registry


def _seed_registry():
    """种入一个已发布的语义对象 + 一个 runtime_resolvable 指标。"""
    reg = create_registry(use_memory=True)
    reg._store.save_domain(  # noqa: SLF001
        BusinessDomain(domain_code="settle", name="结算域")
    )
    obj = BusinessObject(
        object_code="zcgz",
        domain_code="settle",
        name="待遇规则",
        source_adapter_port="InsuranceInterfacePort",
    )
    reg._store.save_object(obj)  # noqa: SLF001
    metric = Metric(
        metric_code="zcgz.deductible_amount",
        object_code="zcgz",
        name="起付金额",
        source_field="deductible_amount",
        source_adapter_port="InsuranceInterfacePort",
    )
    reg.save_metric_draft(metric)
    reg.publish_object("zcgz", changelog="init", published_by="tester")
    return reg


def _draft_with_contract(ec_dict: dict) -> SkillDraft:
    return SkillDraft(
        draft_id="d1",
        skill_id="fee_explain_skill",
        skill_name="医保费用解释",
        source_type=SkillDraftSourceType.TEMPLATE,
        structured_config={
            "basic": {"skill_id": "fee_explain_skill", "skill_name": "医保费用解释"},
            "business_mounting": {
                "business_action": "explain",
                "business_object": "settlement",
                "include_keywords": [],
                "excluded_intents": [],
            },
            "inputs": [],
            "schemas": {},
            "execution_contract": ec_dict,
        },
        raw_files={},
        created_by="tester",
    )


def test_valid_execution_contract_passes_on_real_registry():
    """合法执行契约（对齐设计 §18 示例结构）在真实 registry 上通过校验。"""
    reg = _seed_registry()
    validator = SkillDraftValidator(SkillInputService(reg))

    ec = {
        "version": 2,
        "common": {
            "context_inputs": [
                {"code": "settlement_id", "alias": "结算标识", "purpose": "定位结算"},
            ],
            "metric_inputs": [],
        },
        "profiles": [
            {
                "profile_id": "deductible-explanation",
                "name": "起付线解释",
                "purpose": "解释起付金额来源",
                "routing_hints": ["起付线", "门槛费"],
                "context_inputs": [],
                "metric_inputs": [
                    {"metric_code": "zcgz.deductible_amount", "required": True},
                ],
            }
        ],
    }
    report = validator.validate(_draft_with_contract(ec))
    assert report.blocking_ok, [i.message for i in report.issues]


def test_unresolvable_metric_blocked_on_real_registry():
    """真实 registry 上 draft 指标被 runtime_resolvable 门禁拦截。"""
    reg = _seed_registry()
    # 补一个未发布的指标
    reg.save_metric_draft(
        Metric(
            metric_code="zcgz.draft_metric",
            object_code="zcgz",
            name="草稿指标",
            source_field="x",
            source_adapter_port="InsuranceInterfacePort",
        )
    )  # 不 publish → status=draft
    validator = SkillDraftValidator(SkillInputService(reg))

    ec = {
        "version": 2,
        "common": {"context_inputs": [], "metric_inputs": []},
        "profiles": [
            {
                "profile_id": "p1",
                "name": "A",
                "metric_inputs": [
                    {"metric_code": "zcgz.draft_metric"},
                ],
            }
        ],
    }
    report = validator.validate(_draft_with_contract(ec))
    codes = [i.code for i in report.issues]
    assert "METRIC_NOT_RUNTIME_RESOLVABLE" in codes


def test_selector_enrichment_on_real_registry():
    """真实 registry selector 树含 runtime_resolvable 字段。"""
    reg = _seed_registry()
    svc = SkillInputService(reg)
    tree = svc.input_selector_tree()
    # 找到种入的指标
    found = None
    for domain in tree:
        for obj in domain["objects"]:
            for m in obj["metrics"]:
                if m["metric_code"] == "zcgz.deductible_amount":
                    found = m
    assert found is not None
    assert found["runtime_resolvable"] is True
    assert found["resolution_type"] == "SOURCE_FIELD"
    assert found["unavailable_reason"] is None


def test_contract_json_roundtrip_with_model():
    """跨层一致性：execution_contract JSON ↔ SkillExecutionContract 模型往返。

    验证 structured_config 中存的 dict 能被模型精确重建，
    与设计 §17/§18 推荐结构一致。
    """
    ec_dict = {
        "version": 2,
        "common": {
            "context_inputs": [{"code": "question"}],
            "metric_inputs": [],
        },
        "profiles": [
            {"profile_id": "default", "name": "默认场景", "metric_inputs": []},
        ],
    }
    contract = SkillExecutionContract.model_validate(ec_dict)
    dumped = contract.model_dump(mode="json")
    restored = SkillExecutionContract.model_validate(dumped)
    assert restored == contract
    assert restored.version == 2
    assert restored.profiles[0].profile_id == "default"
