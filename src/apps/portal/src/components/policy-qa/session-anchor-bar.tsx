'use client'

/**
 * SessionAnchorBar —— 顶栏业务主体锚点带（BusinessSession 可视化）
 *
 * 设计依据：docs/steering/医保Agent-政策问答前端改造设计-V1.0.md §三/§4.2
 * - 展示当前患者/就诊/结算/话题徽标
 * - context_need.subject_changed=true 时渲染主体切换横幅（可关闭）
 */

import { User, Building2, CreditCard, MessageSquare, X } from 'lucide-react'
import type { SessionAnchor } from '@/lib/policy-qa-session'

// ── Props ────────────────────────────────────────────────────

interface SessionAnchorBarProps {
  anchor: SessionAnchor
  /** 会话 ID（跨轮复用，调试信息） */
  sessionId?: string
  /** 关闭主体切换横幅 */
  onDismissSubjectChange?: () => void
}

// ── 徽标小部件 ───────────────────────────────────────────────

function AnchorBadge({
  icon,
  label,
  accent,
}: {
  icon: React.ReactNode
  label: string
  accent: 'blue' | 'cyan' | 'emerald' | 'amber'
}) {
  const accents = {
    blue: 'bg-blue-50 text-blue-700 ring-blue-200/70',
    cyan: 'bg-cyan-50 text-cyan-700 ring-cyan-200/70',
    emerald: 'bg-emerald-50 text-emerald-700 ring-emerald-200/70',
    amber: 'bg-amber-50 text-amber-700 ring-amber-200/70',
  }
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${accents[accent]}`}
    >
      {icon}
      {label}
    </span>
  )
}

// ── Component ────────────────────────────────────────────────

export default function SessionAnchorBar({
  anchor,
  sessionId,
  onDismissSubjectChange,
}: SessionAnchorBarProps) {
  return (
    <div className="space-y-2">
      <div
        data-testid="session-anchor-bar"
        className="flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200/70 bg-white/70 px-4 py-2.5 shadow-sm backdrop-blur"
      >
        <span className="text-xs font-semibold text-slate-500">当前锚点</span>

        {anchor.patientId && (
          <AnchorBadge
            icon={<User className="h-3.5 w-3.5" />}
            label={`患者 ${anchor.patientId}`}
            accent="blue"
          />
        )}
        {anchor.encounterId && (
          <AnchorBadge
            icon={<Building2 className="h-3.5 w-3.5" />}
            label={`就诊 ${anchor.encounterId}`}
            accent="cyan"
          />
        )}
        {anchor.settlementId ? (
          <AnchorBadge
            icon={<CreditCard className="h-3.5 w-3.5" />}
            label={`结算 ${anchor.settlementId}`}
            accent="emerald"
          />
        ) : (
          <span className="text-xs text-slate-400">未锚定结算单（首轮提问请提供单号）</span>
        )}
        {anchor.topic && (
          <AnchorBadge
            icon={<MessageSquare className="h-3.5 w-3.5" />}
            label={`话题 ${anchor.topic}`}
            accent="amber"
          />
        )}

        {sessionId && (
          <span className="ml-auto font-mono text-[10px] text-slate-300">
            session: {sessionId}
          </span>
        )}
      </div>

      {/* 主体切换横幅（条件渲染，严肃文案） */}
      {anchor.subjectChanged && anchor.subjectChangeMsg && (
        <div
          data-testid="subject-change-banner"
          className="flex items-center justify-between gap-3 rounded-xl border border-amber-200/80 bg-amber-50/90 px-4 py-2.5 text-sm text-amber-800"
        >
          <span>{anchor.subjectChangeMsg}</span>
          {onDismissSubjectChange && (
            <button
              type="button"
              onClick={onDismissSubjectChange}
              className="flex items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-amber-600 hover:bg-amber-100 hover:text-amber-800"
            >
              <X className="h-3.5 w-3.5" />
              知道了
            </button>
          )}
        </div>
      )}
    </div>
  )
}
