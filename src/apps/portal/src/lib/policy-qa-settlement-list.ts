/**
 * V4.0 结算解释智能体：按时间段列结算单（设计 §7.1 / §8.1）。
 *
 * 对接 U0 后端端点 `GET /policy-qa/settlements?date_from=&date_to=&limit=`，
 * snake_case → camelCase 转换统一在本模块完成（跨层一致性），组件层只见 camelCase。
 * 另含时段（今天/本周/自定义）日期计算纯函数，可单测。
 */

export interface SettlementListItemDTO {
  settlementId: string
  settlementDate: string
  personType: string
  insuranceType: string
  serviceType: string
  totalAmount: number | null
  coverageStatus: 'complete' | 'partial' | 'unavailable'
}

/** 患者定位摘要（身份证号已由后端脱敏；正式接入登录验证后由登录态取代）。 */
export interface PatientSummaryDTO {
  cardNo: string
  idNoMasked: string
  name: string
  gender: string
  birthDate: string
  registrationId: string
}

const SETTLEMENTS_URL = '/api/v1/medical-insurance-ai-agent/policy-qa/settlements'
const PATIENT_LOOKUP_URL = '/api/v1/medical-insurance-ai-agent/policy-qa/patient-lookup'

interface RawSettlementItem {
  settlement_id?: string
  settlement_date?: string | null
  person_type?: string | null
  insurance_type?: string | null
  service_type?: string | null
  total_amount?: number | null
  coverage_status?: string | null
}

function toSettlementItem(raw: RawSettlementItem): SettlementListItemDTO {
  const coverage =
    raw.coverage_status === 'complete' ||
    raw.coverage_status === 'partial' ||
    raw.coverage_status === 'unavailable'
      ? raw.coverage_status
      : 'complete'
  return {
    settlementId: String(raw.settlement_id ?? ''),
    settlementDate: String(raw.settlement_date ?? ''),
    personType: String(raw.person_type ?? ''),
    insuranceType: String(raw.insurance_type ?? ''),
    serviceType: String(raw.service_type ?? ''),
    totalAmount: typeof raw.total_amount === 'number' ? raw.total_amount : null,
    coverageStatus: coverage,
  }
}

/** 按结算日期区间列出结算单摘要；patientKey 提供时仅返回该患者（不做 mock 降级）。 */
export async function fetchSettlementsByDateRange(
  dateFrom: string,
  dateTo: string,
  limit = 50,
  patientKey?: string,
): Promise<SettlementListItemDTO[]> {
  const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo, limit: String(limit) })
  if (patientKey) params.set('patient_key', patientKey)
  const response = await fetch(`${SETTLEMENTS_URL}?${params.toString()}`)
  if (!response.ok) {
    throw new Error(`结算单列表查询失败（HTTP ${response.status}）`)
  }
  const data = (await response.json()) as RawSettlementItem[]
  return Array.isArray(data) ? data.map(toSettlementItem) : []
}

interface RawPatientSummary {
  card_no?: string | null
  id_no_masked?: string | null
  name?: string | null
  gender?: string | null
  birth_date?: string | null
  registration_id?: string | number | null
}

/**
 * 按身份证号或卡号定位患者；未找到返回 null（404），
 * 其他非 2xx 抛错。身份证号由后端脱敏后返回。
 */
export async function fetchPatientLookup(key: string): Promise<PatientSummaryDTO | null> {
  const params = new URLSearchParams({ key })
  const response = await fetch(`${PATIENT_LOOKUP_URL}?${params.toString()}`)
  if (response.status === 404) return null
  if (!response.ok) {
    throw new Error(`患者定位失败（HTTP ${response.status}）`)
  }
  const raw = (await response.json()) as RawPatientSummary
  return {
    cardNo: String(raw.card_no ?? ''),
    idNoMasked: String(raw.id_no_masked ?? ''),
    name: String(raw.name ?? ''),
    gender: String(raw.gender ?? ''),
    birthDate: String(raw.birth_date ?? ''),
    registrationId: String(raw.registration_id ?? ''),
  }
}

// ── 时段计算（纯函数，本地时区）────────────────────────────────

export type SettlementPreset = 'today' | 'this_week' | 'custom'

export interface DateRange {
  dateFrom: string
  dateTo: string
}

/** Date → YYYY-MM-DD（本地时区）。 */
export function toDateInput(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function todayRange(now = new Date()): DateRange {
  const today = toDateInput(now)
  return { dateFrom: today, dateTo: today }
}

/** 本周（周一起始，含今天）。 */
export function thisWeekRange(now = new Date()): DateRange {
  const day = now.getDay()
  const offset = day === 0 ? 6 : day - 1
  const monday = new Date(now)
  monday.setDate(now.getDate() - offset)
  return { dateFrom: toDateInput(monday), dateTo: toDateInput(now) }
}

/** 金额格式化：12,386.40；null → '—'。 */
export function formatAmount(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—'
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
