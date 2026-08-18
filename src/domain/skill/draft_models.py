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
    AI_GENERATED = "ai_generated"


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
    旧版平铺输入契约，保留做向后兼容；新执行契约使用 MetricInputSpec。
    """

    metric_code: str = Field(min_length=1, max_length=256)
    alias: str = Field(default="", max_length=128)
    required: bool = True
    purpose: str = Field(default="", max_length=512)


# ── Skill 执行契约（Skill Execution Contract，设计 §4-§53）───────────
#
# 旧 ``inputs`` 平铺契约升级为：
#   structured_config.execution_contract
#     ├── common       （公共输入：几乎所有 Profile 都需要）
#     │   ├── context_inputs   （运行时上下文：question/settlement_id…）
#     │   └── metric_inputs    （业务指标依赖，必须 runtime_resolvable）
#     └── profiles     （执行场景：同一能力、不同数据依赖）
#         ├── profile_id（kebab-case，Skill 内唯一）
#         ├── routing_hints（路由辅助线索，非决定性规则）
#         ├── context_inputs / metric_inputs
# 新代码禁止依赖旧 ``supported_intents`` 表达执行场景（§24）。


class RuntimeContextCode(StrEnum):
    """Runtime 已知的运行上下文编码（设计 §19）。

    V1 为固定枚举；未来可由 RuntimeContextRegistry 提供动态集合。
    """

    QUESTION = "question"
    SETTLEMENT_ID = "settlement_id"
    PERSON_ID = "person_id"
    VISIT_ID = "visit_id"
    HOSPITAL_ID = "hospital_id"


class MetricResolutionType(StrEnum):
    """Metric 运行时解析方式（设计 §15）。

    V1 仅正式支持 SOURCE_FIELD / DEFAULT_VALUE；其余为预留扩展。
    """

    SOURCE_FIELD = "SOURCE_FIELD"
    DEFAULT_VALUE = "DEFAULT_VALUE"
    SQL_EXPRESSION = "SQL_EXPRESSION"  # 预留
    DERIVED = "DERIVED"  # 预留
    API = "API"  # 预留
    TOOL = "TOOL"  # 预留
    UNKNOWN = "UNKNOWN"  # 预留


class MetricUnavailableReason(StrEnum):
    """Metric 不可作为 Skill 输入的标准化原因（设计 §37）。"""

    NOT_PUBLISHED = "NOT_PUBLISHED"
    OBJECT_NOT_PUBLISHED = "OBJECT_NOT_PUBLISHED"
    NO_RUNTIME_RESOLVER = "NO_RUNTIME_RESOLVER"
    INVALID_MAPPING = "INVALID_MAPPING"
    RESOLVER_DISABLED = "RESOLVER_DISABLED"  # 预留
    VERSION_UNAVAILABLE = "VERSION_UNAVAILABLE"  # 预留


class ContextInputSpec(BaseModel):
    """运行时上下文输入声明（设计 §8、§19）。

    ``code`` 必须来自 RuntimeContextCode 枚举，而非任意自由文本。
    """

    model_config = ConfigDict(frozen=True)

    code: RuntimeContextCode
    alias: str = Field(default="", max_length=128)
    required: bool = True
    purpose: str = Field(default="", max_length=512)
    description: str = Field(default="", max_length=512)


class MetricInputSpec(BaseModel):
    """Metric 依赖声明（设计 §9、§20）。

    ``metric_code`` 必须来自语义层且 runtime_resolvable=true。
    与旧 InputSpec 同构但显式命名，避免与新执行契约语义混淆。
    """

    model_config = ConfigDict(frozen=True)

    metric_code: str = Field(min_length=1, max_length=256)
    alias: str = Field(default="", max_length=128)
    required: bool = True
    purpose: str = Field(default="", max_length=512)


class CommonInputSpec(BaseModel):
    """公共输入：几乎所有执行场景都需要的数据依赖（设计 §25）。

    必须克制使用——只有「绝大多数场景需要 AND 获取成本合理」才放 Common。
    """

    model_config = ConfigDict(frozen=True)

    context_inputs: list[ContextInputSpec] = Field(default_factory=list)
    metric_inputs: list[MetricInputSpec] = Field(default_factory=list)


# profile_id 规范：kebab-case，Skill 内唯一（设计 §22）
_PROFILE_ID_PATTERN = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


class ExecutionProfileSpec(BaseModel):
    """执行场景（Execution Profile，设计 §5、§21）。

    定义同一 Skill 内「核心能力与主要流程不变、仅数据依赖不同」的一种
    运行配置。Profile 不是独立 Skill，其核心职责是声明该执行路径所需
    的特定数据依赖。
    """

    model_config = ConfigDict(frozen=True)

    profile_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    purpose: str = Field(default="", max_length=512)
    routing_hints: list[str] = Field(default_factory=list)
    context_inputs: list[ContextInputSpec] = Field(default_factory=list)
    metric_inputs: list[MetricInputSpec] = Field(default_factory=list)

    @field_validator("profile_id")
    @classmethod
    def _validate_profile_id(cls, value: str) -> str:
        if not _PROFILE_ID_PATTERN.fullmatch(value):
            raise ValueError(
                "profile_id 必须使用 kebab-case 格式"
                "（小写字母、数字、连字符）"
            )
        return value


class SkillExecutionContract(BaseModel):
    """Skill 执行契约（设计 §4、§16-§17）。

    定义 Skill 在不同执行场景下需要哪些上下文、指标依赖，以及不同
    场景之间数据依赖差异的结构化契约。是 Skill 输入定义的唯一
    Source of Truth（§2.5、§29）；运行时 JSON Schema 自动由此派生（§30）。
    """

    model_config = ConfigDict(frozen=True)

    version: int = Field(default=2, ge=1)
    common: CommonInputSpec = Field(default_factory=CommonInputSpec)
    profiles: list[ExecutionProfileSpec] = Field(default_factory=list)


class MetricRuntimeCapability(BaseModel):
    """Metric 运行时可解析能力（设计 §11-§14）。

    由后端统一判定（SkillInputService），前端/AI/Validator/Runtime
    复用同一结果，禁止四套规则各自判断（§14）。
    """

    model_config = ConfigDict(frozen=True)

    metric_code: str
    status: str
    runtime_resolvable: bool
    resolution_type: MetricResolutionType | None = None
    unavailable_reason: MetricUnavailableReason | None = None
