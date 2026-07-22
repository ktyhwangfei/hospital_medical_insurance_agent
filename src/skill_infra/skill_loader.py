"""
SkillLoader — 动态加载 skills/ 目录下的 skill 包。

约定：
- skills/ 目录下每个子目录是一个 skill
- 每个 skill 必须有 skill_manifest.yaml （含 skill_id, supported_intents 等）
- 每个 skill 的 assembler.py 必须提供 load() 函数，返回 assembler 实例

用法：
    loader = SkillLoader()
    loader.discover()                    # 扫描并加载所有 skill
    skill = loader.get("benefit_pooling_self_pay")
    assembler = skill.assembler          # 获取 assembler 实例
    result = assembler.execute(...)      # 执行 skill
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class LoadedSkill:
    """已加载的 skill 运行时对象。"""
    skill_id: str
    skill_name: str
    assembler: Any                                  # assembler 实例（含 execute 方法）
    manifest: dict[str, Any] = field(default_factory=dict)
    include_keywords: list[str] = field(default_factory=list)
    excluded_intents: list[str] = field(default_factory=list)
    business_action: str = ""                       # BusinessAction 枚举值（如 "explain"）
    business_object: str = ""                       # BusinessObject 枚举值（如 "settlement"）
    needed_objects: list[dict[str, Any]] = field(default_factory=list)  # NEW: semantic layer declarations


class SkillLoader:
    """
    从 SKILLS_DIR 目录扫描并加载所有 skill。

    负责：
    1. 扫描目录发现 skill 包
    2. 动态导入 assembler 模块
    3. 调用 load() 获取 assembler 实例
    4. 读取 manifest 构建路由信息
    """

    def __init__(self, skills_dir: str | None = None):
        if skills_dir is None:
            from src.config.production import SKILLS_DIR
            skills_dir = SKILLS_DIR
        self._skills_dir = Path(skills_dir)
        self._registry: dict[str, LoadedSkill] = {}

    def discover(self) -> dict[str, LoadedSkill]:
        """
        扫描 skills/ 目录，加载所有有效 skill。

        只加载同时包含 skill_manifest.yaml 和 assembler.py 的子目录。
        返回 skill_id → LoadedSkill 的字典。
        """
        if not self._skills_dir.exists():
            logger.warning(f"[SkillLoader] Skills directory not found: {self._skills_dir}")
            return {}

        self._registry = {}

        for entry in sorted(self._skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith("_") or entry.name.startswith("."):
                continue

            manifest_path = entry / "skill_manifest.yaml"
            assembler_path = entry / "assembler.py"

            if not manifest_path.exists() or not assembler_path.exists():
                continue

            try:
                skill = self._load_skill(entry.name, manifest_path, assembler_path)
                self._registry[skill.skill_id] = skill
                logger.info(
                    "[SkillLoader] Loaded skill: id=%s name=%s keywords=%s",
                    skill.skill_id,
                    skill.skill_name,
                    skill.include_keywords,
                )
            except Exception:
                logger.exception(
                    "[SkillLoader] Failed to load skill from '%s'", entry
                )

        logger.info("[SkillLoader] Discovered %d skills", len(self._registry))
        return self._registry

    def _load_skill(
        self, dir_name: str, manifest_path: Path, assembler_path: Path
    ) -> LoadedSkill:
        """加载单个 skill：读取 manifest + 动态导入 assembler。"""
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        skill_id = manifest.get("skill_id", "") or dir_name
        skill_name = manifest.get("skill_name", "") or dir_name
        include_keywords = list(manifest.get("supported_intents", []))
        excluded_intents = list(manifest.get("excluded_intents", []))
        business_action = str(manifest.get("business_action", "") or "")
        business_object = str(manifest.get("business_object", "") or "")
        needed_objects = list(manifest.get("needed_objects", []) or [])

        # 动态导入 assembler 模块
        module_name = f"skills.{dir_name}.assembler"
        module = importlib.import_module(module_name)

        # 调用约定的 load() 入口
        if not hasattr(module, "load"):
            raise ImportError(
                f"Skill '{dir_name}': assembler.py must define a load() function"
            )
        assembler = module.load()

        return LoadedSkill(
            skill_id=skill_id,
            skill_name=skill_name,
            assembler=assembler,
            manifest=manifest,
            include_keywords=include_keywords,
            excluded_intents=excluded_intents,
            business_action=business_action,
            business_object=business_object,
            needed_objects=needed_objects,
        )

    def get(self, skill_id: str) -> Optional[LoadedSkill]:
        """按 skill_id 获取已加载的 skill。"""
        return self._registry.get(skill_id)

    def get_all(self) -> dict[str, LoadedSkill]:
        """获取所有已加载的 skill。"""
        return dict(self._registry)

    def rediscover(self) -> dict[str, LoadedSkill]:
        """
        热重载：清空当前注册表并重新扫描 skills/ 目录。

        用于运行时新增 skill 目录后无需重启服务即可发现。
        调用方通过 infra_skill_routes 的 refresh 端点触发。

        Returns:
            更新后的 skill_id → LoadedSkill 字典
        """
        logger.info("[SkillLoader] Rediscovering skills (hot-reload)...")
        self._registry.clear()
        return self.discover()

    def unload(self, skill_id: str) -> bool:
        """从注册表中移除指定 skill（用于 skill 下线）。

        Args:
            skill_id: 要移除的 skill ID

        Returns:
            True 如果成功移除，False 如果 skill 不存在
        """
        if skill_id not in self._registry:
            logger.warning("[SkillLoader] Cannot unload unknown skill: %s", skill_id)
            return False
        del self._registry[skill_id]
        logger.info("[SkillLoader] Unloaded skill: %s", skill_id)
        return True

    @property
    def registry(self) -> dict[str, LoadedSkill]:
        return self._registry


# ── 全局单例 ────────────────────────────────────────────────────

_loader: SkillLoader | None = None


def get_loader() -> SkillLoader:
    """获取全局 SkillLoader 单例（自动发现）。"""
    global _loader
    if _loader is None:
        _loader = SkillLoader()
        _loader.discover()
    return _loader


def refresh_loader() -> dict[str, LoadedSkill]:
    """热重载全局 SkillLoader，重新扫描 skills/ 目录。

    Returns:
        更新后的 skill_id → LoadedSkill 字典
    """
    global _loader
    if _loader is None:
        _loader = SkillLoader()
        _loader.discover()
        return _loader.registry
    return _loader.rediscover()
