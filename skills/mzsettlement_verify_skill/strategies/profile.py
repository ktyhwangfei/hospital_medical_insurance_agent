"""由 Skill YAML 驱动九类门诊结算核验场景。"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import yaml

from src.semantic_layer.query_planner import QueryAnchor, QueryScope, SemanticQuery

from ..models import ContextCheck, OutpatientSettlementContext, OutpatientVerificationResult
from ..scripts.render_answer import render_answer
from ..verifier import verify_settlement


ROOT = Path(__file__).parents[1]


def _load_yaml(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8")) or {}


def _metric_code(item: dict) -> str:
    return str(item["metric_code"]).rsplit(".", 1)[-1]


def _qualified(codes: list[str] | tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(f"mzjyxx.{code}" for code in codes))


def _normalize_value(value: str, rules: dict) -> str:
    if value in rules.get("preserve", []):
        return value
    if value in rules.get("exact", {}):
        return rules["exact"][value]
    for item in rules.get("contains", []):
        if any(term in value for term in item["terms"]):
            return item["value"]
    return value


class ProfileStrategy:
    """读取声明式场景定义并执行查询装配与确定性核验。"""

    def __init__(self) -> None:
        self.manifest = _load_yaml("skill_manifest.yaml")
        self.config = _load_yaml("config.yaml")
        self.policy_config = _load_yaml("policy_queries.yaml")
        contract = self.manifest["execution_contract"]
        self.profiles = {
            item["profile_id"]: item for item in contract["profiles"]
        }
        self.profile_ids = tuple(self.profiles)
        self.common_metrics = tuple(
            _metric_code(item) for item in contract["common"]["metric_inputs"]
        )
        self.profile_metrics = {
            profile_id: tuple(_metric_code(item) for item in profile["metric_inputs"])
            for profile_id, profile in self.profiles.items()
        }
        self.context_fields: dict[str, str] = self.config["context_fields"]

    def detect_profile(self, question: str) -> str | None:
        if any(term in question for term in self.config["excluded_route_phrases"]):
            return None
        for profile_id in self.config["routing_priority"]:
            if any(term in question for term in self.profiles[profile_id]["routing_hints"]):
                return profile_id
        return None

    def requires_human_confirmation(self, question: str) -> bool:
        if any(term in question for term in self.config["always_confirm_actions"]):
            return True
        conditional_actions = set(self.config["high_risk_actions"]) - set(
            self.config["always_confirm_actions"]
        )
        return any(term in question for term in conditional_actions) and any(
            term in question for term in self.config["write_intent_terms"]
        )

    def build_semantic_queries(
        self, settlement_id: str, profile_id: str
    ) -> list[SemanticQuery]:
        if profile_id not in self.profiles:
            raise ValueError(f"未知门诊结算核验场景: {profile_id}")
        scope = QueryScope(
            entity_code="outpatient_transaction",
            anchor=QueryAnchor(field_code="mz_trade.T_TradeNo", value=settlement_id),
            query_scope="whole_settlement",
        )
        queries = [SemanticQuery(
            object_code="mzjyxx",
            scope=scope,
            metrics=_qualified([
                *self.common_metrics,
                *self.profile_metrics[profile_id],
            ]),
        )]
        detail = self.config["fee_item_query"]
        if profile_id in detail["profile_ids"]:
            queries.append(SemanticQuery(
                object_code="mzjyxx",
                scope=scope.model_copy(update={"query_scope": "fee_item"}),
                metrics=_qualified(detail["metrics"]),
                group_by=[f"mz_fee_item.{code}" for code in detail["dimensions"]],
            ))
        return queries

    def build_context(
        self, results: list[object], profile_id: str
    ) -> OutpatientSettlementContext:
        summary_rows = getattr(results[0], "rows", []) if results else []
        summary = summary_rows[0] if summary_rows else {}
        known = {
            target: summary.get(source)
            for source, target in self.context_fields.items()
        }
        if known["settlement_date"] is not None:
            known["settlement_date"] = str(known["settlement_date"])
        additional = {
            key: str(value) if isinstance(value, (date, datetime)) else value
            for key, value in summary.items()
            if key not in self.context_fields
        }
        if known["insurance_type"] == "国家平台险种" and additional.get(
            "PN_NationFundType"
        ):
            known["insurance_type"] = additional["PN_NationFundType"]
        fee_items = (
            list(getattr(results[1], "rows", []))
            if profile_id in self.config["fee_item_query"]["profile_ids"]
            and len(results) > 1
            else []
        )
        quality_warnings = [
            f"第 {index} 个语义查询结果完整性为 "
            f"{getattr(result, 'quality_status', 'unknown')}。"
            for index, result in enumerate(results, start=1)
            if getattr(result, "quality_status", "complete") != "complete"
        ]
        if len(summary_rows) > 1:
            quality_warnings.append(
                f"门诊交易号返回 {len(summary_rows)} 条主记录，无法唯一定位结算。"
            )
        return OutpatientSettlementContext(
            **known,
            additional_metrics=additional,
            fee_items=fee_items,
            data_quality_warnings=quality_warnings,
            record_found=len(summary_rows) == 1,
        )

    @staticmethod
    def build_policy_context(
        context: OutpatientSettlementContext, profile_id: str
    ) -> dict[str, str | bool | None]:
        extra = context.additional_metrics
        return {
            "场景": profile_id,
            "险种": context.insurance_type,
            "人员类别": context.person_type,
            "医疗类别": context.service_type,
            "医疗机构等级": context.hospital_level,
            "军残待遇等级": extra.get("P_JCLevel"),
            "结算日期": context.settlement_date,
            "异地标志": extra.get("PN_OutTransaction"),
            "慢特病标志": extra.get("PN_ChronicFlag"),
            "公务员或公疗标志": extra.get("P_Official"),
            "军残标志": extra.get("T_GFBelongFlag"),
            "退役医疗标志": extra.get("RETIRE_OFFICER_FLAG"),
        }

    def build_policy_queries(
        self,
        profile_id: str,
        context: OutpatientSettlementContext | None = None,
    ) -> list[object]:
        from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
            normalize_hosp_lv,
        )
        from src.runtime.policy_qa.structured_policy_retriever import StructuredPolicyQuery

        filters: dict[str, str] = {}
        if context is not None:
            normalization = self.policy_config["normalization"]
            insurance_type = _normalize_value(
                context.insurance_type or "", normalization["insu_type"]
            )
            service_type = _normalize_value(
                context.service_type or "", normalization["med_type"]
            )
            person_type = _normalize_value(
                context.person_type or "", normalization["psn_type"]
            )
            filters = {
                key: value
                for key, value in {
                    "insu_type": insurance_type,
                    "med_type": service_type,
                    "hosp_lv": normalize_hosp_lv(context.hospital_level or ""),
                    "psn_type": person_type,
                }.items()
                if value
            }
        all_query_terms = self.policy_config.get("query_terms", {})
        default_query_terms = all_query_terms.get("default", {})
        profile_query_terms = all_query_terms.get(profile_id, {})
        exact_match_config = self.policy_config.get("exact_match_fields", {})
        exact_match_fields = exact_match_config.get(
            profile_id, exact_match_config.get("default", [])
        )
        queries = []
        for rule_type in self.policy_config.get("profiles", {}).get(profile_id, []):
            terms = profile_query_terms.get(
                rule_type, default_query_terms.get(rule_type, [rule_type])
            )
            queries.append(StructuredPolicyQuery(
                query_name=f"{profile_id}:{rule_type}",
                required=True,
                filters={"rule_type": rule_type, **filters},
                text_must_include_any=list(terms),
                search_text=" ".join([
                    *terms,
                    *filters.values(),
                ]),
                exact_match_fields=list(exact_match_fields),
            ))
        return queries

    def execute(
        self,
        context: OutpatientSettlementContext,
        *,
        profile_id: str = "overall-settlement-verification",
        policy_evidence: list[dict] | None = None,
    ) -> OutpatientVerificationResult:
        evidence = [
            {
                **item,
                "source_id": item.get("source_id") or item.get("title")
                or item.get("policy_title") or "政策依据",
            }
            for item in policy_evidence or []
        ]
        money_fields = {
            self.context_fields[code]
            for code in self.profile_metrics[profile_id]
            if code in self.context_fields
        }
        required_fields = {
            self.context_fields[code]
            for code in self.profiles[profile_id].get("required_metrics", [])
            if code in self.context_fields
        }
        missing_required_metrics = [
            code
            for code in self.profiles[profile_id].get("required_metrics", [])
            if (
                getattr(context, self.context_fields[code])
                if code in self.context_fields
                else context.additional_metrics.get(code)
            ) is None
        ]
        missing_required_collections = [
            name
            for name in self.profiles[profile_id].get("required_collections", [])
            if not getattr(context, name)
        ]
        result = verify_settlement(
            context,
            scenario_id=profile_id,
            policy_evidence=evidence,
            money_fields=money_fields,
            required_money_fields=required_fields,
        )
        fact_checks = list(result.context_checks)
        missing_profile_facts: list[str] = []
        labels = self.config["metric_labels"]
        for code in dict.fromkeys((*self.common_metrics, *self.profile_metrics[profile_id])):
            if code not in context.additional_metrics or code not in labels:
                continue
            value = context.additional_metrics[code]
            if code in self.profile_metrics[profile_id] and value is None:
                missing_profile_facts.append(labels[code])
            fact_checks.append(ContextCheck(
                name=labels[code],
                value=None if value is None else str(value),
                status="missing" if value is None else "present",
            ))
        for index, item in enumerate(context.fee_items, start=1):
            value = "；".join(
                f"{label}={item.get(code, '')}"
                for code, label in self.config["fee_item_labels"].items()
            )
            fact_checks.append(ContextCheck(
                name=f"费用明细 {index}", value=value, status="present"
            ))
        uncertainties = list(result.uncertainties)
        if missing_profile_facts:
            uncertainties.append(
                f"本场景缺少以下指标：{'、'.join(missing_profile_facts)}。"
            )
        if missing_required_metrics or missing_required_collections:
            uncertainties.append("本场景核心数据缺失，无法形成可靠核验结论。")
        unavailable = (
            result.status == "unavailable"
            or bool(missing_required_metrics)
            or bool(missing_required_collections)
        )
        headline = (
            "结算记录或场景核心数据不可用。" if unavailable
            else result.summary if result.anomalies
            else self.config["profile_summaries"][profile_id]
        )
        return result.model_copy(update={
            "status": (
                "unavailable" if unavailable
                else "partial"
                if result.status == "complete" and missing_profile_facts
                else result.status
            ),
            "summary": render_answer(headline, result, fact_checks),
            "context_checks": fact_checks,
            "uncertainties": uncertainties,
        })
