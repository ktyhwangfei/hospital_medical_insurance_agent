"""Workflow 治理配置解析：平台默认（definitions）← 全局覆盖 ← 院区覆盖。

设计目标（一套产品多院复用）：院区个性化只落在配置层，代码里不出现
"这家医院特殊" 的分支。优先级从低到高：

1. 代码声明（definitions.py 的 intent_keywords，默认启用）
2. 全局覆盖行（hospital_code=""）
3. 院区覆盖行（hospital_code=<院区编码>）
4. 运维 kill-switch（环境变量 WORKFLOW_DISABLED，最高优先，用于故障时
   不依赖配置库即可下线）

院区身份来源：部署级 env `PLATFORM_HOSPITAL_CODE`（A 形态：一院一套部署）。
请求级院区解析（B 形态：一套实例多院）留作后续，接缝已在存储层预留。
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, ConfigDict

from src.data_platform.storage.workflow_config.factory import get_workflow_config_storage
from src.data_platform.storage.workflow_config.ports import WorkflowConfigStorage
from src.domain.workflow.models import WorkflowConfigOverride
from src.runtime.workflow.definitions import ALL_WORKFLOWS
from src.shared.hospital_scope import current_hospital_code


class UnknownWorkflowError(KeyError):
    """配置写入引用了未登记的工作流。"""


class EffectiveWorkflowConfig(BaseModel):
    """单个工作流的生效配置（供路由/目录/模式入口统一消费）。"""

    model_config = ConfigDict(frozen=True)

    workflow_id: str
    enabled: bool
    intent_keywords: list[str]
    source: str  # default | global | hospital（可叠加 +env_disabled）


def _env_disabled_ids() -> set[str]:
    raw = os.getenv("WORKFLOW_DISABLED", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


class WorkflowConfigService:
    def __init__(self, storage: WorkflowConfigStorage | None = None) -> None:
        self._storage = storage or get_workflow_config_storage()

    def list_overrides(self) -> list[WorkflowConfigOverride]:
        return self._storage.list_overrides()

    def get_override(self, hospital_code: str, workflow_id: str) -> WorkflowConfigOverride | None:
        for row in self._storage.list_overrides():
            if row.workflow_id == workflow_id and row.hospital_code == hospital_code:
                return row
        return None

    def set_override(
        self,
        workflow_id: str,
        *,
        enabled: bool,
        intent_keywords: list[str] | None,
        hospital_code: str = "",
        updated_by: str = "",
    ) -> WorkflowConfigOverride:
        if workflow_id not in {d.workflow_id for d in ALL_WORKFLOWS}:
            raise UnknownWorkflowError(workflow_id)
        return self._storage.upsert_override(
            WorkflowConfigOverride(
                workflow_id=workflow_id,
                hospital_code=hospital_code,
                enabled=enabled,
                intent_keywords=intent_keywords,
                updated_by=updated_by,
            )
        )

    def effective(self, hospital_code: str = "") -> dict[str, EffectiveWorkflowConfig]:
        """全部工作流的生效配置（覆盖行量级小，全量解析即可）。"""
        rows = {
            (row.workflow_id, row.hospital_code): row for row in self._storage.list_overrides()
        }
        disabled = _env_disabled_ids()
        result: dict[str, EffectiveWorkflowConfig] = {}
        for definition in ALL_WORKFLOWS:
            current = EffectiveWorkflowConfig(
                workflow_id=definition.workflow_id,
                enabled=True,
                intent_keywords=list(definition.intent_keywords),
                source="default",
            )
            for code, label in (("", "global"), (hospital_code, "hospital")):
                if label == "hospital" and not hospital_code:
                    continue  # 院区身份为空时不存在院区行
                override = rows.get((definition.workflow_id, code))
                if override is not None:
                    current = self._apply(current, override, label)
            if definition.workflow_id in disabled:
                current = current.model_copy(
                    update={"enabled": False, "source": f"{current.source}+env_disabled"}
                )
            result[definition.workflow_id] = current
        return result

    @staticmethod
    def _apply(
        base: EffectiveWorkflowConfig, override: WorkflowConfigOverride, label: str
    ) -> EffectiveWorkflowConfig:
        return EffectiveWorkflowConfig(
            workflow_id=base.workflow_id,
            enabled=override.enabled,
            intent_keywords=(
                base.intent_keywords
                if override.intent_keywords is None
                else list(override.intent_keywords)
            ),
            source=label,
        )


@lru_cache(maxsize=1)
def get_workflow_config_service() -> WorkflowConfigService:
    return WorkflowConfigService()
