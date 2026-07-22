'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import {
  ChevronDown,
  ChevronRight,
  FileText,
  Calculator,
  BookOpen,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'

/* ============================================================
   PolicyAnswerCard — 政策问答结果展示卡片

   包含三个区块：
   1. 待遇分解 — 总费用、医保内、起付线、统筹支付等
   2. 费用分解 — 甲类/乙类/丙类
   3. 溯源证据 — 每个数字的计算过程和数据来源

   设计规范：
   - 左侧彩色边框标识类型（cyan=待遇, amber=费用, green=溯源）
   - JetBrains Mono 显示数字
   - 卡片布局，暗色主题
   ============================================================ */

// ── 类型定义 ──────────────────────────────────────────────────

/** 单个待遇项目 */
export interface TreatmentItem {
  label: string
  value: number
  source?: string
  policy?: string
  calculation?: string
  /** 颜色标记：primary=主要, secondary=次要, muted=弱化 */
  variant?: 'primary' | 'secondary' | 'muted'
}

/** 费用分解项 */
export interface FeeBreakdownItem {
  label: string
  amount: number
  description?: string
}

/** 溯源证据项 */
export interface EvidenceItem {
  item: string
  value: number
  sourceTable?: string
  policyRule?: string
  calculation?: string
}

/** 政策依据卡片项（来自 RAG 检索） */
export interface PolicyCardItem {
  title: string
  clause: string
  evidenceText: string
  matchedReason: string
  ruleType?: string
  score?: number
}

export interface PolicyAnswerCardProps {
  /** 待遇分解列表 */
  treatments?: TreatmentItem[]
  /** 费用分解列表 */
  feeBreakdown?: FeeBreakdownItem[]
  /** 溯源证据列表 */
  evidence?: EvidenceItem[]
  /** 政策依据卡片列表 */
  policyCards?: PolicyCardItem[]
  /** 附加类名 */
  className?: string
}

// ── 工具函数 ──────────────────────────────────────────────────

/** 格式化金额（带千分位） */
function formatMoney(value: number): string {
  return value.toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

// ── 子组件：金额显示 ─────────────────────────────────────────

function MoneyValue({
  value,
  className,
}: {
  value: number
  className?: string
}) {
  return (
    <span className={cn('font-mono tabular-nums font-semibold', className)}>
      {formatMoney(value)}
    </span>
  )
}

// ── 子组件：待遇分解 ─────────────────────────────────────────

function TreatmentSection({ items }: { items: TreatmentItem[] }) {
  if (items.length === 0) return null

  // 分组：主要项目（大项）和次要项目
  const primaryItems = items.filter(
    (i) => i.variant === 'primary' || i.variant === undefined,
  )
  const secondaryItems = items.filter((i) => i.variant === 'secondary')
  const mutedItems = items.filter((i) => i.variant === 'muted')

  return (
    <div
      className="rounded-xl border-l-4 border-cyan-500 bg-white/[0.02] border border-white/[0.06] overflow-hidden"
      style={{ animation: 'fade-in 0.4s ease-out' }}
    >
      {/* 头部 */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-white/[0.04]">
        <FileText className="w-4 h-4 text-cyan-400" />
        <span className="text-sm font-semibold text-slate-100">待遇分解</span>
        <Badge
          variant="outline"
          className="ml-auto bg-cyan-500/10 border-cyan-500/25 text-cyan-400 text-[10px]"
        >
          {items.length} 项
        </Badge>
      </div>

      {/* 主要项目 */}
      <div className="px-4 py-3 space-y-2.5">
        {primaryItems.map((item, idx) => (
          <TreatmentRow key={`p-${idx}`} item={item} highlight />
        ))}
      </div>

      {/* 次要项目（分隔线后） */}
      {secondaryItems.length > 0 && (
        <div className="px-4 py-2.5 border-t border-white/[0.04] space-y-2">
          {secondaryItems.map((item, idx) => (
            <TreatmentRow key={`s-${idx}`} item={item} />
          ))}
        </div>
      )}

      {/* 弱化项目 */}
      {mutedItems.length > 0 && (
        <div className="px-4 py-2 border-t border-white/[0.04] space-y-1.5">
          {mutedItems.map((item, idx) => (
            <TreatmentRow key={`m-${idx}`} item={item} muted />
          ))}
        </div>
      )}
    </div>
  )
}

// ── 子组件：待遇行 ───────────────────────────────────────────

function TreatmentRow({
  item,
  highlight,
  muted,
}: {
  item: TreatmentItem
  highlight?: boolean
  muted?: boolean
}) {
  const [showDetail, setShowDetail] = useState(false)
  const hasDetail = item.calculation || item.policy || item.source

  return (
    <div className="group">
      <div
        className={cn(
          'flex items-center justify-between py-1',
          hasDetail && 'cursor-pointer hover:bg-white/[0.02] -mx-1 px-1 rounded-lg transition-colors',
        )}
        onClick={() => hasDetail && setShowDetail(!showDetail)}
      >
        <div className="flex items-center gap-2">
          {hasDetail && (
            <span className="text-slate-600 transition-colors group-hover:text-slate-400">
              {showDetail ? (
                <ChevronDown className="w-3 h-3" />
              ) : (
                <ChevronRight className="w-3 h-3" />
              )}
            </span>
          )}
          <span
            className={cn(
              'text-[13px]',
              muted ? 'text-slate-500' : highlight ? 'text-slate-200' : 'text-slate-300',
            )}
          >
            {item.label}
          </span>
        </div>
        <MoneyValue
          value={item.value}
          className={cn(
            'text-[13px]',
            muted
              ? 'text-slate-500'
              : highlight
                ? 'text-cyan-300'
                : 'text-slate-200',
          )}
        />
      </div>

      {/* 展开的详情 */}
      {showDetail && hasDetail && (
        <div className="ml-5 mt-1 mb-2 rounded-lg bg-white/[0.02] border border-white/[0.04] p-2.5 space-y-1.5">
          {item.source && (
            <div className="flex items-start gap-2 text-[11px]">
              <span className="text-slate-500 shrink-0">数据源:</span>
              <span className="font-mono text-slate-400 break-all">{item.source}</span>
            </div>
          )}
          {item.policy && (
            <div className="flex items-start gap-2 text-[11px]">
              <span className="text-slate-500 shrink-0">政策依据:</span>
              <span className="text-slate-400">{item.policy}</span>
            </div>
          )}
          {item.calculation && (
            <div className="flex items-start gap-2 text-[11px]">
              <span className="text-slate-500 shrink-0">计算过程:</span>
              <pre className="font-mono text-[10px] text-emerald-400/80 whitespace-pre-wrap leading-relaxed m-0">
                {item.calculation}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── 子组件：费用分解 ─────────────────────────────────────────

function FeeBreakdownSection({ items }: { items: FeeBreakdownItem[] }) {
  if (items.length === 0) return null

  const total = items.reduce((sum, i) => sum + i.amount, 0)

  // 颜色映射
  const colorMap: Record<string, { bar: string; text: string; label: string }> = {
    '甲类': { bar: 'bg-emerald-500', text: 'text-emerald-400', label: '全部医保内' },
    '乙类': { bar: 'bg-amber-500', text: 'text-amber-400', label: '部分医保内' },
    '丙类': { bar: 'bg-red-500', text: 'text-red-400', label: '全部医保外' },
  }

  return (
    <div
      className="rounded-xl border-l-4 border-amber-500 bg-white/[0.02] border border-white/[0.06] overflow-hidden"
      style={{ animation: 'fade-in 0.5s ease-out 0.1s both' }}
    >
      {/* 头部 */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-white/[0.04]">
        <Calculator className="w-4 h-4 text-amber-400" />
        <span className="text-sm font-semibold text-slate-100">费用分解</span>
        <Badge
          variant="outline"
          className="ml-auto bg-amber-500/10 border-amber-500/25 text-amber-400 text-[10px]"
        >
          按收费等级
        </Badge>
      </div>

      {/* 比例条 */}
      <div className="px-4 pt-3">
        <div className="flex h-2 rounded-full overflow-hidden bg-white/[0.04]">
          {items.map((item, idx) => {
            const pct = total > 0 ? (item.amount / total) * 100 : 0
            const colors = colorMap[item.label] || {
              bar: 'bg-slate-500',
              text: 'text-slate-400',
              label: '',
            }
            return (
              <div
                key={idx}
                className={cn('h-full transition-all duration-500', colors.bar)}
                style={{
                  width: `${pct}%`,
                  animation: `bar-grow 0.6s ease-out ${idx * 0.1}s both`,
                }}
              />
            )
          })}
        </div>
      </div>

      {/* 明细列表 */}
      <div className="px-4 py-3 space-y-2">
        {items.map((item, idx) => {
          const colors = colorMap[item.label] || {
            bar: 'bg-slate-500',
            text: 'text-slate-400',
            label: '',
          }
          const pct = total > 0 ? ((item.amount / total) * 100).toFixed(1) : '0.0'
          return (
            <div key={idx} className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className={cn('w-2 h-2 rounded-full', colors.bar)} />
                <span className="text-[13px] text-slate-300">{item.label}</span>
                {colors.label && (
                  <span className="text-[10px] text-slate-500">({colors.label})</span>
                )}
              </div>
              <div className="flex items-center gap-3">
                <span className="text-[10px] font-mono text-slate-500 tabular-nums">
                  {pct}%
                </span>
                <MoneyValue value={item.amount} className={cn('text-[13px]', colors.text)} />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── 子组件：溯源证据 ─────────────────────────────────────────

function EvidenceSection({ items }: { items: EvidenceItem[] }) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null)

  if (items.length === 0) return null

  return (
    <div
      className="rounded-xl border-l-4 border-emerald-500 bg-white/[0.02] border border-white/[0.06] overflow-hidden"
      style={{ animation: 'fade-in 0.5s ease-out 0.2s both' }}
    >
      {/* 头部 */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-white/[0.04]">
        <BookOpen className="w-4 h-4 text-emerald-400" />
        <span className="text-sm font-semibold text-slate-100">溯源证据</span>
        <Badge
          variant="outline"
          className="ml-auto bg-emerald-500/10 border-emerald-500/25 text-emerald-400 text-[10px]"
        >
          {items.length} 条
        </Badge>
      </div>

      {/* 证据列表 */}
      <div className="px-4 py-3 space-y-2">
        {items.map((item, idx) => (
          <div
            key={idx}
            className="rounded-lg border border-white/[0.04] overflow-hidden"
          >
            {/* 证据头 */}
            <button
              type="button"
              className="w-full flex items-center justify-between px-3 py-2 hover:bg-white/[0.02] transition-colors text-left"
              onClick={() =>
                setExpandedIndex(expandedIndex === idx ? null : idx)
              }
            >
              <div className="flex items-center gap-2">
                {expandedIndex === idx ? (
                  <ChevronDown className="w-3 h-3 text-slate-500" />
                ) : (
                  <ChevronRight className="w-3 h-3 text-slate-500" />
                )}
                <span className="text-[13px] text-slate-300">{item.item}</span>
              </div>
              <MoneyValue value={item.value} className="text-[13px] text-emerald-300" />
            </button>

            {/* 证据详情 */}
            {expandedIndex === idx && (
              <div className="px-3 pb-3 space-y-2 border-t border-white/[0.04]">
                {item.sourceTable && (
                  <div className="flex items-start gap-2 text-[11px] mt-2">
                    <TrendingDown className="w-3 h-3 text-slate-500 shrink-0 mt-0.5" />
                    <span className="text-slate-500 shrink-0">数据表:</span>
                    <span className="font-mono text-slate-400 break-all">
                      {item.sourceTable}
                    </span>
                  </div>
                )}
                {item.policyRule && (
                  <div className="flex items-start gap-2 text-[11px]">
                    <TrendingUp className="w-3 h-3 text-slate-500 shrink-0 mt-0.5" />
                    <span className="text-slate-500 shrink-0">政策规则:</span>
                    <span className="text-slate-400">{item.policyRule}</span>
                  </div>
                )}
                {item.calculation && (
                  <div className="mt-1.5 rounded-lg bg-slate-950/60 p-2.5">
                    <div className="text-[10px] text-slate-500 mb-1">计算过程</div>
                    <pre className="font-mono text-[10px] text-emerald-400/80 whitespace-pre-wrap leading-relaxed m-0">
                      {item.calculation}
                    </pre>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── 子组件：政策依据卡片 ─────────────────────────────────────

function PolicyReferencesSection({ cards }: { cards: PolicyCardItem[] }) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null)

  if (cards.length === 0) return null

  return (
    <div
      className="rounded-xl border-l-4 border-purple-500 bg-white/[0.02] border border-white/[0.06] overflow-hidden"
      style={{ animation: 'fade-in 0.5s ease-out 0.3s both' }}
    >
      {/* 头部 */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-white/[0.04]">
        <BookOpen className="w-4 h-4 text-purple-400" />
        <span className="text-sm font-semibold text-slate-100">政策依据</span>
        <Badge
          variant="outline"
          className="ml-auto bg-purple-500/10 border-purple-500/25 text-purple-400 text-[10px]"
        >
          {cards.length} 条
        </Badge>
      </div>

      {/* 卡片列表 */}
      <div className="px-4 py-3 space-y-2">
        {cards.map((card, idx) => (
          <div
            key={idx}
            className="rounded-lg border border-white/[0.04] bg-white/[0.02] overflow-hidden"
          >
            {/* 卡片头部 */}
            <button
              type="button"
              className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-white/[0.03] transition-colors text-left"
              onClick={() =>
                setExpandedIndex(expandedIndex === idx ? null : idx)
              }
            >
              <div className="flex items-center gap-2 min-w-0">
                {expandedIndex === idx ? (
                  <ChevronDown className="w-3 h-3 text-slate-500 shrink-0" />
                ) : (
                  <ChevronRight className="w-3 h-3 text-slate-500 shrink-0" />
                )}
                <span className="text-[13px] text-slate-200 font-medium truncate">
                  {card.title}
                </span>
                {card.ruleType && (
                  <Badge
                    variant="outline"
                    className="bg-purple-500/10 border-purple-500/20 text-purple-400 text-[10px] px-1.5 py-0 shrink-0"
                  >
                    {card.ruleType}
                  </Badge>
                )}
              </div>
              {card.score !== undefined && (
                <span className="text-[10px] font-mono text-slate-500 tabular-nums shrink-0 ml-2">
                  {(card.score * 100).toFixed(0)}%
                </span>
              )}
            </button>

            {/* 卡片详情 */}
            {expandedIndex === idx && (
              <div className="px-3 pb-3 space-y-2 border-t border-white/[0.04]">
                {card.clause && (
                  <div className="flex items-start gap-2 text-[11px] mt-2">
                    <span className="text-slate-500 shrink-0">条文:</span>
                    <span className="text-slate-400 font-mono">{card.clause}</span>
                  </div>
                )}
                {card.evidenceText && (
                  <div className="mt-1.5">
                    <div className="text-[10px] text-slate-500 mb-1">条文原文</div>
                    <pre className="font-mono text-[10px] text-slate-300 bg-slate-950/60 rounded-lg p-2.5 whitespace-pre-wrap leading-relaxed max-h-[200px] overflow-y-auto m-0">
                      {card.evidenceText}
                    </pre>
                  </div>
                )}
                {card.matchedReason && (
                  <div className="flex items-start gap-2 text-[11px]">
                    <span className="text-slate-500 shrink-0">匹配:</span>
                    <span className="text-purple-400/80">{card.matchedReason}</span>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── 主组件 ─────────────────────────────────────────────────────

/**
 * PolicyAnswerCard — 政策问答结果展示卡片
 *
 * 展示费用分解结果，包含待遇分解、费用分解和溯源证据三个区块。
 * 左侧彩色边框标识类型，数字使用等宽字体。
 */
export default function PolicyAnswerCard({
  treatments = [],
  feeBreakdown = [],
  evidence = [],
  policyCards = [],
  className,
}: PolicyAnswerCardProps) {
  const hasContent =
    treatments.length > 0 || feeBreakdown.length > 0 || evidence.length > 0 || policyCards.length > 0

  if (!hasContent) return null

  return (
    <div className={cn('space-y-3', className)}>
      {/* 注入动画 */}
      <style>{CARD_ANIMATIONS}</style>

      {treatments.length > 0 && <TreatmentSection items={treatments} />}
      {feeBreakdown.length > 0 && <FeeBreakdownSection items={feeBreakdown} />}
      {policyCards.length > 0 && <PolicyReferencesSection cards={policyCards} />}
      {evidence.length > 0 && <EvidenceSection items={evidence} />}
    </div>
  )
}

// ── 动画样式 ──────────────────────────────────────────────────

const CARD_ANIMATIONS = `
@keyframes fade-in {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes bar-grow {
  from { width: 0; }
}
`
