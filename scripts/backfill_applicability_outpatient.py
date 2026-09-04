"""门诊+通用规则适用性字段正式回填（Issue #25 阶段 2 门诊灰度 → Issue #33 P0-3 扩展通用范围）。

走正式提议者-审核者流水线（applicability_backfill）：
1. 回滚此前直写的兜底值（恢复待回填状态，否则 propose 不会重新提议）
2. propose()：文档元数据优先（effective_date→publish_date→document_date，
   expiry←abolition_date，publish_status←validity，region←policy_region）
3. apply()：仅应用门诊+通用规则的提议（住院明确不做，Issue #33 范围声明），记录 reviewed_by

写入目标：统一 release resolver 解析的当前读集合（active release 优先）——
存在 active release 时直写 policy_rules_v2 会导致 Runtime 读不到回填结果。

用法：
    POSTGRES_PASSWORD=postgres python scripts/backfill_applicability_outpatient.py           # dry-run
    POSTGRES_PASSWORD=postgres python scripts/backfill_applicability_outpatient.py --apply   # 落库
"""
from __future__ import annotations

import argparse
import collections
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUTPATIENT_MED_TYPES = ("门诊-普通门急诊", "门诊-急诊留观", "门诊-一般门特")
APPLICABILITY_FIELDS = (
    "region", "effective_date", "expiry_date", "publish_status", "policy_version", "is_remote",
)


def _in_scope(rule: dict) -> bool:
    """Issue #33 范围：门诊三值 + 通用（med_type 空）；住院明确排除。"""
    med_type = rule.get("med_type") or ""
    return med_type in OUTPATIENT_MED_TYPES or med_type == ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="执行回滚+提议+应用；缺省仅 dry-run")
    parser.add_argument("--reviewed-by", default="policy-admin", help="人工确认身份（审计字段）")
    args = parser.parse_args()

    from src.knowledge_extension.rule_explanation.policy_retrieval.applicability_backfill import (
        ApplicabilityBackfillService,
        MilvusRuleStore,
        PipelineDocumentStore,
    )
    from src.knowledge_extension.rule_explanation.release_resolver import (
        resolve_rules_collection,
    )

    target = resolve_rules_collection()
    print(f"写入目标 collection: {target}（active release 感知）")
    store = MilvusRuleStore(collection_name=target)
    service = ApplicabilityBackfillService(store, PipelineDocumentStore())

    all_rules = store.list_rules()
    scoped = [r for r in all_rules if _in_scope(r)]
    scoped_ids = {r["rule_id"] for r in scoped}
    print(f"规则总数: {len(all_rules)}，门诊+通用规则: {len(scoped)}（住院规则不回填）")

    if args.apply:
        # Step 1: 回滚此前直写的兜底值（删除适用性键，恢复待回填状态）
        rolled_back = [r for r in scoped if any(r.get(f) is not None for f in APPLICABILITY_FIELDS)]
        for r in rolled_back:
            for f in APPLICABILITY_FIELDS:
                r.pop(f, None)
        if rolled_back:
            n = store.update_rules(rolled_back)
            store.client.flush(store.collection_name)
            print(f"[回滚] 清除直写值: {n} 条")
    else:
        # dry-run：内存模拟回滚，不写库
        for r in scoped:
            for f in APPLICABILITY_FIELDS:
                r.pop(f, None)
        from src.knowledge_extension.rule_explanation.policy_retrieval.applicability_backfill import (
            InMemoryRuleStore,
        )
        service = ApplicabilityBackfillService(InMemoryRuleStore(all_rules), PipelineDocumentStore())

    # Step 2: 正式提议（全表扫描，仅取门诊+通用部分）
    proposals = [p for p in service.propose() if p.rule_id in scoped_ids]
    by_field = collections.Counter(p.field_name for p in proposals)
    print(f"[提议] 门诊+通用待回填字段分布: {dict(by_field)}")

    by_doc: dict[str, set] = collections.defaultdict(set)
    for p in proposals:
        if p.field_name in ("effective_date", "publish_status", "region"):
            by_doc[(p.rule_id, p.field_name)].add((p.proposed_value, p.confidence))
    eff = sorted({(v, c) for (rid, f), s in by_doc.items() if f == "effective_date" for v, c in s})
    print(f"[提议] effective_date 取值: {eff}")
    ps = sorted({(v, c) for (rid, f), s in by_doc.items() if f == "publish_status" for v, c in s})
    print(f"[提议] publish_status 取值: {ps}")

    if not args.apply:
        print("dry-run 结束（未写库）。加 --apply 执行回滚+提议+应用。")
        return 0

    # Step 3: 应用（仅门诊+通用提议；reviewed_by 为人工确认审计字段）
    applications, updated = service.apply(proposals, reviewed_by=args.reviewed_by)
    store.client.flush(store.collection_name)
    print(f"[应用] 确认记录: {len(applications)} 项，更新规则: {updated} 条，reviewed_by={args.reviewed_by}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
