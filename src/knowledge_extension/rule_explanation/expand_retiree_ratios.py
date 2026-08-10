"""退休比例交叉展开（用户需求）：（四）60% × 前九条在职个人支付 = 9 条退休个人比例。

第三十六条（一）（二）（三）9 档为在职职工分段比例（合并规则 fund+personal），
（四）为「退休人员个人支付比例为职工支付比例的60%」。展开生成 9 条退休个人支付
比例规则，挂到（四）单元下，每条注明基数与折算（可审核、可追溯）。

不生成退休基金规则（基金在职=退休，原文无退休基金表述）。

幂等：已有 psn=退休人员 且 personal 值相同 且 rv 含「× 60%」的规则不重复生成。
"""
from __future__ import annotations

import json
import re
import sys

import psycopg

from src.config.production import DATABASE_URL

DOC_ID = "doc_1d44e2e1db0c"
FORMULA_UNIT = "n_hI9sUrj0uvBe"  # （四）退休60%公式单元
FORMULA_EXT_ID = "ext_0e8551a9ebd2"
# 9 个分段单元
_BAND_UNITS = {
    "n_sq6J0oSSsSpz": "三级医院·起付标准-30000",
    "n_yKfL_Cv1mVgI": "三级医院·30000-40000",
    "n_MTbC8CDjykdk": "三级医院·超过40000",
    "n_U_0k3M7TcK36": "二级医院·起付标准-30000",
    "n_mgwLF3pMMa88": "二级医院·30000-40000",
    "n_0bC6PCcMbfE_": "二级医院·超过40000",
    "n_5zgBs9gIzKPb": "一级医院·起付标准-30000",
    "n_Ztz_JqFijLP7": "一级医院·30000-40000",
    "n_1lOz1yAQLbM4": "一级医院·超过40000",
}
_FACTOR_RE = re.compile(r"[×x]\s*(\d+(?:\.\d+)?)\s*[%％]")


def _load_unit_rules(cur, unit_id: str) -> list[dict]:
    cur.execute(
        "SELECT extracted_fields FROM policy_extractions WHERE unit_id=%s AND doc_id=%s LIMIT 1",
        (unit_id, DOC_ID),
    )
    row = cur.fetchone()
    if not row:
        return []
    fields = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    return fields.get("rules") or []


def main() -> int:
    with psycopg.connect(DATABASE_URL) as conn:
        cur = conn.cursor()
        # 1) 系数：从（四）公式解析（× 60%）
        formula_rules = _load_unit_rules(cur, FORMULA_UNIT)
        factor = 0.6
        for rule in formula_rules:
            m = _FACTOR_RE.search(str(rule.get("rule_value") or ""))
            if m:
                factor = round(float(m.group(1)) / 100, 4)
                break
        print(f"[info] 退休系数 factor={factor}")

        # 2) 收集 9 档在职个人支付比例
        base_rules: list[tuple[str, dict]] = []  # (unit_id, rule)
        for unit_id in _BAND_UNITS:
            for rule in _load_unit_rules(cur, unit_id):
                personal = str(rule.get("personal_payment_ratio") or "").strip()
                if personal:
                    base_rules.append((unit_id, rule))
        print(f"[info] 9 档在职规则: {len(base_rules)} 条")

        # 3) 清掉旧的退休派生规则（无 fund），再生成带 payment_ratio 的新版
        #    识别：psn=退休人员 且 rv 含「依据第三十六条（四）」的派生规则；公式不含该后缀
        kept_formula: list[dict] = []
        for rule in formula_rules:
            if str(rule.get("psn_type") or "") == "退休人员" and "依据第三十六条（四）" in str(rule.get("rule_value") or ""):
                continue  # 旧派生规则，清除
            kept_formula.append(rule)
        derived: list[dict] = []
        for unit_id, rule in base_rules:
            personal_str = str(rule["personal_payment_ratio"]).replace("%", "").strip()
            x = float(personal_str)
            y = round(x * factor, 4)
            fund_y = round(100 - y, 4)
            hosp = str(rule.get("hosp_lv") or "")
            band = str(rule.get("amount_band") or "")
            rv = (
                f"退休人员个人支付比例 = {_BAND_UNITS[unit_id]}：在职职工个人支付{personal_str}% × "
                f"{factor*100:g}% = {y:g}%；基金支付比例 = 100% - 个人支付比例{y:g}% = "
                f"{fund_y:g}%（依据第三十六条（四））"
            )
            derived.append({
                "psn_type": "退休人员",
                "rule_type": "支付比例",
                "insu_type": str(rule.get("insu_type") or "城镇职工基本医疗保险"),
                "med_type": str(rule.get("med_type") or "住院"),
                "hosp_lv": hosp,
                "amount_band": band,
                "payment_ratio": f"{fund_y:g}%",  # 基金支付比例 = 100% - 个人支付比例
                "personal_payment_ratio": f"{y:g}%",
                "rule_value": rv,
                "source_text": "退休人员个人支付比例为职工支付比例的60%。",
                "confidence": rule.get("confidence", 0.7),
            })
        print(f"[info] 新生成退休规则: {len(derived)} 条（含基金=100%-个人）")

        # 4) 写入（四）extraction
        if not derived:
            print("[done] 无新增（幂等）")
            return 0
        cur.execute(
            "SELECT extracted_fields FROM policy_extractions WHERE extraction_id=%s",
            (FORMULA_EXT_ID,),
        )
        row = cur.fetchone()
        fields = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        rules = fields.get("rules") or []
        # 清掉旧派生（rv 含「依据第三十六条（四）」的退休规则），保留公式/其他，追加新派生
        kept = [
            r for r in rules
            if not (str(r.get("psn_type") or "") == "退休人员"
                    and "依据第三十六条（四）" in str(r.get("rule_value") or ""))
        ]
        fields["rules"] = kept + derived
        cur.execute(
            "UPDATE policy_extractions SET extracted_fields=%s, updated_at=CURRENT_TIMESTAMP "
            "WHERE extraction_id=%s",
            (json.dumps(fields, ensure_ascii=False), FORMULA_EXT_ID),
        )
        conn.commit()
        print(f"[done] 退休交叉展开：新增 {len(derived)} 条退休个人比例规则（挂 {FORMULA_UNIT}）")
        return 0


if __name__ == "__main__":
    sys.exit(main())
