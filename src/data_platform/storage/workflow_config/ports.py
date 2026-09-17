"""Workflow 治理配置存储端口：院区/平台覆盖（关键词 + 启停）。

覆盖行按 (workflow_id, hospital_code) 唯一；读取面全量返回（行数为
工作流数 × 院区数，量级极小），院区优先级由运行时解析层裁决。
"""

from __future__ import annotations

from typing import Protocol

from src.domain.workflow.models import WorkflowConfigOverride


class WorkflowConfigStorage(Protocol):
    def list_overrides(self) -> list[WorkflowConfigOverride]:
        """全量覆盖行（含平台默认行 hospital_code=""）。"""
        ...

    def upsert_override(self, override: WorkflowConfigOverride) -> WorkflowConfigOverride:
        """按 (workflow_id, hospital_code) 幂等写入并回读。"""
        ...
