/**
 * 两单费用分解对比（Issue #87）。
 *
 * 门诊 / 门诊特殊病（门特）不属于住院语义模型，`settlement-explanation?compare_with=`
 * 无法解释这两类单；因此四类门诊链路的两单对比直接基于两张 `/bill` 的
 * 费用构成与费用明细做确定性核对：
 * - 金额逐单呈现，不做加总；
 * - 只陈述账面字段差异，不做政策归因；
 * - 不对结算结果作合规判断，政策依据缺失如实声明。
 */

import type { PolicyQAChatMessage } from '@/lib/policy-qa-session'
import {
  formatAmount,
  type SettlementBillDTO,
  type SettlementBillFeeItemDTO,
  type SettlementListItemDTO,
} from '@/lib/policy-qa-settlement-list'

interface BuildBillCompareInput {
  older: SettlementListItemDTO
  newer: SettlementListItemDTO
  olderBill: SettlementBillDTO
  newerBill: SettlementBillDTO
}

const PERSONAL_LABELS = ['个人支付总金额', '个人总支付']
const CASH_LABELS = ['当次个人现金支付金额']
const ACCOUNT_LABELS = ['当次个人帐户支付金额']
const TOTAL_LABELS = ['费用总金额', '住院总费用']

/** 已在“个人支付”段落单独呈现，不再重复进构成差异表 */
const PERSONAL_SECTION_LABELS = new Set([
  ...PERSONAL_LABELS,
  ...CASH_LABELS,
  ...ACCOUNT_LABELS,
])

/** 结算解释用户最关心的字段优先展示，其余按差额绝对值排序 */
const PREFERRED_LABELS = [
  '费用总金额',
  '住院总费用',
  '起付金额',
  '起付线',
  '统筹基金支付',
  '统筹支付',
  '当次门诊大额基金支付金额',
  '大额支付',
  '个人支付自付（一）',
  '统筹自付',
  '大额自付金额',
  '补充保险支付金额',
  '残疾军人补助支付金额',
  '单位补充医疗保险（原公疗）支付金额',
  '大病支付',
  '当次个人帐户支付金额',
]

const MAX_DIFF_ROWS = 12
const MAX_SHARED_ITEMS = 5

function parseMoney(value: string | null | undefined): number | null {
  if (value == null) return null
  const normalized = value.replace(/,/g, '').trim()
  if (!normalized) return null
  const parsed = Number(normalized)
  return Number.isFinite(parsed) ? parsed : null
}

function moneyText(value: number | null | undefined): string {
  return value == null ? '—' : formatAmount(value)
}

function fieldAmountByLabel(bill: SettlementBillDTO, labels: string[]): string | null {
  for (const label of labels) {
    const hit = bill.fields.find((field) => field.label === label)
    if (hit?.amount != null) return hit.amount
  }
  return null
}

interface PaySummary {
  personal: number | null
  cash: number | null
  account: number | null
}

function summarizePay(bill: SettlementBillDTO): PaySummary {
  const cash = parseMoney(fieldAmountByLabel(bill, CASH_LABELS))
  const account = parseMoney(fieldAmountByLabel(bill, ACCOUNT_LABELS))
  let personal = parseMoney(fieldAmountByLabel(bill, PERSONAL_LABELS))
  // 部分链路只给现金/账户分项，未落个人支付合计时按两项相加（仅当两项均在）
  if (personal == null && cash != null && account != null) personal = cash + account
  return { personal, cash, account }
}

function billTotal(bill: SettlementBillDTO): number | null {
  const fromFields = parseMoney(fieldAmountByLabel(bill, TOTAL_LABELS))
  return fromFields
}

function settlementLabel(item: SettlementListItemDTO, bill: SettlementBillDTO): string {
  const date = item.settlementDate || bill.settlementDate || '日期待定'
  const service = item.serviceType || bill.serviceType || '类型待定'
  const total = billTotal(bill)
  const totalPart = total == null ? '' : `，总费用 ${moneyText(total)} 元`
  return `${item.settlementId}（${date}，${service}${totalPart}）`
}

function preferredIndex(label: string): number {
  const index = PREFERRED_LABELS.indexOf(label)
  return index === -1 ? PREFERRED_LABELS.length : index
}

interface DiffRow {
  label: string
  older: number
  newer: number
  diff: number
}

function buildDiffRows(olderBill: SettlementBillDTO, newerBill: SettlementBillDTO): DiffRow[] {
  const newerByLabel = new Map(newerBill.fields.map((field) => [field.label, field]))
  const rows: DiffRow[] = []
  for (const field of olderBill.fields) {
    if (PERSONAL_SECTION_LABELS.has(field.label)) continue
    const counterpart = newerByLabel.get(field.label)
    if (!counterpart) continue
    const older = parseMoney(field.amount)
    const newer = parseMoney(counterpart.amount)
    if (older == null || newer == null) continue
    const diff = newer - older
    if (Math.abs(diff) < 0.005) continue
    rows.push({ label: field.label, older, newer, diff })
  }
  rows.sort((a, b) => {
    const byPreferred = preferredIndex(a.label) - preferredIndex(b.label)
    return byPreferred !== 0 ? byPreferred : Math.abs(b.diff) - Math.abs(a.diff)
  })
  return rows.slice(0, MAX_DIFF_ROWS)
}

function diffRowText(row: DiffRow, olderId: string, newerId: string): string {
  const direction = row.diff > 0 ? '多' : '少'
  return `${row.label}：${olderId} ${moneyText(row.older)} 元 → ${newerId} ${moneyText(row.newer)} 元（${newerId} 比 ${olderId} ${direction} ${moneyText(Math.abs(row.diff))} 元）`
}

function itemKey(item: SettlementBillFeeItemDTO): string {
  const code = item.itemCode?.trim()
  if (code) return code
  const name = item.itemName?.trim()
  return name ? `name:${name}` : ''
}

function itemSummary(item: SettlementBillFeeItemDTO): string {
  const quantity = item.quantity?.trim() || '—'
  const unitPrice = parseMoney(item.unitPrice)
  const total = parseMoney(item.totalAmount)
  return `数量 ${quantity}、单价 ${moneyText(unitPrice)} 元、金额 ${moneyText(total)} 元`
}

function sharedItemFlags(older: SettlementBillFeeItemDTO, newer: SettlementBillFeeItemDTO): string[] {
  const flags: string[] = []
  const olderPrice = parseMoney(older.unitPrice)
  const newerPrice = parseMoney(newer.unitPrice)
  if (olderPrice != null && newerPrice != null && Math.abs(olderPrice - newerPrice) >= 0.005) {
    flags.push('两次单价不同，需核对规格或收费口径')
  }
  const olderQuantity = parseMoney(older.quantity)
  const newerQuantity = parseMoney(newer.quantity)
  if (olderQuantity != null && newerQuantity != null && Math.abs(olderQuantity - newerQuantity) >= 0.005) {
    flags.push('数量不同')
  }
  const olderAmount = parseMoney(older.totalAmount)
  const newerAmount = parseMoney(newer.totalAmount)
  if (olderAmount != null && newerAmount != null && Math.abs(olderAmount - newerAmount) >= 0.005) {
    flags.push(`金额相差 ${moneyText(Math.abs(newerAmount - olderAmount))} 元`)
  }
  return flags
}

function sharedItemKeys(olderBill: SettlementBillDTO, newerBill: SettlementBillDTO): SettlementBillFeeItemDTO[] {
  const newerByKey = new Map<string, SettlementBillFeeItemDTO>()
  for (const item of newerBill.feeItems) {
    const key = itemKey(item)
    if (key && !newerByKey.has(key)) newerByKey.set(key, item)
  }
  const shared: SettlementBillFeeItemDTO[] = []
  const seen = new Set<string>()
  for (const item of olderBill.feeItems) {
    const key = itemKey(item)
    if (!key || seen.has(key) || !newerByKey.has(key)) continue
    seen.add(key)
    shared.push(item)
  }
  return shared
}

export function buildBillCompareMessage({
  older,
  newer,
  olderBill,
  newerBill,
}: BuildBillCompareInput): PolicyQAChatMessage {
  const olderId = older.settlementId
  const newerId = newer.settlementId
  const olderPay = summarizePay(olderBill)
  const newerPay = summarizePay(newerBill)
  const uncertainties: string[] = []

  const sections: string[] = []
  sections.push(
    `以较早的结算单 ${settlementLabel(older, olderBill)}为基准，与结算单 ${settlementLabel(newer, newerBill)}逐单对比（金额逐单呈现，不做加总）：`,
  )

  // ── 个人支付：用户最常问的差异点，先给出两张单各自的构成 ──
  if (olderPay.personal != null && newerPay.personal != null) {
    const lines = ['【个人支付】']
    for (const [id, pay] of [
      [olderId, olderPay],
      [newerId, newerPay],
    ] as const) {
      const parts = [`个人支付总金额 ${moneyText(pay.personal)} 元`]
      if (pay.cash != null) parts.push(`个人现金 ${moneyText(pay.cash)} 元`)
      if (pay.account != null) parts.push(`个人账户 ${moneyText(pay.account)} 元`)
      lines.push(`${id}：${parts.join('；')}`)
    }
    const gap = newerPay.personal - olderPay.personal
    if (Math.abs(gap) >= 0.005) {
      lines.push(
        `个人支付相差 ${moneyText(Math.abs(gap))} 元（${newerId} 比 ${olderId} ${gap > 0 ? '多' : '少'} ${moneyText(Math.abs(gap))} 元）。`,
      )
    } else {
      lines.push('两张单个人支付总金额一致。')
    }
    sections.push(lines.join('\n'))
  } else {
    uncertainties.push('两张单缺少可比较的“个人支付总金额”，未比较个人支付差异。')
  }

  // ── 费用构成字段差异（同名字段逐项对比） ──
  const diffRows = buildDiffRows(olderBill, newerBill)
  if (diffRows.length > 0) {
    sections.push(
      ['【费用构成差异】', ...diffRows.map((row) => diffRowText(row, olderId, newerId))].join('\n'),
    )
  } else if (olderBill.fields.length > 0 && newerBill.fields.length > 0) {
    const hasCommonLabel = olderBill.fields.some((field) =>
      newerBill.fields.some((counterpart) => counterpart.label === field.label),
    )
    sections.push(
      hasCommonLabel
        ? '【费用构成差异】\n两张单同名字段的金额一致，未发现构成差异。'
        : '【费用构成差异】\n两张单的费用字段口径不同（如住院与门诊），未做字段级差异对比。',
    )
  }

  // ── 相同收费项目：按项目编码匹配（缺失时退回项目名称） ──
  const missingFeeItems = [
    olderBill.feeItemsState === 'missing' ? olderId : null,
    newerBill.feeItemsState === 'missing' ? newerId : null,
  ].filter((value): value is string => value != null)
  if (missingFeeItems.length > 0) {
    uncertainties.push(`结算单 ${missingFeeItems.join('、')} 的费用明细缺失，未做项目级对比。`)
  } else {
    const shared = sharedItemKeys(olderBill, newerBill)
    if (shared.length === 0) {
      sections.push('【相同的收费项目】\n两张单未发现相同的收费项目（按项目编码匹配），以上仅比较费用构成。')
    } else {
      const newerByKey = new Map<string, SettlementBillFeeItemDTO>()
      for (const item of newerBill.feeItems) {
        const key = itemKey(item)
        if (key && !newerByKey.has(key)) newerByKey.set(key, item)
      }
      const lines = ['【相同的收费项目】']
      for (const olderItem of shared.slice(0, MAX_SHARED_ITEMS)) {
        const newerItem = newerByKey.get(itemKey(olderItem))
        if (!newerItem) continue
        const name = olderItem.itemName || newerItem.itemName || olderItem.itemCode || '未命名项目'
        const flags = sharedItemFlags(olderItem, newerItem)
        const flagText = flags.length > 0 ? `（${flags.join('；')}）` : ''
        lines.push(
          `${name}：${olderId} ${itemSummary(olderItem)}；${newerId} ${itemSummary(newerItem)}${flagText}`,
        )
      }
      if (shared.length > MAX_SHARED_ITEMS) {
        lines.push(`（仅列出前 ${MAX_SHARED_ITEMS} 个相同项目，共 ${shared.length} 个）`)
      }
      sections.push(lines.join('\n'))
    }
  }

  // ── 说明：只做账面核对，不作政策归因与合规判断 ──
  const focusLabels = diffRows.slice(0, 3).map((row) => row.label)
  const notes = ['【说明】']
  if (olderPay.personal != null && newerPay.personal != null && focusLabels.length > 0) {
    notes.push(`从账面字段看，两张单的差异主要集中在：${focusLabels.join('、')}。`)
  }
  notes.push('以上为两张结算单的费用分解核对，未做政策归因，也不对结算结果作合规判断。')
  notes.push('未检索到可展示的政策依据；如需解释起付累计、基金分段等政策原因，可升级医保办核实。')
  sections.push(notes.join('\n'))

  const warnings = Array.from(new Set([...olderBill.warnings, ...newerBill.warnings]))
  if (!uncertainties.includes('未检索到可展示的政策依据，个人支付差异未做政策归因。')) {
    uncertainties.push('未检索到可展示的政策依据，个人支付差异未做政策归因。')
  }

  return {
    role: 'assistant',
    content: sections.join('\n\n'),
    answerStatus: 'partial',
    warnings,
    uncertainties,
  }
}
