"""Skill 生命周期服务（P6）。

管理正式 SkillDefinition 的 enabled/disabled/archived 状态转换（设计 §6）：
- disable：解除 Test Active（尽力退役 active release），定义/版本/审计保留
- restore：disabled → enabled
- archive：→ archived（终态，默认不参与路由）

disable 与 SkillRelease 的联动：若注入 governance_service，disable 时把该 Skill
在 test 环境的 active release 退役（retired）。联动失败不阻断 definition 状态转换。

审计：状态转换记录 actor/前后状态/原因（P6 用日志占位，复用 security/audit 见 D6）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Protocol

from src.data_platform.storage.skill.draft_ports import (
    SkillDefinitionConflictError,
    SkillDefinitionNotFoundError,
)
from src.domain.skill.draft_models import (
    SkillDefinition,
    SkillLifecycleStatus,
)

logger = logging.getLogger(__name__)


class SkillLifecycleError(RuntimeError):
    """非法生命周期转换或前置条件未满足。"""


class GovernancePort(Protocol):
    """SkillGovernanceService 的最小端口（可选注入，用于 disable 联动）。"""

    def list_active_releases(self, skill_id: str, environment: str) -> list[Any]: ...

    def find_release(self, skill_id: str, release_id: str) -> Any | None: ...


class SkillLifecycleService:
    def __init__(
        self,
        *,
        definition_storage: Any,
        governance_service: GovernancePort | None = None,
    ) -> None:
        self._storage = definition_storage
        self._governance = governance_service

    def disable(
        self, *, skill_id: str, reason: str, actor: str, expected_revision: int
    ) -> SkillDefinition:
        definition = self._require(skill_id)
        if definition.lifecycle_status != SkillLifecycleStatus.ENABLED:
            raise SkillLifecycleError(
                f"只有 enabled 定义可停用，当前: {definition.lifecycle_status.value}"
            )
        # 尽力退役 test active release（不阻断）
        self._try_retire_active_releases(skill_id, actor)
        now = datetime.now(timezone.utc)
        updated = definition.model_copy(
            update={
                "lifecycle_status": SkillLifecycleStatus.DISABLED,
                "disabled_at": now,
                "revision": expected_revision + 1,
                "updated_at": now,
            }
        )
        result = self._update(updated, expected_revision)
        self._audit("disable", skill_id, actor, reason, "enabled", "disabled")
        return result

    def restore(
        self, *, skill_id: str, reason: str, actor: str, expected_revision: int
    ) -> SkillDefinition:
        definition = self._require(skill_id)
        if definition.lifecycle_status != SkillLifecycleStatus.DISABLED:
            raise SkillLifecycleError(
                f"只有 disabled 定义可恢复，当前: {definition.lifecycle_status.value}"
            )
        now = datetime.now(timezone.utc)
        updated = definition.model_copy(
            update={
                "lifecycle_status": SkillLifecycleStatus.ENABLED,
                "disabled_at": None,
                "revision": expected_revision + 1,
                "updated_at": now,
            }
        )
        result = self._update(updated, expected_revision)
        self._audit("restore", skill_id, actor, reason, "disabled", "enabled")
        return result

    def archive(
        self, *, skill_id: str, reason: str, actor: str, expected_revision: int
    ) -> SkillDefinition:
        definition = self._require(skill_id)
        if definition.lifecycle_status == SkillLifecycleStatus.ARCHIVED:
            raise SkillLifecycleError("定义已归档，不可重复归档")
        # 尽力退役 active release
        self._try_retire_active_releases(skill_id, actor)
        now = datetime.now(timezone.utc)
        updated = definition.model_copy(
            update={
                "lifecycle_status": SkillLifecycleStatus.ARCHIVED,
                "archived_at": now,
                "revision": expected_revision + 1,
                "updated_at": now,
            }
        )
        result = self._update(updated, expected_revision)
        self._audit(
            "archive",
            skill_id,
            actor,
            reason,
            definition.lifecycle_status.value,
            "archived",
        )
        return result

    # ── 内部 ──────────────────────────────────────────────────────

    def _require(self, skill_id: str) -> SkillDefinition:
        definition = self._storage.get_definition(skill_id)
        if definition is None:
            raise SkillDefinitionNotFoundError(f"定义不存在: {skill_id}")
        return definition

    def _update(
        self, definition: SkillDefinition, expected_revision: int
    ) -> SkillDefinition:
        try:
            return self._storage.update_definition(
                definition, expected_revision=expected_revision
            )
        except SkillDefinitionConflictError as exc:
            raise SkillLifecycleError("定义 revision 已变化，请刷新后重试") from exc

    def _try_retire_active_releases(self, skill_id: str, actor: str) -> None:
        """尽力退役该 Skill 在 test 环境的 active release（设计 §6 停用解除 Test Active）。"""
        if self._governance is None:
            return
        try:
            actives = self._governance.list_active_releases(skill_id, "test")
        except Exception:
            logger.exception("列出 active release 失败，跳过退役: %s", skill_id)
            return
        for release in actives:
            try:
                current = self._governance.find_release(skill_id, release.release_id)
                if current is None:
                    continue
                # governance 域负责实际退役转换；这里仅触发，由 governance_service 处理
                # 若 governance_service 提供 retire_release，则调用
                retire = getattr(self._governance, "retire_release", None)
                if callable(retire):
                    retire(skill_id, release.release_id, expected_revision=current.revision)
            except Exception:
                logger.exception("退役 release 失败: %s/%s", skill_id, release.release_id)

    @staticmethod
    def _audit(
        action: str,
        skill_id: str,
        actor: str,
        reason: str,
        before: str,
        after: str,
    ) -> None:
        logger.info(
            "skill_lifecycle action=%s skill_id=%s actor=%s before=%s after=%s reason=%s",
            action,
            skill_id,
            actor,
            before,
            after,
            reason,
        )
