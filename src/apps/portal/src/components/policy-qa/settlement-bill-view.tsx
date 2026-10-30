'use client'

import { useState } from 'react'

import {
  fetchOutpatientFeeItems,
  formatDecimal2,
  type OutpatientFeeItemDTO,
  type PatientSummaryDTO,
} from '@/lib/policy-qa-settlement-list'
import type { PolicyQAFeeDecomposition } from '@/lib/policy-qa-stream'
import { requiresSettlementTemplate } from '@/lib/policy-qa-stream'
import SettlementTemplateView from './settlement-template-view'

/**
 * 结算单式样费用构成视图（policy-qa 面向用户专用）。
 *
 * 参照医院结算单布局：病人基本信息 + 交易相关信息双列金额 + 费用明细页签。
 * 只展示结算记录金额（observedAmount）——重算是内部实现路径，不向用户暴露
 * 「按规则重算/账面核对/差异/核对状态/候选口径/未决事项」等措辞。
 * 字段可点击：点击即就该字段向问答流发起提问（解释在问答里给出，不在账单上展开）；
 * showFieldExplanations=false 用于结算解释右栏，工作台/问答气泡仍可展开固定字段说明。
 * 派生核对行（fieldCode 含 "."，如 T_FeeAll.identity / T_FeeIn.detail）不展示。
 * 金额为十进制字符串，原样展示，禁止数值化运算。
 */

interface SettlementBillViewProps {
  feeDecomposition?: PolicyQAFeeDecomposition
  /** 已定位患者（脱敏摘要）；null 时不渲染病人基本信息块 */
  patient?: PatientSummaryDTO | null
  settlementId?: string
  settlementDate?: string
  serviceType?: string
  /** 点字段发起提问（「XX」是怎么算的）；缺省时字段不可点击 */
  onAskField?: (fieldLabel: string) => void
  /** 费用明细页签开关（普通门诊交易单才有明细数据源） */
  feeItemsAvailable?: boolean
  /** 是否在字段下展开固定字段说明；结算解释页传 false（说明只在问答里给出） */
  showFieldExplanations?: boolean
}

/** 十进制字符串金额原样展示；null → '—'。 */
function amountText(value: string | null): string {
  return value ?? '—'
}

function PatientInfoItem({ label, value }: { label: string; value: string }) {
  if (!value) return null
  return (
    <div className="flex items-baseline gap-2">
      <span className="shrink-0 text-slate-500">{label}</span>
      <span className="min-w-0 truncate font-medium text-slate-900">{value}</span>
    </div>
  )
}

/** 单个金额格：label + 右对齐金额；提供 onAskField 时整格可点击发起提问。 */
function BillFieldCell({
  label,
  amount,
  onAskField,
}: {
  label: string
  amount: string | null
  onAskField?: (fieldLabel: string) => void
}) {
  const content = (
    <span className="flex w-full items-baseline justify-between gap-3">
      <span className="text-slate-600">{label}</span>
      <span className="shrink-0 font-mono tabular-nums font-medium text-slate-900">
        {amountText(amount)}
      </span>
    </span>
  )
  if (!onAskField) {
    return <div className="px-3 py-2 text-sm">{content}</div>
  }
  return (
    <button
      type="button"
      onClick={() => onAskField(label)}
      title={`问问「${label}」是怎么算的`}
      aria-label={`提问：${label}`}
      className="w-full rounded px-3 py-2 text-left text-sm transition-colors hover:bg-white hover:shadow-sm hover:ring-1 hover:ring-slate-200"
    >
      {content}
    </button>
  )
}

type FeeItemsState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'done'; items: OutpatientFeeItemDTO[] }

/** 费用明细页签：首次切到才拉取（懒加载）。 */
function FeeItemsTab({
  settlementId,
  state,
}: {
  settlementId: string
  state: FeeItemsState
}) {
  if (state.status === 'loading' || state.status === 'idle') {
    return <p className="px-3 py-6 text-center text-sm text-slate-400">正在加载费用明细…</p>
  }
  if (state.status === 'error') {
    return (
      <p role="alert" className="px-3 py-6 text-center text-sm text-amber-700">
        {state.message}
      </p>
    )
  }
  if (state.items.length === 0) {
    return <p className="px-3 py-6 text-center text-sm text-slate-400">本笔交易无费用明细。</p>
  }
  return (
    <div className="overflow-x-auto" data-testid="settlement-bill-fee-items">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-slate-200 text-left text-slate-500">
            <th className="py-1.5 pr-3 font-medium">项目名称</th>
            <th className="py-1.5 pr-3 font-medium">类别</th>
            <th className="py-1.5 pr-3 text-right font-medium">数量</th>
            <th className="py-1.5 pr-3 text-right font-medium">单价</th>
            <th className="py-1.5 pr-3 text-right font-medium">金额</th>
            <th className="py-1.5 pr-3 text-right font-medium">医保内</th>
            <th className="py-1.5 text-right font-medium">医保外</th>
          </tr>
        </thead>
        <tbody>
          {state.items.map((item, index) => (
            <tr key={`${item.itemCode}-${index}`} className="border-b border-slate-100">
              <td className="py-1.5 pr-3 text-slate-700">{item.itemName || item.itemCode}</td>
              <td className="py-1.5 pr-3 text-slate-500">{item.itemType}</td>
              <td className="py-1.5 pr-3 text-right font-mono tabular-nums text-slate-700">
                {formatDecimal2(item.quantity)}
              </td>
              <td className="py-1.5 pr-3 text-right font-mono tabular-nums text-slate-700">
                {formatDecimal2(item.unitPrice)}
              </td>
              <td className="py-1.5 pr-3 text-right font-mono tabular-nums text-slate-900">
                {formatDecimal2(item.totalFee)}
              </td>
              <td className="py-1.5 pr-3 text-right font-mono tabular-nums text-slate-700">
                {formatDecimal2(item.insuranceInner)}
              </td>
              <td className="py-1.5 text-right font-mono tabular-nums text-slate-700">
                {formatDecimal2(item.insuranceOuter)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="pt-1.5 text-right text-[11px] text-slate-400">
        共 {state.items.length} 项 · 单位：元（{settlementId}）
      </p>
    </div>
  )
}

export default function SettlementBillView({
  feeDecomposition,
  patient,
  settlementId,
  settlementDate,
  serviceType,
  onAskField,
  feeItemsAvailable = false,
  showFieldExplanations = true,
}: SettlementBillViewProps) {
  const [tab, setTab] = useState<'info' | 'items'>('info')
  const [feeItemsState, setFeeItemsState] = useState<FeeItemsState>({ status: 'idle' })

  if (!feeDecomposition) return null
  // 派生核对行（fieldCode 含 "."）是内部勾稽口径，不进用户结算单
  const billFields = feeDecomposition.fields.filter((field) => !field.fieldCode.includes('.'))
  // 分解不可用（无字段）时整体不渲染，避免空卡片；解答由问答正文承载
  const template = feeDecomposition.settlementFacts?.displayTemplate
  if (billFields.length === 0 && !template && !requiresSettlementTemplate(feeDecomposition)) return null

  const showItemsTab = feeItemsAvailable && !!settlementId

  const activateItemsTab = () => {
    setTab('items')
    if (feeItemsState.status !== 'idle' || !settlementId) return
    setFeeItemsState({ status: 'loading' })
    fetchOutpatientFeeItems(settlementId)
      .then((items) => setFeeItemsState({ status: 'done', items }))
      .catch((error) =>
        setFeeItemsState({
          status: 'error',
          message: error instanceof Error ? error.message : '费用明细查询失败',
        }),
      )
  }

  return (
    <section
      aria-label="结算单费用构成"
      data-testid="settlement-bill-view"
      className="space-y-4 rounded-xl border border-slate-200 bg-slate-50/60 px-4 py-4"
    >
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        {!template && feeDecomposition.settlementFacts?.chain === 'outpatient' ? <span className="text-xs text-slate-500">退役医疗费标志：{feeDecomposition.settlementFacts.retireOfficerFlag ?? '未返回'}</span> : null}
        <h3 className="text-sm font-semibold text-slate-800">结算单费用构成</h3>
        {settlementId ? (
          <span className="font-mono text-xs text-slate-500">{settlementId}</span>
        ) : null}
        {settlementDate ? (
          <span className="tabular-nums text-xs text-slate-500">
            {settlementDate.slice(0, 16)}
          </span>
        ) : null}
        {showItemsTab ? (
          <div
            role="tablist"
            aria-label="结算单内容"
            className="ml-auto flex items-center gap-1 rounded-full bg-slate-100 p-0.5"
          >
            {(
              [
                { id: 'info', label: '交易信息' },
                { id: 'items', label: '费用明细' },
              ] as const
            ).map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={tab === item.id}
                data-testid={`bill-tab-${item.id}`}
                onClick={() => (item.id === 'items' ? activateItemsTab() : setTab('info'))}
                className={[
                  'rounded-full px-3 py-1 text-xs font-medium transition-colors',
                  tab === item.id
                    ? 'bg-white text-slate-900 shadow-sm'
                    : 'text-slate-600 hover:text-slate-900',
                ].join(' ')}
              >
                {item.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {tab === 'items' && showItemsTab && settlementId ? (
        <FeeItemsTab settlementId={settlementId} state={feeItemsState} />
      ) : template ? (
        <SettlementTemplateView template={template} patient={patient} onAskField={onAskField}
          fieldExplanations={showFieldExplanations ? feeDecomposition.templateExplanations : undefined} />
      ) : requiresSettlementTemplate(feeDecomposition) ? (
        <p role="status" className="text-sm text-amber-800">本单展示模板未配置或内容无效，请核对链路配置。</p>
      ) : (
        <>
          {patient ? (
            <div data-testid="settlement-bill-patient" className="space-y-1.5">
              <p className="text-xs font-medium text-slate-500">病人基本信息</p>
              <div className="grid grid-cols-1 gap-x-8 gap-y-1.5 rounded-lg bg-white px-3 py-3 text-sm ring-1 ring-slate-100 sm:grid-cols-2">
                <PatientInfoItem label="姓名" value={patient.name} />
                <PatientInfoItem label="性别" value={patient.gender} />
                <PatientInfoItem label="身份证号" value={patient.idNoMasked} />
                <PatientInfoItem label="医保卡号" value={patient.cardNo} />
                <PatientInfoItem label="医疗类别" value={serviceType ?? ''} />
              </div>
            </div>
          ) : null}

          <div className="space-y-1.5">
            <p className="text-xs font-medium text-slate-500">交易相关信息（元）</p>
            <div
              data-testid="settlement-bill-fields"
              className="grid grid-cols-1 gap-x-8 gap-y-0.5 sm:grid-cols-2"
            >
              {billFields.map((field) => (
                <BillFieldCell
                  key={field.fieldCode}
                  label={field.label}
                  amount={field.observedAmount}
                  onAskField={onAskField}
                />
              ))}
            </div>
            {onAskField ? (
              <p className="pt-1 text-[11px] text-slate-400">
                点击任意字段可就该字段提问。
              </p>
            ) : null}
          </div>
        </>
      )}
    </section>
  )
}
