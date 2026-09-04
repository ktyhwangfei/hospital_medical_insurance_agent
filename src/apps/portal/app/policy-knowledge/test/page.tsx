'use client'

import { FormEvent, useCallback, useEffect, useState } from 'react'
import { Database, Loader2, Plus, Search, ShieldCheck } from 'lucide-react'

import { AnswerVerificationPanel } from '@/components/policy-qa/answer-verification-panel'
import { QualityDashboard } from '@/components/policy-knowledge/quality-dashboard'
import {
  createRelease,
  buildRelease,
  getActiveRelease,
  getIssue25Metrics,
  getLatestReleaseQuality,
  listReleases,
  listQualityCaseResults,
  listTestCases,
  promoteRelease,
  rollbackRelease,
  runQuality,
  saveTestCase,
  searchPolicyKnowledge,
  type Issue25Metrics,
  type KnowledgeRelease,
  type PolicyTestCase,
  type QualityCaseResult,
  type QualityRun,
  QUALITY_CONFIG_HASH,
  QUALITY_RUN_CONFIG,
} from '@/lib/policy-knowledge-api'

type Mode = 'precise' | 'semantic' | 'hybrid'
type Target = 'policy' | 'database' | 'both'
const FILTERS = ['rule_type', 'insu_type', 'med_type', 'hosp_lv', 'psn_type', 'setl_type']

export default function PolicyKnowledgeTestPage() {
  const [releases, setReleases] = useState<KnowledgeRelease[]>([])
  const [activeRelease, setActiveRelease] = useState<KnowledgeRelease | null>(null)
  const [cases, setCases] = useState<PolicyTestCase[]>([])
  const [latestRun, setLatestRun] = useState<QualityRun | null>(null)
  const [caseResults, setCaseResults] = useState<QualityCaseResult[]>([])
  const [issue25Metrics, setIssue25Metrics] = useState<Issue25Metrics | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const refresh = useCallback(async () => {
    setError('')
    try {
      const [releaseItems, caseItems, active] = await Promise.all([
        listReleases(), listTestCases(), getActiveRelease().catch(() => null),
      ])
      setReleases(releaseItems); setCases(caseItems); setActiveRelease(active)
      const candidate = releaseItems.find((item) => !['active', 'retired'].includes(item.status))
      if (candidate) await restoreQuality(candidate.release_id)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '测试页加载失败') }
  }, [])
  useEffect(() => {
    void Promise.all([
      listReleases(),
      listTestCases(),
      getActiveRelease().catch(() => null),
      getIssue25Metrics('hash').catch(() => null),
    ])
      .then(([releaseItems, caseItems, active, metrics]) => {
        setReleases(releaseItems); setCases(caseItems); setActiveRelease(active)
        if (metrics) setIssue25Metrics(metrics)
        const candidate = releaseItems.find((item) => !['active', 'retired'].includes(item.status))
        if (candidate) void restoreQuality(candidate.release_id)
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : '测试页加载失败'))
  }, [])

  async function restoreQuality(releaseId: string) {
    try {
      const report = await getLatestReleaseQuality(releaseId)
      setLatestRun(report.run); setCaseResults(report.case_results)
    } catch {
      setLatestRun(null); setCaseResults([])
    }
  }

  async function run(releaseId: string) {
    setBusy('run'); setError('')
    try { const result = await runQuality(releaseId); setLatestRun(result); setCaseResults(await listQualityCaseResults(result.run_id)); await refresh() }
    catch (reason) { setError(reason instanceof Error ? reason.message : '统一测试失败') }
    finally { setBusy('') }
  }

  async function rollback(releaseId: string) {
    if (!window.confirm(`确认将整批活动版本回滚到 ${releaseId}？`)) return
    const reviewer = window.prompt('请输入回滚审核人：')
    if (!reviewer) return
    setBusy('rollback'); setError('')
    try { await rollbackRelease(releaseId, reviewer); setNotice(`已原子回滚到 ${releaseId}`); await refresh() }
    catch (reason) { setError(reason instanceof Error ? reason.message : '回滚失败') }
    finally { setBusy('') }
  }

  async function promote(releaseId: string) {
    if (!window.confirm('确认将整批候选知识原子发布为对外活动版本？')) return
    const reviewer = window.prompt('请输入发布审核人：')
    if (!reviewer) return
    setBusy('promote'); setError('')
    try { await promoteRelease(releaseId, reviewer); setNotice('活动版本已原子切换'); await refresh() }
    catch (reason) { setError(reason instanceof Error ? reason.message : '发布失败') }
    finally { setBusy('') }
  }

  return <div className="space-y-5">
    <header><p className="flex items-center gap-1.5 text-xs font-semibold text-violet-700"><ShieldCheck className="size-4" />发布前质量控制</p><h2 className="mt-1 text-xl font-semibold text-slate-900">政策知识测试</h2><p className="mt-1 text-xs text-slate-500">所有检索验证、经典用例、质量对比和版本发布统一在此完成。</p></header>
    {notice && <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">{notice}</div>}
    {error && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}
    {busy && <div className="fixed right-6 top-6 z-40 flex items-center gap-2 rounded-full bg-slate-900 px-3 py-2 text-xs text-white shadow-lg"><Loader2 className="size-3.5 animate-spin" />处理中</div>}

    <SearchWorkbench />
    <QualityDashboard releases={releases} activeRelease={activeRelease} latestRun={latestRun} currentCaseSetVersion={Math.max(0, ...cases.map((item) => item.case_set_version))} caseResults={caseResults} issue25Metrics={issue25Metrics} onSelectRelease={restoreQuality} onRun={run} onPromote={promote} onRollback={rollback} />
    <AnswerVerificationPanel />
    <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
      <TestCasePanel cases={cases} onSaved={refresh} />
      <CandidatePanel onCreated={refresh} />
    </div>
  </div>
}

function SearchWorkbench() {
  const [mode, setMode] = useState<Mode>('semantic')
  const [target, setTarget] = useState<Target>('policy')
  const [query, setQuery] = useState('职工住院支付比例')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [metricCodes, setMetricCodes] = useState('')
  const [registrationId, setRegistrationId] = useState('')
  const [result, setResult] = useState<{ groups: Array<Record<string, unknown>>; total_groups: number } | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault(); setLoading(true); setError('')
    const body: Record<string, unknown> = { mode, target, top_k: 20 }
    if (mode !== 'precise') body.query = query
    if (mode !== 'semantic') body.filters = Object.fromEntries(Object.entries(filters).filter(([, value]) => value))
    if (target !== 'policy') {
      body.metric_codes = metricCodes.split(',').map((item) => item.trim()).filter(Boolean)
      body.context = registrationId ? { djh: registrationId } : {}
    }
    try { setResult(await searchPolicyKnowledge(body)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '检索失败') }
    finally { setLoading(false) }
  }

  return <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
    <div className="flex items-center gap-2"><Search className="size-4 text-blue-600" /><h3 className="text-sm font-semibold text-slate-900">检索验证</h3><span className="text-[11px] text-slate-400">精准 / 语义 / 混合及结构化数据联查均归入测试页</span></div>
    <form onSubmit={submit} className="mt-4 space-y-3">
      <div className="grid gap-3 md:grid-cols-2">
        <Choice label="检索模式" value={mode} options={[['precise', '精准'], ['semantic', '语义'], ['hybrid', '混合']]} onChange={(value) => setMode(value as Mode)} />
        <Choice label="查询目标" value={target} options={[['policy', '政策知识'], ['database', '结构化数据'], ['both', '两者联查']]} onChange={(value) => setTarget(value as Target)} />
      </div>
      {mode !== 'precise' && <input aria-label="检索问题" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入自然语言问题" className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs" />}
      {mode !== 'semantic' && <div className="grid grid-cols-2 gap-2 md:grid-cols-6">{FILTERS.map((key) => <input key={key} aria-label={key} value={filters[key] || ''} onChange={(event) => setFilters((current) => ({ ...current, [key]: event.target.value }))} placeholder={key} className="rounded-lg border border-slate-200 px-2 py-2 text-[11px]" />)}</div>}
      {target !== 'policy' && <div className="grid gap-2 rounded-xl bg-emerald-50 p-3 md:grid-cols-2"><input value={metricCodes} onChange={(event) => setMetricCodes(event.target.value)} placeholder="统一指标编码，逗号分隔" className="rounded-lg border border-emerald-200 px-3 py-2 text-xs" /><input value={registrationId} onChange={(event) => setRegistrationId(event.target.value)} placeholder="业务登记号 djh" className="rounded-lg border border-emerald-200 px-3 py-2 text-xs" /></div>}
      <button type="submit" disabled={loading} className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50">{loading ? <Loader2 className="size-3.5 animate-spin" /> : <Search className="size-3.5" />}执行检索验证</button>
    </form>
    {error && <p className="mt-3 text-xs text-red-600">{error}</p>}
    {result && <div className="mt-4 rounded-xl bg-slate-50 p-3"><p className="text-xs font-semibold text-slate-700">召回 {result.total_groups} 组知识</p><pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap text-[10px] leading-4 text-slate-500">{JSON.stringify(result.groups, null, 2)}</pre></div>}
  </section>
}

function TestCasePanel({ cases, onSaved }: { cases: PolicyTestCase[]; onSaved: () => void }) {
  const [editingId, setEditingId] = useState('')
  const [name, setName] = useState('')
  const [query, setQuery] = useState('')
  const [expected, setExpected] = useState('')
  const [mode, setMode] = useState<Mode>('semantic')
  const [filtersJson, setFiltersJson] = useState('{}')
  const [required, setRequired] = useState(true)
  const [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault(); setError('')
    try {
      const parsedFilters = JSON.parse(filtersJson) as unknown
      if (!parsedFilters || Array.isArray(parsedFilters) || typeof parsedFilters !== 'object') throw new Error('过滤条件必须是 JSON 对象')
      await saveTestCase({ case_id: editingId || `case_${Date.now()}`, name, query, mode, expected_knowledge_ids: expected.split(',').map((item) => item.trim()).filter(Boolean), filters: parsedFilters as Record<string, unknown>, required, active: true })
      setEditingId(''); setName(''); setQuery(''); setExpected(''); setMode('semantic'); setFiltersJson('{}'); setRequired(true); onSaved()
    } catch (reason) { setError(reason instanceof Error ? reason.message : '用例保存失败') }
  }
  async function deactivate(item: PolicyTestCase) {
    await saveTestCase({ ...item, active: false }); onSaved()
  }
  function edit(item: PolicyTestCase) {
    setEditingId(item.case_id); setName(item.name); setQuery(item.query); setExpected(item.expected_knowledge_ids.join(', ')); setMode(item.mode); setFiltersJson(JSON.stringify(item.filters, null, 2)); setRequired(item.required)
  }
  return <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex items-center gap-2"><Database className="size-4 text-amber-600" /><h3 className="text-sm font-semibold">经典测试用例</h3><span className="ml-auto text-xs text-slate-400">{cases.length} 条</span></div><div className="mt-3 max-h-56 space-y-2 overflow-auto">{cases.map((item) => <div key={item.case_id} className={`rounded-lg border p-2 ${item.active ? 'border-slate-100' : 'border-slate-100 opacity-50'}`}><div className="flex gap-2"><p className="text-xs font-semibold text-slate-700">{item.name}</p>{item.required && <span className="rounded bg-red-50 px-1 text-[9px] text-red-600">必测</span>}<button type="button" onClick={() => edit(item)} className="ml-auto text-[10px] text-blue-700">编辑</button>{item.active && <button type="button" onClick={() => void deactivate(item)} className="text-[10px] text-red-600">停用</button>}</div><p className="mt-1 text-[11px] text-slate-500">{item.query}</p><p className="mt-1 font-mono text-[9px] text-slate-400">{item.mode} · 期望：{item.expected_knowledge_ids.join(', ') || '未设置'}</p></div>)}</div><form onSubmit={submit} className="mt-4 grid gap-2"><input required value={name} onChange={(event) => setName(event.target.value)} placeholder="用例名称" className="rounded-lg border border-slate-200 px-3 py-2 text-xs" /><input required value={query} onChange={(event) => setQuery(event.target.value)} placeholder="测试问题" className="rounded-lg border border-slate-200 px-3 py-2 text-xs" /><select aria-label="用例模式" value={mode} onChange={(event) => setMode(event.target.value as Mode)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs"><option value="precise">精准</option><option value="semantic">语义</option><option value="hybrid">混合</option></select><textarea aria-label="过滤条件 JSON" value={filtersJson} onChange={(event) => setFiltersJson(event.target.value)} rows={3} className="rounded-lg border border-slate-200 px-3 py-2 font-mono text-xs" /><label className="flex items-center gap-2 text-xs text-slate-600"><input aria-label="必测用例" type="checkbox" checked={required} onChange={(event) => setRequired(event.target.checked)} />必测用例</label><input required value={expected} onChange={(event) => setExpected(event.target.value)} placeholder="期望 knowledge_id，逗号分隔" className="rounded-lg border border-slate-200 px-3 py-2 text-xs" />{error && <p className="text-xs text-red-600">{error}</p>}<button className="flex w-fit items-center gap-1 rounded-lg border border-amber-200 px-3 py-2 text-xs font-semibold text-amber-700"><Plus className="size-3.5" />{editingId ? '保存用例修改' : '新增测试用例'}</button></form></section>
}

function CandidatePanel({ onCreated }: { onCreated: () => void }) {
  const [releaseId, setReleaseId] = useState(`rel_${new Date().toISOString().slice(0, 10).replaceAll('-', '')}_01`)
  const [contract, setContract] = useState('2')
  const [message, setMessage] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault(); setMessage('')
    try {
      await createRelease({ release_id: releaseId, contract_version: contract, config_hash: QUALITY_CONFIG_HASH })
      await buildRelease(releaseId)
      setMessage('候选版本及独立索引已构建，可执行统一测试')
      onCreated()
    }
    catch (reason) { setMessage(reason instanceof Error ? reason.message : '候选版本创建失败') }
  }
  return <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><h3 className="text-sm font-semibold">候选版本</h3><p className="mt-1 text-xs text-slate-500">固定配置：重复 {QUALITY_RUN_CONFIG.repeat_count} 次，质量 ≥ {QUALITY_RUN_CONFIG.minimum_quality}，一致性 ≥ {QUALITY_RUN_CONFIG.minimum_consistency}。</p><form onSubmit={submit} className="mt-4 grid gap-2"><input required pattern="[A-Za-z0-9_]+" value={releaseId} onChange={(event) => setReleaseId(event.target.value)} className="rounded-lg border border-slate-200 px-3 py-2 font-mono text-xs" /><input required value={contract} onChange={(event) => setContract(event.target.value)} placeholder="语义契约版本" className="rounded-lg border border-slate-200 px-3 py-2 text-xs" /><input aria-label="测试配置哈希" readOnly value={QUALITY_CONFIG_HASH} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-[10px] text-slate-500" />{message && <p className="text-xs text-slate-600">{message}</p>}<button className="flex w-fit items-center gap-1 rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white"><Plus className="size-3.5" />创建候选版本</button></form></section>
}

function Choice({ label, value, options, onChange }: { label: string; value: string; options: string[][]; onChange: (value: string) => void }) {
  return <div><p className="mb-1 text-[10px] font-semibold text-slate-500">{label}</p><div className="flex rounded-lg bg-slate-100 p-1">{options.map(([key, text]) => <button key={key} type="button" onClick={() => onChange(key)} className={`flex-1 rounded-md px-2 py-1.5 text-xs ${value === key ? 'bg-white font-semibold text-blue-700 shadow-sm' : 'text-slate-500'}`}>{text}</button>)}</div></div>
}
