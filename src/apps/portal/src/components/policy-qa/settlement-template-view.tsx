'use client'

import type { CSSProperties, ReactNode } from 'react'
import type { PatientSummaryDTO } from '@/lib/policy-qa-settlement-list'
import { formatDecimal2 } from '@/lib/policy-qa-settlement-list'
import type { PolicyQAFieldExplanation, SettlementDisplayTemplate, SettlementTemplateField } from '@/lib/policy-qa-stream'
import FieldExplanationBlock from './field-explanation-block'

const SECTIONS = [
  ['basic', '病人基本信息'],
  ['transaction', '交易相关信息'],
  ['hospital', '医院定额清算'],
] as const

/** 两处页面共用已绑定模板；窄栏按同一行序单列，不修改原单名称和金额。 */
export default function SettlementTemplateView({ template, patient, onAskField, renderDetail, fieldExplanations }: {
  template: SettlementDisplayTemplate
  patient?: PatientSummaryDTO | null
  onAskField?: (label: string) => void
  renderDetail?: (field: SettlementTemplateField) => ReactNode
  /** 解释投影 1.10：按模板 key 索引的字段四要素固定说明（面板与聊天同源同文） */
  fieldExplanations?: Record<string, PolicyQAFieldExplanation>
}) {
  const patientValues: Record<string, string | undefined> = {
    'patient.name': patient?.name, 'patient.gender': patient?.gender,
    'patient.idNoMasked': patient?.idNoMasked, 'patient.cardNo': patient?.cardNo,
  }
  return (
    <div className="@container space-y-5" data-testid="settlement-template-view" data-template-id={template.templateId} data-template-version={template.version}>
      {SECTIONS.map(([section, title]) => {
        const fields = template.fields.filter(field => field.section === section).sort((a, b) => a.row - b.row || a.column - b.column)
        if (!fields.length) return null
        return (
          <section key={section} aria-label={title} className="space-y-2">
            <h4 className="text-sm font-semibold text-slate-900">{title}{section === 'basic' ? '' : '（元）'}</h4>
            <dl className={`grid grid-cols-1 gap-x-6 border-y border-slate-200 ${section === 'basic' ? '@3xl:grid-cols-4' : '@2xl:grid-cols-2'}`}>
              {fields.map(field => {
                const value = field.contextKey?.startsWith('patient.') ? patientValues[field.contextKey] ?? null : field.value
                const text = value == null ? field.status === 'unmapped' ? '未映射' : '未返回' : section === 'basic' ? value : formatDecimal2(value)
                const style = { '--bill-column': `${field.column} / span ${field.span}`, '--bill-row': String(field.row) } as CSSProperties
                const placement = section === 'basic' ? '@3xl:[grid-column:var(--bill-column)] @3xl:[grid-row:var(--bill-row)]' : '@2xl:[grid-column:var(--bill-column)] @2xl:[grid-row:var(--bill-row)]'
                return (
                  <div key={field.key} style={style} data-template-key={field.key} data-template-row={field.row} data-template-column={field.column} className={`grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 border-b border-slate-100 py-2.5 text-sm leading-6 ${placement}`}>
                      <dt className="min-w-0 break-words text-slate-700">
                        {onAskField && section !== 'basic' ? <button type="button" className="text-left underline decoration-slate-300 underline-offset-4 focus-visible:outline-2" aria-label={`提问：${field.label}`} onClick={() => onAskField(field.label)}>{field.label}</button> : field.label}
                      </dt>
                      <dd className={`shrink-0 text-right tabular-nums ${value == null ? 'text-slate-500' : 'font-medium text-slate-900'}`}>{text}</dd>
                    {section !== 'basic' && renderDetail ? <dd className="col-span-2">{renderDetail(field)}</dd> : null}
                    {field.note ? <dd className="col-span-2 mt-1 text-xs leading-5 text-slate-500">{field.note}</dd> : null}
                    {section !== 'basic' && fieldExplanations?.[field.key] ? (
                      <dd className="col-span-2 mt-1">
                        <details className="text-xs leading-5 text-slate-600">
                          <summary className="cursor-pointer py-0.5 text-slate-400 focus-visible:outline-2">字段说明</summary>
                          <FieldExplanationBlock
                            explanation={fieldExplanations[field.key]}
                            testId={`template-field-explanation-${field.key}`}
                          />
                        </details>
                      </dd>
                    ) : null}
                  </div>
                )
              })}
            </dl>
          </section>
        )
      })}
      {template.layoutStatus === 'provisional' ? <p className="text-xs leading-5 text-slate-500">字段布局待本链路原始结算单确认。</p> : null}
    </div>
  )
}
