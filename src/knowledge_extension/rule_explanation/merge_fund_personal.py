"""合并同档基金/个人规则为一条（用户纠正：原文一句 = 一条规则）。

原文「统筹基金支付85%，职工支付15%」是一个完整条件组合，应是一条规则
（fund 与 personal 为该规则的两个字段）。LLM 提取常拆成两条（基金一条+个人一条）。

合并（第三十六条 9 档，同 unit 内）：psn 相同（在职职工）且 amount_band 相同（同档）
的基金规则（fund 有值 personal 空）与个人规则（personal 有值 fund 空）→ 合并为一条。

幂等：已合并（fund 与 personal 同时有值）的不再处理。
"""
from __future__ import annotations

import json
import sys

import psycopg

from src.config.production import DATABASE_URL

DOC_ID = "doc_1d44e2e1db0c"
_TARGET_UNITS = {
    "n_sq6J0oSSsSpz", "n_yKfL_Cv1mVgI", "n_MTbC8CDjykdk",
    "n_U_0k3M7TcK36", "n_mgwLF3pMMa88", "n_0bC6PCcMbfE_",
    "n_5zgBs9gIzKPb", "n_Ztz_JqFijLP7", "n_1lOz1yAQLbM4",
}


def _band(rule: dict) -> str:
    return str(rule.get("amount_band") or "").strip()


def _merge(rules: list[dict]) -> list[dict]:
    fund_rules = [r for r in rules if (r.get("payment_ratio") or "").strip() and not (r.get("personal_payment_ratio") or "").strip()]
    personal_rules = [r for r in rules if (r.get("personal_payment_ratio") or "").strip() and not (r.get("payment_ratio") or "").strip()]
    others = [r for r in rules if r not in fund_rules and r not in personal_rules]

    merged: list[dict] = []
    used: set[int] = set()
    for f_rule in fund_rules:
        match_idx = None
        for i, p_rule in enumerate(personal_rules):
            if i in used:
                continue
            if p_rule.get("psn_type") == f_rule.get("psn_type") and _band(p_rule) == _band(f_rule):
                match_idx = i
                break
        if match_idx is not None:
            p_rule = personal_rules[match_idx]
            used.add(match_idx)
            new_rule = dict(f_rule)
            new_rule["personal_payment_ratio"] = p_rule["personal_payment_ratio"]
            merged.append(new_rule)
        else:
            merged.append(f_rule)
    merged.extend(p for i, p in enumerate(personal_rules) if i not in used)
    merged.extend(others)
    return merged


def main() -> int:
    with psycopg.connect(DATABASE_URL) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT extraction_id, unit_id, extracted_fields "
            "FROM policy_extractions WHERE doc_id=%s AND status IN ('reviewed','published')",
            (DOC_ID,),
        )
        rows = cur.fetchall()
        merged_count = 0
        updated_ext = 0
        for extraction_id, unit_id, raw_fields in rows:
            if unit_id not in _TARGET_UNITS:
                continue
            fields = raw_fields if isinstance(raw_fields, dict) else json.loads(raw_fields)
            rules = fields.get("rules") or []
            new_rules = _merge(rules)
            if len(new_rules) != len(rules):
                fields["rules"] = new_rules
                cur.execute(
                    "UPDATE policy_extractions SET extracted_fields=%s, updated_at=CURRENT_TIMESTAMP "
                    "WHERE extraction_id=%s",
                    (json.dumps(fields, ensure_ascii=False), extraction_id),
                )
                updated_ext += 1
                merged_count += len(rules) - len(new_rules)
        conn.commit()
        print(f"[done] 合并基金/个人规则：合并 {merged_count} 对；更新 extraction {updated_ext} 条")
        return 0


if __name__ == "__main__":
    sys.exit(main())
