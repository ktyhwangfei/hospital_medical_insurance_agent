"""Skill 回归案例池与回归用例存储端口（防腐层 Protocol）。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.domain.skill.regression_models import (
    SkillErrorDimension,
    SkillEvalCasePoolItem,
    SkillEvalCasePoolStatus,
    SkillRegressionCase,
)


class SkillRegressionConflictError(ValueError):
    """案例池 revision、状态、唯一性或租户归属发生冲突。"""


class SkillRegressionNotFoundError(LookupError):
    """案例池条目或回归用例不存在（跨租户访问也统一抛此异常，不泄露存在性）。"""


class SkillRegressionStorage(Protocol):
    # ── 案例池 ──────────────────────────────────────────────────

    def create_pool_item(
        self, item: SkillEvalCasePoolItem
    ) -> SkillEvalCasePoolItem: ...

    def get_pool_item(
        self, pool_id: str, *, tenant_id: str | None = None
    ) -> SkillEvalCasePoolItem | None: ...

    def list_pool_items(
        self,
        *,
        tenant_id: str | None = None,
        status: SkillEvalCasePoolStatus | str | None = None,
        error_dimension: SkillErrorDimension | str | None = None,
        target_skill_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SkillEvalCasePoolItem]: ...

    def count_pool_items(self, *, tenant_id: str | None = None) -> int: ...

    def update_pool_item(
        self,
        item: SkillEvalCasePoolItem,
        *,
        expected_revision: int,
        tenant_id: str | None = None,
    ) -> SkillEvalCasePoolItem: ...

    def transform_pool_item(
        self,
        pool_id: str,
        *,
        tenant_id: str,
        transformed_dimension: SkillErrorDimension,
        transformed_proposal: dict | None,
        transformed_root_cause: str | None,
        transformed_citations: list[dict],
        transformed_uncertainties: list[str],
        expected_revision: int,
    ) -> SkillEvalCasePoolItem: ...

    def confirm_pool_item(
        self,
        pool_id: str,
        *,
        tenant_id: str,
        case_type: str,
        case_id: str,
        expected_revision: int,
    ) -> SkillEvalCasePoolItem: ...

    def reject_pool_item(
        self,
        pool_id: str,
        *,
        tenant_id: str,
        reason: str,
        expected_revision: int,
    ) -> SkillEvalCasePoolItem: ...

    def soft_delete_expired_pool_items(self, *, before: datetime) -> int: ...

    def detach_pool_item_source(
        self, pool_id: str, *, tenant_id: str
    ) -> SkillEvalCasePoolItem: ...

    # ── 回归用例 ────────────────────────────────────────────────

    def create_case(self, case: SkillRegressionCase) -> SkillRegressionCase: ...

    def get_case(self, case_id: str) -> SkillRegressionCase | None: ...

    def list_cases(
        self,
        *,
        target_skill_id: str | None = None,
        case_type: SkillErrorDimension | str | None = None,
        enabled_only: bool = False,
    ) -> list[SkillRegressionCase]: ...

    def count_cases(self) -> int: ...
