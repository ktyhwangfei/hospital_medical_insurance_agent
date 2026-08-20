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
    evidence: ['knowledge:fact_base'],
    dependencies: ['rule_base'],
    formula: { operator: 'COMPLEMENT', reference: { rule_id: 'rule_base' }, factor: null, total: null },
    compiler_version: '1.0',
    rule_version: 2,
    status: 'REVIEW',
  },
  run: {
    run_id: 'run_1',
    document_id: 'doc_1',
    unit_id: 'unit_1',
    extraction_id: 'ext_1',
    raw_input: { source_text: '政策原文' },
    llm_output: { facts: [{ fact_id: 'fact_1' }] },
    compiler_version: '1.0',
    status: 'REVIEW',
    metrics: {},
    error: null,
    started_at: '2026-08-11T00:00:00Z',
    finished_at: '2026-08-11T00:00:01Z',
  },
  raw_input: { source_text: '政策原文' },
  llm_output: { facts: [{ fact_id: 'fact_1' }] },
  steps: [
    { step_id: 'step_1', run_id: 'run_1', sequence_no: 1, stage: 'INPUT_SNAPSHOT', status: 'PASS', input_payload: { source_text: '退休人员个人支付比例为在职人员的60%' }, output_payload: { source_text: '退休人员个人支付比例为在职人员的60%' }, issues: [], error: null, duration_ms: 0, started_at: '2026-08-11T00:00:00Z', finished_at: '2026-08-11T00:00:00Z' },
    { step_id: 'step_2', run_id: 'run_1', sequence_no: 2, stage: 'LLM_EXTRACTION', status: 'PASS', input_payload: { source_text: '退休人员个人支付比例为在职人员的60%' }, output_payload: { facts: [{ fact_id: 'fact_relative', population: 'retiree', expression: { operator: 'MULTIPLY', factor: '0.60' } }] }, issues: [], error: null, duration_ms: 846, started_at: '2026-08-11T00:00:00Z', finished_at: '2026-08-11T00:00:01Z' },
    { step_id: 'step_3', run_id: 'run_1', sequence_no: 3, stage: 'CANONICALIZE', status: 'PASS', input_payload: { facts: [{ fact_id: 'fact_base', value: { ratio: '15%' } }] }, output_payload: { result: [{ fact_id: 'fact_base', value: { ratio: '0.15' } }] }, issues: [], error: null, duration_ms: 2, started_at: '2026-08-11T00:00:00Z', finished_at: '2026-08-11T00:00:01Z' },
    { step_id: 'step_4', run_id: 'run_1', sequence_no: 4, stage: 'COMPOSE', status: 'PASS', input_payload: { facts: [{ fact_id: 'fact_base', value: { ratio: '0.15' } }] }, output_payload: { result: [[{ rule_id: 'rule_base', population: 'employee', result: { ratio: '0.15' } }], []] }, issues: [], error: null, duration_ms: 1, started_at: '2026-08-11T00:00:00Z', finished_at: '2026-08-11T00:00:01Z' },
    { step_id: 'step_5', run_id: 'run_1', sequence_no: 5, stage: 'RESOLVE', status: 'PASS', input_payload: { rules: [{ rule_id: 'rule_base' }], relations: [{ fact_id: 'fact_relative' }] }, output_payload: { result: { fact_relative: { rules: [{ rule_id: 'rule_base' }] } } }, issues: [], error: null, duration_ms: 1, started_at: '2026-08-11T00:00:00Z', finished_at: '2026-08-11T00:00:01Z' },
    { step_id: 'step_6', run_id: 'run_1', sequence_no: 6, stage: 'DERIVE', status: 'PASS', input_payload: { resolutions: { fact_relative: { relation: { population: 'retiree', expression: { operator: 'MULTIPLY', factor: '0.60' } }, rules: [{ rule_id: 'rule_base', population: 'employee', result: { ratio: '0.15' } }] } } }, output_payload: { result: [{ rule_id: 'rule_1', population: 'retiree', result: { ratio: '0.09' }, source_type: 'DERIVED', dependencies: ['rule_base'], formula: { operator: 'MULTIPLY', factor: '0.60' } }] }, issues: [], error: null, duration_ms: 1, started_at: '2026-08-11T00:00:00Z', finished_at: '2026-08-11T00:00:01Z' },
    { step_id: 'step_7', run_id: 'run_1', sequence_no: 7, stage: 'VALIDATE', status: 'REVIEW', input_payload: { rules: [{ rule_id: 'rule_1', conditions: { amount_band: '0-30000' } }] }, output_payload: { result: null }, issues: [{ issue_id: 'issue_1', severity: 'REVIEW', code: 'OVERLAPPING_RANGE', stage: 'VALIDATE', fact_id: null, rule_id: 'rule_1', message: '范围重叠', recommended_action: '人工核验' }], error: null, duration_ms: 1, started_at: '2026-08-11T00:00:00Z', finished_at: '2026-08-11T00:00:01Z' },
  ],
  issues: [{ issue_id: 'issue_1', severity: 'REVIEW', code: 'OVERLAPPING_RANGE', stage: 'VALIDATE', fact_id: null, rule_id: 'rule_1', message: '范围重叠', recommended_action: '人工核验' }],
  publication: null,
  history: [{ run_id: 'run_1', rule_version: 2, status: 'REVIEW', compiler_version: '1.0', started_at: '2026-08-11T00:00:00Z', finished_at: '2026-08-11T00:00:01Z' }],
} satisfies RuleCompilationTrace

beforeEach(() => {
  vi.mocked(getRuleCompilationTrace).mockReset().mockResolvedValue(trace)
})

afterEach(cleanup)

describe('rule trace drawer', () => {
  it('shows three decision stages and keeps technical input out of the primary navigation', async () => {
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

    expect(await screen.findByRole('heading', { name: '规则审核决策' })).toBeInTheDocument()
    await waitFor(() => expect(getRuleCompilationTrace).toHaveBeenCalledWith(
      'rule_1',
      'run_1',
    ))
    const stageTabs = screen.getAllByRole('tab')
    expect(stageTabs).toHaveLength(3)
    expect(screen.getByRole('tab', { name: /模型识别/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /规范化与冲突/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /发布判定/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.queryByRole('tab', { name: /原始输入/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: /关系解析/ })).not.toBeInTheDocument()
    expect(screen.getByText('OVERLAPPING_RANGE')).toBeInTheDocument()
    expect(screen.queryByText('rule: rule_1')).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: /规范化与冲突/ }))
    const normalizedFields = document.querySelectorAll('[data-change="changed"]')
    expect(normalizedFields).toHaveLength(2)
    expect(normalizedFields[0]).toHaveTextContent('15%')
    expect(normalizedFields[1]).toHaveTextContent('0.15')
    expect(document.querySelector('[data-change="derived"]')).toHaveTextContent('0.09')
    expect(screen.getByText('规则依赖')).toBeInTheDocument()

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
    expect(await screen.findByText('模型识别')).toBeInTheDocument()
    expect(getRuleCompilationTrace).toHaveBeenCalledTimes(2)
  })

  it('renders failed candidate trace without a canonical rule', async () => {
    vi.mocked(getRuleCompilationTrace).mockResolvedValue({
      ...trace,
      rule_id: 'rule_failed',
      rule: null,
      run: { ...trace.run, status: 'FAIL', error: { message: 'compiler failed' } },
      publication: null,
      steps: [{
        ...trace.steps[0],
        status: 'FAIL',
        issues: [],
      }],
      issues: [{
        ...trace.issues[0],
        severity: 'FAIL',
        code: 'RATIO_INVALID',
        stage: 'INPUT_SNAPSHOT',
        rule_id: 'rule_failed',
        message: '比例不是有效数值',
      }],
      history: [{ ...trace.history[0], status: 'FAIL', rule_version: null }],
    })

    render(<RuleTraceDrawer open ruleId="rule_failed" onOpenChange={vi.fn()} />)

    expect(await screen.findByText('未生成规范规则')).toBeInTheDocument()
    expect(screen.getAllByText('FAIL')).not.toHaveLength(0)
    expect(screen.getByText('RATIO_INVALID')).toBeInTheDocument()
    expect(screen.getByText('比例不是有效数值')).toBeInTheDocument()
    expect(screen.getByText(/compiler failed/)).toBeInTheDocument()
    expect(screen.getAllByText(/当前不可发布/)).not.toHaveLength(0)
  })

  it('shows only the current candidate instead of the repeated batch extraction', async () => {
    const user = userEvent.setup()
    const batchIssues = [
      { ...trace.issues[0], issue_id: 'current_conflict', stage: 'COMPOSE' as const, fact_id: 'rule_1', rule_id: null, code: 'CURRENT_CONFLICT' },
      { ...trace.issues[0], issue_id: 'other_conflict', stage: 'COMPOSE' as const, fact_id: 'rule_2', rule_id: null, code: 'OTHER_CONFLICT' },
    ]
    vi.mocked(getRuleCompilationTrace).mockResolvedValue({
      ...trace,
      steps: trace.steps.map((step) => {
        if (step.stage === 'LLM_EXTRACTION') return {
          ...step,
          input_payload: { source_text: '在职职工基本医疗保险统筹基金最高支付限额调整为10万元。' },
          output_payload: {
            rules: [
              { rule_id: 'rule_1', cap_amount: 100000, name: '当前规则' },
              { rule_id: 'rule_2', cap_amount: 200000, name: '同批其他规则' },
            ],
          },
        }
        if (step.stage === 'CANONICALIZE') return {
          ...step,
          input_payload: { facts: [{ fact_id: 'rule_1', population: '在职职工', value: { amount: 100000 } }] },
          output_payload: { result: [{ fact_id: 'rule_1', population: '在职职工', value: { amount: 100000 } }] },
        }
        if (step.stage === 'COMPOSE') return { ...step, status: 'REVIEW' as const, issues: batchIssues }
        return step
      }),
      issues: [...trace.issues, ...batchIssues],
    })

    render(<RuleTraceDrawer open ruleId="rule_1" onOpenChange={vi.fn()} />)

    await screen.findByRole('heading', { name: '规则审核决策' })
    await user.click(screen.getByRole('tab', { name: /模型识别/ }))
    expect(screen.getByRole('heading', { name: '单元原文' })).toBeInTheDocument()
    expect(screen.getByText('10万元').closest('mark')).toBeInTheDocument()
    expect(screen.getByText('100000').closest('[data-source-match="true"]')).toBeInTheDocument()
    expect(screen.getByText('封顶金额')).toBeInTheDocument()
    expect(screen.queryByText('rule_id')).not.toBeInTheDocument()
    expect(screen.queryByText('同批其他规则')).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: /规范化与冲突/ }))
    expect(screen.getByText('CURRENT_CONFLICT')).toBeInTheDocument()
    expect(screen.queryByText('OTHER_CONFLICT')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '规范化输入' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /规范化输出/ })).toBeInTheDocument()
    expect(screen.getAllByText('100000')).toHaveLength(2)
  })

  it('separates extracted fields from compiler inference and hides technical fields', async () => {
    const user = userEvent.setup()
    vi.mocked(getRuleCompilationTrace).mockResolvedValue({
      ...trace,
      steps: trace.steps.map((step) => {
        if (step.stage === 'LLM_EXTRACTION') return {
          ...step,
          input_payload: { source_text: '在职职工住院最高支付限额为10万元。' },
          output_payload: {
            rules: [{
              rule_id: 'rule_1',
              cap_amount: 100000,
              med_type: '住院-普通住院',
              psn_type: '在职职工',
              rule_type: '封顶线',
            }],
          },
        }
        if (step.stage === 'CANONICALIZE') return {
          ...step,
          input_payload: {
            facts: [{
              fact_id: 'rule_1',
              value: { amount: 100000 },
              subject: 'cap',
              confidence: 0.58,
              conditions: { med_type: '住院-普通住院', psn_type: '在职职工' },
              unit_id: 'unit_1',
              document_id: 'doc_1',
              extraction_id: 'ext_1',
              evidence: ['evidence_1'],
            }],
          },
          output_payload: {
            result: [{
              fact_id: 'rule_1',
              value: { amount: 100000 },
              subject: 'cap',
              confidence: 0.58,
              conditions: { med_type: '住院-普通住院', psn_type: '在职职工' },
              unit_id: 'unit_1',
              document_id: 'doc_1',
              extraction_id: 'ext_1',
              evidence: ['evidence_1'],
            }],
          },
        }
        return step
      }),
    })

    render(<RuleTraceDrawer open ruleId="rule_1" onOpenChange={vi.fn()} />)
    await screen.findByRole('heading', { name: '规则审核决策' })

    await user.click(screen.getByRole('tab', { name: /模型识别/ }))
    const extracted = screen.getByRole('heading', { name: '原文提取' }).closest('section')!
    const inferred = screen.getByRole('heading', { name: '辅助推断' }).closest('section')!
    expect(extracted).toHaveTextContent('封顶金额')
    expect(extracted).toHaveTextContent('医疗类别')
    expect(extracted).toHaveTextContent('人群标签')
    expect(inferred).toHaveTextContent('规则主题')
    expect(inferred).toHaveTextContent('综合置信度')
    expect(document.body).not.toHaveTextContent('candidate.')

    await user.click(screen.getByRole('tab', { name: /规范化与冲突/ }))
    const normalizedInput = screen.getByRole('heading', { name: '规范化输入' }).closest('section')!
    expect(normalizedInput).toHaveTextContent('规则金额')
    expect(normalizedInput).toHaveTextContent('医疗类别')
    expect(normalizedInput).toHaveTextContent('人群标签')
    expect(normalizedInput).not.toHaveTextContent(/fact_id|unit_id|document_id|extraction_id|confidence|evidence/)
    expect(screen.queryByText(/fact:/)).not.toBeInTheDocument()
  })

  it('locates the candidate through the evidence chain when extraction ids are placeholders', async () => {
    const user = userEvent.setup()
    // 复刻真实批次场景：LLM 输出 id 是占位符，规范化 facts 用 kn_ 事实 id，
    // 规则→事实链接只在 evidence（knowledge:kn_xxx）里；批次里还有其他 facts 的 issue。
    vi.mocked(getRuleCompilationTrace).mockResolvedValue({
      ...trace,
      rule_id: 'rule_63e8',
      rule: {
        ...trace.rule!,
        rule_id: 'rule_63e8',
        source_type: 'DIRECT',
        evidence: ['knowledge:kn_mine', 'ev_1'],
        dependencies: [],
        formula: null,
        conditions: { hosp_lv: '社区' },
      },
      steps: [
        trace.steps[0],
        { ...trace.steps[1], input_payload: { source_text: '在职职工在本市社区卫生服务机构就医，门诊大额医疗互助资金报销比例为90%' }, output_payload: { rules: [{ rule_id: 'rule_001', fact_id: 'fact_001', rule_value: '门诊大额医疗互助资金报销比例为90%', hosp_lv: '社区' }] } },
        { ...trace.steps[2], input_payload: { facts: [
          { fact_id: 'kn_other', subject: 'other_subject_value', value: { ratio: '10%' }, evidence: ['evidence_x'] },
          { fact_id: 'kn_mine', subject: 'large_medical_mutual_aid_payment_ratio', conditions: { hosp_lv: '社区' }, value: { ratio: '0.9' }, confidence: 0.9, evidence: ['evidence_y'] },
        ] }, output_payload: { result: [
          { fact_id: 'kn_mine', subject: 'large_medical_mutual_aid_payment_ratio', conditions: { hosp_lv: '社区' }, value: { ratio: 0.9 }, confidence: 0.9, evidence: ['evidence_y'] },
        ] } },
        { ...trace.steps[3], status: 'REVIEW' as const, input_payload: { facts: [
          { fact_id: 'kn_mine', subject: 'large_medical_mutual_aid_payment_ratio', conditions: { hosp_lv: '社区' }, value: { ratio: 0.9 } },
        ] }, output_payload: { result: [[
          { rule_id: 'rule_63e8', conditions: { hosp_lv: '社区' }, result: { ratio: 0.9 }, evidence: ['knowledge:kn_mine', 'ev_1'] },
          { rule_id: 'rule_other', subject: 'nested_other_marker', result: { ratio: 0.1 }, evidence: ['knowledge:kn_other'] },
        ], []] } },
        { ...trace.steps[4], input_payload: { rules: [
          { rule_id: 'rule_63e8', conditions: { hosp_lv: '社区' }, result: { ratio: 0.9 }, evidence: ['knowledge:kn_mine', 'ev_1'] },
          { rule_id: 'rule_other', result: { ratio: 0.1 }, evidence: ['knowledge:kn_other'] },
        ], relations: [] }, output_payload: { result: {} } },
        { ...trace.steps[5], input_payload: { resolutions: {} }, output_payload: { result: [] } },
        { ...trace.steps[6], input_payload: { rules: [{ rule_id: 'rule_63e8', conditions: { hosp_lv: '社区' } }] }, output_payload: { result: null } },
      ],
      issues: [
        { ...trace.issues[0], issue_id: 'issue_other', severity: 'FAIL', code: 'SUBJECT_MISSING', stage: 'CANONICALIZE' as const, fact_id: 'kn_other', rule_id: null, message: '政策事实缺少可识别的业务主体', recommended_action: '补充结构化 subject' },
      ],
    })

    render(<RuleTraceDrawer open ruleId="rule_63e8" onOpenChange={vi.fn()} />)
    await screen.findByRole('heading', { name: '规则审核决策' })

    await user.click(screen.getByRole('tab', { name: /模型识别/ }))
    const extracted = screen.getByRole('heading', { name: '原文提取' }).closest('section')!
    const inferred = screen.getByRole('heading', { name: '辅助推断' }).closest('section')!
    expect(extracted).toHaveTextContent('医疗机构等级')
    expect(extracted).toHaveTextContent('社区')
    expect(inferred).toHaveTextContent('规则主题')

    await user.click(screen.getByRole('tab', { name: /规范化与冲突/ }))
    expect(screen.queryByText('SUBJECT_MISSING')).not.toBeInTheDocument()
    expect(document.body).not.toHaveTextContent('other_subject_value')
    expect(document.body).not.toHaveTextContent('nested_other_marker')
    const normalizedInput = screen.getByRole('heading', { name: '规范化输入' }).closest('section')!
    expect(normalizedInput).toHaveTextContent('医疗机构等级')
    await user.click(screen.getByRole('button', { name: 'JSON 对照' }))
    expect(document.body).not.toHaveTextContent('nested_other_marker')
  })

  it('hides the previous run evidence as soon as the target changes', async () => {
    const user = userEvent.setup()
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
      .mockResolvedValue(trace)
    const view = render(
      <Harness runId="run_1" />,
    )
    expect(await screen.findByText('OVERLAPPING_RANGE')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '查看完整 JSON' }))
    expect(screen.getByRole('heading', { name: '完整编译轨迹 JSON' })).toBeInTheDocument()
    committedFrames.length = 0

    view.rerender(<Harness runId="run_2" />)

    expect(screen.queryByRole('heading', { name: '完整编译轨迹 JSON' })).not.toBeInTheDocument()
    expect(committedFrames.at(-1)).not.toContain('OVERLAPPING_RANGE')
    expect(screen.queryByText('OVERLAPPING_RANGE')).not.toBeInTheDocument()
    expect(screen.getByText('正在加载编译轨迹…')).toBeInTheDocument()
    resolveSecond?.({
      ...trace,
      run: { ...trace.run, run_id: 'run_2' },
      issues: [],
      steps: [],
    })
    await waitFor(() => expect(screen.queryByText('正在加载编译轨迹…')).not.toBeInTheDocument())

    view.rerender(<Harness runId="run_1" />)
    await waitFor(() => expect(getRuleCompilationTrace).toHaveBeenCalledTimes(3))
    expect(screen.queryByRole('heading', { name: '完整编译轨迹 JSON' })).not.toBeInTheDocument()
  })

  it('keeps legacy import as a single honest stage', async () => {
    vi.mocked(getRuleCompilationTrace).mockResolvedValue({
      ...trace,
      rule_id: 'legacy_rule',
      steps: [{
        ...trace.steps[0],
        step_id: 'legacy_step',
        sequence_no: 1,
        stage: 'LEGACY_IMPORT',
        status: 'REVIEW',
      }],
      issues: [],
    })

    render(<RuleTraceDrawer open ruleId="legacy_rule" onOpenChange={vi.fn()} />)

    expect(await screen.findByRole('tab', { name: /历史导入/ })).toBeInTheDocument()
    expect(screen.getAllByRole('tab')).toHaveLength(1)
    expect(screen.getByText(/中间编译历史缺失/)).toBeInTheDocument()
  })
})
