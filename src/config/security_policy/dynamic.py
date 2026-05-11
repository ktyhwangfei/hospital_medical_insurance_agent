from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from src.config.security_policy.models import (
    DEFAULT_POLICIES,
    SecurityPolicy,
)


class JSONLogicEvaluator:
    @staticmethod
    def evaluate(expression: str, context: dict[str, Any]) -> bool:
        try:
            parsed = json.loads(expression)
        except (json.JSONDecodeError, TypeError):
            return False
        return bool(JSONLogicEvaluator._evaluate(parsed, context))

    @staticmethod
    def _evaluate(node: Any, context: dict[str, Any]) -> Any:
        if isinstance(node, dict) and len(node) == 1:
            operator, value = next(iter(node.items()))
            result = JSONLogicEvaluator._apply_operator(operator, value, context)
            if result is not None:
                return result
        return node

    @staticmethod
    def _apply_operator(operator: str, value: Any, context: dict[str, Any]) -> Any:
        if operator == "var":
            return JSONLogicEvaluator._resolve_var(value, context)

        if operator == "==":
            if not isinstance(value, list) or len(value) != 2:
                return False
            return JSONLogicEvaluator._evaluate(value[0], context) == JSONLogicEvaluator._evaluate(value[1], context)

        if operator == "!=":
            if not isinstance(value, list) or len(value) != 2:
                return False
            return JSONLogicEvaluator._evaluate(value[0], context) != JSONLogicEvaluator._evaluate(value[1], context)

        if operator == "in":
            if not isinstance(value, list) or len(value) != 2:
                return False
            a = JSONLogicEvaluator._evaluate(value[0], context)
            b = JSONLogicEvaluator._evaluate(value[1], context)
            if isinstance(b, (list, tuple, set)):
                return a in b
            if isinstance(b, str):
                return str(a) in b
            return False

        if operator == "!":
            return not bool(JSONLogicEvaluator._evaluate(value, context))

        if operator == "and":
            for v in value:
                if not JSONLogicEvaluator._evaluate(v, context):
                    return False
            return True

        if operator == "or":
            for v in value:
                if JSONLogicEvaluator._evaluate(v, context):
                    return True
            return False

        return None

    @staticmethod
    def _resolve_var(value: Any, context: dict[str, Any]) -> Any:
        if isinstance(value, str):
            parts = value.split(".")
            current: Any = context
            for part in parts:
                if isinstance(current, dict):
                    current = current.get(part)
                else:
                    return None
            return current
        return value


@dataclass
class PolicyEvaluationResult:
    matched: bool
    action: str
    risk_level: str
    message: str
    policy_id: str
    rule_id: str


class DynamicPolicyEngine:
    def __init__(self) -> None:
        self._policies: dict[str, SecurityPolicy] = {}
        self._evaluator = JSONLogicEvaluator()
        self._load_defaults()

    def _load_defaults(self) -> None:
        for policy in DEFAULT_POLICIES:
            self._policies[policy.policy_id] = deepcopy(policy)

    def evaluate(self, action: str, context: dict[str, Any] | None = None) -> list[PolicyEvaluationResult]:
        ctx: dict[str, Any] = dict(context or {})
        ctx["action"] = action
        results: list[PolicyEvaluationResult] = []

        for policy in self._policies.values():
            for rule in policy.rules:
                matched = self._evaluator.evaluate(rule.condition, ctx)
                if matched:
                    results.append(
                        PolicyEvaluationResult(
                            matched=True,
                            action=rule.action,
                            risk_level=rule.risk_level,
                            message=rule.message,
                            policy_id=policy.policy_id,
                            rule_id=rule.rule_id,
                        )
                    )

        return results

    def add_policy(self, policy: SecurityPolicy) -> None:
        self._policies[policy.policy_id] = deepcopy(policy)

    def remove_policy(self, policy_id: str) -> None:
        self._policies.pop(policy_id, None)

    def get_active_policies(self) -> list[SecurityPolicy]:
        return list(self._policies.values())

    def get_policy(self, policy_id: str) -> SecurityPolicy | None:
        return self._policies.get(policy_id)

    def clear_policies(self) -> None:
        self._policies.clear()

    def reset_to_defaults(self) -> None:
        self._policies.clear()
        self._load_defaults()
