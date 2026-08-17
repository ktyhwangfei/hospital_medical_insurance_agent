"""
UnifiedRouter — 统一的技能路由系统，支持关键词快筛 + LLM 语义消歧。

路由模式（通过环境变量 SKILL_ROUTING_MODE 控制）：
  - "keyword" (关键字匹配)：纯关键词子串匹配，零 LLM 成本
  - "llm"     (大模型路由)：完全由 LLM 语义判断，最准确但每次产生一次调用
  - "hybrid"  (混合模式，默认)：关键词快筛兜底，低置信度时由 LLM 消歧

提供三个层级的路由能力：
1. route_question_ranked() — 返回排序后的所有匹配，带 confidence 分数
2. route_question_best()  — 返回最佳匹配的 skill_id（或 None）
3. SkillMatch 数据类     — 单个匹配结果的完整信息

对比旧 route_question（first-match-wins）：
- 旧：顺序遍历，返回第一个匹配，无分数
- 新：全量评分，按 confidence 降序，支持阈值过滤；hybrid 模式下低分走 LLM
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Iterable, Optional

from src.skill_infra.skill_loader import get_loader, LoadedSkill

logger = logging.getLogger(__name__)

# ── 路由模式 ──
_SKILL_ROUTING_MODE = os.getenv("SKILL_ROUTING_MODE", "hybrid").lower()
assert _SKILL_ROUTING_MODE in ("keyword", "llm", "hybrid"), (
    f"Invalid SKILL_ROUTING_MODE='{_SKILL_ROUTING_MODE}'. "
    "Must be one of: keyword, llm, hybrid"
)

# ── LLM 消歧阈值：关键词置信度低于此值时触发 LLM ──
_LLM_CONFIDENCE_THRESHOLD = 0.3

SKILL_ROUTING_PROMPT_TEMPLATE = (
    "你是医疗医保智能体的技能路由器。根据用户问题，判断是否需要交给某个技能处理。\n\n"
    "可用技能：\n"
    "{skills_text}\n\n"
    "用户问题：{question}\n\n"
    "判断规则：\n"
    "1. 如果用户问题与某个技能的能力范围高度相关 → 返回该技能的 skill_id\n"
    "2. 如果用户问题与任何技能都无关（闲聊、问候、完全无关话题）→ 返回 null\n"
    "3. 如果用户问题涉及医保费用解释、报销计算、政策咨询 → 优先匹配费用解释类技能\n\n"
    "仅返回 JSON（不要其他内容）：\n"
    '{{"skill_id": "<skill_id或null>", "confidence": 0.0-1.0, "reasoning": "简短理由"}}'
)


@dataclass
class SkillMatch:
    """单个技能匹配结果，含置信度评分和匹配详情。"""

    skill_id: str
    skill_name: str
    confidence: float = 0.0
    matched_keywords: list[str] = field(default_factory=list)
    match_method: str = "keyword"  # "keyword" | "semantic"（保留扩展）

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "confidence": self.confidence,
            "matched_keywords": self.matched_keywords,
            "match_method": self.match_method,
        }


def compute_keyword_score(
    question: str,
    skill: LoadedSkill,
) -> tuple[float, list[str]]:
    """
    计算一个 skill 与用户问题的关键词匹配分数。

    评分公式（参考 src/runtime/intent/skill_matcher.py 的 match_skill_by_intent）：
      keyword_coverage = matched_count / total_keywords   （权重 0.4）
      message_coverage = sum(matched_len) / len(question)  （权重 0.6）
      额外：长关键词匹配 = 更具体，已在 message_coverage 中体现

    排除逻辑：
      - 如果 excluded_intents 命中，confidence 乘以 0.3 降权（而非直接跳过）
    """
    question_lower = question.lower().strip()
    if not question_lower or not skill.include_keywords:
        return 0.0, []

    # ── 包含关键词匹配 ──
    matched_keywords = [
        kw for kw in skill.include_keywords
        if kw.lower() in question_lower
    ]

    if not matched_keywords:
        return 0.0, []

    total_keywords = len(skill.include_keywords)
    matched_count = len(matched_keywords)

    # keyword_coverage：命中关键词占总关键词的比例
    keyword_coverage = matched_count / max(total_keywords, 1)

    # message_coverage：命中关键词的字符长度占问题长度的比例
    matched_chars = sum(len(kw) for kw in matched_keywords)
    message_coverage = matched_chars / max(len(question_lower), 1)

    # 综合评分（与 skill_matcher.py 一致）
    confidence = keyword_coverage * 0.4 + message_coverage * 0.6

    # ── 排除关键词降权 ──
    if skill.excluded_intents:
        if any(ekw.lower() in question_lower for ekw in skill.excluded_intents):
            confidence *= 0.3
            logger.debug(
                "[UnifiedRouter] '%s' penalized for %s (exclusion match)",
                question[:50], skill.skill_id,
            )

    return confidence, matched_keywords


def _compute_keyword_score(
    question: str,
    skill: LoadedSkill,
) -> tuple[float, list[str]]:
    """兼容旧测试与调用方的私有入口。"""
    return compute_keyword_score(question, skill)


def rank_keyword_skills(
    question: str,
    skills: Iterable[LoadedSkill],
    *,
    min_confidence: float = 0.0,
) -> list[SkillMatch]:
    """使用运行时一致的评分、排序和阈值规则排列给定 Skill。"""
    matches: list[SkillMatch] = []
    for skill in skills:
        confidence, matched_keywords = compute_keyword_score(question, skill)
        rounded_confidence = round(confidence, 4)
        if rounded_confidence <= 0.0 or rounded_confidence < min_confidence:
            continue
        matches.append(
            SkillMatch(
                skill_id=skill.skill_id,
                skill_name=skill.skill_name,
                confidence=rounded_confidence,
                matched_keywords=matched_keywords,
            )
        )
    matches.sort(
        key=lambda match: (
            -match.confidence,
            -len(match.matched_keywords),
            match.skill_id,
        ),
    )
    return matches


# ═══════════════════════════════════════════════════════════════════
# LLM 语义路由（hybrid / llm 模式使用）
# ═══════════════════════════════════════════════════════════════════

def _build_skill_routing_prompt(question: str) -> str:
    """
    构建 LLM 技能路由提示词，动态列出所有已加载技能。

    返回的 prompt 要求 LLM 判断用户问题是否应由某个技能处理，
    或返回 null 表示不需要技能介入。
    """
    loader = get_loader()
    skills = loader.get_all()

    if not skills:
        return f"用户问题：{question}\n\n无可用技能，返回 null。"

    skill_lines = []
    for skill_id, skill in skills.items():
        skill_lines.append(
            f"- skill_id: {skill_id}\n"
            f"  名称: {skill.skill_name}\n"
            f"  描述: 该技能处理与{skill.skill_name}相关的问题"
        )

    skills_text = "\n".join(skill_lines)

    return SKILL_ROUTING_PROMPT_TEMPLATE.format(
        skills_text=skills_text,
        question=question,
    )


def _route_via_llm(question: str) -> Optional[str]:
    """
    调用 LLM 进行语义技能路由。

    复用 ModelGateway 和 intent_recognition scene 的调用模式。
    任何异常（网络错误、超时、LLM 返回无效 JSON）都会静默降级，
    返回 None 由上层退回关键词结果。

    Returns:
        匹配的 skill_id，LLM 判断无需技能时返回 None
    """
    if not question or not question.strip():
        return None

    try:
        from src.model_service import Message, ModelGateway

        gateway = ModelGateway()
        prompt = _build_skill_routing_prompt(question)
        messages = [Message(role="user", content=prompt)]

        response = gateway.generate(
            messages=messages,
            model_type="llm",
            scene="skill_routing",
        )

        data = json.loads(response.content)
        skill_id = data.get("skill_id")

        # LLM 返回 null 表示无需技能介入
        if not skill_id or skill_id == "null":
            logger.info(
                "[UnifiedRouter] LLM routed '%s' → no skill needed (confidence=%.2f)",
                question[:50], float(data.get("confidence", 0)),
            )
            return None

        # 校验 LLM 返回的 skill_id 是否存在
        loader = get_loader()
        if loader.get(skill_id) is None:
            logger.warning(
                "[UnifiedRouter] LLM returned unknown skill_id='%s' for '%s', ignoring",
                skill_id, question[:50],
            )
            return None

        logger.info(
            "[UnifiedRouter] LLM routed '%s' → skill_id=%s (confidence=%.2f, reason: %s)",
            question[:50], skill_id,
            float(data.get("confidence", 0)),
            data.get("reasoning", ""),
        )
        return skill_id

    except (json.JSONDecodeError, ValueError, TypeError, KeyError) as e:
        logger.warning(
            "[UnifiedRouter] LLM response parse failed for '%s': %s",
            question[:50], e,
        )
        return None
    except Exception as e:
        logger.warning(
            "[UnifiedRouter] LLM routing failed for '%s': %s",
            question[:50], e,
        )
        return None


def route_question_ranked(
    question: str,
    min_confidence: float = 0.0,
) -> list[SkillMatch]:
    """
    对用户问题进行多 skill 评分排序，返回高于阈值的匹配结果列表。

    Args:
        question: 用户的自然语言问题
        min_confidence: 最低置信度阈值（0.0 = 不过滤）

    Returns:
        按 confidence 降序排列的 SkillMatch 列表
    """
    if not question:
        return []

    loader = get_loader()
    skills = loader.get_all()

    matches = rank_keyword_skills(
        question,
        skills.values(),
        min_confidence=min_confidence,
    )

    if matches:
        logger.info(
            "[UnifiedRouter] Top match for '%s': %s (confidence=%.4f)",
            question[:50], matches[0].skill_id, matches[0].confidence,
        )
    else:
        logger.info("[UnifiedRouter] No skill matched for '%s'", question[:50])

    return matches


def route_question_best(question: str) -> Optional[str]:
    """
    返回最佳匹配的 skill_id，无匹配返回 None。

    路由策略由环境变量 SKILL_ROUTING_MODE 控制：
      - "keyword": 纯关键词匹配（route_question_ranked → 取最高分）
      - "llm":     纯 LLM 语义路由（跳过关键词）
      - "hybrid":  关键词快筛 → 低置信度时 LLM 消歧（默认）

    等价于旧 route_question() 的行为，但基于评分而非 first-match-wins。
    """
    if not question or not question.strip():
        return None

    # ── 模式：纯 LLM ──
    if _SKILL_ROUTING_MODE == "llm":
        return _route_via_llm(question)

    # ── 模式：关键词 / 混合 ──
    if _SKILL_ROUTING_MODE == "keyword":
        matches = route_question_ranked(question, min_confidence=0.1)
        if not matches:
            return None
        return matches[0].skill_id

    # ── 模式：hybrid（默认）──
    # 1. 关键词快筛
    matches = route_question_ranked(question, min_confidence=0.1)

    if not matches:
        # 2a. 无关键词命中 → LLM 消歧
        logger.info(
            "[UnifiedRouter] No keyword match for '%s', falling back to LLM",
            question[:50],
        )
        return _route_via_llm(question)

    top = matches[0]

    # 2b. 高置信度 → 直接返回，跳过 LLM
    if top.confidence >= _LLM_CONFIDENCE_THRESHOLD:
        logger.info(
            "[UnifiedRouter] High keyword confidence (%.4f ≥ %.2f) for '%s', "
            "skipping LLM",
            top.confidence, _LLM_CONFIDENCE_THRESHOLD, question[:50],
        )
        return top.skill_id

    # 2c. 低置信度 → LLM 消歧
    logger.info(
        "[UnifiedRouter] Low keyword confidence (%.4f < %.2f) for '%s', "
        "trying LLM disambiguation",
        top.confidence, _LLM_CONFIDENCE_THRESHOLD, question[:50],
    )
    llm_skill_id = _route_via_llm(question)

    # LLM 有结果则用 LLM 的（语义理解优于关键词），否则退回关键词结果
    if llm_skill_id is not None:
        return llm_skill_id

    logger.info(
        "[UnifiedRouter] LLM disambiguation failed for '%s', "
        "falling back to keyword result: %s",
        question[:50], top.skill_id,
    )
    return top.skill_id
