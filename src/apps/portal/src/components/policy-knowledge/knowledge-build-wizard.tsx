'use client'

import Link from 'next/link'
import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, FileCheck2, LockKeyhole, Search, X } from 'lucide-react'

import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import {
  createKnowledgeBuildTask,
  PolicyKnowledgeApiError,
  preflightKnowledgeBuild,
  type CreateKnowledgeBuildTaskRequest,
  type EligibleKnowledgeUnit,
  type KnowledgeBuildPreflight,
} from '@/lib/policy-knowledge-api'

type KnowledgeBuildWizardProps = {
  eligibleUnits: EligibleKnowledgeUnit[]
  userId: string
  onClose: () => void
  onCreated: () => void | Promise<void>
}

type WizardStep = 1 | 2 | 3

export function KnowledgeBuildWizard({ eligibleUnits, userId, onClose, onCreated }: KnowledgeBuildWizardProps) {
  const [step, setStep] = useState<WizardStep>(1)
  const [search, setSearch] = useState('')
  const [docFilter, setDocFilter] = useState('')
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])
  const [taskName, setTaskName] = useState('')
  const [rebuildReason, setRebuildReason] = useState('')
  const [preflight, setPreflight] = useState<KnowledgeBuildPreflight | null>(null)
  const [busy, setBusy] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [semanticUnavailable, setSemanticUnavailable] = useState(false)
  const [claimConflict, setClaimConflict] = useState<{ taskId: string | null; targetHref: string | null } | null>(null)
  const [rebuildModeEnabled, setRebuildModeEnabled] = useState(false)
  const mountedRef = useRef(true)
  const requestGenerationRef = useRef(0)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      requestGenerationRef.current += 1
    }
  }, [])

  const approvedUnits = useMemo(
    () => eligibleUnits.filter((unit) => unit.status === 'reviewed' || unit.status === 'published'),
    [eligibleUnits],
  )
  const unitsByKey = useMemo(
    () => new Map(approvedUnits.map((unit) => [revisionKey(unit), unit])),
    [approvedUnits],
  )
  const selectedUnits = selectedKeys.flatMap((key) => {
    const unit = unitsByKey.get(key)
    return unit ? [unit] : []
  })
  const filteredUnits = approvedUnits.filter((unit) => {
    const query = search.trim().toLocaleLowerCase('zh-CN')
    if (query && !`${unit.doc_title} ${unit.path.join(' ')} ${unit.source_preview}`.toLocaleLowerCase('zh-CN').includes(query)) {
      return false
    }
    if (docFilter && unit.doc_title !== docFilter) return false
    return true
  })
  const docOptions = useMemo(
    () => Array.from(new Map(approvedUnits.map((unit) => [unit.doc_title, unit])).keys()).sort((a, b) => a.localeCompare(b, 'zh-CN')),
    [approvedUnits],
  )
  // 全选只作用于当前筛选结果中的可选单元（排除占用中 / 未开启重建的已发布单元）。
  const selectableFiltered = filteredUnits.filter((unit) => {
    const claimed = unit.availability === 'CLAIMED'
    const publishedLocked = unit.status === 'published' && !rebuildModeEnabled
    return !claimed && !publishedLocked
  })
  const allFilteredSelected = selectableFiltered.length > 0
    && selectableFiltered.every((unit) => selectedKeys.includes(revisionKey(unit)))

  function toggleSelectAll() {
    const keys = selectableFiltered.map(revisionKey)
    setSelectedKeys((current) => {
      const currentSet = new Set(current)
      if (allFilteredSelected) {
        keys.forEach((key) => currentSet.delete(key))
      } else {
        keys.forEach((key) => currentSet.add(key))
      }
      return Array.from(currentSet)
    })
    setMessage(null)
  }
  const rebuildRequired = selectedUnits.some((unit) => unit.availability === 'REBUILD_REQUIRED' || unit.status === 'published')
  const semanticContractVersion = semanticUnavailable
    ? '不可用'
    : preflight?.semantic_contract_version ?? '创建时由服务端锁定'

  function toggleUnit(unit: EligibleKnowledgeUnit) {
    if (unit.availability === 'CLAIMED') return
    const key = revisionKey(unit)
    setSelectedKeys((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key])
    setMessage(null)
  }

  function requestFor(units: EligibleKnowledgeUnit[]): CreateKnowledgeBuildTaskRequest {
    const isRebuild = units.some((unit) => unit.availability === 'REBUILD_REQUIRED' || unit.status === 'published')
    return {
      name: taskName.trim() || defaultTaskName(units),
      created_by: userId,
      build_mode: isRebuild ? 'REBUILD' : 'INITIAL',
      rebuild_reason: isRebuild ? rebuildReason.trim() || null : null,
      unit_revisions: units.map((unit) => ({
        doc_id: unit.doc_id,
        unit_id: unit.unit_id,
        unit_revision_id: unit.unit_revision_id,
      })),
    }
  }

  function moveToConfiguration() {
    if (!selectedUnits.length) {
      setMessage('请至少选择一个审核通过的单元')
      return
    }
    const generatedName = defaultTaskName(selectedUnits)
    setTaskName((current) => current || generatedName)
    setMessage(null)
    setStep(2)
  }

  async function moveToPreflight() {
    if (!taskName.trim()) {
      setMessage('请填写任务名称')
      return
    }
    if (rebuildRequired && !rebuildReason.trim()) {
      setMessage('重建已发布单元时必须填写重建原因')
      return
    }
    const requestGeneration = beginRequest()
    setBusy(true)
    setMessage(null)
    setClaimConflict(null)
    setSemanticUnavailable(false)
    try {
      const result = await preflightKnowledgeBuild(requestFor(selectedUnits))
      if (!isCurrentRequest(requestGeneration)) return
      setPreflight(result)
      setSemanticUnavailable(false)
    } catch (error) {
      if (!isCurrentRequest(requestGeneration)) return
      handlePreflightError(error)
    } finally {
      if (isCurrentRequest(requestGeneration)) {
        setBusy(false)
        setStep(3)
      }
    }
  }

  function handlePreflightError(error: unknown) {
    setPreflight(null)
    setMessage(error instanceof Error ? error.message : '冲突预检失败')
    setSemanticUnavailable(error instanceof PolicyKnowledgeApiError && error.status === 503)
  }

  async function excludeBlockedUnits() {
    if (!preflight) return
    const blockedUnits = new Set(
      preflight.blockers.flatMap((blocker) => blocker.doc_id && blocker.unit_id
        ? [`${blocker.doc_id}:${blocker.unit_id}`]
        : []),
    )
    const blockedRevisions = new Set(
      preflight.blockers.flatMap((blocker) => !(blocker.doc_id && blocker.unit_id) && blocker.unit_revision_id
        ? [blocker.unit_revision_id]
        : []),
    )
    const remaining = selectedUnits.filter((unit) => (
      !blockedUnits.has(`${unit.doc_id}:${unit.unit_id}`)
      && !blockedRevisions.has(unit.unit_revision_id)
    ))
    setSelectedKeys(remaining.map(revisionKey))
    if (!remaining.length) {
      requestGenerationRef.current += 1
      setPreflight(null)
      setClaimConflict(null)
      setSemanticUnavailable(false)
      setMessage('所有阻断单元已排除，请重新选择审核通过的单元')
      setStep(1)
      return
    }
    const requestGeneration = beginRequest()
    setBusy(true)
    setMessage(null)
    setClaimConflict(null)
    setSemanticUnavailable(false)
    try {
      const result = await preflightKnowledgeBuild(requestFor(remaining))
      if (!isCurrentRequest(requestGeneration)) return
      setPreflight(result)
      setSemanticUnavailable(false)
    } catch (error) {
      if (!isCurrentRequest(requestGeneration)) return
      handlePreflightError(error)
    } finally {
      if (isCurrentRequest(requestGeneration)) setBusy(false)
    }
  }

  async function createTask() {
    if (!preflight?.can_submit || preflight.blocking_count || semanticUnavailable || claimConflict) return
    const requestGeneration = beginRequest()
    setBusy(true)
    setSubmitting(true)
    setMessage(null)
    setClaimConflict(null)
    try {
      await createKnowledgeBuildTask(requestFor(selectedUnits))
      if (!isCurrentRequest(requestGeneration)) return
      setBusy(false)
      setSubmitting(false)
      await onCreated()
    } catch (error) {
      if (!isCurrentRequest(requestGeneration)) return
      setMessage(error instanceof Error ? error.message : '构建任务创建失败')
      if (error instanceof PolicyKnowledgeApiError && error.status === 409) {
        setClaimConflict({
          taskId: typeof error.auditEvent.task_id === 'string' ? error.auditEvent.task_id : null,
          targetHref: typeof error.auditEvent.target_href === 'string' ? error.auditEvent.target_href : null,
        })
      }
      if (error instanceof PolicyKnowledgeApiError && error.status === 503) setSemanticUnavailable(true)
    } finally {
      if (isCurrentRequest(requestGeneration)) {
        setBusy(false)
        setSubmitting(false)
      }
    }
  }

  function beginRequest(): number {
    requestGenerationRef.current += 1
    return requestGenerationRef.current
  }

  function isCurrentRequest(requestGeneration: number): boolean {
    return mountedRef.current && requestGenerationRef.current === requestGeneration
  }

  const preciseBlockers = preflight?.blockers.filter((blocker) => (
    (blocker.doc_id && blocker.unit_id) || blocker.unit_revision_id
  )) ?? []
  const blockerCounts = classifyBlockers(preflight)

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !submitting) onClose()
      }}
    >
      <DialogContent
        aria-label="新建构建任务"
        showCloseButton={false}
        className="w-full flex-col gap-0 overflow-hidden bg-white p-0 shadow-2xl ring-0"
        style={{
          top: 0,
          right: 0,
          bottom: 0,
          left: 'auto',
          display: 'flex',
          height: '100dvh',
          maxWidth: '42rem',
          transform: 'none',
          translate: 'none',
          borderRadius: 0,
        }}
      >
        <header className="border-b border-slate-200 px-5 py-4">
          <div className="flex items-start gap-3">
            <div>
              <p className="text-xs font-semibold text-emerald-700">知识构建 · 第 {step}/3 步</p>
              <DialogTitle className="mt-1 text-lg font-semibold tracking-tight text-slate-900">新建构建任务</DialogTitle>
              <DialogDescription className="sr-only">从审核通过的精确单元修订创建知识构建任务</DialogDescription>
            </div>
            <button type="button" aria-label="关闭创建抽屉" disabled={submitting} onClick={onClose} className="ml-auto rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-40">
              <X className="size-4" />
            </button>
          </div>
          <ol aria-label="创建构建任务步骤" className="mt-4 grid grid-cols-3 gap-1.5 text-xs">
            {(['选择单元', '确认配置', '冲突预检'] as const).map((label, index) => (
              <li key={label} aria-current={step === index + 1 ? 'step' : undefined} className={`rounded-md px-2 py-1.5 text-center ring-1 ring-inset ${step === index + 1 ? 'bg-emerald-50 font-semibold text-emerald-800 ring-emerald-600/20' : index + 1 < step ? 'bg-emerald-50/60 text-emerald-700 ring-emerald-600/10' : 'bg-slate-50 text-slate-400 ring-slate-200/60'}`}>{index + 1}. {label}</li>
            ))}
          </ol>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {step === 1 && (
            <div className="space-y-4">
              <div>
                <h3 className="font-semibold text-slate-900">选择已审核单元</h3>
                <p className="mt-1 text-xs text-slate-500">仅展示审核通过或已发布的精确修订；正在构建或审核的单元不可重复选择。</p>
              </div>
              <div className="flex gap-2">
                <label className="relative block flex-1">
                  <Search className="pointer-events-none absolute left-3 top-2.5 size-4 text-slate-400" />
                  <input autoFocus type="search" aria-label="搜索政策标题或条款" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索政策标题、章节或条款" className="h-9 w-full rounded-lg border border-slate-200 pl-9 pr-3 text-sm outline-none transition-colors focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
                </label>
                <select
                  aria-label="按来源文档筛选"
                  value={docFilter}
                  onChange={(event) => setDocFilter(event.target.value)}
                  className="h-9 max-w-56 rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none transition-colors focus:border-emerald-500"
                >
                  <option value="">全部来源文档</option>
                  {docOptions.map((title) => (
                    <option key={title} value={title}>{title}</option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50/50 p-3">
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold text-emerald-900">重新构建已发布单元</p>
                  <p className="mt-1 text-[11px] leading-4 text-emerald-700">默认关闭，避免无意覆盖已发布单元的候选结果；开启后必须填写原因。</p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-label="重新构建已发布单元"
                  aria-checked={rebuildModeEnabled}
                  onClick={() => {
                    const nextEnabled = !rebuildModeEnabled
                    setRebuildModeEnabled(nextEnabled)
                    setMessage(null)
                    if (!nextEnabled) {
                      setSelectedKeys((current) => current.filter((key) => unitsByKey.get(key)?.status !== 'published'))
                      setRebuildReason('')
                    }
                  }}
                  className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${rebuildModeEnabled ? 'bg-emerald-600' : 'bg-slate-300'}`}
                >
                  <span className={`absolute top-0.5 size-5 rounded-full bg-white shadow-sm transition-transform ${rebuildModeEnabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
                </button>
              </div>
              <div className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50/60 px-3 py-2">
                <label className="flex cursor-pointer items-center gap-2 text-xs font-medium text-slate-700">
                  <input
                    type="checkbox"
                    aria-label="全选当前筛选单元"
                    checked={allFilteredSelected}
                    disabled={!selectableFiltered.length}
                    onChange={toggleSelectAll}
                    className="size-4 rounded border-slate-300 accent-emerald-600 disabled:cursor-not-allowed"
                  />
                  全选当前筛选单元
                </label>
                <span className="text-[11px] tabular-nums text-slate-400">
                  已选 {selectedKeys.length} / 筛选 {filteredUnits.length}
                </span>
              </div>
              <div className="space-y-2">
                {filteredUnits.map((unit) => {
                  const claimed = unit.availability === 'CLAIMED'
                  const publishedLocked = unit.status === 'published' && !rebuildModeEnabled
                  const disabled = claimed || publishedLocked
                  const statusLabel = claimed
                    ? occupiedStageLabel(unit.target_href)
                    : publishedLocked
                      ? '已发布，开启重建模式后可选'
                      : unit.status === 'published'
                        ? '已发布，需重建'
                        : '审核通过'
                  const label = `${unit.path.join(' / ') || unit.unit_id} · 修订 ${unit.unit_revision_id} · ${statusLabel}`
                  return (
                    <article key={revisionKey(unit)} className={`rounded-xl border p-3 transition-colors ${disabled ? 'border-slate-200 bg-slate-50' : selectedKeys.includes(revisionKey(unit)) ? 'border-emerald-300 bg-emerald-50/40' : 'border-slate-200 hover:border-slate-300'}`}>
                      <div className="flex gap-3">
                        <input type="checkbox" aria-label={label} disabled={disabled} checked={selectedKeys.includes(revisionKey(unit))} onChange={() => toggleUnit(unit)} className="mt-1 size-4 rounded border-slate-300 accent-emerald-600" />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="font-medium text-slate-900">{unit.doc_title}</p>
                            <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${claimed ? 'bg-amber-100 text-amber-700' : unit.status === 'published' ? 'bg-teal-100 text-teal-700' : 'bg-emerald-100 text-emerald-700'}`}>{statusLabel}</span>
                          </div>
                          <p className="mt-1 text-xs text-slate-600">{unit.path.join(' / ') || '未标注条款'}</p>
                          <p className="mt-1 font-mono text-[10px] text-slate-400">精确修订 {unit.unit_revision_id}</p>
                          <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500">{unit.source_preview}</p>
                          {claimed && unit.occupied_by && unit.target_href && (
                            <Link href={unit.target_href} className="mt-2 inline-block text-xs font-semibold text-emerald-700 hover:underline">查看占用任务 {unit.occupied_by}</Link>
                          )}
                        </div>
                      </div>
                    </article>
                  )
                })}
                {!filteredUnits.length && <p className="rounded-xl border border-dashed border-slate-200 py-10 text-center text-sm text-slate-400">没有匹配的审核单元</p>}
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <div>
                <h3 className="font-semibold text-slate-900">确认构建配置</h3>
                <p className="mt-1 text-xs text-slate-500">仅任务名称和重建原因可填写；语义契约及执行配置由平台锁定。</p>
              </div>
              <label className="block text-xs font-medium text-slate-600">任务名称
                <input aria-label="任务名称" value={taskName} onChange={(event) => setTaskName(event.target.value)} className="mt-1.5 h-9 w-full rounded-lg border border-slate-200 px-3 text-sm font-normal text-slate-900 outline-none transition-colors focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
              </label>
              <div className="grid gap-3 sm:grid-cols-2">
                <ReadonlyField label="构建模式" value={rebuildRequired ? '重新构建' : '首次构建'} />
                <ReadonlyField label="语义契约版本" value={semanticContractVersion} />
                <ReadonlyField label="流水线版本" value="创建时由服务端锁定" />
                <ReadonlyField label="模型场景" value="创建时由服务端锁定" />
                <ReadonlyField label="配置哈希" value="创建时由服务端锁定" />
              </div>
              <div className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
                <LockKeyhole className="mt-0.5 size-4 shrink-0 text-slate-500" />
                <span>配置只读。需要调整 Schema 或语义契约时，请在语义层完成后重新预检。</span>
              </div>
              {rebuildRequired && (
                <label className="block text-xs font-medium text-slate-600">重建原因
                  <textarea required aria-label="重建原因" value={rebuildReason} onChange={(event) => setRebuildReason(event.target.value)} rows={3} placeholder="说明已发布单元为什么需要重新构建" className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm font-normal text-slate-900 outline-none transition-colors focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
                </label>
              )}
              {semanticUnavailable && <SemanticUnavailable message={message ?? '当前没有可用的语义契约'} />}
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4">
              <div>
                <h3 className="font-semibold text-slate-900">冲突预检</h3>
                <p className="mt-1 text-xs text-slate-500">创建前再次核对单元占用、候选结果和重建要求。</p>
                {preflight?.semantic_contract_version && <p className="mt-2 inline-flex rounded-md bg-emerald-50 px-2 py-1 font-mono text-[11px] font-semibold text-emerald-800 ring-1 ring-inset ring-emerald-600/15">语义契约 {preflight.semantic_contract_version}</p>}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <PreflightCard label="可正常构建" value={preflight?.buildable_count ?? 0} tone="emerald" />
                <PreflightCard label="活跃占用" value={blockerCounts.activeClaims} tone="amber" />
                <PreflightCard label="未结束候选" value={blockerCounts.pendingCandidates} tone="red" />
                <PreflightCard label="需要重建" value={Math.max(preflight?.rebuild_count ?? 0, blockerCounts.rebuild)} tone="teal" />
              </div>
              {!!preflight?.warnings.length && (
                <ul className="space-y-1 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
                  {preflight.warnings.map((warning) => <li key={`${warning.code}-${warning.unit_id}`}>· {warning.message}</li>)}
                </ul>
              )}
              {!!preflight?.blockers.length && (
                <div className="rounded-lg border border-red-200 bg-red-50 p-3">
                  <p className="text-xs font-semibold text-red-800">发现 {preflight.blocking_count} 个阻断项</p>
                  {blockerCounts.other > 0 && <p className="mt-1 text-[11px] font-medium text-red-700">其他阻断 {blockerCounts.other}</p>}
                  <ul className="mt-2 space-y-2 text-xs text-red-700">
                    {preflight.blockers.map((blocker, index) => (
                      <li key={`${blocker.code}-${blocker.unit_revision_id ?? index}`}>
                        <span>· {blocker.message}</span>
                        {blocker.task_id && <span className="ml-1 font-mono">{blocker.task_id}</span>}
                        {blocker.target_href && <Link href={blocker.target_href} className="ml-2 font-semibold hover:underline">查看任务</Link>}
                      </li>
                    ))}
                  </ul>
                  {!!preciseBlockers.length && (
                    <button type="button" disabled={busy} onClick={() => void excludeBlockedUnits()} className="mt-3 rounded-lg border border-red-300 bg-white px-3 py-1.5 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50">排除这些单元</button>
                  )}
                </div>
              )}
              {semanticUnavailable && <SemanticUnavailable message={message ?? '当前没有可用的语义契约'} />}
              {!semanticUnavailable && message && (
                <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">
                  <AlertCircle className="mt-0.5 size-4 shrink-0" />
                  <div>
                    <p>{message}</p>
                    {claimConflict?.taskId && <p className="mt-1 font-mono font-semibold">{claimConflict.taskId}</p>}
                    {claimConflict?.targetHref && <Link href={claimConflict.targetHref} className="mt-1 inline-block font-semibold hover:underline">查看冲突任务</Link>}
                  </div>
                </div>
              )}
              {preflight?.can_submit && !preflight.blocking_count && !semanticUnavailable && !claimConflict && (
                <div className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-700">
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
                  <span>{preflight.buildable_count} 个精确修订可创建构建任务。创建后结果进入知识审核，不会直接发布。</span>
                </div>
              )}
            </div>
          )}
          {step !== 3 && message && !semanticUnavailable && <p role="alert" className="mt-4 text-xs font-medium text-red-700">{message}</p>}
        </div>

        <footer className="flex items-center gap-2 border-t border-slate-200 bg-slate-50/70 px-5 py-4">
          {step > 1 && <button type="button" disabled={busy} onClick={() => { setMessage(null); setClaimConflict(null); setStep((step - 1) as WizardStep) }} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50">上一步</button>}
          <span className="ml-auto text-xs text-slate-400">已选 {selectedUnits.length} 个精确修订</span>
          {step === 1 && <PrimaryButton disabled={busy || !selectedUnits.length} onClick={moveToConfiguration}>下一步：确认配置</PrimaryButton>}
          {step === 2 && <PrimaryButton disabled={busy} onClick={() => void moveToPreflight()}>{busy ? '正在预检…' : '下一步：冲突预检'}</PrimaryButton>}
          {step === 3 && <PrimaryButton disabled={busy || !preflight?.can_submit || Boolean(preflight.blocking_count) || semanticUnavailable || Boolean(claimConflict)} onClick={() => void createTask()}>{busy ? '正在创建…' : '创建构建任务'}</PrimaryButton>}
        </footer>
      </DialogContent>
    </Dialog>
  )
}

function PrimaryButton({ disabled, onClick, children }: { disabled: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button type="button" disabled={disabled} onClick={onClick} className="rounded-lg bg-emerald-700 px-3.5 py-2 text-sm font-semibold text-white shadow-[0_1px_2px_rgba(4,120,87,0.3)] transition-all hover:bg-emerald-800 active:scale-[0.98] disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none">{children}</button>
}

function ReadonlyField({ label, value }: { label: string; value: string }) {
  return <label className="block text-xs font-medium text-slate-600">{label}<input aria-label={label} readOnly value={value} className="mt-1.5 h-9 w-full rounded-lg border border-slate-200 bg-slate-50 px-3 font-mono text-[11px] font-normal text-slate-600" /></label>
}

function PreflightCard({ label, value, tone }: { label: string; value: number; tone: 'emerald' | 'amber' | 'red' | 'teal' }) {
  const toneClass = { emerald: 'border-emerald-200 bg-emerald-50 text-emerald-700', amber: 'border-amber-200 bg-amber-50 text-amber-700', red: 'border-red-200 bg-red-50 text-red-700', teal: 'border-teal-200 bg-teal-50 text-teal-700' }[tone]
  return <article aria-label={`${label}预检`} className={`rounded-lg border p-3 ${toneClass}`}><p className="text-xs font-medium">{label}</p><p className="mt-1 font-mono text-xl font-semibold tabular-nums">{value}</p></article>
}

function SemanticUnavailable({ message }: { message: string }) {
  return (
    <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">
      <div className="flex items-start gap-2"><AlertCircle className="mt-0.5 size-4 shrink-0" /><span>{message}</span></div>
      <Link href="/semantic-layer/metrics" className="mt-2 inline-flex items-center gap-1 font-semibold hover:underline"><FileCheck2 className="size-3.5" />前往语义层查看</Link>
    </div>
  )
}

function revisionKey(unit: EligibleKnowledgeUnit): string {
  return `${unit.doc_id}:${unit.unit_id}:${unit.unit_revision_id}`
}

function defaultTaskName(units: EligibleKnowledgeUnit[]): string {
  if (!units.length) return ''
  return `${units[0].doc_title}等 ${units.length} 个单元`
}

function classifyBlockers(preflight: KnowledgeBuildPreflight | null) {
  const counts = { activeClaims: 0, pendingCandidates: 0, rebuild: 0, other: 0 }
  for (const blocker of preflight?.blockers ?? []) {
    const target = blocker.target_href ?? ''
    if (blocker.code === 'UNIT_ALREADY_CLAIMED' && target.includes('/knowledge/build')) {
      counts.activeClaims += 1
    } else if (blocker.code === 'UNIT_ALREADY_CLAIMED' && (target.includes('/knowledge/review') || target.includes('/knowledge/releases'))) {
      counts.pendingCandidates += 1
    } else if (blocker.code === 'REBUILD_MODE_REQUIRED' || blocker.code === 'REBUILD_REASON_REQUIRED') {
      counts.rebuild += 1
    } else {
      counts.other += 1
    }
  }
  return counts
}

function occupiedStageLabel(targetHref: string | null): string {
  const target = targetHref ?? ''
  if (target.includes('/knowledge/build')) return '正在知识构建'
  if (target.includes('/knowledge/review')) return '等待知识审核'
  if (target.includes('/knowledge/releases')) return '等待发布'
  return '已被构建任务占用'
}
