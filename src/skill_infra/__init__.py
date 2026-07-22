# src/skill_infra — Skill 基础设施
#
# 每个 skill 是一个独立子目录，包含 YAML 配置 + Python assembler。
# SkillRouter / UnifiedRouter 负责将用户问题路由到对应 skill。

from src.skill_infra.skill_loader import SkillLoader, LoadedSkill, get_loader, refresh_loader
from src.skill_infra.skill_router import (
    route_question,
    route_question_with_scores,
    get_assembler,
    list_skills,
)
from src.skill_infra.unified_router import (
    SkillMatch,
    route_question_ranked,
    route_question_best,
)

__all__ = [
    "SkillLoader",
    "LoadedSkill",
    "get_loader",
    "refresh_loader",
    "route_question",
    "route_question_with_scores",
    "get_assembler",
    "list_skills",
    "SkillMatch",
    "route_question_ranked",
    "route_question_best",
]
