from __future__ import annotations

from typing import Any
from .models import SearchHit, SearchQuery, PickedEvidence


def _safe_float(value: Any, default: float = -1.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


class RuleBasedReranker:
    def rerank_facts(self, facts: list[SearchHit], sq: SearchQuery) -> list[SearchHit]:
        scored = []

        for h in facts:
            entity = h.entity or {}
            base = h.score if h.score is not None else 0.55
            score = float(base)
            debug = [f"base={score:.4f}"]

            fact_type = entity.get("fact_type")
            population = entity.get("population")
            service_type = entity.get("service_type")
            hospital_level = entity.get("hospital_level")
            admission_order = str(entity.get("admission_order") or "")
            amount = _safe_float(entity.get("amount"))

            if sq.fact_types:
                if fact_type in sq.fact_types:
                    score += 30
                    debug.append(f"+30 fact_type_match:{fact_type}")
                else:
                    score -= 40
                    debug.append(f"-40 fact_type_mismatch:{fact_type}")

            if sq.service_type:
                if service_type == sq.service_type or service_type in ["all", "unknown", None, ""]:
                    score += 10
                    debug.append(f"+10 service_type_match:{service_type}")
                else:
                    score -= 20
                    debug.append(f"-20 service_type_mismatch:{service_type}")

            if sq.population:
                if population == sq.population or population in ["all", "unknown", None, ""]:
                    score += 15
                    debug.append(f"+15 population_match:{population}")
                else:
                    score -= 25
                    debug.append(f"-25 population_mismatch:{population}")

            if sq.hospital_level:
                if hospital_level == sq.hospital_level:
                    score += 20
                    debug.append(f"+20 hospital_level_match:{hospital_level}")
                elif hospital_level in ["unknown", None, ""]:
                    score += 3
                    debug.append(f"+3 hospital_level_unknown:{hospital_level}")
                else:
                    score -= 25
                    debug.append(f"-25 hospital_level_mismatch:{hospital_level}")

            if sq.admission_order:
                if admission_order == sq.admission_order:
                    score += 10
                    debug.append(f"+10 admission_order_match:{admission_order}")
                elif admission_order in ["unknown", "", "None"]:
                    score += 2
                    debug.append(f"+2 admission_order_unknown:{admission_order}")
                elif sq.need_calculation_explanation and admission_order in ["1", "2", ">=2"]:
                    score += 6
                    debug.append(f"+6 admission_order_calc_support:{admission_order}")
                else:
                    score -= 10
                    debug.append(f"-10 admission_order_mismatch:{admission_order}")

            if sq.target_value is not None:
                target_value = _safe_float(sq.target_value)

                if amount >= 0 and target_value >= 0 and abs(amount - target_value) < 0.01:
                    score += 15
                    debug.append(f"+15 target_amount_match:{amount}")
                elif sq.need_calculation_explanation and fact_type in ["deductible", "formula"]:
                    score += 5
                    debug.append("+5 calculation_support_fact")

            if sq.need_formula and fact_type == "formula":
                score += 15
                debug.append("+15 formula_needed_match")

            if entity.get("derived") is True:
                score -= 20
                debug.append("-20 derived_true")
            if entity.get("inferred") is True:
                score -= 20
                debug.append("-20 inferred_true")

            h.rerank_score = score
            h.rerank_debug = debug
            scored.append(h)

        return sorted(scored, key=lambda x: x.rerank_score if x.rerank_score is not None else -9999, reverse=True)

    def rerank_nodes(self, nodes: list[SearchHit], sq: SearchQuery) -> list[SearchHit]:
        for h in nodes:
            h.rerank_score = float(h.score if h.score is not None else 0.55)
            h.rerank_debug = [f"base={h.rerank_score:.4f}"]
        return sorted(nodes, key=lambda x: x.rerank_score if x.rerank_score is not None else -9999, reverse=True)

    def pick_evidence(self, sq: SearchQuery, reranked_facts: list[SearchHit], reranked_nodes: list[SearchHit]) -> PickedEvidence:
        warnings = []
        picked_facts = []

        if sq.need_calculation_explanation:
            deductible = self._first_fact_type(reranked_facts, "deductible")
            formula = self._first_fact_type(reranked_facts, "formula")

            if deductible:
                picked_facts.append(deductible)
            else:
                warnings.append("未找到 deductible 基础事实")

            if formula:
                picked_facts.append(formula)
            else:
                warnings.append("未找到 formula 公式事实")

            return PickedEvidence(facts=picked_facts, nodes=reranked_nodes[:1], search_query=sq, warnings=warnings)

        if sq.target_object in ["deductible", "payment_ratio", "cap"]:
            if reranked_facts:
                picked_facts.append(reranked_facts[0])
            else:
                warnings.append("未找到可用事实")
            return PickedEvidence(facts=picked_facts, nodes=reranked_nodes[:1], search_query=sq, warnings=warnings)

        return PickedEvidence(facts=reranked_facts[:5], nodes=reranked_nodes[:2], search_query=sq, warnings=warnings)

    def _first_fact_type(self, facts: list[SearchHit], fact_type: str) -> SearchHit | None:
        for h in facts:
            if (h.entity or {}).get("fact_type") == fact_type:
                return h
        return None
