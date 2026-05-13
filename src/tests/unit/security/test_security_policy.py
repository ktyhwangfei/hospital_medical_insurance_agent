from src.config.security_policy import (
    DynamicPolicyEngine,
    PolicyEvaluationResult,
    PolicyLoader,
    PolicyRule,
    SecurityPolicy,
)


def test_high_risk_action_detection():
    engine = DynamicPolicyEngine()
    results = engine.evaluate("退费")
    assert len(results) == 1
    assert results[0].action == "require_approval"
    assert results[0].risk_level == "high"
    assert results[0].policy_id == "high-risk-actions"


def test_non_high_risk_action():
    engine = DynamicPolicyEngine()
    results = engine.evaluate("查询费用")
    assert len(results) == 0


def test_all_high_risk_actions():
    engine = DynamicPolicyEngine()
    for action in ["正式结算", "退费", "冲正", "撤销结算", "病案首页修改", "费用明细修改", "最终申诉结论确认"]:
        results = engine.evaluate(action)
        assert len(results) == 1, f"{action} should be detected as high risk"
        assert results[0].action == "require_approval"


def test_admin_policy_change_allowed():
    engine = DynamicPolicyEngine()
    results = engine.evaluate("add_policy", {"role": "admin"})
    assert len(results) == 0


def test_non_admin_policy_change_denied():
    engine = DynamicPolicyEngine()
    results = engine.evaluate("add_policy", {"role": "cashier"})
    assert len(results) == 1
    assert results[0].action == "deny"


def test_remove_and_add_policy():
    engine = DynamicPolicyEngine()
    engine.remove_policy("high-risk-actions")
    assert len(engine.get_active_policies()) == 2

    custom = SecurityPolicy(
        policy_id="test-policy",
        name="Test",
        description="Test policy",
        rules=[
            PolicyRule(
                rule_id="r1",
                condition='{"==": [{"var": "action"}, "test_action"]}',
                action="deny",
                risk_level="medium",
                message="test",
            )
        ],
    )
    engine.add_policy(custom)
    assert len(engine.get_active_policies()) == 3
    results = engine.evaluate("test_action")
    assert len(results) == 1
    assert results[0].action == "deny"


def test_reset_to_defaults():
    engine = DynamicPolicyEngine()
    engine.remove_policy("high-risk-actions")
    assert len(engine.get_active_policies()) == 2
    engine.reset_to_defaults()
    assert len(engine.get_active_policies()) == 3


def test_get_policy():
    engine = DynamicPolicyEngine()
    policy = engine.get_policy("high-risk-actions")
    assert policy is not None
    assert policy.name == "高风险动作管控"

    missing = engine.get_policy("nonexistent")
    assert missing is None


def test_sensitive_data_policy():
    engine = DynamicPolicyEngine()
    results = engine.evaluate("access_field", {"field": "patient_id", "role": "cashier"})
    assert len(results) == 1
    assert results[0].action == "allow"

    results2 = engine.evaluate("access_field", {"field": "audit_risks", "role": "cashier"})
    assert len(results2) == 0


def test_policy_loader():
    loader = PolicyLoader()
    data = {
        "policy_id": "test-loader",
        "name": "Loader Test",
        "description": "Test",
        "rules": [
            {
                "rule_id": "lr1",
                "condition": '{"==": [{"var": "action"}, "test"]}',
                "action": "deny",
                "risk_level": "high",
                "message": "test rule",
            }
        ],
        "version": "1.0.0",
        "effective_date": "2026-01-01",
    }
    policy = loader.load_from_dict(data)
    assert policy.policy_id == "test-loader"
    assert len(policy.rules) == 1
    assert policy.rules[0].rule_id == "lr1"

    engine = DynamicPolicyEngine()
    engine.add_policy(policy)
    results = engine.evaluate("test")
    assert len(results) == 1


def test_validate_policy():
    loader = PolicyLoader()
    valid = SecurityPolicy(
        policy_id="valid",
        name="Valid",
        description="",
        rules=[PolicyRule(rule_id="r1", condition='{"==": [1, 1]}', action="allow", risk_level="low", message="ok")],
    )
    errors = loader.validate_policy(valid)
    assert len(errors) == 0

    invalid = SecurityPolicy(policy_id="", name="", description="", rules=[])
    errors = loader.validate_policy(invalid)
    assert len(errors) > 0


def test_clear_policies():
    engine = DynamicPolicyEngine()
    assert len(engine.get_active_policies()) == 3
    engine.clear_policies()
    assert len(engine.get_active_policies()) == 0
    results = engine.evaluate("退费")
    assert len(results) == 0
