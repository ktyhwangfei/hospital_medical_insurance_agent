"""不调用模型的确定性政策规则编译器。"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Any

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
_SEGMENT_FIELDS = {"segment", "amount_band"}


def freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((key, freeze(item)) for key, item in value.items()))
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(freeze(item) for item in value))
    return value


def rule_key(fact: PolicyFact) -> tuple[object, ...]:
    return (
        fact.subject,
        fact.population,
        *(freeze(fact.conditions.get(name)) for name in RULE_KEY_FIELDS),
    )


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
        if self._has_fail(issues):
            return self._result([], all_issues, steps)

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
            if not fact.evidence:
                issues.append(self._issue(
                    "FAIL", "EVIDENCE_REQUIRED", "CANONICALIZE", fact_id=fact.fact_id,
                    message="政策事实缺少证据", action="补充原文证据后重试",
                ))
                continue
            value = dict(fact.value)
            if "ratio" in value:
                ratio = normalize_ratio(value["ratio"])
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
                issues.append(self._issue(
                    "REVIEW", "CONFLICT", "COMPOSE", fact_id=group[0].fact_id,
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
    def _has_fail(issues: Iterable[ValidationIssue]) -> bool:
        return any(issue.severity == "FAIL" for issue in issues)

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
