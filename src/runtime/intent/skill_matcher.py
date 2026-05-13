from dataclasses import dataclass

from src.data_platform.storage.skill.ports import SkillStorage
from src.domain.skill.models import Skill


@dataclass
class SkillMatchResult:
    skill_id: str
    confidence: float
    matched_keywords: list[str]


def match_skill_by_intent(
    message: str, role: str, skill_storage: SkillStorage
) -> SkillMatchResult | None:
    all_skills = skill_storage.list_skills()
    candidates: list[tuple[Skill, float, list[str]]] = []

    for skill in all_skills:
        if not skill.enabled:
            continue
        if skill.owner != role and role not in skill.required_roles:
            continue
        if not skill.intent_keywords:
            continue

        message_lower = message.lower()
        matched = [kw for kw in skill.intent_keywords if kw.lower() in message_lower]
        if not matched:
            continue
        keyword_coverage = len(matched) / len(skill.intent_keywords)
        message_coverage = sum(len(kw) for kw in matched) / max(len(message_lower), 1)
        score = keyword_coverage * 0.4 + message_coverage * 0.6
        candidates.append((skill, score, matched))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x[1], len(x[2])), reverse=True)
    best_skill, best_score, best_matched = candidates[0]

    if best_score < 0.05:
        return None

    return SkillMatchResult(
        skill_id=best_skill.skill_id,
        confidence=best_score,
        matched_keywords=best_matched,
    )