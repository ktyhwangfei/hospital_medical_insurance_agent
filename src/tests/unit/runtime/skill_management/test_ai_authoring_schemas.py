"""AI Skill 编写契约的单元测试。"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.domain.skill import SkillDraft, SkillDraftSourceType
from src.runtime.skill_management.ai_authoring.schemas import (
    SkillAIGenerationResponse,
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
            "keywords": ["起付线"],
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
        "schemas": {"input": {"type": "object"}, "output": {"type": "object"}},
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
