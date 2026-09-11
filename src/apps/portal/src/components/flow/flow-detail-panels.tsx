'use client'

// 详情面板三件套：校验报告（点击定位节点）/ 编译预览（View DDL + 计划 + 产物哈希）/ 修订历史（回滚）。
// 纯展示 + 回调，不直接请求 API（编辑页统一编排，便于乐观锁时序控制）。
import { AlertTriangle, CheckCircle2, History, Loader2, RefreshCw, Undo2 } from 'lucide-react'
import type {
  CompiledFlowArtifactDto, FlowRevisionViewDto, FlowValidationIssue, FlowValidationReportDto,
} from '@/lib/flow-api'

export function ValidationPanel({ report, onFocusNode }: {
  report: FlowValidationReportDto | null
  onFocusNode: (nodeId: string) => void
}) {
  if (!report) {
    return <p className="px-1 py-2 text-xs text-slate-500">尚未运行校验；点击顶部「校验」获取报告。</p>
  }
  if (report.issues.length === 0) {
    return (
      <p className="flex items-center gap-2 px-1 py-2 text-xs text-emerald-700">
        <CheckCircle2 className="size-4" />校验通过，无阻断与告警。
      </p>
    )
  }
  return (
    <div className="space-y-2" data-testid="flow-validation-issues">
      {report.has_blocking && (
        <p className="flex items-center gap-2 rounded-md bg-red-50 px-2 py-1.5 text-xs font-medium text-red-700">
          <AlertTriangle className="size-4" />存在阻断问题，发布将 fail closed。
        </p>
      )}
      {report.issues.map((issue: FlowValidationIssue, i) => (
        <button
          key={i}
          type="button"
          disabled={!issue.node_id}
          onClick={() => issue.node_id && onFocusNode(issue.node_id)}
          className={`block w-full rounded-md border px-2 py-1.5 text-left text-xs transition-colors ${
            issue.severity === 'blocking'
              ? 'border-red-200 bg-red-50/60 text-red-800'
              : 'border-amber-200 bg-amber-50/60 text-amber-800'
          } ${issue.node_id ? 'hover:border-slate-400' : 'cursor-default'}`}
          data-testid="flow-validation-issue"
        >
          <span className="font-mono text-[11px]">{issue.code}</span>
          {issue.node_id && <span className="ml-1 text-[11px] opacity-70">@{issue.node_id}（点击定位）</span>}
          <span className="mt-0.5 block">{issue.message}</span>
        </button>
      ))}
    </div>
  )
}

export function PreviewPanel({ artifact, loading, onRefresh }: {
  artifact: CompiledFlowArtifactDto | null
  loading: boolean
  onRefresh: () => void
}) {
  return (
    <div className="space-y-2" data-testid="flow-preview-panel">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500">
          {artifact
            ? <>视图 <span className="font-mono text-slate-800">{artifact.view_name}</span>
              　产物哈希 <span className="font-mono text-[11px]">{artifact.artifact_hash.slice(0, 16)}…</span></>
            : '预览发布前的编译产物（CREATE OR REPLACE VIEW，PG 落地库方言）。'}
        </p>
        <button type="button" onClick={onRefresh} disabled={loading}
          className="inline-flex items-center gap-1 text-xs text-sky-600 hover:underline disabled:opacity-40">
          {loading ? <Loader2 className="size-3 animate-spin" /> : <RefreshCw className="size-3" />}
          刷新
        </button>
      </div>
      {artifact && (
        <>
          <pre className="max-h-56 overflow-auto rounded-md bg-slate-900 p-2.5 text-[11px] leading-5 text-slate-100">
            {artifact.view_sql}
          </pre>
          <ol className="space-y-1">
            {artifact.query_plan.map((step) => (
              <li key={step.step_index} className="text-xs text-slate-600">
                <span className="mr-1 font-mono text-slate-400">{step.step_index}.</span>
                <span className="font-medium">{step.node_id}</span>（{step.node_type}）— {step.description}
              </li>
            ))}
          </ol>
        </>
      )}
    </div>
  )
}

export function RevisionsPanel({ revisions, onRollback, rollbackBusy }: {
  revisions: FlowRevisionViewDto[]
  onRollback: (revisionId: string) => void
  rollbackBusy: string | null
}) {
  if (revisions.length === 0) {
    return <p className="px-1 py-2 text-xs text-slate-500">尚无发布修订；发布后此处出现不可变证据链。</p>
  }
  return (
    <ul className="space-y-1.5" data-testid="flow-revisions">
      {revisions.map(({ revision, is_active }) => (
        <li key={revision.revision_id}
          className={`flex items-center justify-between gap-2 rounded-md border px-2 py-1.5 text-xs ${
            is_active ? 'border-emerald-300 bg-emerald-50/60' : 'border-slate-200'
          }`}>
          <div className="min-w-0">
            <p className="flex items-center gap-1.5 font-medium text-slate-800">
              <History className="size-3.5 shrink-0 text-slate-400" />
              <span className="truncate font-mono text-[11px]">{revision.revision_id}</span>
              {is_active && <span className="rounded bg-emerald-600 px-1 py-0.5 text-[10px] text-white">活跃</span>}
            </p>
            <p className="mt-0.5 truncate text-[11px] text-slate-500">
              rev {revision.flow_revision} · {revision.published_at} · {revision.published_by}
              　产物 <span className="font-mono">{revision.artifact_hash.slice(0, 10)}…</span>
            </p>
          </div>
          {!is_active && (
            <button type="button" onClick={() => onRollback(revision.revision_id)}
              disabled={rollbackBusy === revision.revision_id}
              className="inline-flex shrink-0 items-center gap-1 rounded border border-slate-300 px-2 py-1 text-[11px] text-slate-700 transition-colors hover:border-slate-500 disabled:opacity-40">
              {rollbackBusy === revision.revision_id ? <Loader2 className="size-3 animate-spin" /> : <Undo2 className="size-3" />}
              回滚到此版
            </button>
          )}
        </li>
      ))}
    </ul>
  )
}
