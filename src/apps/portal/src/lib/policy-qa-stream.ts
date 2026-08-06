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
}

export interface PolicyQAVerificationSummary {
  settlementChecked: boolean
  calculationChecked: boolean
  policyCount: number
  message: string
}

export interface PolicyQAResult {
  answer: string
  answerStatus: 'complete' | 'partial' | 'unavailable'
  caseContext?: PolicyQACaseContext
  calculationSteps: Array<{ stepName: string; description: string }>
  definition?: { name: string; plainText: string; excludes: string[] }
  warnings: string[]
  citations: Array<{ title: string; excerpt: string }>
  uncertainties: string[]
  verificationSummary: PolicyQAVerificationSummary
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
  }
}

function toCalculationSteps(value: unknown): PolicyQAResult['calculationSteps'] {
  if (!Array.isArray(value)) return []
  return value.filter(isRecord).map((step) => ({
    stepName: typeof step.step_name === 'string' ? step.step_name : '',
    description: typeof step.description === 'string' ? step.description : '',
  }))
}

function toDefinition(value: unknown): PolicyQAResult['definition'] {
  if (!isRecord(value)) return undefined
  return {
    name: typeof value.name === 'string' ? value.name : '',
    plainText: typeof value.plain_text === 'string' ? value.plain_text : '',
    excludes: stringArray(value.excludes),
  }
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
  }))
}
