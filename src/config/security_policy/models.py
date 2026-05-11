from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PolicyRule:
    rule_id: str
    condition: str
    action: str
    risk_level: str
    message: str


@dataclass
class SecurityPolicy:
    policy_id: str
    name: str
    description: str
    rules: list[PolicyRule] = field(default_factory=list)
    version: str = "1.0.0"
    effective_date: str = ""


DEFAULT_HIGH_RISK_POLICY = SecurityPolicy(
    policy_id="high-risk-actions",
    name="高风险动作管控",
    description="高风险医保操作需要人工确认",
    version="1.0.0",
    effective_date="2026-01-01",
    rules=[
        PolicyRule(
            rule_id="rule-settlement",
            condition='{"==": [{"var": "action"}, "正式结算"]}',
            action="require_approval",
            risk_level="high",
            message="正式结算为高风险动作，需人工确认",
        ),
        PolicyRule(
            rule_id="rule-refund",
            condition='{"==": [{"var": "action"}, "退费"]}',
            action="require_approval",
            risk_level="high",
            message="退费为高风险动作，需人工确认",
        ),
        PolicyRule(
            rule_id="rule-reversal",
            condition='{"==": [{"var": "action"}, "冲正"]}',
            action="require_approval",
            risk_level="high",
            message="冲正为高风险动作，需人工确认",
        ),
        PolicyRule(
            rule_id="rule-cancel-settlement",
            condition='{"==": [{"var": "action"}, "撤销结算"]}',
            action="require_approval",
            risk_level="high",
            message="撤销结算为高风险动作，需人工确认",
        ),
        PolicyRule(
            rule_id="rule-medical-record-edit",
            condition='{"==": [{"var": "action"}, "病案首页修改"]}',
            action="require_approval",
            risk_level="high",
            message="病案首页修改为高风险动作，需人工确认",
        ),
        PolicyRule(
            rule_id="rule-cost-detail-edit",
            condition='{"==": [{"var": "action"}, "费用明细修改"]}',
            action="require_approval",
            risk_level="high",
            message="费用明细修改为高风险动作，需人工确认",
        ),
        PolicyRule(
            rule_id="rule-appeal-confirm",
            condition='{"==": [{"var": "action"}, "最终申诉结论确认"]}',
            action="require_approval",
            risk_level="high",
            message="最终申诉结论确认为高风险动作，需人工确认",
        ),
    ],
)

DEFAULT_SENSITIVE_DATA_POLICY = SecurityPolicy(
    policy_id="sensitive-data-access",
    name="敏感数据访问控制",
    description="访问敏感数据需要对应角色授权",
    version="1.0.0",
    effective_date="2026-01-01",
    rules=[
        PolicyRule(
            rule_id="rule-patient-data",
            condition='{"and": [{"==": [{"var": "field"}, "patient_id"]}, {"in": [{"var": "role"}, ["cashier", "medical_office", "clinician"]]}]}',
            action="allow",
            risk_level="low",
            message="患者基本信息允许收银员、医保办、临床医生访问",
        ),
        PolicyRule(
            rule_id="rule-settlement-data",
            condition='{"and": [{"==": [{"var": "field"}, "settlement_status"]}, {"in": [{"var": "role"}, ["cashier", "medical_office"]]}]}',
            action="allow",
            risk_level="medium",
            message="结算状态仅允许收银员和医保办访问",
        ),
        PolicyRule(
            rule_id="rule-audit-risk-data",
            condition='{"and": [{"==": [{"var": "field"}, "audit_risks"]}, {"in": [{"var": "role"}, ["medical_office"]]}]}',
            action="allow",
            risk_level="medium",
            message="审核风险信息仅允许医保办访问",
        ),
    ],
)

DEFAULT_POLICY_CHANGE_POLICY = SecurityPolicy(
    policy_id="policy-change-control",
    name="安全策略变更管控",
    description="修改安全策略需要管理员角色",
    version="1.0.0",
    effective_date="2026-01-01",
    rules=[
        PolicyRule(
            rule_id="rule-add-policy",
            condition='{"and": [{"==": [{"var": "action"}, "add_policy"]}, {"!": {"==": [{"var": "role"}, "admin"]}}]}',
            action="deny",
            risk_level="high",
            message="新增安全策略需要管理员权限",
        ),
        PolicyRule(
            rule_id="rule-remove-policy",
            condition='{"and": [{"==": [{"var": "action"}, "remove_policy"]}, {"!": {"==": [{"var": "role"}, "admin"]}}]}',
            action="deny",
            risk_level="high",
            message="删除安全策略需要管理员权限",
        ),
        PolicyRule(
            rule_id="rule-modify-policy",
            condition='{"and": [{"==": [{"var": "action"}, "modify_policy"]}, {"!": {"==": [{"var": "role"}, "admin"]}}]}',
            action="deny",
            risk_level="high",
            message="修改安全策略需要管理员权限",
        ),
    ],
)

DEFAULT_POLICIES: list[SecurityPolicy] = [
    DEFAULT_HIGH_RISK_POLICY,
    DEFAULT_SENSITIVE_DATA_POLICY,
    DEFAULT_POLICY_CHANGE_POLICY,
]
