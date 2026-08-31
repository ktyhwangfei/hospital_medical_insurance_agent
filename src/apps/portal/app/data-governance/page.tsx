'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { AlertTriangle, Clock3, Database, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { getDataGovernanceOverview, type DataGovernanceOverview } from '@/lib/data-governance-api'

const connectionLabel = { unknown: '未检测', healthy: '连接正常', error: '连接异常' }
const cdcLabel = {
  not_applicable: '不适用', not_checked: '未检测', waiting_dba: '等待 DBA', ready: '已就绪', invalid: '配置异常',
}
const syncLabel: Record<string, string> = {
  draft: '草稿', ready: '已启用', running: '运行中', paused: '已暂停', degraded: '需重建基线', failed: '执行失败',
}
const modeLabel = { cdc: 'CDC', scheduled_sql: '定时 SQL' }
const runKindLabel: Record<string, string> = {
  baseline: '首次基线', incremental: '增量', reconciliation: '夜间对账', manual: '立即执行',
}

function formatTime(value: string | null): string {
  return value ? new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(new Date(value)) : '暂无'
}

function Status({ label, tone = 'neutral' }: { label: string; tone?: 'good' | 'warn' | 'bad' | 'neutral' }) {
  const color = {
    good: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
    warn: 'bg-amber-50 text-amber-800 ring-amber-600/20',
    bad: 'bg-red-50 text-red-700 ring-red-600/20',
    neutral: 'bg-slate-100 text-slate-700 ring-slate-500/20',
  }[tone]
  return <span className={`inline-flex rounded-md px-2 py-1 text-xs font-medium ring-1 ring-inset ${color}`}>{label}</span>
}

function LoadingState() {
  return <div aria-label="正在加载数据治理概览" className="space-y-4">
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {[0, 1, 2, 3].map((item) => <div key={item} className="h-24 animate-pulse rounded-xl bg-slate-200/70" />)}
    </div>
    <div className="h-56 animate-pulse rounded-xl bg-slate-200/70" />
  </div>
}

export default function DataGovernanceOverviewPage() {
  const [overview, setOverview] = useState<DataGovernanceOverview | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const value = await getDataGovernanceOverview()
      setOverview(value)
      setError(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '数据治理服务暂不可用')
    }
  }, [])

  useEffect(() => {
    let active = true
    const load = async () => {
      if (!active) return
      await refresh()
    }
    void load()
    const timer = window.setInterval(() => { void load() }, 15_000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [refresh])

  if (!overview && !error) return <LoadingState />
  if (!overview && error) return <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-800">
    <div className="flex items-start gap-3">
      <AlertTriangle aria-hidden="true" className="mt-0.5 size-5 shrink-0" />
      <div>
        <p className="font-medium">概览加载失败</p>
        <p className="mt-1">{error}</p>
        <Button className="mt-4" variant="outline" onClick={() => void refresh()}>
          <RefreshCw aria-hidden="true" />重新加载
        </Button>
      </div>
    </div>
  </div>

  if (!overview) return null
  const metrics = [
    ['数据源', String(overview.dataSourceCount), '已登记医院门诊数据源'],
    ['运行任务', String(overview.runningJobCount), '已启用或正在执行'],
    ['待处理项', String(overview.issueCount), '需经办或运维处理'],
    ['最新延迟', overview.latestLatencySeconds === null ? '暂无' : `${Math.round(overview.latestLatencySeconds)} 秒`, '非空批次端到端延迟'],
  ]

  return <div aria-live="polite" className="space-y-5">
    <section aria-label="运行指标" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {metrics.map(([label, value, note]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <p className="text-sm font-medium text-slate-600">{label}</p>
        <p className="mt-2 font-mono text-2xl font-semibold tracking-tight text-slate-950">{value}</p>
        <p className="mt-1 text-xs text-slate-500">{note}</p>
      </div>)}
    </section>

    {overview.sources.length === 0 ? <section className="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center">
      <Database aria-hidden="true" className="mx-auto size-8 text-slate-400" />
      <h2 className="mt-3 text-base font-semibold text-slate-900">暂无数据源，请先新增</h2>
      <p className="mt-1 text-sm text-slate-600">登记医院 SQL Server 后，才能检测连接并配置同步。</p>
      <Link href="/data-governance/data-sources?create=1" className="mt-4 inline-flex h-8 items-center rounded-lg bg-slate-900 px-3 text-sm font-medium text-white hover:bg-slate-700">
        新增数据源
      </Link>
    </section> : <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h2 className="font-semibold text-slate-900">医院同步状态</h2>
        <span className="text-xs text-slate-500">每 15 秒刷新</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] text-left text-sm">
          <thead className="bg-slate-50 text-xs text-slate-600">
            <tr><th className="px-4 py-3 font-medium">医院与数据源</th><th className="px-4 py-3 font-medium">连接</th><th className="px-4 py-3 font-medium">CDC</th><th className="px-4 py-3 font-medium">同步</th><th className="px-4 py-3 font-medium">质量</th><th className="px-4 py-3 font-medium">最近成功</th><th className="px-4 py-3 font-medium">延迟</th></tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {overview.sources.map((source) => <tr key={source.sourceId} className="text-slate-700">
              <td className="px-4 py-3"><p className="font-medium text-slate-900">{source.hospitalName}</p><p className="mt-0.5 text-xs text-slate-500">{source.name} ({source.sourceId})</p></td>
              <td className="px-4 py-3"><Status label={connectionLabel[source.connectionStatus]} tone={source.connectionStatus === 'healthy' ? 'good' : source.connectionStatus === 'error' ? 'bad' : 'neutral'} /></td>
              <td className="px-4 py-3"><Status label={cdcLabel[source.cdcStatus]} tone={source.cdcStatus === 'ready' ? 'good' : source.cdcStatus === 'invalid' ? 'bad' : source.cdcStatus === 'waiting_dba' ? 'warn' : 'neutral'} /></td>
              <td className="px-4 py-3"><p>{source.sourceMode ? modeLabel[source.sourceMode] : '未配置'}</p><p className="mt-0.5 text-xs text-slate-500">{source.syncStatus ? syncLabel[source.syncStatus] ?? source.syncStatus : '未创建任务'}</p></td>
              <td className="px-4 py-3">{source.qualityStatus === 'accepted' ? <Status label="通过" tone="good" /> : source.qualityStatus === 'blocked' ? <Status label="已阻断" tone="bad" /> : <Status label="暂无" />}</td>
              <td className="whitespace-nowrap px-4 py-3">{formatTime(source.lastSucceededAt)}</td>
              <td className="whitespace-nowrap px-4 py-3 font-mono">{source.latestLatencySeconds === null ? '暂无' : `${Math.round(source.latestLatencySeconds)} 秒`}</td>
            </tr>)}
          </tbody>
        </table>
      </div>
    </section>}

    {overview.issues.length > 0 && <section className="rounded-xl border border-amber-200 bg-amber-50 p-4">
      <h2 className="flex items-center gap-2 font-semibold text-amber-950"><AlertTriangle aria-hidden="true" className="size-4" />待处理项</h2>
      <ul className="mt-3 grid gap-2 md:grid-cols-2">
        {overview.issues.map((issue) => <li key={`${issue.sourceId}-${issue.code}`} className="rounded-lg bg-white/70 px-3 py-2 text-sm text-amber-950">
          {issue.message}{issue.sourceId ? <span className="ml-2 text-xs text-amber-700">{issue.sourceId}</span> : null}
        </li>)}
      </ul>
    </section>}

    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-3">
        <Clock3 aria-hidden="true" className="size-4 text-slate-500" />
        <h2 className="font-semibold text-slate-900">最近运行</h2>
      </div>
      {overview.recentRuns.length === 0 ? <p className="px-4 py-8 text-center text-sm text-slate-500">暂无同步运行记录</p> : <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="bg-slate-50 text-xs text-slate-600"><tr><th className="px-4 py-3 font-medium">开始时间</th><th className="px-4 py-3 font-medium">数据源</th><th className="px-4 py-3 font-medium">类型</th><th className="px-4 py-3 font-medium">结果</th><th className="px-4 py-3 font-medium">行数</th><th className="px-4 py-3 font-medium">批次</th></tr></thead>
          <tbody className="divide-y divide-slate-100">{overview.recentRuns.map((run) => <tr key={run.attemptId}>
            <td className="whitespace-nowrap px-4 py-3">{formatTime(run.startedAt)}</td><td className="px-4 py-3">{run.sourceId}</td><td className="px-4 py-3">{modeLabel[run.sourceMode]} / {runKindLabel[run.runKind] ?? run.runKind}</td><td className="px-4 py-3"><Status label={run.status === 'succeeded' ? '成功' : run.status === 'running' ? '执行中' : '失败'} tone={run.status === 'succeeded' ? 'good' : run.status === 'failed' ? 'bad' : 'warn'} /></td><td className="px-4 py-3 font-mono">{run.rowCount}</td><td className="px-4 py-3 font-mono text-xs">{run.batchId ?? '暂无'}</td>
          </tr>)}</tbody>
        </table>
      </div>}
    </section>
  </div>
}
