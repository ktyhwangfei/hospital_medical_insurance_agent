"""模型与提示词治理只读接口。"""

import os
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException

from src.gateway.auth import authenticator
from src.model_service.governance import ModelGovernanceSnapshot, build_governance_snapshot
from src.runtime.api.schemas import AgentResponse
from src.shared.schemas.responses import error_detail

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/model-governance",
    tags=["model-governance"],
)


class ModelGovernanceResponse(AgentResponse):
    scenario: Literal["model_governance"] = "model_governance"
    status: Literal["success"] = "success"
    result: ModelGovernanceSnapshot


def require_model_governance_read(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    if os.getenv("MODEL_GOVERNANCE_DEV_MODE", "").lower() not in {
        "1",
        "true",
        "yes",
    }:
        raise HTTPException(
            status_code=403,
            detail=error_detail(
                "MODEL_GOVERNANCE_DISABLED",
                "生产真实认证未接入，模型治理端点默认关闭；仅可在显式开发模式下启用",
            ),
        )
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail=error_detail("AUTH_REQUIRED", "缺少 Authorization 凭据"),
        )
    auth_result = authenticator.validate_token(authorization)
    if not auth_result.is_success:
        raise HTTPException(
            status_code=401,
            detail=error_detail("AUTH_INVALID", auth_result.error_message or "凭据无效"),
        )
    permission_result = authenticator.check_permission(
        auth_result, "model_governance:read"
    )
    if not permission_result.is_success:
        raise HTTPException(
            status_code=403,
            detail=error_detail(
                "AUTH_FORBIDDEN", permission_result.error_message or "权限不足"
            ),
        )


@router.get("/snapshot", response_model=ModelGovernanceResponse)
def get_model_governance_snapshot(
    _: None = Depends(require_model_governance_read),
) -> ModelGovernanceResponse:
    snapshot = build_governance_snapshot()
    return ModelGovernanceResponse(
        result=snapshot,
        citations=[
            {
                "source_type": "code",
                "source_id": source_path,
                "summary": "模型治理快照来源",
            }
            for source_path in snapshot.citations
        ],
        uncertainties=snapshot.uncertainties,
        audit={"mode": "read_only"},
    )
