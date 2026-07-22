import re


PATTERN_RULES = {
    "amount_pattern": [
        r"\d+\s*元",
        r"\d+元",
    ],

    "percent_pattern": [
        r"\d+\s*%",
        r"百分之[一二三四五六七八九十百千万]+",
    ],

    "period_pattern": [
        r"\d+\s*天",
        r"\d+\s*个月",
        r"\d+\s*年",
    ],

    "condition_pattern": [
        r"符合条件",
        r"应当",
        r"按照",
        r"满足",
        r"属于",
        r"参保",
    ],

    "action_pattern": [
        r"支付",
        r"报销",
        r"减半",
        r"提高",
        r"降低",
        r"执行",
    ]
}


def match_patterns(text: str):
    matched = []

    for pattern_type, patterns in PATTERN_RULES.items():
        for pattern in patterns:
            if re.search(pattern, text):
                matched.append(pattern_type)
                break

    return matched