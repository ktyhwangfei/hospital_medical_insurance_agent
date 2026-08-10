"""补全 personal_payment_ratio（问题1：合并规则只提取基金、个人值丢在 rule_value）。

覆盖三类（均幂等——已有 personal_payment_ratio 的规则跳过）：
A. 退休个人支付（rule_value 含「退休人员…个人支付X%」）：personal=X×0.6，纯个人规则清 fund。
B. 退休规则但 rule_value 是职工文本（LLM 复制在职文本，如「统筹基金支付85%，职工支付15%」psn=退休）：
   personal=15%×0.6=9%，rule_value 修正为退休折算表述。
C. 在职合并规则（fund 有值 + rule_value 含「职工支付X%」/「职工个人支付X%」）：补 personal=X。

依据：第三十六条（四）「退休人员个人支付比例为职工支付比例的60%」。
"""
from __future__ import annotations

import json
import re
import sys

import psycopg

from src.config.production import DATABASE_URL

DOC_ID = "doc_1d44e2e1db0c"
FACTOR = 0.6

_RETIREE_PERSONAL_RE = re.compile(r"退休人员.*?个人支付\s*(\d+(?:\.\d+)?)\s*[%％]")
_EMPLOYEE_PERSONAL_RE = re.compile(r"(?:职工支付|职工个人支付|由个人支付|个人支付)\s*(\d+(?:\.\d+)?)\s*[%％]")
_HAS_FUND = re.compile(r"统筹基金支付")


def _fix_rule(rule: dict) -> bool:
    rv = str(rule.get("rule_value") or "")
    psn = str(rule.get("psn_type") or "")
    if rule.get("personal_payment_ratio"):
        return False  # 已补全，幂等
    changed = False

    # A) 退休个人支付（含「退休人员」字样）
    m = _RETIREE_PERSONAL_RE.search(rv)
    if m and "退休" in psn:
        x = float(m.group(1))
        y = round(x * FACTOR, 4)
        rule["personal_payment_ratio"] = f"{y:g}%"
        if not _HAS_FUND.search(rv):
            rule["payment_ratio"] = ""
        rule["rule_value"] = rv.replace(
            m.group(0), f"退休人员个人支付{y:g}%（=职工个人支付{m.group(1)}%×60%）",
        )
        return True

    # B) 退休规则但 rule_value 是职工文本（无「退休人员」字样）
    m2 = _EMPLOYEE_PERSONAL_RE.search(rv)
    if m2 and "退休" in psn:
        x = float(m2.group(1))
        y = round(x * FACTOR, 4)
        rule["personal_payment_ratio"] = f"{y:g}%"
        rule["rule_value"] = rv.replace(
            m2.group(0), f"退休人员个人支付{y:g}%（=职工个人支付{m2.group(1)}%×60%）",
        )
        return True

    # C) 在职合并规则：fund 有值 + rule_value 含职工个人支付
    m3 = _EMPLOYEE_PERSONAL_RE.search(rv)
    if m3 and "退休" not in psn and rule.get("payment_ratio"):
        rule["personal_payment_ratio"] = f"{float(m3.group(1)):g}%"
        changed = True
    return changed


def main() -> int:
    with psycopg.connect(DATABASE_URL) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT extraction_id, extracted_fields "
            "FROM policy_extractions WHERE doc_id=%s AND status IN ('reviewed','published')",
            (DOC_ID,),
        )
        rows = cur.fetchall()
        updated_rules = 0
        updated_ext = 0
        for extraction_id, raw_fields in rows:
            fields = raw_fields if isinstance(raw_fields, dict) else json.loads(raw_fields)
            rules = fields.get("rules") or []
            ext_changed = False
            for rule in rules:
                if _fix_rule(rule):
                    updated_rules += 1
                    ext_changed = True
            if ext_changed:
                cur.execute(
                    "UPDATE policy_extractions SET extracted_fields=%s, updated_at=CURRENT_TIMESTAMP "
                    "WHERE extraction_id=%s",
                    (json.dumps(fields, ensure_ascii=False), extraction_id),
                )
                updated_ext += 1
        conn.commit()
        print(f"[done] 补全 personal_payment_ratio：rule {updated_rules} 条 / extraction {updated_ext} 条")
        return 0


if __name__ == "__main__":
    sys.exit(main())
