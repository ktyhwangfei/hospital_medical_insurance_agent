'use client'

// 交易信息：按医院结算单分组（费用构成/起付与基金/自付构成/补助/大病救助/个人支付/支付方式），
// 每行金额 + 一句解释；解释含"为什么是这个比例"，可展开查看条件四列与来源有效期。
// 只出现人能读懂的中文与算式；账户/现金仅展示，不加解释。
import { Fragment, useState } from 'react'
import type { PolicyQAFeeDecomposition } from '@/lib/policy-qa-stream'
import { requiresSettlementTemplate } from '@/lib/policy-qa-stream'
import { buildFieldInventory, buildSummaryRows, formatMoney, type RatioDetail, type SummaryRow } from '@/lib/fee-explanation'
import SettlementTemplateView from './settlement-template-view'

const CHECK_TEXT: Record<string, string> = { met: '符合', unmet: '不符合', unknown: '未确认' }

function RatioBlock({ ratio, hospitalLevel }: { ratio: RatioDetail; hospitalLevel?: string }) {
  const checkActual = (check: RatioDetail['checks'][number]) =>
    check.name.includes('机构等级档') && hospitalLevel && check.actual && !check.actual.includes(hospitalLevel)
      ? `${hospitalLevel}（${check.actual}）`
      : check.actual ?? '未取得'
  return (
    <div className="space-y-1">
      <p className={`font-medium ${ratio.executed ? 'text-slate-900' : 'text-slate-600'}`}>{ratio.title}：{ratio.chosen}</p>
      {ratio.checks.length ? (
        <table className="w-full max-w-2xl text-left text-[11px] leading-5">
          <thead className="text-slate-500">
            <tr>{['条件', '规则要求', '本单情况', '判定'].map((heading) => <th key={heading} scope="col" className="px-2 py-1 font-medium">{heading}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {ratio.checks.map((check) => (
              <tr key={check.name}>
                <th scope="row" className="px-2 py-1 font-normal text-slate-700">{check.name}</th>
                <td className="px-2 py-1 text-slate-700">{check.expected}</td>
                <td className="px-2 py-1 text-slate-700">{checkActual(check)}</td>
                <td className={`px-2 py-1 ${check.outcome === 'met' ? 'text-emerald-800' : 'text-amber-800'}`}>{CHECK_TEXT[check.outcome] ?? '未确认'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <p className="text-[11px] text-slate-500">
        {[
          ratio.source ? `来源：${ratio.source}` : null,
          ratio.version ? `版本：${ratio.version}` : null,
          ratio.effective ? `有效期：${ratio.effective}` : null,
          ratio.caliber ? `采用口径：${ratio.caliber}` : null,
        ].filter(Boolean).join(' · ') || '来源未返回'}
      </p>
    </div>
  )
}

function HiddenFields({ items }: { items: ReturnType<typeof buildFieldInventory> }) {
  const hidden = items.filter((item) => !item.shownAsRow)
  if (!hidden.length) return null
  return (
    <details className="mt-2 text-xs leading-6">
      <summary className="w-fit cursor-pointer text-slate-600 underline underline-offset-4 focus-visible:outline-2">
        未单列的结算字段（{hidden.length} 项，已计入上方对应行或为分项明细）
      </summary>
      <div className="mt-2 max-w-full overflow-x-auto" role="region" aria-label="未单列的结算字段" tabIndex={0} data-testid="summary-hidden-fields">
        <table className="w-full min-w-[560px] text-left">
          <thead className="text-slate-500">
            <tr>{['字段', '含义', '账面金额（元）', '计算金额（元）', '核对状态', '计入哪一行'].map((label) => <th key={label} scope="col" className="px-2 py-1 font-medium">{label}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {hidden.map((item) => (
              <tr key={item.fieldCode}>
                <th scope="row" className="px-2 py-1 font-mono font-normal text-slate-500">{item.fieldCode}</th>
                <td className="px-2 py-1 text-slate-800">{item.label}</td>
                <td className="px-2 py-1 text-right tabular-nums text-slate-800">{formatMoney(item.observed) ?? '—'}</td>
                <td className="px-2 py-1 text-right tabular-nums text-slate-800">{formatMoney(item.calculated) ?? '—'}</td>
                <td className={`px-2 py-1 ${item.checkStatus === 'matched' ? 'text-slate-700' : 'text-amber-800'}`}>{item.checkStatus}</td>
                <td className="px-2 py-1 text-slate-600">{item.display ?? '未映射'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}

function DetailBlock({ row, hospitalLevel }: { row: SummaryRow; hospitalLevel?: string }) {
  return (
    <div className="space-y-2 text-xs leading-6 text-slate-700">
      {row.notes.map((note) => <p key={note}>{note}</p>)}
      {row.ratios.map((ratio) => <RatioBlock key={ratio.groupId} ratio={ratio} hospitalLevel={hospitalLevel} />)}
    </div>
  )
}

export default function SettlementSummaryTable({ decomposition, identifier }: {
  decomposition: PolicyQAFeeDecomposition
  identifier: string
}) {
  const [open, setOpen] = useState<string | null>(null)
  const { rows, payments } = buildSummaryRows(decomposition)
  const facts = decomposition.settlementFacts
  const name = (key: string, code: string | null) => facts?.metadataNames?.[key] ?? code ?? '未返回'
  const header = [
    name('medical_category', facts?.medicalCategory ?? null),
    name('insurance_type', facts?.insuranceType ?? null),
    name('person_type', facts?.personType ?? null),
    name('hospital_level', facts?.hospitalLevel ?? null),
    facts?.tradeDate ?? null,
    !facts?.displayTemplate && facts?.chain === 'outpatient' ? `退役医疗费标志：${facts.retireOfficerFlag ?? '未返回'}` : null,
  ].filter(Boolean).join(' · ')
  const all: SummaryRow[] = [...rows, ...payments]

  if (facts?.displayTemplate) {
    const byKey = new Map(rows.map(row => [row.key, row]))
    return (
      <section aria-label="交易信息" className="space-y-3" data-testid="settlement-summary-table">
        <p className="text-xs leading-6 text-slate-600">单号 <span className="font-mono text-slate-800">{identifier}</span>{header ? ` · ${header}` : null}</p>
        <SettlementTemplateView template={facts.displayTemplate} renderDetail={field => {
          const row = byKey.get(field.key)
          if (!row) return null
          const expanded = open === row.key
          return <div className="mt-1 space-y-2 text-xs leading-6 text-slate-700">
            {row.explanation ? <p>{row.explanation}</p> : null}
            {row.expandLabel ? <button type="button" aria-expanded={expanded} aria-controls={`template-detail-${row.key}`}
              className="text-blue-800 underline underline-offset-4 focus-visible:outline-2" onClick={() => setOpen(expanded ? null : row.key)}>
              {expanded ? '收起' : row.expandLabel}
            </button> : null}
            {expanded ? <div id={`template-detail-${row.key}`}><DetailBlock row={row} hospitalLevel={facts.metadataNames?.hospital_level} /></div> : null}
          </div>
        }} />
      </section>
    )
  }
  if (requiresSettlementTemplate(decomposition)) return <p role="status" className="text-sm text-amber-800">本单展示模板未配置或内容无效，请核对链路配置。</p>

  return (
    <section aria-label="交易信息" className="space-y-3" data-testid="settlement-summary-table">
      <p className="text-xs leading-6 text-slate-600">
        单号 <span className="font-mono text-slate-800">{identifier}</span>
        {header ? ` · ${header}` : null}
      </p>
      <div className="max-w-full overflow-x-auto" role="region" aria-label="交易信息金额与解释" tabIndex={0}>
        <table className="w-full min-w-[720px] text-left text-sm leading-6">
          <thead className="bg-slate-50 text-slate-600">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">项目</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">金额（元）</th>
              <th scope="col" className="px-3 py-2 font-medium">解释</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {all.map((row, index) => {
              const previous = index > 0 ? all[index - 1].group : null
              const expanded = open === row.key
              return (
                <Fragment key={row.key}>
                  {row.group !== previous ? (
                    <tr className="bg-slate-100/70">
                      <th scope="colgroup" colSpan={3} className="px-3 py-1.5 text-left text-xs font-semibold text-slate-700">{row.group}</th>
                    </tr>
                  ) : null}
                  <tr className="align-top" data-testid={`summary-row-${row.key}`}>
                    <th scope="row" className={`whitespace-nowrap px-3 py-2 font-normal text-slate-800 ${row.indent ? 'pl-8' : ''} ${row.emphasis ? 'font-semibold text-slate-900' : ''}`}>{row.label}</th>
                    <td className={`whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-900 ${row.emphasis ? 'font-semibold' : ''}`}>{formatMoney(row.value) ?? '未返回'}</td>
                    <td className="px-3 py-2 text-slate-700">
                      <span>{row.explanation ?? '—'}</span>
                      {row.expandLabel ? (
                        <button
                          type="button"
                          aria-expanded={expanded}
                          aria-controls={`summary-detail-${row.key}`}
                          onClick={() => setOpen(expanded ? null : row.key)}
                          className="ml-2 whitespace-nowrap text-xs text-blue-800 underline underline-offset-4 focus-visible:outline-2"
                          data-testid={`summary-ratio-${row.key}`}
                        >
                          {expanded ? '收起' : row.expandLabel}
                        </button>
                      ) : null}
                    </td>
                  </tr>
                  {expanded ? (
                    <tr id={`summary-detail-${row.key}`}>
                      <td colSpan={3} className="bg-slate-50 px-3 py-3"><DetailBlock row={row} hospitalLevel={facts?.metadataNames?.hospital_level} /></td>
                    </tr>
                  ) : null}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
      <HiddenFields items={buildFieldInventory(decomposition, [...rows, ...payments])} />
    </section>
  )
}
