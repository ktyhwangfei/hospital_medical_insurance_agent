'use client'

import { Fragment, useState } from 'react'
import type { PolicyQAFeeItem } from '@/lib/policy-qa-stream'
import { percentOf } from '@/lib/fee-explanation-numbers'
import { formatDecimal2 } from '@/lib/policy-qa-settlement-list'

const amount = (value: string | null | undefined) => value == null ? '未取得' : formatDecimal2(value)
const outcome: Record<string, string> = { true: '成立', false: '不成立', unknown: '未取得', blocked: '已阻断', not_applicable: '不适用' }

function division(item: PolicyQAFeeItem) {
  const self = percentOf(item.selfPayRatio)
  if (item.divisionMethod === 'limit') return self ? `${item.ratioBasis ?? '限价内金额'}先行自付 ${self}` : '按单价限额划分'
  if (item.divisionMethod === 'ratio') return self ? `${item.ratioBasis ?? '本行费用金额'}先行自付 ${self}` : `纳入医保范围内 ${percentOf(item.includedRatio) ?? '未取得'}`
  return ({ full_in: '全额纳入医保范围内', full_out: '全额医保范围外', settlement_override: '本单全额个人承担', unknown: '划分规则未取得' })[item.divisionMethod ?? 'unknown'] ?? '划分规则未取得'
}

/** 目录属性：药品用目录收费类别；非药品用"项目类别 · 收费项目等级(sfxmdj)"，无等级时用后端已执行的目录/限价分支。 */
function catalogAttribute(item: PolicyQAFeeItem): { label: string; code: string | null } {
  const kind = item.itemType && item.itemType !== '药品' ? item.itemType : null
  const combine = (label: string) => kind ? `${kind} · ${label}` : label
  if (item.classificationLabel) return { label: combine(item.classificationLabel), code: item.classificationCode ?? null }
  const taken = (codes: string[]) => item.decisionPath?.find((step) => codes.includes(step.code) && step.outcome === 'true')
  if (taken(['material_price_limit'])) return { label: combine('限内纳入、超限自担'), code: null }
  const included = percentOf(item.includedRatio)
  if (taken(['material_threshold']) && included) return { label: combine(`按纳入比例 ${included} 纳入`), code: null }
  const matched = taken(['catalog_match'])
  // 目录名称本身已表明类别（如“医用材料目录”），不再重复前缀项目类别。
  if (matched) return { label: matched.label.replace(/匹配$/, ''), code: null }
  // 目录等级与划分分支都未取得时，只报项目类别，不声称目录分类。
  return { label: kind ?? '目录分类未取得', code: null }
}

function priceComparison(item: PolicyQAFeeItem) {
  const check = item.decisionPath?.filter((step) => ['ncp_price_le_limit', 'drug_price_le_limit', 'unit_price_le_bzjg', 'service_price_le_limit', 'unit_price_over_limit', 'material_price_limit'].includes(step.code)).at(-1)
  if (!check || !['true', 'false'].includes(check.outcome)) return null
  return (check.operator === 'gt' ? check.outcome === 'true' : check.outcome === 'false') ? '高于限价' : '未高于限价'
}

function Reconciliation({ item }: { item: PolicyQAFeeItem }) {
  const checks = item.reconciliations?.length ? item.reconciliations : [
    { label: '医保范围内', observed: item.observedInScope, calculated: item.calculatedInScope, difference: null },
    { label: '医保范围外', observed: item.observedOutScope, calculated: item.calculatedOutScope, difference: null },
    { label: '先行自付', observed: item.observedSelfPay2, calculated: item.calculatedSelfPay2, difference: null },
  ]
  return <table className="w-full text-left" aria-label="逐项金额核对"><thead><tr>{['金额项', '账面值', '计算值', '差额'].map((label) => <th key={label} scope="col" className="px-2 py-1 font-medium">{label}</th>)}</tr></thead><tbody>{checks.map((check) => <tr key={check.label}><th scope="row" className="px-2 py-1 font-normal">{check.label}</th><td className="px-2 py-1 tabular-nums">{amount(check.observed)}</td><td className="px-2 py-1 tabular-nums">{amount(check.calculated)}</td><td className="px-2 py-1 tabular-nums">{amount(check.difference)}</td></tr>)}</tbody></table>
}

function ItemDetails({ item, index }: { item: PolicyQAFeeItem; index: number }) {
  if (!item.explainable) return <Reconciliation item={item} />
  return <div className="space-y-3">
    <dl className="grid grid-cols-[5rem_minmax(0,1fr)_5rem_minmax(0,1fr)] gap-x-4 text-slate-600"><dt>分类来源</dt><dd>{item.classificationSource ?? '未取得'}</dd><dt>目录条目</dt><dd>{item.catalogEntryId ?? '未取得'}</dd><dt>适用日期</dt><dd>{item.effectiveFrom ?? '未取得'} 至 {item.effectiveTo ?? '未取得'}</dd><dt>费用日期</dt><dd>{item.feeDate ?? '未取得'}</dd>{item.ratioSource ? <><dt>比例来源</dt><dd>{item.ratioSource}；作用于{item.ratioBasis}</dd></> : null}{item.limitSource ? <><dt>限价来源</dt><dd>{item.limitSource}</dd></> : null}</dl>
    <table className="w-full table-fixed text-left" aria-label={`第${index + 1}行实际判定路径`}><thead className="text-slate-600"><tr><th scope="col" className="w-[35%] px-2 py-1 font-medium">条件</th><th scope="col" className="w-[15%] px-2 py-1 font-medium">本行值</th><th scope="col" className="px-2 py-1 font-medium">比较值 / 规则要求</th><th scope="col" className="w-20 px-2 py-1 font-medium">判定</th></tr></thead><tbody className="divide-y divide-slate-200">{item.decisionPath?.map((check, i) => <tr key={i} className="align-top"><th scope="row" className="px-2 py-1 font-normal">{i + 1}. {check.label}</th><td className="break-words px-2 py-1">{check.actual ?? '未取得'}</td><td className="px-2 py-1">{check.expected ?? '未取得'}{check.ruleRefs.length ? <span className="ml-2 text-slate-600">{check.ruleRefs.join('、')}</span> : null}</td><td className="whitespace-nowrap px-2 py-1">{outcome[check.outcome] ?? check.outcome}</td></tr>)}</tbody></table>
    <div className="grid grid-cols-[minmax(0,3fr)_minmax(0,2fr)] items-start gap-6 border-t border-slate-200 pt-3"><div>{item.formulas.map((formula, i) => <p key={i}>{formula}</p>)}</div><div><Reconciliation item={item} /><p className="mt-2 text-slate-600">先行自付已含在医保范围外。</p></div></div>
    {item.notes.filter((note) => note.includes('取整') || note.includes('待签核')).map((note, i) => <p key={i} className="text-slate-600">{note}</p>)}
  </div>
}

export default function FeeItemBreakdownList({ items }: { items: PolicyQAFeeItem[] }) {
  const [expanded, setExpanded] = useState<number | null>(null)
  if (!items.length) return <p className="text-sm text-slate-600">未取得逐行分解记录。</p>
  return <div className="max-w-full overflow-x-auto rounded-md border border-slate-200" role="region" aria-label="逐项费用分解" tabIndex={0}>
    <table className="w-full min-w-[850px] text-left text-xs leading-6">
      <thead className="bg-slate-50 text-slate-700"><tr>{['项目 / 费用', '目录属性', '本次单价、限价与比例', '分解金额（元）', '核对与依据'].map((label) => <th key={label} scope="col" className="px-3 py-2 font-medium">{label}</th>)}</tr></thead>
      <tbody className="divide-y divide-slate-200">{items.map((item, index) => {
        const open = expanded === index
        const attribute = catalogAttribute(item)
        const control = <button type="button" aria-expanded={open} aria-controls={`fee-item-detail-${index}`} onClick={() => setExpanded(open ? null : index)} className="whitespace-nowrap text-blue-800 underline underline-offset-4 focus-visible:outline-2">{open ? '收起本行详情' : item.explainable ? '查看本行判定路径' : '查看本行核对诊断'}</button>
        return <Fragment key={`${item.lineId}-${index}`}><tr data-testid={`fee-item-${index}`} className="align-top">
          <th scope="row" className="max-w-48 px-3 py-3 font-normal"><strong className="block text-slate-900">{index + 1}. {item.itemName || item.itemCode || '未命名项目'}</strong><span className="block text-slate-600">{item.itemType} · {amount(item.totalFee)} 元</span></th>
          <td className="px-3 py-3"><strong className="block font-medium">{attribute.label}</strong>{item.itemType === '药品' || item.centralizedProcurement != null ? <span className="block">集采：{item.centralizedProcurement == null ? '未取得' : item.centralizedProcurement ? '是' : '否'}</span> : null}</td>
          {item.explainable ? <>
            <td className="max-w-64 px-3 py-3"><p>单价 {amount(item.unitPrice)} 元 · 数量 {item.quantity ?? '未取得'}</p>{item.unitPriceLimit != null ? <p>采用限价 {amount(item.unitPriceLimit)} 元{priceComparison(item) ? <> · {priceComparison(item)}</> : null}</p> : null}<p className="font-medium text-slate-900">{division(item)}</p></td>
            <td className="whitespace-nowrap px-3 py-3 tabular-nums"><p>医保范围内 {amount(item.calculatedInScope)}</p><p>医保范围外 {amount(item.calculatedOutScope)}</p><p className="text-slate-600">其中先行自付 {amount(item.calculatedSelfPay2)}</p></td>
            <td className="px-3 py-3">{control}</td>
          </> : <td colSpan={3} className="px-3 py-3">{control}</td>}
        </tr>{open ? <tr id={`fee-item-detail-${index}`}><td colSpan={5} className="bg-slate-50 px-4 py-4"><ItemDetails item={item} index={index} /></td></tr> : null}</Fragment>
      })}</tbody>
    </table>
  </div>
}
