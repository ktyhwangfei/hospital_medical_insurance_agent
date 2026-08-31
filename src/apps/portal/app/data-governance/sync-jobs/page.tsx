'use client'

import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { CircleAlert, Pause, Play, RefreshCw, Save } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  getSyncJob,
  listDataSources,
  listSyncRuns,
  pauseSyncJob,
  runSyncJobOnce,
  saveSyncJob,
  startSyncJob,
  type DataSource,
  type SourceMode,
  type SyncJob,
  type SyncRun,
} from '@/lib/data-governance-api'

interface FormState {
  sourceMode: SourceMode
  cdcPollIntervalSeconds: number
  scheduleIntervalMinutes: number
  lookbackHours: number
  reconcileTime: string
  reconcileDays: number
  confirmModeSwitch: boolean
}

const defaults: FormState = {
  sourceMode: 'cdc', cdcPollIntervalSeconds: 45, scheduleIntervalMinutes: 5,
  lookbackHours: 2, reconcileTime: '02:00', reconcileDays: 30, confirmModeSwitch: false,
}
const inputClass = 'h-9 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-100 disabled:text-slate-500'
const modeLabel = { cdc: 'CDC', scheduled_sql: '定时 SQL' }
const statusLabel: Record<string, string> = { draft: '草稿', ready: '已启用', running: '运行中', paused: '已暂停', degraded: '需重建基线', failed: '执行失败' }
const runKindLabel: Record<string, string> = { baseline: '首次基线', incremental: '增量', reconciliation: '夜间对账', manual: '立即执行' }

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="grid gap-1.5 text-sm font-medium text-slate-700"><span>{label}</span>{children}</label>
}

function safeMessage(error: unknown) {
  return error instanceof Error ? error.message : '操作失败，请稍后重试'
}

function timeText(value: string | null) {
  return value ? new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(new Date(value)) : '暂无'
}

export default function SyncJobsPage() {
  const [sources, setSources] = useState<DataSource[]>([])
  const [sourceId, setSourceId] = useState('')
  const [job, setJob] = useState<SyncJob | null>(null)
  const [runs, setRuns] = useState<SyncRun[]>([])
  const [form, setForm] = useState<FormState>(defaults)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void listDataSources().then((items) => {
      setSources(items)
      setSourceId((value) => value || items[0]?.sourceId || '')
    }, (reason) => setError(safeMessage(reason)))
  }, [])

  const loadJob = useCallback(async (selected: string) => {
    if (!selected) {
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const [nextJob, nextRuns] = await Promise.all([getSyncJob(selected), listSyncRuns(selected)])
      setJob(nextJob)
      setRuns(nextRuns)
      setForm(nextJob ? {
        sourceMode: nextJob.sourceMode,
        cdcPollIntervalSeconds: nextJob.cdcPollIntervalSeconds,
        scheduleIntervalMinutes: nextJob.scheduleIntervalMinutes,
        lookbackHours: nextJob.lookbackHours,
        reconcileTime: nextJob.reconcileTime.slice(0, 5),
        reconcileDays: nextJob.reconcileDays,
        confirmModeSwitch: false,
      } : defaults)
      setError(null)
    } catch (reason) {
      setError(safeMessage(reason))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadJob(sourceId) }, 0)
    return () => window.clearTimeout(timer)
  }, [loadJob, sourceId])

  const selectedSource = sources.find((source) => source.sourceId === sourceId) ?? null
  const running = job?.status === 'running' || job?.status === 'ready'
  const modeChanged = Boolean(job && job.sourceMode !== form.sourceMode)
  const cdcBlocked = form.sourceMode === 'cdc' && selectedSource?.cdcStatus !== 'ready'

  const save = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const saved = await saveSyncJob(sourceId, {
        ...form,
        expectedRevision: job?.revision ?? 1,
        reconcileTime: `${form.reconcileTime}:00`,
      })
      setJob(saved)
      setMessage('同步配置已保存')
    } catch (reason) {
      setError(safeMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  const action = async (kind: 'start' | 'pause' | 'run') => {
    setBusy(true)
    setError(null)
    try {
      const updated = kind === 'start'
        ? await startSyncJob(sourceId)
        : kind === 'pause'
          ? await pauseSyncJob(sourceId)
          : await runSyncJobOnce(sourceId)
      setJob(updated)
      setMessage(kind === 'run' ? '已请求，worker 将按队列执行' : kind === 'start' ? '任务已启动' : '任务已暂停')
      setRuns(await listSyncRuns(sourceId))
    } catch (reason) {
      setError(safeMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  if (sources.length === 0 && !loading) return <section className="rounded-xl border border-dashed border-slate-300 bg-white py-12 text-center"><p className="font-medium text-slate-800">请先新增数据源</p><p className="mt-1 text-sm text-slate-500">同步任务必须绑定受控 SQL Server 数据源。</p></section>

  return <div className="space-y-5">
    <div><h2 className="font-semibold text-slate-900">同步任务</h2><p className="mt-1 text-sm text-slate-600">CDC 不可开通时可选定时 SQL，两个模式共用 PostgreSQL 标准化数据。</p></div>
    {(message || error) && <div role={error ? 'alert' : 'status'} className={`rounded-lg border px-4 py-3 text-sm ${error ? 'border-red-200 bg-red-50 text-red-800' : 'border-emerald-200 bg-emerald-50 text-emerald-800'}`}>{error ?? message}</div>}

    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-slate-200 pb-4">
        <Field label="医院数据源"><select className={`${inputClass} min-w-64`} value={sourceId} onChange={(event) => setSourceId(event.target.value)}>{sources.map((source) => <option key={source.sourceId} value={source.sourceId}>{source.hospitalName} / {source.name}</option>)}</select></Field>
        <div className="text-right"><p className="text-xs text-slate-500">当前状态</p><p className="mt-1 text-sm font-medium text-slate-900">{job ? statusLabel[job.status] ?? job.status : '未创建任务'}</p></div>
      </div>

      {loading ? <p className="py-12 text-center text-sm text-slate-500">正在读取任务...</p> : <form onSubmit={save} className="space-y-5 pt-5">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Field label="同步方式"><select className={inputClass} disabled={running} value={form.sourceMode} onChange={(event) => setForm({ ...form, sourceMode: event.target.value as SourceMode, confirmModeSwitch: false })}><option value="cdc">CDC</option><option value="scheduled_sql">定时 SQL</option></select></Field>
          {form.sourceMode === 'cdc' ? <Field label="轮询间隔（秒）"><input className={inputClass} type="number" min={30} max={60} value={form.cdcPollIntervalSeconds} onChange={(event) => setForm({ ...form, cdcPollIntervalSeconds: Number(event.target.value) })} /></Field> : <>
            <Field label="执行周期（分钟）"><input className={inputClass} type="number" min={1} max={1440} value={form.scheduleIntervalMinutes} onChange={(event) => setForm({ ...form, scheduleIntervalMinutes: Number(event.target.value) })} /></Field>
            <Field label="回看窗口（小时）"><input className={inputClass} type="number" min={1} max={168} value={form.lookbackHours} onChange={(event) => setForm({ ...form, lookbackHours: Number(event.target.value) })} /></Field>
            <Field label="对账范围（天）"><input className={inputClass} type="number" min={1} max={365} value={form.reconcileDays} onChange={(event) => setForm({ ...form, reconcileDays: Number(event.target.value) })} /></Field>
            <Field label="本地对账时间"><input className={inputClass} type="time" value={form.reconcileTime} onChange={(event) => setForm({ ...form, reconcileTime: event.target.value })} /></Field>
          </>}
        </div>

        {form.sourceMode === 'scheduled_sql' && <div className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><CircleAlert className="mt-0.5 size-4 shrink-0" /><p>定时 SQL 通过重叠回看和每日对账实现最终一致，不提供任意 SQL 编辑，默认 5 分钟执行一次。</p></div>}
        {cdcBlocked && <p className="text-sm text-red-700">CDC 尚未就绪。请先在“数据源”页下载脚本并由 DBA 执行，再重新检测。</p>}
        {modeChanged && <label className="flex items-start gap-2 text-sm text-slate-700"><input type="checkbox" className="mt-1" checked={form.confirmModeSwitch} onChange={(event) => setForm({ ...form, confirmModeSwitch: event.target.checked })} /><span>确认切换同步模式。下次运行将重新建立基线。</span></label>}

        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={busy || running || (modeChanged && !form.confirmModeSwitch)}><Save />保存配置</Button>
          <Button type="button" variant="outline" disabled={busy || !job || running || cdcBlocked} onClick={() => void action('start')}><Play />启动任务</Button>
          <Button type="button" variant="outline" disabled={busy || !job || !running} onClick={() => void action('pause')}><Pause />暂停任务</Button>
          <Button type="button" variant="outline" disabled={busy || !job || !running} onClick={() => void action('run')}><RefreshCw />立即执行</Button>
        </div>
      </form>}
    </section>

    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-4 py-3"><h2 className="font-semibold text-slate-900">运行记录</h2></div>
      {runs.length === 0 ? <p className="py-10 text-center text-sm text-slate-500">暂无运行记录</p> : <div className="overflow-x-auto"><table className="w-full min-w-[860px] text-left text-sm">
        <thead className="bg-slate-50 text-xs text-slate-600"><tr><th className="px-4 py-3 font-medium">开始</th><th className="px-4 py-3 font-medium">结束</th><th className="px-4 py-3 font-medium">模式</th><th className="px-4 py-3 font-medium">类型</th><th className="px-4 py-3 font-medium">结果</th><th className="px-4 py-3 font-medium">行数</th><th className="px-4 py-3 font-medium">批次</th><th className="px-4 py-3 font-medium">安全错误</th></tr></thead>
        <tbody className="divide-y divide-slate-100">{runs.map((run) => <tr key={run.attemptId}><td className="whitespace-nowrap px-4 py-3">{timeText(run.startedAt)}</td><td className="whitespace-nowrap px-4 py-3">{timeText(run.finishedAt)}</td><td className="px-4 py-3">{modeLabel[run.sourceMode]}</td><td className="px-4 py-3">{runKindLabel[run.runKind] ?? run.runKind}</td><td className="px-4 py-3">{run.status === 'succeeded' ? '成功' : run.status === 'running' ? '执行中' : '失败'}</td><td className="px-4 py-3 font-mono">{run.rowCount}</td><td className="px-4 py-3 font-mono text-xs">{run.batchId ?? '暂无'}</td><td className="px-4 py-3 text-red-700">{run.safeMessage ?? '无'}</td></tr>)}</tbody>
      </table></div>}
    </section>
  </div>
}
