import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import ExecutionContractEditor from '../components/skills/execution-contract-editor'
import type { SkillInputSelectorResponse } from '../lib/types'

// 模拟语义层选择器：含一个可解析 + 一个不可解析指标
const SELECTOR: SkillInputSelectorResponse = {
  tree: [
    {
      domain_code: 'settle',
      name: '结算域',
      objects: [
        {
          object_code: 'Settlement',
          name: '结算',
          definition: '医保结算',
          status: 'published',
          current_version: '1',
          metrics: [
            {
              metric_code: 'Settlement.amount',
              name: '结算金额',
              definition: '总金额',
              source_type: 'structured',
              status: 'published',
              current_version: '1',
              quality_score: 0.9,
              runtime_resolvable: true,
              resolution_type: 'SOURCE_FIELD',
              unavailable_reason: null,
            },
            {
              metric_code: 'Settlement.draft',
              name: '草稿指标',
              definition: '未发布',
              source_type: 'policy_or_external',
              status: 'draft',
              current_version: '1',
              quality_score: 0,
              runtime_resolvable: false,
              resolution_type: null,
              unavailable_reason: 'NOT_PUBLISHED',
            },
          ],
        },
      ],
    },
  ],
}

describe('ExecutionContractEditor', () => {
  afterEach(cleanup)

  it('renders three-column layout with common inputs selected by default', () => {
    render(
      <ExecutionContractEditor
        contract={undefined}
        selector={SELECTOR}
        onChange={() => {}}
      />,
    )
    // 左栏：公共输入 + 新建执行场景
    expect(screen.getByText('公共输入')).toBeInTheDocument()
    expect(screen.getByText('新建执行场景')).toBeInTheDocument()
    // 中栏：运行时上下文选项
    expect(screen.getByText('用户问题')).toBeInTheDocument()
    expect(screen.getByText('结算标识')).toBeInTheDocument()
    // 右栏：搜索 + runtime_resolvable 提示
    expect(screen.getByPlaceholderText('搜索指标')).toBeInTheDocument()
    expect(screen.getByText(/仅 runtime_resolvable 可选/)).toBeInTheDocument()
  })

  it('adds a resolvable metric when clicked from selector', async () => {
    const user = userEvent.setup()
    const changes: unknown[] = []
    render(
      <ExecutionContractEditor
        contract={undefined}
        selector={SELECTOR}
        onChange={(c) => changes.push(c)}
      />,
    )
    // 可解析指标显示为可点击
    const metricBtn = screen.getByText('结算金额')
    await user.click(metricBtn)
    // 应触发 onChange，common.metric_inputs 含该指标
    const last = changes.at(-1) as { common: { metric_inputs: { metric_code: string }[] } }
    expect(last.common.metric_inputs).toEqual([
      expect.objectContaining({ metric_code: 'Settlement.amount' }),
    ])
  })

  it('does not allow selecting unresolvable metric', async () => {
    const user = userEvent.setup()
    const changes: unknown[] = []
    render(
      <ExecutionContractEditor
        contract={undefined}
        selector={SELECTOR}
        onChange={(c) => changes.push(c)}
      />,
    )
    // 不可解析指标默认隐藏；点击「显示不可用」后出现但禁用
    await user.click(screen.getByText('显示不可用'))
    const draftMetric = screen.getByText('草稿指标')
    // 禁用按钮点击不应触发 onChange
    expect(draftMetric.closest('button')).toBeDisabled()
    const before = changes.length
    await user.click(draftMetric)
    expect(changes.length).toBe(before)
  })

  it('creates a new execution profile on button click', async () => {
    const user = userEvent.setup()
    const changes: unknown[] = []
    render(
      <ExecutionContractEditor
        contract={undefined}
        selector={SELECTOR}
        onChange={(c) => changes.push(c)}
      />,
    )
    await user.click(screen.getByText('新建执行场景'))
    const last = changes.at(-1) as { profiles: { profile_id: string; name: string }[] }
    expect(last.profiles).toHaveLength(1)
    expect(last.profiles[0].profile_id).toMatch(/^scene-/)
  })

  it('toggles runtime context inputs', async () => {
    const user = userEvent.setup()
    const changes: unknown[] = []
    render(
      <ExecutionContractEditor
        contract={undefined}
        selector={SELECTOR}
        onChange={(c) => changes.push(c)}
      />,
    )
    await user.click(screen.getByText('结算标识'))
    const last = changes.at(-1) as { common: { context_inputs: { code: string }[] } }
    expect(last.common.context_inputs).toEqual([
      expect.objectContaining({ code: 'settlement_id' }),
    ])
  })

  it('hides metrics already in common inputs when viewing a profile', async () => {
    const user = userEvent.setup()
    render(
      <ExecutionContractEditor
        contract={{
          version: 2,
          common: {
            context_inputs: [],
            metric_inputs: [{ metric_code: 'Settlement.amount', required: true }],
          },
          profiles: [
            {
              profile_id: 'scene-1',
              name: '门诊结算',
              purpose: '',
              routing_hints: [],
              context_inputs: [],
              metric_inputs: [],
            },
          ],
        }}
        selector={SELECTOR}
        onChange={() => {}}
      />,
    )
    // 公共输入视图下能看到该指标
    expect(screen.getByText('结算金额')).toBeInTheDocument()

    // 切换到执行场景
    await user.click(screen.getByText('门诊结算'))

    // 场景视图下：公共输入声明的指标不应出现在右栏选择器中
    expect(screen.queryByText('结算金额')).not.toBeInTheDocument()
  })
})
