"""存量数据修复：基金/个人支付比例误抽纠偏。

范围：
1. PostgreSQL `policy_extractions.extracted_fields.rules` —— 源头数据，未来重发布不再带错。
2. 当前 active release 的 Milvus rules collection —— 结算问答 / 宽泛问答的实时读路径。

执行后需要再跑 `scripts/rebuild_release_facts.py` 重新生成 fact_text 与向量。

用法（项目根目录）：
    uv run python scripts/fix_fund_personal_ratio.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

# ruff: noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg
from pymilvus import MilvusClient

from src.config.production import DATABASE_URL, MILVUS_HOST, MILVUS_PORT
from src.knowledge_extension.rule_explanation.fund_ratio_guard import (
    correct_canonical_ratio,
    correct_fund_personal_ratio,
    to_percent,
)
from src.knowledge_extension.rule_explanation.release_resolver import get_active_release
from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
    DETAIL_FIELDS,
)

# 规则的完整 dynamic key 集合：详情字段 + 适用性字段（Issue #25）+ 基金归属。
# Milvus upsert 是整行替换，加载时漏掉任何一个 dynamic key 都会被抹掉（本次事故教训）。
_APPLICABILITY_FIELDS = (
    "region", "effective_date", "expiry_date",
    "publish_status", "policy_version", "is_remote",
)
_EXTRA_DYNAMIC_FIELDS = ("jjgs", "amount_band_min", "amount_band_max")


def _all_rule_output_fields(client: MilvusClient, collection: str) -> list[str]:
    schema_fields = [f["name"] for f in client.describe_collection(collection)["fields"]]
    extras = [
        name
        for name in (*DETAIL_FIELDS, *_APPLICABILITY_FIELDS, *_EXTRA_DYNAMIC_FIELDS)
        if name not in schema_fields
    ]
    return schema_fields + extras


def fix_postgres_extractions() -> int:
    """纠正 policy_extractions 中规则的基金/个人比例，返回修改的提取记录数。"""
    updated = 0
    with psycopg.connect(DATABASE_URL) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT extraction_id, extracted_fields FROM policy_extractions "
            "WHERE status <> 'archived'"
        )
        rows = cur.fetchall()
        for extraction_id, fields in rows:
            if isinstance(fields, str):
                try:
                    fields = json.loads(fields)
                except (json.JSONDecodeError, TypeError):
                    continue
            rules = (fields or {}).get("rules") or []
            changed = any(
                correct_fund_personal_ratio(rule)
                for rule in rules
                if isinstance(rule, dict)
            )
            if not changed:
                continue
            cur.execute(
                "UPDATE policy_extractions SET extracted_fields = %s, "
                "updated_at = CURRENT_TIMESTAMP WHERE extraction_id = %s",
                (json.dumps(fields, ensure_ascii=False), extraction_id),
            )
            updated += 1
        conn.commit()
    return updated


def _unpack(entity: dict[str, Any]) -> dict[str, Any]:
    """FieldTrace dict → 裸值，供纠偏函数处理。"""
    plain: dict[str, Any] = {}
    for key, value in entity.items():
        if isinstance(value, dict) and "value" in value:
            plain[key] = value["value"]
        else:
            plain[key] = value
    return plain


def _repack(entity: dict[str, Any], plain: dict[str, Any], changed_keys: set[str]) -> None:
    """把纠偏后的裸值写回 FieldTrace（保留原有溯源元数据）。"""
    for key in changed_keys:
        old = entity.get(key)
        new_value = plain.get(key, "")
        if isinstance(old, dict) and "value" in old:
            entity[key] = {**old, "value": new_value}
        else:
            entity[key] = {"value": new_value, "confidence": 0.7}


def fix_milvus_rules() -> int:
    """纠正 active release rules collection 中的基金/个人比例，返回修改的规则数。"""
    release = get_active_release()
    if release is None:
        print("当前没有 active release，跳过 Milvus 修复")
        return 0

    client = MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")
    output_fields = _all_rule_output_fields(client, release.rules_collection)

    rows: list[dict[str, Any]] = []
    iterator = client.query_iterator(
        collection_name=release.rules_collection,
        filter="",
        output_fields=output_fields,
        batch_size=1000,
    )
    while True:
        batch = iterator.next()
        if not batch:
            break
        rows.extend(batch)
    print(f"loaded {len(rows)} rules from {release.rules_collection}")

    changed_rows: list[dict[str, Any]] = []
    for row in rows:
        plain = _unpack(row)
        before = (
            str(plain.get("payment_ratio") or ""),
            str(plain.get("personal_payment_ratio") or ""),
        )
        if not correct_fund_personal_ratio(plain):
            continue
        changed_keys = {
            key
            for key in ("payment_ratio", "personal_payment_ratio")
            if str(plain.get(key) or "") != ""
        }
        # 只回写值发生变化的字段
        after = (
            str(plain.get("payment_ratio") or ""),
            str(plain.get("personal_payment_ratio") or ""),
        )
        if after == before:
            continue
        _repack(row, plain, changed_keys)
        changed_rows.append(row)

    for i in range(0, len(changed_rows), 500):
        client.upsert(collection_name=release.rules_collection, data=changed_rows[i:i + 500])
        print(f"  upserted {min(i + 500, len(changed_rows))}/{len(changed_rows)}")
    if changed_rows:
        client.load_collection(release.rules_collection)
    return len(changed_rows)


def fix_change_sets() -> int:
    """纠正 change set 中 canonical rule 的 result.ratio 补集错误。

    知识字段（item.after.fields）里 payment_ratio/personal_payment_ratio 是对的，
    但历史编译把个人比例写进了 result.ratio（如 统筹90%/个人10% → ratio=0.1）。
    不修的话，重新发布会把错误再次带进 Milvus。
    """
    from src.knowledge_extension.rule_explanation.change_set_store import (
        PostgresChangeSetStore,
    )

    store = PostgresChangeSetStore()
    fixed_sets = 0
    fixed_items = 0
    for change_set in store.list():
        changed = False
        new_items = []
        for item in change_set.items:
            canonical = item.canonical_rule
            fields = {
                f.get("field_code"): f.get("raw_value")
                for f in ((item.after or {}).get("fields") or [])
                if isinstance(f, dict)
            }
            corrected = None
            if canonical is not None and "ratio" in (canonical.result or {}):
                corrected = correct_canonical_ratio(
                    canonical.subject, canonical.result.get("ratio"), fields
                )
            if corrected is None:
                new_items.append(item)
                continue
            new_items.append(item.model_copy(update={
                "canonical_rule": canonical.model_copy(update={
                    "result": {**canonical.result, "ratio": corrected},
                }),
            }))
            changed = True
            fixed_items += 1
        if changed:
            store.save(change_set.model_copy(update={"items": new_items}))
            fixed_sets += 1
    print(f"[change_sets] 修正 {fixed_items} 个变更项 / {fixed_sets} 个变更集")
    return fixed_items


# 「在医院就医…85%，在社区卫生机构…90%」/「支付比例为医院90%、社区卫生机构90%」
_HOSPITAL_COMMUNITY_PATTERNS = (
    re.compile(
        r"在医院就医的(?:支付|报销)比例为\s*(\d+(?:\.\d+)?)\s*[%％][^。]*?"
        r"社区卫生(?:机构|服务中心)[^，。；]*?(?:支付|报销)比例为\s*(\d+(?:\.\d+)?)\s*[%％]"
    ),
    re.compile(
        r"(?:支付|报销)比例为\s*(\d+(?:\.\d+)?)\s*[%％][^。]*?"
        r"[（(]社区卫生机构就医为\s*(\d+(?:\.\d+)?)\s*[%％][)）]"
    ),
    re.compile(
        r"(?:支付|报销)比例为医院\s*(\d+(?:\.\d+)?)\s*[%％][、，,]\s*"
        r"社区卫生机构\s*(\d+(?:\.\d+)?)\s*[%％]"
    ),
)
_LEVEL_WORDS = ("一级", "二级", "三级")


def fix_community_hosp_lv() -> int:
    """门诊「医院 vs 社区」规则的等级归位（存量迁移）。

    门诊原文只区分医院/社区，历史提取被幻觉展开成一/二/三级，且社区被并入一级，
    造成同一维度键下两个比例冲突。按 fact 的单元原文归位：
    - 比例命中社区侧 → hosp_lv=社区（独立值）
    - 比例命中医院侧 → hosp_lv=""（医院泛指，清除幻觉等级）
    不匹配该句式的规则不动。
    """
    release = get_active_release()
    if release is None:
        print("当前没有 active release，跳过社区等级归位")
        return 0

    client = MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")
    facts = client.query(
        collection_name=release.facts_collection,
        filter="",
        output_fields=["fact_id", "unit_source_text"],
        limit=16384,
    )
    unit_text_by_fact = {
        str(f["fact_id"]): str(f.get("unit_source_text") or "") for f in facts
    }

    output_fields = _all_rule_output_fields(client, release.rules_collection)
    rows: list[dict[str, Any]] = []
    iterator = client.query_iterator(
        collection_name=release.rules_collection,
        filter='med_type == "门诊-普通门急诊"',
        output_fields=output_fields,
        batch_size=1000,
    )
    while True:
        batch = iterator.next()
        if not batch:
            break
        rows.extend(batch)

    changed_rows: list[dict[str, Any]] = []
    for row in rows:
        hosp = str(row.get("hosp_lv") or "")
        if hosp not in ("一级", "二级", "三级"):
            continue
        unit_text = unit_text_by_fact.get(str(row.get("fact_id") or ""), "")
        plain = _unpack(row)
        rule_src = str(plain.get("source_text") or "")
        evidence_text = unit_text or rule_src
        pair = None
        for pattern in _HOSPITAL_COMMUNITY_PATTERNS:
            m = pattern.search(evidence_text)
            if m:
                pair = (float(m.group(1)), float(m.group(2)))
                break
        if pair is None:
            # 单边社区句：规则或单元原文只说社区 → 归位社区
            if "社区" in rule_src or "社区" in evidence_text:
                if "社区" in rule_src:
                    row["hosp_lv"] = "社区"
                    changed_rows.append(row)
                continue
            # 原文没有任何等级字样 → 该等级是幻觉维度，清除
            if not any(word in evidence_text for word in _LEVEL_WORDS):
                row["hosp_lv"] = ""
                changed_rows.append(row)
            continue
        ratio = to_percent(plain.get("payment_ratio"))
        if ratio is None:
            continue
        hospital_ratio, community_ratio = pair
        if abs(ratio - community_ratio) < 0.51 and abs(hospital_ratio - community_ratio) > 0.5:
            new_hosp = "社区"
        elif abs(ratio - hospital_ratio) < 0.51:
            new_hosp = ""  # 医院泛指，清除幻觉等级
        else:
            continue
        if new_hosp == hosp:
            continue
        row["hosp_lv"] = new_hosp
        changed_rows.append(row)

    for i in range(0, len(changed_rows), 500):
        client.upsert(collection_name=release.rules_collection, data=changed_rows[i:i + 500])
    if changed_rows:
        client.load_collection(release.rules_collection)
    print(f"[milvus] 门诊社区/医院等级归位 {len(changed_rows)} 条")
    return len(changed_rows)


def fix_residual_conflicts() -> int:
    """尾清理：大额医疗互助资金类规则的等级/主体归位。

    1. 门诊大额规则：单元原文「社区卫生服务机构就医」→ 社区；「社区以外」→ 清空等级；
    2. source_text 主句是大额医疗互助资金报销比例、rule_type 却标为「支付比例」的
       → rule_type 归为 large_medical_mutual_aid_payment_ratio（与统筹基金分键）。
    """
    release = get_active_release()
    if release is None:
        return 0

    client = MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")
    facts = client.query(
        collection_name=release.facts_collection,
        filter="",
        output_fields=["fact_id", "unit_source_text"],
        limit=16384,
    )
    unit_text_by_fact = {
        str(f["fact_id"]): str(f.get("unit_source_text") or "") for f in facts
    }

    output_fields = _all_rule_output_fields(client, release.rules_collection)
    rows: list[dict[str, Any]] = []
    iterator = client.query_iterator(
        collection_name=release.rules_collection,
        filter="",
        output_fields=output_fields,
        batch_size=1000,
    )
    while True:
        batch = iterator.next()
        if not batch:
            break
        rows.extend(batch)

    changed: list[dict[str, Any]] = []
    for row in rows:
        plain = _unpack(row)
        rule_type = str(row.get("rule_type") or "")
        src = str(plain.get("source_text") or "").strip()
        unit_text = unit_text_by_fact.get(str(row.get("fact_id") or ""), "")
        new_row = None
        # 1) 门诊大额：社区/以外归位
        if (
            str(row.get("med_type") or "") == "门诊-普通门急诊"
            and str(row.get("hosp_lv") or "") in ("一级", "二级", "三级")
            and "大额医疗互助" in unit_text
        ):
            if "以外" in unit_text:
                row["hosp_lv"] = ""
                new_row = row
            elif "社区" in unit_text:
                row["hosp_lv"] = "社区"
                new_row = row
        # 2) 大额互助主体误标为「支付比例」
        if rule_type == "支付比例" and re.match(r"^(门诊|住院)大额医疗互助资金", src):
            row["rule_type"] = "large_medical_mutual_aid_payment_ratio"
            new_row = row
        if new_row is not None:
            changed.append(new_row)

    for i in range(0, len(changed), 500):
        client.upsert(collection_name=release.rules_collection, data=changed[i:i + 500])
    if changed:
        client.load_collection(release.rules_collection)
    print(f"[milvus] 大额互助尾清理 {len(changed)} 条")
    return len(changed)


def restore_applicability_fields() -> int:
    """修复丢失的适用性 dynamic key（region/publish_status/is_remote 等）。

    背景：Milvus upsert 为整行替换，早前迁移脚本加载时未带这些 dynamic key
    导致被抹掉；另有 2026-07-29 老基线批次天生缺这些字段。缺失适用性字段的规则
    会被检索过滤静默排除（region == "" 不匹NULL）。缺失时按默认值补齐：
    北京 / published / 非异地 / 默认生效区间。
    """
    release = get_active_release()
    if release is None:
        return 0

    client = MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")
    output_fields = _all_rule_output_fields(client, release.rules_collection)
    rows: list[dict[str, Any]] = []
    iterator = client.query_iterator(
        collection_name=release.rules_collection,
        filter="",
        output_fields=output_fields,
        batch_size=1000,
    )
    while True:
        batch = iterator.next()
        if not batch:
            break
        rows.extend(batch)

    defaults = {
        "region": "北京",
        "publish_status": "published",
        "is_remote": False,
        "effective_date": "1900-01-01",
        "expiry_date": "9999-12-31",
        "policy_version": "1.0",
    }
    changed: list[dict[str, Any]] = []
    for row in rows:
        touched = False
        for key, default in defaults.items():
            if row.get(key) in (None, ""):
                row[key] = default
                touched = True
        if touched:
            changed.append(row)

    for i in range(0, len(changed), 500):
        client.upsert(collection_name=release.rules_collection, data=changed[i:i + 500])
    if changed:
        client.load_collection(release.rules_collection)
    print(f"[milvus] 适用性字段补齐 {len(changed)} 条")
    return len(changed)


def fix_amount_band_ranges() -> int:
    """回填 amount_band_min/max（Issue #25 阶段 2 的金额段数值化）。

    本 release 集合从未写入这两个 dynamic key（老基线 merge 时 read_all 的
    output_fields=["*"] 不覆盖 dynamic key 被丢）。缺失时金额段范围过滤会把
    带分段的规则全部静默排除。按 amount_band 文本用规范解析器回填。
    """
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
        _parse_amount_band,
    )

    release = get_active_release()
    if release is None:
        return 0

    client = MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")
    output_fields = _all_rule_output_fields(client, release.rules_collection)
    rows: list[dict[str, Any]] = []
    iterator = client.query_iterator(
        collection_name=release.rules_collection,
        filter="",
        output_fields=output_fields,
        batch_size=1000,
    )
    while True:
        batch = iterator.next()
        if not batch:
            break
        rows.extend(batch)

    changed: list[dict[str, Any]] = []
    for row in rows:
        plain = _unpack(row)
        band = str(plain.get("amount_band") or "").strip()
        if not band:
            continue
        current_min = row.get("amount_band_min")
        current_max = row.get("amount_band_max")
        if current_min is not None and current_max is not None:
            continue
        band_min, band_max = _parse_amount_band(band, plain.get("deductible_amount"))
        row["amount_band_min"] = band_min
        row["amount_band_max"] = band_max
        changed.append(row)

    for i in range(0, len(changed), 500):
        client.upsert(collection_name=release.rules_collection, data=changed[i:i + 500])
    if changed:
        client.load_collection(release.rules_collection)
    print(f"[milvus] 金额段 min/max 回填 {len(changed)} 条")
    return len(changed)


def main() -> int:
    restore_applicability_fields()
    fix_amount_band_ranges()
    pg_updated = fix_postgres_extractions()
    print(f"[postgres] policy_extractions 修正 {pg_updated} 条")
    fix_change_sets()
    milvus_updated = fix_milvus_rules()
    print(f"[milvus] rules 修正 {milvus_updated} 条")
    fix_community_hosp_lv()
    fix_residual_conflicts()
    print("下一步：运行 uv run python scripts/rebuild_release_facts.py 重建 fact_text")
    return 0


if __name__ == "__main__":
    sys.exit(main())
