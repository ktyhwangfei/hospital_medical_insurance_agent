"""健康运营（Ops Health）领域模型 — issue #45 P0 问题库 + #50 生命周期。

横跨四类资产（skill/knowledge/data/runtime）的开放问题汇聚层；
「发现」阶段检查器只读产出 FindingDraft，存储按 fingerprint 去重
落库为 OpsFinding（occurrence_count 累计）。「处置」阶段（#50）提供
ignore/reopen 手动流转：带乐观锁 revision 与事件时间线；resolved 由
#53 自动修复闭环驱动，本期不建写入口。诊断/修复/验证状态机值随
P1/P2 分期扩充，不提前建列。
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


def new_finding_event_id() -> str:
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


class OpsFindingEventType(StrEnum):
    """生命周期流转事件类型（手动操作产生；resolved 事件归 #53）。"""

    IGNORED = "ignored"
    REOPENED = "reopened"


class OpsFindingEvent(BaseModel):
    """问题生命周期事件（Entity）：一次 ignore/reopen 流转的留痕。

    reason 在 ignore 时必填、reopen 时为空（业务层约束，存储不重复校验）。
    """

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(min_length=1, max_length=64)
    finding_id: str = Field(min_length=1, max_length=64)
    event_type: OpsFindingEventType
    actor: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=500)
    created_at: datetime


class OpsFindingDetail(BaseModel):
    """单条问题详情视图：当前状态 + 生命周期事件时间线（升序）。"""

    finding: OpsFinding
    events: list[OpsFindingEvent]


class OpsFindingNotFoundError(Exception):
    """问题不存在（按 finding_id 查询）。"""

    def __init__(self, finding_id: str) -> None:
        super().__init__(f"问题不存在: {finding_id}")
        self.finding_id = finding_id


class InvalidFindingTransitionError(Exception):
    """非法状态流转（如对已忽略问题再次忽略、对开放问题重开）。"""

    def __init__(self, finding_id: str, action: str, current_status: OpsFindingStatus) -> None:
        super().__init__(
            f"问题 {finding_id} 当前状态 {current_status.value} 不允许执行 {action}"
        )
        self.finding_id = finding_id
        self.action = action
        self.current_status = current_status


class FindingRevisionConflictError(Exception):
    """乐观锁冲突：expected_revision 与库内 revision 不一致（并发流转/巡检刷新）。"""

    def __init__(self, finding_id: str, expected_revision: int, actual_revision: int) -> None:
        super().__init__(
            f"问题 {finding_id} 版本冲突：期望 revision {expected_revision}，实际 {actual_revision}"
        )
        self.finding_id = finding_id
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
