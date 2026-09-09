"""健康运营（Ops Health）领域模型 — issue #45 P0 问题库。

横跨四类资产（skill/knowledge/data/runtime）的开放问题汇聚层；
P0 只落地「发现」：检查器只读产出 FindingDraft，存储按 fingerprint
去重落库为 OpsFinding（occurrence_count 累计）。诊断/修复/验证
状态机值随 P1/P2 分期扩充，不提前建列。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OpsAssetType(StrEnum):
    """受检资产类型（健康运营横跨四域）。"""

    SKILL = "skill"
    KNOWLEDGE = "knowledge"
    DATA = "data"
    RUNTIME = "runtime"


class OpsSeverity(StrEnum):
    """问题严重度：critical 需立即处理，warning 需排期，info 仅记录。"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class OpsFindingStatus(StrEnum):
    """问题状态（P0 仅 open；resolved/ignored 由 #50 生命周期操作驱动）。"""

    OPEN = "open"
    RESOLVED = "resolved"
    IGNORED = "ignored"


def new_finding_id() -> str:
    return uuid.uuid4().hex


def finding_fingerprint(asset_type: OpsAssetType, asset_id: str, check_id: str) -> str:
    """问题身份键：同一资产上同一检查项的复现问题只累计，不重复建档。"""
    return f"{asset_type.value}:{asset_id}:{check_id}"


class FindingDraft(BaseModel):
    """检查器单次巡检产出的问题草稿（值对象：未落库、无去重与状态字段）。

    payload 只允许脱敏后的安全证据字段（safe_* / 状态码 / 时间戳），
    检查器取数侧负责不带出凭据与原始连接串。
    """

    model_config = ConfigDict(frozen=True)

    asset_type: OpsAssetType
    asset_id: str = Field(min_length=1, max_length=128)
    check_id: str = Field(min_length=1, max_length=64)
    severity: OpsSeverity
    payload: dict[str, Any] = Field(default_factory=dict)


class OpsFinding(BaseModel):
    """资产健康问题（聚合根）：fingerprint 唯一，复现累计 occurrence_count。

    revision 为乐观锁版本，随每次 upsert / 生命周期操作递增。
    """

    model_config = ConfigDict(frozen=True)

    finding_id: str = Field(min_length=1, max_length=64)
    asset_type: OpsAssetType
    asset_id: str = Field(min_length=1, max_length=128)
    check_id: str = Field(min_length=1, max_length=64)
    severity: OpsSeverity
    status: OpsFindingStatus = OpsFindingStatus.OPEN
    fingerprint: str = Field(min_length=1, max_length=256)
    payload: dict[str, Any] = Field(default_factory=dict)
    first_seen_at: datetime
    last_seen_at: datetime
    occurrence_count: int = Field(default=1, ge=1)
    diagnosis: dict[str, Any] | None = None  # P1 诊断报告占位（schema 稳定）
    revision: int = Field(default=1, ge=1)


class OpsFindingPage(BaseModel):
    """问题列表分页结果。"""

    items: list[OpsFinding]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
