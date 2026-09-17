"""Tool 领域模型：将现有能力（函数/adapter Protocol）包装为可视化治理的原子能力。

Tool 不重写既有能力，只包装 `target_ref` 指向的既有函数/Protocol 实现；
生命周期与 Skill 版本管理一致：draft → validated → materialized。
"""

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Tool 包装目标只能落在这些既有能力目录内，禁止借 Tool 名义新写业务逻辑。
ALLOWED_TARGET_REF_PREFIXES = (
    "src.runtime.policy_qa.",
    "src.runtime.question_library.",
    "src.adapters.ports.",
    "src.skill_infra.",
    "src.semantic_layer.",
    "src.runtime.flow.",  # 治理 Flow 消费查询（FlowQueryService，既有能力，V3.0 运营问数通道）
)


class ToolContractKind(StrEnum):
    """Tool 的调用契约类型，决定 Registry 如何调用 target_ref。"""

    FUNCTION = "function"
    ADAPTER_PORT = "adapter_port"


class ToolRiskLevel(StrEnum):
    """Tool 风险等级，沿用平台既有分级口径。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolStatus(StrEnum):
    """Tool 治理生命周期状态，镜像 Skill 的 draft/validated/materialized。"""

    DRAFT = "draft"
    VALIDATED = "validated"
    MATERIALIZED = "materialized"


class ToolDefinition(BaseModel):
    """Tool 的静态定义：描述、契约类型、包装目标、风险等级。"""

    model_config = ConfigDict(frozen=True)

    tool_id: str
    name: str
    description: str
    contract_kind: ToolContractKind
    target_ref: str
    risk_level: ToolRiskLevel = ToolRiskLevel.LOW
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    # 执行细节：展示到底层实现——SQL 编译链 / Milvus 检索语句 / 核心公式等静态描述。
    # 仅治理工作台展示用，不是运行时可执行代码。
    execution_detail: str = ""
    tags: list[str] = Field(default_factory=list)

    @field_validator("target_ref")
    @classmethod
    def _target_ref_within_whitelist(cls, value: str) -> str:
        if not value.startswith(ALLOWED_TARGET_REF_PREFIXES):
            raise ValueError(
                f"target_ref 必须指向既有能力白名单目录 {ALLOWED_TARGET_REF_PREFIXES}，"
                "禁止借 Tool 新写业务逻辑"
            )
        return value

    @field_validator("name", "description")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("字段不能为空")
        return value


class ToolVersion(BaseModel):
    """已登记、不可原地修改的 Tool 版本实体。"""

    model_config = ConfigDict(frozen=True)

    version_id: str
    tool_id: str
    semantic_version: str
    definition: ToolDefinition
    status: ToolStatus = ToolStatus.DRAFT
    created_by: str = "system"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
