"""支付比例提取纠偏：基金比例与个人比例分流。

LLM 提取常把「统筹基金支付90%，个人支付10%」中的**个人比例 10%** 误抽到
payment_ratio（基金字段）。本模块按规则自身 source_text / rule_value 确定性纠偏：

- source_text 同时含「统筹基金支付X%」与「个人/职工支付Y%」时：
  - payment_ratio 缺失或等于 Y（个人比例）→ 纠正为 X（基金比例）；
  - personal_payment_ratio 为空 → 补 Y。
- 基金=个人（无法区分）或无对应模式 → 不动。

幂等：已纠正的规则重复执行不再变更。
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Mapping

_FUND_RE = re.compile(r"统筹基金支付\s*(\d+(?:\.\d+)?)\s*[%％]")
_PERSONAL_RE = re.compile(r"(?:职工|个人)(?:个人)?支付\s*(\d+(?:\.\d+)?)\s*[%％]")


def to_percent(value: Any) -> float | None:
    """把 '0.9' / '90%' / '90' 统一成百分数数值；无法解析返回 None。"""
    text = str(value or "").strip().rstrip("%％")
    if not text:
        return None
    try:
        num = float(text)
    except ValueError:
        return None
    return num * 100 if 0 < num <= 1 else num


def correct_fund_personal_ratio(rule: dict[str, Any]) -> bool:
    """按规则自身 source_text/rule_value 纠正支付比例字段，返回是否变更。"""
    src = str(rule.get("source_text") or rule.get("rule_value") or "")
    fund = _FUND_RE.search(src)
    personal = _PERSONAL_RE.search(src)
    if not fund or not personal:
        return False
    fund_pct = float(fund.group(1))
    personal_pct = float(personal.group(1))
    if abs(fund_pct - personal_pct) < 1e-9:
        return False  # 基金=个人，无法判定误抽方向，不动

    changed = False
    current = to_percent(rule.get("payment_ratio"))
    if current is None or abs(current - personal_pct) < 0.51:
        rule["payment_ratio"] = f"{fund_pct:g}%"
        changed = True
    if not str(rule.get("personal_payment_ratio") or "").strip():
        rule["personal_payment_ratio"] = f"{personal_pct:g}%"
        changed = True
    return changed


def correct_canonical_ratio(
    subject: str, ratio: Any, fields: Mapping[str, Any]
) -> Decimal | None:
    """编译结果纠偏：fund 类主体的 result.ratio 若撞上了个人比例（补集错误），
    返回应修正的基金比例（0~1 小数）；无法判定或无需修正返回 None。

    实锤案例：知识字段 payment_ratio=90 / personal_payment_ratio=10 均正确，
    但 canonical result.ratio=0.1（个人比例被写进了基金字段）。
    """
    if subject == "personal_payment_ratio":
        return None
    if "payment_ratio" not in subject and not subject.endswith("_reimbursement_ratio"):
        return None
    fund = to_percent(fields.get("payment_ratio"))
    personal = to_percent(fields.get("personal_payment_ratio"))
    current = to_percent(ratio)
    if fund is None or personal is None or current is None:
        return None
    if abs(current - personal) < 0.51 and abs(fund - personal) > 0.5:
        return Decimal(str(fund / 100))
    return None
