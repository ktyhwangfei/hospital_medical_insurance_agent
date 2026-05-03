from src.config.security_policy.rules import ROLE_VISIBLE_FIELDS, SCENARIO_ALLOWED_ROLES


def visible_fields_for(role: str) -> set[str]:
    return ROLE_VISIBLE_FIELDS.get(role, set())


def is_allowed(role: str, scenario: str) -> bool:
    return role in SCENARIO_ALLOWED_ROLES.get(scenario, set())
