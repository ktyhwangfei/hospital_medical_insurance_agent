from fastapi import APIRouter, HTTPException

from src.domain.skill.models import Skill, SkillMetadata, SkillStep, ToolOwner
from src.knowledge_extension.mcp_registry.models import McpRiskLevel
from src.runtime.api.schemas import (
    SkillCreateRequest,
    SkillUpdateRequest,
)
from src.runtime.api.routes import _skill_storage
from src.runtime.skill_registry.skill_service import SkillService
from src.shared.schemas.responses import error_detail

router = APIRouter()

_skill_service = SkillService(_skill_storage)


@router.post('/skills')
def create_skill(request: SkillCreateRequest) -> dict:
    steps = [
        SkillStep(
            step_id=s.step_id,
            tool_id=s.tool_id,
            depends_on=s.depends_on,
        )
        for s in request.steps
    ]
    skill = Skill(
        skill_id=request.skill_id,
        name=request.name,
        description=request.description,
        owner=ToolOwner(request.owner),
        steps=steps,
        intent_keywords=request.intent_keywords,
        required_roles=request.required_roles,
        risk_level=McpRiskLevel(request.risk_level),
        license=request.license,
        compatibility=request.compatibility,
        allowed_tools=request.allowed_tools,
        skill_metadata=SkillMetadata(**request.skill_metadata),
    )
    try:
        created = _skill_service.create_skill(skill)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=error_detail('INVALID_SKILL', str(exc), {'event_type': 'invalid_skill'}))
    return created.model_dump()


@router.get('/skills')
def list_skills() -> list[dict]:
    skills = _skill_service.list_skills()
    return [s.model_dump() for s in skills]


@router.get('/skills/{skill_id}')
def get_skill(skill_id: str) -> dict:
    skill = _skill_service.get_skill(skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail=error_detail('SKILL_NOT_FOUND', '技能不存在', {'event_type': 'skill_not_found'}))
    return skill.model_dump()


@router.put('/skills/{skill_id}')
def update_skill(skill_id: str, request: SkillUpdateRequest) -> dict:
    existing = _skill_service.get_skill(skill_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=error_detail('SKILL_NOT_FOUND', '技能不存在', {'event_type': 'skill_not_found'}))
    update_data = existing.model_dump()
    for field, value in request.model_dump(exclude_unset=True).items():
        if value is not None:
            if field == 'steps' and value is not None:
                update_data[field] = [
                    SkillStep(
                        step_id=s['step_id'],
                        tool_id=s['tool_id'],
                        depends_on=s.get('depends_on', []),
                    ).model_dump()
                    for s in value
                ]
            elif field == 'skill_metadata' and value is not None:
                update_data[field] = SkillMetadata(**value).model_dump()
            else:
                update_data[field] = value
    updated = Skill(**update_data)
    result = _skill_service.update_skill(skill_id, updated)
    return result.model_dump()


@router.delete('/skills/{skill_id}')
def delete_skill(skill_id: str) -> dict:
    deleted = _skill_service.delete_skill(skill_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=error_detail('SKILL_NOT_FOUND', '技能不存在', {'event_type': 'skill_not_found'}))
    return {'deleted': True}


@router.get('/skills/by-role/{role}')
def list_skills_by_role(role: str) -> list[dict]:
    skills = _skill_service.list_skills_by_role(role)
    return [s.model_dump() for s in skills]