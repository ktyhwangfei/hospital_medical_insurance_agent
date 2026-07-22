from __future__ import annotations

import json
import uuid
from typing import Any

from .models import PickedEvidence, SearchHit
from .explanation_trace import ExplanationStep, ExplanationTrace


HOSPITAL_LEVEL_TO_VALUE_MAP_KEY = {
    "一级及以下": "primary",
    "一级": "primary",
    "二级": "secondary",
    "三级": "tertiary",
}


def _parse_json_maybe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            return json.loads(value)
        except Exception:
            return None
    return None


def _safe_float(value: Any, default: float = -1.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


class ExplanationPlanner:
    def build(self, evidence: PickedEvidence) -> ExplanationTrace:
        sq = evidence.search_query

        if sq.need_calculation_explanation and sq.target_object == "deductible":
            return self._build_deductible_calculation_trace(evidence)

        if sq.target_object in ["deductible", "payment_ratio", "cap"]:
            return self._build_direct_fact_trace(evidence)

        return self._build_fallback_trace(evidence)

    def _build_direct_fact_trace(self, evidence: PickedEvidence) -> ExplanationTrace:
        sq = evidence.search_query
        fact = evidence.facts[0] if evidence.facts else None

        trace = ExplanationTrace(
            trace_id=f"trace_{uuid.uuid4().hex[:12]}",
            question=sq.question,
            intent=sq.intent,
            target_object=sq.target_object,
            target_value=sq.target_value,
        )

        if not fact:
            trace.final_explanation = "未检索到足够明确的政策事实。"
            return trace

        e = fact.entity or {}
        fact_id = e.get("fact_id") or fact.id
        source_node_id = e.get("source_node_id")
        evidence_text = e.get("evidence_text") or ""

        value_text = self._format_fact_value(e, sq)
        condition_text = self._format_conditions(e, sq)

        trace.used_fact_ids = [fact_id]
        if source_node_id:
            trace.used_node_ids = [source_node_id]
        if evidence_text:
            trace.evidence_texts.append(evidence_text)

        trace.calculation_steps.append(
            ExplanationStep(
                step=1,
                description=f"{condition_text}{self._target_name(sq.target_object)}为{value_text}",
                value=value_text,
                source_fact_ids=[fact_id],
                source_node_ids=[source_node_id] if source_node_id else [],
            )
        )

        trace.confidence = 0.9
        trace.final_explanation = f"{condition_text}{self._target_name(sq.target_object)}为{value_text}。"
        if evidence_text:
            trace.final_explanation += f"\n依据：{evidence_text}"
        return trace

    def _build_deductible_calculation_trace(self, evidence: PickedEvidence) -> ExplanationTrace:
        sq = evidence.search_query
        trace = ExplanationTrace(
            trace_id=f"trace_{uuid.uuid4().hex[:12]}",
            question=sq.question,
            intent="explain_calculation",
            target_object=sq.target_object,
            target_value=sq.target_value,
        )

        deductible = self._first_fact_type(evidence.facts, "deductible")
        formula = self._first_fact_type(evidence.facts, "formula")

        if not deductible or not formula:
            trace.confidence = 0.3
            trace.final_explanation = "未找到足够的起付线基础事实或公式事实，无法形成稳定解释。"
            return trace

        de = deductible.entity or {}
        fe = formula.entity or {}

        first_amount = self._get_deductible_amount(de, sq)
        multiplier = self._get_formula_multiplier(fe)

        deductible_id = de.get("fact_id") or deductible.id
        formula_id = fe.get("fact_id") or formula.id

        if first_amount < 0 or multiplier is None:
            trace.confidence = 0.4
            trace.used_fact_ids = [deductible_id, formula_id]
            trace.final_explanation = "已找到相关政策事实，但金额或公式无法解析，不能稳定计算。"
            return trace

        second_amount = first_amount * multiplier
        total = first_amount + second_amount

        trace.used_fact_ids = [deductible_id, formula_id]

        for e in [de, fe]:
            sid = e.get("source_node_id")
            if sid and sid not in trace.used_node_ids:
                trace.used_node_ids.append(sid)
            ev = e.get("evidence_text")
            if ev and ev not in trace.evidence_texts:
                trace.evidence_texts.append(ev)

        if sq.hospital_level:
            trace.assumptions.append(f"按{sq.hospital_level}医疗机构计算")
        if sq.population:
            trace.assumptions.append(f"按{sq.population}人群计算")
        trace.assumptions.append("按首次住院与第二次住院两次起付线合计解释")

        trace.calculation_steps = [
            ExplanationStep(
                step=1,
                description=f"{sq.hospital_level or ''}医疗机构首次住院起付标准为{first_amount:g}元",
                value=first_amount,
                source_fact_ids=[deductible_id],
            ),
            ExplanationStep(
                step=2,
                description=f"第二次及以后住院起付标准按首次住院起付标准的{multiplier * 100:g}%确定",
                formula=f"{first_amount:g} × {multiplier:g}",
                value=second_amount,
                source_fact_ids=[formula_id],
            ),
            ExplanationStep(
                step=3,
                description="两次住院起付线合计",
                formula=f"{first_amount:g} + {second_amount:g}",
                value=total,
                source_fact_ids=[deductible_id, formula_id],
            ),
        ]

        if sq.target_value is not None and abs(total - sq.target_value) < 0.01:
            trace.confidence = 0.93
        else:
            trace.confidence = 0.72

        trace.final_explanation = (
            f"{total:g}元可以按两次住院累计起付线解释："
            f"首次住院起付线为{first_amount:g}元；"
            f"第二次及以后住院按首次起付标准的{multiplier * 100:g}%确定，"
            f"即{first_amount:g}×{multiplier:g}={second_amount:g}元；"
            f"两次合计为{first_amount:g}+{second_amount:g}={total:g}元。"
        )

        if trace.evidence_texts:
            trace.final_explanation += "\n依据：\n" + "\n".join([f"- {x}" for x in trace.evidence_texts])

        return trace

    def _build_fallback_trace(self, evidence: PickedEvidence) -> ExplanationTrace:
        sq = evidence.search_query
        trace = ExplanationTrace(
            trace_id=f"trace_{uuid.uuid4().hex[:12]}",
            question=sq.question,
            intent=sq.intent,
            target_object=sq.target_object,
            target_value=sq.target_value,
            confidence=0.5,
        )

        snippets = []
        for h in evidence.facts[:3]:
            e = h.entity or {}
            ev = e.get("evidence_text")
            if ev:
                snippets.append(ev)

        trace.evidence_texts = snippets
        if snippets:
            trace.final_explanation = "检索到以下相关政策依据：\n" + "\n".join([f"- {x}" for x in snippets])
        else:
            trace.final_explanation = "未检索到足够明确的政策依据。"

        return trace

    def _format_fact_value(self, entity: dict[str, Any], sq) -> str:
        fact_type = entity.get("fact_type")
        amount = _safe_float(entity.get("amount"))
        ratio = _safe_float(entity.get("ratio"))

        if fact_type in ["deductible", "cap"]:
            if amount >= 0:
                return f"{amount:g}元"
            amount = self._get_deductible_amount(entity, sq)
            if amount >= 0:
                return f"{amount:g}元"

        if fact_type == "payment_ratio":
            if ratio >= 0:
                return f"{ratio * 100:g}%"

        return "未明确"

    def _get_deductible_amount(self, entity: dict[str, Any], sq) -> float:
        amount = _safe_float(entity.get("amount"))
        if amount >= 0:
            return amount

        value_map = _parse_json_maybe(entity.get("value_map_json")) or _parse_json_maybe(entity.get("value_map"))
        if isinstance(value_map, dict) and sq.hospital_level:
            key = HOSPITAL_LEVEL_TO_VALUE_MAP_KEY.get(sq.hospital_level)
            if key and key in value_map:
                return _safe_float(value_map[key])

        value_json = _parse_json_maybe(entity.get("value_json")) or _parse_json_maybe(entity.get("value"))
        if isinstance(value_json, dict):
            return _safe_float(value_json.get("amount"))

        return -1

    def _get_formula_multiplier(self, entity: dict[str, Any]) -> float | None:
        formula = _parse_json_maybe(entity.get("formula_json")) or _parse_json_maybe(entity.get("formula"))
        if isinstance(formula, dict):
            multiplier = formula.get("multiplier")
            if multiplier is not None:
                return _safe_float(multiplier)
        return None

    def _first_fact_type(self, facts: list[SearchHit], fact_type: str) -> SearchHit | None:
        for h in facts:
            if (h.entity or {}).get("fact_type") == fact_type:
                return h
        return None

    def _target_name(self, target_object: str | None) -> str:
        mapping = {
            "deductible": "起付标准",
            "payment_ratio": "支付比例",
            "cap": "最高支付限额",
        }
        return mapping.get(target_object or "", "政策事实")

    def _format_conditions(self, entity: dict[str, Any], sq) -> str:
        parts = []
        if sq.hospital_level:
            parts.append(f"{sq.hospital_level}医疗机构")
        if sq.population:
            if sq.population == "adult":
                parts.append("成人")
            elif sq.population == "student_child":
                parts.append("学生儿童")
            else:
                parts.append(sq.population)
        if sq.service_type == "inpatient":
            parts.append("住院")
        if sq.admission_order == "1":
            parts.append("首次")
        return "".join(parts)
