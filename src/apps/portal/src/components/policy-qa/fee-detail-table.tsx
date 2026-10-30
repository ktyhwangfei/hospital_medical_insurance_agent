'use client'

// 交易明细表：项目名、金额、类别与一句关键原因优先占满可视宽度；
// 单价、数量、日期、编码与目录参数收进展开的本行详情。
// 关键原因只写本行实际采用的限价与比例；未采用的目录参数单独标注，避免与采用值并列误读。
import { Fragment, useState } from 'react'
import type { PolicyQAFeeDecomposition } from '@/lib/policy-qa-stream'
import { feeItemExplanation, feeItemReason, formatMoney } from '@/lib/fee-explanation'
import { percentOf } from '@/lib/fee-explanation-numbers'

const dash = (value: string | null | undefined) => value ?? '—'

function Fact({ label, value }: { label: string; value: string | null | undefined }) {
  if (value == null || value === '') return null
  return (
    <div className="flex gap-2">
      <dt className="shrink-0 text-slate-500">{label}</dt>
      <dd className="min-w-0 break-words text-slate-800">{value}</dd>
    </div>
  )
}

export default function FeeDetailTable({ decomposition }: { decomposition: PolicyQAFeeDecomposition }) {
  const [open, setOpen] = useState<number | null>(null)
  const items = decomposition.feeItems ?? []
  if (!items.length) return <p className="p-4 text-sm text-slate-600">本次响应未返回交易明细。</p>
  return (
    <div className="max-w-full overflow-auto" role="region" aria-label="交易明细与逐行解释" tabIndex={0} data-testid="fee-detail-table">
      <table className="w-full min-w-[720px] border-collapse text-left text-xs leading-6">
        <thead className="sticky top-0 z-10 bg-slate-50 text-slate-600">
          <tr>
            {['项目名', '总金额（元）', '医保内（元）', '医保外（元）', '自付二（元）', '类别', '关键原因'].map((label, index) => (
              <th
                key={label}
                scope="col"
                className={`border-b border-slate-200 px-3 py-2 font-medium ${index >= 1 && index <= 4 ? 'text-right' : ''} ${index === 0 ? 'sticky left-0 z-20 bg-slate-50' : ''}`}
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {items.map((item, index) => {
            const expanded = open === index
            const reason = feeItemReason(item)
            const explanation = feeItemExplanation(item)
            const unusedExcessRatio = item.aXbbl && item.aXbbl !== item.selfPayRatio ? (percentOf(item.aXbbl) ?? item.aXbbl) : null
            return (
              <Fragment key={`${item.lineId}-${index}`}>
                <tr className="align-top" data-testid={`fee-detail-row-${index}`}>
                  <th scope="row" className="sticky left-0 min-w-36 bg-white px-3 py-2 text-left font-medium text-slate-900">{dash(item.itemName)}</th>
                  <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-900">{formatMoney(item.totalFee) ?? '—'}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-900">{formatMoney(item.observedInScope) ?? '—'}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-900">{formatMoney(item.observedOutScope) ?? '—'}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-900">{formatMoney(item.observedSelfPay2) ?? '—'}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-700">{dash(item.classificationLabel)}</td>
                  <td className="px-3 py-2 text-slate-700">
                    <span className="break-words">{reason ?? '—'}</span>
                    {explanation ? (
                      <button
                        type="button"
                        aria-expanded={expanded}
                        aria-controls={`fee-detail-explanation-${index}`}
                        onClick={() => setOpen(expanded ? null : index)}
                        className="mt-1 block whitespace-nowrap text-[11px] text-blue-800 underline underline-offset-4 focus-visible:outline-2"
                      >
                        {expanded ? '收起解释' : '展开解释'}
                      </button>
                    ) : null}
                  </td>
                </tr>
                {expanded && explanation ? (
                  <tr id={`fee-detail-explanation-${index}`}>
                    <td colSpan={7} className="bg-slate-50 px-3 py-3">
                      <p className="whitespace-normal break-words text-xs leading-6 text-slate-700">{explanation}</p>
                      <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-[11px] sm:grid-cols-2">
                        <Fact label="单价" value={item.unitPrice ? formatMoney(item.unitPrice) : null} />
                        <Fact label="数量" value={item.quantity} />
                        <Fact label="费用发生日期" value={item.feeDate} />
                        <Fact label="目录有效期" value={item.effectiveFrom || item.effectiveTo ? `${item.effectiveFrom ?? '未标注'} 至 ${item.effectiveTo ?? '未标注'}` : null} />
                        <Fact label="项目编码" value={item.itemCode} />
                        <Fact label="集采" value={item.centralizedProcurement == null ? null : item.centralizedProcurement ? '是' : '否'} />
                        <Fact label="本次采用的限价" value={item.unitPriceLimit ? `${formatMoney(item.unitPriceLimit)}（${item.limitSource ?? '来源未取得'}）` : null} />
                        <Fact label="本次采用的自付比例" value={item.selfPayRatio ? `${item.selfPayRatio}（${item.ratioSource ?? '来源未取得'}）` : null} />
                        <Fact label="目录超限价参数（本行未采用）" value={unusedExcessRatio} />
                      </dl>
                      {item.conditions.length || item.formulas.length || item.notes.length ? (
                        <ul className="mt-2 space-y-1 text-[11px] leading-5 text-slate-600">
                          {[...item.conditions, ...item.formulas, ...item.notes].map((line, lineIndex) => (
                            <li key={lineIndex}>{line}</li>
                          ))}
                        </ul>
                      ) : null}
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
