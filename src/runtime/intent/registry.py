from dataclasses import dataclass, field


@dataclass
class IntentEntry:
    intent_id: str
    description: str
    examples: list[str]
    priority: int
    scenario_route: str
    keywords: list[str] = field(default_factory=list)
    allowed_roles: set[str] = field(default_factory=lambda: {'doctor', 'cashier', 'admin', 'nurse', 'quality_staff', 'coding_staff'})
    status: str = 'active'
    counter_examples: list[str] = field(default_factory=list)
    required_entities: list[str] = field(default_factory=list)
    risk_level: str = 'low'


INTENT_REGISTRY: list[IntentEntry] = [
    IntentEntry(
        intent_id='settlement_exception_guidance',
        description='医保结算失败、结算异常相关问题',
        examples=['结算失败怎么办', '医保结算报错', '结算异常'],
        priority=1,
        scenario_route='guide_settlement_exception',
        keywords=['结算失败', '医保结算', '结算异常', '结算报错', '退款', '冲正'],
        allowed_roles={'cashier', 'admin', 'doctor'},
        status='active',
        counter_examples=['结算成功', '结算完成'],
        required_entities=['patient_id', 'encounter_id'],
        risk_level='medium',
    ),
    IntentEntry(
        intent_id='pre_discharge_quality_control',
        description='出院前联合质控、医保风险检查',
        examples=['出院前检查', '医保风险', '质控问题'],
        priority=2,
        scenario_route='run_pre_discharge_qc',
        keywords=['出院前', '医保风险', '质控', '出院检查', '预出院'],
        allowed_roles={'doctor', 'admin', 'quality_staff'},
        status='active',
        counter_examples=['出院后', '已出院'],
        required_entities=['patient_id', 'encounter_id'],
        risk_level='low',
    ),
    IntentEntry(
        intent_id='policy_explanation',
        description='医保政策规则解释和查询',
        examples=['医保政策怎么规定的', '报销比例是多少', '医保目录'],
        priority=3,
        scenario_route='explain_policy',
        keywords=['医保政策', '报销比例', '医保目录', '政策解释', '报销范围'],
        allowed_roles={'doctor', 'cashier', 'admin', 'nurse'},
        status='planned',
        counter_examples=['政策制定', '修改政策'],
        required_entities=[],
        risk_level='low',
    ),
    IntentEntry(
        intent_id='error_code_explanation',
        description='医保错误码含义和解决方案查询',
        examples=['错误码-1001什么意思', '医保返回码含义', '报错代码解释'],
        priority=4,
        scenario_route='explain_error_code',
        keywords=['错误码', '返回码', '报错代码', '错误代码', 'error code'],
        allowed_roles={'cashier', 'admin', 'doctor'},
        status='planned',
        counter_examples=['系统错误', '网络错误'],
        required_entities=['error_code'],
        risk_level='low',
    ),
    IntentEntry(
        intent_id='appeal_assistance',
        description='医保拒付申诉辅助',
        examples=['拒付了怎么申诉', '申诉材料', '医保拒付原因'],
        priority=5,
        scenario_route='assist_appeal',
        keywords=['拒付', '申诉', '争议', '复议', '拒付原因'],
        allowed_roles={'doctor', 'admin', 'coding_staff'},
        status='planned',
        counter_examples=['申诉成功', '已解决'],
        required_entities=['patient_id', 'encounter_id'],
        risk_level='medium',
    ),
    IntentEntry(
        intent_id='drg_dip_operations',
        description='DRG/DIP分组查询和运营分析',
        examples=['DRG分组结果', 'DIP病种分值', '分组权重'],
        priority=6,
        scenario_route='drg_dip_analysis',
        keywords=['DRG', 'DIP', '分组', '病种', '分值', '权重', 'MDC'],
        allowed_roles={'doctor', 'admin', 'quality_staff', 'coding_staff'},
        status='planned',
        counter_examples=['DRG概念解释'],
        required_entities=['patient_id', 'encounter_id'],
        risk_level='low',
    ),
    IntentEntry(
        intent_id='medical_record_risk_guidance',
        description='病案首页风险导办',
        examples=['病案首页有风险', '编码问题', '病案质量'],
        priority=7,
        scenario_route='guide_medical_record_risk',
        keywords=['病案首页', '编码', '病案质量', '病案风险', '编码风险'],
        allowed_roles={'doctor', 'admin', 'coding_staff', 'quality_staff'},
        status='planned',
        counter_examples=['病案归档', '病案已提交'],
        required_entities=['patient_id', 'encounter_id'],
        risk_level='medium',
    ),
    IntentEntry(
        intent_id='department_rectification',
        description='科室整改闭环跟踪',
        examples=['科室整改进度', '整改任务', '质控反馈'],
        priority=8,
        scenario_route='track_rectification',
        keywords=['整改', '科室整改', '质控反馈', '整改任务', '闭环'],
        allowed_roles={'admin', 'quality_staff'},
        status='planned',
        counter_examples=['个人整改'],
        required_entities=['department_id'],
        risk_level='low',
    ),
    IntentEntry(
        intent_id='medical_insurance_dashboard',
        description='医保运营驾驶舱数据查询',
        examples=['本月医保运营数据', '科室费用排名', '次均费用'],
        priority=9,
        scenario_route='query_dashboard',
        keywords=['运营驾驶舱', '运营数据', '费用排名', '次均费用', '医保数据'],
        allowed_roles={'admin', 'quality_staff'},
        status='planned',
        counter_examples=['个人数据', '患者数据'],
        required_entities=[],
        risk_level='low',
    ),
    IntentEntry(
        intent_id='mcp_tool_invocation',
        description='MCP工具调用和外部集成',
        examples=['画一个流程图', '导出数据', '生成图表'],
        priority=10,
        scenario_route='invoke_mcp_tool',
        keywords=['画图', '画一下', '画个', 'drawio', 'diagram', '图表', '架构图', '流程图', '导出', 'export', 'draw'],
        allowed_roles={'doctor', 'cashier', 'admin', 'nurse', 'quality_staff', 'coding_staff'},
        status='active',
        counter_examples=['图片', '照片'],
        required_entities=[],
        risk_level='low',
    ),
    IntentEntry(
        intent_id='unknown',
        description='无法识别的意图',
        examples=['今天天气', '你好', '随便聊聊'],
        priority=99,
        scenario_route='handle_unknown',
        keywords=[],
        allowed_roles={'doctor', 'cashier', 'admin', 'nurse', 'quality_staff', 'coding_staff'},
        status='active',
        counter_examples=[],
        required_entities=[],
        risk_level='low',
    ),
]


def get_intent_registry() -> list[IntentEntry]:
    return INTENT_REGISTRY


def get_intent_by_id(intent_id: str) -> IntentEntry | None:
    return next((e for e in INTENT_REGISTRY if e.intent_id == intent_id), None)


def get_active_intents() -> list[IntentEntry]:
    return [e for e in INTENT_REGISTRY if e.status == 'active' and e.intent_id != 'unknown']
