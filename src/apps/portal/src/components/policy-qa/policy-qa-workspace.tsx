'use client'

/**
 * PolicyQAWorkspace —— 政策问答主区编排
 *
 * - 顶栏 SessionAnchorBar：业务主体锚点带（含主体切换横幅）
 * - 主区 ChatStream：持续对话流
 * - 持有 usePolicyQAStream 会话级状态（sessionId 跨轮复用）
 *
 * 注：会话记忆面板（MemoryPanel）已从默认视图移除——其对一线收费员无操作价值，
 *     仅保留组件文件供后台/调试页使用。
 */

import ChatStream from '@/components/policy-qa/chat-stream'
import SessionAnchorBar from '@/components/policy-qa/session-anchor-bar'
import { usePolicyQAStream } from '@/lib/use-policy-qa-stream'

export default function PolicyQAWorkspace() {
  const stream = usePolicyQAStream()
  const { anchor, dismissSubjectChange } = stream

  return (
    <div className="flex flex-col gap-4">
      {/* 顶栏 · 业务主体锚点带 */}
      <SessionAnchorBar
        anchor={anchor}
        onDismissSubjectChange={dismissSubjectChange}
      />

      {/* 主区 · 对话流 */}
      <ChatStream stream={stream} />
    </div>
  )
}
