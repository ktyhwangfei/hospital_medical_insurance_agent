/**
 * ReasoningChainCollapsible 组件测试
 *
 * 覆盖设计文档 §4.2：
 * - 无步骤时不渲染
 * - 默认折叠，点击展开步骤列表
 * - kind 语义标签（事实/推理）与置信度渲染
 */

import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import ReasoningChainCollapsible from '@/components/policy-qa/reasoning-chain-collapsible'
import type { ReasoningStep } from '@/lib/policy-qa-session'

afterEach(() => cleanup())

function makeStep(partial: Partial<ReasoningStep>): ReasoningStep {
  return {
    stepId: 'step-1',
    claim: '已获取结算单 1671213 的结算数据',
    kind: 'fact',
    dependsOn: [],
    confidence: 0.95,
    citations: [],
    sourceMemoryIds: ['m-settle'],
    ...partial,
  }
}

describe('ReasoningChainCollapsible', () => {
  it('无步骤时不渲染', () => {
    const { container } = render(<ReasoningChainCollapsible steps={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('默认折叠：显示「查看依据」入口，不显示步骤内容', () => {
    render(<ReasoningChainCollapsible steps={[makeStep({})]} />)
    expect(screen.getByTestId('reasoning-chain-toggle')).toBeInTheDocument()
    expect(screen.getByText('查看依据')).toBeInTheDocument()
    expect(screen.queryByTestId('reasoning-steps')).toBeNull()
  })

  it('点击展开后渲染步骤内容与语义标签', () => {
    render(
      <ReasoningChainCollapsible
        steps={[
          makeStep({ stepId: 's1', kind: 'fact', claim: '已获取结算数据', confidence: 0.95 }),
          makeStep({ stepId: 's2', kind: 'inference', claim: '完成待遇分段计算', confidence: 0.9 }),
        ]}
      />,
    )
    fireEvent.click(screen.getByTestId('reasoning-chain-toggle'))
    expect(screen.getByTestId('reasoning-steps')).toBeInTheDocument()
    expect(screen.getAllByTestId('reasoning-step')).toHaveLength(2)
    expect(screen.getByText('事实')).toBeInTheDocument()
    expect(screen.getByText('推理')).toBeInTheDocument()
    expect(screen.getByText('已获取结算数据')).toBeInTheDocument()
    expect(screen.getByText('完成待遇分段计算')).toBeInTheDocument()
    // 置信度 95%
    expect(screen.getByText('95%')).toBeInTheDocument()
  })

  it('defaultOpen=true 时默认展开', () => {
    render(<ReasoningChainCollapsible steps={[makeStep({})]} defaultOpen />)
    expect(screen.getByTestId('reasoning-steps')).toBeInTheDocument()
  })
})
