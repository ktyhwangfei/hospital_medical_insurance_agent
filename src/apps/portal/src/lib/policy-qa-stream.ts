/** Policy QA SSE 的公开、安全前端契约与纯数据转换。 */

export interface PolicyQACaseContext {
  personType?: string | null
  insuranceType?: string | null
  serviceType?: string | null
  hospitalLevel?: string | null
  deductible?: number | null
  yearlyCycleCount?: number | null
  basicPoolingPayment?: number | null
  basicPoolingSelfPay?: number | null
  largeAmountPayment?: number | null
  largeAmountSelfPay?: number | null
  personalTotalPay?: number | null
  totalAmount?: number | null
  queryScope?: 'whole_admission' | 'segment' | null
  segmentCount?: number | null
  matchedSegmentCount?: number | null
  coverageStatus?: 'complete' | 'partial' | 'unavailable' | null
  stayStartDate?: string | null
  stayEndDate?: string | null
}

export interface PolicyQAVerificationSummary {
  settlementChecked: boolean
  calculationChecked: boolean
  policyCount: number
  message: string
}

export interface PolicyQASettlementField {
  fieldName: string
  value: number | null
  state: 'non_zero' | 'reported_zero' | 'missing' | 'not_applicable'
}

export interface PolicyQADataQueryResult {
  metricId: string
  metricName: string
  chart?: {
    type: 'line' | 'bar' | 'pie' | 'table'
    xAxis?: string[]
    series: Array<{ name: string; data: (number | string)[] }>
  }
  table?: {
    columns: Array<{ key: string; title: string }>
    rows: Array<Record<string, string | number | null>>
  }
  summary: string
  caliber?: string
}

/** 字段四要素固定说明（解释投影 1.10；服务端确定性生成，缺项在 boundary 显式声明）。 */
export interface PolicyQAFieldExplanation {
  /** 金额含义：这笔钱代表什么，属费用/基金支付/个人负担/支付方式口径。 */
  meaning: string | null
  /** 金额构成：由哪些金额相加/相减/按比例得出；无计算记录时为诚实口径。 */
  composition: string | null
  /** 本单依据：采用的比例/限价/待遇档与来源标题。 */
  basisText: string | null
  /** 解释边界：三态零金额、结论分级、缺口与四要素缺项声明。 */
  boundary: string | null
}

/** 费用分解单字段公开视图（对齐后端 DecompositionFieldView；金额为十进制字符串，原样展示）。 */
export interface PolicyQAFeeDecompositionField {
  explainable?: boolean
  explanationReason?: string | null
  fieldCode: string
  label: string
  checkType: 'independent_recalculation' | 'detail_aggregation' | 'identity_check'
  checkStatus: 'matched' | 'mismatched' | 'not_verifiable' | 'not_applicable'
  observedAmount: string | null
  calculatedAmount: string | null
  difference: string | null
  explanationLevel: 'causally_explained' | 'amount_reconciled' | 'observed_only' | 'unexplained'
  /** 解释投影 1.1：reason 原样状态码；1.0 旧载荷为 null。 */
  reasonCode: string | null
  /** 指向 calculations.calculationId。 */
  calculationRefs: string[]
  /** 指向 sources.refId。 */
  sourceRefs: string[]
  /** 指向 uncertainties.id。 */
  gapRefs: string[]
  /** 后端确定性 1-2 句构成说明。 */
  brief: string | null
  /** 解释投影 1.10：字段四要素固定说明；1.9 及更早载荷为 null。 */
  explanation?: PolicyQAFieldExplanation | null
}

export interface PolicyQAFeeDecompositionUncertainty {
  code: string
  message: string
  /** 解释投影 1.1：精确关联 ID（gap_refs 指向它）；1.0 旧载荷为空串。 */
  id: string
  affectedFields: string[]
}

/** 计算操作数公开视图（value 为有符号十进制字符串，负号表减项）。 */
export interface PolicyQAFeeDecompositionOperand {
  displayName: string
  value: string
  isIntermediate: boolean
  inputRef?: string | null
  calculationRef?: string | null
}

/** 单条计算记录公开视图（解释投影 1.1）。 */
export interface PolicyQAFeeDecompositionCalculation {
  explainable?: boolean
  calculationId: string
  formula?: string | null
  displayName: string
  formulaId: string
  formulaVersion: string
  layout: 'sum' | 'subtract_rest' | 'product' | 'generic'
  operands: PolicyQAFeeDecompositionOperand[]
  unroundedResult: string | null
  roundingRule: string | null
  result: string | null
  verificationStatus?: FormulaInputStatus
  verificationReason?: string | null
}

export type FormulaInputStatus = 'verified' | 'unverified' | 'missing' | 'conflict'
export interface PolicyQAFormulaInput {
  inputId: string
  name: string
  value: string | null
  status: FormulaInputStatus
  source: string
  reason: string | null
  calculationRef: string | null
  ruleGroupRef: string | null
  ruleId?: string | null
}
export interface PolicyQARuleChoice {
  groupId: string
  title: string
  calculationRefs: string[]
  inputRefs: string[]
  fieldRefs: string[]
  candidates: Array<{
    ruleId: string; name: string; value: string | null; unit: string; version: string
    effectiveFrom: string | null; effectiveTo: string | null; source: string; confirmationStatus: string
    status: 'selected' | 'eligible' | 'excluded' | 'unknown' | 'conflict'; reason: string
    checks: Array<{ name: string; actual: string | null; expected: string; outcome: 'met' | 'unmet' | 'unknown'; inputRef: string | null }>
  }>
}

/** 来源公开视图（解释投影 1.1）。 */
export interface PolicyQAFeeDecompositionSource {
  refId: string
  title: string
  category: 'settlement_record' | 'policy_basis'
  confirmationStatus: string | null
  value: string | null
  values: string[]
  link: string | null
}

/** 采用条件公开视图（解释投影 1.1）。 */
export interface PolicyQAFeeDecompositionCondition {
  stepId: string
  moduleLabel: string
  description: string
  actualDisplay: string | null
  expectedDisplay: string | null
  outcome: string
  calculationRefs: string[]
}

export interface PolicyQAFeeDecompositionCoverage {
  targetFieldCount: number
  independentlyExplainedCount: number
  amountReconciledCount: number
  observedOnlyCount: number
}

export interface SettlementTemplateField {
  key: string
  label: string
  semanticLabel: string | null
  fieldCode: string | null
  section: 'basic' | 'transaction' | 'hospital'
  row: number
  column: number
  span: number
  scope: 'metadata' | 'patient_actual' | 'patient_book' | 'hospital_quota'
  value: string | null
  sourceKind: 'record' | 'derived' | 'unmapped' | 'context'
  status: 'available' | 'missing' | 'unmapped'
  contextKey: string | null
  note: string | null
}

export interface SettlementDisplayTemplate {
  templateId: string
  version: string
  title: string
  layoutStatus: 'image_verified' | 'provisional'
  fields: SettlementTemplateField[]
}

export interface PolicyQASettlementFacts {
  chain: 'outpatient' | 'special'
  identifier: string | null
  tradeDate: string | null
  medicalCategory: string | null
  insuranceType: string | null
  personType: string | null
  hospitalLevel: string | null
  metadataNames?: Record<string, string>
  retireOfficerFlag?: string | null
  items: Array<{ label: string; value: string | null }>
  paymentItems: Array<{ label: string; value: string | null }>
  displayTemplate?: SettlementDisplayTemplate
}

export interface PolicyQASettlementPathStep {
  stepId: string
  name: string
  status: 'applied' | 'zero_amount' | 'not_applicable' | 'unknown' | 'observed_only'
  amount: string | null
  calculationRefs: string[]
  fieldRefs: string[]
  reason: string | null
  conditionRefs?: string[]
}

export interface PolicyQAFeeItem {
  /** 仅保留原始资料供查证；当前不新增患者展示块。 */
  paymentConditionContext?: import('./fee-decomposition-api').PaymentConditionContextDto
  explainable?: boolean
  explanationReason?: string | null
  classificationCode?: string | null
  classificationLabel?: string | null
  classificationSource?: string | null
  centralizedProcurement?: boolean | null
  catalogEntryId?: string | null
  effectiveFrom?: string | null
  effectiveTo?: string | null
  ratioSource?: string | null
  ratioBasis?: string | null
  limitSource?: string | null
  decisionPath?: Array<{ code: string; label: string; operator: string; actual: string | null; expected: string | null; outcome: string; ruleRefs: string[]; calculationRefs: string[] }>
  calculationRefs?: string[]
  reconciliations?: Array<{ label: string; observed: string | null; calculated: string | null; difference: string | null; checkStatus: string }>
  lineId: string
  itemCode: string
  itemName: string
  itemType: string | null
  feeDate: string | null
  unitPrice: string | null
  quantity: string | null
  totalFee: string | null
  observedInScope: string | null
  observedOutScope: string | null
  observedSelfPay2: string | null
  calculatedInScope: string | null
  calculatedOutScope: string | null
  calculatedSelfPay2: string | null
  calculatedProportionalSelfPay?: string | null
  status: 'calculated' | 'observed_only' | 'unknown'
  verificationStatus?: 'verified' | 'unverified'
  divisionMethod?: 'ratio' | 'limit' | 'full_in' | 'full_out' | 'settlement_override' | 'unknown'
  selfPayRatio?: string | null
  includedRatio?: string | null
  unitPriceLimit?: string | null
  /** 解释投影 1.6：逐行目录事实（缺失键不存在；原值透传）。 */
  aYpbs?: string | null
  aMzxj?: string | null
  aZyxj?: string | null
  aXbbl?: string | null
  ypfl?: string | null
  bzjg?: string | null
  settlementPriceLimit?: string | null
  /** 解释投影 1.6：本行中文解释（逐字取自已执行公式与来源说明）。 */
  explanation?: string | null
  conditions: string[]
  formulas: string[]
  notes: string[]
}

/** 费用分解公开结果（对齐后端 FeeDecompositionPublic）。 */
export interface PolicyQAFeeDecomposition {
  schemaVersion: string
  algorithmVersion: string
  executionStatus: 'complete' | 'partial' | 'unavailable'
  reconciliationStatus: string
  summaryText: string
  summarySource: 'template' | 'model'
  mayClaimFullExplanation: boolean
  formulaInputs?: PolicyQAFormulaInput[]
  ruleChoices?: PolicyQARuleChoice[]
  fields: PolicyQAFeeDecompositionField[]
  uncertainties: PolicyQAFeeDecompositionUncertainty[]
  coverage?: PolicyQAFeeDecompositionCoverage
  /** 解释投影 1.1 新增顶层数组；1.0 旧载荷无此键，解析为空数组。 */
  calculations: PolicyQAFeeDecompositionCalculation[]
  sources: PolicyQAFeeDecompositionSource[]
  conditions: PolicyQAFeeDecompositionCondition[]
  settlementFacts?: PolicyQASettlementFacts
  pathSteps?: PolicyQASettlementPathStep[]
  feeItems?: PolicyQAFeeItem[]
  /** 解释投影 1.10：模板展示字段四要素固定说明，按模板 key 索引。 */
  templateExplanations?: Record<string, PolicyQAFieldExplanation>
}

export interface PolicyQAResult {
  answer: string
  answerStatus: 'complete' | 'partial' | 'unavailable'
  caseContext?: PolicyQACaseContext
  calculationSteps: Array<{ stepName: string; description: string }>
  definition?: { name: string; plainText: string; excludes: string[] }
  warnings: string[]
  citations: Array<{ title: string; excerpt: string; docId?: string; sourceExcerpt?: string }>
  uncertainties: string[]
  verificationSummary: PolicyQAVerificationSummary
  scenarioId?: string
  settlementFields: PolicyQASettlementField[]
  isBroad?: boolean
  dataQueryResult?: PolicyQADataQueryResult
  feeDecomposition?: PolicyQAFeeDecomposition
}

/** 只有明确的旧版载荷保留旧展示；新版本缺模板时不回退猜测字段。 */
export function requiresSettlementTemplate(data: PolicyQAFeeDecomposition): boolean {
  return !['1.0', '1.1', '1.2', '1.3', '1.4', '1.5', '1.6', '1.7'].includes(data.schemaVersion)
}

export interface PolicyQASseEvent {
  event: string
  data: unknown
}

const FORBIDDEN_PUBLIC_KEYS = new Set([
  'patient_view',
  'office_view',
  'settlement_evidence',
  'query_trace',
  'trace_events',
  'reasoning_steps',
  'sql_profile',
  'tables',
  'run_id',
  'selected_skill_id',
  'answer_mode',
])

/** 在任何事件进入状态前递归移除后端内部字段。 */
export function sanitizePublicPayload(payload: unknown): unknown {
  if (Array.isArray(payload)) return payload.map(sanitizePublicPayload)
  if (!isRecord(payload)) return payload

  const safe: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(payload)) {
    if (!FORBIDDEN_PUBLIC_KEYS.has(key)) safe[key] = sanitizePublicPayload(value)
  }
  return safe
}

/** 解析一个已经缓冲完整的 SSE frame；多条 data 行按 SSE 规范以换行连接。 */
export function parseSseBlock(block: string): PolicyQASseEvent | null {
  const lines = block.replace(/\r\n/g, '\n').split('\n')
  let event = ''
  const dataLines: string[] = []
  for (const line of lines) {
    if (!line || line.startsWith(':')) continue
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trimStart())
    }
  }
  if (!event || dataLines.length === 0) return null
  const raw = dataLines.join('\n').trim()
  if (!raw) return { event, data: {} }
  try {
    return { event, data: JSON.parse(raw) as unknown }
  } catch {
    return null
  }
}

const UNAVAILABLE_ANSWER =
  '当前无法基于已公开的核验结果给出准确、可靠的费用解释。建议携带医保结算单前往医院医保办咨询，或拨打当地医保局服务热线咨询。\n\n本回答仅供参考，不作为报销或结算依据。'

/** 将 result 的 snake_case 公开契约转换为组件只读的 camelCase 类型。 */
export function toPolicyQAResult(raw: unknown): PolicyQAResult {
  if (!isRecord(raw)) return unavailableResult()

  const answer = typeof raw.answer === 'string' ? raw.answer.trim() : ''
  const answerStatus = raw.answer_status
  const verification = raw.verification_summary
  const citations = toCitations(raw.citations)
  const uncertainties = strictStringArray(raw.uncertainties)
  if (
    !answer ||
    !isAnswerStatus(answerStatus) ||
    !isRecord(verification) ||
    typeof verification.settlement_checked !== 'boolean' ||
    typeof verification.calculation_checked !== 'boolean' ||
    typeof verification.policy_count !== 'number' ||
    !Number.isInteger(verification.policy_count) ||
    verification.policy_count < 0 ||
    typeof verification.message !== 'string' ||
    citations === undefined ||
    uncertainties === undefined ||
    (citations.length === 0 && uncertainties.length === 0) ||
    (answerStatus === 'complete' &&
      !verification.settlement_checked &&
      !verification.calculation_checked &&
      verification.policy_count === 0)
  ) {
    return unavailableResult()
  }

  return {
    answer,
    answerStatus,
    caseContext: toCaseContext(raw.case_context),
    calculationSteps: toCalculationSteps(raw.calculation_steps),
    definition: toDefinition(raw.definition),
    warnings: stringArray(raw.warnings),
    citations,
    uncertainties,
    verificationSummary: {
      settlementChecked: verification.settlement_checked,
      calculationChecked: verification.calculation_checked,
      policyCount: verification.policy_count,
      message: verification.message,
    },
    scenarioId: typeof raw.scenario_id === 'string' ? raw.scenario_id : undefined,
    settlementFields: toSettlementFields(raw.field_explanations),
    isBroad: raw.is_broad === true,
    dataQueryResult: toDataQueryResult(raw.data_query_result),
    feeDecomposition: toFeeDecomposition(raw.fee_decomposition),
  }
}

function unavailableResult(): PolicyQAResult {
  return {
    answer: UNAVAILABLE_ANSWER,
    answerStatus: 'unavailable',
    calculationSteps: [],
    warnings: [],
    citations: [],
    uncertainties: ['返回结果未通过公开契约校验。'],
    verificationSummary: {
      settlementChecked: false,
      calculationChecked: false,
      policyCount: 0,
      message: '公开结果不完整，未展示未经核验的内容。',
    },
    settlementFields: [],
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isAnswerStatus(value: unknown): value is PolicyQAResult['answerStatus'] {
  return value === 'complete' || value === 'partial' || value === 'unavailable'
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function strictStringArray(value: unknown): string[] | undefined {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
    ? value
    : undefined
}

function nullableString(value: unknown): string | null | undefined {
  return value === null || typeof value === 'string' ? value : undefined
}

function nullableNumber(value: unknown): number | null | undefined {
  return value === null || (typeof value === 'number' && Number.isFinite(value)) ? value : undefined
}

function toCaseContext(value: unknown): PolicyQACaseContext | undefined {
  if (!isRecord(value)) return undefined
  return {
    personType: nullableString(value.person_type),
    insuranceType: nullableString(value.insurance_type),
    serviceType: nullableString(value.service_type),
    hospitalLevel: nullableString(value.hospital_level),
    deductible: nullableNumber(value.deductible),
    yearlyCycleCount: nullableNumber(value.yearly_cycle_count),
    basicPoolingPayment: nullableNumber(value.basic_pooling_payment),
    basicPoolingSelfPay: nullableNumber(value.basic_pooling_self_pay),
    largeAmountPayment: nullableNumber(value.large_amount_payment),
    largeAmountSelfPay: nullableNumber(value.large_amount_self_pay),
    personalTotalPay: nullableNumber(value.personal_total_pay),
    totalAmount: nullableNumber(value.total_amount),
    queryScope:
      value.query_scope === 'whole_admission' || value.query_scope === 'segment'
        ? value.query_scope
        : value.query_scope === null
          ? null
          : undefined,
    segmentCount: nullableNumber(value.segment_count),
    matchedSegmentCount: nullableNumber(value.matched_segment_count),
    coverageStatus:
      value.coverage_status === 'complete' ||
      value.coverage_status === 'partial' ||
      value.coverage_status === 'unavailable'
        ? value.coverage_status
        : value.coverage_status === null
          ? null
          : undefined,
    stayStartDate: nullableString(value.stay_start_date),
    stayEndDate: nullableString(value.stay_end_date),
  }
}

function toCalculationSteps(value: unknown): PolicyQAResult['calculationSteps'] {
  if (!Array.isArray(value)) return []
  return value.filter(isRecord).map((step) => ({
    stepName: typeof step.step_name === 'string' ? step.step_name : '',
    description: typeof step.description === 'string' ? step.description : '',
  }))
}

function toSettlementFields(value: unknown): PolicyQASettlementField[] {
  if (!Array.isArray(value)) return []
  return value.filter(isRecord).flatMap((item) => {
    const state = item.state
    if (
      typeof item.field_name !== 'string' ||
      (state !== 'non_zero' &&
        state !== 'reported_zero' &&
        state !== 'missing' &&
        state !== 'not_applicable')
    ) {
      return []
    }
    const amount = nullableNumber(item.value)
    if (amount === undefined) return []
    return [{ fieldName: item.field_name, value: amount ?? null, state }]
  })
}

function toDefinition(value: unknown): PolicyQAResult['definition'] {
  if (!isRecord(value)) return undefined
  return {
    name: typeof value.name === 'string' ? value.name : '',
    plainText: typeof value.plain_text === 'string' ? value.plain_text : '',
    excludes: stringArray(value.excludes),
  }
}

function toDataQueryResult(value: unknown): PolicyQADataQueryResult | undefined {
  if (!isRecord(value)) return undefined
  const metricId = typeof value.metric_id === 'string' ? value.metric_id : ''
  const metricName = typeof value.metric_name === 'string' ? value.metric_name : ''
  if (!metricId || !metricName) return undefined
  return {
    metricId,
    metricName,
    chart: toDataQueryChart(value.chart),
    table: toDataQueryTable(value.table),
    summary: typeof value.summary === 'string' ? value.summary : '',
    caliber: typeof value.caliber === 'string' ? value.caliber : undefined,
  }
}

function toDataQueryChart(value: unknown): PolicyQADataQueryResult['chart'] | undefined {
  if (!isRecord(value)) return undefined
  const type = value.type
  if (type !== 'line' && type !== 'bar' && type !== 'pie' && type !== 'table') return undefined
  const xAxis = Array.isArray(value.x_axis)
    ? value.x_axis.filter((item): item is string => typeof item === 'string')
    : undefined
  const series = Array.isArray(value.series)
    ? value.series.filter(isRecord).map((s) => ({
        name: typeof s.name === 'string' ? s.name : '',
        data: Array.isArray(s.data)
          ? s.data.filter((v): v is number | string => typeof v === 'number' || typeof v === 'string')
          : [],
      }))
    : []
  return { type, xAxis, series }
}

function toDataQueryTable(value: unknown): PolicyQADataQueryResult['table'] | undefined {
  if (!isRecord(value)) return undefined
  const columns = Array.isArray(value.columns)
    ? value.columns.filter(isRecord).map((col) => ({
        key: typeof col.key === 'string' ? col.key : '',
        title: typeof col.title === 'string' ? col.title : '',
      }))
    : []
  const rows = Array.isArray(value.rows)
    ? value.rows.filter(isRecord).map((row) => {
        const safe: Record<string, string | number | null> = {}
        for (const [k, v] of Object.entries(row)) {
          if (typeof v === 'string' || typeof v === 'number' || v === null) safe[k] = v
        }
        return safe
      })
    : []
  if (columns.length === 0 || rows.length === 0) return undefined
  return { columns, rows }
}

function toCitations(value: unknown): PolicyQAResult['citations'] | undefined {
  if (
    !Array.isArray(value) ||
    !value.every(
      (citation) =>
        isRecord(citation) &&
        typeof citation.title === 'string' &&
        typeof citation.excerpt === 'string',
    )
  ) {
    return undefined
  }
  return value.map((citation) => ({
    title: citation.title as string,
    excerpt: citation.excerpt as string,
    docId:
      typeof citation.doc_id === 'string'
        ? (citation.doc_id as string)
        : undefined,
    sourceExcerpt:
      typeof citation.source_excerpt === 'string'
        ? (citation.source_excerpt as string)
        : undefined,
  }))
}

// ── 费用分解公开结果（Issue #78）──────────────────────────────────
// 稀疏容忍：字段逐项缺省不抛错；金额为十进制字符串原样透传（禁止数值化）。

const FEE_CHECK_TYPES = new Set<PolicyQAFeeDecompositionField['checkType']>([
  'independent_recalculation',
  'detail_aggregation',
  'identity_check',
])

const FEE_CHECK_STATUSES = new Set<PolicyQAFeeDecompositionField['checkStatus']>([
  'matched',
  'mismatched',
  'not_verifiable',
  'not_applicable',
])

const FEE_EXPLANATION_LEVELS = new Set<PolicyQAFeeDecompositionField['explanationLevel']>([
  'causally_explained',
  'amount_reconciled',
  'observed_only',
  'unexplained',
])

const FEE_CALC_LAYOUTS = new Set<PolicyQAFeeDecompositionCalculation['layout']>([
  'sum',
  'subtract_rest',
  'product',
  'generic',
])

function toFieldExplanation(value: unknown): PolicyQAFieldExplanation | null {
  if (!isRecord(value)) return null
  return {
    meaning: nullableString(value.meaning) ?? null,
    composition: nullableString(value.composition) ?? null,
    basisText: nullableString(value.basis_text) ?? null,
    boundary: nullableString(value.boundary) ?? null,
  }
}

function toTemplateExplanations(value: unknown): Record<string, PolicyQAFieldExplanation> | undefined {
  if (!isRecord(value)) return undefined
  const entries = Object.entries(value).flatMap(([key, item]) => {
    const explanation = toFieldExplanation(item)
    return explanation ? [[key, explanation] as const] : []
  })
  return Object.fromEntries(entries)
}

function toFeeDecompositionFields(value: unknown): PolicyQAFeeDecompositionField[] {
  if (!Array.isArray(value)) return []
  return value.filter(isRecord).map((item) => ({
    explainable: item.explainable === true,
    explanationReason: nullableString(item.explanation_reason) ?? null,
    fieldCode: typeof item.field_code === 'string' ? item.field_code : '',
    label: typeof item.label === 'string' ? item.label : '',
    checkType: FEE_CHECK_TYPES.has(item.check_type as PolicyQAFeeDecompositionField['checkType'])
      ? (item.check_type as PolicyQAFeeDecompositionField['checkType'])
      : 'identity_check',
    checkStatus: FEE_CHECK_STATUSES.has(
      item.check_status as PolicyQAFeeDecompositionField['checkStatus'],
    )
      ? (item.check_status as PolicyQAFeeDecompositionField['checkStatus'])
      : 'not_verifiable',
    observedAmount: nullableString(item.observed_amount) ?? null,
    calculatedAmount: nullableString(item.calculated_amount) ?? null,
    difference: nullableString(item.difference) ?? null,
    explanationLevel: FEE_EXPLANATION_LEVELS.has(
      item.explanation_level as PolicyQAFeeDecompositionField['explanationLevel'],
    )
      ? (item.explanation_level as PolicyQAFeeDecompositionField['explanationLevel'])
      : 'unexplained',
    reasonCode: nullableString(item.reason_code) ?? null,
    calculationRefs: stringArray(item.calculation_refs),
    sourceRefs: stringArray(item.source_refs),
    gapRefs: stringArray(item.gap_refs),
    brief: nullableString(item.brief) ?? null,
    explanation: toFieldExplanation(item.explanation),
  }))
}

function toFeeDecompositionUncertainties(
  value: unknown,
): PolicyQAFeeDecompositionUncertainty[] {
  if (!Array.isArray(value)) return []
  return value.filter(isRecord).map((item) => ({
    code: typeof item.code === 'string' ? item.code : '',
    message: typeof item.message === 'string' ? item.message : '',
    id: typeof item.id === 'string' ? item.id : '',
    affectedFields: stringArray(item.affected_fields),
  }))
}

function toFormulaInputStatus(value: unknown): FormulaInputStatus {
  return value === 'verified' || value === 'missing' || value === 'conflict' ? value : 'unverified'
}

function toFormulaInputs(value: unknown): PolicyQAFormulaInput[] {
  if (!Array.isArray(value)) return []
  return value.filter(isRecord).filter((item) => typeof item.input_id === 'string').map((item) => ({
    inputId: item.input_id as string, name: typeof item.name === 'string' ? item.name : '输入依据',
    value: nullableString(item.value) ?? null, status: typeof item.value === 'string' && typeof item.source === 'string' ? toFormulaInputStatus(item.status) : 'missing',
    source: typeof item.source === 'string' ? item.source : '来源未取得', reason: nullableString(item.reason) ?? null,
    calculationRef: nullableString(item.calculation_ref) ?? null, ruleGroupRef: nullableString(item.rule_group_ref) ?? null,
      ...(typeof item.rule_id === 'string' ? { ruleId: item.rule_id } : {}),
  }))
}

function toRuleChoices(value: unknown): PolicyQARuleChoice[] {
  if (!Array.isArray(value)) return []
  const str = (value: unknown) => typeof value === 'string' ? value : ''
  return value.filter(isRecord).filter((item) => typeof item.group_id === 'string').map((item) => ({
    groupId: str(item.group_id), title: str(item.title), calculationRefs: stringArray(item.calculation_refs), inputRefs: stringArray(item.input_refs), fieldRefs: stringArray(item.field_refs),
    candidates: (Array.isArray(item.candidates) ? item.candidates : []).filter(isRecord).map((row) => ({
      ruleId: str(row.rule_id), name: str(row.name), value: nullableString(row.value) ?? null, unit: str(row.unit), version: str(row.version),
      effectiveFrom: nullableString(row.effective_from) ?? null, effectiveTo: nullableString(row.effective_to) ?? null,
      source: str(row.source), confirmationStatus: str(row.confirmation_status), reason: str(row.reason),
      status: row.status === 'selected' || row.status === 'eligible' || row.status === 'excluded' || row.status === 'conflict' ? row.status : 'unknown',
      checks: (Array.isArray(row.checks) ? row.checks : []).filter(isRecord).map((check) => ({
        name: str(check.name), actual: nullableString(check.actual) ?? null, expected: str(check.expected),
        outcome: check.outcome === 'met' || check.outcome === 'unmet' ? check.outcome : 'unknown', inputRef: nullableString(check.input_ref) ?? null,
      })),
    })),
  }))
}

function toFeeDecompositionOperands(value: unknown): PolicyQAFeeDecompositionOperand[] {
  if (!Array.isArray(value)) return []
  return value.filter(isRecord).map((item) => ({
    displayName: typeof item.display_name === 'string' ? item.display_name : '',
    value: typeof item.value === 'string' ? item.value : '',
    isIntermediate: item.is_intermediate === true,
    ...(typeof item.input_ref === 'string' ? { inputRef: item.input_ref } : {}),
    ...(typeof item.calculation_ref === 'string' ? { calculationRef: item.calculation_ref } : {}),
  }))
}

function toFeeDecompositionCalculations(
  value: unknown,
): PolicyQAFeeDecompositionCalculation[] {
  if (!Array.isArray(value)) return []
  return value.filter(isRecord).map((item) => ({
    explainable: item.explainable === true,
    calculationId: typeof item.calculation_id === 'string' ? item.calculation_id : '',
    displayName: typeof item.display_name === 'string' ? item.display_name : '',
    formulaId: typeof item.formula_id === 'string' ? item.formula_id : '',
    formulaVersion: typeof item.formula_version === 'string' ? item.formula_version : '',
    formula: nullableString(item.formula) ?? null,
    verificationStatus: toFormulaInputStatus(item.verification_status),
    verificationReason: nullableString(item.verification_reason) ?? null,
    layout: FEE_CALC_LAYOUTS.has(item.layout as PolicyQAFeeDecompositionCalculation['layout'])
      ? (item.layout as PolicyQAFeeDecompositionCalculation['layout'])
      : 'generic',
    operands: toFeeDecompositionOperands(item.operands),
    unroundedResult: nullableString(item.unrounded_result) ?? null,
    roundingRule: nullableString(item.rounding_rule) ?? null,
    result: nullableString(item.result) ?? null,
  }))
}

/** 来源项 category 非法（非 settlement_record/policy_basis）时整项丢弃。 */
function toFeeDecompositionSources(value: unknown): PolicyQAFeeDecompositionSource[] {
  if (!Array.isArray(value)) return []
  return value.filter(isRecord).flatMap((item) => {
    const category = item.category
    if (category !== 'settlement_record' && category !== 'policy_basis') return []
    return [
      {
        refId: typeof item.ref_id === 'string' ? item.ref_id : '',
        title: typeof item.title === 'string' ? item.title : '',
        category,
        confirmationStatus: nullableString(item.confirmation_status) ?? null,
        value: nullableString(item.value) ?? null,
        values: stringArray(item.values),
        link: nullableString(item.link) ?? null,
      },
    ]
  })
}

function toFeeDecompositionConditions(value: unknown): PolicyQAFeeDecompositionCondition[] {
  if (!Array.isArray(value)) return []
  return value.filter(isRecord).map((item) => ({
    stepId: typeof item.step_id === 'string' ? item.step_id : '',
    moduleLabel: typeof item.module_label === 'string' ? item.module_label : '',
    description: typeof item.description === 'string' ? item.description : '',
    actualDisplay: nullableString(item.actual_display) ?? null,
    expectedDisplay: nullableString(item.expected_display) ?? null,
    outcome: typeof item.outcome === 'string' ? item.outcome : '',
    calculationRefs: stringArray(item.calculation_refs),
  }))
}

function toDisplayTemplate(raw: unknown): SettlementDisplayTemplate | undefined {
  if (!isRecord(raw) || typeof raw.template_id !== 'string' || typeof raw.version !== 'string'
    || typeof raw.title !== 'string' || !['image_verified', 'provisional'].includes(String(raw.layout_status)) || !Array.isArray(raw.fields)) return undefined
  const fields: SettlementTemplateField[] = []
  const seen = new Set<string>()
  for (const item of raw.fields) {
    if (!isRecord(item) || typeof item.key !== 'string' || !/^[a-z][a-z0-9_]*$/.test(item.key)
      || seen.has(item.key) || typeof item.label !== 'string' || !['basic', 'transaction', 'hospital'].includes(String(item.section))
      || !Number.isInteger(item.row) || Number(item.row) < 1 || !Number.isInteger(item.column) || Number(item.column) < 1 || Number(item.column) > 4
      || !Number.isInteger(item.span) || Number(item.span) < 1 || Number(item.span) > 4
      || !['metadata', 'patient_actual', 'patient_book', 'hospital_quota'].includes(String(item.scope))
      || !['record', 'derived', 'unmapped', 'context'].includes(String(item.source_kind))
      || !['available', 'missing', 'unmapped'].includes(String(item.status))) return undefined
    seen.add(item.key)
    fields.push({ key: item.key, label: item.label, semanticLabel: nullableString(item.semantic_label) ?? null,
      fieldCode: nullableString(item.field_code) ?? null, section: item.section as SettlementTemplateField['section'],
      row: Number(item.row), column: Number(item.column), span: Number(item.span), scope: item.scope as SettlementTemplateField['scope'],
      value: nullableString(item.value) ?? null, sourceKind: item.source_kind as SettlementTemplateField['sourceKind'],
      status: item.status as SettlementTemplateField['status'], contextKey: nullableString(item.context_key) ?? null, note: nullableString(item.note) ?? null })
  }
  return { templateId: raw.template_id, version: raw.version, title: raw.title,
    layoutStatus: raw.layout_status as SettlementDisplayTemplate['layoutStatus'], fields }
}

function toSettlementFacts(value: unknown): PolicyQASettlementFacts | undefined {
  if (!isRecord(value) || (value.chain !== 'outpatient' && value.chain !== 'special')) return undefined
  const items = (raw: unknown): PolicyQASettlementFacts['items'] =>
    Array.isArray(raw) ? raw.filter(isRecord).filter((item) => typeof item.label === 'string').map((item) => ({
      label: item.label as string,
      value: nullableString(item.value) ?? null,
    })) : []
  return {
    chain: value.chain,
    identifier: nullableString(value.identifier) ?? null,
    tradeDate: nullableString(value.trade_date) ?? null,
    medicalCategory: nullableString(value.medical_category) ?? null,
    insuranceType: nullableString(value.insurance_type) ?? null,
    personType: nullableString(value.person_type) ?? null,
    hospitalLevel: nullableString(value.hospital_level) ?? null,
    retireOfficerFlag: nullableString(value.retire_officer_flag) ?? null,
    metadataNames: isRecord(value.metadata_names) ? Object.fromEntries(Object.entries(value.metadata_names).filter((entry): entry is [string, string] => typeof entry[1] === 'string')) : {},
    items: items(value.items),
    paymentItems: items(value.payment_items),
    displayTemplate: toDisplayTemplate(value.display_template),
  }
}

const PATH_STATUSES = new Set(['applied', 'zero_amount', 'not_applicable', 'unknown', 'observed_only'])

function toPathSteps(value: unknown): PolicyQASettlementPathStep[] | undefined {
  if (!Array.isArray(value)) return undefined
  return value.filter(isRecord).filter((item) => typeof item.step_id === 'string' && typeof item.name === 'string').map((item) => ({
    stepId: item.step_id as string,
    name: item.name as string,
    status: PATH_STATUSES.has(item.status as string) ? item.status as PolicyQASettlementPathStep['status'] : 'unknown',
    amount: nullableString(item.amount) ?? null,
    calculationRefs: stringArray(item.calculation_refs),
    fieldRefs: stringArray(item.field_refs),
    reason: nullableString(item.reason) ?? null,
    conditionRefs: stringArray(item.condition_refs),
  }))
}

function toFeeDecompositionCoverage(
  value: unknown,
): PolicyQAFeeDecompositionCoverage | undefined {
  if (!isRecord(value)) return undefined
  const count = (v: unknown): number =>
    typeof v === 'number' && Number.isInteger(v) && v >= 0 ? v : 0
  return {
    targetFieldCount: count(value.target_field_count),
    independentlyExplainedCount: count(value.independently_explained_count),
    amountReconciledCount: count(value.amount_reconciled_count),
    observedOnlyCount: count(value.observed_only_count),
  }
}

/**
 * 白名单转换后端 FeeDecompositionPublic（snake_case）。
 * 非对象或 execution_status 非法时返回 undefined（调用方不渲染分解块）。
 */
export function toFeeDecomposition(raw: unknown): PolicyQAFeeDecomposition | undefined {
  if (!isRecord(raw)) return undefined
  if (!isAnswerStatus(raw.execution_status)) return undefined
  return {
    schemaVersion: typeof raw.schema_version === 'string' ? raw.schema_version : '',
    algorithmVersion: typeof raw.algorithm_version === 'string' ? raw.algorithm_version : '',
    executionStatus: raw.execution_status,
    reconciliationStatus:
      typeof raw.reconciliation_status === 'string'
        ? raw.reconciliation_status
        : 'not_verifiable',
    summaryText: typeof raw.summary_text === 'string' ? raw.summary_text : '',
    summarySource: raw.summary_source === 'model' ? 'model' : 'template',
    mayClaimFullExplanation: raw.may_claim_full_explanation === true,
    fields: toFeeDecompositionFields(raw.fields),
    uncertainties: toFeeDecompositionUncertainties(raw.uncertainties),
    coverage: toFeeDecompositionCoverage(raw.coverage),
    calculations: toFeeDecompositionCalculations(raw.calculations),
    formulaInputs: toFormulaInputs(raw.formula_inputs),
    ruleChoices: toRuleChoices(raw.rule_choices),
    sources: toFeeDecompositionSources(raw.sources),
    conditions: toFeeDecompositionConditions(raw.conditions),
    settlementFacts: toSettlementFacts(raw.settlement_facts),
    pathSteps: toPathSteps(raw.path_steps),
    feeItems: toFeeItems(raw.fee_items),
    templateExplanations: toTemplateExplanations(raw.template_explanations),
  }
}

function toPaymentConditionContext(value: unknown): import('./fee-decomposition-api').PaymentConditionContextDto | undefined {
  if (!isRecord(value)) return undefined
  return {
    bz: nullableString(value.bz) ?? null, catalog_status: nullableString(value.catalog_status) ?? 'unavailable',
    catalog_source: nullableString(value.catalog_source) ?? null,
    effective_from: nullableString(value.effective_from) ?? null, effective_to: nullableString(value.effective_to) ?? null,
    fee_date: nullableString(value.fee_date) ?? null, date_basis: nullableString(value.date_basis) ?? null,
    specification: nullableString(value.specification) ?? null, unit: nullableString(value.unit) ?? null, usage: nullableString(value.usage) ?? null,
    hospital_level: nullableString(value.hospital_level) ?? null, hospital_level_name: nullableString(value.hospital_level_name) ?? null,
    catalog_hospital_level: nullableString(value.catalog_hospital_level) ?? null,
    catalog_hospital_type: nullableString(value.catalog_hospital_type) ?? null,
    catalog_use_restriction: nullableString(value.catalog_use_restriction) ?? null,
    diagnosis_status: nullableString(value.diagnosis_status) ?? 'unavailable',
    diagnoses: Array.isArray(value.diagnoses) ? value.diagnoses.filter(isRecord).map((diagnosis) => ({
      code: nullableString(diagnosis.code) ?? null, name: nullableString(diagnosis.name) ?? null,
      association: nullableString(diagnosis.association) ?? 'same_settlement', is_placeholder: diagnosis.is_placeholder === true,
      department: nullableString(diagnosis.department) ?? null, prescriber_level: nullableString(diagnosis.prescriber_level) ?? null,
    })) : [],
    symptoms: nullableString(value.symptoms) ?? null, symptoms_status: nullableString(value.symptoms_status) ?? 'not_available_in_current_source',
    clinical_conditions_verified: false,
    source_hash: nullableString(value.source_hash) ?? '', read_at: nullableString(value.read_at) ?? '',
  }
}

function toFeeItems(value: unknown): PolicyQAFeeItem[] | undefined {
  if (!Array.isArray(value)) return undefined
  return value.filter(isRecord).map((item) => ({
    lineId: nullableString(item.line_id) ?? '', itemCode: nullableString(item.item_code) ?? '',
    paymentConditionContext: toPaymentConditionContext(item.payment_condition_context),
    explainable: item.explainable === true,
    explanationReason: nullableString(item.explanation_reason) ?? null,
    classificationCode: nullableString(item.classification_code) ?? null,
    classificationLabel: nullableString(item.classification_label) ?? null,
    classificationSource: nullableString(item.classification_source) ?? null,
    centralizedProcurement: typeof item.centralized_procurement === 'boolean' ? item.centralized_procurement : null,
    catalogEntryId: nullableString(item.catalog_entry_id) ?? null,
    effectiveFrom: nullableString(item.effective_from) ?? null,
    effectiveTo: nullableString(item.effective_to) ?? null,
    ratioSource: nullableString(item.ratio_source) ?? null,
    ratioBasis: nullableString(item.ratio_basis) ?? null,
    limitSource: nullableString(item.limit_source) ?? null,
    decisionPath: (Array.isArray(item.decision_path) ? item.decision_path : []).filter(isRecord).map((check) => ({
      code: nullableString(check.code) ?? '', label: nullableString(check.label) ?? '', operator: nullableString(check.operator) ?? '',
      actual: nullableString(check.actual) ?? null, expected: nullableString(check.expected) ?? null, outcome: nullableString(check.outcome) ?? 'unknown',
      ruleRefs: stringArray(check.rule_refs), calculationRefs: stringArray(check.calculation_refs),
    })),
    calculationRefs: stringArray(item.calculation_refs),
    reconciliations: (Array.isArray(item.reconciliations) ? item.reconciliations : []).filter(isRecord).map((check) => ({
      label: nullableString(check.label) ?? '', observed: nullableString(check.observed) ?? null, calculated: nullableString(check.calculated) ?? null,
      difference: nullableString(check.difference) ?? null, checkStatus: nullableString(check.check_status) ?? 'not_verifiable',
    })),
    itemName: nullableString(item.item_name) ?? '', itemType: nullableString(item.item_type) ?? null,
    feeDate: nullableString(item.fee_date) ?? null, unitPrice: nullableString(item.unit_price) ?? null,
    quantity: nullableString(item.quantity) ?? null, totalFee: nullableString(item.total_fee) ?? null,
    observedInScope: nullableString(item.observed_in_scope) ?? null, observedOutScope: nullableString(item.observed_out_scope) ?? null,
    observedSelfPay2: nullableString(item.observed_self_pay_2) ?? null,
    calculatedInScope: nullableString(item.calculated_in_scope) ?? null, calculatedOutScope: nullableString(item.calculated_out_scope) ?? null,
    calculatedSelfPay2: nullableString(item.calculated_self_pay_2) ?? null,
    calculatedProportionalSelfPay: nullableString(item.calculated_proportional_self_pay) ?? null,
    verificationStatus: item.verification_status === 'verified' ? 'verified' : 'unverified',
      divisionMethod: ['ratio', 'limit', 'full_in', 'full_out', 'settlement_override'].includes(String(item.division_method)) ? item.division_method as PolicyQAFeeItem['divisionMethod'] : 'unknown',
      selfPayRatio: nullableString(item.self_pay_ratio) ?? null,
      includedRatio: nullableString(item.included_ratio) ?? null,
      unitPriceLimit: nullableString(item.unit_price_limit) ?? null,
      ...(item.a_ypbs != null ? { aYpbs: nullableString(item.a_ypbs) ?? null } : {}),
      ...(item.a_mzxj != null ? { aMzxj: nullableString(item.a_mzxj) ?? null } : {}),
      ...(item.a_zyxj != null ? { aZyxj: nullableString(item.a_zyxj) ?? null } : {}),
      ...(item.a_xbbl != null ? { aXbbl: nullableString(item.a_xbbl) ?? null } : {}),
      ...(item.ypfl != null ? { ypfl: nullableString(item.ypfl) ?? null } : {}),
      ...(item.bzjg != null ? { bzjg: nullableString(item.bzjg) ?? null } : {}),
      ...(item.settlement_price_limit != null ? { settlementPriceLimit: nullableString(item.settlement_price_limit) ?? null } : {}),
      ...(item.explanation != null ? { explanation: nullableString(item.explanation) ?? null } : {}),
    status: item.status === 'calculated' || item.status === 'observed_only' ? item.status : 'unknown',
    conditions: stringArray(item.conditions), formulas: stringArray(item.formulas), notes: stringArray(item.notes),
  }))
}

/** 页面与后续模型解释只使用后端批准的金额及其实际依赖。旧协议保留事实和诊断。 */
export function matchedFeeExplanation(data: PolicyQAFeeDecomposition): PolicyQAFeeDecomposition {
  const fields = data.fields.filter((field) => field.explainable === true)
  const calculations = data.calculations.filter((calc) => calc.explainable === true)
  const ids = new Set(calculations.map((calc) => calc.calculationId))
  const fieldIds = new Set(fields.map((field) => field.fieldCode))
  const pathSteps = data.pathSteps?.filter((step) => step.calculationRefs.some((ref) => ids.has(ref)) || step.fieldRefs.some((ref) => fieldIds.has(ref))).map((step) => ({ ...step, calculationRefs: step.calculationRefs.filter((ref) => ids.has(ref)), fieldRefs: step.fieldRefs.filter((ref) => fieldIds.has(ref)) }))
  const conditions = new Set(pathSteps?.flatMap((step) => step.conditionRefs ?? []) ?? [])
  return { ...data, fields, calculations, pathSteps, feeItems: data.feeItems?.filter((item) => item.explainable === true),
    conditions: data.conditions.filter((condition) => conditions.has(condition.stepId) || condition.calculationRefs.some((ref) => ids.has(ref))),
    ruleChoices: data.ruleChoices?.filter((group) => group.calculationRefs.some((ref) => ids.has(ref)) || group.fieldRefs.some((ref) => fieldIds.has(ref))),
  }
}
