"""P0 数据修正（问题1/2/3）：退休折算 + 字段语义分离 + 一级知识归位。

针对 doc_1d44e2e1db0c 全部 extraction：
1. 退休个人支付规则：数值 ×0.6（第三十六条（四）：退休个人=职工个人×60%），
   rule_value 注明折算；纯个人规则 payment_ratio 清空（基金字段不存个人比例）。
2. 在职个人支付规则：personal_payment_ratio=X，payment_ratio 清空（语义分离：
   payment_ratio=基金支付比例，个人比例进 personal_payment_ratio）。
3. ext_0b7736c11934（一级医院知识）unit_id 重挂到一级 3 档 n_1lOz1yAQLbM4
   （leaf_match 去重修复后该叶子已回归）。

幂等：基于 rule_value/psn_type 判定，重复执行不产生叠加。
"""
from __future__ import annotations

import json
import re
import sys

import psycopg

from src.config.production import DATABASE_URL

DOC_ID = "doc_1d44e2e1db0c"
FACTOR = 0.6  # 退休个人支付比例系数

# 退休个人支付：如「退休人员个人支付3%」
_RETIREE_PERSONAL_RE = re.compile(r"退休人员个人支付\s*(\d+(?:\.\d+)?)\s*[%％]")
# 在职个人支付：如「职工个人支付8%」「职工支付8%」「个人支付15%」
_EMPLOYEE_PERSONAL_RE = re.compile(r"(?:职工)?个人支付\s*(\d+(?:\.\d+)?)\s*[%％]")
_IS_AMOUNT = re.compile(r"\d+(?:\.\d+)?\s*[%％]")
_HAS_FUND = re.compile(r"统筹基金支付")


def _fix_rule(rule: dict) -> bool:
    """修正单条 rule，返回是否变更。"""
    rv = str(rule.get("rule_value") or "")
    psn = str(rule.get("psn_type") or "")
    changed = False

    # 1) 退休个人支付规则 → ×0.6
    m = _RETIREE_PERSONAL_RE.search(rv)
    if m and "退休" in psn:
        x = float(m.group(1))
        y = round(x * FACTOR, 4)
        rule["personal_payment_ratio"] = f"{y:g}%"
        # 纯个人规则（不含基金信息）清空基金字段；合并规则（含统筹基金支付）保留基金值
        if not _HAS_FUND.search(rv):
            rule["payment_ratio"] = ""
        rule["rule_value"] = rv.replace(
            f"退休人员个人支付{m.group(1)}%",
            f"退休人员个人支付{y:g}%（=职工个人支付{m.group(1)}%×60%）",
        )
        changed = True
        return changed

    # 2) 在职个人支付规则 → 语义分离（personal_payment_ratio=X，payment_ratio 清空）
    m2 = _EMPLOYEE_PERSONAL_RE.search(rv)
    if m2 and "退休" not in psn and not _HAS_FUND.search(rv):
        rule["personal_payment_ratio"] = f"{float(m2.group(1)):g}%"
        rule["payment_ratio"] = ""
        changed = True
    return changed


def main() -> int:
    with psycopg.connect(DATABASE_URL) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT extraction_id, unit_id, extracted_fields "
            "FROM policy_extractions WHERE doc_id=%s AND status IN ('reviewed','published')",
            (DOC_ID,),
        )
        rows = cur.fetchall()

        updated_rules = 0
        updated_ext = 0
        relocated = 0
        for extraction_id, unit_id, raw_fields in rows:
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

        # 一级医院知识归位（leaf_match 去重修复后 n_1lOz1yAQLbM4 已回归）
        cur.execute(
            "UPDATE policy_extractions SET unit_id='n_1lOz1yAQLbM4', updated_at=CURRENT_TIMESTAMP "
            "WHERE extraction_id='ext_0b7736c11934'",
        )
        relocated = cur.rowcount
        conn.commit()

        print(f"[done] 修正 rule {updated_rules} 条 / extraction {updated_ext} 条；重挂 {relocated} 条")
        return 0


if __name__ == "__main__":
    sys.exit(main())
