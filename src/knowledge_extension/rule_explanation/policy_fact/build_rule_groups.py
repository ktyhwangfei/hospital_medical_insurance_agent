from __future__ import annotations

import argparse
import ast
import hashlib
import json
import logging
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_INPUT = Path("./raw/policy_facts1.xlsx")
DEFAULT_OUTPUT_GROUPED = Path("./raw/policy_facts_grouped.xlsx")
DEFAULT_OUTPUT_ACTIVE = Path("./raw/policy_active_rules.xlsx")
DEFAULT_OUTPUT_FLAT = Path("./raw/policy_facts_flat.xlsx")

DATE_COLUMNS = [
    "meta_实施日期",
    "meta_成文日期",
    "meta_发布日期",
    "实施日期",
    "成文日期",
    "发布日期",
]
VALIDITY_COLUMNS = ["meta_有效性", "有效性"]
TITLE_COLUMNS = ["meta_标题", "policy_title", "标题"]
DOC_NO_COLUMNS = ["meta_发文字号", "发文字号"]
ORG_COLUMNS = ["meta_发文机构", "发文机构"]

SUPPORTED_FACT_TYPES = {"deductible", "payment_ratio", "cap", "formula", "condition", "inclusion", "exclusion"}


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def load_jsonish(value: Any) -> Any:
    """Parse JSON stored in Excel. Supports real JSON, Python-literal-like strings, and empty values."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if isinstance(value, (list, dict)):
        return value

    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None

    try:
        return json.loads(text)
    except Exception:
        pass

    try:
        return ast.literal_eval(text)
    except Exception:
        logger.debug("无法解析 JSONish 字段: %s", text[:200])
        return None


def dumps_compact(value: Any) -> str:
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(value: Any, prefix: str, length: int = 16) -> str:
    text = dumps_compact(value) if not isinstance(value, str) else value
    digest = hashlib.blake2s(text.encode("utf-8"), digest_size=12).hexdigest()
    return f"{prefix}_{digest[:length]}"


def normalize_scalar(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        text = re.sub(r"\s+", "", text)
        text = text.replace("％", "%")
        return text
    if isinstance(value, float):
        if math.isnan(value):
            return None
        return round(value, 8)
    return value


def normalize_for_key(value: Any, *, remove_condition_value: bool = False) -> Any:
    """Normalize dict/list for stable grouping. Optionally removes condition value to detect value-boundary changes."""
    if isinstance(value, dict):
        result = {}
        for k, v in sorted(value.items(), key=lambda x: str(x[0])):
            if v is None or v == "":
                continue
            # For conditions, value is usually part of business slot. Keep by default.
            if remove_condition_value and k in {"value", "amount", "ratio"}:
                continue
            result[str(k)] = normalize_for_key(v, remove_condition_value=remove_condition_value)
        return result
    if isinstance(value, list):
        normalized = [normalize_for_key(v, remove_condition_value=remove_condition_value) for v in value]
        # Keep condition order if it exists. Sorting may destroy interval semantics.
        return normalized
    return normalize_scalar(value)


def pick_first(row: pd.Series, columns: list[str]) -> str:
    for col in columns:
        if col in row.index:
            val = safe_str(row.get(col))
            if val:
                return val
    return ""


def parse_effective_date(row: pd.Series) -> pd.Timestamp | pd.NaT:
    for col in DATE_COLUMNS:
        if col in row.index:
            val = row.get(col)
            if safe_str(val):
                dt = pd.to_datetime(val, errors="coerce")
                if not pd.isna(dt):
                    return dt
    return pd.NaT


def is_valid_policy(row: pd.Series) -> bool:
    text = pick_first(row, VALIDITY_COLUMNS)
    if not text:
        return True
    invalid_keywords = ["废止", "失效", "无效", "否"]
    return not any(k in text for k in invalid_keywords)


def document_type_score(title: str) -> int:
    """Small heuristic: implementation details are usually more operational than broad measures."""
    if not title:
        return 0
    if any(k in title for k in ["细则", "规程", "经办", "操作", "流程", "口径"]):
        return 30
    if any(k in title for k in ["通知", "意见", "方案"]):
        return 20
    if any(k in title for k in ["办法", "规定", "制度"]):
        return 10
    return 0


def specificity_score(fact: dict[str, Any]) -> int:
    subject = fact.get("subject") if isinstance(fact.get("subject"), dict) else {}
    conditions = fact.get("conditions") if isinstance(fact.get("conditions"), list) else []
    score = 0
    score += len([v for v in subject.values() if v not in (None, "", [], {})]) * 5
    score += len(conditions) * 5
    evidence = safe_str(fact.get("evidence_text"))
    if any(k in evidence for k in ["三级", "二级", "一级", "学生儿童", "退休", "困难", "特殊病", "门诊", "住院"]):
        score += 10
    return score


def priority_score(row: pd.Series, fact: dict[str, Any], effective_date: pd.Timestamp | pd.NaT) -> int:
    score = 0
    if is_valid_policy(row):
        score += 1000000
    if not pd.isna(effective_date):
        score += int(effective_date.strftime("%Y%m%d"))
    title = pick_first(row, TITLE_COLUMNS)
    score += document_type_score(title)
    score += specificity_score(fact)
    return score


def metric_for_fact(fact: dict[str, Any], dsl: dict[str, Any] | None = None) -> str:
    fact_type = safe_str(fact.get("fact_type"))
    if dsl and isinstance(dsl, dict):
        action = dsl.get("action") if isinstance(dsl.get("action"), dict) else {}
        action_type = safe_str(action.get("type"))
        if action_type:
            return action_type

    if fact_type == "deductible":
        return "deductible_amount"
    if fact_type == "payment_ratio":
        return "fund_payment_ratio"
    if fact_type == "cap":
        return "cap_amount"
    if fact_type == "formula":
        formula = fact.get("formula") if isinstance(fact.get("formula"), dict) else {}
        return safe_str(formula.get("target")) or "formula"
    return fact_type or "unknown"


def build_rule_group_key(fact: dict[str, Any], dsl: dict[str, Any] | None = None) -> tuple[str, str]:
    """Group same business slot. Value is intentionally excluded."""
    fact_type = safe_str(fact.get("fact_type")) or "unknown"
    subject = normalize_for_key(fact.get("subject") or {})
    conditions = normalize_for_key(fact.get("conditions") or [])
    metric = metric_for_fact(fact, dsl)

    payload = {
        "fact_type": fact_type,
        "subject": subject,
        "conditions": conditions,
        "metric": metric,
    }
    return stable_hash(payload, "grp"), dumps_compact(payload)


def build_rule_value_key(fact: dict[str, Any], dsl: dict[str, Any] | None = None) -> tuple[str, str]:
    value_payload = {
        "value": normalize_for_key(fact.get("value")),
        "value_map": normalize_for_key(fact.get("value_map")),
        "formula": normalize_for_key(fact.get("formula")),
    }

    if dsl and isinstance(dsl, dict):
        action = dsl.get("action") if isinstance(dsl.get("action"), dict) else {}
        value_payload["action_value"] = normalize_for_key(action.get("value"))
        value_payload["action_formula"] = normalize_for_key(action.get("formula"))

    return stable_hash(value_payload, "val"), dumps_compact(value_payload)


def match_dsl_for_fact(fact: dict[str, Any], dsls: list[dict[str, Any]]) -> dict[str, Any] | None:
    fact_id = safe_str(fact.get("fact_id"))
    if not fact_id:
        return None
    for dsl in dsls:
        if isinstance(dsl, dict) and safe_str(dsl.get("source_fact_id")) == fact_id:
            return dsl
    return None


def extract_meta(row: pd.Series) -> dict[str, str]:
    meta = {}
    for col in row.index:
        if col.startswith("meta_"):
            meta[col] = safe_str(row[col])
    return meta


def flatten_facts(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for source_row_index, row in df.iterrows():
        facts = load_jsonish(row.get("facts")) or []
        dsls = load_jsonish(row.get("canonical_dsls")) or []

        if not isinstance(facts, list):
            continue
        if not isinstance(dsls, list):
            dsls = []

        effective_date = parse_effective_date(row)
        policy_title = safe_str(row.get("policy_title")) or pick_first(row, TITLE_COLUMNS)
        policy_doc_no = pick_first(row, DOC_NO_COLUMNS)
        policy_org = pick_first(row, ORG_COLUMNS)
        meta = extract_meta(row)

        for fact_index, fact in enumerate(facts, start=1):
            if not isinstance(fact, dict):
                continue

            fact_type = safe_str(fact.get("fact_type"))
            if fact_type and fact_type not in SUPPORTED_FACT_TYPES:
                logger.warning("未知 fact_type=%s, source_row=%s", fact_type, source_row_index)

            dsl = match_dsl_for_fact(fact, dsls)
            group_key, group_payload = build_rule_group_key(fact, dsl)
            value_key, value_payload = build_rule_value_key(fact, dsl)

            local_fact_id = safe_str(fact.get("fact_id")) or f"fact_{fact_index}"
            fact_global_id_payload = {
                "source_row_index": int(source_row_index),
                "node_id": safe_str(row.get("node_id")),
                "fact_id": local_fact_id,
                "evidence_text": safe_str(fact.get("evidence_text")),
            }
            fact_global_id = stable_hash(fact_global_id_payload, "fact", 18)

            out = {
                "fact_global_id": fact_global_id,
                "source_row_index": int(source_row_index),
                "source_fact_id": local_fact_id,
                "source_rule_id": safe_str(dsl.get("rule_id")) if isinstance(dsl, dict) else "",
                "node_id": safe_str(row.get("node_id")),
                "policy_title": policy_title,
                "policy_doc_no": policy_doc_no,
                "policy_org": policy_org,
                "effective_date": "" if pd.isna(effective_date) else effective_date.strftime("%Y-%m-%d"),
                "is_policy_valid": is_valid_policy(row),
                "fact_type": fact_type,
                "rule_metric": metric_for_fact(fact, dsl),
                "subject_json": dumps_compact(fact.get("subject") or {}),
                "conditions_json": dumps_compact(fact.get("conditions") or []),
                "value_json": dumps_compact(fact.get("value")),
                "value_map_json": dumps_compact(fact.get("value_map")),
                "formula_json": dumps_compact(fact.get("formula")),
                "evidence_text": safe_str(fact.get("evidence_text")),
                "derived": bool(fact.get("derived", False)),
                "inferred": bool(fact.get("inferred", False)),
                "rule_group_key": group_key,
                "rule_group_payload": group_payload,
                "rule_value_key": value_key,
                "rule_value_payload": value_payload,
                "priority_score": priority_score(row, fact, effective_date),
                "path_text": safe_str(row.get("path_text")),
                "current_text": safe_str(row.get("current_text")),
                "full_context_text": safe_str(row.get("full_context_text")),
                "fact_json": dumps_compact(fact),
                "canonical_dsl_json": dumps_compact(dsl),
            }
            out.update(meta)
            rows.append(out)

    return pd.DataFrame(rows)


def choose_active(group: pd.DataFrame) -> int:
    """Return index of active row within original flat df index."""
    sorted_group = group.sort_values(
        by=["is_policy_valid", "priority_score", "effective_date", "source_row_index"],
        ascending=[False, False, False, False],
        na_position="last",
    )
    return int(sorted_group.index[0])


def classify_group(flat_df: pd.DataFrame) -> pd.DataFrame:
    if flat_df.empty:
        return flat_df

    result = flat_df.copy()
    result["group_size"] = 1
    result["rule_status"] = "active"
    result["active_fact_id"] = result["fact_global_id"]
    result["relation_type"] = "unique"
    result["relation_reason"] = "该规则分组内只有一条事实规则"
    result["group_value_count"] = 1

    for group_key, group in result.groupby("rule_group_key", dropna=False):
        group_indices = list(group.index)
        group_size = len(group)
        value_count = group["rule_value_key"].nunique(dropna=False)
        active_idx = choose_active(group)
        active_fact_id = result.at[active_idx, "fact_global_id"]
        active_value_key = result.at[active_idx, "rule_value_key"]

        result.loc[group_indices, "group_size"] = group_size
        result.loc[group_indices, "active_fact_id"] = active_fact_id
        result.loc[group_indices, "group_value_count"] = value_count

        if group_size == 1:
            continue

        if value_count == 1:
            result.loc[group_indices, "relation_type"] = "duplicate"
            result.loc[group_indices, "rule_status"] = "duplicate"
            result.loc[group_indices, "relation_reason"] = "同一规则分组下规则值完全相同，判定为重复规则；保留优先级最高的一条为 active"
            result.loc[active_idx, "rule_status"] = "active"
            result.loc[active_idx, "relation_type"] = "active_duplicate_group"
            result.loc[active_idx, "relation_reason"] = "重复规则组内优先级最高，作为当前采用规则"
            continue

        # Multiple values. If at least one date/priority can determine active, mark non-active as override.
        has_any_date = group["effective_date"].astype(str).str.len().gt(0).any()
        has_valid_priority = group["priority_score"].nunique(dropna=False) > 1

        if has_any_date or has_valid_priority:
            result.loc[group_indices, "relation_type"] = "override"
            result.loc[group_indices, "rule_status"] = "override"
            result.loc[group_indices, "relation_reason"] = "同一规则分组下规则值不同，按有效性/日期/文件类型/具体性选择当前有效规则，其余判定为被覆盖"
            result.loc[active_idx, "rule_status"] = "active"
            result.loc[active_idx, "relation_type"] = "active_override_group"
            result.loc[active_idx, "relation_reason"] = "变更规则组内优先级最高，作为当前有效规则"
        else:
            result.loc[group_indices, "relation_type"] = "conflict"
            result.loc[group_indices, "rule_status"] = "conflict"
            result.loc[group_indices, "relation_reason"] = "同一规则分组下规则值不同，但缺少有效日期或优先级依据，需人工复核"
            # Still record best-effort active id, but do not mark any row active.

    return result


def write_outputs(grouped_df: pd.DataFrame, flat_df: pd.DataFrame, output_grouped: Path, output_active: Path, output_flat: Path) -> None:
    output_grouped.parent.mkdir(parents=True, exist_ok=True)
    output_active.parent.mkdir(parents=True, exist_ok=True)
    output_flat.parent.mkdir(parents=True, exist_ok=True)

    active_df = grouped_df[grouped_df["rule_status"] == "active"].copy()
    conflict_df = grouped_df[grouped_df["rule_status"] == "conflict"].copy()

    with pd.ExcelWriter(output_grouped, engine="openpyxl") as writer:
        grouped_df.to_excel(writer, index=False, sheet_name="grouped_rules")
        active_df.to_excel(writer, index=False, sheet_name="active_rules")
        conflict_df.to_excel(writer, index=False, sheet_name="conflicts")

    active_df.to_excel(output_active, index=False)
    flat_df.to_excel(output_flat, index=False)


def build_rule_groups(input_file: Path, output_grouped: Path, output_active: Path, output_flat: Path) -> pd.DataFrame:
    if not input_file.exists():
        raise FileNotFoundError(f"未找到输入文件: {input_file}")

    logger.info("读取输入文件: %s", input_file)
    df = pd.read_excel(input_file)

    if "facts" not in df.columns:
        raise ValueError(f"输入文件缺少 facts 字段，当前字段: {list(df.columns)}")

    logger.info("开始展开 facts")
    flat_df = flatten_facts(df)
    logger.info("展开完成: %s 条 fact", len(flat_df))

    if flat_df.empty:
        logger.warning("没有可处理的 facts，仍将输出空表")
        grouped_df = flat_df
    else:
        logger.info("开始规则分组与 active/override/duplicate/conflict 标记")
        grouped_df = classify_group(flat_df)

    write_outputs(grouped_df, flat_df, output_grouped, output_active, output_flat)

    logger.info("输出完成: %s", output_grouped)
    logger.info("active 输出: %s", output_active)
    logger.info("flat 输出: %s", output_flat)

    if not grouped_df.empty:
        logger.info("统计: total=%s active=%s override=%s duplicate=%s conflict=%s",
                    len(grouped_df),
                    int((grouped_df["rule_status"] == "active").sum()),
                    int((grouped_df["rule_status"] == "override").sum()),
                    int((grouped_df["rule_status"] == "duplicate").sum()),
                    int((grouped_df["rule_status"] == "conflict").sum()))

    return grouped_df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="医保 PolicyFact 轻量规则分组与有效规则选择")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="输入 policy_facts1.xlsx")
    parser.add_argument("--output-grouped", type=Path, default=DEFAULT_OUTPUT_GROUPED, help="输出 grouped xlsx")
    parser.add_argument("--output-active", type=Path, default=DEFAULT_OUTPUT_ACTIVE, help="输出 active rules xlsx")
    parser.add_argument("--output-flat", type=Path, default=DEFAULT_OUTPUT_FLAT, help="输出 flat facts xlsx")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_rule_groups(
        input_file=args.input,
        output_grouped=args.output_grouped,
        output_active=args.output_active,
        output_flat=args.output_flat,
    )


if __name__ == "__main__":
    main()
