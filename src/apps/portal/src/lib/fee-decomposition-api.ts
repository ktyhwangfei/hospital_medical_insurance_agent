// 费用分解工作台 API 客户端 — Issue #78 四链路页面可用化（Phase 3）。
// DTO 字段与后端 src/runtime/policy_qa/public_contract.py FeeDecompositionPublic
// 及 POST /fee-decomposition/decompose 响应逐字段对齐（snake_case 直传）；
// camelCase 转换复用 src/lib/policy-qa-stream.ts 的 toFeeDecomposition。
import { requestJson } from './api-client'

// ── DTO（snake_case，与后端公开契约一致；金额为十进制字符串）──

export type FeeDecompositionChain = 'auto' | 'outpatient' | 'special'

/** 解释投影 1.10：字段四要素固定说明（snake_case，与后端 FieldExplanationView 对齐）。 */
export interface FieldExplanationDto {
  meaning: string | null
  composition: string | null
  basis_text: string | null
  boundary: string | null
}

export interface FeeDecompositionFieldDto {
  explainable?: boolean
  explanation_reason?: string | null
  field_code: string
  label: string
  check_type: string
  check_status: string
  observed_amount: string | null
  calculated_amount: string | null
  difference: string | null
  explanation_level: string
  /** 解释投影 1.1 增补；1.0 旧载荷键整体缺失，故声明可选。 */
  reason_code?: string | null
  calculation_refs?: string[]
  source_refs?: string[]
  gap_refs?: string[]
  brief?: string | null
  /** 解释投影 1.10 增补；1.9 及更早载荷键整体缺失，故声明可选。 */
  explanation?: FieldExplanationDto | null
}

export interface FeeDecompositionUncertaintyDto {
  code: string
  message: string
  /** 解释投影 1.1 增补。 */
  id?: string
  affected_fields?: string[]
}

/** 解释投影 1.1：计算操作数（value 为有符号十进制字符串，负号表减项）。 */
export interface FeeDecompositionOperandDto {
  display_name: string
  value: string
  is_intermediate: boolean
  input_ref?: string | null
  calculation_ref?: string | null
}

/** 解释投影 1.1：单条计算记录。 */
export interface FeeDecompositionCalculationDto {
  explainable?: boolean
  calculation_id: string
  formula?: string | null
  display_name: string
  formula_id: string
  formula_version: string
  layout: 'sum' | 'subtract_rest' | 'product' | 'generic'
  operands: FeeDecompositionOperandDto[]
  unrounded_result: string | null
  rounding_rule: string | null
  result: string | null
  verification_status?: 'verified' | 'unverified' | 'missing' | 'conflict'
  verification_reason?: string | null
}

export interface FormulaInputDto {
  input_id: string; name: string; value: string | null
  status: 'verified' | 'unverified' | 'missing' | 'conflict'
  source: string; reason: string | null; calculation_ref: string | null; rule_group_ref: string | null
    rule_id?: string | null
}
export interface RuleChoiceGroupDto {
  group_id: string; title: string; calculation_refs: string[]; input_refs: string[]; field_refs?: string[]
  candidates: Array<{
    rule_id: string; name: string; value: string | null; unit: string; version: string
    effective_from: string | null; effective_to: string | null; source: string; confirmation_status: string
    status: 'selected' | 'eligible' | 'excluded' | 'unknown' | 'conflict'; reason: string
    checks: Array<{ name: string; actual: string | null; expected: string; outcome: 'met' | 'unmet' | 'unknown'; input_ref: string | null }>
  }>
}

/** 解释投影 1.1：来源。 */
export interface FeeDecompositionSourceDto {
  ref_id: string
  title: string
  category: 'settlement_record' | 'policy_basis'
  confirmation_status: string | null
  value: string | null
  values: string[]
  link: string | null
}

/** 解释投影 1.1：采用条件。 */
export interface FeeDecompositionConditionDto {
  step_id: string
  module_label: string
  description: string
  actual_display: string | null
  expected_display: string | null
  outcome: string
  calculation_refs: string[]
}

export interface FeeDecompositionCoverageDto {
  target_field_count: number
  independently_explained_count: number
  amount_reconciled_count: number
  observed_only_count: number
}

export interface FeeDecompositionMetaDto {
  identifier: string
  chain: string
  profile: string | null
  algorithm_version: string
}

export interface SettlementFactsDto {
  chain: 'outpatient' | 'special'
  identifier: string | null
  trade_date: string | null
  medical_category: string | null
  insurance_type: string | null
  person_type: string | null
  hospital_level: string | null
  metadata_names?: Record<string, string>
  retire_officer_flag?: string | null
  items: Array<{ label: string; value: string | null }>
  payment_items: Array<{ label: string; value: string | null }>
  display_template?: {
    template_id: string; version: string; title: string; layout_status: 'image_verified' | 'provisional'
    fields: Array<{
      key: string; label: string; semantic_label: string | null; field_code: string | null
      section: 'basic' | 'transaction' | 'hospital'; row: number; column: number; span: number
      scope: 'metadata' | 'patient_actual' | 'patient_book' | 'hospital_quota'; value: string | null
      source_kind: 'record' | 'derived' | 'unmapped' | 'context'; status: 'available' | 'missing' | 'unmapped'
      context_key: string | null; note: string | null
    }>
  }
}

export interface SettlementPathStepDto {
  step_id: string
  name: string
  status: 'applied' | 'zero_amount' | 'not_applicable' | 'unknown' | 'observed_only'
  amount: string | null
  calculation_refs: string[]
  field_refs: string[]
  reason: string | null
  condition_refs?: string[]
}

export interface FeeItemExplanationDto {
  explainable?: boolean
  explanation_reason?: string | null
  classification_code?: string | null
  classification_label?: string | null
  classification_source?: string | null
  centralized_procurement?: boolean | null
  catalog_entry_id?: string | null
  effective_from?: string | null
  effective_to?: string | null
  ratio_source?: string | null
  ratio_basis?: string | null
  limit_source?: string | null
  /** 解释投影 1.6：逐行目录事实与中文解释（键缺失即未返回）。 */
  a_ypbs?: string | null
  a_mzxj?: string | null
  a_zyxj?: string | null
  a_xbbl?: string | null
  ypfl?: string | null
  bzjg?: string | null
  settlement_price_limit?: string | null
  explanation?: string | null
  decision_path?: Array<{ code: string; label: string; operator: string; actual: string | null; expected: string | null; outcome: string; rule_refs: string[]; calculation_refs: string[] }>
  calculation_refs?: string[]
  reconciliations?: Array<{ label: string; observed: string | null; calculated: string | null; difference: string | null; check_status: string }>
  line_id: string
  item_code: string
  item_name: string
  item_type: string | null
  fee_date: string | null
  unit_price: string | null
  quantity: string | null
  total_fee: string | null
  observed_in_scope: string | null
  observed_out_scope: string | null
  observed_self_pay_2: string | null
  calculated_in_scope: string | null
  calculated_out_scope: string | null
  calculated_self_pay_2: string | null
  calculated_proportional_self_pay?: string | null
  status: 'calculated' | 'observed_only' | 'unknown'
  verification_status?: 'verified' | 'unverified'
  division_method?: 'ratio' | 'limit' | 'full_in' | 'full_out' | 'settlement_override' | 'unknown'
  self_pay_ratio?: string | null
  included_ratio?: string | null
  unit_price_limit?: string | null
  conditions: string[]
  formulas: string[]
  notes: string[]
}

/** POST /fee-decomposition/decompose 响应：FeeDecompositionPublic 全字段 + meta。 */
export interface FeeDecompositionResponseDto {
  schema_version: string
  formula_inputs?: FormulaInputDto[]
  rule_choices?: RuleChoiceGroupDto[]
  algorithm_version: string
  execution_status: 'complete' | 'partial' | 'unavailable'
  reconciliation_status: string
  summary_text: string
  summary_source: 'template' | 'model'
  may_claim_full_explanation: boolean
  fields: FeeDecompositionFieldDto[]
  uncertainties: FeeDecompositionUncertaintyDto[]
  coverage?: FeeDecompositionCoverageDto | null
  /** 解释投影 1.1 新增顶层数组；空时后端 exclude_if 不序列化该键，故声明可选。 */
  calculations?: FeeDecompositionCalculationDto[]
  sources?: FeeDecompositionSourceDto[]
  conditions?: FeeDecompositionConditionDto[]
  settlement_facts?: SettlementFactsDto | null
  path_steps?: SettlementPathStepDto[]
  fee_items?: FeeItemExplanationDto[]
  /** 解释投影 1.10：模板展示字段四要素固定说明，按模板 key 索引。 */
  template_explanations?: Record<string, FieldExplanationDto>
  meta: FeeDecompositionMetaDto
}

// ── 按人定位（resolve-person）：身份证 → 门诊交易/门特登记候选 ──

export interface PersonCandidateDto {
  chain: 'outpatient' | 'special'
  identifier: string
  chain_label: string
  profile_label: string
  service_date: string | null
  total_amount: string | null
}

/** POST /fee-decomposition/resolve-person 响应。 */
export interface ResolvePersonResponseDto {
  match_status: 'unique_match' | 'multiple_candidates' | 'no_match'
  truncated: boolean
  candidates: PersonCandidateDto[]
}

/**
 * 身份证格式判定：15 位纯数字，或 17 位数字 + 末位数字/X/x。
 * 交易号（T 前缀等）与门特登记号 djh（短号）不会命中。
 */
export function looksLikeIdCard(value: string): boolean {
  const text = value.trim()
  return /^\d{15}$/.test(text) || /^\d{17}[\dXx]$/.test(text)
}

// ── 鉴权（与 question-library 同模式：sessionStorage → dev 环境变量 token）──

export function feeDecompositionToken(): string | null {
  if (typeof window !== 'undefined') {
    const token = window.sessionStorage.getItem('fee-decomposition-token')
    if (token) return token
  }
  return process.env.NODE_ENV === 'production'
    ? null
    : process.env.NEXT_PUBLIC_FEE_DECOMPOSITION_TOKEN || null
}

/** 结算金额读取（列表/明细/解释流）统一 Authorization 头；无 token 时不伪造。 */
export function feeReadAuthHeaders(): Record<string, string> {
  const token = feeDecompositionToken()
  return token ? { Authorization: token.startsWith('Bearer ') ? token : `Bearer ${token}` } : {}
}

// ── 端点 ──

/** 单笔费用分解；未配置时后端返回 503（ApiClientError.detail 带缺失项说明）。 */
export function decomposeFee(
  identifier: string,
  chain: FeeDecompositionChain = 'auto',
): Promise<FeeDecompositionResponseDto> {
  const headers = new Headers({ 'Content-Type': 'application/json' })
  const token = feeDecompositionToken()
  if (token) headers.set('Authorization', token.startsWith('Bearer ') ? token : `Bearer ${token}`)
  return requestJson<FeeDecompositionResponseDto>('/fee-decomposition/decompose', {
    method: 'POST',
    headers,
    body: JSON.stringify({ identifier, chain }),
  })
}

/**
 * 会话级共享费用分解实例（阶段 A：面板↔聊天同源）。
 * 与 policy-qa 主流共用同一 (session, settlement) 实例、同一 fail-closed 口径；
 * 响应与 POST /fee-decomposition/decompose 同构（含 meta）。
 */
export function fetchSessionDecomposition(
  sessionId: string,
  settlementId: string,
  chain: FeeDecompositionChain = 'auto',
): Promise<FeeDecompositionResponseDto> {
  const params = new URLSearchParams({ settlement_id: settlementId, chain })
  return requestJson<FeeDecompositionResponseDto>(
    `/policy-qa/sessions/${encodeURIComponent(sessionId)}/decomposition?${params.toString()}`,
    { headers: feeReadAuthHeaders() },
  )
}

/** 按身份证号定位人员，列出该人员的门诊交易/门特登记候选；422 表示身份证格式非法。 */
export function resolvePerson(idCard: string): Promise<ResolvePersonResponseDto> {
  const headers = new Headers({ 'Content-Type': 'application/json' })
  const token = feeDecompositionToken()
  if (token) headers.set('Authorization', token.startsWith('Bearer ') ? token : `Bearer ${token}`)
  return requestJson<ResolvePersonResponseDto>('/fee-decomposition/resolve-person', {
    method: 'POST',
    headers,
    body: JSON.stringify({ id_card: idCard }),
  })
}
