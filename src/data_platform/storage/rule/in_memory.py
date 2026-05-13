"""
内存规则解释存储（测试/降级用）
"""

from typing import Any


class InMemoryRuleStorage:
    """内存规则解释存储

    用于 USE_MEMORY_STORAGE=1 降级路径及单元测试。
    与 PostgresRuleStorage 保持相同接口签名。
    """

    def __init__(self):
        self._rules: dict[str, dict[str, Any]] = {}

    def save_rule(self, rule: dict[str, Any]) -> None:
        self._rules[rule["rule_id"]] = {**rule}

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        return self._rules.get(rule_id)

    def list_rules(self, scenario: str | None = None) -> list[dict[str, Any]]:
        items = list(self._rules.values())
        if scenario:
            items = [r for r in items if r.get("scenario") == scenario]
        return [r for r in items if r.get("enabled", True)]

    def delete_rule(self, rule_id: str) -> None:
        self._rules.pop(rule_id, None)

    def health(self) -> dict[str, Any]:
        return {"status": "healthy", "backend": "in_memory", "rules_count": len(self._rules)}
