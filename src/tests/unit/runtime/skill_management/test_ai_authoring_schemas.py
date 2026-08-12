"""AI Skill 编写契约的单元测试。"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.domain.skill import SkillDraft, SkillDraftSourceType
from src.runtime.skill_management.ai_authoring.schemas import (
    SkillAIGenerationResponse,
    SkillAIModelOutput,
)
from src.runtime.api.skill_schemas import (
    SkillAIAcceptRequest,
    SkillAIGenerateRequest,
    SkillAIOptimizeRequest,
)


def _valid_structured_config() -> dict[str, object]:
    return {
        "basic": {
            "skill_id": "deductible_explain",
            "skill_name": "起付线解释",
            "description": "解释医保结算中的起付线计算",
            "owner": "medical_office",
        },
        "business_mounting": {
            "business_action": "explain",
            "business_object": "settlement",
            "include_keywords": ["起付线"],
            "excluded_intents": [],
        },
        "inputs": [
            {
                "metric_code": "Settlement.deductible",
                "alias": "deductible",
                "required": True,
                "purpose": "计算起付线",
            }
        ],
        "schemas": {
            "input": {
                "type": "object",
                "properties": {"amount": {"type": "number"}},
                "required": ["amount"],
            },
            "output": {"type": "object"},
        },
    }


def _valid_provenance() -> dict[str, object]:
    return {
        "model_type": "reasoning",
        "scene": "skill_authoring",
        "prompt_version": "v1",
        "metric_versions": [
            {
                "metric_code": "Settlement.deductible",
                "object_code": "Settlement",
                "object_version": 3,
                "status": "published",
            }
        ],
        "generated_at": datetime(2026, 8, 10, tzinfo=timezone.utc),
        "content_hash": "b" * 64,
    }


def _valid_ai_response() -> SkillAIGenerationResponse:
    return SkillAIGenerationResponse.model_validate(
        {
            "generation_id": "gen-1",
            "proposal_hash": "a" * 64,
            "structured_config": _valid_structured_config(),
            "raw_files": {"assembler.py": "def load():\n    return None\n"},
            "validation_preview": {
                "issues": [],
                "has_blocking": False,
                "blocking_ok": True,
            },
            "provenance": _valid_provenance(),
            "citations": [
                {
                    "source_type": "metric_registry",
                    "source_id": "Settlement.deductible@3",
                    "summary": "已发布指标快照",
                }
            ],
            "uncertainties": ["需人工确认政策适用范围"],
        }
    )


def test_ai_proposal_rejects_unknown_fields() -> None:
    payload = _valid_ai_response().model_dump()
    payload["untrusted_extra"] = True

    with pytest.raises(ValidationError):
        SkillAIGenerationResponse.model_validate(payload)


def test_ai_proposal_freezes_provenance() -> None:
    proposal = _valid_ai_response()

    with pytest.raises(ValidationError):
        proposal.provenance.prompt_version = "changed"


def test_skill_draft_accepts_ai_generated_source_type() -> None:
    draft = SkillDraft(
        draft_id="draft-ai-1",
        skill_id="deductible_explain",
        skill_name="起付线解释",
        source_type=SkillDraftSourceType.AI_GENERATED,
        structured_config=_valid_structured_config(),
        created_by="tester",
    )

    assert draft.source_type.value == "ai_generated"


def test_ai_proposal_deeply_freezes_json_objects() -> None:
    proposal = _valid_ai_response()

    with pytest.raises(TypeError):
        proposal.raw_files["assembler.py"] = "changed"
    with pytest.raises(TypeError):
        proposal.structured_config.schemas.input["type"] = "array"
    with pytest.raises(TypeError):
        proposal.structured_config.schemas.input["properties"]["amount"] = {
            "type": "string"
        }

    serialized = json.loads(proposal.model_dump_json())
    assert serialized["raw_files"]["assembler.py"].startswith("def load")
    assert serialized["structured_config"]["schemas"]["input"]["required"] == [
        "amount"
    ]


def test_frozen_mappings_keep_object_shape_in_json_schema() -> None:
    schema = SkillAIGenerationResponse.model_json_schema(mode="serialization")

    assert schema["properties"]["raw_files"] == {
        "additionalProperties": {"type": "string"},
        "title": "Raw Files",
        "type": "object",
    }


def test_validation_preview_rejects_contradictory_summary() -> None:
    payload = _valid_ai_response().model_dump()
    payload["validation_preview"] = {
        "issues": [
            {
                "code": "MISSING_CITATION",
                "message": "缺少来源",
                "severity": "blocking",
                "path": "citations",
            }
        ],
        "has_blocking": False,
        "blocking_ok": True,
    }

    with pytest.raises(ValidationError):
        SkillAIGenerationResponse.model_validate(payload)


def test_ai_output_requires_citation_or_non_empty_uncertainty() -> None:
    payload = _valid_ai_response().model_dump()
    payload["citations"] = []
    payload["uncertainties"] = []

    with pytest.raises(ValidationError):
        SkillAIGenerationResponse.model_validate(payload)

    model_output = {
        "structured_config": _valid_structured_config(),
        "raw_files": {"assembler.py": "def load():\n    return None\n"},
        "citations": [],
        "uncertainties": [],
    }
    with pytest.raises(ValidationError):
        SkillAIModelOutput.model_validate(model_output)

    payload = _valid_ai_response().model_dump()
    payload["citations"] = []
    payload["uncertainties"] = ["   "]
    with pytest.raises(ValidationError):
        SkillAIGenerationResponse.model_validate(payload)


def test_ai_output_allows_uncertainty_without_citation() -> None:
    payload = _valid_ai_response().model_dump()
    payload["citations"] = []
    payload["uncertainties"] = ["需人工确认政策适用范围"]

    proposal = SkillAIGenerationResponse.model_validate(payload)

    assert proposal.citations == ()


@pytest.mark.parametrize(
    "citation",
    [
        {"source_type": "", "source_id": "", "summary": ""},
        {
            "source_type": "   ",
            "source_id": "Settlement.deductible@3",
            "summary": "已发布指标快照",
        },
        {
            "source_type": "metric_registry",
            "source_id": "   ",
            "summary": "已发布指标快照",
        },
        {
            "source_type": "metric_registry",
            "source_id": "Settlement.deductible@3",
            "summary": "   ",
        },
    ],
)
def test_ai_output_rejects_blank_citation_without_uncertainty(
    citation: dict[str, str],
) -> None:
    payload = _valid_ai_response().model_dump()
    payload["citations"] = [citation]
    payload["uncertainties"] = []

    with pytest.raises(ValidationError):
        SkillAIGenerationResponse.model_validate(payload)


def test_ai_proposal_rejects_invalid_hashes_and_nested_unknown_fields() -> None:
    payload = _valid_ai_response().model_dump()
    payload["proposal_hash"] = "A" * 64
    with pytest.raises(ValidationError):
        SkillAIGenerationResponse.model_validate(payload)

    payload = _valid_ai_response().model_dump()
    payload["provenance"]["content_hash"] = "b" * 63
    with pytest.raises(ValidationError):
        SkillAIGenerationResponse.model_validate(payload)

    payload = _valid_ai_response().model_dump()
    payload["structured_config"]["basic"]["untrusted_extra"] = True
    with pytest.raises(ValidationError):
        SkillAIGenerationResponse.model_validate(payload)


def test_generated_at_requires_timezone_and_normalizes_to_utc() -> None:
    payload = _valid_ai_response().model_dump()
    payload["provenance"]["generated_at"] = datetime(2026, 8, 10, 8, 0)
    with pytest.raises(ValidationError):
        SkillAIGenerationResponse.model_validate(payload)

    payload = _valid_ai_response().model_dump()
    payload["provenance"]["generated_at"] = datetime(
        2026, 8, 10, 8, 0, tzinfo=timezone(timedelta(hours=8))
    )
    proposal = SkillAIGenerationResponse.model_validate(payload)

    assert proposal.provenance.generated_at == datetime(
        2026, 8, 10, tzinfo=timezone.utc
    )
    assert proposal.provenance.generated_at.tzinfo is timezone.utc


@pytest.mark.parametrize(
    ("request_model", "payload"),
    [
        (
            SkillAIGenerateRequest,
            {"description": "生成起付线解释", "metric_codes": ["Settlement.deductible"]},
        ),
        (
            SkillAIOptimizeRequest,
            {
                "description": "补充政策来源",
                "metric_codes": ["Settlement.deductible"],
                "expected_revision": 1,
            },
        ),
        (
            SkillAIAcceptRequest,
            {
                "generation_id": "gen-1",
                "proposal_hash": "a" * 64,
                "skill_id": "deductible_explain",
                "skill_name": "起付线解释",
                "structured_config": _valid_structured_config(),
                "raw_files": {"assembler.py": "def load():\n    return None\n"},
            },
        ),
    ],
)
def test_ai_api_request_dtos_reject_unknown_fields(
    request_model: type, payload: dict[str, object]
) -> None:
    payload["untrusted_extra"] = True

    with pytest.raises(ValidationError):
        request_model.model_validate(payload)


@pytest.mark.parametrize("description", ["", "   ", "x" * 4001])
def test_generate_request_rejects_invalid_description(description: str) -> None:
    with pytest.raises(ValidationError):
        SkillAIGenerateRequest(
            description=description,
            metric_codes=["Settlement.deductible"],
        )


@pytest.mark.parametrize(
    "metric_codes",
    [[], [""], ["   "], ["x" * 257], [f"Metric.{i}" for i in range(101)]],
)
def test_generate_request_rejects_invalid_metric_codes(
    metric_codes: list[str],
) -> None:
    with pytest.raises(ValidationError):
        SkillAIGenerateRequest(
            description="生成起付线解释",
            metric_codes=metric_codes,
        )


def test_optimize_request_requires_positive_revision() -> None:
    with pytest.raises(ValidationError):
        SkillAIOptimizeRequest(
            description="补充政策来源",
            metric_codes=["Settlement.deductible"],
            expected_revision=0,
        )


def test_accept_request_rejects_invalid_hash_and_nested_unknown_field() -> None:
    payload = {
        "generation_id": "gen-1",
        "proposal_hash": "A" * 64,
        "skill_id": "deductible_explain",
        "skill_name": "起付线解释",
        "structured_config": _valid_structured_config(),
        "raw_files": {"assembler.py": "def load():\n    return None\n"},
    }
    with pytest.raises(ValidationError):
        SkillAIAcceptRequest.model_validate(payload)

    payload["proposal_hash"] = "a" * 64
    payload["structured_config"]["schemas"]["untrusted_extra"] = True
    with pytest.raises(ValidationError):
        SkillAIAcceptRequest.model_validate(payload)
