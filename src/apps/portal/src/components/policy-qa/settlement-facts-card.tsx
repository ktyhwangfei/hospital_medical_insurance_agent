'use client'

import type { PolicyQASettlementFacts } from '@/lib/policy-qa-stream'

function Amounts({ items }: { items: PolicyQASettlementFacts['items'] }) {
  return (
    <dl className="grid gap-x-8 sm:grid-cols-2">
      {items.map((item, index) => (
        <div key={`${item.label}-${index}`} className="flex min-w-0 items-baseline justify-between gap-3 border-b border-slate-100 py-2 text-sm">
          <dt className="text-slate-600">{item.label}</dt>
          <dd className="shrink-0 tabular-nums font-medium text-slate-900">{item.value === null ? '未返回' : `${item.value} 元`}</dd>
        </div>
      ))}
    </dl>
  )
}

export default function SettlementFactsCard({ facts, identifier }: {
  facts?: PolicyQASettlementFacts
  identifier: string
}) {
  const name = (key: string, code: string | null) => facts?.metadataNames?.[key] ?? (code === null ? '未返回' : '中文含义未取得')
  return (
    <section aria-label="结算事实" className="space-y-2 rounded-xl border border-slate-200 bg-white p-4" data-testid="settlement-facts-card">
      <div>
        <h2 className="text-base font-semibold text-slate-900">交易信息</h2>
      </div>
          {facts ? (
            <details className="text-sm">
              <summary className="cursor-pointer leading-6 text-slate-800 focus-visible:outline-2">{[name('person_type', facts.personType), name('insurance_type', facts.insuranceType), name('medical_category', facts.medicalCategory), name('hospital_level', facts.hospitalLevel), facts.tradeDate].filter(Boolean).join(' · ')}<span className="ml-2 text-xs text-blue-800 underline underline-offset-4">详细交易信息</span></summary>
              <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 text-sm md:grid-cols-3">
                {[
                  ['单号', facts.identifier], ['交易日期', facts.tradeDate],
                  ['医疗类别', name('medical_category', facts.medicalCategory)], ['险种', name('insurance_type', facts.insuranceType)],
                  ['人员类别', name('person_type', facts.personType)], ['机构等级', name('hospital_level', facts.hospitalLevel)],
                ].map(([label, value]) => (
                  <div key={label} className="min-w-0">
                    <dt className="text-slate-600">{label}</dt>
                    <dd className="mt-0.5 break-all font-medium text-slate-900">{value ?? '未返回'}</dd>
                  </div>
                ))}
              </dl>
              <details className="text-sm">
                <summary className="cursor-pointer py-2 text-slate-600 focus-visible:outline-2">原单全部金额与原始代码</summary>
                <p className="pb-2 text-xs text-slate-600">医疗类别代码 {facts.medicalCategory ?? '未返回'} · 险种代码 {facts.insuranceType ?? '未返回'} · 人员类别代码 {facts.personType ?? '未返回'} · 机构等级代码 {facts.hospitalLevel ?? '未返回'}</p>
                <Amounts items={facts.items} />
              <div>
                <h3 className="text-sm font-semibold text-slate-800">支付方式</h3>
                <p className="mt-1 text-xs text-slate-600">账户与现金是个人支付的渠道，不与个人支付总金额重复相加。</p>
                <Amounts items={facts.paymentItems} />
              </div>
              </details>
            </details>
          ) : <p className="py-3 text-sm text-slate-600">单号 {identifier}：本次响应未提供原单事实；已有解释见下方。</p>}
    </section>
  )
}
