import { StrictMode } from 'react'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import KnowledgeReviewRoute from '../../../app/policy-knowledge/knowledge/review/page'
import KnowledgeReviewDetailRoute from '../../../app/policy-knowledge/knowledge/review/[changeSetId]/page'
import {
  approveChangeSet,
  getChangeSet,
  getRuleCompilationTrace,
  getRuleDetail,
  listChangeSets,
  listDecisionTasks,
  PolicyKnowledgeApiError,
  rejectChangeSet,
  resolveDecisionTask,
  returnKnowledgeReview,
  reviewKnowledge,
  type DecisionTask,
  type KnowledgeChangeSet,
  type RuleDetail,
} from '@/lib/policy-knowledge-api'

const push = vi.fn()
const refresh = vi.fn()
const currentApiContext = vi.hoisted(() => ({ userId: 'context-actor' }))

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => '/policy-knowledge/knowledge/review'),
  useRouter: vi.fn(() => ({ push, refresh })),
}))

vi.mock('@/lib/api-context', () => ({
  useApiContext: vi.fn(() => currentApiContext),
}))

vi.mock('@/lib/policy-knowledge-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/policy-knowledge-api')>()),
  approveChangeSet: vi.fn(),
  getChangeSet: vi.fn(),
  getRuleCompilationTrace: vi.fn(),
  getRuleDetail: vi.fn(),
  listChangeSets: vi.fn(),
  listDecisionTasks: vi.fn(),
  listTestCases: vi.fn(),
  listSemanticMetrics: vi.fn().mockResolvedValue([]),
  rejectChangeSet: vi.fn(),
  resolveDecisionTask: vi.fn(),
  returnKnowledgeReview: vi.fn(),
  reviewKnowledge: vi.fn(),
}))

const ruleDetail: RuleDetail = {
  rule: {
    knowledge_id: 'KN_001',
    unit_id: 'UNIT_001',
    extraction_id: 'EXT_001',
    relationship_source: 'persisted',
    business_sentence: '三级医院在职职工住院报销比例为 85%。',
    source_text: '在职职工在三级医院住院，统筹基金支付比例为百分之八十五。',
    fields: [
      { field_code: 'hosp_lv', field_name: '医院等级', raw_value: '三级' },
      { field_code: 'payment_ratio', field_name: '支付比例', raw_value: 0.85 },
    ],
    standardized_fields: [{
      source_field: 'payment_ratio',
      source_value: 0.85,
      status: 'mapped',
      metric_code: 'zcgz.payment_ratio',
      metric_name: '支付比例',
      value_domain: null,
      standard_value: 0.85,
      binding_id: 'BIND_001',
    }],
    confidence: {
      completeness: 0.95,
      accuracy: 0.9,
      source_fidelity: 1,
      model_confidence: 0.82,
      value_domain_compliance: 1,
      overall: 0.88,
      uncertainties: ['例外人群尚需人工核对'],
    },
    citations: [{ evidence: '第十二条', title: '职工基本医疗保险办法' }],
    evidences: [{
      evidence_id: 'EVID_001',
      document_version_id: 'DOC_REV_001',
      unit_id: 'UNIT_001',
      clause_path: '第三章 / 第十二条',
      page_no: 6,
      exact_quote: '在职职工在三级医院住院，统筹基金支付比例为百分之八十五。',
      start_offset: 0,
      end_offset: 31,
      evidence_role: '主结论证据',
    }],
    semantic_bindings: [{
      policy_field: 'payment_ratio',
      semantic_field: 'settlement.payment_ratio',
      concept: '医保支付比例',
      value_domain: null,
      status: 'CONFIRMED',
    }],
  },
  unit: {
    unit_id: 'UNIT_001',
    path: ['第三章', '第十二条'],
    source_text: '在职职工在三级医院住院，统筹基金支付比例为百分之八十五。',
    status: 'reviewed',
  },
  document: {
    doc_id: 'DOC_001',
    doc_title: '职工基本医疗保险办法',
    contract_version: 'v2.3',
  },
  change_set_id: 'CS_REVIEW',
  review_status: 'pending',
}

const pendingChangeSet = makeChangeSet()
const completedChangeSet = makeChangeSet({
  change_set_id: 'CS_DONE',
  doc_title: '门诊慢特病管理办法',
  status: 'APPROVED',
  source_units: [{
    doc_id: 'DOC_002',
    doc_title: '门诊慢特病管理办法',
    unit_id: 'UNIT_003',
    unit_revision_id: 'REV_003',
    path: ['第二章', '第八条'],
  }],
  summary: { additions: 0, modifications: 2, replacements: 1, expirations: 0, unchanged: 3 },
  items: [],
  risk_summary: { LOW: 3 },
})

const pendingTasks: DecisionTask[] = [
  makeDecisionTask(),
  makeDecisionTask({
    task_id: 'DEC_002',
    task_type: 'LOW_CONFIDENCE_MAPPING',
    question: '支付比例的语义字段是否正确？',
    risk_level: 'HIGH',
  }),
  makeDecisionTask({ task_id: 'DEC_OTHER', blocking_scope: 'CS_OTHER' }),
]

const traceForRun = (runId: string) => ({
  rule_id: 'RULE_001',
  rule: { rule_id: 'RULE_001', subject: '住院待遇', population: null, conditions: {}, result: { ratio: '0.85' }, source_type: 'DIRECT' as const, evidence: ['EVID_001'], dependencies: [], formula: null, compiler_version: '1.0', rule_version: 1, status: 'PASS' as const },
  run: { run_id: runId, document_id: 'DOC_001', unit_id: 'UNIT_001', extraction_id: 'EXT_001', raw_input: {}, llm_output: {}, model_name: null, prompt_version: null, schema_version: null, compiler_version: '1.0', status: 'PASS' as const, metrics: {}, error: null, started_at: '2026-08-11T00:00:00Z', finished_at: '2026-08-11T00:00:01Z' },
  raw_input: { source_text: '政策原文' },
  llm_output: { facts: [] },
  steps: [],
  issues: [],
  publication: null,
  history: [],
})

beforeEach(() => {
  currentApiContext.userId = 'context-actor'
  push.mockReset()
  refresh.mockReset()
  vi.mocked(listChangeSets).mockReset().mockResolvedValue([pendingChangeSet, completedChangeSet])
  vi.mocked(listDecisionTasks).mockReset().mockResolvedValue(pendingTasks)
  vi.mocked(getChangeSet).mockReset().mockResolvedValue(pendingChangeSet)
  vi.mocked(getRuleCompilationTrace).mockReset().mockResolvedValue(
    traceForRun('RUN_ITEM_001'),
  )
  vi.mocked(getRuleDetail).mockReset().mockResolvedValue(ruleDetail)
  vi.mocked(resolveDecisionTask).mockReset().mockImplementation(async (taskId, decision) => ({
    ...pendingTasks.find((task) => task.task_id === taskId)!,
    status: 'RESOLVED',
    decision,
  }))
  vi.mocked(approveChangeSet).mockReset().mockResolvedValue({ ...pendingChangeSet, status: 'APPROVED' })
  vi.mocked(returnKnowledgeReview).mockReset().mockResolvedValue({ ...pendingChangeSet, status: 'RETURNED' })
  vi.mocked(rejectChangeSet).mockReset().mockResolvedValue({ ...pendingChangeSet, status: 'REJECTED' })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('knowledge review list', () => {
  it('aggregates review cards and blocking issues without reviving old information architecture', async () => {
    const user = userEvent.setup()
    const { container } = render(<KnowledgeReviewRoute />)

    expect(await screen.findByRole('heading', { name: '知识审核' })).toBeInTheDocument()
    const viewFilters = screen.getByRole('group', { name: '审核视图筛选' })
    expect(within(viewFilters).getAllByRole('button').map((button) => button.textContent)).toEqual([
      '待审核',
      '全部审核',
      '已完成',
      '仅看待处理问题',
    ])
    expect(screen.queryByText('待我审核')).not.toBeInTheDocument()
    expect(screen.getByText('来源已审核单元 2 个')).toBeInTheDocument()
    expect(screen.getByText('新增 2')).toBeInTheDocument()
    expect(screen.getByText('修改 1')).toBeInTheDocument()
    expect(screen.getByText('替代 1')).toBeInTheDocument()
    expect(screen.getByText('待处理问题 2 项')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '进入审核' })).toHaveAttribute(
      'href',
      '/policy-knowledge/knowledge/review/CS_REVIEW',
    )
    expect(container).not.toHaveTextContent('知识变更集')
    expect(container).not.toHaveTextContent('待决策队列')

    expect(screen.queryByRole('tablist')).not.toBeInTheDocument()
    await user.click(within(viewFilters).getByRole('button', { name: '仅看待处理问题' }))
    expect(screen.getByText('职工基本医疗保险办法')).toBeInTheDocument()
    expect(screen.queryByText('门诊慢特病管理办法')).not.toBeInTheDocument()
  })

  it('distinguishes a loading failure from an empty review list', async () => {
    vi.mocked(listChangeSets).mockRejectedValueOnce(new Error('审核存储暂不可用'))
    render(<KnowledgeReviewRoute />)

    expect(await screen.findByRole('alert')).toHaveTextContent('审核存储暂不可用')
    expect(screen.queryByText('暂无审核任务')).not.toBeInTheDocument()
  })
})

describe('knowledge review detail', () => {
  it('keeps structured knowledge, source text, confidence, issues and review actions together', async () => {
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)

    expect(await screen.findByText('结构化知识列表')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '知识审核详情' })).toBeInTheDocument()
    expect(screen.getByText('当前审核身份：context-actor')).toBeInTheDocument()
    expect(screen.getAllByText('第三章 / 第十二条').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/统筹基金支付比例为百分之八十五/).length).toBeGreaterThan(0)
    expect(screen.getByText('置信度 88%')).toBeInTheDocument()
    expect(screen.getByText('例外人群尚需人工核对')).toBeInTheDocument()
    expect(screen.getByText('需人工确认的风险项')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '整批通过审核' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: /绑定指标|创建指标|新增标准值/ })).not.toBeInTheDocument()
  })

  it('offers one lazy trace action for every rule row', async () => {
    const user = userEvent.setup()
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)

    const actions = await screen.findAllByRole('button', { name: '查看溯源' })
    expect(actions).toHaveLength(pendingChangeSet.items.length)
    expect(getRuleCompilationTrace).not.toHaveBeenCalled()

    await user.click(actions[0])

    await waitFor(() => expect(getRuleCompilationTrace).toHaveBeenCalledWith(
      'RULE_001',
      'RUN_ITEM_001',
    ))
    expect(screen.getByRole('heading', { name: '规则编译溯源' })).toBeInTheDocument()
  })

  it('queries each shared rule row by its own compile run', async () => {
    const user = userEvent.setup()
    const first = pendingChangeSet.items[0]
    vi.mocked(getChangeSet).mockResolvedValue({
      ...pendingChangeSet,
      items: [
        { ...first, item_id: 'ITEM_RUN_1', compile_run_id: 'RUN_ITEM_001' },
        { ...first, item_id: 'ITEM_RUN_2', compile_run_id: 'RUN_ITEM_002' },
      ],
    })
    vi.mocked(getRuleCompilationTrace).mockImplementation(async (_ruleId, runId) => ({
      ...traceForRun(runId ?? 'missing'),
    }))
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)

    const actions = await screen.findAllByRole('button', { name: '查看溯源' })
    await user.click(actions[0])
    await waitFor(() => expect(getRuleCompilationTrace).toHaveBeenNthCalledWith(
      1,
      'RULE_001',
      'RUN_ITEM_001',
    ))
    await user.click(screen.getByRole('button', { name: '关闭溯源' }))
    await waitFor(() => expect(
      screen.queryByRole('heading', { name: '规则编译溯源' }),
    ).not.toBeInTheDocument())

    await user.click(actions[1])
    await waitFor(() => expect(getRuleCompilationTrace).toHaveBeenNthCalledWith(
      2,
      'RULE_001',
      'RUN_ITEM_002',
    ))
  })

  it('exposes row-level and batch re-extract entry points for a reviewable change set', async () => {
    const user = userEvent.setup()
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)

    await screen.findByText('结构化知识列表')
    // 行级「重提取」按钮在 PENDING_REVIEW 下可见
    expect(screen.getAllByRole('button', { name: /重提取/ }).length).toBeGreaterThan(0)

    // 选中可审核项 → 工具栏出现「批量重新提取」
    await user.click(screen.getByLabelText('全选可审核项'))
    expect(screen.getByRole('button', { name: /批量重新提取/ })).toBeInTheDocument()
  })

  it('treats the build candidate snapshot as authoritative instead of live rule content', async () => {
    const candidateRule = {
      ...ruleDetail.rule,
      business_sentence: '本次构建候选快照结论：支付比例调整为 90%。',
      source_text: '候选快照政策原文：统筹基金支付比例调整为百分之九十。',
      evidences: [{
        ...ruleDetail.rule.evidences![0],
        exact_quote: '候选证据：统筹基金支付比例调整为百分之九十。',
      }],
      semantic_bindings: [{
        ...ruleDetail.rule.semantic_bindings![0],
        semantic_field: 'candidate.payment_ratio',
      }],
      standardized_fields: [{
        ...ruleDetail.rule.standardized_fields[0],
        metric_code: 'candidate.payment_ratio',
      }],
    }
    vi.mocked(getChangeSet).mockResolvedValue(makeChangeSet({
      items: [{
        ...pendingChangeSet.items[0],
        after: candidateRule,
      }],
    }))
    vi.mocked(getRuleDetail).mockResolvedValue({
      ...ruleDetail,
      rule: {
        ...ruleDetail.rule,
        business_sentence: '实时规则内容，不应覆盖候选快照。',
        source_text: '实时规则原文，不应覆盖候选原文。',
        evidences: [{
          ...ruleDetail.rule.evidences![0],
          exact_quote: '实时规则证据，不应覆盖候选证据。',
        }],
        semantic_bindings: [{
          ...ruleDetail.rule.semantic_bindings![0],
          semantic_field: 'live.payment_ratio',
        }],
        standardized_fields: [{
          ...ruleDetail.rule.standardized_fields[0],
          metric_code: 'live.payment_ratio',
        }],
      },
      review_status: 'approved',
    })
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)

    expect(await screen.findByText('结构化知识列表')).toBeInTheDocument()
    expect(screen.getAllByText(/候选快照政策原文/).length).toBeGreaterThan(0)
    expect(screen.queryByText(/实时规则内容/)).not.toBeInTheDocument()
    expect(screen.queryByText(/实时规则原文/)).not.toBeInTheDocument()
    expect(screen.queryByText(/实时规则证据/)).not.toBeInTheDocument()
    expect(screen.queryByText(/live\.payment_ratio/)).not.toBeInTheDocument()
    expect(getRuleDetail).not.toHaveBeenCalled()
  })

  it('surfaces semantic changes with a dedicated badge in the review table', async () => {
    const beforeRule = {
      ...ruleDetail.rule,
      semantic_bindings: [{
        ...ruleDetail.rule.semantic_bindings![0],
        semantic_field: 'old.payment_ratio',
      }],
      standardized_fields: [{
        ...ruleDetail.rule.standardized_fields[0],
        metric_code: 'old.payment_ratio',
        standard_value: 0.8,
      }],
    }
    const afterRule = {
      ...ruleDetail.rule,
      semantic_bindings: [{
        ...ruleDetail.rule.semantic_bindings![0],
        semantic_field: 'new.payment_ratio',
      }],
      standardized_fields: [{
        ...ruleDetail.rule.standardized_fields[0],
        metric_code: 'new.payment_ratio',
        standard_value: 0.85,
      }],
    }
    vi.mocked(getChangeSet).mockResolvedValue(makeChangeSet({
      items: [{
        ...pendingChangeSet.items[0],
        change_type: 'SEMANTIC_CHANGE',
        before: beforeRule,
        after: afterRule,
      }],
    }))
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)

    expect((await screen.findAllByText('语义调整')).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/统筹基金支付比例为百分之八十五/).length).toBeGreaterThan(0)
  })

  it('uses the before snapshot only for an expired candidate', async () => {
    const expiredRule = {
      ...ruleDetail.rule,
      business_sentence: '失效前候选规则：三级医院支付比例为 85%。',
      source_text: '失效前候选政策原文。',
    }
    vi.mocked(getChangeSet).mockResolvedValue(makeChangeSet({
      items: [{
        ...pendingChangeSet.items[0],
        change_type: 'EXPIRE',
        before: expiredRule,
        after: null,
      }],
    }))
    vi.mocked(getRuleDetail).mockResolvedValue({
      ...ruleDetail,
      rule: { ...ruleDetail.rule, business_sentence: '实时规则不应覆盖失效候选。' },
    })
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)

    expect((await screen.findAllByText('失效前候选政策原文。')).length).toBeGreaterThan(0)
    expect(screen.queryByText('实时规则不应覆盖失效候选。')).not.toBeInTheDocument()
  })

  it('reports a missing candidate snapshot instead of falling back to before for a modification', async () => {
    const oldRule = {
      ...ruleDetail.rule,
      business_sentence: '修改前旧规则不能作为本次候选。',
    }
    const lowRiskChangeSet = makeLowRiskChangeSet()
    vi.mocked(listDecisionTasks).mockResolvedValue([])
    vi.mocked(getChangeSet).mockResolvedValue({
      ...lowRiskChangeSet,
      items: [{
        ...lowRiskChangeSet.items[0],
        change_type: 'MODIFY',
        before: oldRule,
        after: null,
      }],
    })
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)

    expect(await screen.findByRole('alert')).toHaveTextContent('候选快照异常/缺失：MODIFY 必须包含 after 快照')
    expect(screen.queryByText('修改前旧规则不能作为本次候选。')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '整批通过审核' })).toBeDisabled()
    expect(screen.getByText('存在 1 个候选快照异常/缺失，无法通过审核')).toBeInTheDocument()
  })

  it('blocks aggregate approval when the change set has no candidate items', async () => {
    vi.mocked(listDecisionTasks).mockResolvedValue([])
    vi.mocked(getChangeSet).mockResolvedValue({
      ...makeLowRiskChangeSet(),
      items: [],
    })
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)

    await screen.findByRole('heading', { name: '知识审核详情' })
    expect(screen.getByRole('button', { name: '整批通过审核' })).toBeDisabled()
    expect(screen.getByText('候选集合为空，无法通过审核')).toBeInTheDocument()
  })

  it('blocks aggregate approval when a non-selected candidate has an invalid runtime shape', async () => {
    const lowRiskChangeSet = makeLowRiskChangeSet()
    const validItem = lowRiskChangeSet.items[0]
    vi.mocked(listDecisionTasks).mockResolvedValue([])
    vi.mocked(getChangeSet).mockResolvedValue({
      ...lowRiskChangeSet,
      items: [
        validItem,
        {
          ...validItem,
          item_id: 'ITEM_BROKEN',
          rule_id: 'RULE_BROKEN',
          unit_id: 'UNIT_BROKEN',
          after: {
            ...ruleDetail.rule,
            knowledge_id: 'KN_BROKEN',
            unit_id: 'UNIT_BROKEN',
            source_text: undefined,
          },
        },
      ],
    })
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)

    await screen.findByRole('heading', { name: '知识审核详情' })
    expect(screen.getAllByText(/统筹基金支付比例为百分之八十五/).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: '整批通过审核' })).toBeDisabled()
    expect(screen.getByText('存在 1 个候选快照异常/缺失，无法通过审核')).toBeInTheDocument()
  })

  it('labels the demo actor without claiming authenticated identity', async () => {
    currentApiContext.userId = 'demo'
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)

    expect(await screen.findByText('当前审核身份：demo（演示身份）')).toBeInTheDocument()
  })

  it('renders the candidate table without fetching live rule context', async () => {
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)

    expect(await screen.findByText('结构化知识列表')).toBeInTheDocument()
    expect(screen.getAllByText(/统筹基金支付比例为百分之八十五/).length).toBeGreaterThan(0)
    expect(getRuleDetail).not.toHaveBeenCalled()
  })

  it('resolves a question with the current user and reloads both review resources', async () => {
    const user = userEvent.setup()
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)
    await screen.findByRole('heading', { name: '知识审核详情' })

    await user.click(screen.getAllByRole('button', { name: '查看候选' })[0])
    expect(screen.getByText(/候选 A/)).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: '接受建议' })[0])

    await waitFor(() => expect(resolveDecisionTask).toHaveBeenCalledWith('DEC_001', {
      action: 'accept_recommendation',
      by: 'context-actor',
      option: pendingTasks[0].recommended_option,
    }))
    expect(getChangeSet).toHaveBeenCalledTimes(2)
    expect(listDecisionTasks).toHaveBeenCalledTimes(2)
  })

  it('requires a reason for return and submits it with the current reviewer', async () => {
    const user = userEvent.setup()
    vi.mocked(listDecisionTasks).mockResolvedValue([])
    vi.mocked(getChangeSet).mockResolvedValue(makeLowRiskChangeSet())
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)
    await screen.findByRole('heading', { name: '知识审核详情' })

    expect(screen.getByRole('button', { name: '整批通过审核' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: '退回重新构建' }))
    const dialog = screen.getByRole('dialog', { name: '退回重新构建' })
    expect(dialog).toHaveAttribute('data-slot', 'dialog-content')
    expect(within(dialog).getByRole('button', { name: '确认退回' })).toBeDisabled()
    await user.type(within(dialog).getByRole('textbox', { name: '退回原因' }), '原文证据不足')
    await user.click(within(dialog).getByRole('button', { name: '确认退回' }))

    await waitFor(() => expect(returnKnowledgeReview).toHaveBeenCalledWith(
      'CS_REVIEW',
      'context-actor',
      '原文证据不足',
    ))
    expect(push).toHaveBeenCalledWith('/policy-knowledge/knowledge/review')
    expect(refresh).toHaveBeenCalled()
  })

  it('skips a pending issue with the current actor and reloads the same review context', async () => {
    const user = userEvent.setup()
    const resolvedSkipTask: DecisionTask = {
      ...pendingTasks[0],
      status: 'RESOLVED',
      decision: { action: 'skip', by: 'context-actor' },
      resolved_at: '2026-08-05T08:06:00Z',
    }
    vi.mocked(listDecisionTasks)
      .mockResolvedValueOnce([pendingTasks[0]])
      .mockResolvedValueOnce([resolvedSkipTask])
    vi.mocked(getChangeSet).mockResolvedValue(makeChangeSet({ risk_summary: { LOW: 1 } }))
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)
    await screen.findByText('结构化知识列表')

    await user.click(screen.getByRole('button', { name: '跳过' }))

    await waitFor(() => expect(resolveDecisionTask).toHaveBeenCalledWith('DEC_001', {
      action: 'skip',
      by: 'context-actor',
    }))
    expect(getChangeSet).toHaveBeenCalledTimes(2)
    expect(listDecisionTasks).toHaveBeenCalledTimes(2)
    expect(screen.getByText('已跳过')).toBeInTheDocument()
  })

  it('requires a reason before rejecting the review result', async () => {
    const user = userEvent.setup()
    vi.mocked(listDecisionTasks).mockResolvedValue([])
    vi.mocked(getChangeSet).mockResolvedValue(makeChangeSet({ risk_summary: { LOW: 1 } }))
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)
    await screen.findByText('结构化知识列表')

    await user.click(screen.getAllByRole('button', { name: '拒绝' }).at(-1)!)
    const dialog = screen.getByRole('dialog', { name: '拒绝' })
    expect(within(dialog).getByRole('button', { name: '确认拒绝' })).toBeDisabled()
    await user.type(within(dialog).getByRole('textbox', { name: '拒绝原因' }), '规则结论与原文冲突')
    await user.click(within(dialog).getByRole('button', { name: '确认拒绝' }))

    await waitFor(() => expect(rejectChangeSet).toHaveBeenCalledWith(
      'CS_REVIEW',
      'context-actor',
      '规则结论与原文冲突',
    ))
    expect(push).toHaveBeenCalledWith('/policy-knowledge/knowledge/review')
  })

  it('approves a single candidate row with the current actor', async () => {
    const user = userEvent.setup()
    vi.mocked(listDecisionTasks).mockResolvedValue([])
    vi.mocked(getChangeSet).mockResolvedValue(makeLowRiskChangeSet())
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)
    await screen.findByText('结构化知识列表')

    await user.click(screen.getByRole('button', { name: '通过' }))

    await waitFor(() => expect(reviewKnowledge).toHaveBeenCalledWith(
      'KN_001',
      expect.objectContaining({
        doc_id: 'DOC_001',
        unit_id: 'UNIT_001',
        knowledge_id: 'KN_001',
        status: 'approved',
        reviewed_by: 'context-actor',
      }),
    ))
    expect((await screen.findAllByText('已通过')).length).toBeGreaterThan(0)
  })

  it('rejects a single candidate row with a required reason', async () => {
    const user = userEvent.setup()
    vi.mocked(listDecisionTasks).mockResolvedValue([])
    vi.mocked(getChangeSet).mockResolvedValue(makeLowRiskChangeSet())
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)
    await screen.findByText('结构化知识列表')

    await user.click(screen.getAllByRole('button', { name: '拒绝' })[0])
    const dialog = screen.getByRole('dialog', { name: '拒绝该条知识' })
    expect(dialog).toHaveAttribute('data-slot', 'dialog-content')
    expect(within(dialog).getByRole('button', { name: '确认拒绝' })).toBeDisabled()
    await user.type(within(dialog).getByRole('textbox', { name: '拒绝原因' }), '规则结论与原文冲突')
    await user.click(within(dialog).getByRole('button', { name: '确认拒绝' }))

    await waitFor(() => expect(reviewKnowledge).toHaveBeenCalledWith(
      'KN_001',
      expect.objectContaining({
        status: 'rejected',
        reviewed_by: 'context-actor',
        note: '规则结论与原文冲突',
      }),
    ))
    expect((await screen.findAllByText('已拒绝')).length).toBeGreaterThan(0)
  })

  it('returns a single candidate row and marks it with a prefixed reason', async () => {
    const user = userEvent.setup()
    vi.mocked(listDecisionTasks).mockResolvedValue([])
    vi.mocked(getChangeSet).mockResolvedValue(makeLowRiskChangeSet())
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)
    await screen.findByText('结构化知识列表')

    await user.click(screen.getAllByRole('button', { name: '退回' })[0])
    const dialog = screen.getByRole('dialog', { name: '退回该条知识' })
    await user.type(within(dialog).getByRole('textbox', { name: /退回原因/ }), '原文证据不足')
    await user.click(within(dialog).getByRole('button', { name: '确认退回' }))

    await waitFor(() => expect(reviewKnowledge).toHaveBeenCalledWith(
      'KN_001',
      expect.objectContaining({
        status: 'rejected',
        note: '[退回重提取] 原文证据不足',
      }),
    ))
    expect((await screen.findAllByText('已退回')).length).toBeGreaterThan(0)
  })

  it('filters the review table by source unit', async () => {
    const user = userEvent.setup()
    const secondItem = {
      ...pendingChangeSet.items[0],
      item_id: 'ITEM_002',
      rule_id: 'RULE_002',
      unit_id: 'UNIT_002',
      after: {
        ...ruleDetail.rule,
        knowledge_id: 'KN_002',
        business_sentence: '第二条候选知识结论。',
        source_text: '第二条候选原文。',
      },
    }
    vi.mocked(getChangeSet).mockResolvedValue(makeChangeSet({
      items: [pendingChangeSet.items[0], secondItem],
    }))
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)
    await screen.findByText('结构化知识列表')

    expect(screen.getAllByText('第二条候选原文。').length).toBeGreaterThan(0)
    await user.selectOptions(screen.getByRole('combobox', { name: '按单元筛选' }), 'UNIT_002')
    expect(screen.queryByText(/统筹基金支付比例为百分之八十五/)).not.toBeInTheDocument()
    expect(screen.getByText('第二条候选原文。')).toBeInTheDocument()
  })

  it('filters the review table by change type', async () => {
    const user = userEvent.setup()
    vi.mocked(listDecisionTasks).mockResolvedValue([])
    const addItem: typeof pendingChangeSet.items[number] = {
      ...pendingChangeSet.items[0],
      item_id: 'ITEM_002',
      rule_id: 'RULE_002',
      unit_id: 'UNIT_002',
      change_type: 'ADD',
      after: {
        ...ruleDetail.rule,
        knowledge_id: 'KN_002',
        business_sentence: '新增规则结论。',
        source_text: '新增规则原文片段。',
      },
    }
    vi.mocked(getChangeSet).mockResolvedValue(makeChangeSet({
      risk_summary: { LOW: 2 },
      items: [
        { ...pendingChangeSet.items[0], risk_level: 'LOW', needs_human: false },
        addItem,
      ],
    }))
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)
    await screen.findByText('结构化知识列表')

    expect(screen.getAllByText(/统筹基金支付比例为百分之八十五/).length).toBeGreaterThan(0)
    expect(screen.getByText('新增规则原文片段。')).toBeInTheDocument()
    await user.selectOptions(screen.getByRole('combobox', { name: '按变更类型筛选' }), 'ADD')
    expect(screen.queryByText(/统筹基金支付比例为百分之八十五/)).not.toBeInTheDocument()
    expect(screen.getByText('新增规则原文片段。')).toBeInTheDocument()
  })

  it('batch-approves multiple selected rows with the current actor', async () => {
    const user = userEvent.setup()
    vi.mocked(listDecisionTasks).mockResolvedValue([])
    vi.mocked(reviewKnowledge).mockClear()
    const secondItem: typeof pendingChangeSet.items[number] = {
      ...pendingChangeSet.items[0],
      item_id: 'ITEM_002',
      rule_id: 'RULE_002',
      unit_id: 'UNIT_002',
      after: { ...ruleDetail.rule, knowledge_id: 'KN_002' },
    }
    vi.mocked(getChangeSet).mockResolvedValue(makeChangeSet({
      risk_summary: { LOW: 2 },
      items: [
        { ...pendingChangeSet.items[0], risk_level: 'LOW', needs_human: false },
        { ...secondItem, risk_level: 'LOW', needs_human: false },
      ],
    }))
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)
    await screen.findByText('结构化知识列表')

    await user.click(screen.getByRole('checkbox', { name: '全选可审核项' }))
    await user.click(screen.getByRole('button', { name: /批量通过/ }))

    await waitFor(() => expect(reviewKnowledge).toHaveBeenCalledTimes(2))
    expect(reviewKnowledge).toHaveBeenCalledWith('KN_001', expect.objectContaining({ status: 'approved', reviewed_by: 'context-actor' }))
    expect(reviewKnowledge).toHaveBeenCalledWith('KN_002', expect.objectContaining({ status: 'approved', reviewed_by: 'context-actor' }))
  })

  it('expands the 19 rule-object fields as table columns without JSON formatting', async () => {
    vi.mocked(listDecisionTasks).mockResolvedValue([])
    vi.mocked(getChangeSet).mockResolvedValue(makeChangeSet({
      items: [{
        ...pendingChangeSet.items[0],
        after: {
          ...ruleDetail.rule,
          fields: [
            { field_code: 'hosp_lv', field_name: '医疗机构等级', raw_value: '三级' },
            { field_code: 'psn_type', field_name: '人群标签', raw_value: '在职职工、退休人员' },
            { field_code: 'entities', field_name: 'entities', raw_value: [
              { name: '在职职工', type: 'PERSON', highlight: '在职职工' },
              { name: '退休人员', type: 'PERSON', highlight: '退休人员' },
            ] },
            { field_code: 'relations', field_name: 'relations', raw_value: [
              { subject: '基本医疗保险统筹基金', predicate: '最高支付限额', object: '10万元' },
            ] },
          ],
        },
      }],
    }))
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)

    expect(await screen.findByText('结构化知识列表')).toBeInTheDocument()
    // 默认只展示业务核心列（所属单元由分组标题行提供；ID 列隐藏）
    for (const header of ['规则类型', '人群标签', '医疗机构等级', '金额分段', '支付比例', '个人支付比例', '规则值', '原始政策文本']) {
      expect(screen.getByRole('columnheader', { name: header })).toBeInTheDocument()
    }
    expect(screen.queryByRole('columnheader', { name: '政策文件ID' })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: '条款ID' })).not.toBeInTheDocument()
    // 打开列设置并全部显示：全部 rule-object 字段均可展开为列
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '表格列设置' }))
    await user.click(screen.getByRole('button', { name: '全部显示' }))
    for (const header of ['政策文件ID', '单元ID', '所属单元', '规则ID', '险种类别', '医疗类别', '医疗机构等级', '人群标签', '结算方式', '支付比例', '个人支付比例', '起付金额', '封顶金额', '金额分段', '时间周期', '住院次数', '规则优先级', '规则类型', '规则值', '业务描述', '原始政策文本', '条款ID']) {
      expect(screen.getByRole('columnheader', { name: header })).toBeInTheDocument()
    }
    expect(screen.queryByRole('columnheader', { name: '实体' })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: '关系' })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: '单元原文' })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: '变更/结论' })).not.toBeInTheDocument()
    expect(screen.getByText('三级')).toBeInTheDocument()
    expect(screen.getAllByText('在职职工、退休人员').length).toBeGreaterThan(0)
    expect(screen.queryByText(/"name"|"subject"|\[\{/)).not.toBeInTheDocument()
  })

  it('reflects the matched preset in the column settings dropdown', async () => {
    const user = userEvent.setup()
    window.localStorage.clear()
    vi.mocked(listDecisionTasks).mockResolvedValue([])
    vi.mocked(getChangeSet).mockResolvedValue(makeLowRiskChangeSet())
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)
    await screen.findByText('结构化知识列表')

    await user.click(screen.getByRole('button', { name: '表格列设置' }))
    const presetSelect = screen.getByRole('combobox', { name: '按规则类型预设列' })
    // 默认列布局与"支付比例"预设一致，回显该预设
    expect(presetSelect).toHaveValue('支付比例')
    await user.selectOptions(presetSelect, '资格')
    expect(presetSelect).toHaveValue('资格')
  })

  it('shows a 409 current-state message and never fakes navigation success', async () => {
    const user = userEvent.setup()
    vi.mocked(listDecisionTasks).mockResolvedValue([])
    vi.mocked(getChangeSet).mockResolvedValue(makeLowRiskChangeSet())
    vi.mocked(approveChangeSet).mockRejectedValueOnce(new PolicyKnowledgeApiError(
      '当前状态为 RETURNED，不能通过审核',
      409,
      'KNOWLEDGE_REVIEW_STATE_CONFLICT',
      {},
    ))
    const page = await KnowledgeReviewDetailRoute({
      params: Promise.resolve({ changeSetId: 'CS_REVIEW' }),
    })
    render(page)
    await screen.findByRole('heading', { name: '知识审核详情' })

    await user.click(screen.getByRole('button', { name: '整批通过审核' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('当前状态为 RETURNED，不能通过审核')
    expect(push).not.toHaveBeenCalled()
    expect(refresh).not.toHaveBeenCalled()
  })
})

function makeChangeSet(overrides: Partial<KnowledgeChangeSet> = {}): KnowledgeChangeSet {
  return {
    change_set_id: 'CS_REVIEW',
    source_document_version_id: 'DOC_REV_001',
    doc_id: 'DOC_001',
    doc_title: '职工基本医疗保险办法',
    build_task_id: 'TASK_001',
    source_units: [
      {
        doc_id: 'DOC_001',
        doc_title: '职工基本医疗保险办法',
        unit_id: 'UNIT_001',
        unit_revision_id: 'REV_001',
        path: ['第三章', '第十二条'],
      },
      {
        doc_id: 'DOC_001',
        doc_title: '职工基本医疗保险办法',
        unit_id: 'UNIT_002',
        unit_revision_id: 'REV_002',
        path: ['第三章', '第十三条'],
      },
    ],
    semantic_contract_version: 'v2.3',
    supersedes_candidate_id: null,
    status: 'PENDING_REVIEW',
    summary: { additions: 2, modifications: 1, replacements: 1, expirations: 0, unchanged: 5 },
    items: [{
      item_id: 'ITEM_001',
      change_type: 'MODIFY',
      rule_id: 'KNOWLEDGE_001',
      canonical_rule: { rule_id: 'RULE_001' },
      compile_run_id: 'RUN_ITEM_001',
      unit_id: 'UNIT_001',
      doc_id: 'DOC_001',
      before: { payment_ratio: 0.8, hospital_level: '三级' },
      after: {
        ...ruleDetail?.rule,
        payment_ratio: 0.85,
        hospital_level: '三级',
      },
      ai_recommendation: '核对支付比例后通过',
      reason: '政策原文中的支付比例由 80% 调整为 85%',
      evidence_ids: ['EVID_001'],
      quality_checks: ['source_fidelity_passed'],
      risk_level: 'HIGH',
      impact_scope: { rule_count: 1 },
      needs_human: true,
    }],
    quality_report: {
      source_fidelity: 1,
      structural_completeness: 0.95,
      semantic_consistency: 0.9,
      rule_consistency: 0.92,
    },
    risk_summary: { HIGH: 1, MEDIUM: 1 },
    blockers: [],
    review_decision: null,
    created_at: '2026-08-05T08:00:00Z',
    updated_at: '2026-08-05T08:05:00Z',
    ...overrides,
  }
}

function makeDecisionTask(overrides: Partial<DecisionTask> = {}): DecisionTask {
  return {
    task_id: 'DEC_001',
    task_type: 'INSUFFICIENT_EVIDENCE',
    question: '该支付比例是否有足够原文证据？',
    recommended_option: { action: 'retain', detail: '保留 85%，并复核原文' },
    alternatives: [{ action: 'return', detail: '退回补充证据' }],
    evidence: { rule_id: 'RULE_001', exact_quote: '统筹基金支付比例为百分之八十五' },
    risk_level: 'MEDIUM',
    affected_items: { rule_ids: ['RULE_001'] },
    blocking_scope: 'CS_REVIEW',
    status: 'PENDING',
    decision: null,
    created_at: '2026-08-05T08:04:00Z',
    resolved_at: null,
    ...overrides,
  }
}

function makeLowRiskChangeSet(): KnowledgeChangeSet {
  const changeSet = makeChangeSet({ risk_summary: { LOW: 1 } })
  return {
    ...changeSet,
    items: changeSet.items.map((item) => ({ ...item, risk_level: 'LOW', needs_human: false })),
  }
}
