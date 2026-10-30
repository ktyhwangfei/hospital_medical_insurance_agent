"""费用分解工作台 API — Issue #78 四链路页面可用化 Phase 1。

POST /fee-decomposition/decompose：按门诊交易号（T_TradeNo）或门特登记号（djh）
做单笔确定性费用分解，直接返回 FeeDecompositionPublic 公开契约 + 工作台 meta。

- 鉴权：签名 JWT 的 fee_decomposition:read 权限（与 ops-analytics 同模式）；
- 门控未配置 → 503 FEE_DECOMPOSITION_NOT_CONFIGURED（显式报因，带缺失 env 名）；
- 分解不可用 → 200 + execution_status=unavailable + uncertainties（诚实降级，
  与内核语义一致，数据不可用不是 HTTP 错误）；
- provider 通过 Depends(get_fee_decomposition_provider) 注入——API 测试 override
  该依赖即可注入 stub（项目既有陷阱：直接调用工厂不响应 override）。
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from src.adapters.base.models import AdapterCallStatus
from src.adapters.data_supply.decomposition_person_queries import (
    is_id_card_format,
    resolve_decomposition_targets_by_person,
)
from src.gateway.auth import authenticator
from src.runtime.api.data_governance_schemas import DataGovernancePrincipal
# 与 policy-qa 主链同款公开文本消毒（物理表名/内部标识不进公开文案），单源复用
from src.runtime.api.policy_qa_routes import _public_text
from src.runtime.policy_qa.fee_decomposition.integration import decompose_for_workbench
from src.runtime.policy_qa.fee_decomposition.public_view import to_public_contract_dict
from src.runtime.policy_qa.public_contract import FeeDecompositionPublic
from src.runtime.policy_qa.settlement_data_provider import create_settlement_data_provider
from src.shared.schemas.responses import error_detail

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/fee-decomposition",
    tags=["fee-decomposition"],
)


def get_fee_decomposition_provider() -> Any:
    """依赖注入 seam：默认真实结算数据 provider（含数据供给连接工厂）。"""
    return create_settlement_data_provider()


def _require_fee_decomposition_read(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> DataGovernancePrincipal:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail("AUTH_REQUIRED", "缺少 Authorization 凭据"),
        )
    auth = authenticator.validate_signed_token(authorization)
    if not auth.is_success or not auth.user_id.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail("AUTH_INVALID", auth.error_message or "登录凭据无效"),
        )
    permitted = authenticator.check_permission(auth, "fee_decomposition:read")
    if not permitted.is_success:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail("AUTH_FORBIDDEN", "权限不足"),
        )
    return DataGovernancePrincipal(
        user_id=auth.user_id, roles=auth.roles, permissions=auth.permissions,
    )


class FeeDecompositionDecomposeRequest(BaseModel):
    """单笔分解请求：identifier 为门诊交易号或门特登记号；chain 默认 auto 自动识别。"""

    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(min_length=1, max_length=64)
    chain: Literal["auto", "outpatient", "special"] = "auto"


class FeeDecompositionMeta(BaseModel):
    """工作台 meta：识别链路、险种 profile、算法版本（供页面 meta 条展示）。"""

    model_config = ConfigDict(extra="forbid")

    identifier: str
    chain: str
    profile: str | None = None
    algorithm_version: str
    # 本次采用的累计/资格口径：eval_calibers 仅工作台；policy-qa 主链恒 fail_closed
    caliber: str = "fail_closed"


class FeeDecompositionDecomposeResponse(FeeDecompositionPublic):
    """费用分解公开契约全字段 + 工作台 meta。"""

    meta: FeeDecompositionMeta


@router.post("/decompose")
def decompose(
    request: FeeDecompositionDecomposeRequest,
    _principal: DataGovernancePrincipal = Depends(_require_fee_decomposition_read),
    provider: Any = Depends(get_fee_decomposition_provider),
):
    # 防误判：18 位身份证号会被交易号识别规则（[A-Za-z0-9]{15,}）吞掉而查不到，
    # 显式 422 引导改用按人定位；报错信息不回显身份证原文
    if is_id_card_format(request.identifier):
        raise HTTPException(
            status_code=422,
            detail=error_detail(
                "IDENTIFIER_IS_ID_CARD",
                "identifier 为身份证号格式，本端点仅支持门诊交易号/门特登记号；"
                "请改用 POST /fee-decomposition/resolve-person 按人定位候选后再分解"),
        )
    outcome = decompose_for_workbench(request.identifier, request.chain, provider)
    if outcome.status == "not_configured":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail("FEE_DECOMPOSITION_NOT_CONFIGURED", outcome.message),
        )
    presentation = outcome.presentation
    assert presentation is not None  # status=ok 必携带表述
    # 与主链共用同一公开投影入口：投影 + 公开文本消毒（_public_text）一站式完成；
    # 1.2 起结算事实侧车随 presentation 一并进入公开契约
    public = FeeDecompositionPublic.model_validate(
        to_public_contract_dict(
            presentation.result,
            summary_text=presentation.summary_text,
            summary_source=presentation.summary_source,
            settlement_facts=presentation.settlement_facts,
            sanitize=_public_text,
        )
    )
    response = FeeDecompositionDecomposeResponse(
        **public.model_dump(),
        meta=FeeDecompositionMeta(
            identifier=request.identifier,
            chain=outcome.chain,
            profile="/".join(outcome.profile) if outcome.profile else None,
            caliber=outcome.caliber,
            algorithm_version=public.algorithm_version,
        ),
    )
    return response.model_dump()


# ── 按身份证号定位（resolve-person）──────────────────────────────────
#
# 工作台「按身份证号定位」入口：身份证号 → 普通门诊交易/门特登记候选。
# 不做分解（无取整门控），只定位候选；响应与日志绝不回显身份证原文。


class FeeDecompositionResolvePersonRequest(BaseModel):
    """按人定位请求：id_card 为 15 位纯数字或 18 位（末位可 X/x）身份证号。"""

    model_config = ConfigDict(extra="forbid")

    id_card: str = Field(pattern=r"^(?:\d{15}|\d{17}[\dXx])$")


class ResolvePersonCandidate(BaseModel):
    """单个分解候选：链路、定位标识（交易号/登记号）、链路/险种标签、日期与总金额。

    刻意不含任何身份原文字段（身份证/卡号只进查询 WHERE，不进输出）。
    """

    model_config = ConfigDict(extra="forbid")

    chain: Literal["outpatient", "special"]
    identifier: str
    chain_label: str
    profile_label: str | None = None
    service_date: str | None = None
    total_amount: str | None = None


class FeeDecompositionResolvePersonResponse(BaseModel):
    """按人定位响应：三态 match_status + 候选列表 + 截断标记。"""

    model_config = ConfigDict(extra="forbid")

    match_status: Literal["unique_match", "multiple_candidates", "no_match"]
    candidates: list[ResolvePersonCandidate]
    truncated: bool


@router.post("/resolve-person")
def resolve_person(
    request: FeeDecompositionResolvePersonRequest,
    _principal: DataGovernancePrincipal = Depends(_require_fee_decomposition_read),
    provider: Any = Depends(get_fee_decomposition_provider),
):
    connect = getattr(provider, "_connect", None)
    if connect is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail(
                "FEE_DECOMPOSITION_NOT_CONFIGURED",
                "结算数据 provider 无数据供给连接工厂（_connect），按人定位不可用"),
        )
    conn = None
    try:
        conn = connect("bjybdb")
        result = resolve_decomposition_targets_by_person(conn, request.id_card)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — 诚实降级：异常转 503，不抛栈
        # 查询层已按掩码留痕；此处不再携带身份标识，杜绝 15 位身份证绕过前3后4掩码
        logger.warning("[FEE-DECOMP] 按人定位执行异常: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail("PERSON_RESOLVE_FAILED", "按人定位执行异常，暂不可用"),
        ) from exc
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    if result.status != AdapterCallStatus.SUCCESS:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail("PERSON_RESOLVE_FAILED", "按人定位查询失败，暂不可用"),
        )
    data = result.data
    return FeeDecompositionResolvePersonResponse(
        match_status=data["match_status"],
        candidates=[ResolvePersonCandidate(**c) for c in data["candidates"]],
        truncated=bool(data["truncated"]),
    ).model_dump()
