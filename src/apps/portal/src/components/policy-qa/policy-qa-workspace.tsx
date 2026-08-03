'use client'

/**
 * PolicyQAWorkspace —— 政策问答三区布局编排
 *
 * 设计依据：docs/steering/医保Agent-政策问答前端改造设计-V1.0.md §三
 * - 顶栏 SessionAnchorBar：业务主体锚点带（含主体切换横幅）
 * - 左栏 MemoryPanel：会话记忆面板（窄屏折叠为单列，记忆收为折叠区）
 * - 主区 ChatStream：持续对话流
 * - 持有 usePolicyQAStream 会话级状态（sessionId 跨轮复用）
 */

import ChatStream from '@/components/policy-qa/chat-stream'
import MemoryPanel from '@/components/policy-qa/memory-panel'
import SessionAnchorBar from '@/components/policy-qa/session-anchor-bar'
import { usePolicyQAStream } from '@/lib/use-policy-qa-stream'

export default function PolicyQAWorkspace() {
  const stream = usePolicyQAStream()
  const { anchor, dismissSubjectChange, memories, lastContextNeed } = stream

  return (
    <div className="flex flex-col gap-4">
      {/* 顶栏 · 业务主体锚点带 */}
      <SessionAnchorBar
        anchor={anchor}
        sessionId={stream.sessionId}
        onDismissSubjectChange={dismissSubjectChange}
      />

      {/* 三区：左栏记忆面板 + 主区对话流（窄屏单列） */}
      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <div className="hidden lg:block">
          <div className="lg:sticky lg:top-6">
            <MemoryPanel memories={memories} lastContextNeed={lastContextNeed} />
          </div>
        </div>
        <ChatStream stream={stream} />
      </div>

      {/* 窄屏：记忆面板收为对话流下方的折叠区 */}
      <details className="rounded-2xl border border-slate-200/70 bg-white/70 backdrop-blur lg:hidden">
        <summary className="cursor-pointer select-none px-4 py-2.5 text-sm font-semibold text-slate-700">
          会话记忆（{memories.length} 条）
        </summary>
        <div className="border-t border-slate-200/60 p-3">
          <MemoryPanel memories={memories} lastContextNeed={lastContextNeed} />
        </div>
      </details>
    </div>
  )
}
