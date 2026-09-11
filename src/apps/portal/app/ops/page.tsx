'use client'

// 健康运营 /ops 页 — #45：开放问题列表（severity/资产过滤 + 分页）+「立即巡检」。
// #50：状态筛选与状态徽标、行点开详情抽屉（忽略/重开生命周期操作）。
// #52：顶部巡检摘要条（最近巡检/结果/下次巡检时间/周期）。
import { useCallback, useEffect, useState } from 'react'
import { CalendarClock, HeartPulse, Loader2, RefreshCw, ShieldCheck } from 'lucide-react'
import {
  getOpsInspectionSummary,
  hasOpsPermission,
  listOpsFindings,
  runOpsInspection,
  type OpsAssetType,
  type OpsFindingDto,
  type OpsFindingPageDto,
  type OpsFindingStatus,
  type OpsInspectionSummaryDto,
  type OpsSeverity,
} from '@/lib/ops-api'
import { ApiClientError } from '@/lib/types'
import FindingDetailDrawer from './finding-detail-drawer'
import {
  ASSET_LABELS,
  CHECK_LABELS,
  INSPECTION_STATUS_BADGES,
  INSPECTION_STATUS_LABELS,
  INSPECTION_TRIGGER_LABELS,
  SEVERITY_BADGES,
  SEVERITY_LABELS,
  STATUS_BADGES,
  STATUS_LABELS,
  formatTime,
  inspectionIntervalLabel,
} from './shared'

/** 证据摘要：problem 优先展示，附 1-2 个关键安全字段 */
function evidenceSummary(finding: OpsFindingDto): string {
  const payload = finding.payload ?? {}
  const parts: string[] = []
  if (typeof payload.safe_probe_message === 'string' && payload.safe_probe_message) {
    parts.push(payload.safe_probe_message)
  }
  if (typeof payload.last_error_code === 'string' && payload.last_error_code) {
    parts.push(`错误码 ${payload.last_error_code}`)
  }
  if (typeof payload.grace_minutes === 'number') {
    parts.push(`超宽限 ${payload.grace_minutes} 分钟`)
  }
  return parts.join(' · ') || '—'
}

export default function OpsPage() {
  const [page, setPage] = useState<OpsFindingPageDto | null>(null)
  const [summary, setSummary] = useState<OpsInspectionSummaryDto | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [severity, setSeverity] = useState<OpsSeverity | ''>('')
  const [assetType, setAssetType] = useState<OpsAssetType | ''>('')
  const [statusFilter, setStatusFilter] = useState<OpsFindingStatus | ''>('')
  const [pageNum, setPageNum] = useState(1)
  const [inspecting, setInspecting] = useState(false)
  const [inspectionNote, setInspectionNote] = useState<string | null>(null)
  const [activeFindingId, setActiveFindingId] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      // 问题列表与巡检摘要并行刷新（#52 摘要条与列表同生命周期）
      const [result, inspectionSummary] = await Promise.all([
        listOpsFindings({
          status: statusFilter || undefined,
          severity: severity || undefined,
          asset_type: assetType || undefined,
          page: pageNum,
          page_size: 20,
        }),
        getOpsInspectionSummary(),
      ])
      setPage(result)
      setSummary(inspectionSummary)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [severity, assetType, statusFilter, pageNum])

  useEffect(() => { reload() }, [reload])

  // 过滤条件变化后回到第一页
  const changeSeverity = (value: OpsSeverity | '') => {
    setSeverity(value)
    setPageNum(1)
  }
  const changeAssetType = (value: OpsAssetType | '') => {
    setAssetType(value)
    setPageNum(1)
  }
  const changeStatus = (value: OpsFindingStatus | '') => {
    setStatusFilter(value)
    setPageNum(1)
  }

  const handleInspect = async () => {
    setInspecting(true)
    setInspectionNote(null)
    try {
      const result = await runOpsInspection()
      const errorNote = result.checker_errors.length
        ? `；${result.checker_errors.length} 个检查器执行失败`
        : ''
      setInspectionNote(
        `巡检完成（${result.check_count} 项检查）：本次发现 ${result.finding_count} 个问题、新发现 ${result.new_finding_count} 个${errorNote}`,
      )
      setPageNum(1)
      await reload()
    } catch (e) {
      setError(
        e instanceof ApiClientError
          ? `${e.detail.error_code}：${e.detail.message}`
          : e instanceof Error ? e.message : String(e),
      )
    } finally {
      setInspecting(false)
    }
  }

  const canWrite = hasOpsPermission('write')
  const totalPages = page ? Math.max(1, Math.ceil(page.total / page.page_size)) : 1
  const selectCls =
    'rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs focus:border-slate-400 focus:outline-none'

  return (
    <div className="mx-auto max-w-5xl space-y-4" data-testid="ops-page">
      <header className="flex flex-wrap items-center gap-3">
        <span className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-slate-900 px-2.5 py-2 text-white">
          <HeartPulse className="size-4" />
        </span>
        <div className="min-w-0">
          <h1 className="text-base font-semibold text-slate-900">健康运营</h1>
          <p className="text-xs text-slate-500">
            资产开放问题库：数据同步 / 数据源连接等检查项，巡检去重累计，fail closed 不自动处置
          </p>
        </div>
        <button
          type="button"
          onClick={handleInspect}
          disabled={inspecting || !canWrite}
          title={canWrite ? undefined : '缺少 ops:write 权限'}
          className="ml-auto inline-flex shrink-0 items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-40"
          data-testid="ops-inspect-button"
        >
          {inspecting
            ? <Loader2 className="size-3.5 animate-spin" />
            : <RefreshCw className="size-3.5" />}
          立即巡检
        </button>
      </header>

      {summary && (
        <div
          className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs shadow-sm"
          data-testid="ops-inspection-summary"
        >
          <span className="inline-flex shrink-0 items-center gap-1.5 font-medium text-slate-700">
            <CalendarClock className="size-3.5 text-slate-400" />
            巡检调度
          </span>
          {summary.latest ? (
            <span className="text-slate-600" data-testid="ops-summary-last">
              最近巡检 {formatTime(summary.latest.finished_at ?? summary.latest.started_at)}
              <span className={`ml-1.5 inline-flex rounded-full px-2 py-px text-[10px] font-semibold ring-1 ${INSPECTION_STATUS_BADGES[summary.latest.status]}`}>
                {INSPECTION_STATUS_LABELS[summary.latest.status]}
              </span>
              <span className="ml-1.5">
                {INSPECTION_TRIGGER_LABELS[summary.latest.trigger_source]} · 新发现 {summary.latest.new_finding_count}
              </span>
            </span>
          ) : (
            <span className="text-slate-400" data-testid="ops-summary-last">尚无巡检记录</span>
          )}
          {summary.in_progress ? (
            <span className="inline-flex items-center gap-1.5 text-amber-600" data-testid="ops-summary-next">
              <Loader2 className="size-3 animate-spin" />巡检进行中…
            </span>
          ) : (
            <span className="text-slate-600" data-testid="ops-summary-next">
              下次巡检 {formatTime(summary.next_run_at)}
            </span>
          )}
          <span className="ml-auto shrink-0 text-slate-400" data-testid="ops-summary-interval">
            周期 {inspectionIntervalLabel(summary.interval_minutes)}
          </span>
        </div>
      )}

      {error && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700" data-testid="ops-error">
          {error}
        </p>
      )}
      {inspectionNote && (
        <p
          className={`rounded-md px-3 py-2 text-xs ${inspectionNote.includes('失败') ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'}`}
          data-testid="ops-inspection-note"
        >
          {inspectionNote}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2" data-testid="ops-filters">
        <label className="flex items-center gap-1.5 text-xs text-slate-500">
          严重度
          <select
            className={selectCls}
            value={severity}
            aria-label="按严重度过滤"
            onChange={(e) => changeSeverity(e.target.value as OpsSeverity | '')}
          >
            <option value="">全部</option>
            <option value="critical">严重</option>
            <option value="warning">警告</option>
            <option value="info">提示</option>
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-500">
          资产类型
          <select
            className={selectCls}
            value={assetType}
            aria-label="按资产类型过滤"
            onChange={(e) => changeAssetType(e.target.value as OpsAssetType | '')}
          >
            <option value="">全部</option>
            <option value="data">数据</option>
            <option value="skill">技能</option>
            <option value="knowledge">知识</option>
            <option value="runtime">运行时</option>
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-500">
          状态
          <select
            className={selectCls}
            value={statusFilter}
            aria-label="按状态过滤"
            onChange={(e) => changeStatus(e.target.value as OpsFindingStatus | '')}
          >
            <option value="">全部</option>
            <option value="open">开放</option>
            <option value="ignored">已忽略</option>
            <option value="resolved">已解决</option>
          </select>
        </label>
        {page && (
          <span className="ml-auto text-xs text-slate-500" data-testid="ops-total">
            问题 {page.total} 条
          </span>
        )}
      </div>

      {page === null ? (
        <div className="flex h-40 items-center justify-center gap-2 text-sm text-slate-500">
          <Loader2 className="size-4 animate-spin" />加载问题清单…
        </div>
      ) : page.items.length === 0 ? (
        <div
          className="rounded-lg border border-dashed border-emerald-300 bg-emerald-50/40 p-10 text-center"
          data-testid="ops-empty"
        >
          <ShieldCheck className="mx-auto size-8 text-emerald-500" />
          <p className="mt-2 text-sm font-medium text-emerald-700">全部健康</p>
          <p className="mt-1 text-xs text-slate-500">
            当前筛选条件下没有问题记录。点击右上角「立即巡检」重新检查各资产域。
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm" data-testid="ops-table">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-100 text-slate-500">
                <th className="px-4 py-2.5 font-medium">严重度</th>
                <th className="px-4 py-2.5 font-medium">资产</th>
                <th className="px-4 py-2.5 font-medium">检查项</th>
                <th className="px-4 py-2.5 font-medium">证据摘要</th>
                <th className="px-4 py-2.5 font-medium">状态</th>
                <th className="px-4 py-2.5 font-medium">首次发现</th>
                <th className="px-4 py-2.5 font-medium">最近发现</th>
                <th className="px-4 py-2.5 font-medium">次数</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((finding) => (
                <tr
                  key={finding.finding_id}
                  onClick={() => setActiveFindingId(finding.finding_id)}
                  className="cursor-pointer border-b border-slate-50 last:border-0 hover:bg-amber-50/30"
                  data-testid="ops-finding-row"
                >
                  <td className="px-4 py-2.5">
                    <span className={`inline-flex rounded-full px-2 py-px text-[10px] font-semibold ring-1 ${SEVERITY_BADGES[finding.severity]}`}>
                      {SEVERITY_LABELS[finding.severity]}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 whitespace-nowrap">
                    <span className="text-slate-500">{ASSET_LABELS[finding.asset_type]}</span>
                    <span className="ml-1.5 font-mono text-[11px] text-slate-700">{finding.asset_id}</span>
                  </td>
                  <td className="px-4 py-2.5 whitespace-nowrap text-slate-700">
                    {CHECK_LABELS[finding.check_id] ?? finding.check_id}
                  </td>
                  <td className="max-w-[16rem] truncate px-4 py-2.5 text-slate-500" title={evidenceSummary(finding)}>
                    {evidenceSummary(finding)}
                  </td>
                  <td className="px-4 py-2.5 whitespace-nowrap">
                    <span className={`inline-flex rounded-full px-2 py-px text-[10px] font-semibold ring-1 ${STATUS_BADGES[finding.status]}`}>
                      {STATUS_LABELS[finding.status]}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 whitespace-nowrap text-slate-500">
                    {formatTime(finding.first_seen_at)}
                  </td>
                  <td className="px-4 py-2.5 whitespace-nowrap text-slate-500">
                    {formatTime(finding.last_seen_at)}
                  </td>
                  <td className="px-4 py-2.5 text-slate-700">{finding.occurrence_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {page && page.total > page.page_size && (
        <div className="flex items-center justify-end gap-2" data-testid="ops-pagination">
          <button
            type="button"
            onClick={() => setPageNum((n) => Math.max(1, n - 1))}
            disabled={pageNum <= 1}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs shadow-sm disabled:opacity-30"
          >
            上一页
          </button>
          <span className="text-xs text-slate-500">第 {page.page} / {totalPages} 页</span>
          <button
            type="button"
            onClick={() => setPageNum((n) => Math.min(totalPages, n + 1))}
            disabled={pageNum >= totalPages}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs shadow-sm disabled:opacity-30"
          >
            下一页
          </button>
        </div>
      )}

      <FindingDetailDrawer
        findingId={activeFindingId}
        canWrite={canWrite}
        onClose={() => setActiveFindingId(null)}
        onMutated={reload}
      />
    </div>
  )
}
