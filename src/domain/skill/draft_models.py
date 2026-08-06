"""Skill 草稿与定义领域模型（Skill 管理工作台）。

设计来源：docs/superpowers/specs/2026-08-06-skill-management-workbench-design.md §6。

四类治理对象拆分（见设计 §6）：
- ``SkillDraft``：创建、导入、复制和编辑中的过渡态草稿（本模块）。
- ``SkillDefinition``：正式目录中的可加载定义，承载治理生命周期状态
  （enabled/disabled/archived），与不可变 ``SkillVersion`` 区分。
- ``SkillVersion``：已登记不可变版本快照（见 ``version_models``）。
- ``SkillEvalRun`` / ``SkillRelease``：评测证据与 Test 发布记录（见 ``governance_models``）。

治理状态（健康/待评测/待发布等）由这些事实对象聚合得出，不单独作为事实源存储。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_SKILL_ID_PATTERN = re.compile(r"[a-z0-9]+([-_][a-z0-9]+)*")


class SkillDraftSourceType(StrEnum):
    """草稿来源类型。"""

    TEMPLATE = "template"
    IMPORT = "import"
    COPY = "copy"


class SkillDraftStatus(StrEnum):
    """草稿状态。

    - editing：可反复编辑
    - validated：校验通过（含 P2 结构校验 + P4 输入指标门禁）
    - materialized：已物化为正式 ``SkillDefinition`` + ``SkillVersion``，草稿冻结
    """

    EDITING = "editing"
    VALIDATED = "validated"
    MATERIALIZED = "materialized"


class SkillLifecycleStatus(StrEnum):
    """正式 Skill 定义的生命周期状态（设计 §6）。

    - enabled：参与路由
    - disabled：解除 Test Active，不删定义/版本/审计
    - archived：默认不参与路由，历史证据仍可查询
    """

    ENABLED = "enabled"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class SkillDraft(BaseModel):
    """草稿 — 创建、导入、复制和编辑中的过渡态。

    草稿独立存储，校验通过并经管理员确认后才写入正式 ``skills/``（设计 §6）。
    携带乐观锁 ``revision``，冲突时存储层抛 ``SkillDraftConflictError``。
    草稿可软删（``deleted_at``），可永久删除。
    """

    model_config = ConfigDict(frozen=True)

    draft_id: str = Field(min_length=1, max_length=128)
    skill_id: str = Field(min_length=1, max_length=128)
    skill_name: str = Field(min_length=1, max_length=256)
    source_type: SkillDraftSourceType
    source_skill_id: str | None = Field(default=None, max_length=128)
    structured_config: dict[str, Any] = Field(default_factory=dict)
    raw_files: dict[str, str] = Field(default_factory=dict)
    validation_report: dict[str, Any] | None = None
    status: SkillDraftStatus = SkillDraftStatus.EDITING
    revision: int = Field(default=1, ge=1)
    created_by: str = Field(min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    deleted_at: datetime | None = None

    @field_validator("skill_id", "source_skill_id")
    @classmethod
    def _validate_skill_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _SKILL_ID_PATTERN.fullmatch(value):
            raise ValueError(
                "skill_id 必须使用 kebab-case 或 snake_case 格式"
                "（小写字母、连字符、下划线、数字）"
            )
        return value


class SkillDefinition(BaseModel):
    """正式目录中的可加载 Skill 定义，承载治理生命周期状态。

    与 ``SkillVersion``（某次登记的不可变快照）区分：
    ``SkillDefinition`` 是 Skill 的"当前治理态"——是否参与路由、语义依赖是否变化。
    生命周期转换（disable/restore/archive）由服务层驱动，携带乐观锁 ``revision``。
    """

    model_config = ConfigDict(frozen=True)

    skill_id: str = Field(min_length=1, max_length=128)
    skill_name: str = Field(min_length=1, max_length=256)
    business_action: str = Field(min_length=1, max_length=128)
    business_object: str = Field(min_length=1, max_length=128)
    lifecycle_status: SkillLifecycleStatus = SkillLifecycleStatus.ENABLED
    semantic_dependency_changed: bool = False
    current_version_id: str | None = Field(default=None, max_length=128)
    revision: int = Field(default=1, ge=1)
    disabled_at: datetime | None = None
    archived_at: datetime | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @field_validator("skill_id")
    @classmethod
    def _validate_skill_id(cls, value: str) -> str:
        if not _SKILL_ID_PATTERN.fullmatch(value):
            raise ValueError(
                "skill_id 必须使用 kebab-case 或 snake_case 格式"
                "（小写字母、连字符、下划线、数字）"
            )
        return value


class ValidationSeverity(StrEnum):
    """校验问题严重程度。blocking 阻止登记，warning 仅提醒。"""

    BLOCKING = "blocking"
    WARNING = "warning"


class ValidationIssue(BaseModel):
    """单项校验问题。"""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    severity: ValidationSeverity
    path: str | None = None


class ValidationReport(BaseModel):
    """草稿校验报告。含 blocking 问题时阻止登记/物化。"""

    model_config = ConfigDict(frozen=True)

    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def has_blocking(self) -> bool:
        return any(i.severity == ValidationSeverity.BLOCKING for i in self.issues)

    @property
    def blocking_ok(self) -> bool:
        return not self.has_blocking


class InputSpec(BaseModel):
    """Skill 声明的单个输入指标契约（设计 §5.3）。

    Skill 只声明所需指标，查询方式由指标所属语义对象决定。
    """

    metric_code: str = Field(min_length=1, max_length=256)
    alias: str = Field(default="", max_length=128)
    required: bool = True
    purpose: str = Field(default="", max_length=512)
