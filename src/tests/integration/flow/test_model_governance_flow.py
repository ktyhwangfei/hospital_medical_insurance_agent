from src.data_platform.storage.model_governance.factory import (
    get_model_governance_storage,
)
from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
    PipelineOrchestrator,
)
from src.model_service.governance_assets import (
    GovernanceEnvironment,
    ModelProfileAssetContent,
    PromptAssetContent,
    PromptVariable,
    RouteRuleAssetContent,
)
from src.model_service.governance_service import ModelGovernanceService
from src.model_service.models import ModelResponse, TokenUsage
from src.semantic_layer.extraction_contract import ExtractionSchema, FieldContract


def _approve(service: ModelGovernanceService, draft_id: str, revision: int):
    validated = service.validate_draft(draft_id, expected_revision=revision)
    pending = service.request_review(
        draft_id, expected_revision=validated.revision, actor="editor"
    )
    return service.approve(
        draft_id,
        expected_revision=pending.revision,
        actor="reviewer",
        reason="flow",
    )


def _publish(service: ModelGovernanceService, approved):
    return service.publish(
        approved.draft_id,
        expected_revision=approved.revision,
        actor="publisher",
        environment=GovernanceEnvironment.DEV,
    )


def test_published_model_route_and_prompt_drive_policy_extraction(monkeypatch):
    monkeypatch.setenv("USE_MEMORY_STORAGE", "1")
    monkeypatch.setenv("MODEL_GOVERNANCE_ENV", "dev")
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    get_model_governance_storage.cache_clear()
    storage = get_model_governance_storage()
    service = ModelGovernanceService(storage)

    profile = ModelProfileAssetContent(
        asset_id="model.flow",
        name="flow model",
        base_url="https://governed-flow.example.test/v1",
        model_name="governed-flow-model",
        credential_ref="credential.flow",
        timeout_seconds=23,
        temperature=0.18,
        max_tokens=456,
    )
    model_draft = service.create_draft_with_credential(
        profile,
        profile.credential_ref,
        "sk-governed-flow",
        actor="editor",
    )
    approved_model = _approve(service, model_draft.draft_id, model_draft.revision)
    service.record_connection_test(
        draft_id=model_draft.draft_id,
        actor="editor",
        succeeded=True,
        latency_ms=1,
        safe_message="连接成功",
    )
    _publish(service, approved_model)

    route_draft = service.create_draft(
        RouteRuleAssetContent(
            asset_id="route.flow",
            name="flow route",
            scene="policy_fact_extraction",
            model_type="llm",
            profile_id=profile.asset_id,
        ),
        actor="editor",
    )
    _publish(service, _approve(service, route_draft.draft_id, route_draft.revision))

    variable_names = [
        "schema_version",
        "fields_desc",
        "entities_desc",
        "relations_desc",
        "title",
        "text",
        "field_codes",
        "fields_json_example",
        "field_count",
    ]
    prompt_draft = service.create_draft(
        PromptAssetContent(
            asset_id="policy.extract.schema",
            name="flow prompt",
            scene="policy_fact_extraction",
            user_prompt_template="FLOW_PROMPT {text}",
            variables=[PromptVariable(name=name) for name in variable_names],
        ),
        actor="editor",
    )
    _publish(service, _approve(service, prompt_draft.draft_id, prompt_draft.revision))

    captured = {}

    class SpyProvider:
        def __init__(self, base_url, api_key, timeout):
            captured.update(base_url=base_url, api_key=api_key, timeout=timeout)

        def invoke(self, request):
            captured["request"] = request
            return ModelResponse(
                content='[{"fact_text":"测试政策事实","rules":[]}]',
                model_name=request.model_type,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
                finish_reason="stop",
            )

    monkeypatch.setattr(
        "src.model_service.gateway.OpenAICompatibleProvider", SpyProvider
    )
    monkeypatch.setattr(
        "src.semantic_layer.extraction_contract.build_extraction_schema",
        lambda *_args, **_kwargs: ExtractionSchema(
            fields=[
                FieldContract(code=code, name=f"字段 {code}")
                for code in (
                    "rule_id", "fact_id", "policy_id", "clause_id", "source_text",
                    "insu_type", "med_type", "hosp_lv", "psn_type", "setl_type",
                    "payment_ratio", "deductible_amount", "cap_amount", "time_period",
                    "admission_order", "amount_band", "priority", "rule_type",
                    "rule_value",
                )
            ]
        ),
    )

    facts = PipelineOrchestrator()._extract_policy_facts(
        "参保人员符合条件时享受医保待遇。",
        document_title="测试医保政策",
    )

    assert facts == [{"fact_text": "测试政策事实", "rules": []}]
    assert captured["base_url"] == profile.base_url
    assert captured["api_key"] == "sk-governed-flow"
    assert captured["timeout"] == profile.timeout_seconds
    assert captured["request"].model_type == profile.model_name
    assert captured["request"].temperature == profile.temperature
    assert captured["request"].max_tokens == profile.max_tokens
    assert "FLOW_PROMPT" in captured["request"].messages[0].content

    get_model_governance_storage.cache_clear()
