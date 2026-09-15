'use client'

import { useEffect } from 'react'

import PolicyConversation from '@/components/policy-qa/policy-conversation'
import { usePolicyQAStream } from '@/lib/use-policy-qa-stream'

/**
 * V4.0 政策问答智能体工作区：纯自然语言政策问答（无结算单锚点），
 * 政策来源可追溯是核心价值（设计 §4.1）。
 */
export default function PolicyAgentWorkspace({
  onStreamingChange,
}: {
  onStreamingChange?: (streaming: boolean) => void
}) {
  const stream = usePolicyQAStream({ mode: 'policy_chat', storageScope: 'policy' })

  useEffect(() => {
    onStreamingChange?.(stream.isStreaming)
  }, [stream.isStreaming, onStreamingChange])

  return <PolicyConversation stream={stream} />
}
