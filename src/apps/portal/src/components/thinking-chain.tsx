'use client'

import { useState, useEffect, useRef } from 'react'
import { cn } from '@/lib/utils'


/* ============================================================
   ThinkingChain — AI 思维链 · 实时推理过程

   匹配 v3 原型设计：
   - 只显示已接收的步骤，未到达的步骤不显示
   - 步骤逐个出现，带动画过渡
   - 垂直时间线 + 连接竖线
   - 语义色区分步骤类型（intent→cyan, adapter→blue, knowledge→amber, rule→green, mcp→purple）
   - 步骤状态：pending(灰点+emoji), running(脉冲+emoji), done(实心+✓), error(红叉)
   ============================================================ */

// ── 类型定义 ──────────────────────────────────────────────────

export interface ThinkingStep {
  step: string
  status: 'pending' | 'running' | 'done' | 'error' | 'streaming'
  /** INTERNAL ONLY - 后端 detail 字段，禁止直接渲染 */
  detail?: Record<string, unknown>
  /** 用户可展示的结构化数据 */
  publicDetail?: Record<string, unknown>
  /** ★ 用户可展示的纯文本摘要（优先渲染） */
  publicMessage?: string
  chunk?: string
  error?: string
  startTime?: number
  endTime?: number
}

export interface ThinkingChainProps {
  steps: ThinkingStep[]
  isLoading: boolean
}

// ── 步骤配置 ──────────────────────────────────────────────────

interface StepConfig {
  icon: string
  name: string
  type: string
  /** 语义色 hex */
  color: string
  /** Tailwind 类：边框色 */
  borderClass: string
  /** Tailwind 类：背景色 */
  bgClass: string
  /** Tailwind 类：文字色 */
  textClass: string
  /** Tailwind 类：Badge 色 */
  badgeClass: string
}

const STEP_CONFIGS: Record<string, StepConfig> = {
  // ── 后端 routes.py 固定步骤 ──
  intent_detection: {
    icon: '🎯',
    name: '意图识别',
    type: 'INTENT',
    color: '#06b6d4',
    borderClass: 'border-cyan-500',
    bgClass: 'bg-cyan-500/10',
    textClass: 'text-cyan-400',
    badgeClass: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/25',
  },
  risk_control: {
    icon: '🛡️',
    name: '风险控制',
    type: 'RULE',
    color: '#10b981',
    borderClass: 'border-emerald-500',
    bgClass: 'bg-emerald-500/10',
    textClass: 'text-emerald-400',
    badgeClass: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25',
  },
  authorization: {
    icon: '🔐',
    name: '权限校验',
    type: 'RULE',
    color: '#10b981',
    borderClass: 'border-emerald-500',
    bgClass: 'bg-emerald-500/10',
    textClass: 'text-emerald-400',
    badgeClass: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25',
  },
  scenario_processing: {
    icon: '⚙️',
    name: '场景处理',
    type: 'ADAPTER',
    color: '#3b82f6',
    borderClass: 'border-blue-500',
    bgClass: 'bg-blue-500/10',
    textClass: 'text-blue-400',
    badgeClass: 'bg-blue-500/15 text-blue-400 border-blue-500/25',
  },
  response_rendering: {
    icon: '💬',
    name: '生成结果',
    type: 'MCP',
    color: '#a855f7',
    borderClass: 'border-purple-500',
    bgClass: 'bg-purple-500/10',
    textClass: 'text-purple-400',
    badgeClass: 'bg-purple-500/15 text-purple-400 border-purple-500/25',
  },
  // ── LangGraph 节点（结算异常场景）──
  validate_claim: {
    icon: '🔍',
    name: '校验结算',
    type: 'ADAPTER',
    color: '#3b82f6',
    borderClass: 'border-blue-500',
    bgClass: 'bg-blue-500/10',
    textClass: 'text-blue-400',
    badgeClass: 'bg-blue-500/15 text-blue-400 border-blue-500/25',
  },
  check_high_risk: {
    icon: '⚠️',
    name: '风险检测',
    type: 'RULE',
    color: '#eab308',
    borderClass: 'border-amber-500',
    bgClass: 'bg-amber-500/10',
    textClass: 'text-amber-400',
    badgeClass: 'bg-amber-500/15 text-amber-400 border-amber-500/25',
  },
  query_error_knowledge: {
    icon: '📚',
    name: '错误码检索',
    type: 'KNOWLEDGE',
    color: '#eab308',
    borderClass: 'border-amber-500',
    bgClass: 'bg-amber-500/10',
    textClass: 'text-amber-400',
    badgeClass: 'bg-amber-500/15 text-amber-400 border-amber-500/25',
  },
  build_recommendation: {
    icon: '📋',
    name: '生成建议',
    type: 'MCP',
    color: '#a855f7',
    borderClass: 'border-purple-500',
    bgClass: 'bg-purple-500/10',
    textClass: 'text-purple-400',
    badgeClass: 'bg-purple-500/15 text-purple-400 border-purple-500/25',
  },
  // ── LangGraph 节点（出院质控场景）──
  get_patient_summary: {
    icon: '📋',
    name: '患者摘要',
    type: 'ADAPTER',
    color: '#3b82f6',
    borderClass: 'border-blue-500',
    bgClass: 'bg-blue-500/10',
    textClass: 'text-blue-400',
    badgeClass: 'bg-blue-500/15 text-blue-400 border-blue-500/25',
  },
  run_qc_rules: {
    icon: '🔬',
    name: '质控规则',
    type: 'RULE',
    color: '#10b981',
    borderClass: 'border-emerald-500',
    bgClass: 'bg-emerald-500/10',
    textClass: 'text-emerald-400',
    badgeClass: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25',
  },
  check_qc_issues: {
    icon: '⚠️',
    name: '风险筛查',
    type: 'RULE',
    color: '#eab308',
    borderClass: 'border-amber-500',
    bgClass: 'bg-amber-500/10',
    textClass: 'text-amber-400',
    badgeClass: 'bg-amber-500/15 text-amber-400 border-amber-500/25',
  },
  build_qc_report: {
    icon: '📄',
    name: '质控报告',
    type: 'MCP',
    color: '#a855f7',
    borderClass: 'border-purple-500',
    bgClass: 'bg-purple-500/10',
    textClass: 'text-purple-400',
    badgeClass: 'bg-purple-500/15 text-purple-400 border-purple-500/25',
  },
  // ── Policy QA Skill 步骤（新架构，替代旧 sql_query/search/decomposition/explain）──
  query_sql_data: {
    icon: '🔌',
    name: '数据查询',
    type: 'MCP',
    color: '#a855f7',
    borderClass: 'border-purple-500',
    bgClass: 'bg-purple-500/10',
    textClass: 'text-purple-400',
    badgeClass: 'bg-purple-500/15 text-purple-400 border-purple-500/25',
  },
  search_policy_rules: {
    icon: '📚',
    name: '政策检索',
    type: 'KNOWLEDGE',
    color: '#eab308',
    borderClass: 'border-amber-500',
    bgClass: 'bg-amber-500/10',
    textClass: 'text-amber-400',
    badgeClass: 'bg-amber-500/15 text-amber-400 border-amber-500/25',
  },
  calculate_explanation: {
    icon: '🧮',
    name: '费用计算',
    type: 'SKILL',
    color: '#f97316',
    borderClass: 'border-orange-500',
    bgClass: 'bg-orange-500/10',
    textClass: 'text-orange-400',
    badgeClass: 'bg-orange-500/15 text-orange-400 border-orange-500/25',
  },
  generate_explanation: {
    icon: '💬',
    name: '生成解释',
    type: 'MCP',
    color: '#a855f7',
    borderClass: 'border-purple-500',
    bgClass: 'bg-purple-500/10',
    textClass: 'text-purple-400',
    badgeClass: 'bg-purple-500/15 text-purple-400 border-purple-500/25',
  },
  // ── 旧版步骤名（向后兼容）──
  intent: {
    icon: '🎯',
    name: '意图识别',
    type: 'INTENT',
    color: '#06b6d4',
    borderClass: 'border-cyan-500',
    bgClass: 'bg-cyan-500/10',
    textClass: 'text-cyan-400',
    badgeClass: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/25',
  },
  sql_query: {
    icon: '🔌',
    name: '数据查询',
    type: 'MCP',
    color: '#a855f7',
    borderClass: 'border-purple-500',
    bgClass: 'bg-purple-500/10',
    textClass: 'text-purple-400',
    badgeClass: 'bg-purple-500/15 text-purple-400 border-purple-500/25',
  },
  rewrite: {
    icon: '📝',
    name: '问题重写',
    type: 'KNOWLEDGE',
    color: '#eab308',
    borderClass: 'border-amber-500',
    bgClass: 'bg-amber-500/10',
    textClass: 'text-amber-400',
    badgeClass: 'bg-amber-500/15 text-amber-400 border-amber-500/25',
  },
  search: {
    icon: '📚',
    name: '政策检索',
    type: 'KNOWLEDGE',
    color: '#eab308',
    borderClass: 'border-amber-500',
    bgClass: 'bg-amber-500/10',
    textClass: 'text-amber-400',
    badgeClass: 'bg-amber-500/15 text-amber-400 border-amber-500/25',
  },
  decomposition: {
    icon: '🧮',
    name: '费用分解',
    type: 'SKILL',
    color: '#f97316',
    borderClass: 'border-orange-500',
    bgClass: 'bg-orange-500/10',
    textClass: 'text-orange-400',
    badgeClass: 'bg-orange-500/15 text-orange-400 border-orange-500/25',
  },
  explain: {
    icon: '💬',
    name: '生成解释',
    type: 'MCP',
    color: '#a855f7',
    borderClass: 'border-purple-500',
    bgClass: 'bg-purple-500/10',
    textClass: 'text-purple-400',
    badgeClass: 'bg-purple-500/15 text-purple-400 border-purple-500/25',
  },
}

const DEFAULT_CONFIG: StepConfig = {
  icon: '❓',
  name: '未知步骤',
  type: 'UNKNOWN',
  color: '#64748b',
  borderClass: 'border-slate-500',
  bgClass: 'bg-slate-500/10',
  textClass: 'text-slate-400',
  badgeClass: 'bg-slate-500/15 text-slate-400 border-slate-500/25',
}

// ── 工具函数 ──────────────────────────────────────────────────

/** 格式化耗时（秒）— running 步骤使用传入的 now 实现实时跳动 */
function formatDuration(startTime?: number, endTime?: number, now?: number): string {
  if (!startTime) return '0.0'
  const end = endTime || now || Date.now()
  return ((end - startTime) / 1000).toFixed(1)
}

/** 生成步骤详情文本（仅使用 publicMessage/publicDetail 确保不泄露内部数据） */
function getDetailText(step: ThinkingStep): string {
  // ★ 优先使用 publicMessage（后端提供的纯文本步骤摘要）
  if (step.publicMessage && step.publicMessage.trim()) {
    return step.publicMessage
  }
  // ★ 回退: publicDetail.summary（结构化公共数据）
  if (step.publicDetail && step.publicDetail.summary) {
    return String(step.publicDetail.summary)
  }
  // 不再暴露 detail 字段中的任何内部数据
  return ''
}

// ── 子组件：状态文字（原型风格 — 纯文字无额外图标）──────────

/** 状态文字 */
function statusText(status: ThinkingStep['status']): string {
  switch (status) {
    case 'pending':
      return '○ 待处理'
    case 'running':
    case 'streaming':
      return '⟳ 执行中'
    case 'done':
      return '✓ 完成'
    case 'error':
      return '✗ 失败'
    default:
      return '○ 待处理'
  }
}

// ── 子组件：单个步骤 ─────────────────────────────────────────

function ThinkingStepItem({
  step,
  index,
  isLast,
  isVisible,
  now,
}: {
  step: ThinkingStep
  index: number
  isLast: boolean
  isVisible: boolean
  now?: number
}) {
  const config = STEP_CONFIGS[step.step] || { ...DEFAULT_CONFIG, name: step.step }
  const duration = formatDuration(step.startTime, step.endTime, now)
  const detailText = getDetailText(step)
  const isActive = step.status === 'running' || step.status === 'streaming'
  const isDone = step.status === 'done'
  const isError = step.status === 'error'
  const isPending = step.status === 'pending'

  const statusColorClass =
    step.status === 'done'
      ? 'text-emerald-400'
      : isActive
        ? 'text-cyan-400'
        : step.status === 'error'
          ? 'text-red-400'
          : 'text-slate-500'

  return (
    <div
      className={cn(
        'flex items-start gap-3 transition-all duration-400',
        isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2'
      )}
      style={{
        transitionTimingFunction: 'cubic-bezier(0.4, 0, 0.2, 1)',
        transitionDelay: `${index * 120}ms`,
      }}
    >
      {/* 左侧：竖线 + 节点 */}
      <div className="flex flex-col items-center shrink-0" style={{ width: 24 }}>
        {/* 上方连接线（非首项） */}
        {index > 0 && (
          <div
            className={cn(
              'w-0.5 transition-all duration-600',
              isDone || isActive
                ? 'bg-emerald-500/40'
                : 'bg-white/[0.06]',
            )}
            style={{ height: 14 }}
          />
        )}

        {/* 节点圆 */}
        <div
          className={cn(
            'relative flex items-center justify-center w-6 h-6 rounded-full transition-all duration-300',
            isActive && 'animate-pulse',
          )}
          style={{
            border: `2px solid ${isActive || isDone ? config.color : isError ? '#ef4444' : isPending ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.1)'}`,
            background: isActive
              ? `${config.color}15`
              : isDone
                ? config.color
                : 'rgba(255,255,255,0.03)',
            boxShadow: isActive
              ? `0 0 16px ${config.color}30`
              : isDone
                ? `0 0 12px ${config.color}30`
                : 'none',
            animation: isActive ? 'dot-pulse 1s ease-in-out infinite' : undefined,
          }}
        >
          {isDone ? (
            <span className="text-white text-xs font-bold">✓</span>
          ) : (
            <span className="text-xs select-none">{config.icon}</span>
          )}
        </div>

        {/* 下方连接线（非末项） */}
        {!isLast && (
          <div
            className={cn(
              'w-0.5 flex-1 min-h-[12px] transition-all duration-600',
              isDone ? 'bg-emerald-500/40' : 'bg-white/[0.06]',
            )}
          />
        )}
      </div>

      {/* 右侧：步骤内容 */}
      <div className="flex-1 min-w-0 pt-0.5 pb-4">
        {/* 步骤头部 */}
        <div className="flex items-center gap-2 mb-1">
          <span className="text-sm select-none">{config.icon}</span>
          <span className="text-[13px] font-semibold text-slate-100">
            {config.name}
          </span>
          <span
            className={cn(
              'text-[10px] font-semibold px-1.5 py-0.5 rounded-full tracking-wider',
              config.badgeClass,
            )}
          >
            {config.type}
          </span>
          <span className="text-[11px] font-mono text-slate-500 tabular-nums ml-auto">
            {duration}s
          </span>
        </div>

        {/* 步骤详情 — MCP/SKILL 类型使用专属色调 */}
        <p
          className={cn(
            'text-[12px] leading-relaxed mb-1 font-mono',
            config.type === 'MCP'
              ? 'text-purple-300/90'
              : config.type === 'SKILL'
                ? 'text-orange-300/90'
                : 'text-slate-400',
          )}
        >
          {config.type === 'MCP' && detailText ? (
            <>
              <span className="inline-block bg-purple-500/15 text-purple-400 px-1.5 py-px rounded text-[10px] font-semibold mr-1.5 align-middle">
                MCP
              </span>
              {detailText.replace(/^MCP\s*/i, '')}
            </>
          ) : config.type === 'SKILL' && detailText ? (
            <>
              <span className="inline-block bg-orange-500/15 text-orange-400 px-1.5 py-px rounded text-[10px] font-semibold mr-1.5 align-middle">
                SKILL
              </span>
              {detailText.replace(/^SKILL\s*/i, '')}
            </>
          ) : (
            detailText || '处理中...'
          )}
        </p>

        {/* 步骤状态（原型风格 — 纯文字） */}
        <div className={cn('text-[11px]', statusColorClass)}>
          <span>{statusText(step.status)}</span>
          {step.error && (
            <span className="text-red-400 ml-2 truncate">— {step.error}</span>
          )}
        </div>
      </div>
    </div>
  )
}

// ── 主组件 ─────────────────────────────────────────────────────

/**
 * ThinkingChain — AI 思维链 · 实时推理过程
 *
 * 以垂直时间线形式展示执行步骤，
 * 只显示已接收的步骤，未到达的步骤不显示。
 * 步骤逐个出现，带动画过渡。
 * 仅通过 publicMessage / publicDetail 展示用户安全内容，
 * 禁止渲染 detail 内部字段。
 */
export default function ThinkingChain({ steps, isLoading }: ThinkingChainProps) {
  const [visibleStepCount, setVisibleStepCount] = useState(0)
  const [now, setNow] = useState<number>(Date.now())
  const prevStepsRef = useRef<string>('')

  // 实时计时器：有 running 步骤时每 100ms 刷新，驱动耗时数字跳动
  const hasRunning = steps.some((s) => s.status === 'running' || s.status === 'streaming')

  useEffect(() => {
    if (!hasRunning) return
    const timer = setInterval(() => setNow(Date.now()), 100)
    return () => clearInterval(timer)
  }, [hasRunning])

  // 当新步骤到达时，逐步显示
  useEffect(() => {
    const currentKey = steps.map(s => `${s.step}:${s.status}`).join(',')
    if (currentKey === prevStepsRef.current) return
    prevStepsRef.current = currentKey

    // 逐步暴露步骤，每步间隔 180ms 交错动画（匹配原型 activateStep 节奏）
    const target = steps.length
    const timer = setInterval(() => {
      setVisibleStepCount((prev) => {
        if (prev >= target) {
          clearInterval(timer)
          return prev
        }
        return prev + 1
      })
    }, 180)

    return () => clearInterval(timer)
  }, [steps])

  // 计算总耗时（running 状态时用 now 实时跳动）
  const totalDuration =
    steps.length > 0 && steps[0].startTime
      ? ((steps[steps.length - 1].endTime || now || Date.now()) - steps[0].startTime) / 1000
      : 0

  const completedCount = steps.filter((s) => s.status === 'done').length

  // 如果没有步骤，不渲染
  if (steps.length === 0) return null

  return (
    <div
      className="rounded-2xl border border-indigo-500/20 overflow-hidden"
      style={{
        background: 'rgba(19,27,42,0.6)',
        boxShadow: '0 0 40px rgba(99,102,241,0.05)',
        animation: 'thinking-in 0.5s cubic-bezier(0.4, 0, 0.2, 1) both',
      }}
    >
      {/* 注入动画 */}
      <style>{CHAIN_ANIMATIONS}</style>

      {/* 头部 */}
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-white/[0.04] bg-white/[0.02]">
        <span className="text-lg">🧠</span>
        <span className="text-sm font-semibold text-slate-100 flex-1">
          AI 思维链 · 实时推理过程
        </span>
        <div
          className={cn(
            'flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full',
            isLoading
              ? 'bg-cyan-500/10 text-cyan-400'
              : 'bg-emerald-500/10 text-emerald-400',
          )}
        >
          <span
            className={cn(
              'w-[5px] h-[5px] rounded-full',
              isLoading ? 'bg-cyan-400' : 'bg-emerald-400',
            )}
            style={isLoading ? { animation: 'mini-pulse 1.5s ease-in-out infinite' } : undefined}
          />
          {isLoading ? '实时' : '完成'}
        </div>
      </div>

      {/* 步骤列表 */}
      <div className="px-4 py-3">
        {steps.map((step, index) => (
          <ThinkingStepItem
            key={step.step}
            step={step}
            index={index}
            isLast={index === steps.length - 1}
            isVisible={index < visibleStepCount}
            now={now}
          />
        ))}
      </div>

      {/* 尾部统计 */}
      <div className="flex items-center justify-between px-4 py-3 border-t border-white/[0.04] text-[11px] text-slate-500 font-mono">
        <span className="tabular-nums">⏱ 总耗时: {totalDuration.toFixed(1)}s</span>
        <span className="tabular-nums">
          <span className="text-cyan-400 font-semibold">{completedCount}</span>/{steps.length} 步骤完成
        </span>
      </div>
    </div>
  )
}

// ── 动画样式 ──────────────────────────────────────────────────

const CHAIN_ANIMATIONS = `
@keyframes thinking-in {
  from { opacity: 0; transform: translateY(16px) scale(0.97); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}
@keyframes dot-pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.15); }
}
@keyframes mini-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.8); }
}
`
