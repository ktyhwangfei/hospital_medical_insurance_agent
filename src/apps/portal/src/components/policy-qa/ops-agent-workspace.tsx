'use client'

import { useEffect } from 'react'

import PolicyConversation from '@/components/policy-qa/policy-conversation'
import { usePolicyQAStream } from '@/lib/use-policy-qa-stream'

/**
 * V4.0 运营问数智能体工作区（U2 骨架）。
 *
 * U3 将收窄为：自然语言问数 + 表格/图表富块（设计 §4.3）。
 */
export default function OpsAgentWorkspace({
  onStreamingChange,
}: {
  onStreamingChange?: (streaming: boolean) => void
}) {
  const stream = usePolicyQAStream({ mode: 'data_query', storageScope: 'ops' })

  useEffect(() => {
    onStreamingChange?.(stream.isStreaming)
  }, [stream.isStreaming, onStreamingChange])

  return <PolicyConversation stream={stream} />
}
