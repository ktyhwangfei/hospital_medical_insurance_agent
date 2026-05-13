-- ============================================================================
-- 院端医保智能体系统 - 数据库初始化脚本
-- 数据库: hospital_mcp (PostgreSQL)
-- 版本: 3.0
-- 日期: 2026-05-12
-- 说明: 自动建表 + 种子数据（可重复执行，ON CONFLICT 幂等）
-- 使用: psql -U postgres -d hospital_mcp -f scripts/init_data.sql
-- ============================================================================

-- ============================================================================
-- 第一部分: 核心业务数据
-- ============================================================================

-- 1. 患者信息
CREATE TABLE IF NOT EXISTS patients (
    patient_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. 医保交易记录
CREATE TABLE IF NOT EXISTS insurance_transactions (
    id SERIAL PRIMARY KEY,
    patient_id VARCHAR(64) NOT NULL,
    encounter_id VARCHAR(64) NOT NULL,
    settlement_status VARCHAR(32),
    upload_status VARCHAR(32),
    error_code VARCHAR(64),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(patient_id, encounter_id)
);
CREATE INDEX IF NOT EXISTS idx_transactions_patient ON insurance_transactions(patient_id);

-- ============================================================================
-- 第二部分: 平台运行数据
-- ============================================================================

-- 3. 工作流实例
CREATE TABLE IF NOT EXISTS workflows (
    workflow_id VARCHAR(128) PRIMARY KEY,
    scenario VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    current_step VARCHAR(128),
    steps JSONB NOT NULL DEFAULT '[]'::JSONB,
    audit_refs JSONB NOT NULL DEFAULT '[]'::JSONB,
    knowledge_events JSONB NOT NULL DEFAULT '[]'::JSONB,
    knowledge_degradation_reasons JSONB NOT NULL DEFAULT '[]'::JSONB,
    session_id VARCHAR(128),
    patient_id VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 4. 工作流执行单元
CREATE TABLE IF NOT EXISTS tasks (
    task_id VARCHAR(128) PRIMARY KEY,
    task_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    description TEXT,
    responsible_role VARCHAR(64),
    workflow_id VARCHAR(128),
    confirmed_by VARCHAR(64),
    confirmed_at TIMESTAMPTZ,
    reason TEXT,
    executor_type VARCHAR(64),
    input_data JSONB NOT NULL DEFAULT '{}'::JSONB,
    output_data JSONB NOT NULL DEFAULT '{}'::JSONB,
    step_id VARCHAR(128),
    error_message TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tasks_workflow ON tasks(workflow_id);
CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(task_type);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

-- 5. 网关审计日志
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(64) NOT NULL,
    workflow_id VARCHAR(128),
    step_id VARCHAR(128),
    payload JSON NOT NULL DEFAULT '{}',
    user_id VARCHAR(64),
    session_id VARCHAR(128),
    role VARCHAR(32),
    request_path VARCHAR(512),
    request_method VARCHAR(16),
    request_summary JSONB,
    response_status INTEGER,
    response_summary JSONB,
    client_ip VARCHAR(64),
    user_agent VARCHAR(512),
    duration_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_logs(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_workflow ON audit_logs(workflow_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);

-- 6. 用户会话
CREATE TABLE IF NOT EXISTS sessions (
    session_id VARCHAR(128) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    role VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_active TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 第三部分: 配置与知识数据
-- ============================================================================

-- 7. AI 技能注册表
CREATE TABLE IF NOT EXISTS skills (
    skill_id VARCHAR(128) PRIMARY KEY,
    name VARCHAR(256) NOT NULL,
    description TEXT,
    owner VARCHAR(128),
    steps JSONB DEFAULT '[]',
    intent_keywords JSONB DEFAULT '[]',
    required_roles JSONB DEFAULT '[]',
    enabled BOOLEAN DEFAULT TRUE,
    risk_level VARCHAR(32) DEFAULT 'LOW',
    license VARCHAR(128),
    compatibility TEXT,
    allowed_tools JSONB DEFAULT '[]',
    skill_metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_skills_owner ON skills(owner);

-- 8. MCP 服务器注册
CREATE TABLE IF NOT EXISTS mcp_servers (
    server_id VARCHAR(128) PRIMARY KEY,
    name VARCHAR(256),
    payload_json TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    transport VARCHAR(32) NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 9. MCP 能力注册
CREATE TABLE IF NOT EXISTS mcp_capabilities (
    capability_id VARCHAR(128) PRIMARY KEY,
    server_id VARCHAR(128) NOT NULL,
    payload_json TEXT NOT NULL,
    capability_type VARCHAR(32) NOT NULL,
    risk_level VARCHAR(32) NOT NULL,
    enabled BOOLEAN NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_mcp_capabilities_server_id ON mcp_capabilities(server_id);

-- 10. 错误码知识库
CREATE TABLE IF NOT EXISTS error_code_knowledge (
    error_code VARCHAR(64) PRIMARY KEY,
    description TEXT,
    exception_type VARCHAR(128),
    responsible_role VARCHAR(64),
    recommendation TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 11. 规则解释库
CREATE TABLE IF NOT EXISTS rule_explanations (
    rule_id VARCHAR(128) PRIMARY KEY,
    rule_name VARCHAR(256) NOT NULL,
    category VARCHAR(64),
    scenario VARCHAR(64),
    rule_content TEXT,
    explanation TEXT,
    applicable_roles JSONB DEFAULT '[]',
    risk_level VARCHAR(32) DEFAULT 'LOW',
    effective_date DATE,
    enabled BOOLEAN DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rules_category ON rule_explanations(category);
CREATE INDEX IF NOT EXISTS idx_rules_scenario ON rule_explanations(scenario);

-- 12. 知识资产
CREATE TABLE IF NOT EXISTS knowledge_assets (
    asset_id VARCHAR(128) PRIMARY KEY,
    title VARCHAR(512) NOT NULL,
    source VARCHAR(256),
    asset_type VARCHAR(64),
    version VARCHAR(32),
    status VARCHAR(32) DEFAULT 'draft',
    summary TEXT,
    visibility JSONB DEFAULT '{}',
    index_status VARCHAR(32),
    effective_date DATE,
    imported_at TIMESTAMP,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_assets_type ON knowledge_assets(asset_type);
CREATE INDEX IF NOT EXISTS idx_assets_status ON knowledge_assets(status);

-- 13. 知识切片（向量化源）
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id VARCHAR(128) PRIMARY KEY,
    asset_id VARCHAR(128) NOT NULL,
    asset_type VARCHAR(64),
    title VARCHAR(512),
    section VARCHAR(256),
    text TEXT,
    summary TEXT,
    tags JSONB DEFAULT '[]',
    scenario_tags JSONB DEFAULT '[]',
    visibility JSONB DEFAULT '{}',
    locator VARCHAR(256),
    embedding_id VARCHAR(128),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chunks_asset ON knowledge_chunks(asset_id);

-- ============================================================================
-- 第四部分: 安全风控
-- ============================================================================

-- 14. 风控规则
CREATE TABLE IF NOT EXISTS risk_control_rules (
    rule_id VARCHAR(128) PRIMARY KEY,
    rule_name VARCHAR(256) NOT NULL,
    action_pattern TEXT NOT NULL,
    risk_level VARCHAR(32) DEFAULT 'HIGH',
    block_reason TEXT,
    recommendation TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 15. 风控事件记录
CREATE TABLE IF NOT EXISTS risk_control_events (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(64) UNIQUE,
    event_type VARCHAR(64) NOT NULL DEFAULT 'risk_detected',
    rule_id VARCHAR(128),
    user_id VARCHAR(64),
    patient_id VARCHAR(64),
    encounter_id VARCHAR(64),
    role VARCHAR(32),
    action TEXT,
    risk_level VARCHAR(32) NOT NULL DEFAULT 'HIGH',
    blocked BOOLEAN NOT NULL DEFAULT FALSE,
    result VARCHAR(32),
    reason TEXT,
    message_preview TEXT,
    workflow_id VARCHAR(128),
    context JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_risk_events_rule ON risk_control_events(rule_id);
CREATE INDEX IF NOT EXISTS idx_risk_events_created ON risk_control_events(created_at);

-- ============================================================================
-- 第五部分: 模板管理
-- ============================================================================

-- 16. 申诉模板
CREATE TABLE IF NOT EXISTS appeal_templates (
    template_id VARCHAR(128) PRIMARY KEY,
    template_name VARCHAR(256) NOT NULL,
    template_type VARCHAR(64),
    denial_reason_pattern VARCHAR(256),
    content TEXT NOT NULL,
    required_evidence JSONB DEFAULT '[]',
    applicable_scenarios JSONB DEFAULT '[]',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_appeal_templates_type ON appeal_templates(template_type);

-- 17. 提示词模板
CREATE TABLE IF NOT EXISTS prompt_templates (
    template_id VARCHAR(128) PRIMARY KEY,
    template_name VARCHAR(256) NOT NULL,
    template_type VARCHAR(64) NOT NULL,
    scenario VARCHAR(64),
    role VARCHAR(64),
    system_prompt TEXT,
    user_prompt_template TEXT,
    variables JSONB DEFAULT '[]',
    output_format JSONB DEFAULT '{}',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_prompts_scenario ON prompt_templates(scenario);
CREATE INDEX IF NOT EXISTS idx_prompts_role ON prompt_templates(role);

-- ============================================================================
-- 第六部分: LangGraph 编排
-- ============================================================================

-- 18. LangGraph 检查点
CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
    thread_id VARCHAR(128) NOT NULL,
    checkpoint_ns VARCHAR(128) NOT NULL DEFAULT '',
    checkpoint_id VARCHAR(128) NOT NULL,
    parent_checkpoint_id VARCHAR(128),
    state JSONB NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_thread ON langgraph_checkpoints(thread_id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_parent ON langgraph_checkpoints(parent_checkpoint_id);

-- 19. LangGraph 挂起写入
CREATE TABLE IF NOT EXISTS langgraph_writes (
    thread_id VARCHAR(128) NOT NULL,
    checkpoint_ns VARCHAR(128) NOT NULL DEFAULT '',
    checkpoint_id VARCHAR(128) NOT NULL,
    task_id VARCHAR(128) NOT NULL,
    idx INTEGER NOT NULL,
    channel VARCHAR(128) NOT NULL,
    value JSONB DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

-- ============================================================================
-- 第七部分: 种子测试数据
-- ============================================================================

-- --------------------------------------------------------------------------
-- 7.1 患者数据
-- --------------------------------------------------------------------------
INSERT INTO patients (patient_id, name) VALUES
    ('P001', '张三'),
    ('P002', '李四'),
    ('P003', '王五'),
    ('P004', '赵六'),
    ('P005', '孙七')
ON CONFLICT (patient_id) DO UPDATE SET name = EXCLUDED.name;

-- --------------------------------------------------------------------------
-- 7.2 医保交易记录
-- --------------------------------------------------------------------------
INSERT INTO insurance_transactions (patient_id, encounter_id, settlement_status, upload_status, error_code) VALUES
    ('P001', 'E001', 'failed',      'failed',    'E-UPLOAD-001'),
    ('P001', 'E002', 'success',     'success',   NULL),
    ('P002', 'E003', 'failed',      'failed',    'E-DRUG-002'),
    ('P002', 'E004', 'failed',      'failed',    'E-INFO-003'),
    ('P003', 'E005', 'pending',     'pending',   NULL),
    ('P003', 'E006', 'failed',      'success',   'E-DRG-004'),
    ('P004', 'E007', 'success',     'success',   NULL),
    ('P005', 'E008', 'failed',      'failed',    'E-REIMB-005')
ON CONFLICT (patient_id, encounter_id) DO UPDATE SET
    settlement_status = EXCLUDED.settlement_status,
    upload_status = EXCLUDED.upload_status,
    error_code = EXCLUDED.error_code;

-- --------------------------------------------------------------------------
-- 7.3 错误码知识库
-- --------------------------------------------------------------------------
INSERT INTO error_code_knowledge (error_code, description, exception_type, responsible_role, recommendation) VALUES
    ('E-UPLOAD-001', '费用明细未全部上传',                 '费用上传异常',   '收费员', '请核对费用上传状态，补传失败明细后重新预结算。'),
    ('E-DRUG-002',   '药品不在医保目录范围内',             '医保目录异常',   '医生',   '请核实该药品是否在医保三大目录范围内，如在目录外需告知患者自费。'),
    ('E-INFO-003',   '参保人身份信息不匹配',               '参保人异常',     '医保办', '请核实参保人身份证号与医保系统中的参保信息是否一致，如有误需到医保经办机构更新。'),
    ('E-DRG-004',    'DRG分组与诊断不匹配',                'DRG分组异常',    '病案室', '请核实病案首页诊断编码与DRG分组规则是否匹配，必要时申请分组复核。'),
    ('E-REIMB-005',  '报销比例计算异常',                   '报销计算异常',   '医保办', '请核对患者医保类型与报销政策，确认起付线、封顶线和报销比例配置正确。'),
    ('E-SETTLE-006', '结算总金额超出医保限额',             '结算金额异常',   '收费员', '请检查费用明细是否有误，如费用无误需患者自付超出限额部分。'),
    ('E-PREAUD-007', '事前审核未通过',                     '事前审核异常',   '医生',   '请根据事前审核拒绝原因调整诊疗方案或补充审核材料后重新提交。'),
    ('E-POLICY-008', '政策变动导致费用项目不可结算',       '政策变动异常',   '医保办', '该项目因医保政策调整暂不可结算，请确认最新政策后告知患者替代方案。'),
    ('E-SYSTEM-009', '医保系统接口超时',                   '系统异常',       '信息科', '医保结算系统接口响应超时，请检查网络连接后重试。'),
    ('E-DUPLIC-010', '疑似重复结算',                       '重复结算异常',   '收费员', '系统检测到该就诊可能存在重复结算，请核实是否已结算过，避免重复收费。')
ON CONFLICT (error_code) DO UPDATE SET
    description = EXCLUDED.description,
    exception_type = EXCLUDED.exception_type,
    responsible_role = EXCLUDED.responsible_role,
    recommendation = EXCLUDED.recommendation;

-- --------------------------------------------------------------------------
-- 7.4 规则解释库
-- --------------------------------------------------------------------------
INSERT INTO rule_explanations (rule_id, rule_name, category, scenario, rule_content, explanation, applicable_roles, risk_level, effective_date, enabled) VALUES
    ('RULE-001', '医保目录匹配规则',           '目录管理', 'settlement_exception', '费用项目须在医保三大目录（药品、诊疗项目、医疗服务设施）范围内方可结算。', '当结算出现费用项目不在医保目录内的错误时，收费员需核对药品编码、诊疗项目编码是否与医保目录一致，不一致则需联系医生修改医嘱或告知患者自费。', '["billing_staff","insurance_officer"]', 'LOW',    '2025-01-01', TRUE),
    ('RULE-002', 'DRG分组入组规则',             'DRG管理',  'pre_discharge_qc',    'DRG分组依据主要诊断、手术操作、年龄、性别、出院方式等因素综合判定。', '病案首页填写质量直接影响DRG分组结果。质控时需核实主要诊断选择是否正确、手术操作编码是否完整、合并症/并发症是否遗漏。', '["medical_record_staff","doctor"]', 'MEDIUM', '2025-01-01', TRUE),
    ('RULE-003', '事前审核拦截规则',           '审核管理', 'pre_discharge_qc',    '特定诊疗项目、高值耗材、超限用药等需事前审核通过方可结算。', '医生开具医嘱时，系统自动比对事前审核规则库。被拦截的项目需提交审核申请，审核通过后方可执行。', '["doctor","insurance_officer"]', 'HIGH',   '2025-03-01', TRUE),
    ('RULE-004', '报销比例分层规则',           '报销管理', 'settlement_exception', '职工医保报销比例85%%，居民医保报销比例70%%，退休人员报销比例90%%。', '结算时系统根据患者医保类型自动计算报销金额。异常通常源于医保类型登记错误或政策理解偏差。', '["billing_staff"]', 'LOW',    '2025-01-01', TRUE),
    ('RULE-005', '拒付申诉规则',               '申诉管理', 'appeal',              '对医保拒付决定有异议的，可在收到拒付通知后15个工作日内提交申诉材料。', '申诉需提供：病案首页、费用清单、诊断证明、申诉理由说明。缺少任一材料将不予受理。', '["insurance_officer","doctor"]', 'MEDIUM', '2025-06-01', TRUE),
    ('RULE-006', '高值耗材使用规范',           '耗材管理', 'pre_discharge_qc',    '单价超过2000元的耗材需在病历中记录使用理由，并经科室主任审批。', '质控时需检查高值耗材使用的必要性和合理性，确保病历记录完整、审批流程合规。', '["doctor","department_head"]', 'HIGH',   '2025-01-01', TRUE)
ON CONFLICT (rule_id) DO UPDATE SET
    rule_name = EXCLUDED.rule_name,
    category = EXCLUDED.category,
    scenario = EXCLUDED.scenario,
    rule_content = EXCLUDED.rule_content,
    explanation = EXCLUDED.explanation,
    applicable_roles = EXCLUDED.applicable_roles,
    risk_level = EXCLUDED.risk_level,
    effective_date = EXCLUDED.effective_date,
    enabled = EXCLUDED.enabled;

-- --------------------------------------------------------------------------
-- 7.5 知识资产
-- --------------------------------------------------------------------------
INSERT INTO knowledge_assets (asset_id, title, source, asset_type, version, status, summary, index_status) VALUES
    ('ASSET-001', '北京市基本医疗保险药品目录（2025版）', '北京市医保局', 'policy_doc',   '2025.1', 'published', '收录西药、中成药、中药饮片等医保目录药品，共2860个品种。', 'indexed'),
    ('ASSET-002', 'DRG分组方案（CHS-DRG 2025版）',        '国家医保局',   'policy_doc',   '2025.1', 'published', 'CHS-DRG分组方案，包含618个ADRG组和246个DRG组。', 'indexed'),
    ('ASSET-003', '医保结算异常处理手册',                 '院内编制',     'guide',        '1.0',    'published', '院内常见结算异常类型及标准化处理流程，含20种常见错误码处理方案。', 'indexed'),
    ('ASSET-004', '出院前医保质控检查清单',               '院内编制',     'checklist',    '2.0',    'published', '出院前需完成的医保质控检查项清单，覆盖诊断、费用、审核三大领域。', 'indexed'),
    ('ASSET-005', '2025年度医保报销政策汇编',             '市人社局',     'policy_doc',   '2025',   'published', '2025年度职工医保、居民医保、大病保险报销政策汇总。', 'pending')
ON CONFLICT (asset_id) DO UPDATE SET
    title = EXCLUDED.title,
    source = EXCLUDED.source,
    asset_type = EXCLUDED.asset_type,
    status = EXCLUDED.status,
    summary = EXCLUDED.summary,
    index_status = EXCLUDED.index_status;

-- --------------------------------------------------------------------------
-- 7.6 知识切片
-- --------------------------------------------------------------------------
INSERT INTO knowledge_chunks (chunk_id, asset_id, asset_type, title, section, text, summary, tags, scenario_tags) VALUES
    ('CHUNK-001', 'ASSET-001', 'policy_doc', '西药目录-A类',    '西药部分', '阿莫西林胶囊、头孢克肟片、阿奇霉素片...', '抗菌药物类医保目录药品', '["西药","抗菌药"]', '["settlement_exception"]'),
    ('CHUNK-002', 'ASSET-001', 'policy_doc', '中成药目录-A类',  '中成药部分', '连花清瘟颗粒、蒲地蓝消炎口服液...', '中成药类医保目录药品', '["中成药"]', '["settlement_exception"]'),
    ('CHUNK-003', 'ASSET-002', 'policy_doc', 'ADRG分组-呼吸',  '呼吸系统', 'ES1 呼吸系统感染/炎症...', '呼吸系统疾病DRG分组方案', '["DRG","呼吸科"]', '["pre_discharge_qc"]'),
    ('CHUNK-004', 'ASSET-002', 'policy_doc', 'ADRG分组-循环',  '循环系统', 'FM1 急性心肌梗死...', '循环系统疾病DRG分组方案', '["DRG","心内科"]', '["pre_discharge_qc"]'),
    ('CHUNK-005', 'ASSET-003', 'guide',       '费用上传异常处理', '第一章', '常见费用上传异常包括：1. 费用明细缺失 2. 费用编码不匹配...', '费用上传异常的标准处理流程', '["费用上传","结算异常"]', '["settlement_exception"]'),
    ('CHUNK-006', 'ASSET-003', 'guide',       '药品目录匹配异常', '第二章', '当出现药品不在目录内的错误时：1. 核对药品编码 2. 查询替代药品...', '药品目录匹配异常处理流程', '["药品目录","结算异常"]', '["settlement_exception"]'),
    ('CHUNK-007', 'ASSET-004', 'checklist',   '诊断质控检查项',   '第一节', '1. 主要诊断选择是否正确 2. 合并症/并发症编码是否完整...', '出院前诊断相关质控检查项', '["诊断","质控"]', '["pre_discharge_qc"]'),
    ('CHUNK-008', 'ASSET-004', 'checklist',   '费用质控检查项',   '第二节', '1. 费用明细是否完整 2. 高值耗材是否有审批记录...', '出院前费用相关质控检查项', '["费用","质控"]', '["pre_discharge_qc"]')
ON CONFLICT (chunk_id) DO UPDATE SET
    text = EXCLUDED.text,
    summary = EXCLUDED.summary,
    tags = EXCLUDED.tags,
    scenario_tags = EXCLUDED.scenario_tags;

-- --------------------------------------------------------------------------
-- 7.7 风控规则
-- --------------------------------------------------------------------------
INSERT INTO risk_control_rules (rule_id, rule_name, action_pattern, risk_level, block_reason, recommendation, enabled) VALUES
    ('RISK-001', '正式结算拦截',           '正式结算|最终结算|确认结算',       'HIGH',   '正式结算属于高风险操作，需人工审核确认',     '请仔细核对结算金额与患者信息，确认无误后在既有业务系统中执行结算。', TRUE),
    ('RISK-002', '退费操作拦截',           '退费|退款',                      'HIGH',   '退费操作涉及资金安全，需人工审核确认',       '请核实退费原因和金额，确认后在收费系统中执行退费。', TRUE),
    ('RISK-003', '冲正操作拦截',           '冲正|撤销|作废',                 'HIGH',   '冲正操作不可逆，需人工审核确认',             '请核实需要冲正的原始交易，确认后在系统中执行冲正。', TRUE),
    ('RISK-004', '病案修改拦截',           '修改病案|篡改病案|修改诊断',     'HIGH',   '病案修改需遵循病案管理规定',                 '请在病案管理系统中按规范流程修改病案，保留修改痕迹。', TRUE),
    ('RISK-005', '批量数据导出拦截',       '批量导出|全部导出|数据导出',     'MEDIUM', '批量导出涉及患者隐私数据',                   '请确认导出目的和范围，遵循数据安全管理规定。', TRUE),
    ('RISK-006', '药品目录修改拦截',       '修改药品目录|调整医保目录',      'HIGH',   '医保目录修改属于高风险配置变更',             '请确认变更依据，由医保办审核后在正式系统中操作。', TRUE),
    ('RISK-007', '报销比例调整拦截',       '调整报销比例|修改报销比例',      'HIGH',   '报销比例调整影响结算金额',                   '请确认政策依据，由医保办审核后操作。', TRUE)
ON CONFLICT (rule_id) DO UPDATE SET
    rule_name = EXCLUDED.rule_name,
    action_pattern = EXCLUDED.action_pattern,
    risk_level = EXCLUDED.risk_level,
    block_reason = EXCLUDED.block_reason,
    recommendation = EXCLUDED.recommendation,
    enabled = EXCLUDED.enabled;

-- --------------------------------------------------------------------------
-- 7.8 申诉模板
-- --------------------------------------------------------------------------
INSERT INTO appeal_templates (template_id, template_name, template_type, denial_reason_pattern, content, required_evidence, applicable_scenarios) VALUES
    ('at-001', '费用上传异常申诉模板',        'appeal', '费用上传',
     '申诉事由：因费用上传异常导致结算失败。\n处理经过：已核对费用明细，补传缺失数据。\n申诉依据：根据医保结算管理办法第X条...\n请求：撤销拒付决定，重新结算。',
     '["费用明细清单","上传日志截图"]', '["settlement_exception"]'),
    ('at-002', 'DRG分组争议申诉模板',          'appeal', 'DRG分组',
     '申诉事由：因DRG分组不合理导致支付偏差。\n患者情况：主要诊断XX，手术操作XX，合并症XX。\n申诉依据：根据CHS-DRG分组方案，应入组XX。\n请求：重新核定DRG分组，调整支付标准。',
     '["病案首页","诊断证明","手术记录"]', '["drg_dip_operation"]'),
    ('at-003', '药品目录争议申诉模板',        'appeal', '药品目录',
     '申诉事由：因药品不在医保目录内导致拒付。\n药品信息：药品名称XX，医保编码XX。\n申诉依据：该药品属于医保目录XX类，应纳入报销范围。\n请求：重新审核药品目录匹配结果。',
     '["药品说明书","处方记录","临床必要性说明"]', '["settlement_exception"]'),
    ('at-004', '事前审核争议申诉模板',        'appeal', '事前审核',
     '申诉事由：事前审核被拦截导致诊疗延迟。\n审核项目：XX诊疗项目/高值耗材。\n申诉依据：该诊疗方案符合临床诊疗指南，具有必要性。\n请求：豁免事前审核限制，补办审核手续。',
     '["病历记录","会诊意见","诊疗必要性说明"]', '["pre_discharge_qc"]')
ON CONFLICT (template_id) DO UPDATE SET
    template_name = EXCLUDED.template_name,
    content = EXCLUDED.content;

-- --------------------------------------------------------------------------
-- 7.9 提示词模板
-- --------------------------------------------------------------------------
INSERT INTO prompt_templates (template_id, template_name, template_type, scenario, role, system_prompt, user_prompt_template, variables, output_format) VALUES
    ('pt-001', '意图识别提示词',             'system',   'intent_detection',                'system',      '你是一个医保智能导办助手，负责识别用户的医保业务意图。请根据用户消息和上下文，准确判断意图类型。', NULL, '["user_message","patient_context"]', '{"intent":"string","confidence":"float","entities":"dict"}'),
    ('pt-002', '结算异常导办提示词',         'scenario', 'settlement_exception_guidance', 'cashier',     '你是一个医保结算异常导办专家，帮助收费员处理结算异常。请根据错误码和患者信息，提供清晰的处理建议。', NULL, '["error_code","patient_info","knowledge"]', '{"recommendation":"string","responsible_role":"string","steps":"list"}'),
    ('pt-003', '出院前质控提示词',           'scenario', 'pre_discharge_qc',              'doctor',      '你是医院医保出院前质控专家。请根据患者信息和审核结果，评估出院前医保风险并生成质控建议。', NULL, '["patient_info","audit_results"]', '{"risks":"list","recommendations":"string"}'),
    ('pt-004', '拒付申诉撰写提示词',         'scenario', 'appeal',                         'insurance_officer', '你是一个医保拒付申诉撰写专家。根据拒付原因和患者病历，生成专业的申诉文书。', NULL, '["denial_reason","patient_case","evidence_list"]', '{"appeal_document":"string","key_arguments":"list"}'),
    ('pt-005', 'DRG运营分析提示词',          'analysis', 'drg_dip_operation',             'manager',     '你是DRG运营分析专家。请根据医院DRG数据，分析盈亏情况并给出运营建议。', NULL, '["drg_data","hospital_info","period"]', '{"analysis":"string","recommendations":"list","metrics":"dict"}'),
    ('pt-006', '通用医保政策问答提示词',     'general',  'general',                        'any',         '你是一个专业的医保政策咨询助手。请根据最新的医保政策，准确回答用户的问题。回答时请引用具体的政策条款。', NULL, '["user_question","relevant_policies"]', '{"answer":"string","citations":"list"}')
ON CONFLICT (template_id) DO UPDATE SET
    template_name = EXCLUDED.template_name,
    system_prompt = EXCLUDED.system_prompt;

-- --------------------------------------------------------------------------
-- 7.10 AI 技能注册
-- --------------------------------------------------------------------------
INSERT INTO skills (skill_id, name, description, owner, steps, intent_keywords, required_roles, risk_level) VALUES
    ('skill-settlement-guide',   '结算异常导办',              '帮助收费员和医生处理医保结算异常，根据错误码提供诊断和处理建议', 'platform', '[]', '["结算失败","结算异常","上传失败","错误码","结算不了","无法结算","医保结算"]', '["billing_staff","doctor","insurance_officer"]', 'LOW'),
    ('skill-pre-discharge-qc',   '出院前联合质控',            '在患者出院前进行医保合规性审核，检查诊断、费用、药品等',       'platform', '[]', '["出院","质控","审核","出院前检查","出院审核","出院前"]',       '["doctor","medical_record_staff","insurance_officer"]', 'MEDIUM'),
    ('skill-drg-analysis',       'DRG/DIP运营分析',           '分析科室DRG/DIP运营数据，提供盈亏分析和管理建议',              'platform', '[]', '["DRG","DIP","运营分析","盈亏","分组","CMI"]',                  '["manager","insurance_officer"]', 'MEDIUM'),
    ('skill-appeal-assistant',   '拒付申诉助手',              '辅助生成医保拒付申诉材料，提供申诉模板和证据清单',            'platform', '[]', '["拒付","申诉","申诉材料","申诉书","申诉模板"]',                 '["insurance_officer","doctor"]', 'MEDIUM'),
    ('skill-medical-record-risk','病案首页风险导办',          '检查病案首页填写质量，识别DRG分组风险和医保合规风险',          'platform', '[]', '["病案首页","病案","诊断编码","手术编码"]',                       '["medical_record_staff","doctor"]', 'LOW'),
    ('skill-policy-qa',          '医保政策与规则解释',        '根据最新医保政策，回答用户关于报销、目录、DRG等政策问题',      'platform', '[]', '["政策","报销比例","目录","报销政策","医保政策","规定"]',        '["any"]', 'LOW')
ON CONFLICT (skill_id) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    intent_keywords = EXCLUDED.intent_keywords,
    required_roles = EXCLUDED.required_roles;

-- --------------------------------------------------------------------------
-- 7.11 MCP 服务器
-- --------------------------------------------------------------------------
INSERT INTO mcp_servers (server_id, name, payload_json, status, transport) VALUES
    ('mcp-server-local-tools', '院内本地工具集',
     '{"server_id":"mcp-server-local-tools","name":"院内本地工具集","description":"提供院内系统查询、费用查询等本地工具"}',
     'active', 'stdio'),
    ('mcp-server-insurance', '医保接口服务',
     '{"server_id":"mcp-server-insurance","name":"医保接口服务","description":"提供医保结算查询、目录查询、事前审核等医保接口"}',
     'active', 'stdio')
ON CONFLICT (server_id) DO UPDATE SET
    name = EXCLUDED.name,
    payload_json = EXCLUDED.payload_json,
    status = EXCLUDED.status;

-- --------------------------------------------------------------------------
-- 7.12 MCP 能力注册
-- --------------------------------------------------------------------------
INSERT INTO mcp_capabilities (capability_id, server_id, payload_json, capability_type, risk_level, enabled) VALUES
    ('cap-query-patient',       'mcp-server-local-tools', '{"name":"查询患者信息","description":"根据患者ID查询患者基本信息"}',                     'tool', 'LOW',    TRUE),
    ('cap-query-fee',           'mcp-server-local-tools', '{"name":"查询费用明细","description":"根据就诊ID查询费用明细列表"}',                       'tool', 'LOW',    TRUE),
    ('cap-query-settlement',    'mcp-server-insurance',   '{"name":"查询结算状态","description":"查询医保结算状态和错误码"}',                         'tool', 'LOW',    TRUE),
    ('cap-query-drug-catalog',  'mcp-server-insurance',   '{"name":"查询药品目录","description":"查询药品是否在医保目录内及报销比例"}',               'tool', 'LOW',    TRUE),
    ('cap-pre-audit-check',     'mcp-server-insurance',   '{"name":"事前审核检查","description":"对诊疗项目进行事前审核规则检查"}',                   'tool', 'MEDIUM', TRUE),
    ('cap-drg-group-query',     'mcp-server-insurance',   '{"name":"DRG分组查询","description":"根据诊断和手术编码查询DRG分组结果"}',                 'tool', 'LOW',    TRUE),
    ('cap-settlement-submit',   'mcp-server-insurance',   '{"name":"提交结算","description":"提交医保正式结算（高风险操作）"}',                       'tool', 'HIGH',   FALSE)
ON CONFLICT (capability_id) DO UPDATE SET
    server_id = EXCLUDED.server_id,
    payload_json = EXCLUDED.payload_json,
    capability_type = EXCLUDED.capability_type,
    risk_level = EXCLUDED.risk_level,
    enabled = EXCLUDED.enabled;

-- --------------------------------------------------------------------------
-- 7.13 会话数据
-- --------------------------------------------------------------------------
INSERT INTO sessions (session_id, user_id, role) VALUES
    ('sess-20260512-001', 'U001', 'doctor'),
    ('sess-20260512-002', 'U002', 'billing_staff'),
    ('sess-20260512-003', 'U003', 'insurance_officer'),
    ('sess-20260512-004', 'U004', 'medical_record_staff'),
    ('sess-20260512-005', 'U005', 'manager')
ON CONFLICT (session_id) DO NOTHING;

-- --------------------------------------------------------------------------
-- 7.14 工作流实例
-- --------------------------------------------------------------------------
INSERT INTO workflows (workflow_id, scenario, status, current_step, steps, audit_refs, knowledge_events, knowledge_degradation_reasons, session_id, patient_id) VALUES
    ('wf-20260512-001', 'settlement_exception_guidance', 'completed', 'response_rendered',
     '[{"step_id":"step-intent","status":"completed","input_refs":[],"output_refs":["intent-001"],"error":null,"audit_refs":[]},{"step_id":"step-skill-exec","status":"completed","input_refs":["intent-001"],"output_refs":["result-001"],"error":null,"audit_refs":[]}]',
     '["audit-001","audit-002"]', '["ke-001"]', '[]', 'sess-20260512-001', 'P001'),
    ('wf-20260512-002', 'pre_discharge_joint_qc', 'completed', 'response_rendered',
     '[{"step_id":"step-candidate-retrieval","status":"completed","input_refs":[],"output_refs":["candidates-001"],"error":null,"audit_refs":[]},{"step_id":"step-discrimination","status":"completed","input_refs":["candidates-001"],"output_refs":["risks-001"],"error":null,"audit_refs":[]}]',
     '["audit-003","audit-004"]', '["ke-002"]', '[]', 'sess-20260512-001', 'P002'),
    ('wf-20260512-003', 'high_risk_action_confirmation', 'waiting_confirmation', 'waiting_human_confirmation',
     '[{"step_id":"step-risk-detect","status":"completed","input_refs":[],"output_refs":["risk-001"],"error":null,"audit_refs":[]}]',
     '["audit-005"]', '[]', '[]', 'sess-20260512-002', 'P003'),
    ('wf-20260512-004', 'settlement_exception_guidance', 'completed', 'response_rendered',
     '[{"step_id":"step-intent","status":"completed","input_refs":[],"output_refs":["intent-002"],"error":null,"audit_refs":[]},{"step_id":"step-skill-exec","status":"completed","input_refs":["intent-002"],"output_refs":["result-002"],"error":null,"audit_refs":[]}]',
     '["audit-006"]', '["ke-003"]', '["knowledge-timeout"]', 'sess-20260512-003', 'P005')
ON CONFLICT (workflow_id) DO UPDATE SET
    scenario = EXCLUDED.scenario,
    status = EXCLUDED.status,
    steps = EXCLUDED.steps,
    session_id = EXCLUDED.session_id,
    patient_id = EXCLUDED.patient_id;

-- --------------------------------------------------------------------------
-- 7.15 任务数据
-- --------------------------------------------------------------------------
INSERT INTO tasks (task_id, task_type, status, description, responsible_role, workflow_id, executor_type, input_data, output_data, step_id, duration_ms) VALUES
    ('task-20260512-001', 'human_confirmation', 'confirmed',  '确认退费操作：患者P003要求退还未使用药品费用', 'billing_staff',  'wf-20260512-003', 'internal', '{"action":"refund","amount":156.80,"patient_id":"P003"}', '{"confirmed":true,"confirmed_by":"U002"}', 'step-risk-detect', 12500),
    ('task-20260512-002', 'skill_execution',    'completed',  '执行结算异常导办技能：查询患者P001的交易错误码', 'system',         'wf-20260512-001', 'skill',    '{"skill_id":"skill-settlement-guide","patient_id":"P001"}', '{"error_code":"E-UPLOAD-001","recommendation":"补传费用明细"}', 'step-skill-exec', 2300),
    ('task-20260512-003', 'mcp_call',           'completed',  'MCP调用：查询患者P001的结算状态',               'system',         'wf-20260512-001', 'mcp',      '{"capability_id":"cap-query-settlement","params":{"patient_id":"P001"}}', '{"settlement_status":"failed","error_code":"E-UPLOAD-001"}', 'step-skill-exec', 850),
    ('task-20260512-004', 'llm_call',           'completed',  'LLM调用：生成出院前质控建议',                   'system',         'wf-20260512-002', 'llm',      '{"model":"deepseek-v3","prompt":"分析患者P002的质控风险..."}', '{"risks":[{"type":"diagnosis","severity":"medium"}],"recommendation":"..."}', 'step-discrimination', 4200),
    ('task-20260512-005', 'human_confirmation', 'pending',    '确认高危操作：DRG分组修改申请',                 'medical_record_staff', 'wf-20260512-002', 'internal', '{"action":"drg_group_change","patient_id":"P002"}', '{}', 'step-discrimination', NULL)
ON CONFLICT (task_id) DO UPDATE SET
    task_type = EXCLUDED.task_type,
    status = EXCLUDED.status,
    description = EXCLUDED.description,
    workflow_id = EXCLUDED.workflow_id,
    executor_type = EXCLUDED.executor_type,
    input_data = EXCLUDED.input_data,
    output_data = EXCLUDED.output_data;

-- --------------------------------------------------------------------------
-- 7.16 审计日志
-- --------------------------------------------------------------------------
INSERT INTO audit_logs (event_type, user_id, session_id, role, request_path, request_method, request_summary, response_status, response_summary, workflow_id, client_ip, duration_ms) VALUES
    ('api_request',  'U001', 'sess-20260512-001', 'doctor',                 '/api/v1/medical-insurance-ai-agent/chat', 'POST', '{"user_id":"U001","role":"doctor","message":"患者P001结算失败，错误码E-UPLOAD-001","patient_id":"P001"}', 200, '{"scenario":"settlement_exception_guidance","status":"completed"}', 'wf-20260512-001', '192.168.1.101', 2340),
    ('api_response', 'U001', 'sess-20260512-001', 'doctor',                 '/api/v1/medical-insurance-ai-agent/chat', 'POST', NULL, 200, '{"scenario":"settlement_exception_guidance","status":"completed"}', 'wf-20260512-001', '192.168.1.101', 2340),
    ('api_request',  'U001', 'sess-20260512-001', 'doctor',                 '/api/v1/medical-insurance-ai-agent/chat', 'POST', '{"user_id":"U001","role":"doctor","message":"患者P002出院前质控检查","patient_id":"P002"}', 200, '{"scenario":"pre_discharge_joint_qc","status":"completed"}', 'wf-20260512-002', '192.168.1.101', 4500),
    ('api_response', 'U001', 'sess-20260512-001', 'doctor',                 '/api/v1/medical-insurance-ai-agent/chat', 'POST', NULL, 200, '{"scenario":"pre_discharge_joint_qc","status":"completed"}', 'wf-20260512-002', '192.168.1.101', 4500),
    ('api_request',  'U002', 'sess-20260512-002', 'billing_staff',          '/api/v1/medical-insurance-ai-agent/chat', 'POST', '{"user_id":"U002","role":"billing_staff","message":"帮我退费"}', 200, '{"status":"waiting_human_confirmation"}', 'wf-20260512-003', '192.168.1.102', 120),
    ('risk_blocked',  'U002', 'sess-20260512-002', 'billing_staff',         '/api/v1/medical-insurance-ai-agent/chat', 'POST', '{"detected_action":"退费"}', 200, '{"blocked_actions":["退费"]}', 'wf-20260512-003', '192.168.1.102', 120),
    ('config_change', 'U003', 'sess-20260512-003', 'insurance_officer',     '/api/v1/medical-insurance-ai-agent/skills', 'PUT', '{"skill_id":"skill-settlement-guide","enabled":true}', 200, NULL, NULL, '192.168.1.103', 450)
ON CONFLICT DO NOTHING;

-- ============================================================================
-- 初始化完成
-- ============================================================================
-- 执行以下命令验证:
--   psql -U postgres -d hospital_mcp -c "\dt"
--   psql -U postgres -d hospital_mcp -c "SELECT count(*) FROM patients"
-- ============================================================================
