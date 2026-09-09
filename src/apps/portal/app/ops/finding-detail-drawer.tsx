'use client'

// 问题详情抽屉 — issue #50：证据快照 + 生命周期时间线 + 忽略/重开操作；
// issue #53：白名单 L1「执行修复」+ 修复留痕时间线。
// 由 /ops 列表行点开；操作成功后以响应回填详情并通知列表刷新。
import { useCallback, useEffect, useState } from 'react'
import { Loader2, RotateCcw, Stethoscope, Wrench, X } from 'lucide-react'
import {
  getOpsFinding,
  ignoreOpsFinding,
  listOpsRemediationActions,
  remediateOpsFinding,
  reopenOpsFinding,
  type OpsFindingDetailDto,
  type OpsRemediationActionDto,
  type OpsRemediationRunDto,
} from '@/lib/ops-api'
import { ApiClientError } from '@/lib/types'
import {
  ACTION_LABELS,
  ASSET_LABELS,
  CHECK_LABELS,
  PAYLOAD_KEY_LABELS,
  RUN_STATUS_LABELS,
  SEVERITY_BADGES,
  SEVERITY_LABELS,
  STATUS_BADGES,
  STATUS_LABELS,
  VERIFICATION_LABELS,
  formatPayloadValue,
  formatTime,
} from './shared'

interface FindingDetailDrawerProps {
  findingId: string | null
  canWrite: boolean
  onClose: () => void
  /** 生命周期变更（忽略/重开/修复）后通知列表刷新 */
  onMutated: () => void
}

interface TimelineEntry {
  at: string
  label: string
  sub: string | null
  /** sub 前缀（事件原因用「原因：」，修复留痕自带结构化摘要不加前缀） */
  subPrefix: string | null
}

/** 修复留痕时间线副标题：动作执行状态 · 验证结果 · 未发起原因 */
function runSub(run: OpsRemediationRunDto): string {
  const parts: string[] = [RUN_STATUS_LABELS[run.status]]
  if (run.verification_result) parts.push(VERIFICATION_LABELS[run.verification_result])
  else parts.push('未验证')
  const error = run.after_evidence.error
  if (typeof error === 'string') parts.push(`原因：${error}`)
  return parts.join(' · ')
}

function buildTimeline(detail: OpsFindingDetailDto): TimelineEntry[] {
  const { finding, events, remediations } = detail
  const entries: TimelineEntry[] = [
    { at: finding.first_seen_at, label: '首次发现', sub: null, subPrefix: null },
    ...events.map((event) => ({
      at: event.created_at,
      label: event.event_type === 'ignored'
        ? `由 ${event.actor} 忽略`
        : event.event_type === 'resolved'
          ? `由 ${event.actor} 解决`
          : `由 ${event.actor} 重开`,
      sub: event.reason,
      subPrefix: '原因：',
    })),
    ...remediations.map((run) => ({
      at: run.created_at,
      label: `由 ${run.created_by} 执行修复（${ACTION_LABELS[run.action] ?? run.action}）`,
      sub: runSub(run),
      subPrefix: null,
    })),
    { at: finding.last_seen_at, label: '最近巡检确认', sub: null, subPrefix: null },
  ]
  return entries.sort((a, b) => a.at.localeCompare(b.at))
}

export default function FindingDetailDrawer({
  findingId,
  canWrite,
  onClose,
  onMutated,
}: FindingDetailDrawerProps) {
  const [detail, setDetail] = useState<OpsFindingDetailDto | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [mutating, setMutating] = useState(false)
  const [remediating, setRemediating] = useState(false)
  const [actions, setActions] = useState<OpsRemediationActionDto[]>([])
  const [ignoreDraftOpen, setIgnoreDraftOpen] = useState(false)
  const [ignoreReason, setIgnoreReason] = useState('')

  useEffect(() => {
    if (!findingId) return
    setLoading(true)
    setError(null)
    setActionError(null)
    setIgnoreDraftOpen(false)
    setIgnoreReason('')
    getOpsFinding(findingId)
      .then(setDetail)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
    // 白名单决定是否展示「执行修复」入口（与详情并行加载）
    if (canWrite) {
      listOpsRemediationActions()
        .then(setActions)
        .catch(() => setActions([]))
    }
  }, [findingId, canWrite])

  // Escape 关闭（对话框键盘化，与 flow 编辑器约定一致）
  useEffect(() => {
    if (!findingId) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [findingId, onClose])

  const errorMessage = (e: unknown): string =>
    e instanceof ApiClientError
      ? `${e.detail.error_code}：${e.detail.message}`
      : e instanceof Error ? e.message : String(e)

  const handleIgnore = useCallback(async () => {
    if (!detail) return
    setMutating(true)
    setActionError(null)
    try {
      const updated = await ignoreOpsFinding(
        detail.finding.finding_id, detail.finding.revision, ignoreReason.trim(),
      )
      setDetail(updated)
      setIgnoreDraftOpen(false)
      setIgnoreReason('')
      onMutated()
    } catch (e) {
      setActionError(errorMessage(e))
    } finally {
      setMutating(false)
    }
  }, [detail, ignoreReason, onMutated])

  const handleReopen = useCallback(async () => {
    if (!detail) return
    setMutating(true)
    setActionError(null)
    try {
      setDetail(await reopenOpsFinding(detail.finding.finding_id, detail.finding.revision))
      onMutated()
    } catch (e) {
      setActionError(errorMessage(e))
    } finally {
      setMutating(false)
    }
  }, [detail, onMutated])

  const handleRemediate = useCallback(async () => {
    if (!detail) return
    setRemediating(true)
    setActionError(null)
    try {
      const result = await remediateOpsFinding(
        detail.finding.finding_id, detail.finding.revision,
      )
      setDetail(result.detail)
      onMutated()
    } catch (e) {
      setActionError(errorMessage(e))
    } finally {
      setRemediating(false)
    }
  }, [detail, onMutated])

  if (!findingId) return null

  const finding = detail?.finding
  const timeline = detail ? buildTimeline(detail) : []
  const remediation = finding
    ? actions.find((a) => a.check_id === finding.check_id) ?? null
    : null

  return (
    <div className="fixed inset-0 z-40 flex justify-end" data-testid="ops-detail-overlay">
      <button
        type="button"
        aria-label="关闭详情"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-slate-900/30"
        data-testid="ops-detail-backdrop"
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="问题详情"
        className="relative flex h-full w-full max-w-md flex-col overflow-y-auto bg-white shadow-xl"
        data-testid="ops-detail-drawer"
      >
        {loading || !detail || !finding ? (
          <div className="flex h-40 items-center justify-center gap-2 text-sm text-slate-500">
            {error
              ? <span data-testid="ops-detail-error">{error}</span>
              : <><Loader2 className="size-4 animate-spin" />加载问题详情…</>}
          </div>
        ) : (
          <>
            <header className="sticky top-0 flex items-start gap-2 border-b border-slate-100 bg-white px-5 py-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className={`inline-flex rounded-full px-2 py-px text-[10px] font-semibold ring-1 ${SEVERITY_BADGES[finding.severity]}`}>
                    {SEVERITY_LABELS[finding.severity]}
                  </span>
                  <span className={`inline-flex rounded-full px-2 py-px text-[10px] font-semibold ring-1 ${STATUS_BADGES[finding.status]}`}>
                    {STATUS_LABELS[finding.status]}
                  </span>
                  <span className="text-sm font-semibold text-slate-900">
                    {CHECK_LABELS[finding.check_id] ?? finding.check_id}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  {ASSET_LABELS[finding.asset_type] ?? finding.asset_type}
                  <span className="ml-1.5 font-mono text-[11px] text-slate-700">{finding.asset_id}</span>
                </p>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="关闭"
                className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                data-testid="ops-detail-close"
              >
                <X className="size-4" />
              </button>
            </header>

            <div className="space-y-5 px-5 py-4 text-xs">
              {actionError && (
                <p className="rounded-md bg-red-50 px-3 py-2 text-red-700" data-testid="ops-detail-action-error">
                  {actionError}
                </p>
              )}

              <section aria-label="基础信息" className="grid grid-cols-2 gap-x-4 gap-y-2 text-slate-600">
                <div>
                  <dt className="text-slate-400">首次发现</dt>
                  <dd>{formatTime(finding.first_seen_at)}</dd>
                </div>
                <div>
                  <dt className="text-slate-400">最近发现</dt>
                  <dd>{formatTime(finding.last_seen_at)}</dd>
                </div>
                <div>
                  <dt className="text-slate-400">巡检确认次数</dt>
                  <dd>{finding.occurrence_count} 次</dd>
                </div>
                <div>
                  <dt className="text-slate-400">问题指纹</dt>
                  <dd className="truncate font-mono text-[11px]" title={finding.fingerprint}>
                    {finding.fingerprint}
                  </dd>
                </div>
              </section>

              <section aria-label="证据快照">
                <h2 className="mb-2 text-xs font-semibold text-slate-900">证据快照</h2>
                <dl className="divide-y divide-slate-50 rounded-lg border border-slate-100">
                  {Object.entries(finding.payload).map(([key, value]) => (
                    <div key={key} className="flex gap-3 px-3 py-2">
                      <dt className="w-28 shrink-0 text-slate-400">
                        {PAYLOAD_KEY_LABELS[key] ?? key}
                      </dt>
                      <dd className="min-w-0 break-words text-slate-700">
                        {key.endsWith('_at')
                          ? formatTime(typeof value === 'string' ? value : '')
                          : formatPayloadValue(key, value)}
                      </dd>
                    </div>
                  ))}
                  {Object.keys(finding.payload).length === 0 && (
                    <div className="px-3 py-2 text-slate-400">本次证据为空</div>
                  )}
                </dl>
              </section>

              <section aria-label="诊断">
                <h2 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-slate-900">
                  <Stethoscope className="size-3.5 text-slate-400" />诊断
                </h2>
                {finding.diagnosis ? (
                  <pre className="overflow-x-auto rounded-lg bg-slate-50 px-3 py-2 text-[11px] text-slate-700">
                    {JSON.stringify(finding.diagnosis, null, 2)}
                  </pre>
                ) : (
                  <p className="rounded-lg border border-dashed border-slate-200 px-3 py-2 text-slate-400" data-testid="ops-detail-diagnosis">
                    诊断报告未生成（P1 诊断引擎接入后自动产出）
                  </p>
                )}
              </section>

              {canWrite && (
                <section aria-label="状态操作" className="space-y-2">
                  <h2 className="text-xs font-semibold text-slate-900">状态操作</h2>
                  {finding.status === 'open' && remediation && (
                    <div className="space-y-1.5" data-testid="ops-detail-remediate-block">
                      <button
                        type="button"
                        onClick={handleRemediate}
                        disabled={remediating || mutating}
                        className="inline-flex items-center gap-1.5 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-40"
                        data-testid="ops-detail-remediate"
                      >
                        {remediating
                          ? <Loader2 className="size-3.5 animate-spin" />
                          : <Wrench className="size-3.5" />}
                        执行修复（{ACTION_LABELS[remediation.action] ?? remediation.action}）
                      </button>
                      <p className="text-[11px] text-slate-400">
                        {remediation.description}；执行后自动重跑检查验证，通过才标记已解决。
                      </p>
                    </div>
                  )}
                  {finding.status === 'open' && !ignoreDraftOpen && (
                    <button
                      type="button"
                      onClick={() => setIgnoreDraftOpen(true)}
                      disabled={mutating}
                      className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40"
                      data-testid="ops-detail-ignore"
                    >
                      忽略此问题
                    </button>
                  )}
                  {finding.status === 'open' && ignoreDraftOpen && (
                    <div className="space-y-2 rounded-lg border border-slate-200 p-3" data-testid="ops-detail-ignore-form">
                      <label className="block text-slate-500" htmlFor="ops-ignore-reason">
                        忽略原因（必填，写入流转记录）
                      </label>
                      <textarea
                        id="ops-ignore-reason"
                        value={ignoreReason}
                        onChange={(e) => setIgnoreReason(e.target.value)}
                        rows={3}
                        maxLength={500}
                        placeholder="例：DBA 已排期维护，窗口期内不处理"
                        className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-xs focus:border-slate-400 focus:outline-none"
                        data-testid="ops-detail-ignore-reason"
                      />
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => { setIgnoreDraftOpen(false); setIgnoreReason('') }}
                          disabled={mutating}
                          className="rounded-md px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-50 disabled:opacity-40"
                        >
                          取消
                        </button>
                        <button
                          type="button"
                          onClick={handleIgnore}
                          disabled={mutating || ignoreReason.trim() === ''}
                          className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-40"
                          data-testid="ops-detail-ignore-confirm"
                        >
                          {mutating && <Loader2 className="size-3.5 animate-spin" />}
                          确认忽略
                        </button>
                      </div>
                    </div>
                  )}
                  {finding.status !== 'open' && (
                    <button
                      type="button"
                      onClick={handleReopen}
                      disabled={mutating}
                      className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-40"
                      data-testid="ops-detail-reopen"
                    >
                      {mutating
                        ? <Loader2 className="size-3.5 animate-spin" />
                        : <RotateCcw className="size-3.5" />}
                      重开此问题
                    </button>
                  )}
                </section>
              )}

              <section aria-label="流转时间线">
                <h2 className="mb-2 text-xs font-semibold text-slate-900">流转时间线</h2>
                <ol className="space-y-0" data-testid="ops-detail-timeline">
                  {timeline.map((entry, index) => (
                    <li key={`${entry.at}-${index}`} className="flex gap-3">
                      <div className="flex flex-col items-center">
                        <span className={`mt-1 size-2 rounded-full ${index === timeline.length - 1 ? 'bg-slate-300' : 'bg-sky-400'}`} />
                        {index < timeline.length - 1 && <span className="w-px flex-1 bg-slate-200" />}
                      </div>
                      <div className="pb-4">
                        <p className="text-slate-700">{entry.label}</p>
                        <p className="mt-0.5 text-[11px] text-slate-400">{formatTime(entry.at)}</p>
                        {entry.sub && (
                          <p className="mt-1 rounded-md bg-slate-50 px-2 py-1 text-[11px] text-slate-600">
                            {entry.subPrefix}{entry.sub}
                          </p>
                        )}
                      </div>
                    </li>
                  ))}
                </ol>
              </section>
            </div>
          </>
        )}
      </aside>
    </div>
  )
}
