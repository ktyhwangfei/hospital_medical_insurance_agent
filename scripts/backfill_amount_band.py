"""金额段数值化存量回填（Issue #33 P0-2，门诊+通用范围）。

背景：`_parse_amount_band` 只在入库路径（rule_to_entity）调用，存量规则从未回填，
amount_band_min/max 全为 (0,0)，金额段过滤形同虚设——FAR 主因之一
（docs/reviews/2026-09-01-issue25-structured-index-assessment.md）。

口径：
- 范围：门诊三值 + 通用（med_type 空）；住院明确不做（issue 范围声明）。
- 写入目标：统一 release resolver 解析的当前读集合（active release 优先）。
- 解析仍失败（(0,0)）的规则不写库，仅列入人工核对清单——检索层已改为
  对 (0,0) 跳过范围过滤（保留召回），不会因回填静默消失。

用法：
    python scripts/backfill_amount_band.py           # dry-run（默认，不写库）
    python scripts/backfill_amount_band.py --apply   # 落库
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUTPATIENT_MED_TYPES = ("门诊-普通门急诊", "门诊-急诊留观", "门诊-一般门特")


def _trace_value(value: Any) -> Any:
    """detail 字段是 FieldTrace dict，解包为裸值。"""
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _in_scope(rule: dict) -> bool:
    med_type = rule.get("med_type") or ""
    return med_type in OUTPATIENT_MED_TYPES or med_type == ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写库；缺省仅 dry-run")
    args = parser.parse_args()

    from src.knowledge_extension.rule_explanation.policy_retrieval.applicability_backfill import (
        MilvusRuleStore,
    )
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
        _parse_amount_band,
    )
    from src.knowledge_extension.rule_explanation.release_resolver import (
        resolve_rules_collection,
    )

    target = resolve_rules_collection()
    print(f"写入目标 collection: {target}（active release 感知）")
    store = MilvusRuleStore(collection_name=target)

    all_rules = store.list_rules()
    scoped = [r for r in all_rules if _in_scope(r)]
    print(f"规则总数: {len(all_rules)}，门诊+通用规则: {len(scoped)}（住院规则不回填）")

    changed: list[dict] = []
    unparsed: list[tuple[str, str]] = []
    already_ok = 0
    for rule in scoped:
        band_text = _trace_value(rule.get("amount_band"))
        deductible = _trace_value(rule.get("deductible_amount"))
        new_min, new_max = _parse_amount_band(band_text, deductible)
        current = (int(rule.get("amount_band_min") or 0), int(rule.get("amount_band_max") or 0))
        if (new_min, new_max) == (0, 0):
            if band_text:
                unparsed.append((str(rule.get("rule_id")), str(band_text)))
            continue
        if (new_min, new_max) == current:
            already_ok += 1
            continue
        rule["amount_band_min"] = new_min
        rule["amount_band_max"] = new_max
        changed.append(rule)

    print(f"[扫描] 已正确: {already_ok} 条；待回填: {len(changed)} 条；无法解析(保留(0,0)待人工核对): {len(unparsed)} 条")
    for rule_id, text in unparsed[:20]:
        print(f"  [未解析] {rule_id}: {text}")
    for rule in changed[:10]:
        print(
            f"  [回填] {rule.get('rule_id')}: "
            f"{_trace_value(rule.get('amount_band'))!r} -> "
            f"({rule['amount_band_min']}, {rule['amount_band_max']})"
        )

    if not args.apply:
        print("dry-run 结束（未写库）。加 --apply 落库。")
        return 0

    updated = store.update_rules(changed)
    store.client.flush(store.collection_name)
    print(f"[应用] 更新规则: {updated} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
