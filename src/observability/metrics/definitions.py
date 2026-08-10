METRICS = {
    'task_completion_rate': '任务闭环完成率',
    'average_task_duration': '任务平均处理时长',
    'risk_discovery_count': '风险发现数量',
    'settlement_exception_duration': '结算异常处理时长',
    # Skill 错误挖掘与评测（低基数标签：status / reason_code / dimension /
    # evaluator_status；禁止 qa_turn_id / user_id / tenant_id / skill_id / 问题内容）
    'skill_eval_pool_created_total': '案例池新建总数',
    'skill_eval_pool_duplicate_total': '案例池重复合并总数',
    'skill_eval_transform_total': 'AI 转换总数',
    'skill_eval_confirm_total': '人工确认总数',
    'skill_eval_blocked_total': '评测阻断总数',
    'skill_eval_dimension_total': '按错误维度的案例计数',
}
