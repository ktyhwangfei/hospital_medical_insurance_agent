"""合并规则拆条（"同样内容有的1条有的2条"：提取形态不一致）。

LLM 提取时同一类原文（「统筹基金支付X%，职工支付Y%」）输出形态不统一：
- 有的拆成两条（基金一条 + 个人一条）
- 有的合并成一条（fund+personal 同 rule，psn 只能标一个，基金通用语义丢失）

统一为拆分形态（与多数单元一致，符合「基金=通用、个人=分人群」语义）：
- 基金规则：payment_ratio=X，personal 空，psn=在职职工,退休人员
- 个人规则：personal=X，payment_ratio 空，psn=在职职工（退休个人已独立存在）

幂等：已拆分（fund/personal 不同时非空）的不动。
"""
from __future__ import annotations

import json
import sys

import psycopg

from src.config.production import DATABASE_URL

DOC_ID = "doc_1d44e2e1db0c"


def _split_merged(rule: dict) -> list[dict]:
    fund = str(rule.get("payment_ratio") or "").strip()
    personal = str(rule.get("personal_payment_ratio") or "").strip()
    if not (fund and personal):
        return [rule]
    rv = str(rule.get("rule_value") or "")
    fund_rule = dict(rule)
    fund_rule["personal_payment_ratio"] = ""
    fund_rule["psn_type"] = "在职职工,退休人员"
    personal_rule = dict(rule)
    personal_rule["payment_ratio"] = ""
    personal_rule["psn_type"] = "退休人员" if ("退休人员" in rv and "个人支付" in rv) else "在职职工"
    return [fund_rule, personal_rule]


def main() -> int:
    with psycopg.connect(DATABASE_URL) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT extraction_id, extracted_fields "
            "FROM policy_extractions WHERE doc_id=%s AND status IN ('reviewed','published')",
            (DOC_ID,),
        )
        rows = cur.fetchall()
        updated_ext = 0
        added_rules = 0
        for extraction_id, raw_fields in rows:
            fields = raw_fields if isinstance(raw_fields, dict) else json.loads(raw_fields)
            rules = fields.get("rules") or []
            new_rules: list[dict] = []
            changed = False
            for rule in rules:
                split = _split_merged(rule)
                if len(split) > 1:
                    changed = True
                    added_rules += 1
                new_rules.extend(split)
            if changed:
                fields["rules"] = new_rules
                cur.execute(
                    "UPDATE policy_extractions SET extracted_fields=%s, updated_at=CURRENT_TIMESTAMP "
                    "WHERE extraction_id=%s",
                    (json.dumps(fields, ensure_ascii=False), extraction_id),
                )
                updated_ext += 1
        conn.commit()
        print(f"[done] 合并规则拆条：新增拆分规则 {added_rules} 条；更新 extraction {updated_ext} 条")
        return 0


if __name__ == "__main__":
    sys.exit(main())
