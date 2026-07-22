'use client'

import { useState } from 'react'
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react'

/* ============================================================
   ExecutionTracePanel — 问答执行链路
   展示后端 trace_event 驱动的真实执行步骤
   v2: warning 状态、优化耗时显示、修复编号、默认折叠
   ============================================================ */

// ── 类型定义 ──────────────────────────────────────────────────

export interface TraceEventItem {
  step_id: string
  step_name: string
  step_number: number
  status: 'pending' | 'running' | 'success' | 'warning' | 'failed' | 'skipped'
  duration_ms: number
  summary: string
  details?: Record<string, unknown>
  error?: string
}

export interface ExecutionTracePanelProps {
  traceEvents: TraceEventItem[]
  isLoading: boolean
}

// ── 耗时格式化 ──────────────────────────────────────────────────

function formatDuration(ms: number | null | undefined): string {
  if (ms == null || ms === 0) return '<1ms'
  if (ms < 1) return '<1ms'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

// ── Details 渲染 ────────────────────────────────────────────────

const MAX_DETAIL_ITEMS = 5

function renderDetailValue(value: unknown, depth: number = 0): React.ReactNode {
  if (value === null || value === undefined) return <span className="text-slate-400 italic">—</span>
  if (typeof value === 'boolean') return <span className="text-slate-500">{value ? 'true' : 'false'}</span>
  if (typeof value === 'number') return <span className="text-slate-700 font-mono">{value.toLocaleString()}</span>
  if (typeof value === 'string') {
    if (value.length > 120) return <span className="text-slate-600">{value.slice(0, 120)}…</span>
    return <span className="text-slate-600">{value}</span>
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-slate-400 italic">[]</span>
    const shown = value.slice(0, MAX_DETAIL_ITEMS)
    const hidden = value.length - MAX_DETAIL_ITEMS
    return (
      <ul className="list-disc pl-4 space-y-0.5">
        {shown.map((item, i) => (
          <li key={i} className="text-slate-600 text-[10px]">{renderDetailValue(item, depth + 1)}</li>
        ))}
        {hidden > 0 && (
          <li className="text-slate-400 text-[10px] italic">… 还有 {hidden} 项</li>
        )}
      </ul>
    )
  }
  if (typeof value === 'object') return <span className="text-slate-500">{JSON.stringify(value).slice(0, 120)}</span>
  return <span className="text-slate-600">{String(value)}</span>
}

// ── 状态配置 ──────────────────────────────────────────────────

interface StatusConfig {
  label: string
  color: string
  bgClass: string
  textClass: string
  badgeClass: string
  dotClass: string
}

const STATUS_CONFIGS: Record<string, StatusConfig> = {
  pending: {
    label: '待处理',
    color: '#64748b',
    bgClass: 'bg-slate-50',
    textClass: 'text-slate-500',
    badgeClass: 'bg-slate-100 text-slate-500 border-slate-200',
    dotClass: 'bg-slate-400',
  },
  running: {
    label: '执行中',
    color: '#3b82f6',
    bgClass: 'bg-blue-50',
    textClass: 'text-blue-600',
    badgeClass: 'bg-blue-100 text-blue-600 border-blue-200',
    dotClass: 'bg-blue-500',
  },
  success: {
    label: '成功',
    color: '#10b981',
    bgClass: 'bg-emerald-50',
    textClass: 'text-emerald-600',
    badgeClass: 'bg-emerald-100 text-emerald-600 border-emerald-200',
    dotClass: 'bg-emerald-500',
  },
  warning: {
    label: '警告',
    color: '#f59e0b',
    bgClass: 'bg-amber-50',
    textClass: 'text-amber-600',
    badgeClass: 'bg-amber-100 text-amber-600 border-amber-200',
    dotClass: 'bg-amber-500',
  },
  failed: {
    label: '失败',
    color: '#ef4444',
    bgClass: 'bg-red-50',
    textClass: 'text-red-600',
    badgeClass: 'bg-red-100 text-red-600 border-red-200',
    dotClass: 'bg-red-500',
  },
  skipped: {
    label: '跳过',
    color: '#64748b',
    bgClass: 'bg-slate-50',
    textClass: 'text-slate-400',
    badgeClass: 'bg-slate-100 text-slate-400 border-slate-200',
    dotClass: 'bg-slate-300',
  },
}

// ── 子组件：单个 trace 步骤 ─────────────────────────────────

function TraceStepItem({
  item,
  displayNumber,
  isLast,
}: {
  item: TraceEventItem
  displayNumber: number
  isLast: boolean
}) {
  const [detailsOpen, setDetailsOpen] = useState(false)
  const config = STATUS_CONFIGS[item.status] || STATUS_CONFIGS.pending
  const hasDetails = item.details && Object.keys(item.details).length > 0
  const isRunning = item.status === 'running'
  const duration = formatDuration(item.duration_ms)

  return (
    <div className="flex items-start gap-3 transition-all duration-300">
      {/* 左侧：竖线 + 节点 */}
      <div className="flex flex-col items-center shrink-0" style={{ width: 24 }}>
        {displayNumber > 1 && (
          <div
            className={`w-0.5 transition-all duration-500 ${
              item.status === 'success' ? 'bg-emerald-200'
              : item.status === 'warning' ? 'bg-amber-200'
              : item.status === 'failed' ? 'bg-red-200'
              : 'bg-slate-200'
            }`}
            style={{ height: 14 }}
          />
        )}

        {/* 节点圆 */}
        <div
          className={`relative flex items-center justify-center w-5 h-5 rounded-full border-2 transition-all duration-300 ${
            isRunning ? 'animate-pulse' : ''
          }`}
          style={{
            borderColor: config.color,
            backgroundColor: ['success', 'warning', 'failed'].includes(item.status) ? config.color : 'white',
          }}
        >
          {item.status === 'success' || item.status === 'warning' ? (
            <span className="text-white text-[10px] font-bold">{item.status === 'warning' ? '!' : '✓'}</span>
          ) : item.status === 'failed' ? (
            <span className="text-[#ef4444] text-[10px] font-bold">✕</span>
          ) : (
            <div className={`w-2 h-2 rounded-full ${config.dotClass}`} />
          )}
        </div>

        {!isLast && (
          <div
            className={`w-0.5 flex-1 min-h-[12px] transition-all duration-500 ${
              item.status === 'success' ? 'bg-emerald-200'
              : item.status === 'warning' ? 'bg-amber-200'
              : 'bg-slate-200'
            }`}
          />
        )}
      </div>

      {/* 右侧：步骤内容 */}
      <div className="flex-1 min-w-0 pb-4">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-sm font-semibold text-slate-800">
            {displayNumber}. {item.step_name}
          </span>
          <span
            className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full border ${config.badgeClass}`}
          >
            {config.label}
          </span>
          <span className="text-[11px] font-mono text-slate-400 tabular-nums ml-auto">
            {duration}
          </span>
        </div>

        {/* 摘要 */}
        <p className="text-[12px] text-slate-600 leading-relaxed mb-1">
          {item.summary || '处理中...'}
        </p>

        {/* 错误信息 */}
        {item.error && (
          <p className="text-[11px] text-red-500 mt-1 font-mono">
            {item.error}
          </p>
        )}

        {/* 可折叠详情 */}
        {hasDetails && (
          <div className="mt-1">
            <button
              type="button"
              onClick={() => setDetailsOpen(!detailsOpen)}
              className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-600 transition-colors"
            >
              {detailsOpen ? (
                <ChevronDown className="w-3 h-3" />
              ) : (
                <ChevronRight className="w-3 h-3" />
              )}
              详情
            </button>
            {detailsOpen && (
              <div className="mt-1 p-2.5 bg-slate-50 border border-slate-200 rounded text-[10px] text-slate-600 font-mono max-h-48 overflow-y-auto">
                <table className="w-full border-collapse">
                  <tbody>
                    {Object.entries(item.details ?? {}).map(([key, value]) => (
                      <tr key={key} className="border-b border-slate-100 last:border-b-0">
                        <td className="py-1 pr-3 text-slate-400 align-top whitespace-nowrap">{key}</td>
                        <td className="py-1 text-slate-700 align-top break-all">{renderDetailValue(value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── 主组件 ────────────────────────────────────────────────────

export default function ExecutionTracePanel({
  traceEvents,
  isLoading,
}: ExecutionTracePanelProps) {
  const [collapsed, setCollapsed] = useState(true)

  if (traceEvents.length === 0 && isLoading) {
    return (
      <div className="bg-white border border-slate-200 rounded-xl p-4">
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="w-4 h-4 animate-spin text-blue-500" />
          正在获取执行链路...
        </div>
      </div>
    )
  }

  if (traceEvents.length === 0) return null

  const completedCount = traceEvents.filter(
    (e) => e.status === 'success' || e.status === 'warning' || e.status === 'failed' || e.status === 'skipped'
  ).length

  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      {/* 头部 — 可折叠 */}
      <button
        type="button"
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-50 transition-colors text-left"
      >
        <div className="flex items-center gap-2">
          {collapsed ? (
            <ChevronRight className="w-4 h-4 text-slate-400" />
          ) : (
            <ChevronDown className="w-4 h-4 text-slate-400" />
          )}
          <span className="text-sm font-semibold text-slate-800">问答执行链路</span>
          {isLoading && (
            <span className="text-[11px] text-slate-400 font-mono animate-pulse">
              执行中...
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {isLoading && (
            <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-500" />
          )}
          <span className="text-xs text-slate-500 font-mono">
            <span className="text-emerald-600 font-semibold">{completedCount}</span>
            /{traceEvents.length}
          </span>
        </div>
      </button>

      {/* 步骤列表 — 折叠时隐藏 */}
      {!collapsed && (
        <div className="border-t border-slate-100">
          <div className="px-4 py-3">
            {traceEvents.map((item, index) => (
              <TraceStepItem
                key={item.step_id}
                item={item}
                displayNumber={index + 1}
                isLast={index === traceEvents.length - 1}
              />
            ))}
          </div>

          {/* 尾部统计 */}
          <div className="flex items-center justify-between px-4 py-2.5 border-t border-slate-100 bg-slate-50/50 text-[11px] text-slate-500 font-mono">
            <span className="tabular-nums">
              ⏱ {traceEvents.length} 个步骤
            </span>
            <span className="tabular-nums">
              {completedCount}/{traceEvents.length} 完成
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
