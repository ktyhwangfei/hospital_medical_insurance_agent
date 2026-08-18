"""Skill 草稿应用服务。

负责草稿的创建（模板/复制）、保存、删除与列表。导入来源见 P3 的
``SkillImportService``。所有写操作经存储端口持久化，携带乐观锁。

structured_config 约定结构（随 P2/P4 扩展）::

    {
        "basic": {"skill_id", "skill_name", "description", "owner"},
        "business_mounting": {
            "business_action", "business_object",
            "include_keywords": [...], "excluded_intents": [...]
        },
        "inputs": [...],          # P4 输入指标契约
        "schemas": {...},          # P2 输入/输出 Schema
    }
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from src.config.production import SKILLS_DIR
from src.data_platform.storage.skill.draft_ports import (
    SkillDraftConflictError,
    SkillDraftNotFoundError,
)
from src.domain.skill.draft_models import (
    SkillDraft,
    SkillDraftSourceType,
    SkillDraftStatus,
)
from src.runtime.skill_management.ai_authoring.schemas import (
    SkillAIGenerationResponse,
)

# 复制源 Skill 时纳入 raw_files 的文件扩展名/文件名（排除脚本/缓存/敏感内容）
_COPY_INCLUDE_FILES = {
    "SKILL.md",
    "skill_manifest.yaml",
    "config.yaml",
    "README.md",
}
_COPY_INCLUDE_DIRS = ("schemas", "templates", "references")
_COPY_MAX_FILE_BYTES = 256 * 1024  # 单文件 256KB 上限，避免复制巨型文件


class SkillLoaderPort(Protocol):
    """SkillLoader 的最小端口，便于服务层解耦与测试注入。"""

    def get(self, skill_id: str) -> Any | None: ...


class SkillDraftService:
    """草稿创建、保存、删除、复制。"""

    def __init__(
        self,
        storage: Any,
        *,
        loader: SkillLoaderPort | None = None,
        skills_root: Path | str = SKILLS_DIR,
    ) -> None:
        self._storage = storage
        self._loader = loader
        self._skills_root = Path(skills_root)

    # ── 创建 ──────────────────────────────────────────────────────

    def create_from_template(
        self,
        *,
        skill_id: str,
        skill_name: str,
        created_by: str,
        description: str = "",
        owner: str = "",
        business_action: str = "",
        business_object: str = "",
        include_keywords: list[str] | None = None,
        excluded_intents: list[str] | None = None,
        execution_contract: dict[str, Any] | None = None,
    ) -> SkillDraft:
        """从空模板创建草稿。"""
        structured_config = self._build_template_config(
            skill_id=skill_id,
            skill_name=skill_name,
            description=description,
            owner=owner,
            business_action=business_action,
            business_object=business_object,
            include_keywords=include_keywords or [],
            excluded_intents=excluded_intents or [],
            execution_contract=execution_contract,
        )
        return self._persist_new(
            skill_id=skill_id,
            skill_name=skill_name,
            source_type=SkillDraftSourceType.TEMPLATE,
            created_by=created_by,
            structured_config=structured_config,
        )

    def copy_skill(
        self,
        *,
        source_skill_id: str,
        new_skill_id: str,
        created_by: str,
    ) -> SkillDraft:
        """复制正式 Skill 为草稿。

        复制结构化配置与文件内容（schemas/templates/references + 关键 YAML），
        不复制版本历史、评测、发布、审计与敏感配置（设计 §4.3）。
        源 Skill 不存在时抛 ``SkillDraftNotFoundError``。
        """
        if self._loader is None:
            raise RuntimeError("复制需要 SkillLoader，未注入")
        source = self._loader.get(source_skill_id)
        if source is None:
            raise SkillDraftNotFoundError(
                f"源 Skill 不存在: {source_skill_id}"
            )
        structured_config = self._build_template_config(
            skill_id=new_skill_id,
            skill_name=getattr(source, "skill_name", new_skill_id),
            description=str(
                getattr(source, "manifest", {}).get("description", "")
            ),
            owner=str(getattr(source, "manifest", {}).get("owner", "")),
            business_action=getattr(source, "business_action", "") or "",
            business_object=getattr(source, "business_object", "") or "",
            include_keywords=list(getattr(source, "include_keywords", []) or []),
            excluded_intents=list(getattr(source, "excluded_intents", []) or []),
            execution_contract=None,
        )
        raw_files = self._read_source_files(source_skill_id)
        return self._persist_new(
            skill_id=new_skill_id,
            skill_name=structured_config["basic"]["skill_name"],
            source_type=SkillDraftSourceType.COPY,
            created_by=created_by,
            structured_config=structured_config,
            source_skill_id=source_skill_id,
            raw_files=raw_files,
        )

    def create_from_ai(
        self,
        *,
        proposal: SkillAIGenerationResponse,
        created_by: str,
        draft_id: str | None = None,
    ) -> SkillDraft:
        """人工接受后单次原子保存 AI_GENERATED 草稿。"""

        deterministic_draft_id = self.ai_draft_id(proposal.generation_id)
        if draft_id is not None and draft_id != deterministic_draft_id:
            raise SkillDraftConflictError("AI 草稿 ID 与 generation_id 不一致")
        config = proposal.structured_config.model_dump(mode="json")
        basic = config["basic"]
        generation_meta = {
            "generation_id": proposal.generation_id,
            "proposal_hash": proposal.proposal_hash,
            "provenance": proposal.provenance.model_dump(mode="json"),
            "citations": [
                {
                    "source_type": item.source_type,
                    "source_id": item.source_id,
                    "summary": item.summary,
                }
                for item in proposal.citations
            ],
            "uncertainties": list(proposal.uncertainties),
        }
        raw_files = dict(proposal.raw_files)
        raw_files["__generation_meta__.json"] = json.dumps(
            generation_meta,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            return self._persist_new(
                skill_id=str(basic["skill_id"]),
                skill_name=str(basic["skill_name"]),
                source_type=SkillDraftSourceType.AI_GENERATED,
                created_by=created_by,
                structured_config=config,
                raw_files=raw_files,
                draft_id=deterministic_draft_id,
            )
        except SkillDraftConflictError as exc:
            existing = self._storage.get_draft(deterministic_draft_id)
            if existing is not None and self._matches_ai_proposal(existing, proposal):
                return existing
            raise SkillDraftConflictError(
                "generation_id 已关联不同的 AI proposal 草稿"
            ) from exc

    @staticmethod
    def ai_draft_id(generation_id: str) -> str:
        digest = hashlib.sha256(generation_id.encode("utf-8")).hexdigest()
        return f"draft-{digest[:12]}"

    @staticmethod
    def _matches_ai_proposal(
        draft: SkillDraft, proposal: SkillAIGenerationResponse
    ) -> bool:
        if draft.source_type != SkillDraftSourceType.AI_GENERATED:
            return False
        raw_metadata = draft.raw_files.get("__generation_meta__.json")
        if not isinstance(raw_metadata, str):
            return False
        try:
            metadata = json.loads(raw_metadata)
        except (json.JSONDecodeError, TypeError):
            return False
        return (
            isinstance(metadata, dict)
            and set(metadata)
            == {
                "generation_id",
                "proposal_hash",
                "provenance",
                "citations",
                "uncertainties",
            }
            and metadata.get("generation_id") == proposal.generation_id
            and metadata.get("proposal_hash") == proposal.proposal_hash
        )

    # ── 读写 ──────────────────────────────────────────────────────

    def get_draft(self, draft_id: str) -> SkillDraft | None:
        return self._storage.get_draft(draft_id)

    def list_drafts(
        self,
        *,
        include_deleted: bool = False,
        skill_id: str | None = None,
        status: SkillDraftStatus | None = None,
    ) -> list[SkillDraft]:
        return self._storage.list_drafts(
            include_deleted=include_deleted,
            skill_id=skill_id,
            status=status,
        )

    def save_draft(
        self,
        *,
        draft_id: str,
        structured_config: dict[str, Any],
        expected_revision: int,
        raw_files: dict[str, str] | None = None,
        status: SkillDraftStatus | None = None,
    ) -> SkillDraft:
        """保存草稿（更新 structured_config/raw_files/status），乐观锁。

        保存操作会将草稿状态重置为 editing（除非显式传入 status），
        因为内容变化后需要重新校验（设计 §6 草稿可反复编辑）。
        """
        existing = self._storage.get_draft(draft_id)
        if existing is None:
            raise SkillDraftNotFoundError(f"草稿不存在: {draft_id}")
        update: dict[str, Any] = {
            "structured_config": structured_config,
            "updated_at": datetime.now(timezone.utc),
        }
        if raw_files is not None:
            update["raw_files"] = raw_files
        update["status"] = status if status is not None else SkillDraftStatus.EDITING
        update["skill_name"] = str(
            structured_config.get("basic", {}).get("skill_name")
            or existing.skill_name
        )
        update["revision"] = expected_revision + 1
        updated = existing.model_copy(update=update)
        return self._storage.update_draft(updated, expected_revision=expected_revision)

    def record_validation(
        self,
        *,
        draft_id: str,
        validation_report: dict[str, Any],
        expected_revision: int,
        blocking_ok: bool,
    ) -> SkillDraft:
        """记录校验结果并推进状态（P2 校验器调用）。blocking_ok=True→validated。"""
        existing = self._storage.get_draft(draft_id)
        if existing is None:
            raise SkillDraftNotFoundError(f"草稿不存在: {draft_id}")
        updated = existing.model_copy(
            update={
                "validation_report": validation_report,
                "status": SkillDraftStatus.VALIDATED
                if blocking_ok
                else SkillDraftStatus.EDITING,
                "revision": expected_revision + 1,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        return self._storage.update_draft(updated, expected_revision=expected_revision)

    def mark_materialized(
        self, *, draft_id: str, expected_revision: int
    ) -> SkillDraft:
        """P5 物化成功后调用：冻结草稿为 materialized。"""
        existing = self._storage.get_draft(draft_id)
        if existing is None:
            raise SkillDraftNotFoundError(f"草稿不存在: {draft_id}")
        updated = existing.model_copy(
            update={
                "status": SkillDraftStatus.MATERIALIZED,
                "revision": expected_revision + 1,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        return self._storage.update_draft(updated, expected_revision=expected_revision)

    def delete_draft(self, *, draft_id: str, expected_revision: int) -> SkillDraft:
        return self._storage.delete_draft(draft_id, expected_revision=expected_revision)

    # ── 内部 ──────────────────────────────────────────────────────

    def _persist_new(
        self,
        *,
        skill_id: str,
        skill_name: str,
        source_type: SkillDraftSourceType,
        created_by: str,
        structured_config: dict[str, Any],
        source_skill_id: str | None = None,
        raw_files: dict[str, str] | None = None,
        draft_id: str | None = None,
    ) -> SkillDraft:
        now = datetime.now(timezone.utc)
        draft = SkillDraft(
            draft_id=draft_id or f"draft-{uuid.uuid4().hex[:12]}",
            skill_id=skill_id,
            skill_name=skill_name,
            source_type=source_type,
            source_skill_id=source_skill_id,
            structured_config=structured_config,
            raw_files=raw_files or {},
            status=SkillDraftStatus.EDITING,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        try:
            return self._storage.save_draft(draft)
        except SkillDraftConflictError as exc:
            raise SkillDraftConflictError(
                f"草稿 ID 冲突，请重试: {draft.draft_id}"
            ) from exc

    @staticmethod
    def _build_template_config(
        *,
        skill_id: str,
        skill_name: str,
        description: str,
        owner: str,
        business_action: str,
        business_object: str,
        include_keywords: list[str],
        excluded_intents: list[str],
        execution_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        config: dict[str, Any] = {
            "basic": {
                "skill_id": skill_id,
                "skill_name": skill_name,
                "description": description,
                "owner": owner,
            },
            "business_mounting": {
                "business_action": business_action,
                "business_object": business_object,
                "include_keywords": list(include_keywords),
                "excluded_intents": list(excluded_intents),
            },
            "inputs": [],
            "schemas": {},
        }
        # 执行契约仅在显式传入时落键，保持旧草稿向后兼容（不写入空键）。
        if execution_contract is not None:
            config["execution_contract"] = execution_contract
        return config

    def _read_source_files(self, skill_id: str) -> dict[str, str]:
        """读取源 Skill 目录的关键文件为 raw_files（复制用）。"""
        source_dir = self._skills_root / skill_id
        if not source_dir.exists():
            return {}
        files: dict[str, str] = {}
        for name in _COPY_INCLUDE_FILES:
            path = source_dir / name
            if path.is_file() and path.stat().st_size <= _COPY_MAX_FILE_BYTES:
                files[name] = path.read_text(encoding="utf-8")
        for sub in _COPY_INCLUDE_DIRS:
            sub_dir = source_dir / sub
            if not sub_dir.is_dir():
                continue
            for path in sub_dir.rglob("*"):
                if not path.is_file():
                    continue
                if path.stat().st_size > _COPY_MAX_FILE_BYTES:
                    continue
                rel = path.relative_to(source_dir).as_posix()
                files[rel] = path.read_text(encoding="utf-8")
        return files
