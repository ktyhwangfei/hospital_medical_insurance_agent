ROLE_VISIBLE_FIELDS = {
    'cashier': {'patient_id', 'encounter_id', 'settlement_status'},
    'medical_office': {'patient_id', 'encounter_id', 'settlement_status', 'audit_risks'},
    'clinician': {'patient_id', 'encounter_id'},
}

SCENARIO_ALLOWED_ROLES = {
    'settlement_exception_guidance': {'cashier', 'medical_office', 'information_department'},
    'pre_discharge_quality_control': {'medical_office', 'medical_record_staff', 'clinician'},
}

HIGH_RISK_ACTIONS = {'正式结算', '退费', '冲正', '撤销结算', '病案首页修改', '费用明细修改', '最终申诉结论确认'}
