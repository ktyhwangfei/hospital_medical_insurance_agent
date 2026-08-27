"""不调用模型的确定性政策规则编译器。"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Any

from src.knowledge_extension.rule_explanation.policy_extract import domain_definitions
from src.knowledge_extension.rule_explanation.policy_compiler.models import (
    CanonicalRule,
    CompilationResult,
    CompileStage,
    CompileStatus,
    CompileStep,
    PolicyExpression,
    PolicyFact,
    ValidationIssue,
)
from src.knowledge_extension.rule_explanation.policy_retrieval.utils import normalize_ratio

logger = logging.getLogger(__name__)


RULE_KEY_FIELDS = (
    "service_type",
    "hospital_level",
    "treatment_type",
    "segment",
    "amount_band",
    "admission_order",
    "effective_period",
    "additional_conditions",
)
_NON_IDENTITY_CONDITION_FIELDS = {"rule_value"}
_SEGMENT_FIELDS = {"segment", "amount_band"}
# 身份无法确定时的哨兵值：必须 fail-closed，否则语义不同的规则会塌缩进同一 rule_id。
# ponytail: 哨兵集合是封闭枚举，新增适配器产生的未知身份值时需同步扩充。
SUBJECT_SENTINELS = frozenset({"", "unclassified", "unknown", "未分类", "none"})


def _domain_terms(domain) -> frozenset[str]:
    """受控值域的全部合法表述（标准名 + 简称 + 别名）。"""
    terms: set[str] = set()
    for value in domain.values:
        terms.update((value.standard_name, value.abbreviation, *value.aliases))
    return frozenset(terms)


# conditions 枚举字段的受控值域（来源：policy_extract/domain_definitions，单一事实源）。
# 未命中不阻断编译，生成 REVIEW 级 VALUE_DOMAIN_UNMAPPED，交由语义映射/值域新增流程收敛。
# conditions 枚举字段的受控值域（来源：policy_extract/domain_definitions，单一事实源）。
# 语义层已发布值域（med_type/hosp_lv/psn_type/insu_type/setl_type/jjgs）同步纳入允许集：
# 提取层按语义层契约产出长格式值（如「门诊-普通门急诊」），若只认 domain_definitions
# 短值（门诊）会全量误报 VALUE_DOMAIN_UNMAPPED（线上 52 条 blocker 全部由此产生）。

def _merge_semantic_registry_domains(base: dict[str, frozenset[str]]) -> dict[str, frozenset[str]]:
    """合并语义层已发布值域到编译器允许集（best-effort，失败用硬编码域）。"""
    try:
        from src.semantic_layer.registry import create_registry
        registry = create_registry()
        merged = {k: set(v) for k, v in base.items()}
        for metric in registry.list_metrics("zcgz"):
            field = metric.metric_code.split(".", 1)[-1]
            if field not in merged or not metric.value_domain:
                continue
            domain = registry.get_value_domain(metric.value_domain)
            if domain:
                merged[field] |= set(domain.standard_values)
        return {k: frozenset(v) for k, v in merged.items()}
    except Exception:
        logger.warning("编译器合并语义层值域失败，退回硬编码域", exc_info=True)
        return base


_CONDITION_VALUE_DOMAINS = _merge_semantic_registry_domains({
    "insu_type": _domain_terms(domain_definitions.INSURANCE_SYSTEM),
    "med_type": _domain_terms(domain_definitions.MEDICAL_CATEGORY),
    "hosp_lv": _domain_terms(domain_definitions.HOSPITAL_LEVEL),
    "psn_type": _domain_terms(domain_definitions.POPULATION_TAGS),
    "setl_type": _domain_terms(domain_definitions.SETTLEMENT_METHOD),
})


def _iter_condition_values(raw: object):
    """枚举字段值可能是标量或嵌套多值列表，逐项展开。"""
    if isinstance(raw, (list, tuple, set)):
        for item in raw:
            yield from _iter_condition_values(item)
    elif isinstance(raw, str):
        yield raw


def _check_condition_value_domains(
    fact: PolicyFact,
) -> list[str]:
    """校验枚举条件字段是否落在受控值域内，返回未映射值描述列表。

    只校验含中文的值：受控值域均为中文表述，英文值（retiree/working 等内部语义键）
    不在本校验范围，避免存量内部键误报。
    """
    unmapped: list[str] = []
    for name, allowed in _CONDITION_VALUE_DOMAINS.items():
        if name not in fact.conditions:
            continue
        for raw in _iter_condition_values(fact.conditions[name]):
            stripped = raw.strip()
            if stripped and _CJK_RE.search(stripped) and stripped not in allowed:
                unmapped.append(f"{name}「{stripped}」")
    return unmapped


_CJK_RE = __import__("re").compile(r"[\u4e00-\u9fff]")


def freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((key, freeze(item)) for key, item in value.items()))
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(freeze(item) for item in value))
    return value


def rule_key(fact: PolicyFact) -> tuple[object, ...]:
    # value.keys() 必须参与身份：否则同 subject/population 的“比例规则”与“金额规则”会算出同一 rule_id。
    key = (
        fact.subject,
        fact.population,
        *(freeze(fact.conditions.get(name)) for name in RULE_KEY_FIELDS),
        freeze(sorted(fact.value.keys())),
    )
    dynamic_conditions = {
        name: value for name, value in fact.conditions.items()
        if name not in RULE_KEY_FIELDS and name not in _NON_IDENTITY_CONDITION_FIELDS
    }
    return (*key, freeze(dynamic_conditions)) if dynamic_conditions else key


class PolicyRuleCompiler:
    """把类型化事实编译成可审核规则；不推测缺失关系。"""

    def __init__(self, compiler_version: str = "1.0") -> None:
        self.compiler_version = compiler_version

    def compile(
        self, facts: list[PolicyFact], *, run_id: str = "run_pure"
    ) -> CompilationResult:
        steps: list[CompileStep] = []
        all_issues: list[ValidationIssue] = []

        normalized, issues = self._stage(
            steps,
            run_id,
            "CANONICALIZE",
            {"facts": self._dump(facts)},
            lambda: self._canonicalize(facts),
        )
        all_issues.extend(issues)

        direct_rules, relations, issues = self._stage(
            steps,
            run_id,
            "COMPOSE",
            {"facts": self._dump(normalized)},
            lambda: self._compose(normalized),
        )
        all_issues.extend(issues)

        resolutions, issues = self._stage(
            steps,
            run_id,
            "RESOLVE",
            {
                "rules": self._dump(direct_rules),
                "relations": self._dump(relations),
            },
            lambda: self._resolve(relations, direct_rules),
        )
        all_issues.extend(issues)

        derived_rules, issues = self._stage(
            steps,
            run_id,
            "DERIVE",
            {"resolutions": self._dump_resolutions(resolutions)},
            lambda: self._derive(resolutions),
        )
        all_issues.extend(issues)

        rules = direct_rules + derived_rules
        _, issues = self._stage(
            steps,
            run_id,
            "VALIDATE",
            {"rules": self._dump(rules)},
            lambda: (None, self._validate(rules)),
        )
        all_issues.extend(issues)
        return self._result(rules, all_issues, steps)

    def _canonicalize(
        self, facts: list[PolicyFact]
    ) -> tuple[list[PolicyFact], list[ValidationIssue]]:
        normalized: list[PolicyFact] = []
        issues: list[ValidationIssue] = []
        for fact in facts:
            if (fact.subject or "").strip().lower() in SUBJECT_SENTINELS:
                issues.append(self._issue(
                    "FAIL", "SUBJECT_MISSING", "CANONICALIZE", fact_id=fact.fact_id,
                    message="政策事实缺少可识别的业务主体",
                    action="补充结构化 subject（如 personal_payment_ratio）",
                ))
                continue
            if not fact.evidence:
                issues.append(self._issue(
                    "FAIL", "EVIDENCE_REQUIRED", "CANONICALIZE", fact_id=fact.fact_id,
                    message="政策事实缺少证据", action="补充原文证据后重试",
                ))
                continue
            if not fact.value and (
                fact.expression is None or fact.expression.operator == "ABSOLUTE"
            ):
                issues.append(self._issue(
                    "REVIEW", "RESULT_MISSING", "CANONICALIZE", fact_id=fact.fact_id,
                    message="政策事实缺少结构化结果", action="补充规则值或数值结果后重提取",
                ))
                continue
            value = dict(fact.value)
            if "ratio" in value:
                raw_ratio = value["ratio"]
                if isinstance(raw_ratio, str) and raw_ratio.strip().endswith("%"):
                    try:
                        ratio = float(Decimal(raw_ratio.strip()[:-1]) / Decimal("100"))
                    except InvalidOperation:
                        ratio = None
                else:
                    ratio = normalize_ratio(raw_ratio)
                if ratio is None:
                    issues.append(self._issue(
                        "FAIL", "RATIO_INVALID", "CANONICALIZE", fact_id=fact.fact_id,
                        message="比例不是有效数值", action="提供结构化数值",
                    ))
                    continue
                decimal_ratio = Decimal(str(ratio))
                if not Decimal("0") <= decimal_ratio <= Decimal("1"):
                    issues.append(self._issue(
                        "FAIL", "RATIO_OUT_OF_RANGE", "CANONICALIZE", fact_id=fact.fact_id,
                        message="比例超出 0 到 1", action="核对提取值及单位",
                    ))
                    continue
                value["ratio"] = decimal_ratio
            # 枚举字段值域归属校验：未命中受控值域不阻断，标记 REVIEW 走值域新增/语义映射流程
            for unmapped in _check_condition_value_domains(fact):
                issues.append(self._issue(
                    "REVIEW", "VALUE_DOMAIN_UNMAPPED", "CANONICALIZE", fact_id=fact.fact_id,
                    message=f"条件值 {unmapped} 未映射到受控值域",
                    action="在语义映射中绑定标准值域，或通过值域新增流程收录该值",
                ))
            for name, raw in tuple(value.items()):
                if name == "ratio" or isinstance(raw, (dict, list, bool)) or raw is None:
                    continue
                try:
                    value[name] = Decimal(str(raw))
                except InvalidOperation:
                    pass
            normalized.append(fact.model_copy(update={"value": value}))
        return normalized, issues

    def _compose(
        self, facts: list[PolicyFact]
    ) -> tuple[tuple[list[CanonicalRule], list[PolicyFact]], list[ValidationIssue]]:
        direct = [
            fact for fact in facts
            if fact.expression is None or fact.expression.operator == "ABSOLUTE"
        ]
        relations = [
            fact for fact in facts
            if fact.expression is not None and fact.expression.operator != "ABSOLUTE"
        ]
        grouped: dict[tuple[object, ...], list[PolicyFact]] = {}
        for fact in direct:
            grouped.setdefault(rule_key(fact), []).append(fact)

        rules: list[CanonicalRule] = []
        issues: list[ValidationIssue] = []
        for key, group in grouped.items():
            distinct_values = {freeze(fact.value) for fact in group}
            if len(distinct_values) > 1:
                for fact in group:
                    issues.append(self._issue(
                        "REVIEW", "CONFLICT", "COMPOSE", fact_id=fact.fact_id,
                        message="相同规则身份存在冲突结果", action="人工确认唯一结果",
                    ))
                continue
            first = group[0]
            evidence = list(dict.fromkeys(item for fact in group for item in fact.evidence))
            rules.append(CanonicalRule(
                rule_id=self._rule_id(key),
                subject=first.subject,
                population=first.population,
                conditions=first.conditions,
                result=first.value,
                evidence=evidence,
                compiler_version=self.compiler_version,
            ))
        return (rules, relations), issues

    def _resolve(
        self, relations: list[PolicyFact], rules: list[CanonicalRule]
    ) -> tuple[dict[str, tuple[PolicyFact, list[CanonicalRule]]], list[ValidationIssue]]:
        resolved: dict[str, tuple[PolicyFact, list[CanonicalRule]]] = {}
        issues: list[ValidationIssue] = []
        for relation in relations:
            selector = (relation.expression.reference if relation.expression else None) or {}
            subject = selector.get("subject", relation.subject)
            candidates = [
                rule for rule in rules
                if rule.subject == subject and self._matches(rule, selector)
            ]
            if not candidates:
                issues.append(self._issue(
                    "REVIEW", "NOT_FOUND", "RESOLVE", fact_id=relation.fact_id,
                    message="未找到关系引用的基础规则", action="补充或修正精确引用",
                ))
            elif len(candidates) > 1 and not self._is_segmented_set(candidates):
                issues.append(self._issue(
                    "REVIEW", "AMBIGUOUS", "RESOLVE", fact_id=relation.fact_id,
                    message="关系引用匹配到多个基础规则", action="补充引用条件",
                ))
            else:
                resolved[relation.fact_id] = (relation, candidates)
        return resolved, issues

    def _derive(
        self,
        resolutions: dict[str, tuple[PolicyFact, list[CanonicalRule]]],
    ) -> tuple[list[CanonicalRule], list[ValidationIssue]]:
        rules: list[CanonicalRule] = []
        issues: list[ValidationIssue] = []
        for relation, bases in resolutions.values():
            expression = relation.expression
            if expression is None:
                continue
            if expression.operator == "MULTIPLY" and expression.factor is None:
                issues.append(self._issue(
                    "REVIEW", "EXPRESSION_INVALID", "DERIVE", fact_id=relation.fact_id,
                    message="MULTIPLY 缺少 factor", action="补充确定系数",
                ))
                continue
            for base in bases:
                result = self._evaluate(expression, base.result)
                if result is None:
                    issues.append(self._issue(
                        "REVIEW", "NON_NUMERIC_REFERENCE", "DERIVE",
                        fact_id=relation.fact_id, rule_id=base.rule_id,
                        message="引用结果不能执行确定性表达式", action="改用数值型基础规则",
                    ))
                    continue
                conditions = {**base.conditions, **relation.conditions}
                try:
                    rules.append(CanonicalRule(
                        rule_id=self._rule_id((relation.subject, relation.population, freeze(conditions))),
                        subject=relation.subject,
                        population=relation.population,
                        conditions=conditions,
                        result=result,
                        source_type="DERIVED",
                        evidence=list(dict.fromkeys([*relation.evidence, *base.evidence])),
                        dependencies=[base.rule_id],
                        formula=expression,
                        compiler_version=self.compiler_version,
                    ))
                except ValueError:
                    issues.append(self._issue(
                        "FAIL", "DERIVED_RESULT_INVALID", "DERIVE",
                        fact_id=relation.fact_id, rule_id=base.rule_id,
                        message="派生结果不满足规则契约", action="核对基础值和表达式",
                    ))
        return rules, issues

    def _validate(self, rules: list[CanonicalRule]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        groups: dict[tuple[Any, ...], list[CanonicalRule]] = {}
        for rule in rules:
            band = rule.conditions.get("amount_band")
            if band is None:
                continue
            identity = (
                rule.subject,
                rule.population,
                freeze({key: value for key, value in rule.conditions.items() if key != "amount_band"}),
            )
            groups.setdefault(identity, []).append(rule)
        for group in groups.values():
            parsed = sorted(
                ((bounds, rule) for rule in group if (bounds := self._parse_band(rule.conditions.get("amount_band"))) is not None),
                key=lambda item: item[0][0],
            )
            for ((_, previous_high), _), ((current_low, _), current) in zip(parsed, parsed[1:]):
                if current_low < previous_high:
                    issues.append(self._issue(
                        "REVIEW", "AMOUNT_BAND_OVERLAP", "VALIDATE", rule_id=current.rule_id,
                        message="金额区间重叠", action="人工确认区间边界",
                    ))
        return issues

    def _stage(
        self,
        steps: list[CompileStep],
        run_id: str,
        stage: CompileStage,
        input_payload: dict[str, Any],
        operation,
    ):
        started = perf_counter()
        output, issues = operation()
        status = self._status(issues)
        steps.append(CompileStep(
            step_id=f"{run_id}_{len(steps) + 1}",
            run_id=run_id,
            sequence_no=len(steps) + 1,
            stage=stage,
            status=status,
            input_payload=input_payload,
            output_payload={"result": self._dump(output)},
            issues=issues,
            duration_ms=max(0, int((perf_counter() - started) * 1000)),
            finished_at=datetime.now(timezone.utc),
        ))
        return (*output, issues) if isinstance(output, tuple) else (output, issues)

    def _result(
        self,
        rules: list[CanonicalRule],
        issues: list[ValidationIssue],
        steps: list[CompileStep],
    ) -> CompilationResult:
        status = self._status(issues)
        return CompilationResult(
            rules=rules,
            issues=issues,
            unresolved_relations=[
                issue for issue in issues
                if issue.code in {"NOT_FOUND", "AMBIGUOUS", "CONFLICT"}
            ],
            steps=steps,
            metrics={"fact_count": len(rules), "issue_count": len(issues)},
            status=status,
        )

    @staticmethod
    def _evaluate(
        expression: PolicyExpression, result: dict[str, Any]
    ) -> dict[str, Decimal] | None:
        if expression.operator == "DIRECT_COPY":
            return dict(result)
        output: dict[str, Decimal] = {}
        for name, raw in result.items():
            try:
                value = Decimal(str(raw))
            except InvalidOperation:
                return None
            if expression.operator == "MULTIPLY":
                output[name] = value * expression.factor
            elif expression.operator == "COMPLEMENT" and expression.total is not None:
                output[name] = expression.total - value
            else:
                return None
        return output

    @staticmethod
    def _matches(rule: CanonicalRule, selector: dict[str, Any]) -> bool:
        for name, expected in selector.items():
            if name == "subject":
                actual = rule.subject
            elif name == "population":
                actual = rule.population
            else:
                actual = rule.conditions.get(name)
            if actual != expected:
                return False
        return True

    @staticmethod
    def _is_segmented_set(rules: list[CanonicalRule]) -> bool:
        static_conditions = {
            freeze({key: value for key, value in rule.conditions.items() if key not in _SEGMENT_FIELDS})
            for rule in rules
        }
        segment_values = {
            freeze({key: rule.conditions.get(key) for key in _SEGMENT_FIELDS})
            for rule in rules
        }
        return len(static_conditions) == 1 and len(segment_values) == len(rules)

    @staticmethod
    def _parse_band(value: Any) -> tuple[Decimal, Decimal] | None:
        if not isinstance(value, str):
            return None
        parts = value.split("-", 1)
        if len(parts) != 2:
            return None
        try:
            return Decimal(parts[0].strip()), Decimal(parts[1].strip())
        except InvalidOperation:
            return None

    @staticmethod
    def _status(issues: Iterable[ValidationIssue]) -> CompileStatus:
        severities = {issue.severity for issue in issues}
        if "FAIL" in severities:
            return "FAIL"
        if "REVIEW" in severities:
            return "REVIEW"
        if "WARN" in severities:
            return "WARN"
        return "PASS"

    @staticmethod
    def _issue(
        severity: str,
        code: str,
        stage: CompileStage,
        *,
        message: str,
        action: str,
        fact_id: str | None = None,
        rule_id: str | None = None,
    ) -> ValidationIssue:
        identity = f"{stage}:{code}:{fact_id or rule_id or ''}"
        issue_id = "issue_" + hashlib.sha256(identity.encode()).hexdigest()[:16]
        return ValidationIssue(
            issue_id=issue_id,
            severity=severity,
            code=code,
            stage=stage,
            fact_id=fact_id,
            rule_id=rule_id,
            message=message,
            recommended_action=action,
        )

    @staticmethod
    def _rule_id(identity: object) -> str:
        payload = json.dumps(freeze(identity), ensure_ascii=False, default=str)
        return "rule_" + hashlib.sha256(payload.encode()).hexdigest()[:16]

    @staticmethod
    def _dump(value: Any) -> Any:
        if isinstance(value, list):
            return [PolicyRuleCompiler._dump(item) for item in value]
        if isinstance(value, dict):
            return {key: PolicyRuleCompiler._dump(item) for key, item in value.items()}
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, Decimal):
            return str(value)
        return value

    @staticmethod
    def _dump_resolutions(
        resolutions: dict[str, tuple[PolicyFact, list[CanonicalRule]]]
    ) -> dict[str, Any]:
        return {
            fact_id: {
                "relation": relation.model_dump(mode="json"),
                "rules": [rule.model_dump(mode="json") for rule in rules],
            }
            for fact_id, (relation, rules) in resolutions.items()
        }
