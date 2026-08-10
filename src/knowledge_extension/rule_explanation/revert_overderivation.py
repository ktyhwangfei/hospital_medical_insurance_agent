"""回退过度推导（用户纠正：分段比例是原文在职职工规则，退休只有（四）60%公式）。

错误处理（前几轮 normalize/complete/fix 造成）：
1. 从「职工支付X%」×60% 推导出「退休人员个人X%」规则 —— 原文没有，删。
2. 把分段比例规则 psn 标成「在职职工,退休人员」（通用） —— 原文各档是在职职工，回退为在职职工。
3. LLM 自推的退休基金规则（psn=退休人员 且 payment_ratio 有值）—— 原文无退休基金，删。

原则：忠实原文，不跨单元拼凑推导。保留（四）公式「退休人员个人支付比例为职工支付比例的60%」。

范围：第三十六条 9 个分段单元 + （四）公式单元（unit_id 前缀在 _TARGET_UNITS）。
幂等：按 rv/psn/fund/personal 特征判定，重复执行不误删。
"""
from __future__ import annotations

import json
import sys

import psycopg

from src.config.production import DATABASE_URL

DOC_ID = "doc_1d44e2e1db0c"
# 第三十六条 9 档 + （四）公式单元
_TARGET_UNITS = {
    "n_sq6J0oSSsSpz", "n_yKfL_Cv1mVgI", "n_MTbC8CDjykdk",
    "n_U_0k3M7TcK36", "n_mgwLF3pMMa88", "n_0bC6PCcMbfE_",
    "n_5zgBs9gIzKPb", "n_Ztz_JqFijLP7", "n_1lOz1yAQLbM4",
    "n_hI9sUrj0uvBe",
}


def _is_formula(rule: dict) -> bool:
    rv = str(rule.get("rule_value") or "")
    return "退休人员个人支付比例" in rv and "×" in rv and "60%" in rv


def _fix(rule: dict) -> tuple[list[dict], bool]:
    """返回 (保留的规则列表, 是否变更)。"""
    psn = str(rule.get("psn_type") or "")
    fund = str(rule.get("payment_ratio") or "").strip()
    personal = str(rule.get("personal_payment_ratio") or "").strip()
    if psn == "退休人员":
        if _is_formula(rule):
            return [rule], False  # （四）公式保留
        return [], True  # 推导退休个人 / LLM 自推退休基金 → 删除
    if psn == "在职职工,退休人员":
        rule["psn_type"] = "在职职工"
        return [rule], True  # 通用标注 → 在职职工
    return [rule], False


def main() -> int:
    with psycopg.connect(DATABASE_URL) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT extraction_id, unit_id, extracted_fields "
            "FROM policy_extractions WHERE doc_id=%s AND status IN ('reviewed','published')",
            (DOC_ID,),
        )
        rows = cur.fetchall()
        removed = 0
        updated_ext = 0
        for extraction_id, unit_id, raw_fields in rows:
            if unit_id not in _TARGET_UNITS:
                continue
            fields = raw_fields if isinstance(raw_fields, dict) else json.loads(raw_fields)
            rules = fields.get("rules") or []
            kept: list[dict] = []
            changed = False
            for rule in rules:
                result, did_change = _fix(rule)
                if did_change:
                    changed = True
                    removed += len(rule) - len(result) if False else (1 if not result else 0)
                kept.extend(result)
            # 统计删除数（retiree 非公式）
            deleted = len(rules) - len(kept)
            if changed or deleted:
                fields["rules"] = kept
                cur.execute(
                    "UPDATE policy_extractions SET extracted_fields=%s, updated_at=CURRENT_TIMESTAMP "
                    "WHERE extraction_id=%s",
                    (json.dumps(fields, ensure_ascii=False), extraction_id),
                )
                updated_ext += 1
                removed += deleted
        conn.commit()
        print(f"[done] 回退过度推导：删除 {removed} 条（含推导退休/自推退休基金）；回退标注 extraction {updated_ext} 条")
        return 0


if __name__ == "__main__":
    sys.exit(main())
