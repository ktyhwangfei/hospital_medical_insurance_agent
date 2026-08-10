"""基金规则去重 + 人群标注统一（"一类问题"：基金规则被 LLM 复制成在职/退休两条且标注混乱）。

修复（对 doc_1d44e2e1db0c 全部 extraction）：
1. 基金规则（payment_ratio 有值）：psn 统一为「在职职工,退休人员」（基金在职=退休，通用）；
   同一条 extraction 内 fund 值相同的多条基金规则只保留一条（删除冗余的退休基金复制）。
2. 个人规则：psn 规范为「在职职工」/「退休人员」（退休个人=在职×0.6 已由既有脚本折算）。

幂等：基金规则去重按 fund 值 + psn 归一后判断，重复执行不重复删除。
"""
from __future__ import annotations

import json
import sys

import psycopg

from src.config.production import DATABASE_URL

DOC_ID = "doc_1d44e2e1db0c"


def _normalize(rule: dict) -> bool:
    """规范化单条 rule，返回是否变更。"""
    fund = str(rule.get("payment_ratio") or "").strip()
    psn = str(rule.get("psn_type") or "").strip()
    changed = False
    if fund:
        if psn != "在职职工,退休人员":
            rule["psn_type"] = "在职职工,退休人员"
            changed = True
    elif "退休" in psn:
        if psn != "退休人员":
            rule["psn_type"] = "退休人员"
            changed = True
    elif psn and psn != "在职职工":
        rule["psn_type"] = "在职职工"
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
        updated_ext = 0
        removed_rules = 0
        for extraction_id, raw_fields in rows:
            fields = raw_fields if isinstance(raw_fields, dict) else json.loads(raw_fields)
            rules = fields.get("rules") or []
            if not rules:
                continue
            ext_changed = False
            seen_fund: set[str] = set()
            kept: list[dict] = []
            for rule in rules:
                if _normalize(rule):
                    ext_changed = True
                fund = str(rule.get("payment_ratio") or "").strip()
                if fund:
                    if fund in seen_fund:
                        removed_rules += 1
                        ext_changed = True
                        continue  # 同 extraction 内基金值重复 → 丢弃冗余（退休基金复制）
                    seen_fund.add(fund)
                kept.append(rule)
            if ext_changed:
                fields["rules"] = kept
                cur.execute(
                    "UPDATE policy_extractions SET extracted_fields=%s, updated_at=CURRENT_TIMESTAMP "
                    "WHERE extraction_id=%s",
                    (json.dumps(fields, ensure_ascii=False), extraction_id),
                )
                updated_ext += 1
        conn.commit()
        print(f"[done] 基金去重：删除冗余基金规则 {removed_rules} 条；更新 extraction {updated_ext} 条")
        return 0


if __name__ == "__main__":
    sys.exit(main())
