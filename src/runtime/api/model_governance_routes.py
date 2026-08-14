"""模型与提示词治理只读接口。"""

from fastapi import APIRouter

from src.model_service.governance import ModelGovernanceSnapshot, build_governance_snapshot

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/model-governance",
    tags=["model-governance"],
)


@router.get("/snapshot", response_model=ModelGovernanceSnapshot)
def get_model_governance_snapshot() -> ModelGovernanceSnapshot:
    return build_governance_snapshot()
