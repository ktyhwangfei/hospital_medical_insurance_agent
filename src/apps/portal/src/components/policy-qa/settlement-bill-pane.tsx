'use client'

import { ReceiptText } from 'lucide-react'

import type { SettlementBillDTO } from '@/lib/policy-qa-settlement-list'

/**
 * 单张结算单右侧栏：结算单费用构成 + 费用明细。
 *
 * 门诊/门特/住院共用同一展示结构（多笔时每张 tab 各渲染一份）；
 * 只展示后端返回的真实字段，缺失显示「—」，不推导目录属性或限价。
 */

function amountText(value: string | null): string {
  return value ?? '—'
}

export default function SettlementBillPane({ bill }: { bill: SettlementBillDTO }) {
  return (
    <article
      data-testid="settlement-bill"
      className="space-y-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-slate-100 pb-2">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
          <ReceiptText className="size-4 text-slate-400" aria-hidden />
          结算单 {bill.settlementId}
        </div>
        <p className="text-xs text-slate-500">
          {[bill.serviceType, bill.settlementDate].filter(Boolean).join(' · ') || '结算类型待定'}
        </p>
      </header>

      <section aria-label="结算单费用构成">
        <h3 className="mb-2 text-xs font-semibold tracking-wide text-slate-500">结算单费用构成</h3>
        <ul data-testid="settlement-bill-fields" className="divide-y divide-slate-100 text-sm">
          {bill.fields.map((field) => (
            <li key={field.key} className="flex items-baseline justify-between gap-3 py-1.5">
              <span className="text-slate-600">{field.label}</span>
              <span className="tabular-amounts shrink-0 text-slate-900">
                {amountText(field.amount)}
              </span>
            </li>
          ))}
        </ul>
      </section>

      {bill.warnings.length > 0 ? (
        <ul
          data-testid="settlement-bill-warnings"
          className="list-disc space-y-1 rounded-xl bg-amber-50 px-4 py-2 pl-8 text-xs leading-5 text-amber-800"
        >
          {bill.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}

      <section aria-label="费用明细">
        <h3 className="mb-2 text-xs font-semibold tracking-wide text-slate-500">费用明细</h3>
        {bill.feeItemsState === 'missing' ? (
          <p
            data-testid="settlement-fee-empty"
            className="rounded-xl bg-slate-50 px-3 py-2 text-sm text-slate-500"
          >
            未查询到该结算单的费用明细。
          </p>
        ) : (
          <div className="max-h-[28rem] overflow-auto rounded-xl border border-slate-100">
            <table
              data-testid="settlement-fee-table"
              className="w-full min-w-[560px] text-left text-xs"
            >
              <thead className="sticky top-0 bg-white">
                <tr className="border-b border-slate-200 text-slate-500">
                  <th className="py-1.5 pr-2 font-medium">项目 / 费用</th>
                  <th className="px-2 py-1.5 font-medium">类别</th>
                  <th className="px-2 py-1.5 text-right font-medium">数量</th>
                  <th className="px-2 py-1.5 text-right font-medium">单价</th>
                  <th className="px-2 py-1.5 text-right font-medium">金额</th>
                  <th className="px-2 py-1.5 text-right font-medium">医保内</th>
                  <th className="py-1.5 pl-2 text-right font-medium">医保外</th>
                </tr>
              </thead>
              <tbody>
                {bill.feeItems.map((item, index) => (
                  <tr
                    key={`${item.itemCode || item.itemName}-${index}`}
                    className="border-b border-slate-100 align-top last:border-b-0"
                  >
                    <td className="py-1.5 pr-2">
                      <p className="font-medium text-slate-900">
                        {item.itemName || item.itemCode || '—'}
                      </p>
                      {item.itemCode && item.itemCode !== item.itemName ? (
                        <p className="text-[11px] text-slate-400">{item.itemCode}</p>
                      ) : null}
                    </td>
                    <td className="px-2 py-1.5 text-slate-600">{item.itemType || '—'}</td>
                    <td className="tabular-amounts px-2 py-1.5 text-right text-slate-700">
                      {amountText(item.quantity)}
                    </td>
                    <td className="tabular-amounts px-2 py-1.5 text-right text-slate-700">
                      {amountText(item.unitPrice)}
                    </td>
                    <td className="tabular-amounts px-2 py-1.5 text-right text-slate-900">
                      {amountText(item.totalAmount)}
                    </td>
                    <td className="tabular-amounts px-2 py-1.5 text-right text-slate-700">
                      {amountText(item.insuranceInner)}
                    </td>
                    <td className="tabular-amounts py-1.5 pl-2 text-right text-slate-700">
                      {amountText(item.insuranceOuter)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </article>
  )
}
