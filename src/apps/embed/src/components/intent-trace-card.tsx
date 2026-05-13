'use client'

import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import {
  Target,
  BrainCircuit,
  GitBranch,
  ShieldCheck,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Clock3,
  Sparkles,
  RotateCcw,
  Zap,
  HelpCircle,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'

interface IntentCandidate {
  intent_id: string
  score: number
  source: string
  matched_keywords: string[]
}

interface IntentTrace {
  intent: string
  confidence: number
  status: string
  top_candidates: IntentCandidate[]
  missing_fields: string[]
  clarification_needed: boolean
  clarification_question: string | null
  original_message: string | null
  rewrite_changes: string[]
  entities: Record<string, unknown>
  citations: string[]
}

interface IntentTraceCardProps {
  intentTrace: IntentTrace
  isStreaming?: boolean
  className?: string
}

type StageStatus = 'pending' | 'running' | 'done' | 'blocked'

const INTENT_LABELS: Record<string, string> = {
  settlement_exception_guidance: '医保结算异常导办',
  pre_discharge_quality_control: '出院前联合质控',
  high_risk_action_confirmation: '高风险动作确认',
  mcp_tool_invocation: 'MCP 工具调用',
  denial_appeal_assistant: '拒付申诉助手',
  policy_rule_explanation: '政策规则解释',
  unknown: '待澄清场景',
}

function intentLabel(intentId: string): string {
  return INTENT_LABELS[intentId] ?? intentId
}

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value * 100)))
}

function statusColor(status: string): string {
  switch (status) {
    case 'routed':
      return 'bg-emerald-400/15 text-emerald-300 border-emerald-400/30'
    case 'needs_clarification':
      return 'bg-amber-400/15 text-amber-300 border-amber-400/30'
    case 'fallback_keyword':
      return 'bg-blue-400/15 text-blue-300 border-blue-400/30'
    default:
      return 'bg-slate-400/15 text-slate-400 border-slate-400/30'
  }
}

function statusDot(status: string): string {
  switch (status) {
    case 'routed':
      return 'bg-emerald-400 shadow-emerald-400/50'
    case 'needs_clarification':
      return 'bg-amber-400 shadow-amber-400/50'
    case 'fallback_keyword':
      return 'bg-blue-400 shadow-blue-400/50'
    default:
      return 'bg-slate-500 shadow-slate-500/30'
  }
}

function sourceLabel(source: string): string {
  if (source === 'keyword') return '关键词'
  if (source === 'semantic') return '语义'
  return source
}

function sourceIcon(source: string) {
  if (source === 'semantic') {
    return <BrainCircuit className="w-3 h-3 text-violet-400" />
  }
  if (source === 'keyword') {
    return <Zap className="w-3 h-3 text-cyan-400" />
  }
  return null
}

function pipelineStages(trace: IntentTrace): Array<{ id: string; label: string; description: string; status: StageStatus }> {
  const { status, top_candidates, clarification_needed } = trace
  const hasResults = top_candidates.length > 0
  const isBlocked = status === 'needs_clarification' || clarification_needed

  return [
    {
      id: 'recall',
      label: '候选召回',
      description: '关键词 / 语义双路召回意图候选',
      status: hasResults ? 'done' : 'running',
    },
    {
      id: 'llm',
      label: 'LLM判别',
      description: '结构化意图判别与置信度计算',
      status: isBlocked ? 'blocked' : hasResults ? 'done' : 'running',
    },
    {
      id: 'verify',
      label: '结果校验',
      description: '检查必须字段、权限与风险策略',
      status: status === 'routed' ? 'done' : 'running',
    },
    {
      id: 'route',
      label: '决策路由',
      description: '将请求路由至对应业务场景',
      status: status === 'routed' ? 'done' : 'blocked',
    },
  ]
}

function stageStyle(status: StageStatus): string {
  switch (status) {
    case 'pending':
      return 'border-slate-200/60 bg-slate-50/50 text-slate-500 dark:border-white/[0.04] dark:bg-white/[0.02] dark:text-slate-500'
    case 'running':
      return 'border-blue-200/80 bg-blue-50/60 text-blue-700 dark:border-blue-400/15 dark:bg-blue-400/5 dark:text-blue-300'
    case 'done':
      return 'border-emerald-200/80 bg-emerald-50/60 text-emerald-700 dark:border-emerald-400/15 dark:bg-emerald-400/5 dark:text-emerald-300'
    case 'blocked':
      return 'border-amber-200/80 bg-amber-50/60 text-amber-700 dark:border-amber-400/15 dark:bg-amber-400/5 dark:text-amber-300'
  }
}

function stageIcon(status: StageStatus) {
  if (status === 'done') return <CheckCircle2 className="w-3.5 h-3.5" />
  if (status === 'blocked') return <AlertTriangle className="w-3.5 h-3.5" />
  if (status === 'running') return <Loader2 className="w-3.5 h-3.5 animate-spin" />
  return <Clock3 className="w-3.5 h-3.5" />
}

export default function IntentTraceCard({ intentTrace, isStreaming = false, className = '' }: IntentTraceCardProps) {
  const [expanded, setExpanded] = useState(false)
  const {
    intent,
    confidence,
    status,
    top_candidates,
    missing_fields,
    clarification_needed,
    clarification_question,
    original_message,
    rewrite_changes,
    citations,
  } = intentTrace

  const showRewrite = original_message && rewrite_changes.length > 0
  const showClarification = clarification_needed && clarification_question
  const showCandidates = clarification_needed || status === 'needs_clarification' || top_candidates.length > 1
  const stages = pipelineStages(intentTrace)
  const confidencePct = clampPercent(confidence)

  return (
    <div className={`mb-4 ${className}`}>
      {/* Collapsed summary bar */}
      <button
        onClick={() => setExpanded(!expanded)}
        className={`w-full flex items-center gap-3 rounded-xl border border-white/[0.06] bg-white/[0.03] px-4 py-2.5 text-left transition-all duration-200 hover:bg-white/[0.05] hover:border-white/[0.1] ${
          expanded ? 'rounded-b-none border-b-0' : ''
        }`}
      >
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            {isStreaming ? (
              <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />
            ) : (
              <Target className="w-4 h-4 text-cyan-400" />
            )}
            <span className="text-xs font-semibold text-white/80 truncate">
              {intentLabel(intent)}
            </span>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-[11px] font-mono text-white/50 tabular-nums">
              {confidencePct}%
            </span>
            <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${statusColor(status)}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${statusDot(status)}`} />
              {status === 'routed' && '已路由'}
              {status === 'needs_clarification' && '需澄清'}
              {status === 'fallback_keyword' && '关键词降级'}
              {status === 'unknown' && '未知'}
            </span>
          </div>
        </div>
        <div className="shrink-0 text-white/30">
          {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </div>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="rounded-b-xl border border-t-0 border-white/[0.06] bg-white/[0.02] overflow-hidden">
          <div className="p-4 space-y-4">

            {/* Header section */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Target className="w-4 h-4 text-cyan-400" />
                <span className="text-sm font-semibold text-white/90">意图识别</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-mono text-white/40 tabular-nums">
                  {confidencePct}% 置信度
                </span>
                <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${statusColor(status)}`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${statusDot(status)}`} />
                  {status === 'routed' && '已路由'}
                  {status === 'needs_clarification' && '需澄清'}
                  {status === 'fallback_keyword' && '关键词降级'}
                  {status === 'unknown' && '未知'}
                </span>
              </div>
            </div>

            {/* Query Rewrite */}
            {showRewrite && (
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-4">
                <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-400">
                  <RotateCcw className="w-3.5 h-3.5 text-cyan-400/70" />
                  Query Rewrite
                </div>
                <div className="rounded-lg bg-slate-950/60 p-3 text-[11px] leading-relaxed text-slate-500">
                  <div className="mb-1.5 text-slate-600">原始消息</div>
                  <div className="text-slate-200">{original_message}</div>
                  {rewrite_changes.map((change, i) => (
                    <div key={i} className="mt-2 flex items-start gap-1.5 text-cyan-200/80">
                      <Sparkles className="w-3 h-3 mt-0.5 shrink-0" />
                      <span>{change}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* TopN Candidates */}
            {showCandidates && (
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-4">
                <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-slate-400">
                  <GitBranch className="w-3.5 h-3.5 text-violet-400/70" />
                  TopN 候选意图
                </div>
                <div className="space-y-3">
                  {top_candidates.map((candidate, index) => {
                    const pct = clampPercent(candidate.score)
                    const isTop = index === 0
                    return (
                      <div key={candidate.intent_id} className="space-y-1.5">
                        <div className="flex items-center justify-between gap-2 text-xs">
                          <div className="flex items-center gap-1.5 min-w-0">
                            <span className={`truncate font-medium ${isTop ? 'text-white/90' : 'text-slate-300'}`}>
                              {intentLabel(candidate.intent_id)}
                            </span>
                            {sourceIcon(candidate.source)}
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <Badge variant="outline" className="border-white/[0.06] bg-white/[0.04] px-1.5 py-0 text-[10px] text-slate-400">
                              {sourceLabel(candidate.source)}
                            </Badge>
                            <span className="text-slate-500 font-mono text-[11px]">{pct}%</span>
                          </div>
                        </div>
                        <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                          <div
                            className={`h-full rounded-full transition-all duration-500 ${
                              isTop ? 'bg-gradient-to-r from-cyan-400/80 to-violet-400/80' : 'bg-gradient-to-r from-slate-400/40 to-slate-500/40'
                            }`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        {candidate.matched_keywords.length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            {candidate.matched_keywords.map((kw) => (
                              <span key={kw} className="inline-block rounded-md bg-white/[0.04] px-1.5 py-0.5 text-[10px] text-slate-500">
                                {kw}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Processing Pipeline */}
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-4">
              <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-slate-400">
                <ShieldCheck className="w-3.5 h-3.5 text-amber-400/70" />
                处理链路
              </div>
              <div className="space-y-2.5">
                {stages.map((stage) => (
                  <div key={stage.id} className={`rounded-lg border px-3 py-2.5 ${stageStyle(stage.status)}`}>
                    <div className="flex items-center gap-2 text-xs font-semibold">
                      {stageIcon(stage.status)}
                      {stage.label}
                    </div>
                    <div className="mt-1 text-[11px] leading-relaxed opacity-80">{stage.description}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Missing Fields */}
            {missing_fields.length > 0 && (
              <div className="rounded-xl border border-amber-400/15 bg-amber-400/[0.03] p-4">
                <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-amber-300">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  缺失字段
                </div>
                <ul className="space-y-1">
                  {missing_fields.map((field) => (
                    <li key={field} className="flex items-center gap-2 text-[11px] text-amber-200/80">
                      <span className="w-1 h-1 rounded-full bg-amber-400/60" />
                      {field}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Clarification */}
            {showClarification && (
              <div className="rounded-xl border border-amber-400/15 bg-amber-400/[0.03] p-4">
                <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-amber-300">
                  <HelpCircle className="w-3.5 h-3.5" />
                  需要澄清
                </div>
                <p className="text-[11px] leading-relaxed text-amber-200/80">{clarification_question}</p>
              </div>
            )}

            {/* Citations */}
            {citations.length > 0 && (
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-4">
                <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-400">
                  <Sparkles className="w-3.5 h-3.5 text-blue-400/70" />
                  引用来源
                </div>
                <ul className="space-y-1">
                  {citations.map((citation, i) => (
                    <li key={i} className="text-[11px] text-slate-400 leading-relaxed">
                      <span className="text-slate-600">{i + 1}.</span>{' '}
                      {citation}
                    </li>
                  ))}
                </ul>
              </div>
            )}

          </div>
        </div>
      )}
    </div>
  )
}
