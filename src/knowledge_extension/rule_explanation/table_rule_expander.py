"""表格/压缩比例句的确定性展开器。

LLM 提取遇到「一级医院报销90.0%，二级医院87.0%，三级医院85.0%」或
「一/二/三级医院报销比例依次为90%/87%/85%」这类压缩表格写法时，经常只产一条
无医院等级的聚合规则（或直接漏抽）。本模块在提取后做确定性展开：

- 规则自身已带 hosp_lv → 已是原子规则，不动；
- 原文能解析出 ≥2 个「等级→比例」对 → 每等级展开一条规则；
- 解析不出 → 不动（交给覆盖率校验报警）。

只处理比例类规则（payment_ratio 相关）；起付线/封顶的金额展开同理可后续加。
"""

from __future__ import annotations

import re
from typing import Any

# 「一级医院报销90.0%」「二级医疗机构支付比例87%」等显式成对写法
# 「一级医院报销90.0%」「二级医院96.1%」「三级医院 支付比例85%」等显式成对写法
# （动词可选：表格化写法常省略「报销」）
_LEVEL_PAIR_RE = re.compile(
    r"(一级|二级|三级)(?:医院|医疗机构)?[^，。；0-9]{0,12}?"
    r"(?:报销|支付|统筹基金支付)?(?:比例)?(?:为|：|:)?\s*(\d+(?:\.\d+)?)\s*[%％]"
)
# 「一/二/三级医院报销比例依次为90%/87%/85%」压缩写法
_SEQ_RE = re.compile(
    r"一\s*/\s*二\s*/\s*三级(?:医院|医疗机构)[^，。；]{0,20}?依次为\s*"
    r"(\d+(?:\.\d+)?)\s*[%％]\s*/\s*(\d+(?:\.\d+)?)\s*[%％]\s*/\s*(\d+(?:\.\d+)?)\s*[%％]"
)

_SEQ_LEVELS = ("一级", "二级", "三级")


def parse_level_ratios(text: str) -> dict[str, float]:
    """从文本解析 {等级: 比例%}；不足两级视为非表格写法，返回空。"""
    pairs: dict[str, float] = {}
    for level, ratio in _LEVEL_PAIR_RE.findall(text):
        pairs[level] = float(ratio)
    if len(pairs) < 2:
        seq = _SEQ_RE.search(text)
        if seq:
            pairs = {
                level: float(ratio)
                for level, ratio in zip(_SEQ_LEVELS, seq.groups())
            }
    return pairs if len(pairs) >= 2 else {}


def expand_table_rule(rule: dict[str, Any]) -> list[dict[str, Any]] | None:
    """把无医院等级的比例规则按原文表格写法展开成原子规则。

    返回 None 表示不需要/无法展开；否则返回展开后的规则列表（含原规则全部字段，
    仅覆盖 hosp_lv / payment_ratio / rule_id）。
    """
    if str(rule.get("hosp_lv") or "").strip():
        return None  # 已是原子规则
    text = " ".join(filter(None, [
        str(rule.get("source_text") or ""),
        str(rule.get("rule_value") or ""),
    ]))
    pairs = parse_level_ratios(text)
    if not pairs:
        return None
    rule_type = str(rule.get("rule_type") or "")
    has_ratio_value = bool(str(rule.get("payment_ratio") or "").strip())
    if not has_ratio_value and "比例" not in rule_type and "ratio" not in rule_type.casefold():
        return None

    base_id = str(rule.get("rule_id") or "rule").strip() or "rule"
    expanded: list[dict[str, Any]] = []
    for level in ("一级", "二级", "三级"):
        if level not in pairs:
            continue
        expanded.append({
            **rule,
            "rule_id": f"{base_id}_lv_{level}",
            "hosp_lv": level,
            "payment_ratio": f"{pairs[level]:g}%",
        })
    return expanded or None
