from .keyword_rules import RULE_KEYWORDS, NON_RULE_KEYWORDS
from .pattern_rules import match_patterns


LEVEL_SCORE = {
    "chapter": 1,
    "article": 2,
    "paragraph": 2,
    "subparagraph": 3,
    "item": 4,
    "subitem": 3,
}


KEYWORD_BASE_SCORE = {
    "deductible_rule": 5,
    "ratio_rule": 5,
    "cap_rule": 5,
    "period_rule": 4,
    "eligibility_rule": 3,
    "payment_rule": 3,
    "exception_rule": 4,
    "process_rule": 2,
}


PATTERN_SCORE = {
    "amount_pattern": 3,
    "percent_pattern": 3,
    "period_pattern": 4,
    "condition_pattern": 2,
    "action_pattern": 2,
}


def score_rule_candidate(
    text: str,
    level: str,
):
    score = 0

    matched_keywords = []
    candidate_types = set()

    # 关键词评分
    for rule_type, keywords in RULE_KEYWORDS.items():

        for keyword in keywords:
            if keyword in text:

                matched_keywords.append(keyword)
                candidate_types.add(rule_type)

                score += KEYWORD_BASE_SCORE.get(
                    rule_type,
                    1
                )

    # Pattern评分
    matched_patterns = match_patterns(text)

    for pattern in matched_patterns:
        score += PATTERN_SCORE.get(pattern, 1)

    # 结构层级加分
    score += LEVEL_SCORE.get(level, 0)

    # 排除词扣分
    negative_keywords = []

    for keyword in NON_RULE_KEYWORDS:
        if keyword in text:
            negative_keywords.append(keyword)
            score -= 5

    # 去重
    matched_keywords = sorted(
        list(set(matched_keywords))
    )

    matched_patterns = sorted(
        list(set(matched_patterns))
    )

    negative_keywords = sorted(
        list(set(negative_keywords))
    )

    # 候选判断
    is_rule_candidate = score >= 8

    # 强规则
    if score >= 15:
        candidate_level = "strong"

    elif score >= 8:
        candidate_level = "medium"

    elif score >= 4:
        candidate_level = "weak"

    else:
        candidate_level = "none"

    return {
        "rule_score": score,

        "candidate_level": candidate_level,

        "is_rule_candidate": is_rule_candidate,

        "candidate_types": sorted(
            list(candidate_types)
        ),

        "matched_keywords": matched_keywords,

        "matched_patterns": matched_patterns,

        "negative_keywords": negative_keywords,
    }