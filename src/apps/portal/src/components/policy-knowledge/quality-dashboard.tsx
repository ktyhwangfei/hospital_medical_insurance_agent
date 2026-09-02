'use client'

import { useState } from 'react'
import { ArrowRight, CheckCircle2, FlaskConical, LockKeyhole, Rocket, ShieldAlert } from 'lucide-react'

import type { Issue25Metrics, KnowledgeRelease, QualityCaseResult, QualityRun } from '@/lib/policy-knowledge-api'

export function QualityDashboard({ releases, activeRelease, latestRun, currentCaseSetVersion, caseResults = [], issue25Metrics = null, onSelectRelease, onRun, onPromote, onRollback }: {
  releases: KnowledgeRelease[]
  activeRelease: KnowledgeRelease | null
  latestRun: QualityRun | null
  currentCaseSetVersion: number
  caseResults?: QualityCaseResult[]
  issue25Metrics?: Issue25Metrics | null
  onSelectRelease?: (releaseId: string) => void
  onRun: (releaseId: string) => void
  onPromote: (releaseId: string) => void
  onRollback?: (releaseId: string) => void
}) {
  const candidates = releases.filter((release) => release.status !== 'active' && release.status !== 'retired')
  const [releaseId, setReleaseId] = useState(candidates[0]?.release_id || '')
  const effectiveReleaseId = candidates.some((item) => item.release_id === releaseId) ? releaseId : candidates[0]?.release_id || ''
  const selected = candidates.find((release) => release.release_id === effectiveReleaseId)
  const run = latestRun?.release_id === effectiveReleaseId ? latestRun : null
  const canPublish = selected?.status === 'passed'
    && run?.status === 'passed'
    && run.release_id === selected.release_id
    && run.case_set_version === selected.case_set_version
    && run.case_set_version === currentCaseSetVersion
    && run.config_hash === selected.config_hash
  const failedCases = caseResults.filter((item) => item.target === 'candidate' && !item.passed)
  const caseDiffs = buildCaseDiffs(caseResults)

  return <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
    <div className="flex flex-wrap items-start gap-3">
      <div><p className="flex items-center gap-1.5 text-xs font-semibold text-violet-700"><FlaskConical className="size-4" />统一质量门禁</p><h3 className="mt-1 text-base font-semibold text-slate-900">候选版与活动版同集对跑</h3><p className="mt-1 text-xs text-slate-500">相同用例、相同配置、至少重复 3 次；测试不会自动发布。</p></div>
      <select aria-label="选择候选版本" value={effectiveReleaseId} onChange={(event) => { setReleaseId(event.target.value); onSelectRelease?.(event.target.value) }} className="ml-auto rounded-lg border border-slate-200 px-3 py-2 text-xs">
        {!candidates.length && <option value="">暂无候选版本</option>}
        {candidates.map((release) => <option key={release.release_id} value={release.release_id}>{release.release_id} · {statusLabel(release.status)}</option>)}
      </select>
    </div>

    <div className="mt-5 grid items-stretch gap-3 md:grid-cols-[1fr_auto_1fr]">
      <ReleaseCard label="候选版本" release={selected || null} accent="violet" />
      <div className="flex items-center justify-center"><ArrowRight className="size-5 text-slate-300" /></div>
      <ReleaseCard label="当前活动版本" release={activeRelease} accent="blue" />
    </div>

    {run && <div className={`mt-4 rounded-xl border p-4 ${run.status === 'passed' ? 'border-emerald-200 bg-emerald-50/60' : 'border-red-200 bg-red-50/60'}`}>
      <div className="flex items-center gap-2">
        {run.status === 'passed' ? <CheckCircle2 className="size-4 text-emerald-600" /> : <ShieldAlert className="size-4 text-red-600" />}
        <p className={`text-xs font-semibold ${run.status === 'passed' ? 'text-emerald-700' : 'text-red-700'}`}>{run.status === 'passed' ? '测试通过，待人工发布' : '质量门禁未通过'}</p>
        <span className="ml-auto text-[10px] text-slate-400">重复 {run.repeat_count} 次</span>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2">
        <Metric label="候选质量" value={run.candidate_score} />
        <Metric label="活动版质量" value={run.baseline_score} />
        <Metric label="重复一致性" value={run.consistency_score} />
      </div>
      <ComparisonBars candidate={run.candidate_score} baseline={run.baseline_score} />
      {!!run.blocked_reasons.length && <ul className="mt-3 space-y-1 text-xs text-red-700">{run.blocked_reasons.map((reason) => <li key={reason}>· {reason}</li>)}</ul>}
      {!!failedCases.length && <div className="mt-3"><p className="text-[11px] font-semibold text-red-800">逐用例失败明细</p><ul className="mt-1 space-y-1 text-[11px] text-red-700">{failedCases.map((item) => <li key={`${item.case_id}-${item.repeat_index}`}>{item.case_id} · 第 {item.repeat_index + 1} 次 · 得分 {Math.round(item.score * 100)}% · {JSON.stringify(item.diagnostics)}</li>)}</ul></div>}
      {!!caseDiffs.length && <div className="mt-3 rounded-lg bg-white/70 p-3"><p className="text-[11px] font-semibold text-slate-700">候选 / 基线逐案 diff</p><ul className="mt-2 space-y-1 font-mono text-[10px] text-slate-600">{caseDiffs.map((item) => <li key={`${item.caseId}-${item.repeatIndex}`}>{item.caseId} #{item.repeatIndex + 1} · 候选 [{item.candidateIds.join(', ') || '—'}] ({pctValue(item.candidateScore)}) → 基线 [{item.baselineIds.join(', ') || '—'}] ({pctValue(item.baselineScore)})</li>)}</ul></div>}
    </div>}

    <div className="mt-4 flex flex-wrap justify-end gap-2">
      <button type="button" disabled={!selected || selected.status !== 'ready'} onClick={() => selected && onRun(selected.release_id)} className="flex items-center gap-1.5 rounded-lg border border-violet-200 px-3 py-2 text-xs font-semibold text-violet-700 disabled:cursor-not-allowed disabled:opacity-40"><FlaskConical className="size-3.5" />批量统一测试</button>
      <button type="button" aria-label="人工发布候选版本" disabled={!canPublish} onClick={() => selected && onPromote(selected.release_id)} className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300">
        {canPublish ? <Rocket className="size-3.5" /> : <LockKeyhole className="size-3.5" />}人工发布候选版本
      </button>
    </div>

    {issue25Metrics && <Issue25MetricsCard metrics={issue25Metrics} />}

    <div className="mt-5 border-t border-slate-100 pt-4"><p className="text-xs font-semibold text-slate-700">发布与回滚历史</p><div className="mt-2 space-y-2">{releases.filter((release) => release.status === 'active' || release.status === 'retired').map((release) => <div key={release.release_id} className="flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-[11px]"><span className="font-mono text-slate-700">{release.release_id}</span><span className="text-slate-400">{statusLabel(release.status)}</span>{release.status === 'retired' && onRollback && <button type="button" aria-label={`回滚到 ${release.release_id}`} onClick={() => onRollback(release.release_id)} className="ml-auto rounded border border-amber-200 px-2 py-1 font-semibold text-amber-700">回滚</button>}</div>)}</div></div>
  </section>
}

function Issue25MetricsCard({ metrics }: { metrics: Issue25Metrics }) {
  const baselines = [
    { key: 'text_only', label: '纯文本召回' },
    { key: 'current_hybrid', label: '当前混合检索' },
    { key: 'enhanced_hybrid', label: '补强适用性字段' },
    { key: 'broad_hybrid', label: '宽泛问题混合检索' },
  ] as const

  const formatPct = (value: number | undefined) => value === undefined ? '—' : `${Math.round(value * 100)}%`
  const formatMs = (value: number | undefined) => value === undefined ? '—' : `${value.toFixed(2)}ms`

  return <div className="mt-5 rounded-xl border border-indigo-200 bg-indigo-50/40 p-4">
    <div className="flex items-center gap-2">
      <FlaskConical className="size-4 text-indigo-600" />
      <p className="text-xs font-semibold text-indigo-700">Issue #25 专项检索指标</p>
      <span className="ml-auto text-[10px] text-slate-400">{metrics.run_at} · {metrics.embedding_kind} · {metrics.case_count} 用例</span>
    </div>
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="text-left text-slate-500">
            <th className="pb-2 font-medium">基线</th>
            <th className="pb-2 font-medium">P@3</th>
            <th className="pb-2 font-medium">R@3</th>
            <th className="pb-2 font-medium">FAR</th>
            <th className="pb-2 font-medium">完整回答率</th>
            <th className="pb-2 font-medium">诚实拒答率</th>
            <th className="pb-2 font-medium">P95 时延</th>
          </tr>
        </thead>
        <tbody>
          {baselines.map(({ key, label }) => {
            const m = metrics[key]
            return <tr key={key} className="border-t border-indigo-100">
              <td className="py-2 font-medium text-slate-700">{label}</td>
              <td className="py-2">{formatPct(m.precision_at_k)}</td>
              <td className="py-2">{formatPct(m.recall)}</td>
              <td className="py-2 text-red-700">{formatPct(m.far)}</td>
              <td className="py-2">{formatPct(m.complete_rate)}</td>
              <td className="py-2">{formatPct(m.honest_refusal_rate)}</td>
              <td className="py-2">{formatMs(m.p95_latency_ms)}</td>
            </tr>
          })}
        </tbody>
      </table>
    </div>
    <div className="mt-3 grid grid-cols-3 gap-2">
      <div className="rounded-lg bg-white/80 p-2 text-center">
        <p className="text-[10px] text-slate-400">字段完整率</p>
        <p className="mt-1 text-sm font-bold text-slate-800">{formatPct(metrics.field_quality_score)}</p>
      </div>
      <div className="rounded-lg bg-white/80 p-2 text-center">
        <p className="text-[10px] text-slate-400">语料规模</p>
        <p className="mt-1 text-sm font-bold text-slate-800">{metrics.corpus_size}</p>
      </div>
      <div className="rounded-lg bg-white/80 p-2 text-center">
        <p className="text-[10px] text-slate-400">用例数</p>
        <p className="mt-1 text-sm font-bold text-slate-800">{metrics.case_count}</p>
      </div>
    </div>
    {metrics.top_diff_cases.length > 0 && <div className="mt-3 rounded-lg bg-white/70 p-3">
      <p className="text-[11px] font-semibold text-slate-700">Top 差异用例（补强 - 当前）</p>
      <ul className="mt-2 space-y-1 font-mono text-[10px] text-slate-600">
        {metrics.top_diff_cases.slice(0, 3).map((item) => <li key={item.case_id}>
          {item.case_id} · P+{Math.round(item.precision_diff * 100)}% R+{Math.round(item.recall_diff * 100)}% · {item.scenario}
        </li>)}
      </ul>
    </div>}
  </div>
}

function buildCaseDiffs(results: QualityCaseResult[]) {
  const grouped = new Map<string, { caseId: string; repeatIndex: number; candidateIds: string[]; baselineIds: string[]; candidateScore: number | null; baselineScore: number | null }>()
  for (const result of results) {
    const key = `${result.case_id}:${result.repeat_index}`
    const item = grouped.get(key) || { caseId: result.case_id, repeatIndex: result.repeat_index, candidateIds: [], baselineIds: [], candidateScore: null, baselineScore: null }
    if (result.target === 'candidate') { item.candidateIds = result.result_knowledge_ids; item.candidateScore = result.score }
    else { item.baselineIds = result.result_knowledge_ids; item.baselineScore = result.score }
    grouped.set(key, item)
  }
  return [...grouped.values()]
}

const pctValue = (value: number | null) => value === null ? '—' : `${Math.round(value * 100)}%`

function ReleaseCard({ label, release, accent }: { label: string; release: KnowledgeRelease | null; accent: 'violet' | 'blue' }) {
  return <div className={`rounded-xl border p-3 ${accent === 'violet' ? 'border-violet-200 bg-violet-50/50' : 'border-blue-200 bg-blue-50/50'}`}><p className="text-[10px] text-slate-400">{label}</p>{release ? <><p className="mt-1 font-mono text-xs font-semibold text-slate-700">{release.release_id}</p><p className="mt-2 text-[11px] text-slate-500">契约 v{release.contract_version} · 用例集 v{release.case_set_version}</p><span className="mt-2 inline-block rounded bg-white px-1.5 py-0.5 text-[10px] font-semibold text-slate-600">{statusLabel(release.status)}</span></> : <p className="mt-4 text-xs text-slate-400">暂无版本</p>}</div>
}

function Metric({ label, value }: { label: string; value: number | null }) {
  return <div className="rounded-lg bg-white/80 p-2 text-center"><p className="text-[10px] text-slate-400">{label}</p><p className="mt-1 text-sm font-bold text-slate-800">{value === null ? '—' : `${Math.round(value * 100)}%`}</p></div>
}

function ComparisonBars({ candidate, baseline }: { candidate: number | null; baseline: number | null }) {
  return <div className="mt-3 space-y-2 rounded-lg bg-white/80 p-3">
    <QualityBar label="候选版本质量" value={candidate} color="bg-violet-500" />
    <QualityBar label="活动版本质量" value={baseline} color="bg-blue-500" />
  </div>
}

function QualityBar({ label, value, color }: { label: string; value: number | null; color: string }) {
  const percent = Math.round((value || 0) * 100)
  return <div className="grid grid-cols-[5rem_1fr_2.5rem] items-center gap-2 text-[10px] text-slate-500"><span>{label}</span><div className="h-2 overflow-hidden rounded-full bg-slate-100"><div aria-label={`${label} ${percent}%`} className={`h-full rounded-full ${color}`} style={{ width: `${percent}%` }} /></div><span className="text-right font-semibold text-slate-700">{value === null ? '—' : `${percent}%`}</span></div>
}

function statusLabel(status: KnowledgeRelease['status']) {
  return ({ building: '构建中', ready: '待测试', testing: '测试中', passed: '已通过', failed: '未通过', active: '使用中', retired: '已退役' })[status]
}
