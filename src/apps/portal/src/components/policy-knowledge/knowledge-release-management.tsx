'use client'

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { ArchiveRestore, Boxes, Check, FlaskConical, Loader2, RefreshCw, Rocket, ShieldCheck } from 'lucide-react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useApiContext } from '@/lib/api-context'
import {
  buildRelease,
  createRelease,
  getActiveRelease,
  getActiveSnapshot,
  getLatestReleaseQuality,
  getReleaseGateStatus,
  listChangeSets,
  listPublishedSnapshots,
  listReleases,
  listTestCases,
  saveTestCase,
  PolicyKnowledgeApiError,
  promoteGovernedRelease,
  rollbackRelease,
  runQuality,
  type KnowledgeChangeSet,
  type PolicyTestCase,
  type KnowledgeRelease,
  type PublishedSnapshot,
  type QualityRunReport,
  type ReleaseGateStatus,
  QUALITY_CONFIG_HASH,
} from '@/lib/policy-knowledge-api'

type QualityState = Record<string, QualityRunReport | null>
type GateState = Record<string, ReleaseGateStatus | null>
type LoadErrors = Partial<Record<'releases' | 'changeSets' | 'snapshots' | 'activeRelease' | 'activeSnapshot' | 'testCases', string>>

export function KnowledgeReleaseManagement() {
  const { userId } = useApiContext()
  const [releases, setReleases] = useState<KnowledgeRelease[]>([])
  const [approvedChangeSets, setApprovedChangeSets] = useState<KnowledgeChangeSet[]>([])
  const [snapshots, setSnapshots] = useState<PublishedSnapshot[]>([])
  const [activeRelease, setActiveRelease] = useState<KnowledgeRelease | null>(null)
  const [activeSnapshot, setActiveSnapshot] = useState<PublishedSnapshot | null>(null)
  const [qualityByRelease, setQualityByRelease] = useState<QualityState>({})
  const [qualityErrors, setQualityErrors] = useState<Set<string>>(new Set())
  const [gateByRelease, setGateByRelease] = useState<GateState>({})
  const [gateErrors, setGateErrors] = useState<Record<string, string>>({})
  const [testCases, setTestCases] = useState<PolicyTestCase[]>([])
  const [loadErrors, setLoadErrors] = useState<LoadErrors>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [selectedChangeSetId, setSelectedChangeSetId] = useState('')
  const [releaseId, setReleaseId] = useState('')
  const [rollbackTarget, setRollbackTarget] = useState<KnowledgeRelease | null>(null)
  const mountedRef = useRef(false)
  const requestRef = useRef(0)

  const load = useCallback(async () => {
    const requestId = ++requestRef.current
    if (mountedRef.current) {
      setLoading(true)
      setError('')
    }
    try {
      const [releaseResult, changeSetResult, snapshotResult, activeReleaseResult, activeSnapshotResult, testCaseResult] = await Promise.allSettled([
        listReleases(),
        listChangeSets(),
        listPublishedSnapshots(),
        optionalNotFound(getActiveRelease()),
        optionalNotFound(getActiveSnapshot()),
        listTestCases(),
      ])
      const releaseItems = releaseResult.status === 'fulfilled' ? releaseResult.value : []
      const currentRelease = activeReleaseResult.status === 'fulfilled' ? activeReleaseResult.value : null
      const candidates = releaseItems.filter((item) => item.status !== 'active' && item.status !== 'retired')
      const gateTargets = [...candidates]
      if (currentRelease && !gateTargets.some((item) => item.release_id === currentRelease.release_id)) gateTargets.push(currentRelease)
      const targetStates = await Promise.all(gateTargets.map(async (item) => {
        const [qualityResult, gateResult] = await Promise.allSettled([
          item.status === 'active' ? Promise.resolve(null) : getLatestReleaseQuality(item.release_id),
          getReleaseGateStatus(item.release_id),
        ])
        return {
          releaseId: item.release_id,
          report: qualityResult.status === 'fulfilled' ? qualityResult.value : null,
          qualityFailed: qualityResult.status === 'rejected'
            && !(qualityResult.reason instanceof PolicyKnowledgeApiError && qualityResult.reason.status === 404),
          gate: gateResult.status === 'fulfilled' ? gateResult.value : null,
          gateError: gateResult.status === 'rejected'
            ? messageOf(gateResult.reason, '发布门禁暂不可用')
            : '',
        }
      }))
      if (!mountedRef.current || requestId !== requestRef.current) return
      if (releaseResult.status === 'fulfilled') setReleases(releaseResult.value)
      if (changeSetResult.status === 'fulfilled') setApprovedChangeSets(changeSetResult.value.filter((item) => item.status === 'APPROVED'))
      if (snapshotResult.status === 'fulfilled') setSnapshots(snapshotResult.value)
      if (activeReleaseResult.status === 'fulfilled') setActiveRelease(activeReleaseResult.value)
      if (activeSnapshotResult.status === 'fulfilled') setActiveSnapshot(activeSnapshotResult.value)
      if (testCaseResult.status === 'fulfilled') setTestCases(testCaseResult.value)
      setLoadErrors({
        ...rejectedError(releaseResult, 'release 列表加载失败', 'releases'),
        ...rejectedError(changeSetResult, '审核结果加载失败', 'changeSets'),
        ...rejectedError(snapshotResult, '历史快照加载失败', 'snapshots'),
        ...rejectedError(activeReleaseResult, '活动版本加载失败', 'activeRelease'),
        ...rejectedError(activeSnapshotResult, '活动快照加载失败', 'activeSnapshot'),
        ...rejectedError(testCaseResult, '测试用例加载失败', 'testCases'),
      })
      setQualityByRelease((previous) => ({ ...previous, ...Object.fromEntries(targetStates.map((item) => [item.releaseId, item.report])) }))
      setQualityErrors(new Set(targetStates.filter((item) => item.qualityFailed).map((item) => item.releaseId)))
      setGateByRelease((previous) => ({ ...previous, ...Object.fromEntries(targetStates.map((item) => [item.releaseId, item.gate])) }))
      setGateErrors(Object.fromEntries(targetStates.filter((item) => item.gateError).map((item) => [item.releaseId, item.gateError])))
    } finally {
      if (mountedRef.current && requestId === requestRef.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    void Promise.resolve().then(() => {
      if (mountedRef.current) return load()
    })
    return () => {
      mountedRef.current = false
      requestRef.current += 1
    }
  }, [load])

  async function createCandidate(event: FormEvent) {
    event.preventDefault()
    const changeSet = approvedChangeSets.find((item) => item.change_set_id === selectedChangeSetId)
    if (!changeSet) {
      setError('请选择一个审核通过的构建结果')
      return
    }
    if (!changeSet.semantic_contract_version) {
      setError('服务端未提供该构建结果的权威语义契约版本，暂不可创建')
      return
    }
    await mutate('create', async () => {
      await createRelease({
        release_id: releaseId.trim(),
        contract_version: changeSet.semantic_contract_version || '',
        config_hash: QUALITY_CONFIG_HASH,
        source_change_set_id: changeSet.change_set_id,
      })
      setReleaseId('')
      setSelectedChangeSetId('')
      setNotice('发布候选已创建，下一步可构建独立索引')
    })
  }

  async function mutate(key: string, action: () => Promise<void>) {
    if (busy) return
    setBusy(key)
    setError('')
    setNotice('')
    try {
      await action()
      await load()
    } catch (reason) {
      if (mountedRef.current) setError(messageOf(reason, '操作失败'))
    } finally {
      if (mountedRef.current) setBusy('')
    }
  }

  async function promoteCandidate(release: KnowledgeRelease) {
    if (busy) return
    setBusy(`promote:${release.release_id}`)
    setError('')
    setNotice('')
    try {
      await promoteGovernedRelease(release.release_id, userId)
      setNotice(release.status === 'active' ? '发布同步已收口' : '正式版本已切换')
      await load()
    } catch (reason) {
      if (reason instanceof PolicyKnowledgeApiError && reason.errorCode === 'POLICY_RELEASE_SYNC_PENDING') {
        await load()
        if (mountedRef.current) setError(syncPendingMessage(reason))
      } else if (reason instanceof PolicyKnowledgeApiError && reason.errorCode === 'POLICY_RELEASE_STATE_UNKNOWN') {
        await load()
        if (mountedRef.current) setError('发布状态未知，已刷新服务端状态，请核对后重试')
      } else if (mountedRef.current) {
        setError(messageOf(reason, '发布失败'))
      }
    } finally {
      if (mountedRef.current) setBusy('')
    }
  }

  const candidates = releases.filter((item) => item.status !== 'active' && item.status !== 'retired')
  const alignedActiveSnapshot = activeRelease && activeSnapshot?.snapshot_id === activeRelease.release_id ? activeSnapshot : null
  const activeMismatch = Boolean(activeRelease && activeSnapshot && !alignedActiveSnapshot)
  const history = alignHistory(snapshots, releases, [activeRelease?.release_id, activeSnapshot?.snapshot_id])
  const hasData = Boolean(releases.length || approvedChangeSets.length || snapshots.length || activeRelease || activeSnapshot || Object.keys(loadErrors).length)

  return (
    <section aria-labelledby="knowledge-releases-title" className="space-y-5 pt-2">
      <header className="flex flex-wrap items-end gap-3">
        <div>
          <p className="text-xs font-semibold text-emerald-700">质量门禁快照 · 不可变发布快照</p>
          <h2 id="knowledge-releases-title" className="mt-1 text-xl font-semibold text-slate-900">发布管理</h2>
          <p className="mt-1 text-xs text-slate-500">页面展示服务端门禁快照与提示；点击发布后，服务端仍会重新校验。</p>
          <p className="mt-1 text-[11px] text-slate-400">当前发布身份：{userId}{userId === 'demo' ? '（演示身份）' : ''}</p>
        </div>
        <button
          type="button"
          aria-label="刷新发布管理"
          disabled={loading || Boolean(busy)}
          onClick={() => void load()}
          className="ml-auto rounded-lg border border-slate-200 bg-white p-2 text-slate-500 hover:bg-slate-50 disabled:opacity-40"
        >
          <RefreshCw className={`size-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </header>

      {notice && <div role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">{notice}</div>}
      {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}
      {busy && <div role="status" className="fixed right-6 top-6 z-40 flex items-center gap-2 rounded-full bg-slate-900 px-3 py-2 text-xs text-white shadow-lg"><Loader2 className="size-3.5 animate-spin" />处理中</div>}

      {loading && !hasData ? (
        <div role="status" className="flex items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white py-20 text-sm text-slate-500"><Loader2 className="size-4 animate-spin" />正在加载发布数据</div>
      ) : (
        <>
          <ReleaseSection title="当前正式版本">
            {loadErrors.activeRelease && <InlineError text={loadErrors.activeRelease} />}
            {loadErrors.activeSnapshot && <InlineError text={loadErrors.activeSnapshot} />}
            {activeMismatch && <InlineWarning text="活动版本与快照同步中/不一致，已停止拼接展示" />}
            {activeRelease ? (
              <PublishedVersionCard
                release={activeRelease}
                snapshot={alignedActiveSnapshot}
                current
                gate={gateByRelease[activeRelease.release_id] || null}
                gateError={gateErrors[activeRelease.release_id] || ''}
                busy={Boolean(busy)}
                onRetrySync={activeRelease.source_change_set_id ? () => void promoteCandidate(activeRelease) : undefined}
              />
            ) : activeSnapshot ? (
              <div className="space-y-2"><InlineWarning text="仅加载到活动快照，活动 release 状态暂不可用" /><PublishedVersionCard release={null} snapshot={activeSnapshot} /></div>
            ) : (
              <Empty text="尚无正式发布版本" />
            )}
          </ReleaseSection>

          <ReleaseSection title="待发布版本">
            {loadErrors.releases && <InlineError text={loadErrors.releases} />}
            <CandidateCreator
              approved={approvedChangeSets}
              selectedId={selectedChangeSetId}
              releaseId={releaseId}
              busy={Boolean(busy)}
              loadError={loadErrors.changeSets || ''}
              onSelected={setSelectedChangeSetId}
              onReleaseId={setReleaseId}
              onSubmit={createCandidate}
            />
            <div className="mt-3 space-y-3">
              {candidates.map((item) => (
                <CandidateCard
                  key={item.release_id}
                  release={item}
                  report={qualityByRelease[item.release_id] || null}
                  qualityError={qualityErrors.has(item.release_id)}
                  gate={gateByRelease[item.release_id] || null}
                  gateError={gateErrors[item.release_id] || ''}
                  busy={Boolean(busy)}
                  onBuild={() => void mutate(`build:${item.release_id}`, async () => { await buildRelease(item.release_id) })}
                  onRun={() => void mutate(`quality:${item.release_id}`, async () => { await runQuality(item.release_id) })}
                  onPromote={() => void promoteCandidate(item)}
                />
              ))}
              {!candidates.length && <Empty text="尚无待发布版本" />}
            </div>
          </ReleaseSection>

          <ReleaseSection title="历史正式版本">
            {loadErrors.snapshots && <InlineError text={loadErrors.snapshots} />}
            <div className="space-y-3">
              {history.map(({ snapshot, release }) => (
                <PublishedVersionCard
                  key={snapshot?.snapshot_id || release?.release_id}
                  snapshot={snapshot}
                  release={release}
                  onRollback={release?.status === 'retired' && Boolean(release.source_change_set_id) ? () => setRollbackTarget(release) : undefined}
                />
              ))}
              {!history.length && <Empty text="尚无历史正式版本" />}
            </div>
          </ReleaseSection>

          <ReleaseSection title="质量测试用例">
            {loadErrors.testCases && <InlineError text={loadErrors.testCases} />}
            <QualityTestCasePanel cases={testCases} busy={Boolean(busy)} onSaved={() => void load()} />
          </ReleaseSection>
        </>
      )}

      <Dialog open={Boolean(rollbackTarget)} onOpenChange={(open) => { if (!open && !busy) setRollbackTarget(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认回滚正式版本</DialogTitle>
            <DialogDescription>
              将整体切换回 {rollbackTarget?.release_id}，原有不可变历史快照会继续保留。
            </DialogDescription>
          </DialogHeader>
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800">
            确认人：{userId}{userId === 'demo' ? '（演示身份）' : ''}
          </p>
          <DialogFooter>
            <button type="button" disabled={Boolean(busy)} onClick={() => setRollbackTarget(null)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600">取消</button>
            <button
              type="button"
              disabled={!rollbackTarget || Boolean(busy)}
              onClick={() => {
                const target = rollbackTarget
                if (!target) return
                void mutate(`rollback:${target.release_id}`, async () => {
                  await rollbackRelease(target.release_id, userId)
                  setRollbackTarget(null)
                  setNotice(`已回滚到 ${target.release_id}`)
                })
              }}
              className="rounded-lg bg-amber-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"
            >确认回滚</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}

function ReleaseSection({ title, children }: { title: string; children: React.ReactNode }) {
  const id = `release-section-${title}`
  return <section role="region" aria-labelledby={id} className="rounded-xl border border-slate-200 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]"><h3 id={id} className="text-base font-semibold tracking-tight text-slate-900">{title}</h3><div className="mt-3">{children}</div></section>
}

function CandidateCreator({ approved, selectedId, releaseId, busy, loadError, onSelected, onReleaseId, onSubmit }: {
  approved: KnowledgeChangeSet[]
  selectedId: string
  releaseId: string
  busy: boolean
  loadError: string
  onSelected: (value: string) => void
  onReleaseId: (value: string) => void
  onSubmit: (event: FormEvent) => void
}) {
  const selected = approved.find((item) => item.change_set_id === selectedId)
  const candidateCount = (item: KnowledgeChangeSet) =>
    (item.summary.additions ?? 0) + (item.summary.modifications ?? 0) + (item.summary.replacements ?? 0)
  return <form onSubmit={onSubmit} className="rounded-xl border border-dashed border-emerald-200 bg-emerald-50/40 p-4">
    <div className="flex items-center gap-2 text-xs font-semibold text-emerald-800"><Boxes className="size-4" />从审核通过结果创建候选</div>
    <p className="mt-1 text-[11px] text-slate-500">下方为已整批通过审核、待发布的变更集；点选一个后填写发布标识即可创建发布候选（每个候选只绑定 1 个构建结果）。</p>
    {loadError ? (
      <InlineError text={loadError} />
    ) : approved.length === 0 ? (
      <p className="mt-3 rounded-lg bg-white px-3 py-3 text-xs text-slate-500">暂无审核通过且未发布的构建结果——在「知识审核」页整批通过后，变更集会出现在这里。</p>
    ) : (
      <ul className="mt-3 space-y-1.5">
        {approved.map((item) => {
          const active = item.change_set_id === selectedId
          return (
            <li key={item.change_set_id}>
              <button
                type="button"
                aria-label={`选择变更集 ${item.change_set_id}`}
                onClick={() => onSelected(item.change_set_id)}
                className={`flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs transition-colors ${active ? 'border-emerald-400 bg-emerald-50 ring-1 ring-emerald-200' : 'border-slate-200 bg-white hover:border-emerald-200 hover:bg-emerald-50/40'}`}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium text-slate-700">{item.doc_title}</span>
                  <span className="mt-0.5 block truncate font-mono text-[10px] text-slate-400">
                    {item.change_set_id} · {candidateCount(item)} 条候选 · 契约 {item.semantic_contract_version ?? '缺失'}
                  </span>
                </span>
                {active && <Check className="size-4 shrink-0 text-emerald-600" />}
              </button>
            </li>
          )
        })}
      </ul>
    )}
    <div className="mt-3 grid gap-2 md:grid-cols-[1fr_auto]">
      <input aria-label="发布候选标识" required pattern="[A-Za-z0-9_]+" value={releaseId} disabled={busy || !selected} onChange={(event) => onReleaseId(event.target.value)} placeholder="发布候选标识，例：REL_20260805" className="rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-xs outline-none transition-colors focus:border-emerald-500 disabled:opacity-60" />
      <button type="submit" disabled={busy || Boolean(loadError) || !selected || !releaseId.trim() || !selected.semantic_contract_version} className="rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white shadow-[0_1px_2px_rgba(4,120,87,0.25)] transition-all hover:bg-emerald-800 active:scale-[0.98] disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none">创建发布候选</button>
    </div>
    {selected && !selected.semantic_contract_version && <p role="alert" className="mt-2 text-xs text-red-700">服务端未提供该结果的权威语义契约版本，创建已锁定。</p>}
  </form>
}

function QualityTestCasePanel({ cases, busy, onSaved }: {
  cases: PolicyTestCase[]
  busy: boolean
  onSaved: () => void
}) {
  const [name, setName] = useState('')
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState<PolicyTestCase['mode']>('semantic')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      await saveTestCase({ name: name.trim(), query: query.trim(), mode, required: true, active: true })
      setName('')
      setQuery('')
      setMode('semantic')
      onSaved()
    } catch (reason) {
      setError(messageOf(reason, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-xl border border-dashed border-violet-200 bg-violet-50/40 p-4">
      <div className="flex items-center gap-2 text-xs font-semibold text-violet-800"><FlaskConical className="size-4" />质量测试用例</div>
      <p className="mt-1 text-[11px] text-slate-500">内置经典用例 + 自定义用例；「运行质量检查」会逐条运行。新增用例后用例集版本 +1，存量候选需重新创建候选版本。</p>
      <ul className="mt-3 space-y-1.5">
        {cases.map((item) => (
          <li key={item.case_id} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-xs font-medium text-slate-700">{item.name}</span>
              <span className="mt-0.5 block truncate font-mono text-[10px] text-slate-400">{item.case_id} · v{item.case_set_version} · {item.mode}</span>
            </span>
            {!item.active && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">已停用</span>}
            {item.required && <span className="rounded bg-violet-100 px-1.5 py-0.5 text-[10px] text-violet-700">必测</span>}
          </li>
        ))}
        {!cases.length && <p className="text-xs text-slate-500">暂无测试用例</p>}
      </ul>
      <form onSubmit={(event) => void handleSubmit(event)} className="mt-3 grid gap-2 md:grid-cols-[1fr_1.6fr_0.55fr_auto]">
        <input aria-label="用例名称" required value={name} disabled={saving || busy} onChange={(event) => setName(event.target.value)} placeholder="用例名称" className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs outline-none transition-colors focus:border-violet-500 disabled:opacity-60" />
        <input aria-label="用例查询" required value={query} disabled={saving || busy} onChange={(event) => setQuery(event.target.value)} placeholder="政策查询语句" className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs outline-none transition-colors focus:border-violet-500 disabled:opacity-60" />
        <select aria-label="用例模式" value={mode} disabled={saving || busy} onChange={(event) => setMode(event.target.value as PolicyTestCase['mode'])} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs outline-none transition-colors focus:border-violet-500 disabled:opacity-60">
          <option value="semantic">语义</option>
          <option value="hybrid">混合</option>
          <option value="precise">精确</option>
        </select>
        <button type="submit" disabled={saving || busy || !name.trim() || !query.trim()} className="rounded-lg bg-violet-700 px-3 py-2 text-xs font-semibold text-white transition-all hover:bg-violet-800 active:scale-[0.98] disabled:cursor-not-allowed disabled:bg-slate-300">新增用例</button>
      </form>
      {error && <p role="alert" className="mt-2 text-xs text-red-700">{error}</p>}
    </div>
  )
}

function CandidateCard({ release, report, qualityError, gate, gateError, busy, onBuild, onRun, onPromote }: {
  release: KnowledgeRelease
  report: QualityRunReport | null
  qualityError: boolean
  gate: ReleaseGateStatus | null
  gateError: string
  busy: boolean
  onBuild: () => void
  onRun: () => void
  onPromote: () => void
}) {
  const canPromote = gate?.can_promote === true
  return <article className="rounded-xl border border-slate-200 p-4 transition-colors hover:border-slate-300">
    <div className="flex flex-wrap items-start gap-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2"><span className="font-mono text-sm font-semibold text-slate-800">{release.release_id}</span><Status status={release.status} /></div>
        <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500"><span>语义契约 {versionLabel(release.contract_version)}</span><span className="tabular-nums">用例集 v{release.case_set_version}</span><span>{sourceCountLabel(release.source_change_set_id)}</span><span className="font-mono">血缘 {release.source_change_set_id || '暂无记录'}</span></p>
        <p className="mt-1 text-[11px] tabular-nums text-slate-500">质量 {percent(release.quality_score)} · 一致性 {percent(release.consistency_score)}</p>
        {qualityError && <p className="mt-2 text-xs text-amber-700">质量记录加载失败，请刷新后重试。</p>}
        {report?.run.blocked_reasons.map((reason) => <p key={reason} className="mt-2 text-xs text-red-700">{reason}</p>)}
        {gate?.blocked_reasons.map((reason) => <p key={`gate:${reason}`} className="mt-2 text-xs text-amber-700">{reason}</p>)}
        {gateError && <p className="mt-2 text-xs font-medium text-red-700">{gateError}</p>}
      </div>
      <div className="flex flex-wrap gap-2">
        {release.status === 'building' && <Action label={`构建索引：${release.release_id}`} text="构建索引" disabled={busy} onClick={onBuild} />}
        {release.status === 'ready' && <Action label={`运行质量检查：${release.release_id}`} text="运行质量检查" disabled={busy} onClick={onRun} />}
        {release.status === 'failed' && <Action label={`重新运行质量检查：${release.release_id}`} text="重新运行质量检查" disabled={busy} onClick={onRun} />}
        {canPromote && <Action label={`发布正式版本：${release.release_id}`} text="发布正式版本" disabled={busy} onClick={onPromote} primary />}
        {release.status === 'testing' && <span className="flex items-center gap-1 text-xs text-blue-700"><Loader2 className="size-3.5 animate-spin" />质量检查中</span>}
      </div>
    </div>
  </article>
}

function PublishedVersionCard({ release, snapshot, current = false, gate = null, gateError = '', busy = false, onRetrySync, onRollback }: {
  release: KnowledgeRelease | null
  snapshot: PublishedSnapshot | null
  current?: boolean
  gate?: ReleaseGateStatus | null
  gateError?: string
  busy?: boolean
  onRetrySync?: () => void
  onRollback?: () => void
}) {
  const id = snapshot?.snapshot_id || release?.release_id || '未知版本'
  return <article className={`rounded-xl border p-4 transition-colors ${current ? 'border-emerald-200 bg-emerald-50/30' : 'border-slate-200 hover:border-slate-300'}`}>
    <div className="flex flex-wrap items-start gap-3">
      <ShieldCheck className={`mt-0.5 size-4 ${current ? 'text-emerald-600' : 'text-slate-400'}`} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2"><span className="font-mono text-sm font-semibold text-slate-800">{id}</span>{current && <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">当前正式版本</span>}{snapshot?.immutable && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">不可变快照</span>}</div>
        <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
          {current ? <>
            <span>当前启用时间：{release?.promoted_at ? formatDate(release.promoted_at) : '暂无记录'}</span>
            <span>本次启用操作人：{release?.promoted_by || '暂无记录'}</span>
            {snapshot ? <><span>原始快照发布时间：{formatDate(snapshot.published_at)}</span><span>原始快照发布人：{snapshot.published_by || '暂无记录'}</span></> : <span>原始快照：暂无记录</span>}
          </> : <>
            <span>发布时间：{snapshot ? formatDate(snapshot.published_at) : '暂无记录'}</span>
            <span>发布人：{snapshot?.published_by || '暂无记录'}</span>
          </>}
          <span>语义契约 {versionLabel(snapshot?.semantic_contract_version || release?.contract_version || null)}</span>
          <span>质量 {percent(release?.quality_score ?? null)}</span>
          <span className="font-mono">血缘 {publishedSourceId(snapshot, release) || '暂无记录'}</span>
          <span>{sourceCountLabel(publishedSourceId(snapshot, release))}</span>
          <span>规则总数：暂无统计</span>
        </p>
        {gateError && <p className="mt-2 text-xs text-red-700">{gateError}</p>}
        {gate?.sync_pending && <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
          <p className="text-xs font-semibold text-amber-800">发布已生效，同步待收口</p>
          {gate.sync_pending_reasons.map((reason) => <p key={reason} className="mt-1 text-xs text-amber-700">{reason}</p>)}
          {onRetrySync && <button type="button" aria-label={`重试发布同步：${release?.release_id}`} disabled={busy} onClick={onRetrySync} className="mt-2 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-semibold text-amber-800 disabled:opacity-40">重试发布同步</button>}
        </div>}
      </div>
      {onRollback && <button type="button" aria-label={`回滚到 ${id}`} onClick={onRollback} className="flex items-center gap-1 rounded-lg border border-amber-200 px-3 py-2 text-xs font-semibold text-amber-700 hover:bg-amber-50"><ArchiveRestore className="size-3.5" />回滚</button>}
    </div>
  </article>
}

function Action({ label, text, disabled, onClick, primary = false }: { label: string; text: string; disabled: boolean; onClick: () => void; primary?: boolean }) {
  return <button type="button" aria-label={label} disabled={disabled} onClick={onClick} className={`flex items-center gap-1 rounded-lg px-3 py-2 text-xs font-semibold transition-all disabled:cursor-not-allowed disabled:opacity-40 active:scale-[0.98] ${primary ? 'bg-emerald-700 text-white shadow-[0_1px_2px_rgba(4,120,87,0.25)] hover:bg-emerald-800' : 'border border-slate-200 text-slate-700 hover:bg-slate-50'}`}>{primary ? <Rocket className="size-3.5" /> : null}{text}</button>
}

function Status({ status }: { status: KnowledgeRelease['status'] }) {
  const labels: Record<KnowledgeRelease['status'], string> = { building: '待构建索引', ready: '待质量检查', testing: '质量检查中', passed: '质量已通过', failed: '质量未通过', active: '当前正式版本', retired: '历史版本' }
  const tones: Record<KnowledgeRelease['status'], string> = {
    building: 'bg-sky-50 text-sky-700',
    ready: 'bg-amber-50 text-amber-700',
    testing: 'bg-sky-50 text-sky-700',
    passed: 'bg-emerald-50 text-emerald-700',
    failed: 'bg-red-50 text-red-700',
    active: 'bg-emerald-50 text-emerald-700',
    retired: 'bg-slate-100 text-slate-500',
  }
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${tones[status]}`}>{labels[status]}</span>
}

function Empty({ text }: { text: string }) {
  return <div className="rounded-xl border border-dashed border-slate-200 px-3 py-10 text-center text-sm text-slate-400">{text}</div>
}

function InlineError({ text }: { text: string }) {
  return <div role="alert" className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{text}</div>
}

function InlineWarning({ text }: { text: string }) {
  return <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">{text}</div>
}

function alignHistory(snapshotItems: PublishedSnapshot[], releaseItems: KnowledgeRelease[], activeIds: Array<string | undefined>) {
  const excludedIds = new Set(activeIds.filter((item): item is string => Boolean(item)))
  const result: Array<{ snapshot: PublishedSnapshot | null; release: KnowledgeRelease | null }> = snapshotItems
    .filter((item) => !excludedIds.has(item.snapshot_id))
    .map((item) => ({ snapshot: item, release: releaseItems.find((release) => release.release_id === item.snapshot_id) || null }))
  const knownIds = new Set(result.map((item) => item.release?.release_id || item.snapshot?.snapshot_id))
  for (const release of releaseItems.filter((item) => item.status === 'retired')) {
    if (!knownIds.has(release.release_id)) result.push({ snapshot: null, release })
  }
  return result
}

async function optionalNotFound<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise
  } catch (reason) {
    if (reason instanceof PolicyKnowledgeApiError && reason.status === 404) return null
    throw reason
  }
}

const percent = (value: number | null) => value === null ? '暂无记录' : `${Math.round(value * 100)}%`
const sourceCountLabel = (sourceId: string | null | undefined) => sourceId ? '1 个构建结果' : '来源未记录（兼容版本）'
const publishedSourceId = (snapshot: PublishedSnapshot | null, release: KnowledgeRelease | null) => snapshot ? snapshot.source_change_set_id : release?.source_change_set_id
const versionLabel = (value: string | null) => value ? (value.startsWith('v') ? value : `v${value}`) : '暂无记录'
const formatDate = (value: string) => new Date(value).toLocaleString('zh-CN')
const messageOf = (reason: unknown, fallback: string) => reason instanceof Error ? reason.message : fallback
function rejectedError<K extends keyof LoadErrors>(result: PromiseSettledResult<unknown>, fallback: string, key: K): Pick<LoadErrors, K> | Record<string, never> {
  return result.status === 'rejected' ? { [key]: messageOf(result.reason, fallback) } as Pick<LoadErrors, K> : {}
}
const syncPendingMessage = (error: PolicyKnowledgeApiError) => {
  const context = [error.auditEvent.release_id, error.auditEvent.source_change_set_id].filter(Boolean).join(' · ')
  return `发布已生效，快照/血缘同步待重试${context ? `（${context}）` : ''}`
}
