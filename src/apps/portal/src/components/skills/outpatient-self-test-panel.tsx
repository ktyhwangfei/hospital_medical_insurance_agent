'use client'

import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, CheckCircle2, Database, Loader2, LockKeyhole, Pencil, Play, Save, X } from 'lucide-react'
import {
  freezeSkillEvalDataset,
  importOutpatientEvalTasks,
  listSettlementSelfTests,
  runSettlementSelfTests,
  updateSettlementSelfTest,
} from '@/lib/api-client'
import { ApiClientError } from '@/lib/types'
import type {
  OutpatientSettlementSelfTestContext,
  SettlementSelfTestCase,
  SettlementSelfTestRun,
  SettlementSelfTestSuite,
} from '@/lib/types'

const MONEY_FIELDS = [
  ['total_amount', '费用总金额'],
  ['in_scope_amount', '医保范围内金额'],
  ['out_of_scope_amount', '医保范围外金额'],
  ['self_pay_one', '个人自付一'],
  ['self_pay_two', '个人自付二'],
  ['personal_total_amount', '个人支付总金额'],
  ['deductible_amount', '起付金额'],
  ['beyond_cap_amount', '大额超封顶金额'],
  ['large_self_pay', '大额自付金额'],
  ['fund_total_amount', '基金支付总金额'],
  ['large_fund_payment', '大额基金支付'],
  ['account_payment', '个人账户支付'],
  ['cash_payment', '个人现金支付'],
  ['big_disease_payment', '大病支付'],
  ['retired_medical_payment', '退役医疗费'],
  ['unit_supplement_payment', '单位补充或公疗支付'],
  ['disabled_soldier_payment', '残疾军人补助'],
  ['supplementary_insurance_payment', '补充保险支付'],
  ['assistance_payment', '救助支付'],
] as const

const CHANNEL_FIELDS = [
  ['large_fund_payment', '大额基金'],
  ['supplementary_insurance_payment', '补充保险'],
  ['unit_supplement_payment', '公务员或公疗'],
  ['big_disease_payment', '大病保障'],
  ['retired_medical_payment', '退役医疗'],
  ['assistance_payment', '医疗救助'],
  ['disabled_soldier_payment', '军残补助'],
] as const

type MoneyField = (typeof MONEY_FIELDS)[number][0]

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiClientError ? error.detail.message : fallback
}

function nonZero(value: string | null | undefined): boolean {
  return value != null && Number(value) !== 0
}

function paymentChannels(context: OutpatientSettlementSelfTestContext): string[] {
  return CHANNEL_FIELDS.filter(([field]) => nonZero(context[field])).map(([, label]) => label)
}

export default function OutpatientSelfTestPanel({
  suiteId,
  onDatasetChanged,
}: {
  suiteId?: string | null
  onDatasetChanged?: () => void
}) {
  const [suite, setSuite] = useState<SettlementSelfTestSuite | null>(null)
  const [run, setRun] = useState<SettlementSelfTestRun | null>(null)
  const [editing, setEditing] = useState<SettlementSelfTestCase | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [datasetMessage, setDatasetMessage] = useState<string | null>(null)

  useEffect(() => {
    listSettlementSelfTests()
      .then(setSuite)
      .catch((reason) => setError(errorMessage(reason, '加载全人群固定样例失败')))
      .finally(() => setLoading(false))
  }, [])

  const coverage = useMemo(() => {
    const items = suite?.items ?? []
    return {
      people: new Set(items.map((item) => item.context.person_type).filter(Boolean)).size,
      insurances: new Set(items.map((item) => item.context.insurance_type).filter(Boolean)).size,
      services: new Set(items.map((item) => item.context.service_type).filter(Boolean)).size,
      channels: new Set(items.flatMap((item) => paymentChannels(item.context))).size,
    }
  }, [suite])

  async function runAll(): Promise<void> {
    setBusy(true)
    setError(null)
    try {
      setRun(await runSettlementSelfTests())
    } catch (reason) {
      setError(errorMessage(reason, '运行固定样例失败'))
    } finally {
      setBusy(false)
    }
  }

  async function importTasks(): Promise<void> {
    if (!suiteId) return
    setBusy(true)
    setError(null)
    try {
      const imported = await importOutpatientEvalTasks(suiteId)
      setDatasetMessage(`已导入 ${imported.total} 条端到端评测任务。`)
      onDatasetChanged?.()
    } catch (reason) {
      setError(errorMessage(reason, '导入评测任务失败'))
    } finally {
      setBusy(false)
    }
  }

  async function freezeDataset(): Promise<void> {
    if (!suiteId) return
    setBusy(true)
    setError(null)
    try {
      const frozen = await freezeSkillEvalDataset(suiteId)
      setDatasetMessage(`已冻结数据集版本 v${frozen.version_number}。`)
      onDatasetChanged?.()
    } catch (reason) {
      setError(errorMessage(reason, '冻结数据集失败'))
    } finally {
      setBusy(false)
    }
  }

  async function save(): Promise<void> {
    if (!editing) return
    setBusy(true)
    setError(null)
    try {
      const { case_id: caseId, ...request } = editing
      const updated = await updateSettlementSelfTest(caseId, request)
      setSuite((current) => {
        if (!current) return current
        const items = current.items.map((item) => item.case_id === caseId ? updated : item)
        return { ...current, items, enabled: items.filter((item) => item.enabled).length }
      })
      setEditing(null)
      setRun(null)
    } catch (reason) {
      setError(errorMessage(reason, '保存固定样例失败'))
    } finally {
      setBusy(false)
    }
  }

  function setContext(field: keyof OutpatientSettlementSelfTestContext, value: string): void {
    setEditing((current) => current && ({
      ...current,
      context: { ...current.context, [field]: value || null },
    }))
  }

  const resultByCase = new Map(run?.results.map((item) => [item.case_id, item]))

  return (
    <section aria-label="全人群结算自测" className="rounded-xl border border-blue-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">全人群结算自测</h3>
          <p className="mt-1 text-xs text-slate-500">
            固定真实结算快照，覆盖不同人群、险种和支付渠道。金额取结算单原始字段，不反推个人自付一。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void importTasks()}
            disabled={busy || !suiteId}
            className="inline-flex items-center gap-1.5 rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-sm font-medium text-blue-800 hover:bg-blue-100 disabled:opacity-50"
          >
            <Database className="h-4 w-4" />
            导入 28 条任务
          </button>
          <button
            type="button"
            onClick={() => void freezeDataset()}
            disabled={busy || !suiteId}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            <LockKeyhole className="h-4 w-4" />
            冻结数据集
          </button>
          <button
            type="button"
            onClick={() => void runAll()}
            disabled={busy || loading}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-800 disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            运行固定样例
          </button>
        </div>
      </div>

      {error ? (
        <div className="mt-3 flex items-center gap-2 rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-700">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" /> {error}
        </div>
      ) : null}
      {datasetMessage ? (
        <p role="status" className="mt-3 text-xs font-medium text-blue-800">{datasetMessage}</p>
      ) : null}

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
        {[
          ['固定样例', suite?.total ?? 0],
          ['参保人群', coverage.people],
          ['险种', coverage.insurances],
          ['就医类别', coverage.services],
          ['支付渠道', coverage.channels],
        ].map(([label, value]) => (
          <div key={label} className="rounded-lg bg-slate-50 px-3 py-2">
            <div className="text-lg font-semibold text-slate-900">{value}</div>
            <div className="text-xs text-slate-500">{label}</div>
          </div>
        ))}
      </div>

      {run ? (
        <div className={`mt-3 flex items-center gap-2 rounded-lg px-3 py-2 text-sm ${run.failed ? 'bg-rose-50 text-rose-700' : 'bg-emerald-50 text-emerald-700'}`}>
          {run.failed ? <AlertCircle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
          {run.passed}/{run.total} 通过{run.failed ? `，${run.failed} 个失败` : '，全部通过'}
        </div>
      ) : null}

      {loading ? (
        <p className="py-6 text-center text-sm text-slate-400">加载中…</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-xs">
            <thead className="border-y border-slate-200 bg-slate-50 text-slate-500">
              <tr>
                <th className="px-2 py-2 font-medium">结算交易号</th>
                <th className="px-2 py-2 font-medium">人群 / 险种</th>
                <th className="px-2 py-2 font-medium">就医类别</th>
                <th className="px-2 py-2 font-medium">个人自付一</th>
                <th className="px-2 py-2 font-medium">非零支付渠道</th>
                <th className="px-2 py-2 font-medium">结果</th>
                <th className="px-2 py-2 font-medium">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {suite?.items.map((item) => {
                const result = resultByCase.get(item.case_id)
                return (
                  <tr key={item.case_id} className={item.enabled ? '' : 'opacity-50'}>
                    <td className="px-2 py-2 font-mono text-slate-700">{item.settlement_id}</td>
                    <td className="px-2 py-2 text-slate-700">
                      {item.context.person_type ?? '未填写'}
                      <div className="text-slate-400">{item.context.insurance_type ?? '未填写'}</div>
                    </td>
                    <td className="px-2 py-2 text-slate-600">{item.context.service_type ?? '未填写'}</td>
                    <td className="px-2 py-2 font-medium text-slate-800">{item.expected_self_pay_one} 元</td>
                    <td className="px-2 py-2 text-slate-600">{paymentChannels(item.context).join('、') || '无'}</td>
                    <td className="px-2 py-2">
                      {result ? (
                        <span className={result.status === 'passed' ? 'text-emerald-700' : result.status === 'failed' ? 'text-rose-700' : 'text-slate-400'}>
                          {result.status === 'passed' ? '通过' : result.status === 'failed' ? '失败' : '已停用'}
                        </span>
                      ) : '未运行'}
                    </td>
                    <td className="px-2 py-2">
                      <button
                        type="button"
                        onClick={() => setEditing(structuredClone(item))}
                        className="inline-flex items-center gap-1 text-blue-700 hover:underline"
                      >
                        <Pencil className="h-3.5 w-3.5" /> 编辑
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {editing ? (
        <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold text-slate-800">编辑固定样例：{editing.case_id}</h4>
            <button type="button" aria-label="取消编辑" onClick={() => setEditing(null)} className="text-slate-400 hover:text-slate-700">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <TextField label="结算交易号" value={editing.settlement_id} onChange={(value) => setEditing({ ...editing, settlement_id: value })} />
            <TextField label="参保人群" value={editing.context.person_type ?? ''} onChange={(value) => setContext('person_type', value)} />
            <TextField label="险种" value={editing.context.insurance_type ?? ''} onChange={(value) => setContext('insurance_type', value)} />
            <TextField label="就医类别" value={editing.context.service_type ?? ''} onChange={(value) => setContext('service_type', value)} />
            <MoneyInput label="预期个人自付一" value={editing.expected_self_pay_one} onChange={(value) => setEditing({ ...editing, expected_self_pay_one: value })} />
            {MONEY_FIELDS.map(([field, label]) => (
              <MoneyInput key={field} label={label} value={editing.context[field] ?? ''} onChange={(value) => setContext(field as MoneyField, value)} />
            ))}
          </div>
          <label className="mt-3 block text-xs text-slate-600">
            备注
            <textarea
              value={editing.note}
              onChange={(event) => setEditing({ ...editing, note: event.target.value })}
              rows={2}
              className="mt-1 w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-sm"
            />
          </label>
          <div className="mt-3 flex items-center justify-between">
            <label className="flex items-center gap-2 text-xs text-slate-600">
              <input type="checkbox" checked={editing.enabled} onChange={(event) => setEditing({ ...editing, enabled: event.target.checked })} />
              启用此样例
            </label>
            <button
              type="button"
              onClick={() => void save()}
              disabled={busy || !editing.settlement_id || !editing.expected_self_pay_one}
              className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              <Save className="h-4 w-4" /> 保存样例
            </button>
          </div>
        </div>
      ) : null}
    </section>
  )
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="text-xs text-slate-600">
      {label}
      <input value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-sm" />
    </label>
  )
}

function MoneyInput({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="text-xs text-slate-600">
      {label}
      <input type="number" min="0" step="0.01" value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-sm" />
    </label>
  )
}
