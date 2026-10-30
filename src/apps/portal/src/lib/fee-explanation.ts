// 结算单解释投影：交易信息表 + 交易明细表的行/列与中文解释（Issue #78 工作台）。
// 人看口径：只出现人能读懂的中文与算式；字段代码、参数键、规则编号一律不出现。
// 解释边界：后端标记 explainable=false 的金额不展开计算原因（恒等式构成的账面金额除外）。
// 不同险种/医疗类别的原单字段名不同，这里统一为医院结算单口径，金额仍按算法原值透传。
import type { PolicyQAFeeDecomposition, PolicyQAFeeDecompositionField, PolicyQAFeeItem, PolicyQARuleChoice } from './policy-qa-stream'
import { decimalUnits, percentOf, sumAmounts } from './fee-explanation-numbers'
import { formatDecimal2 } from './policy-qa-settlement-list'
import { requiresSettlementTemplate } from './policy-qa-stream'

const money = (value: string | null | undefined) => value == null ? null : `${formatDecimal2(value)} 元`
const num = (value: string | null | undefined) => value != null && /^-?\d+(\.\d+)?$/.test(value) ? Number(value) : null
const isZero = (value: string | null | undefined) => num(value) === 0
const positive = (value: string | null | undefined) => (num(value) ?? 0) > 0

export interface RatioCheck {
  name: string
  expected: string
  actual: string | null
  outcome: 'met' | 'unmet' | 'unknown'
}

/** 比例档展开：档位、命中条件（四列）、来源与有效期，供逐行溯源。 */
export interface RatioDetail {
  groupId: string
  title: string
  chosen: string
  checks: RatioCheck[]
  source: string | null
  version: string | null
  effective: string | null
  caliber: string | null
  /** 档位值（含单位），如 50% / 4500 元/保险年度 */
  value: string
  /** true=本次实际执行；false=条件符合但本单未进入该分支 */
  executed: boolean
}

export interface SummaryRow {
  key: string
  label: string
  value: string | null
  explanation: string | null
  group: string
  indent?: boolean
  emphasis?: boolean
  /** 展开依据：完整函数算式等 */
  notes: string[]
  /** 展开依据：采用的比例档 */
  ratios: RatioDetail[]
  /** 展开按钮文案 */
  expandLabel: string | null
}

/** 展示名：与医院结算单模板 label 一致；内部匹配仍用规范名。 */
const HOSPITAL_LABELS: Record<string, string> = {
  费用总金额: '费用总金额',
  医保范围内金额: '医疗保险范围内金额',
  医保范围外金额: '医疗保险范围外金额',
  自付二: '个人支付自付（二）金额',
  起付金额: '起付金额',
  统筹基金支付: '统筹基金支付金额',
  统筹自付: '统筹自付金额',
  大额支付: '门诊大额基金支付金额',
  大额个人自付: '大额自付金额',
  自付一: '个人支付自付（一）金额',
  退休补助: '补充保险支付金额',
  军残补助: '残疾军人补助支付金额',
  公疗补助: '单位补充医疗保险（原公疗）支付金额',
  退役医疗费支付: '退役医疗费',
  基金合计: '基金支付金额',
  大病保险支付: '大病支付',
  民政救助支付: '救助支付',
  个人支付总金额: '个人支付总金额',
  账户支付: '当次个人帐户支付金额',
  现金支付: '当次个人现金支付金额',
}
const hospital = (label: string) => HOSPITAL_LABELS[label] ?? label

const GROUP_ORDER = [
  '费用构成',
  '起付与基金支付',
  '自付构成',
  '补助',
  '大病与医疗救助',
  '个人支付合计',
  '支付方式',
] as const

const ROW_GROUP: Record<string, string> = {
  费用总金额: '费用构成', 医保范围内金额: '费用构成', 医保范围外金额: '费用构成', 自付二: '费用构成',
  起付金额: '起付与基金支付', 基金合计: '起付与基金支付', 统筹基金支付: '起付与基金支付', 大额支付: '起付与基金支付',
  自付一: '自付构成', 统筹自付: '自付构成', 大额个人自付: '自付构成',
  退休补助: '补助', 军残补助: '补助', 公疗补助: '补助', 退役医疗费支付: '补助',
  大病保险支付: '大病与医疗救助', 民政救助支付: '大病与医疗救助',
  个人支付总金额: '个人支付合计',
}

export { GROUP_ORDER }

/** 去掉字段代码、参数键、规则编号与比较符，只留中文。 */
export function plainDescription(text: string): string {
  return cleanup(
    text
      .replace(/[A-Za-z_][A-Za-z0-9_.-]*\s*=\s*'[^']*'/g, '')
      .replace(/[A-Za-z_][A-Za-z0-9_.-]*(?:\s*(?:>=|<=|>|<|≠|!=|→)\s*[\d.%]*)?/g, '')
      .replace(/(>=|<=|!=|≠|→|[<>])/g, ' ')
      .replace(/^[：:；;，,、\s]+/, ''),
  )
}

function cleanup(text: string): string {
  return text
    .replace(/（\s*=[A-Za-z_][A-Za-z0-9_.]*\s*）/g, '')
    .replace(/（[：:→=\s]+/g, '（')
    .replace(/\s+）/g, '）')
    .replace(/（\s*）/g, '')
    .replace(/([\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff，。；、：）])/g, '$1')
    .replace(/\s+/g, ' ')
    .trim()
}

type AggregateKey = 'total' | 'in' | 'out' | 'self2'

/** 交易信息前四行：一律由交易明细逐项合计得出，原单同名行不再重复展示。 */
const AGGREGATES: Array<{
  key: AggregateKey
  label: string
  pick: (item: PolicyQAFeeItem) => string | null | undefined
  matches: (label: string) => boolean
}> = [
  { key: 'total', label: '费用总金额', pick: (item) => item.totalFee, matches: (label) => label === '总费用' || label === '费用总金额' },
  { key: 'in', label: '医保范围内金额', pick: (item) => item.observedInScope, matches: (label) => label.includes('医保内') || label.includes('医保范围内') },
  { key: 'out', label: '医保范围外金额', pick: (item) => item.observedOutScope, matches: (label) => label.includes('医保外') || label.includes('医保范围外') },
  { key: 'self2', label: '自付二', pick: (item) => item.observedSelfPay2, matches: (label) => label.includes('自付二') || label.includes('个人自付2') || label.includes('先行自付') },
]

/** 原单字段名 → 医院结算单口径（不同险种/医疗类别只差底层字段名）。 */
const LABEL_ALIAS: Record<string, string> = {
  本次起付金额: '起付金额',
  本次起付承担: '起付金额',
  大额互助支付: '大额支付',
  大额自付: '大额个人自付',
  退休补充保险补助: '退休补助',
  军残支付: '军残补助',
  公疗补充支付: '公疗补助',
  医疗救助支付: '民政救助支付',
  '个人支付自付（一）金额': '自付一',
  原始个人自付一: '自付一',
  '定额范围内原始自付一（含起付）': '自付一',
}

/** 展示口径 → 后端字段 label 候选（后端各链路 label 不同，按候选逐一匹配）。 */
const FIELD_CANDIDATES: Record<string, string[]> = {
  起付金额: ['本次起付承担', '本次起付金额', '起付金额'],
  自付一: ['个人支付自付（一）金额', '自付一', '原始个人自付一', '定额范围内原始自付一（含起付）'],
  大额支付: ['大额支付', '大额互助支付', '基本医保基金支付'],
  大额个人自付: ['大额个人自付', '大额自付', '基本医保基金支付后自付'],
  退休补助: ['退休补充保险补助', '退休补助'],
  军残补助: ['军残支付', '军残补助'],
  公疗补助: ['公疗补充支付', '公疗补助'],
  民政救助支付: ['医疗救助支付', '民政救助支付'],
  大病保险支付: ['大病保险支付（二次保障）', '大病保险支付'],
  个人支付总金额: ['最终个人承担', '个人应付（对照现金与账户合计）', '个人支付总金额'],
}

/** 后端字段 label → 展示行（反向映射）；特殊病/普通门诊双套事实条目归到同一行。 */
const FIELD_TO_DISPLAY: Record<string, string> = (() => {
  const map: Record<string, string> = {}
  for (const [display, candidates] of Object.entries(FIELD_CANDIDATES)) {
    for (const candidate of candidates) map[candidate] = display
  }
  for (const [alias, display] of Object.entries(LABEL_ALIAS)) if (!map[alias]) map[alias] = display
  // 门特/普通门诊字段 label（employee_outpatient_special._FIELD_LABELS 口径）
  for (const label of ['总费用', '费用总金额']) map[label] = '费用总金额'
  for (const label of ['医保内费用', '医疗保险范围内金额', '特殊病医保内', '普通门诊医保内']) map[label] = '医保范围内金额'
  for (const label of ['医保外费用', '医疗保险范围外金额', '特殊病医保外', '普通门诊医保外']) map[label] = '医保范围外金额'
  map['先行自付'] = '自付二'
  map['个人支付自付（二）金额'] = '自付二'
  map['本次起付金额'] = '起付金额'
  map['统筹基金支付金额'] = '统筹基金支付'
  map['统筹自付金额'] = '统筹自付'
  map['门诊大额基金支付金额'] = '大额支付'
  map['大额自付金额'] = '大额个人自付'
  map['补充保险支付金额'] = '退休补助'
  map['残疾军人补助支付金额'] = '军残补助'
  map['单位补充医疗保险（原公疗）支付金额'] = '公疗补助'
  map['大病支付'] = '大病保险支付'
  map['救助支付'] = '民政救助支付'
  map['个人支付自付（一）金额'] = '自付一'
  map['原始个人自付一'] = '自付一'
  map['定额范围内原始自付一（含起付）'] = '自付一'
  // 分桶/汇总子项：金额已计入对应的合计行
  map['先行自付（明细汇总）'] = '自付二'
  for (const label of ['医保内个人自付一的大病支付', '按比例先行自付的大病支付']) map[label] = '大病保险支付'
  for (const label of ['医保内剩余个人负担的救助', '按比例先行自付剩余负担的救助']) map[label] = '民政救助支付'
  // 字段 label 与展示行同名的直接回环（统筹基金支付/大额互助支付/现金支付等）
  for (const label of Object.keys(ROW_GROUP)) if (!map[label]) map[label] = label
  for (const label of ['账户支付', '现金支付']) if (!map[label]) map[label] = label
  return map
})()

/** 单个后端字段的映射清单：页面哪一行承接它、账面/计算值、是否单独成行。 */
export interface FieldInventoryItem {
  fieldCode: string
  label: string
  /** 承接它的展示行（字段代码口径）；null = 未映射到任何行 */
  display: string | null
  group: string
  observed: string | null
  calculated: string | null
  checkStatus: string
  /** true=页面已有同名行；false=只在下方“未单列字段”明细里出现 */
  shownAsRow: boolean
}

/** 全部非派生字段的映射清单：保证任何后端字段都能在页面上找到。 */
export function buildFieldInventory(data: PolicyQAFeeDecomposition, rows?: SummaryRow[]): FieldInventoryItem[] {
  const rowLabels = new Set((rows ?? []).map((row) => row.label))
  return data.fields
    .filter((field) => !field.fieldCode.includes('.'))
    .map((field) => {
      const canonical = FIELD_TO_DISPLAY[field.label] ?? null
      const display = canonical ? hospital(canonical) : null
      return {
        fieldCode: field.fieldCode, label: field.label, display, group: canonical ? ROW_GROUP[canonical] ?? '其他' : '其他',
        observed: field.observedAmount, calculated: field.calculatedAmount,
        checkStatus: field.checkStatus,
        shownAsRow: display != null && rowLabels.has(display),
      }
    })
}

/** 基金合计 = 各基金支出之和（与后端恒等式分量一致）。 */
const FUND_COMPONENTS = ['统筹基金支付', '大额支付', '退休补助', '军残补助', '公疗补助', '退役医疗费支付', '大病保险支付', '民政救助支付']

/** 大病/救助类金额行：后端算式不直接引用比例计算，按规则组标题关键字关联。 */
const RATIO_KEYWORDS: Record<string, string[]> = {
  大病保险支付: ['大病'],
  民政救助支付: ['救助'],
}

const UNMET_KEYWORDS: Record<string, string[]> = {
  退休补助: ['退休'],
  军残补助: ['军残', '残疾军人'],
  公疗补助: ['公疗'],
}

function findField(data: PolicyQAFeeDecomposition, label: string) {
  if (label === '基金合计') {
    const listed = data.fields.find((field) => field.fieldCode === 'T_FundPay.listed_channels' && field.checkStatus === 'matched')
    if (listed) return listed
  }
  const names = FIELD_CANDIDATES[label] ?? [label]
  return data.fields.find((field) => names.includes(field.label)) ?? null
}

function findCalc(data: PolicyQAFeeDecomposition, id: string | undefined) {
  return id ? data.calculations.find((calc) => calc.calculationId === id) ?? null : null
}

function lastFormula(data: PolicyQAFeeDecomposition, fieldCode: string): string | null {
  const field = data.fields.find((item) => item.fieldCode === fieldCode)
  return findCalc(data, field?.calculationRefs.at(-1))?.formula ?? null
}

/** 字段自身的算式：优先选结果等于本字段金额的计算，不直接取依赖列表最后一条。 */
function fieldFormula(data: PolicyQAFeeDecomposition, field: PolicyQAFeeDecompositionField | null): string | null {
  if (!field) return null
  const calculated = (field.calculationRefs ?? [])
    .map((ref) => findCalc(data, ref))
    .filter((calc): calc is NonNullable<typeof calc> => !!calc?.formula)
  const amount = field.observedAmount ?? field.calculatedAmount
  const matching = amount == null
    ? []
    : calculated.filter((calc) => calc.result != null && decimalUnits(calc.result) === decimalUnits(amount))
  // 同一金额可能同时是基金支付与个人差额（各占 50% 时金额相等）：
  // 非自付字段排除“自付/差额”记录，避免把个人承担当成基金支付。
  const selfPayField = /SelfPay|自付/.test(`${field.fieldCode} ${field.label}`)
  const own = selfPayField ? matching : matching.filter((calc) => !/self_pay|差额|自付/i.test(`${calc.calculationId} ${calc.displayName}`))
  return (own.at(-1) ?? matching.at(-1) ?? calculated.at(-1))?.formula ?? null
}

/** 该字段所属结算阶段里未命中/不适用的条件，作为"为什么是 0"的算法原话。 */
function unmetConditions(data: PolicyQAFeeDecomposition, fieldCode: string, label: string): string | null {
  const step = (data.pathSteps ?? []).find((item) => item.fieldRefs.includes(fieldCode))
  if (!step) return null
  const refs = new Set(step.conditionRefs ?? [])
  const keywords = UNMET_KEYWORDS[label]
  const lines = data.conditions
    .filter((condition) => refs.has(condition.stepId) && ['false', 'not_applicable'].includes(condition.outcome))
    .filter((condition) => !condition.stepId.includes('.segment.') && !condition.stepId.endsWith('.intersection'))
    .filter((condition) => !keywords || keywords.some((keyword) => condition.description.includes(keyword)))
    .map((condition) => `${condition.outcome === 'not_applicable' ? '不适用' : '未命中'}：${plainDescription(condition.description)}`)
  return [...new Set(lines)].join('；') || null
}

/** 金额为 0 时先回答"为什么是 0"：优先取本行算法里"基数为零/不发生"的记录。 */
function zeroReason(data: PolicyQAFeeDecomposition, fieldCode: string | null, label: string): string | null {
  if (!fieldCode) return null
  const field = data.fields.find((item) => item.fieldCode === fieldCode)
  const formulas = (field?.calculationRefs ?? []).map((ref) => findCalc(data, ref)).filter((calc) => calc?.formula)
  const key = label.includes('民政') ? '救助' : label.includes('大病') ? '大病' : null
  const own = key ? formulas.filter((calc) => calc!.formula!.includes(key)) : formulas
  const zero = own.find((calc) => calc!.formula!.includes('为零') || calc!.formula!.includes('不发生'))
    ?? own.find((calc) => calc!.formula!.includes('×'))
    ?? formulas.find((calc) => calc!.formula!.includes('为零') || calc!.formula!.includes('不发生'))
  if (zero?.formula) return zero.formula
  return unmetConditions(data, fieldCode, label)
}

/** 比例档：先按计算记录关联，再按标签关键字补关联；未执行的档位单独标注。 */
function rowRatioGroups(data: PolicyQAFeeDecomposition, fieldCode: string | null, label: string, used: Set<string>): PolicyQARuleChoice[] {
  const refs = new Set(fieldCode ? data.fields.find((item) => item.fieldCode === fieldCode)?.calculationRefs ?? [] : [])
  const keywords = RATIO_KEYWORDS[label] ?? []
  return (data.ruleChoices ?? []).filter((group) => {
    if (used.has(group.groupId)) return false
    const picked = group.candidates.some((candidate) => candidate.status === 'selected' || candidate.status === 'eligible')
    if (!picked) return false
    const linked = group.calculationRefs.some((ref) => refs.has(ref))
      || keywords.some((keyword) => group.title.includes(keyword))
    if (!linked) return false
    used.add(group.groupId)
    return true
  })
}

export function ratioDetails(groups: PolicyQARuleChoice[]): RatioDetail[] {
  return groups.flatMap((group) => {
    const selected = group.candidates.find((row) => row.status === 'selected')
    const candidate = selected ?? group.candidates.find((row) => row.status === 'eligible')
    if (!candidate) return []
    const value = candidate.value == null ? '' : `${candidate.value}${candidate.unit === '%' ? '%' : candidate.unit ? ` ${candidate.unit}` : ''}`
    const title = group.title.replace(/\s*·\s*(不适用|已采用|未采用|待核实|未确认)\s*$/, '')
    const effective = candidate.effectiveFrom || candidate.effectiveTo
      ? `${candidate.effectiveFrom ?? '未标注'} 至 ${candidate.effectiveTo ?? '未标注'}`
      : null
    return [{
      groupId: group.groupId,
      title,
      chosen: selected
        ? `采用「${candidate.name}」${value}`
        : `未执行「${candidate.name}」${value}（本单未进入该待遇分支）`,
      executed: Boolean(selected),
      value,
      checks: candidate.checks.map((check) => ({ name: check.name, expected: check.expected, actual: check.actual, outcome: check.outcome })),
      source: candidate.source || null,
      version: candidate.version || null,
      effective,
      caliber: candidate.confirmationStatus || null,
    }]
  })
}

/** 正文只带本次采用的百分比；条件四列与封顶细节留在展开里。 */
function ratioSuffix(ratios: RatioDetail[]): string {
  const percents = ratios.filter((ratio) => ratio.executed && ratio.value.endsWith('%'))
  return percents.length ? `；本次比例 ${percents.map((ratio) => ratio.value).join('、')}` : ''
}

const factAmount = (data: PolicyQAFeeDecomposition, labels: string[]) =>
  data.settlementFacts?.items.find((item) => labels.includes(item.label))?.value ?? null

/** 大额支付：一句人话“基数×比例=支付”，封顶只在触及或有关键余额时补一句。 */
function bigPayExplanation(data: PolicyQAFeeDecomposition, value: string | null, ratios: RatioDetail[]): string | null {
  const base = findCalc(data, 'calc.deductible.copay_base')?.result
  const rate = ratios.find((ratio) => ratio.executed && ratio.value.endsWith('%'))?.value
  const pay = value ?? findCalc(data, 'calc.big_pay.capped')?.result
  if (!base || !rate) return null
  const cap = ratios.find((ratio) => ratio.executed && !ratio.value.endsWith('%'))
  const room = cap?.checks.map((check) => check.actual ?? '').join('').match(/剩余额度 ([\d.]+) 元/)?.[1]
  const touched = cap?.checks.some((check) => (check.actual ?? '').includes('已按剩余额度封顶'))
  const capNote = room ? `；年度封顶剩余额度 ${money(room)}${touched ? '，本次已按剩余额度封顶' : '，本次未触及'}` : ''
  return `本笔共付段基数 ${money(base)} × 基金比例 ${rate} ＝ ${money(pay)}${capNote}`
}

/** 大额个人自付：说明为什么这么多——基数减基金支付，并指出起付与分担比例。 */
function bigSelfPayExplanation(data: PolicyQAFeeDecomposition, value: string | null): string | null {
  const base = findCalc(data, 'calc.deductible.copay_base')?.result
  const pay = findCalc(data, 'calc.big_pay.capped')?.result
  if (!base || !pay) return null
  const deductible = factAmount(data, ['起付金额', '本次起付金额', '本次起付承担'])
  const parts = [`大额个人自付＝共付段基数 ${money(base)} － 基金支付 ${money(pay)}＝${money(value ?? pay)}`]
  if (deductible != null) parts.push(`本笔起付 ${money(deductible)}`)
  // 分担比例直接取自本笔基数与支付额（同一份已核对金额），不依赖比例组是否已在本行消费。
  const fundRate = percentOf(pay, base)
  const selfRate = percentOf(sumAmounts([base, `-${pay}`]), base)
  if (fundRate && selfRate) parts.push(`共付段基金与个人按 ${fundRate}／${selfRate} 分担`)
  return `${parts.join('；')}。`
}

function sameAmount(value: string | null, parts: (string | null)[]): boolean {
  const total = num(value)
  const units = parts.map(num)
  if (total === null || units.some((unit) => unit === null)) return false
  return Math.abs((units as number[]).reduce((sum, unit) => sum + unit, 0) - total) < 0.005
}

/** 包含关系（经验算成立才用）：自付一＝起付＋段内自付；个人支付＝自付一＋医保外/自付二。 */
function containmentExplanation(label: string, value: string | null, values: Map<string, string | null>): string | null {
  if (label === '自付一') {
    const start = values.get('起付金额') ?? null
    const segment = values.get('大额个人自付') ?? null
    const pool = values.get('统筹自付') ?? null
    if (pool !== null && sameAmount(value, [start, segment, pool])) {
      return `${hospital('自付一')}＝${hospital('起付金额')} ${money(start)} ＋ ${hospital('统筹自付')} ${money(pool)} ＋ ${hospital('大额个人自付')} ${money(segment)}＝${money(value)}`
    }
    if (sameAmount(value, [start, segment])) {
      return `${hospital('自付一')}＝${hospital('起付金额')} ${money(start)} ＋ ${hospital('大额个人自付')} ${money(segment)}＝${money(value)}`
    }
  }
  if (label === '个人支付总金额') {
    const first = values.get('自付一') ?? null
    const outside = values.get('医保范围外金额') ?? null
    if (outside !== null && num(outside) !== 0 && sameAmount(value, [first, outside])) {
      return `个人支付总金额＝医保内个人承担（自付一）${money(first)} ＋ 医保范围外 ${money(outside)}＝${money(value)}；账户与现金是支付方式，不重复相加`
    }
    const second = values.get('自付二') ?? null
    if (sameAmount(value, [first, second])) {
      return `${hospital('个人支付总金额')}＝${hospital('自付一')} ${money(first)} ＋ ${hospital('自付二')} ${money(second)}＝${money(value)}`
    }
  }
  return null
}

/** 自付二构成：按行区分“超限价自付”和“按比例先行自付”，并说明已含在医保外、另有多少全额自费。 */
function selfPay2Explanation(items: PolicyQAFeeItem[], total: string | null): { text: string; notes: string[] } | null {
  const contributors = items.filter((item) => positive(item.observedSelfPay2))
  if (!contributors.length) return null
  const limited = contributors.filter((item) =>
    item.divisionMethod === 'limit' || (positive(item.unitPriceLimit) && (num(item.unitPrice) ?? 0) > (num(item.unitPriceLimit) ?? 0)))
  const proportional = contributors.filter((item) => !limited.includes(item))
  const parts = [
    limited.length ? `超限价自付 ${money(sumAmounts(limited.map((item) => item.observedSelfPay2)))}` : null,
    proportional.length ? `按比例先行自付 ${money(sumAmounts(proportional.map((item) => item.observedSelfPay2)))}` : null,
  ].filter(Boolean)
  const outside = sumAmounts(items.map((item) => item.observedOutScope))
  const fullSelfPay = outside != null && total != null ? sumAmounts([outside, `-${total}`]) : null
  let text = `自付二＝${parts.join(' ＋ ')}＝${money(total) ?? '未取得'}`
  if (outside != null) {
    text += `；已包含在医保外 ${money(outside)}中`
    if (fullSelfPay != null && positive(fullSelfPay)) text += `，另有 ${money(fullSelfPay)}为全额自费项目`
  }
  const notes = limited.map((item) =>
    `${item.itemName || item.itemCode}：单价 ${money(item.unitPrice)} 超出${item.limitSource ?? '结算限价'} ${money(item.unitPriceLimit)}，超出部分 ${money(item.observedSelfPay2)} 计入自付二`)
  return { text, notes }
}

/** 起付金额：默认只给两句人话；完整函数算式进展开。 */
function deductibleExplanation(data: PolicyQAFeeDecomposition, fieldCode: string, value: string | null): { text: string | null; note: string | null } {
  const field = data.fields.find((item) => item.fieldCode === fieldCode)
  const refs = field?.calculationRefs ?? []
  const split = refs.map((ref) => findCalc(data, ref)).find((calc) => calc?.formula?.includes('起付'))
  const base = findCalc(data, 'calc.deductible.copay_base') ?? refs.map((ref) => findCalc(data, ref)).find((calc) => calc?.formula?.includes('报销基数'))
  const standard = split?.operands.find((operand) => operand.displayName.includes('标准'))
  const prior = split?.operands.find((operand) => operand.displayName.includes('累计') || operand.displayName.includes('已交'))
  if (!split) return { text: null, note: null }
  const special = data.settlementFacts?.chain === 'special'
  const head = [
    standard ? `${special ? '本结算周期起付标准' : '年度起付标准'} ${standard.value} 元` : null,
    prior ? `${special ? '交易前已承担起付' : '交易前累计'} ${prior.value} 元` : null,
  ].filter(Boolean).join('，')
  const inScope = base?.operands[0]?.value ?? null
  const text = [
    `${head ? `${head}；` : ''}本次承担起付 ${money(value)}。`,
    inScope && base ? `医保内 ${money(inScope)} － 起付 ${money(value)} ＝ 报销基数 ${money(base.result)}。` : null,
  ].filter(Boolean).join(' ')
  return { text, note: split.formula ?? null }
}

/** 职工门特：把"在职基础档 × 退休折算系数 = 本段个人比例"讲清楚。 */
function segmentedRatioExplanation(data: PolicyQAFeeDecomposition, fieldCode: string, ratios: RatioDetail[]): string | null {
  const field = data.fields.find((item) => item.fieldCode === fieldCode)
  const refs = field?.calculationRefs ?? []
  const selfRatio = refs.filter((ref) => ref.endsWith('.self_ratio')).map((ref) => findCalc(data, ref)).find((calc) => calc?.result)
  if (!selfRatio?.result) return null
  const baseRate = ratios.find((ratio) => ratio.title.includes('基础比例') || ratio.title.includes('在职自付'))
  const factor = ratios.find((ratio) => ratio.title.includes('系数'))
  if (!baseRate || !factor) return null
  const finalSelf = percentOf(selfRatio.result)
  const selfValue = num(selfRatio.result)
  const fundShare = selfValue == null ? null : percentOf(String(1 - selfValue))
  const base = refs.filter((ref) => ref.endsWith('.base')).map((ref) => findCalc(data, ref)).find((calc) => calc?.result)
  const pay = findCalc(data, refs.at(-1))?.result
  const baseRateValue = baseRate.chosen.replace(/^.*」\s*/, '')
  const factorValue = factor.chosen.replace(/^.*」\s*/, '')
  const tail = base?.result && fundShare
    ? `；报销基数 ${money(base.result)}×${fundShare}${pay ? `＝${money(pay)}` : ''}`
    : ''
  return `本段个人比例＝在职自付基础 ${baseRateValue} × 退休折算系数 ${factorValue} ＝ ${finalSelf ?? '未取得'}；基金比例 ${fundShare ?? '未取得'}${tail}`
}

/** 展示文本里的多位小数统一到两位（只影响显示，不改数据源）。 */
export function normalizeAmountText(text: string): string {
  return text.replace(/-?\d+\.\d{3,}/g, (match) => Number(match).toFixed(2))
}

function sumExplanation(label: string, items: PolicyQAFeeItem[], pick: (item: PolicyQAFeeItem) => string | null | undefined, total: string | null): string {
  const parts = items.map((item) => `${item.itemName || item.itemCode} ${money(pick(item)) ?? '未取得'}`)
  return parts.length ? `${label}＝${parts.join(' ＋ ')}＝${money(total) ?? '未取得'}` : `${label}：本次未返回交易明细`
}

/** 按医院结算单顺序给出金额行：明细合计 → 起付/基金/补助 → 个人支付 → 支付方式。 */
export function buildSummaryRows(data: PolicyQAFeeDecomposition): { rows: SummaryRow[]; payments: SummaryRow[] } {
  if (data.settlementFacts?.displayTemplate) return buildConfiguredSummaryRows(data)
  if (requiresSettlementTemplate(data)) return { rows: [], payments: [] }
  const items = data.feeItems ?? []
  const facts = data.settlementFacts
  const rows: SummaryRow[] = []
  const used = new Set<string>()
  const hasDetails = items.length > 0

  for (const aggregate of hasDetails ? AGGREGATES : []) {
    const total = sumAmounts(items.map(aggregate.pick))
    const base = sumExplanation(aggregate.label, items, aggregate.pick, total)
    const breakdown = aggregate.key === 'self2' ? selfPay2Explanation(items, total) : null
    rows.push({
      key: `sum.${aggregate.key}`,
      label: hospital(aggregate.label),
      value: total,
      explanation: breakdown?.text ?? base,
      group: ROW_GROUP[aggregate.label] ?? '费用构成',
      indent: aggregate.label === '自付二',
      notes: breakdown?.notes ?? [],
      ratios: [],
      expandLabel: breakdown?.notes.length ? '自付二构成' : null,
    })
  }

  const factValue = new Map<string, string | null>()
  for (const fact of facts?.items ?? []) factValue.set(LABEL_ALIAS[fact.label] ?? fact.label, fact.value)

  const seen = new Set<string>()
  const pending: SummaryRow[] = []
  for (const fact of facts?.items ?? []) {
    const label = LABEL_ALIAS[fact.label] ?? fact.label
    if ((hasDetails && AGGREGATES.some((aggregate) => aggregate.matches(fact.label))) || label === '个人支付总金额' || seen.has(label)) continue
    seen.add(label)
    const field = findField(data, label)
    const fieldCode = field?.fieldCode ?? null
    const groups = rowRatioGroups(data, fieldCode, label, used)
    const ratios = ratioDetails(groups)
    const zero = isZero(fact.value)
    // 解释边界：后端标记 explainable=false 且非账面恒等式的金额，不展开计算原因。
    const settlementFact = label === '退役医疗费支付'
    const gated = !settlementFact && field != null && field.explainable === false && field.checkType !== 'identity_check'

    let explanation: string | null = null
    const notes: string[] = []
    if (settlementFact) {
      explanation = fact.value == null ? null : '按本单结算记录列示。'
    } else if (label === '基金合计') {
      const parts = FUND_COMPONENTS.filter((name) => factValue.has(name)).map((name) => [name, factValue.get(name)] as const)
      const total = sumAmounts(parts.map(([, value]) => value))
      const sum = parts.length > 1 && total !== null && decimalUnits(total) === decimalUnits(fact.value)
        ? `${parts.map(([name, value]) => `${name} ${money(value)}`).join(' ＋ ')}＝${money(fact.value) ?? '未取得'}`
        : null
      const formula = fieldCode && field?.checkStatus === 'matched' ? lastFormula(data, fieldCode) : null
      if (formula) { explanation = formula; notes.push(formula) }
      else if (sum) explanation = sum
    } else if (gated) {
      explanation = zero ? zeroReason(data, fieldCode, label) : null
    } else if (label === '起付金额' && fieldCode) {
      const composed = deductibleExplanation(data, fieldCode, fact.value)
      explanation = composed.text
      if (composed.note) notes.push(composed.note)
    } else if (label === '大额支付' && fieldCode) {
      explanation = bigPayExplanation(data, fact.value, ratios) ?? rowExplanation(data, fieldCode, label)
    } else if (label === '大额个人自付' && fieldCode) {
      explanation = bigSelfPayExplanation(data, fact.value) ?? rowExplanation(data, fieldCode, label)
    } else {
      const segmented = fieldCode ? segmentedRatioExplanation(data, fieldCode, ratios) : null
      explanation = containmentExplanation(label, fact.value, factValue)
        ?? rowExplanation(data, fieldCode, label)
      if (segmented) explanation = segmented
      if (!explanation && zero) explanation = zeroReason(data, fieldCode, label)
    }
    // 写了金额解释就带上采用的比例；零金额行不突出比例，比例只在展开里看。
    if (explanation && !zero && ratios.length && !['起付金额', '大额支付', '大额个人自付'].includes(label)) explanation = `${explanation}${ratioSuffix(ratios)}`
    if (gated && !zero) {
      rows.push({ key: `fact.${label}`, label: hospital(label), value: fact.value, explanation: null, group: ROW_GROUP[label] ?? '其他', notes: [], ratios: [], expandLabel: null })
      continue
    }
    pending.push({
      key: `fact.${label}`,
      label: hospital(label),
      value: fact.value,
      explanation,
      group: ROW_GROUP[label] ?? '其他',
      indent: label === '自付二',
      emphasis: label === '自付一' || label === '个人支付总金额',
      notes,
      ratios,
      expandLabel: label === '起付金额' && notes.length ? '起付标准依据' : ratios.length ? '比例依据' : notes.length ? '计算依据' : null,
    })
  }

  // 个人支付总金额：优先用分解结果的最终个人承担，其次原单，再其次账户+现金。
  const personal = findField(data, '个人支付总金额')
  const payments: SummaryRow[] = (facts?.paymentItems ?? []).map((item) => ({
    key: `pay.${item.label}`, label: hospital(item.label), value: item.value, explanation: null,
    group: '支付方式', notes: [], ratios: [], expandLabel: null,
  }))
  const channel = payments.map((item) => `${item.label} ${money(item.value) ?? '未取得'}`).join(' ＋ ')
  const personalValue = personal?.observedAmount ?? facts?.items.find((item) => item.label === '个人支付总金额')?.value ?? sumAmounts(payments.map((item) => item.value))
  const personalExplanation = containmentExplanation('个人支付总金额', personalValue, factValue)
    ?? rowExplanation(data, personal?.fieldCode ?? null, '个人支付总金额')
    ?? (channel ? `${channel}＝${money(sumAmounts(payments.map((item) => item.value))) ?? '未取得'}` : null)
  rows.push(
    ...pending,
    {
      key: 'sum.personal_total', label: '个人支付总金额', value: personalValue, explanation: personalExplanation,
      group: '个人支付合计', emphasis: true, notes: channel ? [`支付方式：${channel}`] : [], ratios: [],
      expandLabel: channel ? '支付方式' : null,
    },
  )

  rows.sort((left, right) => GROUP_ORDER.indexOf(left.group as never) - GROUP_ORDER.indexOf(right.group as never))
  return { rows, payments }
}

/** 新契约只按模板的字段代码取解释，名称、位置、金额均不再用别名或明细合计替换。 */
/** 交易信息按费用分解算法顺序分组（模板只提供名称与取值，不决定顺序）。 */
const STAGE_OF_KEY: Record<string, string> = {
  fee_all: '费用构成', fee_in: '费用构成', fee_out: '费用构成',
  normal_in: '费用构成', normal_out: '费用构成', special_in: '费用构成', special_out: '费用构成',
  self_pay_1: '费用构成', self_pay_2: '费用构成', beyond_cap: '费用构成',
  first_pay: '起付',
  pool_pay: '统筹与大额', pool_self: '统筹与大额', big_pay: '统筹与大额', big_self_pay: '统筹与大额',
  fund_total: '统筹与大额',
  retire_pay: '补助', military_pay: '补助', official_pay: '补助', retire_officer_pay: '补助',
  big_ill_pay: '二次保障', aid_pay: '二次保障', feein_db: '二次保障', feeout_db: '二次保障',
  feein_aid: '二次保障', feeout_aid: '二次保障',
  secondary_base: '二次保障', secondary_big_ill: '二次保障', secondary_after_db: '二次保障',
  secondary_civil: '二次保障', secondary_person: '二次保障',
  personal_total: '个人负担',
  account_pay: '支付方式', cash_pay: '支付方式',
}
const STAGE_ORDER = ['费用构成', '起付', '统筹与大额', '补助', '二次保障', '个人负担', '支付方式', '医院定额清算', '其他']

function buildConfiguredSummaryRows(data: PolicyQAFeeDecomposition): { rows: SummaryRow[]; payments: SummaryRow[] } {
  const template = data.settlementFacts!.displayTemplate!
  const rows = template.fields.filter(item => item.section !== 'basic').map(item => {
    const field = item.fieldCode ? data.fields.find(field => field.fieldCode === item.fieldCode) : null
    // 模板未映射原单列（如个人支付总金额）时，回落到同名算法字段，保证右栏不缺行。
    const value = item.value ?? (item.key === 'personal_total' ? field?.observedAmount ?? null : null)
    const matched = field != null && value != null && field.observedAmount != null
      && decimalUnits(value) === decimalUnits(field.observedAmount)
    const eligible = matched && (field.explainable === true || field.checkType === 'identity_check' && field.checkStatus === 'matched')
    const refs = new Set(field?.calculationRefs ?? [])
    const groups = eligible ? (data.ruleChoices ?? []).filter(group => group.fieldRefs?.includes(field!.fieldCode)
      || group.calculationRefs.some(ref => refs.has(ref))) : []
    const ratios = ratioDetails(groups)
    const notes: string[] = []
    let explanation: string | null = null
    if (item.key === 'self_pay_1') {
      const parts = data.calculations.find((calc) => calc.calculationId === 'calc.self_pay_1.parts')
      if (parts?.formula) notes.push(`计算构成（非原单记录）：${parts.formula}`)
    }
    if (item.key === 'big_ill_pay' || item.key === 'aid_pay') {
      const subCodes = item.key === 'big_ill_pay'
        ? ['FEEIN_DB_PAY', 'FEEOUT_DB_PAY'] : ['FEEIN_MAF_PAY', 'FEEOUT_MAF_PAY']
      for (const code of subCodes) {
        const sub = data.fields.find((field) => field.fieldCode === code)
        if (sub?.observedAmount != null) notes.push(`${sub.label} ${money(sub.observedAmount)}`)
      }
    }
    if (eligible && !['account_pay', 'cash_pay'].includes(item.key)) {
      if (item.key === 'first_pay') {
        const deductible = deductibleExplanation(data, field!.fieldCode, value)
        explanation = deductible.text
        if (deductible.note) notes.push(deductible.note)
      } else if (item.key === 'big_pay' && data.settlementFacts?.chain === 'outpatient') {
        explanation = bigPayExplanation(data, value, ratios)
      } else if (item.key === 'big_self_pay') {
        explanation = (data.settlementFacts?.chain === 'outpatient' ? bigSelfPayExplanation(data, value) : null)
          ?? rowExplanation(data, field!.fieldCode, item.semanticLabel ?? item.label)
        if (explanation) notes.push('按“报销基数−已取整基金支付”计算，不另按比例单独取整。')
      } else if (item.key === 'self_pay_2') {
        const items = data.feeItems ?? []
        const total = sumAmounts(items.map(item => item.observedSelfPay2))
        if (total != null && decimalUnits(total) === decimalUnits(value)) {
          const breakdown = selfPay2Explanation(items, value)
          explanation = breakdown?.text ?? null
          notes.push(...breakdown?.notes ?? [])
        }
      }
      explanation ??= rowExplanation(data, field!.fieldCode, item.semanticLabel ?? item.label)
    }
    if (explanation && field?.label !== item.label) explanation = explanation.replaceAll(field!.label, item.label)
    return {
      key: item.key, label: item.label, value,
      explanation: explanation == null ? null : normalizeAmountText(explanation),
      group: item.section === 'hospital' ? '医院定额清算' : (STAGE_OF_KEY[item.key] ?? '其他'),
      notes: notes.map(normalizeAmountText), ratios, expandLabel: ratios.length ? '比例依据' : notes.length ? '计算依据' : null,
    }
  })
  // 二次保障阶段：大病前合规基数 → 大病后剩余 → 救助后个人（缺记录时不补行）
  const stageRows: Array<[string, string, string]> = [
    ['secondary_base', '大病前合规基数', 'calc.secondary.current_base'],
    ['secondary_after_db', '大病后合规剩余', 'calc.secondary.remaining_base'],
    ['secondary_person', '救助后个人支付', 'calc.secondary.person_payable'],
  ]
  const presentKeys = new Set(rows.map((row) => row.key))
  for (const [key, label, calcId] of stageRows) {
    const calc = data.calculations.find((item) => item.calculationId === calcId)
    if (calc?.result == null || presentKeys.has(key)) continue
    rows.push({
      key, label, value: calc.result,
      explanation: calc.formula == null ? null : normalizeAmountText(calc.formula),
      group: '二次保障', notes: [], ratios: [], expandLabel: null,
    })
  }
  const payments = rows.filter(row => ['account_pay', 'cash_pay'].includes(row.key))
  const ordered = rows
    .filter(row => !['account_pay', 'cash_pay'].includes(row.key))
    .sort((left, right) => STAGE_ORDER.indexOf(left.group) - STAGE_ORDER.indexOf(right.group))
  return { rows: ordered, payments }
}

function rowExplanation(data: PolicyQAFeeDecomposition, fieldCode: string | null, label: string): string | null {
  if (!fieldCode) return null
  const field = data.fields.find((item) => item.fieldCode === fieldCode)
  if (field?.explainable === false && field.checkType !== 'identity_check') return null
  if (field?.checkType === 'identity_check' && field.checkStatus !== 'matched') return null
  const formula = fieldFormula(data, field ?? null)
  if (formula) return formula
  const unmet = unmetConditions(data, fieldCode, label)
  if (unmet) return unmet
  return field?.brief ?? field?.explanationReason ?? null
}

/** 本行实际采用的限价名称：明细结算时限价优先，其次目录单价限额。 */
function limitLabel(item: PolicyQAFeeItem): string {
  if (item.limitSource?.includes('结算时限价') || positive(item.settlementPriceLimit)) return '结算时限价'
  if (item.limitSource?.includes('目录')) return '目录单价限额'
  return '限价'
}

/** 超出限价的金额（单价差×数量）；缺数量时不展示。 */
function excessOverLimit(item: PolicyQAFeeItem): string | null {
  const price = num(item.unitPrice), limit = num(item.unitPriceLimit), count = num(item.quantity)
  if (price == null || limit == null || count == null || price <= limit) return null
  return ((price - limit) * count).toFixed(2)
}

/** 交易明细一句关键原因：把目录属性、限价、本次采用的比例和金额结果串起来。 */
export function feeItemReason(item: PolicyQAFeeItem): string | null {
  if (item.explainable === false) return null
  const parts: string[] = []
  if (item.classificationLabel) parts.push(item.classificationLabel)
  if (item.centralizedProcurement === true) parts.push('集采药')
  if (item.unitPrice && positive(item.unitPriceLimit)) {
    const over = (num(item.unitPrice) ?? 0) > (num(item.unitPriceLimit) ?? 0)
    parts.push(`单价 ${item.unitPrice} ${over ? '高于' : '不高于'}${limitLabel(item)} ${item.unitPriceLimit}`)
  }
  const ratio = percentOf(item.selfPayRatio)
  if (ratio && (num(item.selfPayRatio) ?? 0) > 0) parts.push(`按 ${ratio} 计自付二`)
  else if (item.divisionMethod === 'full_in') parts.push('全额纳入医保内')
  else if (item.divisionMethod === 'full_out') parts.push('全额医保外')
  else if (ratio) parts.push(`目录自付比例 ${ratio}`)
  const self2 = money(item.observedSelfPay2)
  const inScope = money(item.observedInScope)
  if (self2 || inScope) parts.push(`自付二 ${self2 ?? '未取得'}、医保内 ${inScope ?? '未取得'}`)
  return parts.length ? parts.join('；') : null
}

/** 交易明细完整解释：方式 → 比例 → 作用基数 → 结果，逐段可读。 */
export function feeItemExplanation(item: PolicyQAFeeItem): string | null {
  if (item.explainable === false) return null
  const steps: string[] = []
  const catalog = [item.classificationLabel, item.centralizedProcurement === true ? '集采药品' : null].filter(Boolean)
  if (catalog.length) steps.push(catalog.join('，'))
  if (item.unitPrice && positive(item.unitPriceLimit)) {
    const over = (num(item.unitPrice) ?? 0) > (num(item.unitPriceLimit) ?? 0)
    const label = limitLabel(item)
    if (over) {
      const excess = excessOverLimit(item)
      steps.push(`按本行${label} ${item.unitPriceLimit} 元纳入医保内${excess ? `；超出 ${excess} 元计入自付二` : '；超出部分计入自付二'}`)
    } else {
      steps.push(`本行单价 ${item.unitPrice} 元未超过${label} ${item.unitPriceLimit} 元，按本行类别划分`)
    }
  }
  const ratio = percentOf(item.selfPayRatio)
  if (ratio) {
    const source = item.ratioSource === '明细结算时比例（正值优先）'
      ? '明细结算时比例'
      : item.ratioSource === '命中目录的自付比例' ? '命中目录的自付比例' : item.ratioSource
    steps.push(`采用${source ?? '自付比例'} ${ratio}，作用于整笔费用 ${money(item.totalFee) ?? '未取得'}`)
  } else if (item.divisionMethod === 'full_in') {
    steps.push(`全额纳入医保内，作用于整笔费用 ${money(item.totalFee) ?? '未取得'}`)
  } else if (item.divisionMethod === 'full_out') {
    steps.push(`全额计入医保外，作用于整笔费用 ${money(item.totalFee) ?? '未取得'}`)
  }
  const result = [
    `自付二 ${money(item.observedSelfPay2) ?? '未取得'}`,
    `医保内 ${money(item.observedInScope) ?? '未取得'}`,
    `医保外 ${money(item.observedOutScope) ?? '未取得'}`,
  ].join('、')
  steps.push(result)
  return steps.join('；')
}

export { money as formatMoney }
