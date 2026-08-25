ROLE_VISIBLE_FIELDS = {
    'cashier': {'patient_id', 'encounter_id', 'settlement_status'},
    'medical_office': {'patient_id', 'encounter_id', 'settlement_status', 'audit_risks'},
    'clinician': {'patient_id', 'encounter_id'},
}

ALL_ROLES = frozenset({'cashier', 'medical_office', 'information_department', 'medical_record_staff', 'clinician'})

SCENARIO_ALLOWED_ROLES = {
    'mcp_tool_invocation': ALL_ROLES,
}

# L1 硬编码兜底规则 — 仅当 risk_control_rules 表（L0）不可用时使用
HIGH_RISK_ACTIONS = {'正式结算', '退费', '冲正', '撤销结算', '病案首页修改', '费用明细修改', '最终申诉结论确认'}
