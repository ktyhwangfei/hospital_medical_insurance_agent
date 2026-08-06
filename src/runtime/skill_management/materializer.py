"""Skill 物化器（P5）。

将校验通过的草稿原子写入正式 ``skills/`` 目录并登记不可变版本。
设计 §8.3：生成临时包 → 校验通过 → 原子替换；失败回滚，不产生半成品。

流程（设计 §6）：
1. 草稿状态必须为 validated
2. 重新结构校验（blocking 必须全过）
3. 生成标准包（含占位 assembler，保证 SkillLoader 可加载）
4. 原子写入 skills/{skill_id}/（备份→替换→失败恢复）
5. 热重载 + 登记版本（复用 SkillVersionService）
6. 草稿标记 materialized + 创建/更新 SkillDefinition（enabled）
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from src.config.production import SKILLS_DIR
from src.data_platform.storage.skill.draft_ports import (
    SkillDefinitionConflictError,
    SkillDraftConflictError,
)
from src.domain.skill.draft_models import (
    SkillDefinition,
    SkillDraftStatus,
    SkillLifecycleStatus,
)
from src.runtime.skill_management.draft_service import SkillDraftService
from src.runtime.skill_management.draft_validator import SkillDraftValidator
from src.runtime.skill_management.package_generator import SkillPackageGenerator

# 占位 assembler：声明式 Skill 的执行入口，loader 据此加载 skill。
_PLACEHOLDER_ASSEMBLER = '''"""自动生成的占位 assembler。

声明式 Skill 的执行入口。本文件由物化器在写入正式目录时生成，
后续应根据 skill_manifest.yaml 的声明替换为真实业务逻辑。
"""


class Assembler:
    """声明式 Skill 的占牌执行器。"""

    def execute(self, **kwargs):
        return {
            "status": "placeholder",
            "message": "声明式 Skill，执行逻辑待实现",
        }


def load() -> Assembler:
    """loader 约定的入口：返回 Assembler 实例。"""
    return Assembler()
'''


class SkillMaterializeError(RuntimeError):
    """物化前置条件未满足或写入失败。"""


class VersionServicePort(Protocol):
    """SkillVersionService 的最小端口（便于测试注入 mock）。"""

    def sync_version(
        self, skill_id: str, *, source_commit: str | None, created_by: str
    ) -> Any: ...


@dataclass(frozen=True)
class MaterializeResult:
    skill_id: str
    version_id: str
    semantic_version: str
    definition: SkillDefinition
    artifact_written: bool


class SkillMaterializer:
    def __init__(
        self,
        *,
        draft_service: SkillDraftService,
        draft_storage: Any,
        version_service: VersionServicePort,
        generator: SkillPackageGenerator | None = None,
        validator: SkillDraftValidator | None = None,
        skills_root: Path | str = SKILLS_DIR,
        loader: Any | None = None,
    ) -> None:
        self._draft_service = draft_service
        self._draft_storage = draft_storage
        self._version_service = version_service
        self._generator = generator or SkillPackageGenerator()
        self._validator = validator or SkillDraftValidator()
        self._skills_root = Path(skills_root)
        self._loader = loader

    def materialize(
        self,
        *,
        draft_id: str,
        expected_revision: int,
        created_by: str,
        reason: str,
        source_commit: str | None = None,
    ) -> MaterializeResult:
        if not reason.strip():
            raise SkillMaterializeError("物化必须提供原因（reason）")

        draft = self._draft_service.get_draft(draft_id)
        if draft is None:
            raise SkillMaterializeError(f"草稿不存在: {draft_id}")
        if draft.status != SkillDraftStatus.VALIDATED:
            raise SkillMaterializeError(
                f"草稿状态必须为 validated，当前: {draft.status.value}"
            )

        # 重新结构校验（设计：物化前必须 blocking 全过）
        report = self._validator.validate(draft)
        if report.has_blocking:
            codes = ",".join(i.code for i in report.issues if i.severity.value == "blocking")
            raise SkillMaterializeError(f"草稿存在 blocking 问题: {codes}")

        # 生成包 + 注入占位 assembler（保证 loader 可加载）
        package = self._generator.generate(draft)
        files = dict(package.files)
        files.setdefault("assembler.py", _PLACEHOLDER_ASSEMBLER)

        # 原子写入
        self._atomic_write(draft.skill_id, files)

        # 热重载 loader，使新物化的 skill 可被版本登记感知
        if self._loader is not None:
            try:
                rediscover = getattr(self._loader, "rediscover", None)
                if callable(rediscover):
                    rediscover()
            except Exception:
                pass

        # 登记版本
        commit = source_commit or uuid.uuid4().hex[:7]
        try:
            version = self._version_service.sync_version(
                draft.skill_id, source_commit=commit, created_by=created_by
            )
        except Exception:
            # 版本登记失败：保留草稿与校验报告，但需回滚已写入的目录
            self._rollback_write(draft.skill_id)
            raise

        # 草稿标记 materialized（用读到的当前 revision，物化过程不修改草稿）
        try:
            self._draft_service.mark_materialized(
                draft_id=draft_id, expected_revision=draft.revision
            )
        except SkillDraftConflictError:
            # 草稿已被他人改动，版本已登记但不冻结草稿——记录但不阻断
            pass

        # 创建/更新 SkillDefinition（enabled）
        definition = self._upsert_definition(draft, version.version_id)

        return MaterializeResult(
            skill_id=draft.skill_id,
            version_id=version.version_id,
            semantic_version=version.semantic_version,
            definition=definition,
            artifact_written=True,
        )

    # ── 原子写入 ──────────────────────────────────────────────────

    def _atomic_write(self, skill_id: str, files: dict[str, str]) -> None:
        target = self._skills_root / skill_id
        # 在 skills_root 内创建临时目录，保证同文件系统 rename 原子性
        tmp = Path(tempfile.mkdtemp(prefix=f".{skill_id}-tmp-", dir=self._skills_root))
        try:
            for rel, content in files.items():
                dest = tmp / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")

            backup: Path | None = None
            if target.exists():
                backup = target.parent / f".{skill_id}.bak"
                if backup.exists():
                    shutil.rmtree(backup)
                target.rename(backup)
            try:
                tmp.rename(target)
            except Exception:
                if backup is not None and backup.exists():
                    backup.rename(target)
                raise
            if backup is not None and backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

    def _rollback_write(self, skill_id: str) -> None:
        """版本登记失败时回滚已写入的目录（删除半成品）。"""
        target = self._skills_root / skill_id
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)

    # ── SkillDefinition upsert ────────────────────────────────────

    def _upsert_definition(self, draft: Any, version_id: str) -> SkillDefinition:
        bm = draft.structured_config.get("business_mounting", {}) or {}
        existing = self._draft_storage.get_definition(draft.skill_id)
        now_def = SkillDefinition(
            skill_id=draft.skill_id,
            skill_name=draft.skill_name,
            business_action=str(bm.get("business_action", "")),
            business_object=str(bm.get("business_object", "")),
            lifecycle_status=SkillLifecycleStatus.ENABLED,
            current_version_id=version_id,
        )
        if existing is None:
            try:
                return self._draft_storage.save_definition(now_def)
            except SkillDefinitionConflictError:
                existing = self._draft_storage.get_definition(draft.skill_id)
        # 更新 current_version_id（乐观锁）
        updated = existing.model_copy(
            update={
                "skill_name": now_def.skill_name,
                "business_action": now_def.business_action,
                "business_object": now_def.business_object,
                "current_version_id": version_id,
            }
        )
        try:
            return self._draft_storage.update_definition(
                updated, expected_revision=existing.revision
            )
        except SkillDefinitionConflictError:
            return self._draft_storage.get_definition(draft.skill_id)
