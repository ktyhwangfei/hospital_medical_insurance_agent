'use client'

import { useCallback, useState } from 'react'

import AgentSwitcher, { type AgentId } from '@/components/policy-qa/agent-switcher'
import PolicyAgentWorkspace from '@/components/policy-qa/policy-agent-workspace'
import SettlementAgentWorkspace from '@/components/policy-qa/settlement-agent-workspace'
import OpsAgentWorkspace from '@/components/policy-qa/ops-agent-workspace'

/**
 * V4.0 智能体中心（Agent Hub）：一个页面承载三个智能体，
 * 切换器常驻，切换 = 工作区整体切换（轻 fade 150ms，设计 §三）。
 * 每智能体工作区独立实例化会话 hook（localStorage 按 scope 隔离，设计 §五）。
 */
export default function PolicyQAWorkspace() {
  const [agent, setAgent] = useState<AgentId>('policy')
  const [busy, setBusy] = useState(false)

  // onStreamingChange 由子工作区 effect 回调；useCallback 保持引用稳定，
  // 避免每次渲染都触发子组件的 effect 依赖变化
  const handleStreamingChange = useCallback((streaming: boolean) => {
    setBusy(streaming)
  }, [])

  return (
    <div
      data-testid="policy-qa-reading-column"
      className="mx-auto flex w-full max-w-[840px] flex-col px-6 py-8"
    >
      <AgentSwitcher agent={agent} onChange={setAgent} disabled={busy} />
      <div key={agent} className="animate-workspace-fade" data-testid={`agent-workspace-${agent}`}>
        {agent === 'policy' ? (
          <PolicyAgentWorkspace onStreamingChange={handleStreamingChange} />
        ) : agent === 'settlement' ? (
          <SettlementAgentWorkspace onStreamingChange={handleStreamingChange} />
        ) : (
          <OpsAgentWorkspace onStreamingChange={handleStreamingChange} />
        )}
      </div>
    </div>
  )
}
