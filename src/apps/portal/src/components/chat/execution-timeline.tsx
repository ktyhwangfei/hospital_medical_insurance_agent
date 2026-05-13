'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Loader2,
  CheckCircle2,
  AlertCircle,
  Clock,
  ChevronDown,
  ChevronRight,
  Terminal,
} from 'lucide-react'

/* ============================================================
   ExecutionStepTimeline — 实时执行步骤时间线
   
   展示 AI 处理管线的实时执行步骤，包含：
   - 垂直时间线 + 连接节点
   - 颜色编码的状态指示（pending/running/completed/error）
   - 工具调用步骤的可折叠详情面板
   - 渐进式线条连接动画
   - 深色主题匹配现有聊天界面风格
   ============================================================ */

// ── 类型定义 ──────────────────────────────────────────────────

export interface ExecutionStep {
  /** 步骤标识名（如 "intent_recall", "tool_execute"） */
  step: string
  /** 步骤描述消息 */
  message: string
  /** 步骤状态 */
  status: 'pending' | 'running' | 'completed' | 'error'
  /** 时间戳（可选） */
  timestamp?: string
  /** 工具调用名称 — 存在此字段时步骤显示为工具调用类型 */
  tool_name?: string
  /** 工具调用参数 */
  params?: Record<string, unknown>
  /** 工具调用结果 */
  result?: Record<string, unknown>
  /** 工具执行耗时（毫秒） */
  duration_ms?: number
}

export interface ExecutionTimelineProps {
  /** 执行步骤列表 */
  steps: ExecutionStep[]
  /** 附加 CSS 类名 */
  className?: string
}

// ── 状态样式配置 ──────────────────────────────────────────────

interface StatusStyle {
  nodeBorder: string
  nodeBg: string
  nodeShadow: string
  text: string
  badge: string
  badgeLabel: string
  connectorTop: string
  connectorBottom: string
  cardBorder: string
  cardBg: string
}

const STATUS_STYLE: Record<ExecutionStep['status'], StatusStyle> = {
  pending: {
    nodeBorder: 'border-slate-600/30',
    nodeBg: 'bg-slate-800/60',
    nodeShadow: '',
    text: 'text-slate-400',
    badge: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
    badgeLabel: '待处理',
    connectorTop: 'bg-slate-700/30',
    connectorBottom: 'bg-slate-700/30',
    cardBorder: 'border-white/[0.04]',
    cardBg: 'bg-white/[0.01]',
  },
  running: {
    nodeBorder: 'border-blue-500/50',
    nodeBg: 'bg-blue-500/15',
    nodeShadow: 'shadow-[0_0_12px_rgba(59,130,246,0.25)]',
    text: 'text-blue-300',
    badge: 'bg-blue-500/15 text-blue-300 border-blue-500/25',
    badgeLabel: '处理中',
    connectorTop: 'bg-gradient-to-b from-emerald-500/40 to-blue-500/40',
    connectorBottom: 'bg-blue-500/40',
    cardBorder: 'border-blue-500/20',
    cardBg: 'bg-blue-950/20',
  },
  completed: {
    nodeBorder: 'border-emerald-500/50',
    nodeBg: 'bg-emerald-500/15',
    nodeShadow: 'shadow-[0_0_8px_rgba(16,185,129,0.2)]',
    text: 'text-emerald-300',
    badge: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25',
    badgeLabel: '已完成',
    connectorTop: 'bg-emerald-500/40',
    connectorBottom: 'bg-emerald-500/40',
    cardBorder: 'border-emerald-500/20',
    cardBg: 'bg-emerald-950/20',
  },
  error: {
    nodeBorder: 'border-red-500/50',
    nodeBg: 'bg-red-500/15',
    nodeShadow: 'shadow-[0_0_8px_rgba(239,68,68,0.2)]',
    text: 'text-red-300',
    badge: 'bg-red-500/15 text-red-300 border-red-500/25',
    badgeLabel: '出错',
    connectorTop: 'bg-red-500/40',
    connectorBottom: 'bg-slate-700/30',
    cardBorder: 'border-red-500/20',
    cardBg: 'bg-red-950/20',
  },
}

// ── 内联动画样式 ──────────────────────────────────────────────

const ANIMATION_STYLES = `
@keyframes exec-slide-in {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes exec-connector-grow {
  from { height: 0; }
}
@keyframes exec-pulse-border {
  0%, 100% { box-shadow: 0 0 8px rgba(59,130,246,0.15); }
  50%      { box-shadow: 0 0 16px rgba(59,130,246,0.35); }
}
`

// ── 子组件：状态图标 ─────────────────────────────────────────

function StatusIcon({ status }: { status: ExecutionStep['status'] }) {
  switch (status) {
    case 'pending':
      return <Clock className="w-3.5 h-3.5 text-slate-400" />
    case 'running':
      return <Loader2 className="w-3.5 h-3.5 text-blue-400 animate-spin" />
    case 'completed':
      return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
    case 'error':
      return <AlertCircle className="w-3.5 h-3.5 text-red-400" />
  }
}

// ── 子组件：单步时间线节点 ────────────────────────────────────

function TimelineStepNode({
  status,
  index,
  isLast,
}: {
  status: ExecutionStep['status']
  index: number
  isLast: boolean
}) {
  const style = STATUS_STYLE[status]

  return (
    <div className="flex flex-col items-center shrink-0" style={{ width: 32 }}>
      {/* 上方连接线（非首项） */}
      {index > 0 && (
        <div
          className={cn(
            'w-0.5 transition-all duration-700 ease-out',
            style.connectorTop,
          )}
          style={{ height: 14, animation: index > 0 ? 'exec-connector-grow 0.5s ease-out' : undefined }}
        />
      )}

      {/* 节点圆 */}
      <div
        className={cn(
          'relative flex items-center justify-center w-8 h-8 rounded-full border-2 transition-all duration-300',
          style.nodeBorder,
          style.nodeBg,
          style.nodeShadow,
          status === 'running' && 'animate-pulse',
        )}
        style={
          status === 'running'
            ? { animation: 'exec-pulse-border 2s ease-in-out infinite' }
            : undefined
        }
      >
        <StatusIcon status={status} />
      </div>

      {/* 下方连接线（非末项，flex-1 填充剩余间距） */}
      {!isLast && (
        <div
          className={cn(
            'w-0.5 transition-all duration-700 ease-out min-h-[12px] flex-1',
            style.connectorBottom,
          )}
          style={{ animation: 'exec-connector-grow 0.6s ease-out' }}
        />
      )}
    </div>
  )
}

// ── 子组件：工具调用详情（可折叠） ────────────────────────────

function ToolCallDetails({
  tool_name,
  params,
  result,
  duration_ms,
}: {
  tool_name: string
  params?: Record<string, unknown>
  result?: Record<string, unknown>
  duration_ms?: number
}) {
  const [expanded, setExpanded] = useState(false)
  const hasParams = params && Object.keys(params).length > 0
  const hasResult = result && Object.keys(result).length > 0
  const hasDetails = hasParams || hasResult

  if (!hasDetails) {
    return (
      <div className="flex items-center gap-1.5 border-t border-white/[0.04] px-3.5 py-1.5">
        <Terminal className="w-3 h-3 text-slate-500" />
        <span className="text-[10px] font-mono text-slate-500">{tool_name}</span>
        {duration_ms !== undefined && (
          <span className="text-[10px] font-mono text-emerald-400/40 ml-auto tabular-nums">
            {duration_ms}ms
          </span>
        )}
      </div>
    )
  }

  return (
    <>
      {/* 折叠头 */}
      <button
        onClick={() => setExpanded(!expanded)}
        className={cn(
          'w-full flex items-center gap-1.5 border-t border-white/[0.04] px-3.5 py-1.5',
          'text-left text-[10px] font-medium transition-colors',
          'text-slate-500 hover:text-slate-300 hover:bg-white/[0.02]',
        )}
      >
        <Terminal className="w-3 h-3 shrink-0" />
        <span className="font-mono">{tool_name}</span>
        {duration_ms !== undefined && (
          <span className="text-emerald-400/40 ml-auto tabular-nums">
            {duration_ms}ms
          </span>
        )}
        {expanded ? (
          <ChevronDown className="w-3 h-3 shrink-0 ml-1" />
        ) : (
          <ChevronRight className="w-3 h-3 shrink-0 ml-1" />
        )}
      </button>

      {/* 折叠内容 */}
      {expanded && (
        <div className="border-t border-white/[0.04] bg-slate-950/50">
          <CardContent className="px-3.5 py-2.5 space-y-2.5">
            {hasParams && (
              <div>
                <div className="text-[10px] font-medium text-slate-500 mb-1">
                  参数
                </div>
                <pre className="text-[10px] font-mono text-slate-400 bg-slate-950/60 rounded-lg p-2 overflow-x-auto whitespace-pre-wrap leading-relaxed">
                  {JSON.stringify(params, null, 2)}
                </pre>
              </div>
            )}
            {hasResult && (
              <div>
                <div className="text-[10px] font-medium text-slate-500 mb-1">
                  结果
                </div>
                <pre className="text-[10px] font-mono text-slate-400 bg-slate-950/60 rounded-lg p-2 overflow-x-auto whitespace-pre-wrap leading-relaxed">
                  {JSON.stringify(result, null, 2)}
                </pre>
              </div>
            )}
          </CardContent>
        </div>
      )}
    </>
  )
}

// ── 子组件：时间线步骤项 ──────────────────────────────────────

function TimelineStepItem({
  step,
  index,
  isLast,
}: {
  step: ExecutionStep
  index: number
  isLast: boolean
}) {
  const style = STATUS_STYLE[step.status]
  const isToolCall = Boolean(step.tool_name)

  return (
    <li
      className="relative flex items-stretch"
      style={{
        animation: `exec-slide-in 0.35s ease-out ${index * 0.08}s both`,
      }}
    >
      {/* 左侧：连接线 + 节点 */}
      <TimelineStepNode status={step.status} index={index} isLast={isLast} />

      {/* 右侧：步骤卡片 */}
      <div className={cn('flex-1 pb-5 pl-3 pt-0.5', isLast && 'pb-0')}>
        <div
          className={cn(
            'rounded-xl border transition-all duration-300 overflow-hidden',
            style.cardBorder,
            style.cardBg,
            step.status === 'running' && 'border-blue-400/30',
          )}
        >
          {/* 步骤头信息 */}
          <div className="px-3.5 py-2.5">
            <div className="flex items-center gap-2 mb-1">
              {/* 步骤编号 */}
              <span className="text-[10px] font-mono font-semibold text-white/15 tabular-nums min-w-[20px] select-none">
                {String(index + 1).padStart(2, '0')}
              </span>

              {/* 步骤名称 */}
              <span className={cn('text-xs font-semibold', style.text)}>
                {step.step}
              </span>

              {/* 状态标签 */}
              <Badge
                variant="outline"
                className={cn(
                  'ml-auto px-1.5 py-0 text-[10px] font-medium leading-normal border rounded-full',
                  style.badge,
                )}
              >
                {style.badgeLabel}
              </Badge>
            </div>

            {/* 描述消息 */}
            <p className="text-[11px] text-white/60 leading-relaxed pl-[26px]">
              {step.message}
            </p>

            {/* 时间戳 + 耗时 */}
            {(step.timestamp || (step.duration_ms && step.status === 'completed')) && (
              <div className="flex items-center gap-3 mt-1.5 pl-[26px]">
                {step.timestamp && (
                  <span className="text-[10px] font-mono text-white/15 tabular-nums select-none">
                    {step.timestamp}
                  </span>
                )}
                {step.duration_ms !== undefined && step.status === 'completed' && (
                  <span className="text-[10px] font-mono text-emerald-400/35 tabular-nums">
                    {step.duration_ms}ms
                  </span>
                )}
              </div>
            )}
          </div>

          {/* 工具调用详情（可折叠） */}
          {isToolCall && (
            <Card className="border-0 rounded-none bg-transparent shadow-none">
              <ToolCallDetails
                tool_name={step.tool_name!}
                params={step.params}
                result={step.result}
                duration_ms={step.duration_ms}
              />
            </Card>
          )}
        </div>
      </div>
    </li>
  )
}

// ── 主组件 ─────────────────────────────────────────────────────

/**
 * ExecutionTimeline — 实时执行步骤时间线组件
 *
 * 以垂直时间线形式展示 AI 管线的每一步执行状态，
 * 支持工具调用参数/结果的折叠展示与渐进式连接动画。
 *
 * @example
 * ```tsx
 * <ExecutionTimeline
 *   steps={[
 *     { step: '意图识别', message: '正在分析用户输入...', status: 'completed' },
 *     { step: '工具调用', message: '查询医保目录...', status: 'running', tool_name: 'query_insurance' },
 *   ]}
 * />
 * ```
 */
export default function ExecutionTimeline({
  steps,
  className,
}: ExecutionTimelineProps) {
  // 空状态
  if (steps.length === 0) {
    return (
      <div
        className={cn(
          'flex items-center gap-2 rounded-xl border border-white/[0.06] bg-white/[0.02] px-4 py-3',
          className,
        )}
      >
        <Clock className="w-4 h-4 text-slate-500" />
        <span className="text-xs text-slate-500">等待执行步骤…</span>
      </div>
    )
  }

  return (
    <div className={cn('execution-timeline', className)}>
      {/* 注入动画关键帧 */}
      <style>{ANIMATION_STYLES}</style>

      {/* 时间线 —— 有序列表，语义化步骤序列 */}
      <ol className="relative space-y-0 list-none m-0 p-0">
        {steps.map((step, index) => (
          <TimelineStepItem
            key={`${step.step}-${index}`}
            step={step}
            index={index}
            isLast={index === steps.length - 1}
          />
        ))}
      </ol>
    </div>
  )
}
