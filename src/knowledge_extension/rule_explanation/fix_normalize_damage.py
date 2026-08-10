"""修复 normalize 误伤：合并规则 psn 归位 + 补齐被删的退休个人规则。

背景：normalize_fund_rules 的基金去重把「退休基金规则」（complete 脚本已补成
fund+personal 合并）当成冗余基金删除 → 退休个人比例规则丢失；且保留的合并规则
psn 被统一成「在职职工,退休人员」（错误——其 personal 是具体人群的值）。

修复（对 doc_1d44e2e1db0c 全部 extraction）：
1. 合并规则（fund+personal 同有）psn 归位：
   - rv 含「退休人员个人支付」→ psn=退休人员
   - 否则 → psn=在职职工（personal 是职工个人值）
2. 按 unit 补齐退休个人规则：存在在职个人 X%（psn 在职/合并规则）且无退休个人
   X×0.6% → 追加退休个人规则（psn=退休人员，personal=X×0.6%，rv 注明折算）。

幂等：已归位/已补齐的不再改动。
"""
from __future__ import annotations

import json
import re
import sys

import psycopg

from src.config.production import DATABASE_URL

DOC_ID = "doc_1d44e2e1db0c"
FACTOR = 0.6

_EMPLOYEE_PERSONAL_RE = re.compile(r"(?:职工支付|职工个人支付|由个人支付|个人支付)\s*(\d+(?:\.\d+)?)\s*[%％]")
_RETIREE_PERSONAL_RE = re.compile(r"退休人员.*?个人支付\s*(\d+(?:\.\d+)?)\s*[%％]")


def _fmt(v: float) -> str:
    return f"{round(v, 4):g}%"


def _fix_merged(rule: dict) -> bool:
    """合并规则 psn 归位。"""
    fund = str(rule.get("payment_ratio") or "").strip()
    personal = str(rule.get("personal_payment_ratio") or "").strip()
    psn = str(rule.get("psn_type") or "").strip()
    if not (fund and personal):
        return False
    rv = str(rule.get("rule_value") or "")
    target = "退休人员" if "退休人员" in rv and "个人支付" in rv else "在职职工"
    if psn != target:
        rule["psn_type"] = target
        return True
    return False


def _derive_retiree_rule(inwork: dict) -> dict | None:
    """从在职个人规则派生退休个人规则（×0.6）。"""
    rv = str(inwork.get("rule_value") or "")
    m = _EMPLOYEE_PERSONAL_RE.search(rv)
    if not m:
        return None
    x = float(m.group(1))
    y = round(x * FACTOR, 4)
    new_rv = _EMPLOYEE_PERSONAL_RE.sub(
        lambda _mm: f"退休人员个人支付{_fmt(y)}（=职工个人支付{_fmt(x)}×60%）",
        rv,
        count=1,
    )
    return {
        "psn_type": "退休人员",
        "personal_payment_ratio": _fmt(y),
        "payment_ratio": "",
        "rule_value": new_rv,
        "confidence": inwork.get("confidence", 0.7),
    }


def main() -> int:
    with psycopg.connect(DATABASE_URL) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT extraction_id, unit_id, extracted_fields "
            "FROM policy_extractions WHERE doc_id=%s AND status IN ('reviewed','published')",
            (DOC_ID,),
        )
        rows = cur.fetchall()
        # 第一遍：收集各 unit 的规则 + 修复合并规则 psn
        unit_rules: dict[str, list[dict]] = {}
        ext_map: dict[str, list[dict]] = {}  # extraction_id -> rules list
        ext_changed: set[str] = set()
        for extraction_id, unit_id, raw_fields in rows:
            fields = raw_fields if isinstance(raw_fields, dict) else json.loads(raw_fields)
            rules = fields.get("rules") or []
            ext_map[extraction_id] = rules
            for rule in rules:
                if _fix_merged(rule):
                    ext_changed.add(extraction_id)
                unit_rules.setdefault(unit_id, []).append(rule)

        # 第二遍：按 unit 补齐退休个人规则
        added = 0
        for unit_id, rules in unit_rules.items():
            inwork: dict | None = None
            retiree_values: set[str] = set()
            for rule in rules:
                psn = str(rule.get("psn_type") or "")
                personal = str(rule.get("personal_payment_ratio") or "").strip()
                rv = str(rule.get("rule_value") or "")
                if psn == "退休人员" and personal:
                    retiree_values.add(personal)
                elif personal and psn in ("在职职工", "在职职工,退休人员") and "退休人员" not in rv:
                    inwork = rule
            if inwork is None:
                continue
            derived = _derive_retiree_rule(inwork)
            if derived is None or derived["personal_payment_ratio"] in retiree_values:
                continue  # 已有退休个人（×0.6）或无法派生
            # 追加到 inwork 所在 extraction
            for extraction_id, rules_list in ext_map.items():
                if any(r is inwork for r in rules_list):
                    rules_list.append(derived)
                    ext_changed.add(extraction_id)
                    added += 1
                    break

        for extraction_id in ext_changed:
            fields = dict()
            for eid, _uid, raw_fields in rows:
                if eid == extraction_id:
                    fields = raw_fields if isinstance(raw_fields, dict) else json.loads(raw_fields)
                    break
            fields["rules"] = ext_map[extraction_id]
            cur.execute(
                "UPDATE policy_extractions SET extracted_fields=%s, updated_at=CURRENT_TIMESTAMP "
                "WHERE extraction_id=%s",
                (json.dumps(fields, ensure_ascii=False), extraction_id),
            )
        conn.commit()
        print(f"[done] 合并规则 psn 归位 extraction {len(ext_changed)} 条；补退休个人规则 {added} 条")
        return 0


if __name__ == "__main__":
    sys.exit(main())
