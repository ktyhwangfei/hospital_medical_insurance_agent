from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .embedding_text_builder import build_fact_embedding_text, build_node_embedding_text
from .models import PolicyFact, PolicyNode
from .utils import (
    HOSPITAL_LEVEL_MAP,
    condition_value,
    normalize_ratio,
    normalize_unit,
    parse_json_like,
    safe_float,
    safe_int,
    safe_str,
)


def load_policy_nodes_from_excel(path: str | Path) -> list[PolicyNode]:
    df = pd.read_excel(path)
    nodes: list[PolicyNode] = []
    for _, row in df.iterrows():
        node = PolicyNode(
            node_id=safe_str(row.get("node_id")),
            parent_id=safe_str(row.get("parent_id")) or None,
            policy_id=safe_str(row.get("policy_index")) or None,
            policy_title=safe_str(row.get("policy_title")) or None,
            level=safe_int(row.get("level")),
            path_text=safe_str(row.get("path_text")) or None,
            current_text=safe_str(row.get("current_text")),
            full_context_text=safe_str(row.get("full_context_text")) or None,
            chunk_type=safe_str(row.get("chunk_type")) or None,
            keywords=_split_keywords(row.get("matched_keywords")),
            summary=None,
            metadata={
                "marker": safe_str(row.get("marker")),
                "candidate_types": safe_str(row.get("candidate_types")),
                "rule_score": safe_float(row.get("rule_score")),
                "candidate_level": safe_str(row.get("candidate_level")),
                "has_children": safe_str(row.get("has_children")),
                "is_rule_candidate": safe_str(row.get("is_rule_candidate")),
            },
        )
        node.embedding_text = build_node_embedding_text(node)
        nodes.append(node)
    return nodes


def load_policy_facts_from_excel(path: str | Path) -> list[PolicyFact]:
    """
    兼容当前 policy_facts.xlsx：
    - 优先读取 normalized_policy_fact_result / policy_fact_result / facts 字段
    - 自动将 value_map 展开为可高级检索的明细 fact：例如 primary/secondary/tertiary -> hospital_level 标量字段
    """
    df = pd.read_excel(path)
    all_facts: list[PolicyFact] = []
    for _, row in df.iterrows():
        source_node_id = safe_str(row.get("node_id"))
        policy_id = safe_str(row.get("policy_index")) or None
        policy_title = safe_str(row.get("policy_title")) or None

        facts_raw = _extract_facts_from_row(row)
        for fact_raw in facts_raw:
            expanded = _expand_fact(
                fact_raw,
                source_node_id=source_node_id,
                policy_id=policy_id,
                policy_title=policy_title,
            )
            all_facts.extend(expanded)
    return all_facts


def _extract_facts_from_row(row: pd.Series) -> list[dict[str, Any]]:
    for col in ["normalized_policy_fact_result", "policy_fact_result", "raw_llm_result"]:
        obj = parse_json_like(row.get(col), default=None)
        if isinstance(obj, dict) and isinstance(obj.get("facts"), list):
            return [x for x in obj["facts"] if isinstance(x, dict)]

    obj = parse_json_like(row.get("facts"), default=None)
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    return []


def _expand_fact(
    raw: dict[str, Any], *, source_node_id: str, policy_id: str | None, policy_title: str | None
) -> list[PolicyFact]:
    fact_type = safe_str(raw.get("fact_type")) or "condition"
    fact_id = safe_str(raw.get("fact_id")) or f"fact_{abs(hash(str(raw))) % 10_000_000}"
    subject = raw.get("subject") if isinstance(raw.get("subject"), dict) else {}
    conditions = raw.get("conditions") if isinstance(raw.get("conditions"), list) else []
    value = raw.get("value")
    value_map = raw.get("value_map") if isinstance(raw.get("value_map"), dict) else None
    formula = raw.get("formula") if isinstance(raw.get("formula"), dict) else None

    base_kwargs = dict(
        source_node_id=source_node_id,
        policy_id=policy_id,
        policy_title=policy_title,
        fact_type=fact_type,
        subject=subject,
        value=value,
        value_map=value_map,
        formula=formula,
        evidence_text=safe_str(raw.get("evidence_text")),
        derived=bool(raw.get("derived", False)),
        inferred=bool(raw.get("inferred", False)),
        derivation_basis=safe_str(raw.get("derivation_basis")) or None,
        uncertainty_reason=safe_str(raw.get("uncertainty_reason")) or None,
        keywords=_build_fact_keywords(raw),
        dimensions={},
        knowledge_group_id=_build_knowledge_group_id(policy_id, source_node_id),
        knowledge_group_type=_infer_knowledge_group_type(subject, fact_type),
        depends_on=raw.get("depends_on") if isinstance(raw.get("depends_on"), list) else [],
        population=safe_str(subject.get("population")) or "unknown",
        service_type=safe_str(subject.get("service_type")) or "unknown",
        insurance_type=safe_str(subject.get("insurance_type")) or "unknown",
        admission_order=_normalize_admission_order(condition_value(conditions, "admission_order")),
    )

    if value_map:
        expanded: list[PolicyFact] = []
        for key, mapped_value in value_map.items():
            hospital_level = _normalize_hospital_level(key)
            amount, ratio, unit = _extract_amount_ratio_unit(mapped_value, fact_type)
            new_conditions = list(conditions)
            if hospital_level != "unknown" and not condition_value(new_conditions, "hospital_level"):
                new_conditions.append({"field": "hospital_level", "operator": "=", "value": hospital_level})
                fact = PolicyFact(
                fact_id=f"{fact_id}__{key}",
                conditions=new_conditions,
                amount=amount,
                ratio=ratio,
                unit=unit,
                hospital_level=hospital_level,
                **base_kwargs,
            )
            fact.value = _to_scalar_value(mapped_value, fact_type)
            fact.dimensions = _build_dimensions(fact)
            fact.embedding_text = build_fact_embedding_text(fact)
            expanded.append(fact)
        return expanded

    amount, ratio, unit = _extract_amount_ratio_unit(value, fact_type)
    fact = PolicyFact(
        fact_id=fact_id,
        conditions=conditions,
        hospital_level=_normalize_hospital_level(condition_value(conditions, "hospital_level")),
        amount=amount,
        ratio=ratio,
        unit=unit,
        **base_kwargs,
    )
    fact.dimensions = _build_dimensions(fact)
    fact.embedding_text = build_fact_embedding_text(fact)
    return [fact]


def _extract_amount_ratio_unit(value: Any, fact_type: str) -> tuple[float | None, float | None, str]:
    if isinstance(value, dict):
        amount = safe_float(value.get("amount"))
        ratio = normalize_ratio(value.get("ratio", value.get("rate")))
        unit = normalize_unit(value.get("unit"))
        return amount, ratio, unit
    if fact_type == "payment_ratio":
        return None, normalize_ratio(value), "unknown"
    if fact_type in ["deductible", "cap", "limit"]:
        return safe_float(value), None, "CNY" if value is not None else "unknown"
    return None, None, "unknown"


def _to_scalar_value(value: Any, fact_type: str) -> Any:
    if isinstance(value, dict):
        if "amount" in value:
            return {"amount": safe_float(value.get("amount")), "unit": normalize_unit(value.get("unit"))}
        if "ratio" in value or "rate" in value:
            return {"ratio": normalize_ratio(value.get("ratio", value.get("rate")))}
    if fact_type == "payment_ratio":
        return {"ratio": normalize_ratio(value)}
    if fact_type in ["deductible", "cap", "limit"]:
        return {"amount": safe_float(value), "unit": "CNY"}
    return value


def _normalize_hospital_level(value: Any) -> str:
    text = safe_str(value)
    return HOSPITAL_LEVEL_MAP.get(text, text or "unknown")


def _normalize_admission_order(value: Any) -> str:
    if value is None:
        return "unknown"
    text = safe_str(value)
    if text == "1" or text == "1.0":
        return "1"
    if text == "2" or text == "2.0":
        return "2"
    if text:
        return text
    return "unknown"


def _build_fact_keywords(raw: dict[str, Any]) -> list[str]:
    words: list[str] = []
    fact_type = safe_str(raw.get("fact_type"))
    evidence = safe_str(raw.get("evidence_text"))
    mapping = {
        "deductible": "起付线",
        "payment_ratio": "支付比例",
        "cap": "封顶线",
        "formula": "计算公式",
    }
    if fact_type in mapping:
        words.append(mapping[fact_type])
    for kw in ["住院", "门诊", "三级", "二级", "一级", "学生儿童", "首次", "第二次", "20万元"]:
        if kw in evidence:
            words.append(kw)
    return list(dict.fromkeys(words))


def _build_dimensions(fact: PolicyFact) -> dict[str, Any]:
    return {
        "fact_type": fact.fact_type,
        "population": fact.population,
        "service_type": fact.service_type,
        "hospital_level": fact.hospital_level,
        "admission_order": fact.admission_order,
        "amount": fact.amount,
        "ratio": fact.ratio,
    }


def _build_knowledge_group_id(policy_id: str | None, node_id: str) -> str:
    base = policy_id or "policy"
    return f"kg_{base}_{node_id}".replace(" ", "_")


def _infer_knowledge_group_type(subject: dict[str, Any], fact_type: str) -> str:
    if subject.get("service_type") == "inpatient":
        return "inpatient_reimbursement_policy"
    return f"{fact_type}_policy"


def _split_keywords(value: Any) -> list[str]:
    parsed = parse_json_like(value, default=None)
    if isinstance(parsed, list):
        return [safe_str(x) for x in parsed if safe_str(x)]
    text = safe_str(value)
    if not text:
        return []
    for sep in [",", "，", "、", ";", "；"]:
        text = text.replace(sep, "|")
    return [x.strip() for x in text.split("|") if x.strip()]
