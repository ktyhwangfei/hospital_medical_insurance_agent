/**
 * SettlementExplanationTypes — 结算异常导办中"统筹自付"类问题的结构化解释类型
 *
 * 用于渲染「统筹段计算解释」页面的完整数据模型。
 * 当前版本为 mock 数据，后续接入 real API 时保持接口不变。
 */

/** 结算解释顶层结构 */
export interface SettlementExplanationData {
  question: string
  answer_type: 'benefit_calculation_explanation'
  target_field: string
  target_amount: number
  /** 数据来源: REAL_DB 或 MOCK */
  data_source?: string
  /** 是否使用了 mock */
  mock_used?: boolean
  /** 查询追溯信息 */
  query_trace?: QueryTrace
  case_context: CaseContext
  definition: Definition
  policy_evidence: PolicyEvidenceItem[]
  calculation_trace: CalculationTrace
  patient_answer: string
  office_answer: string
  warnings: string[]
  /** ── 展示驱动字段（可选，向后兼容） ── */
  /** 展示模式 */
  mode?: DisplayMode
  /** 展示配置 */
  display_config?: DisplayConfig
  /** 参保信息值列表 */
  profile?: ProfileValue[]
  /** 输出分组值列表 */
  output_groups?: OutputGroupValue[]
}

/** 数据库查询追溯信息 */
export interface QueryTrace {
  settlement_id: string
  tables: string[]
  sql_profile: string
}

/** 案例上下文（来自结算表的数据快照） */
export interface CaseContext {
  person_type: string
  insurance_type: string
  service_type: string
  hospital_level: string
  deductible: number
  medical_insurance_inner_amount: number
  basic_pooling_payment: number
  basic_pooling_self_pay: number
  large_amount_payment: number
  large_amount_self_pay: number
  personal_total_pay: number
}

/** 名词定义 */
export interface Definition {
  name: string
  plain_text: string
  excludes: string[]
}

/** 政策依据项 */
export interface PolicyEvidenceItem {
  policy_title: string
  clause_text: string
  rule_tags: string[]
  applied_reason: string
}

/** 计算过程追踪 */
export interface CalculationTrace {
  method: string
  steps: CalculationStep[]
}

/** 计算步骤 */
export interface CalculationStep {
  step_name: string
  description: string
}

// ─── 展示配置 ─────────────────────────────────────

/** 展示方式 */
export type DisplayMode = 'single' | 'compare'

/** 金额显示格式 */
export type DisplayFormat = 'money' | 'number' | 'text'

/** 展示配置项 */
export interface DisplayConfig {
  mode: DisplayMode
  profile: ProfileConfig
  output: OutputGroupConfig[]
  collapsible: string[]
}

/** 参保信息配置 */
export interface ProfileConfig {
  title: string
  items: ProfileItemConfig[]
}

/** 参保信息项 */
export interface ProfileItemConfig {
  field: string
  label: string
}

/** 输出分组配置 */
export interface OutputGroupConfig {
  group: string
  items: OutputItemConfig[]
}

/** 输出项配置 */
export interface OutputItemConfig {
  field: string
  label: string
  format?: DisplayFormat
  hint?: string
  highlight?: boolean
}

/** Profile 值（从 API 返回） */
export interface ProfileValue {
  field: string
  label: string
  value: string
}

/** Output 分组值（从 API 返回） */
export interface OutputGroupValue {
  group: string
  items: OutputItemValue[]
}

/** 输出项值（从 API 返回） */
export interface OutputItemValue {
  label: string
  value: number
  format: DisplayFormat
  hint?: string
  highlight?: boolean
}
