"""Skill 回归案例池与回归用例内存存储（开发与测试）。

所有读路径返回深拷贝，避免外部修改污染内部状态。案例池按 (tenant_id,
source_qa_turn_id) 去重；回归用例按 (source_type, source_ref, case_type)
唯一。跨租户访问统一返回 None / 抛 NotFound，不泄露存在性。
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock

from src.data_platform.storage.skill.regression_ports import (
    SkillRegressionConflictError,
    SkillRegressionNotFoundError,
)
from src.domain.skill.regression_models import (
    EvalCaseRef,
    SkillEvalCasePoolItem,
    SkillEvalCasePoolStatus,
    SkillRegressionCase,
)


class InMemorySkillRegressionStorage:
    def __init__(self) -> None:
        self._pool: dict[str, SkillEvalCasePoolItem] = {}
        self._regression_cases: dict[str, SkillRegressionCase] = {}
        self._lock = RLock()

    @staticmethod
    def _copy[T](value: T) -> T:
        return value.model_copy(deep=True)  # type: ignore[attr-defined, no-any-return]

    # ── 案例池 ──────────────────────────────────────────────────

    def create_pool_item(
        self, item: SkillEvalCasePoolItem
    ) -> SkillEvalCasePoolItem:
        with self._lock:
            existing = self._find_by_tenant_turn(item.tenant_id, item.source_qa_turn_id)
            if existing is not None:
                return self._copy(existing)
            stored = self._copy(item)
            self._pool[stored.pool_id] = stored
            return self._copy(stored)

    def _find_by_tenant_turn(
        self, tenant_id: str, qa_turn_id: str
    ) -> SkillEvalCasePoolItem | None:
        for item in self._pool.values():
            if (
                item.tenant_id == tenant_id
                and item.source_qa_turn_id == qa_turn_id
            ):
                return item
        return None

    def get_pool_item(
        self, pool_id: str, *, tenant_id: str | None = None
    ) -> SkillEvalCasePoolItem | None:
        with self._lock:
            item = self._pool.get(pool_id)
            if item is None:
                return None
            if tenant_id is not None and item.tenant_id != tenant_id:
                return None
            return self._copy(item)

    def list_pool_items(
        self,
        *,
        tenant_id: str | None = None,
        status: SkillEvalCasePoolStatus | str | None = None,
        error_dimension=None,
        target_skill_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SkillEvalCasePoolItem]:
        with self._lock:
            normalized_status = None if status is None else str(status)
            normalized_dimension = None if error_dimension is None else str(error_dimension)
            items = [
                self._copy(item)
                for item in self._pool.values()
                if (tenant_id is None or item.tenant_id == tenant_id)
                and (normalized_status is None or item.status.value == normalized_status)
                and (
                    normalized_dimension is None
                    or str(item.error_dimension.value) == normalized_dimension
                )
                and (
                    target_skill_id is None
                    or item.source_selected_skill_id == target_skill_id
                )
            ]
        items.sort(key=lambda i: (i.created_at, i.pool_id))
        return items[offset : offset + limit]

    def count_pool_items(self, *, tenant_id: str | None = None) -> int:
        with self._lock:
            return sum(
                1
                for item in self._pool.values()
                if tenant_id is None or item.tenant_id == tenant_id
            )

    def update_pool_item(
        self,
        item: SkillEvalCasePoolItem,
        *,
        expected_revision: int,
        tenant_id: str | None = None,
    ) -> SkillEvalCasePoolItem:
        with self._lock:
            current = self._require_pool(item.pool_id, tenant_id=tenant_id)
            self._check_revision(current, expected_revision)
            stored = self._copy(item)
            self._pool[item.pool_id] = stored
            return self._copy(stored)

    def transform_pool_item(
        self,
        pool_id: str,
        *,
        tenant_id: str,
        transformed_dimension,
        transformed_proposal: dict | None,
        transformed_root_cause: str | None,
        transformed_citations: list[dict],
        transformed_uncertainties: list[str],
        expected_revision: int,
    ) -> SkillEvalCasePoolItem:
        with self._lock:
            current = self._require_pool(pool_id, tenant_id=tenant_id)
            self._check_revision(current, expected_revision)
            updated = current.model_copy(
                update={
                    "status": SkillEvalCasePoolStatus.TRANSFORMED,
                    "transformed_dimension": transformed_dimension,
                    "transformed_proposal": transformed_proposal,
                    "transformed_root_cause": transformed_root_cause,
                    "transformed_citations": list(transformed_citations),
                    "transformed_uncertainties": list(transformed_uncertainties),
                    "revision": current.revision + 1,
                    "updated_at": datetime.now(timezone.utc),
                },
                deep=True,
            )
            self._pool[pool_id] = updated
            return self._copy(updated)

    def confirm_pool_item(
        self,
        pool_id: str,
        *,
        tenant_id: str,
        case_type: str,
        case_id: str,
        expected_revision: int,
    ) -> SkillEvalCasePoolItem:
        with self._lock:
            current = self._require_pool(pool_id, tenant_id=tenant_id)
            ref = EvalCaseRef(case_type=case_type, case_id=case_id)
            # 幂等：已确认到同一目标且 revision 匹配 → 原样返回，不递增
            if (
                current.status == SkillEvalCasePoolStatus.CONFIRMED
                and current.eval_case_ref == ref
                and current.revision == expected_revision
            ):
                return self._copy(current)
            self._check_revision(current, expected_revision)
            if current.status == SkillEvalCasePoolStatus.CONFIRMED:
                raise SkillRegressionConflictError("案例池条目已确认到不同资产")
            updated = current.model_copy(
                update={
                    "status": SkillEvalCasePoolStatus.CONFIRMED,
                    "eval_case_ref": ref,
                    "revision": current.revision + 1,
                    "updated_at": datetime.now(timezone.utc),
                },
                deep=True,
            )
            self._pool[pool_id] = updated
            return self._copy(updated)

    def reject_pool_item(
        self,
        pool_id: str,
        *,
        tenant_id: str,
        reason: str,
        expected_revision: int,
    ) -> SkillEvalCasePoolItem:
        with self._lock:
            current = self._require_pool(pool_id, tenant_id=tenant_id)
            self._check_revision(current, expected_revision)
            updated = current.model_copy(
                update={
                    "status": SkillEvalCasePoolStatus.REJECTED,
                    "rejection_reason": reason,
                    "revision": current.revision + 1,
                    "updated_at": datetime.now(timezone.utc),
                },
                deep=True,
            )
            self._pool[pool_id] = updated
            return self._copy(updated)

    def soft_delete_expired_pool_items(self, *, before: datetime) -> int:
        with self._lock:
            count = 0
            for pool_id, item in list(self._pool.items()):
                if (
                    item.status != SkillEvalCasePoolStatus.CONFIRMED
                    and item.created_at.replace(tzinfo=item.created_at.tzinfo or timezone.utc)
                    < before
                ):
                    self._pool.pop(pool_id, None)
                    count += 1
            return count

    def detach_pool_item_source(
        self, pool_id: str, *, tenant_id: str
    ) -> SkillEvalCasePoolItem:
        with self._lock:
            current = self._require_pool(pool_id, tenant_id=tenant_id)
            updated = current.model_copy(
                update={
                    "source_user_id": "",
                    "question_excerpt": "",
                    "answer_excerpt": "",
                    "comment": "",
                    "revision": current.revision + 1,
                    "updated_at": datetime.now(timezone.utc),
                },
                deep=True,
            )
            self._pool[pool_id] = updated
            return self._copy(updated)

    # ── 回归用例 ────────────────────────────────────────────────

    def create_case(self, case: SkillRegressionCase) -> SkillRegressionCase:
        with self._lock:
            for existing in self._regression_cases.values():
                if (
                    existing.source_type == case.source_type
                    and existing.source_ref == case.source_ref
                    and str(existing.case_type.value) == str(case.case_type.value)
                    and existing.enabled
                ):
                    raise SkillRegressionConflictError(
                        "同一来源与维度的回归用例已存在"
                    )
            stored = self._copy(case)
            self._regression_cases[stored.case_id] = stored
            return self._copy(stored)

    def get_case(self, case_id: str) -> SkillRegressionCase | None:
        with self._lock:
            case = self._regression_cases.get(case_id)
            return None if case is None else self._copy(case)

    def list_cases(
        self,
        *,
        target_skill_id: str | None = None,
        case_type=None,
        enabled_only: bool = False,
    ) -> list[SkillRegressionCase]:
        with self._lock:
            normalized_case_type = None if case_type is None else str(case_type)
            cases = [
                self._copy(case)
                for case in self._regression_cases.values()
                if (target_skill_id is None or case.target_skill_id == target_skill_id)
                and (
                    normalized_case_type is None
                    or str(case.case_type.value) == normalized_case_type
                )
                and (not enabled_only or case.enabled)
            ]
        cases.sort(key=lambda c: (c.created_at, c.case_id))
        return cases

    def count_cases(self) -> int:
        with self._lock:
            return len(self._regression_cases)

    # ── 内部工具 ────────────────────────────────────────────────

    def _require_pool(
        self, pool_id: str, *, tenant_id: str | None = None
    ) -> SkillEvalCasePoolItem:
        item = self._pool.get(pool_id)
        if item is None or (tenant_id is not None and item.tenant_id != tenant_id):
            raise SkillRegressionNotFoundError(f"案例池条目不存在: {pool_id}")
        return item

    @staticmethod
    def _check_revision(
        item: SkillEvalCasePoolItem, expected_revision: int
    ) -> None:
        if item.revision != expected_revision:
            raise SkillRegressionConflictError(
                f"案例池条目 revision 已变化（当前 {item.revision}，期望 {expected_revision}）"
            )
