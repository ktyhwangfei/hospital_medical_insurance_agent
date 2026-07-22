"""
SkillRouter — 将用户问题路由到对应的 skill。

依赖 SkillLoader 从 skills/ 目录动态发现所有 skill，
读取各 skill 的 manifest 构建路由表，无需硬编码。

新增 skill 时：
1. 创建 skills/<skill_id>/ 目录
2. 创建 skill_manifest.yaml（含 supported_intents, excluded_intents）
3. 创建 assembler.py（含 load() 函数）
4. 无需修改本文件

v2 升级：
- 路由实现委托给 unified_router.py，基于评分排序而非 first-match-wins
- 旧 route_question() 保持签名和返回类型不变（向后兼容）
- 新增 route_question_with_scores() 返回排序后的评分列表
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from src.skill_infra.skill_loader import get_loader
from src.skill_infra.unified_router import (
    SkillMatch,
    route_question_best,
    route_question_ranked,
)

logger = logging.getLogger(__name__)


def route_question(question: str) -> Optional[str]:
    """
    将用户问题路由到对应的 skill（基于评分的最佳匹配）。

    Args:
        question: 用户的自然语言问题

    Returns:
        匹配的 skill_id，无匹配返回 None

    路由规则（委托给 unified_router）：
    1. 用 SkillLoader 加载所有 skill 的 manifest
    2. 对每个 skill 计算关键词匹配评分
    3. 返回评分最高的 skill_id（confidence >= 0.1）
    """
    result = route_question_best(question)
    if result is not None:
        logger.info(
            "[SkillRouter] '%s' → skill_id=%s (via unified_router)",
            question[:50], result,
        )
    else:
        logger.info("[SkillRouter] No skill matched for '%s'", question[:50])
    return result


def route_question_with_scores(
    question: str,
    min_confidence: float = 0.0,
) -> list[SkillMatch]:
    """
    对用户问题进行多 skill 评分排序，返回所有匹配结果（含置信度）。

    Args:
        question: 用户的自然语言问题
        min_confidence: 最低置信度阈值（0.0 = 不过滤）

    Returns:
        按 confidence 降序排列的 SkillMatch 列表，每个包含：
        - skill_id: str
        - skill_name: str
        - confidence: float (0-1)
        - matched_keywords: list[str]
        - match_method: str
    """
    return route_question_ranked(question, min_confidence=min_confidence)


def get_assembler(skill_id: str) -> Any | None:
    """
    获取指定 skill 的 assembler 实例。
    
    供产品层调用: assembler = get_assembler("benefit_pooling_self_pay")
    """
    loader = get_loader()
    skill = loader.get(skill_id)
    if skill is None:
        logger.warning("[SkillRouter] Skill not found: %s", skill_id)
        return None
    return skill.assembler


def get_skill_manifest(skill_id: str) -> dict[str, Any] | None:
    """
    获取指定 skill 的完整 manifest 字典。

    用于产品层读取 skill 的 display 配置、路由信息等元数据。
    返回原始 YAML 解析后的 dict，调用方按需提取字段。
    """
    loader = get_loader()
    skill = loader.get(skill_id)
    if skill is None:
        logger.warning("[SkillRouter] Skill not found for manifest: %s", skill_id)
        return None
    return skill.manifest


def list_skills() -> list[dict[str, Any]]:
    """列出所有已加载的 skill（供调试用）。"""
    loader = get_loader()
    return [
        {
            "skill_id": s.skill_id,
            "skill_name": s.skill_name,
            "include_keywords": s.include_keywords,
            "excluded_intents": s.excluded_intents,
            "business_action": s.business_action,
            "business_object": s.business_object,
        }
        for s in loader.get_all().values()
    ]
