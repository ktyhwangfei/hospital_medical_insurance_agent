from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.config.security_policy.models import PolicyRule, SecurityPolicy


class PolicyLoader:
    def __init__(self) -> None:
        self._errors: list[str] = []

    def load_from_file(self, path: str) -> list[SecurityPolicy]:
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Policy file not found: {path}")

        suffix = file_path.suffix.lower()
        raw = file_path.read_text(encoding="utf-8")

        if suffix in (".json",):
            data = json.loads(raw)
        elif suffix in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore[import-untyped]

                data = yaml.safe_load(raw)
            except ImportError:
                raise ImportError("PyYAML is required to load YAML policy files")
        else:
            raise ValueError(f"Unsupported policy file format: {suffix}")

        return self._parse_list(data)

    def load_from_dict(self, data: dict) -> SecurityPolicy:
        return self._parse_single(data)

    def load_from_dict_list(self, data: list[dict]) -> list[SecurityPolicy]:
        return self._parse_list(data)

    def validate_policy(self, policy: SecurityPolicy) -> list[str]:
        errors: list[str] = []
        if not policy.policy_id:
            errors.append("policy_id is required")
        if not policy.name:
            errors.append("name is required")
        if not policy.rules:
            errors.append("policy must have at least one rule")
        if not policy.version:
            errors.append("version is required")

        for rule in policy.rules:
            rule_errors = self._validate_rule(rule)
            errors.extend(rule_errors)

        return errors

    def _validate_rule(self, rule: PolicyRule) -> list[str]:
        errors: list[str] = []
        if not rule.rule_id:
            errors.append("rule_id is required for each rule")
        if not rule.condition:
            errors.append(f"condition is required for rule {rule.rule_id}")
        if rule.action not in ("allow", "deny", "require_approval"):
            errors.append(f"invalid action '{rule.action}' in rule {rule.rule_id}: must be allow, deny, or require_approval")
        if rule.risk_level not in ("high", "medium", "low"):
            errors.append(f"invalid risk_level '{rule.risk_level}' in rule {rule.rule_id}: must be high, medium, or low")

        try:
            parsed = json.loads(rule.condition)
            if not isinstance(parsed, dict):
                errors.append(f"condition must be a JSON object in rule {rule.rule_id}")
        except json.JSONDecodeError:
            errors.append(f"condition is not valid JSON in rule {rule.rule_id}")

        return errors

    def _parse_single(self, data: dict[str, Any]) -> SecurityPolicy:
        rules_data = data.get("rules", [])
        rules = [
            PolicyRule(
                rule_id=r["rule_id"],
                condition=r["condition"],
                action=r["action"],
                risk_level=r["risk_level"],
                message=r.get("message", ""),
            )
            for r in rules_data
        ]
        return SecurityPolicy(
            policy_id=data["policy_id"],
            name=data["name"],
            description=data.get("description", ""),
            rules=rules,
            version=data.get("version", "1.0.0"),
            effective_date=data.get("effective_date", ""),
        )

    def _parse_list(self, data: list[dict[str, Any]]) -> list[SecurityPolicy]:
        return [self._parse_single(item) for item in data]
