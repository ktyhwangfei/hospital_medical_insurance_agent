'use client'

// 费用分解工作台 /fee-decomposition — Issue #78 四链路页面可用化（Phase 3）。
// 治理/验证支撑页（同 ops-analytics 先例，不改变 /policy-qa 唯一业务入口定位）：
// 输入交易号（普通门诊）、门特登记号 djh 或身份证号，单笔实时分解，无持久化。
// 身份证号输入走按人定位（resolve-person）列出该人员候选，点击候选后再分解。
// 险种（职工/居民）由数据自动判定（普通门诊取交易行险种码，门特取唯一登记行险种码），链路仅区分普通门诊/门特。
import { useState } from 'react'
import { Calculator, Loader2, Search } from 'lucide-react'
import {
  decomposeFee,
  looksLikeIdCard,
  resolvePerson,
  type FeeDecompositionChain,
  type FeeDecompositionResponseDto,
  type PersonCandidateDto,
  type ResolvePersonResponseDto,
} from '@/lib/fee-decomposition-api'
import { toFeeDecomposition } from '@/lib/policy-qa-stream'
import { ApiClientError } from '@/lib/types'
import SettlementSummaryTable from '@/components/policy-qa/settlement-summary-table'
import FeeDetailTable from '@/components/policy-qa/fee-detail-table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

const CHAIN_OPTIONS: Array<{ value: FeeDecompositionChain; label: string }> = [
  { value: 'auto', label: '自动识别' },
  { value: 'outpatient', label: '普通门诊（交易号）' },
  { value: 'special', label: '门诊特殊病（登记号 djh）' },
]

interface QueryError {
  status: number | null
  errorCode: string
  message: string
}

function toQueryError(e: unknown): QueryError {
  if (e instanceof ApiClientError) {
    return { status: e.status, errorCode: e.detail.error_code, message: e.detail.message }
  }
  return {
    status: null,
    errorCode: 'REQUEST_FAILED',
    message: e instanceof Error ? e.message : String(e),
  }
}

export default function FeeDecompositionPage() {
  const [identifier, setIdentifier] = useState('')
  const [chain, setChain] = useState<FeeDecompositionChain>('auto')
  const [result, setResult] = useState<FeeDecompositionResponseDto | null>(null)
  const [personLookup, setPersonLookup] = useState<ResolvePersonResponseDto | null>(null)
  const [error, setError] = useState<QueryError | null>(null)
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState('summary')

  async function submit() {
    const value = identifier.trim()
    if (!value || loading) return
    setLoading(true)
    setError(null)
    setResult(null)
    setPersonLookup(null)
    setTab('summary')
    try {
      if (looksLikeIdCard(value)) {
        // 身份证号 → 按人定位，列出该人员门诊交易/门特登记候选
        setPersonLookup(await resolvePerson(value))
      } else {
        setResult(await decomposeFee(value, chain))
      }
    } catch (e) {
      setError(toQueryError(e))
    } finally {
      setLoading(false)
    }
  }

  // 点击候选：用候选自带 identifier + chain 发起分解；保留候选列表便于切换
  async function pickCandidate(candidate: PersonCandidateDto) {
    if (loading) return
    setLoading(true)
    setError(null)
    setResult(null)
    setTab('summary')
    try {
      setResult(await decomposeFee(candidate.identifier, candidate.chain))
    } catch (e) {
      setError(toQueryError(e))
    } finally {
      setLoading(false)
    }
  }

  const decomposition = result ? toFeeDecomposition(result) : undefined
  const notConfigured = error?.status === 503

  return (
    <div className="mx-auto max-w-4xl space-y-5" data-testid="fee-decomposition-page">
      <header className="flex flex-wrap items-center gap-3">
        <span className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-slate-900 px-2.5 py-2 text-white">
          <Calculator className="size-4" />
          费用分解
        </span>
        <div className="min-w-0">
          <h1 className="text-sm font-semibold">费用分解与结算解释</h1>
          <p className="text-xs text-slate-500">
            查询本单基金与个人支付比例、待遇条件及每项费用的比例或限价；险种由原单自动识别
          </p>
        </div>
        <span className="ml-auto rounded bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700 ring-1 ring-amber-200">
          候选口径·待业务签核
        </span>
      </header>

      <form
        className="flex flex-wrap items-center gap-2"
        data-testid="fee-decomposition-form"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <input
          type="text"
          aria-label="交易号、门特登记号或身份证号"
          value={identifier}
          onChange={(e) => setIdentifier(e.target.value)}
          placeholder="交易号（如 T 开头流水号）、门特登记号 djh（如 604）或身份证号（按人列出候选）"
          className="min-w-0 basis-full rounded-md border border-slate-200 px-3 py-2 font-mono text-sm focus:border-slate-400 focus:outline-none sm:flex-1 sm:basis-0"
          data-testid="fee-decomposition-identifier"
        />
        <select
          aria-label="结算链路"
          value={chain}
          onChange={(e) => setChain(e.target.value as FeeDecompositionChain)}
          className="rounded-md border border-slate-200 px-2 py-2 text-sm"
          data-testid="fee-decomposition-chain"
        >
          {CHAIN_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={!identifier.trim() || loading}
          className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-2 text-sm text-white hover:bg-slate-700 disabled:opacity-40"
          data-testid="fee-decomposition-submit"
        >
          {loading ? <Loader2 className="size-4 animate-spin" /> : <Search className="size-4" />}
          分解
        </button>
      </form>

      {error ? (
        <div
          className={`rounded-md border p-3 text-xs ${
            notConfigured
              ? 'border-amber-200 bg-amber-50 text-amber-800'
              : 'border-red-200 bg-red-50 text-red-700'
          }`}
          data-testid="fee-decomposition-error"
        >
          <div className="font-semibold">
            {notConfigured ? '费用分解功能未配置' : '查询失败'}
            <span className="ml-2 rounded bg-white/70 px-1.5 py-0.5 font-mono text-[10px]">
              {error.errorCode}
            </span>
          </div>
          <div className="mt-1 leading-snug">{error.message}</div>
        </div>
      ) : null}

      {personLookup ? (
        <div
          className="space-y-2 rounded-md border border-slate-200 bg-white p-3"
          data-testid="person-candidates"
        >
          <div className="text-xs font-semibold text-slate-700">
            该身份证号匹配到的候选记录
            {personLookup.match_status === 'unique_match' ? '（唯一匹配，点击确认分解）' : ''}
          </div>
          {personLookup.truncated ? (
            <div
              className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] text-amber-800"
              data-testid="person-candidates-truncated"
            >
              结果过多已截断，请改用交易号/登记号精确查询
            </div>
          ) : null}
          {personLookup.match_status === 'no_match' || personLookup.candidates.length === 0 ? (
            <div className="text-xs text-slate-500" data-testid="person-candidates-empty">
              未找到该人员的门诊交易/门特登记
            </div>
          ) : (
            <ul className="divide-y divide-slate-100">
              {personLookup.candidates.map((candidate) => (
                <li key={`${candidate.chain}:${candidate.identifier}`}>
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => void pickCandidate(candidate)}
                    className="flex w-full flex-wrap items-center gap-x-3 gap-y-0.5 px-1 py-2 text-left text-xs hover:bg-slate-50 disabled:opacity-50"
                    data-testid={`person-candidate-${candidate.chain}-${candidate.identifier}`}
                  >
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">
                      {candidate.chain_label}
                    </span>
                    <span className="text-slate-600">{candidate.profile_label}</span>
                    <span className="text-slate-500">{candidate.service_date ?? '—'}</span>
                    <span className="text-slate-500">
                      {candidate.total_amount != null ? `¥${candidate.total_amount}` : '—'}
                    </span>
                    <span className="ml-auto font-mono text-slate-700">
                      {candidate.identifier}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}

      {result && decomposition ? (
        <div className="space-y-5" data-testid="fee-decomposition-result">
          {decomposition.executionStatus === 'unavailable' ? (
            <p className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800" data-testid="fee-decomposition-unavailable">
              暂无法分解：{decomposition.uncertainties.find((gap) => !gap.code.includes('ROUNDING'))?.message || '结算依据尚不完整。'}
            </p>
          ) : null}
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList aria-label="交易信息与交易明细" variant="line" className="mb-2 h-10">
              <TabsTrigger value="summary" className="px-4">交易信息</TabsTrigger>
              {(decomposition.feeItems?.length ?? 0) > 0 ? (
                <TabsTrigger value="detail" className="px-4">交易明细</TabsTrigger>
              ) : null}
            </TabsList>
            <TabsContent value="summary">
              <SettlementSummaryTable key={`summary-${result.meta.identifier}`} decomposition={decomposition} identifier={result.meta.identifier} />
            </TabsContent>
            {(decomposition.feeItems?.length ?? 0) > 0 ? (
              <TabsContent value="detail">
                <FeeDetailTable decomposition={decomposition} />
              </TabsContent>
            ) : null}
          </Tabs>
        </div>
      ) : result ? (
        <div
          className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-700"
          data-testid="fee-decomposition-error"
        >
          后端响应未通过公开契约校验，未展示未经核验的内容。
        </div>
      ) : null}
    </div>
  )
}
