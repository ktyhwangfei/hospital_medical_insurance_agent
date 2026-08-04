'use client'

/**
 * MemoryPanel —— 左栏会话记忆面板（BusinessMemory + MemoryManager 可视化）
 *
 * 设计依据：docs/steering/医保Agent-政策问答前端改造设计-V1.0.md §三/§4.2
 * - 按记忆类型分组展示记忆卡
 * - 来源标注：✓ 来自记忆（本轮命中）/ ✨ 本轮新查 / 📌 跨话题保留（STICKY）
 * - 记忆随对话增长；主体切换后 TOPIC 记忆消失（hook 层已过滤），STICKY 政策保留
 */

import { useMemo } from 'react'
import {
  CreditCard,
  ScrollText,
  Scale,
  Pill,
  User,
  Stethoscope,
  MessageSquare,
  Brain,
} from 'lucide-react'
import type { ContextNeedSnapshot, MemoryCard } from '@/lib/policy-qa-session'

// ── Props ────────────────────────────────────────────────────

interface MemoryPanelProps {
  memories: MemoryCard[]
  /** 本轮上下文规划（加载来源指示） */
  lastContextNeed?: ContextNeedSnapshot | null
}

// ── 类型配置 ─────────────────────────────────────────────────

const TYPE_CONFIG: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
  settlement: { label: '结算', icon: <CreditCard className="h-3.5 w-3.5" />, color: 'text-emerald-600 bg-emerald-50' },
  policy: { label: '政策', icon: <ScrollText className="h-3.5 w-3.5" />, color: 'text-blue-600 bg-blue-50' },
  rule: { label: '规则', icon: <Scale className="h-3.5 w-3.5" />, color: 'text-violet-600 bg-violet-50' },
  drug: { label: '药品', icon: <Pill className="h-3.5 w-3.5" />, color: 'text-pink-600 bg-pink-50' },
  patient: { label: '患者', icon: <User className="h-3.5 w-3.5" />, color: 'text-slate-600 bg-slate-100' },
  visit: { label: '就诊', icon: <Stethoscope className="h-3.5 w-3.5" />, color: 'text-cyan-600 bg-cyan-50' },
  conversation: { label: '对话', icon: <MessageSquare className="h-3.5 w-3.5" />, color: 'text-amber-600 bg-amber-50' },
}

function typeConfig(type: string) {
  return (
    TYPE_CONFIG[type] ?? {
      label: type,
      icon: <Brain className="h-3.5 w-3.5" />,
      color: 'text-slate-600 bg-slate-100',
    }
  )
}

/** 按重要度降序分组展示 */
function groupByType(memories: MemoryCard[]): Array<{ type: string; items: MemoryCard[] }> {
  const groups = new Map<string, MemoryCard[]>()
  for (const m of [...memories].sort((a, b) => b.importance - a.importance)) {
    const list = groups.get(m.type) ?? []
    list.push(m)
    groups.set(m.type, list)
  }
  return Array.from(groups.entries()).map(([type, items]) => ({ type, items }))
}

// ── Component ────────────────────────────────────────────────

export default function MemoryPanel({ memories, lastContextNeed }: MemoryPanelProps) {
  const groups = useMemo(() => groupByType(memories), [memories])
  const hitCount = memories.filter((m) => m.hitThisTurn).length

  return (
    <aside
      data-testid="memory-panel"
      className="flex flex-col gap-3 rounded-2xl border border-slate-200/70 bg-white/70 p-4 shadow-[0_12px_40px_rgba(15,23,42,0.06)] backdrop-blur"
    >
      {/* 面板头部 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-slate-500" />
          <span className="text-sm font-semibold text-slate-800">会话记忆</span>
        </div>
        <span className="font-mono text-[11px] text-slate-400">{memories.length} 条</span>
      </div>

      {/* 本轮加载来源指示 */}
      {lastContextNeed && (
        <div className="rounded-lg border border-slate-100 bg-slate-50/80 px-3 py-2 text-[11px] text-slate-500">
          {lastContextNeed.memoryIds.length > 0 ? (
            <>
              本轮复用记忆 <span className="font-mono text-emerald-600">{hitCount} 条</span>
              {lastContextNeed.objectTypes.length > 0 && (
                <span className="ml-1">· 需要 {lastContextNeed.objectTypes.join(' / ')}</span>
              )}
            </>
          ) : (
            <>本轮需检索：{lastContextNeed.objectTypes.join(' / ') || '—'}</>
          )}
        </div>
      )}

      {/* 空态 */}
      {memories.length === 0 && (
        <div className="py-8 text-center text-xs leading-relaxed text-slate-400">
          暂无会话记忆
          <br />
          对话后将在此沉淀结算 / 政策 / 规则记忆
        </div>
      )}

      {/* 记忆卡列表（按类型分组） */}
      <div className="space-y-3">
        {groups.map((group) => {
          const cfg = typeConfig(group.type)
          return (
            <div key={group.type} data-testid="memory-group">
              <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold text-slate-500">
                <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 ${cfg.color}`}>
                  {cfg.icon}
                  {cfg.label}
                </span>
                <span className="font-mono font-normal text-slate-300">
                  {group.items.length}
                </span>
              </div>
              <div className="space-y-1.5">
                {group.items.map((m) => (
                  <MemoryCardView key={m.memoryId} card={m} />
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </aside>
  )
}

// ── 单条记忆卡 ───────────────────────────────────────────────

function MemoryCardView({ card }: { card: MemoryCard }) {
  return (
    <div
      data-testid="memory-card"
      data-memory-id={card.memoryId}
      data-type={card.type}
      className={`rounded-xl border px-3 py-2 text-xs transition-shadow ${
        card.hitThisTurn
          ? 'border-emerald-300/80 bg-emerald-50/60 shadow-[0_0_0_1px_rgba(5,150,105,0.15)]'
          : card.isNewThisTurn
            ? 'border-blue-200/80 bg-blue-50/50'
            : 'border-slate-200/70 bg-white/80'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] font-medium text-slate-700">
          {card.refId ?? card.memoryId.slice(0, 8)}
        </span>
        {/* 来源标注 */}
        <div className="flex items-center gap-1">
          {card.hitThisTurn && (
            <span className="rounded bg-emerald-100 px-1 py-0.5 text-[10px] font-medium text-emerald-700">
              ✓ 来自记忆
            </span>
          )}
          {card.isNewThisTurn && !card.hitThisTurn && (
            <span className="rounded bg-blue-100 px-1 py-0.5 text-[10px] font-medium text-blue-700">
              ✨ 本轮新查
            </span>
          )}
          {card.expirePolicy === 'sticky' && (
            <span className="rounded bg-slate-100 px-1 py-0.5 text-[10px] font-medium text-slate-500">
              📌 跨话题保留
            </span>
          )}
        </div>
      </div>
      {card.snapshot && Object.keys(card.snapshot).length > 0 ? (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {Object.entries(card.snapshot).map(([key, value]) => (
            <span
              key={key}
              className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[10px] text-slate-500"
            >
              {key}: {String(value)}
            </span>
          ))}
        </div>
      ) : card.snapshotKeys.length > 0 ? (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {card.snapshotKeys.map((key) => (
            <span
              key={key}
              className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[10px] text-slate-400"
            >
              {key}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}
