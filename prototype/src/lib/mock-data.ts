export type RiskLevel = '高' | '中' | '低'
export type WorkStatus = '待处理' | '处理中' | '已完成'
export type Priority = '高' | '中' | '低'
export type McpCapabilityType = 'Tool' | 'Resource' | 'Prompt' | 'Service'
export type McpTransport = 'stdio' | 'sse' | 'streamable_http'
export type McpServerStatus = 'enabled' | 'disabled' | 'degraded' | 'unhealthy'

export interface SettlementExceptionMock {
  id: string
  patientId: string
  patientName: string
  encounterId: string
  exceptionType: string
  errorCode: string
  errorMsg: string
  detectedAt: string
  status: WorkStatus
  priority: Priority
}

export interface DischargeRiskMock {
  type: string
  level: RiskLevel
  description: string
  source: string
}

export interface DischargeQcMock {
  id: string
  patientId: string
  patientName: string
  encounterId: string
  department: string
  doctor: string
  expectedDischargeDate: string
  risks: DischargeRiskMock[]
  status: WorkStatus
  priority: Priority
}

export interface RoleDefinitionMock {
  id: string
  name: string
  icon: string
  description: string
}

export interface McpServerMock {
  server_id: string
  name: string
  endpoint: string
  transport: McpTransport
  status: McpServerStatus
  protocol_version: string
  auth_headers: Record<string, string>
  metadata: Record<string, string>
}

export interface McpStorageHealthMock {
  status: 'ok' | 'degraded' | 'down'
  backend: 'memory' | 'postgresql' | 'redis'
  details: {
    server_count: number
    capability_count: number
    checked_at: string
  }
}

export interface McpCapabilityMock {
  id: string
  type: McpCapabilityType
  name: string
  count: number
  color: string
}

export interface KnowledgeAssetMock {
  title: string
  value: string
  coverage: number
  color: string
}

export interface RagResultMock {
  source: string
  score: number
  summary: string
}

export interface DrgRuleMock {
  code: string
  title: string
  summary: string
}

export interface PromptTemplateMock {
  name: string
  scenario: string
  role: string
}

export interface ModelTestMockResult {
  content: string
  model_name: string
  latency_ms: number
  prompt_tokens: number
  completion_tokens: number
}

// 模拟数据 - 医保结算异常导办场景
export const settlementExceptions: SettlementExceptionMock[] = [
  {
    id: 'SE001',
    patientId: 'P001',
    patientName: '张三',
    encounterId: 'E001',
    exceptionType: '医保结算失败',
    errorCode: 'ERR_001',
    errorMsg: '患者待遇资格校验不通过',
    detectedAt: '2026-05-06 09:30:00',
    status: '待处理',
    priority: '高',
  },
  {
    id: 'SE002',
    patientId: 'P002',
    patientName: '李四',
    encounterId: 'E002',
    exceptionType: '费用上传异常',
    errorCode: 'ERR_002',
    errorMsg: '诊疗项目目录对码错误',
    detectedAt: '2026-05-06 10:15:00',
    status: '处理中',
    priority: '中',
  },
  {
    id: 'SE003',
    patientId: 'P003',
    patientName: '王五',
    encounterId: 'E003',
    exceptionType: '预结算金额异常',
    errorCode: 'ERR_003',
    errorMsg: 'DRG分组结果与费用不匹配',
    detectedAt: '2026-05-06 11:00:00',
    status: '待处理',
    priority: '高',
  },
]

// 模拟数据 - 出院前联合质控场景
export const dischargeQCList: DischargeQcMock[] = [
  {
    id: 'QC001',
    patientId: 'P001',
    patientName: '张三',
    encounterId: 'E001',
    department: '骨科',
    doctor: '张医生',
    expectedDischargeDate: '2026-05-07',
    risks: [
      {
        type: '结算准备',
        level: '高',
        description: '费用未完全上传',
        source: '首信医保接口',
      },
      {
        type: '合规风险',
        level: '中',
        description: '高值耗材使用未说明理由',
        source: '东软事前审核',
      },
      {
        type: 'DRG风险',
        level: '高',
        description: '主要诊断与手术操作不匹配，可能影响入组',
        source: '大瑞集思DRG',
      },
      {
        type: '病案质量',
        level: '中',
        description: '住院天数填写异常',
        source: '医保数据中台',
      },
    ],
    status: '待处理',
    priority: '高',
  },
  {
    id: 'QC002',
    patientId: 'P004',
    patientName: '赵六',
    encounterId: 'E004',
    department: '心内科',
    doctor: '李医生',
    expectedDischargeDate: '2026-05-08',
    risks: [
      {
        type: '合规风险',
        level: '高',
        description: '药品适应症不符合医保限制',
        source: '东软事前审核',
      },
      {
        type: '费用结构',
        level: '中',
        description: '检查费用占比过高',
        source: '医保数据中台',
      },
    ],
    status: '处理中',
    priority: '中',
  },
]

// 错误码知识库
export const errorCodeKnowledge = {
  ERR_001: {
    code: 'ERR_001',
    description: '患者待遇资格校验不通过',
    possibleCauses: [
      '患者医保卡未激活',
      '患者欠费停机',
      '患者待遇享受期已过期',
      '患者参保状态异常',
    ],
    handlingSteps: [
      '核实患者医保卡状态',
      '检查患者是否欠费',
      '确认患者参保状态',
      '联系医保办处理待遇恢复',
    ],
    responsibleRole: '收费员',
    estimatedTime: '15分钟',
  },
  ERR_002: {
    code: 'ERR_002',
    description: '诊疗项目目录对码错误',
    possibleCauses: [
      'HIS项目编码与医保目录不匹配',
      '新项目未维护医保对码关系',
      '医保目录版本更新未同步',
    ],
    handlingSteps: [
      '查询HIS项目医保对码关系',
      '更新医保目录对照表',
      '重新上传费用',
      '验证对码正确性',
    ],
    responsibleRole: '信息科',
    estimatedTime: '30分钟',
  },
  ERR_003: {
    code: 'ERR_003',
    description: 'DRG分组结果与费用不匹配',
    possibleCauses: [
      '主要诊断选择错误',
      '手术操作编码不完整',
      '病案首页填写错误',
    ],
    handlingSteps: [
      '检查病案首页主要诊断',
      '核实手术操作编码',
      '重新进行DRG预分组',
      '必要时修改病案首页',
    ],
    responsibleRole: '病案室',
    estimatedTime: '45分钟',
  },
}

// 角色定义
export const roles: RoleDefinitionMock[] = [
  {
    id: 'cashier',
    name: '收费员',
    icon: '💰',
    description: '负责医保结算、费用上传、交易查询',
  },
  {
    id: 'insurance_office',
    name: '医保办',
    icon: '🏥',
    description: '负责医保政策解释、拒付处理、科室协调',
  },
  {
    id: 'it_department',
    name: '信息科',
    icon: '💻',
    description: '负责系统接口、数据问题排查、技术支撑',
  },
  {
    id: 'medical_record',
    name: '病案室',
    icon: '📋',
    description: '负责病案首页质量、编码审核、DRG入组',
  },
]

// AI对话模拟回复
export const mockAIChatResponses: Record<string, string[]> = {
  '为什么这个患者结算失败': [
    '我查询到患者张三(P001)的结算失败原因：',
    '',
    '**错误码**: ERR_001',
    '**错误信息**: 患者待遇资格校验不通过',
    '',
    '**可能原因**:',
    '1. 患者医保卡未激活',
    '2. 患者欠费停机',
    '3. 患者待遇享受期已过期',
    '',
    '**建议处理步骤**:',
    '1. 核实患者医保卡状态',
    '2. 检查患者是否欠费',
    '3. 联系医保办处理待遇恢复',
    '',
    '需要我帮您生成处理任务吗？',
  ],
  '这个患者出院前还有哪些风险': [
    '我已完成患者张三(E001)的出院前联合质控，发现以下风险：',
    '',
    '**🔴 高风险 (2项)**',
    '- 费用未完全上传 (首信)',
    '- 主要诊断与手术操作不匹配 (DRG)',
    '',
    '**🟡 中风险 (2项)**',
    '- 高值耗材使用未说明理由 (东软)',
    '- 住院天数填写异常 (数据中台)',
    '',
    '已生成联合质控清单，责任角色：收费员、病案室',
    '',
    '需要我帮您分派处理任务吗？',
  ],
  '本月哪个科室DRG亏损最多': [
    '根据本月数据分析，DRG亏损排名前三的科室：',
    '',
    '1. **骨科** - 亏损58万元',
    '   - 主要问题：高值耗材使用过多',
    '   - 涉及病组：BM21(髋膝关节置换)',
    '',
    '2. **心内科** - 亏损42万元',
    '   - 主要问题：检查费用占比过高',
    '   - 涉及病组：CV1(心血管介入)',
    '',
    '3. **神经内科** - 亏损35万元',
    '   - 主要问题：住院天数过长',
    '   - 涉及病组：CV3(脑血管病)',
    '',
    '需要我生成科室整改建议吗？',
  ],
}

export type Role = (typeof roles)[0]
export type SettlementException = (typeof settlementExceptions)[0]
export type DischargeQC = (typeof dischargeQCList)[0]
export type ErrorCodeKnowledge = typeof errorCodeKnowledge

export const mockMcpServers: McpServerMock[] = [
  {
    server_id: 'mcp-knowledge-search',
    name: '知识检索 MCP 服务',
    endpoint: 'http://127.0.0.1:9101/sse',
    transport: 'sse',
    status: 'enabled',
    protocol_version: '2025-03-26',
    auth_headers: {},
    metadata: { owner: '医保办', scene: 'knowledge_search' },
  },
  {
    server_id: 'mcp-policy-rules',
    name: '政策规则 MCP 服务',
    endpoint: 'http://127.0.0.1:9102/mcp',
    transport: 'streamable_http',
    status: 'degraded',
    protocol_version: '2025-03-26',
    auth_headers: {},
    metadata: { owner: '信息科', scene: 'policy_rule' },
  },
]

export const mockMcpStorageHealth: McpStorageHealthMock = {
  status: 'ok',
  backend: 'memory',
  details: {
    server_count: 2,
    capability_count: 8,
    checked_at: '2026-05-06T13:00:00+08:00',
  },
}

export const mockMcpCapabilities: McpCapabilityMock[] = [
  { id: 'tool-search-policy', type: 'Tool', name: '政策检索工具', count: 3, color: 'text-blue-600' },
  { id: 'resource-error-codes', type: 'Resource', name: '错误码资源', count: 2, color: 'text-green-600' },
  { id: 'prompt-qc-guide', type: 'Prompt', name: '质控导办提示', count: 2, color: 'text-purple-600' },
  { id: 'service-risk-score', type: 'Service', name: '风险评分服务', count: 1, color: 'text-orange-600' },
]

export const mockKnowledgeAssets: KnowledgeAssetMock[] = [
  { title: '错误码知识库', value: '128条', coverage: 92, color: 'text-blue-600' },
  { title: '政策规则库', value: '56条', coverage: 81, color: 'text-green-600' },
  { title: 'DRG/DIP知识库', value: '34条', coverage: 74, color: 'text-purple-600' },
  { title: '提示模板库', value: '18个', coverage: 88, color: 'text-orange-600' },
]

export const mockRagResults: RagResultMock[] = [
  { source: '医保政策规则库', score: 0.91, summary: '待遇资格校验失败时，应先核验参保状态、待遇享受期和账户状态。' },
  { source: '错误码知识库 ERR_001', score: 0.86, summary: 'ERR_001 表示患者待遇资格校验不通过，常见原因为医保卡未激活或待遇过期。' },
  { source: '结算异常处置流程', score: 0.78, summary: '收费员确认患者信息后，由医保办协助恢复待遇资格或指导患者补缴。' },
]

export const mockDrgRules: DrgRuleMock[] = [
  { code: 'DRG-BM21', title: '髋膝关节置换病组', summary: '关注主要诊断、手术操作编码和高值耗材说明完整性。' },
  { code: 'DIP-CV1', title: '心血管介入病种', summary: '关注检查费用占比、耗材适应症和住院天数合理性。' },
]

export const mockPromptTemplates: PromptTemplateMock[] = [
  { name: '结算异常导办模板', scenario: 'settlement_exception_guidance', role: '收费员' },
  { name: '出院前质控模板', scenario: 'pre_discharge_quality_control', role: '病案室' },
  { name: '政策解释模板', scenario: 'policy_explanation', role: '医保办' },
]

export const mockModelTestResult: ModelTestMockResult = {
  content: '这是离线模式下的模型测试结果。后端模型服务不可用时，前端会保留演示体验。',
  model_name: 'mock-model',
  latency_ms: 120,
  prompt_tokens: 32,
  completion_tokens: 48,
}
