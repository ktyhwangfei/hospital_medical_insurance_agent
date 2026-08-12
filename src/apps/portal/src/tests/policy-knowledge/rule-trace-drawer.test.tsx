import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import RuleTraceDrawer from '../../components/policy-knowledge/rule-trace-drawer'
import {
  getRuleCompilationTrace,
  type RuleCompilationTrace,
} from '@/lib/policy-knowledge-api'

vi.mock('@/lib/policy-knowledge-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/policy-knowledge-api')>()),
  getRuleCompilationTrace: vi.fn(),
}))

const trace = {
  rule_id: 'rule_1',
  rule: {
    rule_id: 'rule_1',
    subject: '住院待遇',
    population: null,
    conditions: {},
    result: { ratio: '0.8' },
    source_type: 'DERIVED',
    evidence: ['evidence_1'],
    dependencies: ['rule_base'],
    formula: { operator: 'COMPLEMENT', reference: { rule_id: 'rule_base' }, factor: null, total: null },
    compiler_version: '1.0',
    rule_version: 2,
    status: 'WARN',
  },
  run: {
    run_id: 'run_1',
    document_id: 'doc_1',
    unit_id: 'unit_1',
    extraction_id: 'ext_1',
    raw_input: { source_text: '政策原文' },
    llm_output: { facts: [{ fact_id: 'fact_1' }] },
    compiler_version: '1.0',
    status: 'WARN',
    metrics: {},
    error: null,
    started_at: '2026-08-11T00:00:00Z',
    finished_at: '2026-08-11T00:00:01Z',
  },
  raw_input: { source_text: '政策原文' },
  llm_output: { facts: [{ fact_id: 'fact_1' }] },
  steps: [
    { step_id: 'step_2', run_id: 'run_1', sequence_no: 2, stage: 'VALIDATE', status: 'WARN', input_payload: {}, output_payload: {}, issues: [{ issue_id: 'issue_1', severity: 'WARN', code: 'OVERLAPPING_RANGE', stage: 'VALIDATE', fact_id: null, rule_id: 'rule_1', message: '范围重叠', recommended_action: '人工核验' }], error: null, duration_ms: 1, started_at: '2026-08-11T00:00:00Z', finished_at: '2026-08-11T00:00:01Z' },
    { step_id: 'step_1', run_id: 'run_1', sequence_no: 1, stage: 'CANONICALIZE', status: 'PASS', input_payload: { fact: 1 }, output_payload: { rule: 1 }, issues: [], error: null, duration_ms: 1, started_at: '2026-08-11T00:00:00Z', finished_at: '2026-08-11T00:00:01Z' },
  ],
  issues: [{ issue_id: 'issue_1', severity: 'WARN', code: 'OVERLAPPING_RANGE', stage: 'VALIDATE', fact_id: null, rule_id: 'rule_1', message: '范围重叠', recommended_action: '人工核验' }],
  publication: { release_id: 'release_1', status: 'published', published_at: '2026-08-11T00:00:02Z' },
  history: [{ run_id: 'run_1', rule_version: 2, status: 'WARN', compiler_version: '1.0', started_at: '2026-08-11T00:00:00Z', finished_at: '2026-08-11T00:00:01Z' }],
} satisfies RuleCompilationTrace

beforeEach(() => {
  vi.mocked(getRuleCompilationTrace).mockReset().mockResolvedValue(trace)
})

afterEach(cleanup)

describe('rule trace drawer', () => {
  it('fetches lazily and renders the ordered, expandable audit chain', async () => {
    const user = userEvent.setup()
    const onOpenChange = vi.fn()
    const view = render(
      <RuleTraceDrawer
        open={false}
        ruleId="rule_1"
        runId="run_1"
        onOpenChange={onOpenChange}
      />,
    )

    expect(getRuleCompilationTrace).not.toHaveBeenCalled()
    view.rerender(
      <RuleTraceDrawer open ruleId="rule_1" runId="run_1" onOpenChange={onOpenChange} />,
    )

    expect(await screen.findByRole('heading', { name: '规则编译溯源' })).toBeInTheDocument()
    await waitFor(() => expect(getRuleCompilationTrace).toHaveBeenCalledWith(
      'rule_1',
      'run_1',
    ))
    expect(screen.getByText('原始输入')).toBeInTheDocument()
    expect(screen.getByText('LLM 提取')).toBeInTheDocument()
    const stages = screen.getAllByTestId('trace-stage').map((node) => node.textContent)
    expect(stages[0]).toContain('CANONICALIZE')
    expect(stages[1]).toContain('VALIDATE')
    expect(screen.getByText('OVERLAPPING_RANGE')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '查看完整 JSON' }))
    expect(screen.getByRole('heading', { name: '完整编译轨迹 JSON' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '关闭完整 JSON' }))
    await user.click(screen.getByRole('button', { name: '关闭溯源' }))
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('shows an error and retries the same rule', async () => {
    const user = userEvent.setup()
    vi.mocked(getRuleCompilationTrace)
      .mockRejectedValueOnce(new Error('轨迹加载失败'))
      .mockResolvedValueOnce(trace)

    render(<RuleTraceDrawer open ruleId="rule_1" onOpenChange={vi.fn()} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('轨迹加载失败')
    await user.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('原始输入')).toBeInTheDocument()
    expect(getRuleCompilationTrace).toHaveBeenCalledTimes(2)
  })

  it('renders failed candidate trace without a canonical rule', async () => {
    vi.mocked(getRuleCompilationTrace).mockResolvedValue({
      ...trace,
      rule_id: 'rule_failed',
      rule: null,
      run: { ...trace.run, status: 'FAIL' },
      publication: null,
      steps: [{
        ...trace.steps[0],
        status: 'FAIL',
        issues: [{
          ...trace.issues[0],
          severity: 'FAIL',
          code: 'RATIO_INVALID',
          message: '比例不是有效数值',
        }],
      }],
      issues: [{
        ...trace.issues[0],
        severity: 'FAIL',
        code: 'RATIO_INVALID',
        message: '比例不是有效数值',
      }],
      history: [{ ...trace.history[0], status: 'FAIL', rule_version: null }],
    })

    render(<RuleTraceDrawer open ruleId="rule_failed" onOpenChange={vi.fn()} />)

    expect(await screen.findByText('未生成规范规则')).toBeInTheDocument()
    expect(screen.getByText('FAIL')).toBeInTheDocument()
    expect(screen.getByText('RATIO_INVALID')).toBeInTheDocument()
    expect(screen.getByText('比例不是有效数值')).toBeInTheDocument()
  })

  it('hides the previous run evidence as soon as the target changes', async () => {
    let resolveSecond: ((value: RuleCompilationTrace) => void) | undefined
    const committedFrames: string[] = []
    const Harness = ({ runId }: { runId: string }) => (
      <>
        <RuleTraceDrawer
          open
          ruleId="rule_1"
          runId={runId}
          onOpenChange={vi.fn()}
        />
        <span ref={(node) => {
          if (node) committedFrames.push(document.body.textContent ?? '')
        }} />
      </>
    )
    vi.mocked(getRuleCompilationTrace)
      .mockResolvedValueOnce(trace)
      .mockImplementationOnce(() => new Promise((resolve) => {
        resolveSecond = resolve
      }))
    const view = render(
      <Harness runId="run_1" />,
    )
    expect(await screen.findByText('OVERLAPPING_RANGE')).toBeInTheDocument()
    committedFrames.length = 0

    view.rerender(<Harness runId="run_2" />)

    expect(committedFrames.at(-1)).not.toContain('OVERLAPPING_RANGE')
    expect(screen.queryByText('OVERLAPPING_RANGE')).not.toBeInTheDocument()
    expect(screen.getByText('正在加载编译轨迹…')).toBeInTheDocument()
    resolveSecond?.({
      ...trace,
      run: { ...trace.run, run_id: 'run_2' },
      issues: [],
      steps: [],
    })
  })
})
