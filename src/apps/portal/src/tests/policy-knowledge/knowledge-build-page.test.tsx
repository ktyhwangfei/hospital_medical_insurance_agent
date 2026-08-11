import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import KnowledgeBuildRoute from '../../../app/policy-knowledge/knowledge/build/page'
import {
  createKnowledgeBuildTask,
  listEligibleKnowledgeUnits,
  listKnowledgeBuildTasks,
  PolicyKnowledgeApiError,
  preflightKnowledgeBuild,
  type EligibleKnowledgeUnit,
  type KnowledgeBuildPreflight,
  type KnowledgeBuildTask,
} from '@/lib/policy-knowledge-api'

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => '/policy-knowledge/knowledge/build'),
}))

vi.mock('@/lib/api-context', () => ({
  useApiContext: vi.fn(() => ({ userId: 'policy-user-42' })),
}))

vi.mock('@/lib/policy-knowledge-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/policy-knowledge-api')>()),
  createKnowledgeBuildTask: vi.fn(),
  listEligibleKnowledgeUnits: vi.fn(),
  listKnowledgeBuildTasks: vi.fn(),
  listTestCases: vi.fn(),
  preflightKnowledgeBuild: vi.fn(),
}))

const eligibleUnits: EligibleKnowledgeUnit[] = [
  {
    doc_id: 'DOC_001',
    doc_title: '职工基本医疗保险办法',
    unit_id: 'UNIT_001',
    unit_revision_id: 'REV_001_A',
    path: ['第三章', '第十二条'],
    source_preview: '在职职工住院起付标准按医院等级确定。',
    status: 'reviewed',
    knowledge_count: 0,
    availability: 'AVAILABLE',
    occupied_by: null,
    target_href: null,
  },
  {
    doc_id: 'DOC_001',
    doc_title: '职工基本医疗保险办法',
    unit_id: 'UNIT_002',
    unit_revision_id: 'REV_002_B',
    path: ['第四章', '第二十条'],
    source_preview: '退休人员待遇调整需经人工复核。',
    status: 'reviewed',
    knowledge_count: 2,
    availability: 'CLAIMED',
    occupied_by: 'TASK_CLAIMED',
    target_href: '/policy-knowledge/knowledge/review/CS_CLAIMED',
  },
  {
    doc_id: 'DOC_002',
    doc_title: '门诊慢特病管理细则',
    unit_id: 'UNIT_003',
    unit_revision_id: 'REV_003_C',
    path: ['第二章', '第八条'],
    source_preview: '门诊慢特病支付范围按病种目录执行。',
    status: 'published',
    knowledge_count: 4,
    availability: 'REBUILD_REQUIRED',
    occupied_by: null,
    target_href: null,
  },
]

const tasks: KnowledgeBuildTask[] = [
  makeTask({
    task_id: 'TASK_RUNNING',
    name: '住院政策首次构建',
    status: 'RUNNING',
    processed_units: 1,
    units: [taskUnit('UNIT_001', 'REV_001_A'), taskUnit('UNIT_004', 'REV_004_A')],
  }),
  makeTask({
    task_id: 'TASK_REVIEW',
    name: '门诊政策同步构建',
    status: 'WAITING_REVIEW',
    processed_units: 1,
    result_change_set_id: 'CS_REVIEW',
    result_summary: { additions: 2, modifications: 1, unchanged: 4 },
    issue_count: 3,
  }),
  makeTask({
    task_id: 'TASK_FAILED',
    name: '异地政策构建',
    status: 'FAILED',
    processed_units: 0,
    units: [{ ...taskUnit('UNIT_005', 'REV_005_A'), status: 'FAILED', error_code: 'EXTRACT_TIMEOUT', error_message: '模型提取超时' }],
  }),
  makeTask({
    task_id: 'TASK_PUBLISHED',
    name: '历史发布任务',
    status: 'PUBLISHED',
    processed_units: 1,
    result_change_set_id: 'CS_PUBLISHED',
  }),
  makeTask({
    task_id: 'TASK_APPROVED',
    name: '审核通过待发布任务',
    status: 'APPROVED_PENDING_RELEASE',
    processed_units: 1,
    result_change_set_id: 'CS_APPROVED',
  }),
]

const buildablePreflight: KnowledgeBuildPreflight = {
  selected_count: 1,
  buildable_count: 1,
  blocking_count: 0,
  rebuild_count: 0,
  can_submit: true,
  semantic_contract_version: 'v2.3',
  blockers: [],
  warnings: [],
}

beforeEach(() => {
  vi.mocked(listEligibleKnowledgeUnits).mockReset()
  vi.mocked(listKnowledgeBuildTasks).mockReset()
  vi.mocked(preflightKnowledgeBuild).mockReset()
  vi.mocked(createKnowledgeBuildTask).mockReset()
  vi.mocked(listEligibleKnowledgeUnits).mockResolvedValue(eligibleUnits)
  vi.mocked(listKnowledgeBuildTasks).mockResolvedValue(tasks)
  vi.mocked(preflightKnowledgeBuild).mockResolvedValue(buildablePreflight)
  vi.mocked(createKnowledgeBuildTask).mockResolvedValue(makeTask({
    task_id: 'TASK_NEW',
    name: '职工基本医疗保险办法等 1 个单元',
    status: 'WAITING_REVIEW',
    processed_units: 1,
    result_change_set_id: 'CS_NEW',
  }))
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('knowledge build page', () => {
  it('renders the fixed workspace order, real summaries, and honest task progress', async () => {
    const { container } = render(<KnowledgeBuildRoute />)

    expect(screen.getAllByRole('button', { name: '新建构建任务' })).toHaveLength(1)
    expect(screen.queryByText('选择已审核单元')).not.toBeInTheDocument()

    await screen.findByText('可构建单元')
    expect(screen.getByLabelText('可构建单元摘要')).toHaveTextContent('2')
    expect(screen.getByLabelText('构建中摘要')).toHaveTextContent('1')
    expect(screen.getByLabelText('等待审核摘要')).toHaveTextContent('1')
    expect(screen.getByLabelText('待发布摘要')).toHaveTextContent('1')
    expect(screen.getByLabelText('已发布摘要')).toHaveTextContent('1')
    expect(screen.getByLabelText('知识构建上下文')).toHaveTextContent('语义契约版本：暂无版本')
    expect(container).not.toHaveTextContent('96.4%')

    const regions = within(container).getAllByTestId(/knowledge-build-section-/)
    expect(regions.map((region) => region.dataset.testid)).toEqual([
      'knowledge-build-section-nav',
      'knowledge-build-section-context',
      'knowledge-build-section-flow',
      'knowledge-build-section-summary',
      'knowledge-build-section-tasks',
    ])

    const runningRow = screen.getByRole('row', { name: /TASK_RUNNING/ })
    expect(runningRow).toHaveTextContent('50%')
    expect(runningRow).toHaveTextContent('知识构建')

    const reviewRow = screen.getByRole('row', { name: /TASK_REVIEW/ })
    expect(reviewRow).toHaveTextContent('100%')
    expect(reviewRow).toHaveTextContent('待审核')
    expect(reviewRow).toHaveTextContent('新增 2')
    expect(reviewRow).toHaveTextContent('修改 1')
    expect(reviewRow).toHaveTextContent('未变化 4')
    expect(reviewRow).toHaveTextContent('待处理问题 3')
    expect(within(reviewRow).getByRole('link', { name: '进入审核' })).toHaveAttribute(
      'href',
      '/policy-knowledge/knowledge/review/CS_REVIEW',
    )

    const failedRow = screen.getByRole('row', { name: /TASK_FAILED/ })
    expect(failedRow).toHaveTextContent('模型提取超时')
    expect(failedRow).not.toHaveTextContent('处理中')
  })

  it('selects exact reviewed revisions, excludes blockers, creates, refreshes, and clears the drawer', async () => {
    const user = userEvent.setup()
    const blockedPreflight: KnowledgeBuildPreflight = {
      ...buildablePreflight,
      selected_count: 2,
      buildable_count: 1,
      blocking_count: 1,
      can_submit: false,
      blockers: [{
        code: 'UNIT_REVISION_CHANGED',
        message: '单元修订已变化',
        doc_id: 'DOC_002',
        unit_id: 'UNIT_003',
        unit_revision_id: 'REV_003_NEW',
        task_id: null,
        target_href: null,
      }],
    }
    vi.mocked(preflightKnowledgeBuild)
      .mockResolvedValueOnce(blockedPreflight)
      .mockResolvedValueOnce(buildablePreflight)

    render(<KnowledgeBuildRoute />)
    await screen.findByLabelText('可构建单元摘要')
    await user.click(screen.getByRole('button', { name: '新建构建任务' }))

    const drawer = screen.getByRole('dialog', { name: '新建构建任务' })
    expect(within(drawer).getByText('选择已审核单元')).toBeInTheDocument()
    await user.type(within(drawer).getByRole('searchbox', { name: '搜索政策标题或条款' }), '医疗保险')
    expect(within(drawer).getByRole('checkbox', { name: /REV_001_A/ })).toBeInTheDocument()
    expect(within(drawer).queryByRole('checkbox', { name: /第八条.*REV_003_C/ })).not.toBeInTheDocument()
    await user.clear(within(drawer).getByRole('searchbox', { name: '搜索政策标题或条款' }))

    await user.click(within(drawer).getByRole('checkbox', { name: /第十二条.*REV_001_A/ }))
    expect(within(drawer).getByRole('checkbox', { name: /第八条.*REV_003_C/ })).toBeDisabled()
    await user.click(within(drawer).getByRole('switch', { name: '重新构建已发布单元' }))
    await user.click(within(drawer).getByRole('checkbox', { name: /第八条.*REV_003_C/ }))
    await user.click(within(drawer).getByRole('button', { name: '下一步：确认配置' }))

    expect(within(drawer).getByText('确认构建配置')).toBeInTheDocument()
    expect(within(drawer).getByLabelText('语义契约版本')).toHaveValue('创建时由服务端锁定')
    expect(within(drawer).getByLabelText('语义契约版本')).toHaveAttribute('readonly')
    expect(within(drawer).getByLabelText('构建模式')).toHaveValue('重新构建')
    expect(within(drawer).getByLabelText('流水线版本')).toHaveAttribute('readonly')
    expect(within(drawer).getByLabelText('流水线版本')).toHaveValue('创建时由服务端锁定')
    expect(within(drawer).getByLabelText('模型场景')).toHaveAttribute('readonly')
    expect(within(drawer).getByLabelText('模型场景')).toHaveValue('创建时由服务端锁定')
    expect(within(drawer).getByLabelText('配置哈希')).toHaveAttribute('readonly')
    expect(within(drawer).getByLabelText('配置哈希')).toHaveValue('创建时由服务端锁定')
    expect(within(drawer).getByRole('textbox', { name: '重建原因' })).toBeRequired()

    await user.clear(within(drawer).getByRole('textbox', { name: '任务名称' }))
    await user.type(within(drawer).getByRole('textbox', { name: '任务名称' }), '医保政策精确构建')
    await user.type(within(drawer).getByRole('textbox', { name: '重建原因' }), '政策条款已更新')
    await user.click(within(drawer).getByRole('button', { name: '下一步：冲突预检' }))

    expect(within(drawer).getByText('冲突预检')).toBeInTheDocument()
    expect(within(drawer).getByText('语义契约 v2.3')).toBeInTheDocument()
    expect(within(drawer).getByText(/单元修订已变化/)).toBeInTheDocument()
    expect(within(drawer).getByRole('button', { name: '创建构建任务' })).toBeDisabled()
    await user.click(within(drawer).getByRole('button', { name: '排除这些单元' }))
    await waitFor(() => expect(within(drawer).getByRole('button', { name: '创建构建任务' })).toBeEnabled())
    await user.click(within(drawer).getByRole('button', { name: '创建构建任务' }))

    expect(await screen.findByRole('status')).toHaveTextContent('已生成待审知识')
    expect(screen.queryByRole('dialog', { name: '新建构建任务' })).not.toBeInTheDocument()
    expect(createKnowledgeBuildTask).toHaveBeenCalledWith({
      name: '医保政策精确构建',
      created_by: 'policy-user-42',
      build_mode: 'INITIAL',
      rebuild_reason: null,
      unit_revisions: [{ doc_id: 'DOC_001', unit_id: 'UNIT_001', unit_revision_id: 'REV_001_A' }],
    })
    expect(listEligibleKnowledgeUnits).toHaveBeenCalledTimes(2)
    expect(listKnowledgeBuildTasks).toHaveBeenCalledTimes(2)

    await user.click(screen.getByRole('button', { name: '新建构建任务' }))
    expect(screen.getByRole('checkbox', { name: /第十二条.*REV_001_A/ })).not.toBeChecked()
    expect(screen.getByRole('searchbox', { name: '搜索政策标题或条款' })).toHaveValue('')
  })

  it('keeps claimed units disabled with a destination and clears dirty state on close', async () => {
    const user = userEvent.setup()
    render(<KnowledgeBuildRoute />)
    await screen.findByLabelText('可构建单元摘要')
    await user.click(screen.getByRole('button', { name: '新建构建任务' }))

    const claimed = screen.getByRole('checkbox', { name: /第二十条.*等待知识审核/ })
    expect(claimed).toBeDisabled()
    expect(screen.getByRole('link', { name: '查看占用任务 TASK_CLAIMED' })).toHaveAttribute(
      'href',
      '/policy-knowledge/knowledge/review/CS_CLAIMED',
    )
    await user.click(screen.getByRole('checkbox', { name: /第十二条.*REV_001_A/ }))
    await user.type(screen.getByRole('searchbox', { name: '搜索政策标题或条款' }), '职工')
    await user.click(screen.getByRole('button', { name: '关闭创建抽屉' }))

    await user.click(screen.getByRole('button', { name: '新建构建任务' }))
    expect(screen.getByRole('checkbox', { name: /第十二条.*REV_001_A/ })).not.toBeChecked()
    expect(screen.getByRole('searchbox', { name: '搜索政策标题或条款' })).toHaveValue('')
  })

  it('shows a 409 claim conflict with the server task and destination inside preflight', async () => {
    const user = userEvent.setup()
    vi.mocked(createKnowledgeBuildTask).mockRejectedValue(new PolicyKnowledgeApiError(
      '单元已被其他任务占用',
      409,
      'KNOWLEDGE_BUILD_CLAIM_CONFLICT',
      { task_id: 'TASK_RACE', target_href: '/policy-knowledge/knowledge/review/CS_RACE' },
    ))

    render(<KnowledgeBuildRoute />)
    await openBuildablePreflight(user)
    await user.click(screen.getByRole('button', { name: '创建构建任务' }))

    const drawer = screen.getByRole('dialog', { name: '新建构建任务' })
    expect(within(drawer).getByText('单元已被其他任务占用')).toBeInTheDocument()
    expect(within(drawer).getByText('TASK_RACE')).toBeInTheDocument()
    expect(within(drawer).getByRole('button', { name: '创建构建任务' })).toBeDisabled()
    expect(within(drawer).queryByText(/个精确修订可创建构建任务/)).not.toBeInTheDocument()
    expect(within(drawer).getByRole('link', { name: '查看冲突任务' })).toHaveAttribute(
      'href',
      '/policy-knowledge/knowledge/review/CS_RACE',
    )
  })

  it('shows extraction failure without misclassifying it as a semantic outage', async () => {
    const user = userEvent.setup()
    vi.mocked(createKnowledgeBuildTask).mockRejectedValue(new PolicyKnowledgeApiError(
      '模型未返回可构建的政策事实',
      503,
      'KNOWLEDGE_EXTRACTION_FAILED',
      { task_id: 'KB_FAILED', doc_id: 'DOC_001', unit_id: 'UNIT_001' },
    ))

    render(<KnowledgeBuildRoute />)
    await openBuildablePreflight(user)
    await user.click(screen.getByRole('button', { name: '创建构建任务' }))

    const drawer = screen.getByRole('dialog', { name: '新建构建任务' })
    expect(within(drawer).getByText('模型未返回可构建的政策事实')).toBeInTheDocument()
    expect(within(drawer).queryByRole('link', { name: '前往语义层查看' })).not.toBeInTheDocument()
    expect(within(drawer).getByRole('button', { name: '创建构建任务' })).toBeEnabled()
  })

  it('disables creation and links to the semantic layer when the contract is unavailable', async () => {
    const user = userEvent.setup()
    vi.mocked(preflightKnowledgeBuild).mockRejectedValue(new PolicyKnowledgeApiError(
      '当前没有可用的语义契约',
      503,
      'SEMANTIC_CONTRACT_UNAVAILABLE',
      {},
    ))

    render(<KnowledgeBuildRoute />)
    await screen.findByLabelText('可构建单元摘要')
    await user.click(screen.getByRole('button', { name: '新建构建任务' }))
    await user.click(screen.getByRole('checkbox', { name: /第十二条.*REV_001_A/ }))
    await user.click(screen.getByRole('button', { name: '下一步：确认配置' }))
    await user.click(screen.getByRole('button', { name: '下一步：冲突预检' }))

    const drawer = screen.getByRole('dialog', { name: '新建构建任务' })
    expect(within(drawer).getByText('当前没有可用的语义契约')).toBeInTheDocument()
    expect(within(drawer).getByRole('button', { name: '创建构建任务' })).toBeDisabled()
    expect(within(drawer).getByRole('link', { name: '前往语义层查看' })).toHaveAttribute(
      'href',
      '/semantic-layer/metrics',
    )
    expect(within(drawer).queryByRole('button', { name: /编辑契约/ })).not.toBeInTheDocument()
  })

  it('classifies claimed blockers into exactly one workflow stage', async () => {
    const user = userEvent.setup()
    vi.mocked(preflightKnowledgeBuild).mockResolvedValue({
      ...buildablePreflight,
      selected_count: 1,
      buildable_count: 0,
      blocking_count: 4,
      can_submit: false,
      rebuild_count: 0,
      blockers: [
        {
          code: 'UNIT_ALREADY_CLAIMED',
          message: '仍在构建',
          doc_id: 'DOC_001',
          unit_id: 'UNIT_001',
          unit_revision_id: 'REV_001_A',
          task_id: 'TASK_BUILD',
          target_href: '/policy-knowledge/knowledge/build',
        },
        {
          code: 'UNIT_ALREADY_CLAIMED',
          message: '正在审核',
          doc_id: 'DOC_001',
          unit_id: 'UNIT_004',
          unit_revision_id: 'REV_004_A',
          task_id: 'TASK_REVIEWING',
          target_href: '/policy-knowledge/knowledge/review/CS_004',
        },
        {
          code: 'REBUILD_MODE_REQUIRED',
          message: '必须使用重建模式',
          doc_id: 'DOC_002',
          unit_id: 'UNIT_003',
          unit_revision_id: 'REV_003_C',
          task_id: null,
          target_href: null,
        },
        {
          code: 'SEMANTIC_CONTRACT_MISMATCH',
          message: '语义契约已变化',
          doc_id: 'DOC_003',
          unit_id: 'UNIT_006',
          unit_revision_id: 'REV_006_A',
          task_id: null,
          target_href: null,
        },
      ],
    })

    render(<KnowledgeBuildRoute />)
    await openBuildablePreflight(user)

    expect(screen.getByLabelText('活跃占用预检')).toHaveTextContent('1')
    expect(screen.getByLabelText('未结束候选预检')).toHaveTextContent('1')
    expect(screen.getByLabelText('需要重建预检')).toHaveTextContent('1')
    expect(screen.getByText('其他阻断 1')).toBeInTheDocument()
  })

  it('treats an eligible-units 503 as unavailable rather than an empty result', async () => {
    vi.mocked(listEligibleKnowledgeUnits).mockRejectedValue(new PolicyKnowledgeApiError(
      '语义契约服务不可用',
      503,
      'SEMANTIC_CONTRACT_UNAVAILABLE',
      {},
    ))

    render(<KnowledgeBuildRoute />)

    const createButton = await screen.findByRole('button', { name: '新建构建任务' })
    await waitFor(() => expect(createButton).toBeDisabled())
    expect(screen.getByLabelText('可构建单元摘要')).toHaveTextContent('暂无统计')
    expect(screen.getByRole('link', { name: '前往语义层查看' })).toHaveAttribute(
      'href',
      '/semantic-layer/metrics',
    )
  })

  it('keeps eligible statistics while marking task summaries and the task table unavailable', async () => {
    vi.mocked(listKnowledgeBuildTasks).mockRejectedValue(new PolicyKnowledgeApiError(
      '构建任务存储暂不可用',
      503,
      'KNOWLEDGE_BUILD_TASK_STORE_UNAVAILABLE',
      {},
    ))

    render(<KnowledgeBuildRoute />)

    await waitFor(() => expect(screen.getByLabelText('可构建单元摘要')).toHaveTextContent('2'))
    expect(screen.getByLabelText('构建中摘要')).toHaveTextContent('暂无统计')
    expect(screen.getByLabelText('等待审核摘要')).toHaveTextContent('暂无统计')
    expect(screen.getByLabelText('已发布摘要')).toHaveTextContent('暂无统计')
    expect(screen.getByRole('region', { name: '构建任务' })).toHaveTextContent('构建任务数据不可用')
    expect(screen.queryByText('暂无构建任务，请从审核通过的单元新建任务。')).not.toBeInTheDocument()
  })

  it('labels occupied units by their actual workflow destination', async () => {
    const user = userEvent.setup()
    vi.mocked(listEligibleKnowledgeUnits).mockResolvedValue([
      claimedUnit('UNIT_BUILD', 'TASK_BUILD', '/policy-knowledge/knowledge/build'),
      claimedUnit('UNIT_REVIEWING', 'TASK_REVIEWING', '/policy-knowledge/knowledge/review/CS_REVIEWING'),
      claimedUnit('UNIT_RELEASING', 'TASK_RELEASING', '/policy-knowledge/knowledge/releases'),
    ])

    render(<KnowledgeBuildRoute />)
    await screen.findByLabelText('可构建单元摘要')
    await user.click(screen.getByRole('button', { name: '新建构建任务' }))

    expect(screen.getByRole('checkbox', { name: /UNIT_BUILD.*正在知识构建/ })).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: /UNIT_REVIEWING.*等待知识审核/ })).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: /UNIT_RELEASING.*等待发布/ })).toBeDisabled()
    expect(screen.getByRole('link', { name: '查看占用任务 TASK_BUILD' })).toHaveAttribute('href', '/policy-knowledge/knowledge/build')
    expect(screen.getByRole('link', { name: '查看占用任务 TASK_REVIEWING' })).toHaveAttribute('href', '/policy-knowledge/knowledge/review/CS_REVIEWING')
    expect(screen.getByRole('link', { name: '查看占用任务 TASK_RELEASING' })).toHaveAttribute('href', '/policy-knowledge/knowledge/releases')
  })

  it('returns to unit selection without preflighting an empty request after excluding the only unit', async () => {
    const user = userEvent.setup()
    vi.mocked(listEligibleKnowledgeUnits).mockResolvedValue([eligibleUnits[0]])
    vi.mocked(preflightKnowledgeBuild).mockResolvedValue({
      ...buildablePreflight,
      buildable_count: 0,
      blocking_count: 1,
      can_submit: false,
      blockers: [{
        code: 'UNIT_REVISION_CHANGED',
        message: '唯一单元修订已变化',
        doc_id: 'DOC_001',
        unit_id: 'UNIT_001',
        unit_revision_id: 'REV_001_NEW',
        task_id: null,
        target_href: null,
      }],
    })

    render(<KnowledgeBuildRoute />)
    await openBuildablePreflight(user)
    await user.click(screen.getByRole('button', { name: '排除这些单元' }))

    const drawer = screen.getByRole('dialog', { name: '新建构建任务' })
    expect(within(drawer).getByText('选择已审核单元')).toBeInTheDocument()
    expect(within(drawer).getByRole('alert')).toHaveTextContent('所有阻断单元已排除，请重新选择')
    expect(within(drawer).getByText('已选 0 个精确修订')).toBeInTheDocument()
    expect(preflightKnowledgeBuild).toHaveBeenCalledTimes(1)
  })

  it('clears a stale semantic-unavailable state when a retry fails with a non-503 error', async () => {
    const user = userEvent.setup()
    vi.mocked(preflightKnowledgeBuild)
      .mockRejectedValueOnce(new PolicyKnowledgeApiError(
        '当前没有可用的语义契约',
        503,
        'SEMANTIC_CONTRACT_UNAVAILABLE',
        {},
      ))
      .mockRejectedValueOnce(new PolicyKnowledgeApiError(
        '预检服务暂时失败',
        500,
        'KNOWLEDGE_BUILD_PREFLIGHT_FAILED',
        {},
      ))

    render(<KnowledgeBuildRoute />)
    await openBuildablePreflight(user)
    expect(screen.getByRole('link', { name: '前往语义层查看' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '上一步' }))
    await user.click(screen.getByRole('button', { name: '下一步：冲突预检' }))

    const drawer = screen.getByRole('dialog', { name: '新建构建任务' })
    expect(within(drawer).getByRole('alert')).toHaveTextContent('预检服务暂时失败')
    expect(within(drawer).queryByRole('link', { name: '前往语义层查看' })).not.toBeInTheDocument()
  })

  it('discards a completed preflight from a closed wizard instead of polluting a reopened session', async () => {
    const user = userEvent.setup()
    const oldRequest = deferred<KnowledgeBuildPreflight>()
    vi.mocked(preflightKnowledgeBuild).mockReturnValueOnce(oldRequest.promise)

    render(<KnowledgeBuildRoute />)
    await screen.findByLabelText('可构建单元摘要')
    await user.click(screen.getByRole('button', { name: '新建构建任务' }))
    await user.click(screen.getByRole('checkbox', { name: /第十二条.*REV_001_A/ }))
    await user.click(screen.getByRole('button', { name: '下一步：确认配置' }))
    await user.click(screen.getByRole('button', { name: '下一步：冲突预检' }))
    await user.click(screen.getByRole('button', { name: '关闭创建抽屉' }))
    await user.click(screen.getByRole('button', { name: '新建构建任务' }))

    await act(async () => {
      oldRequest.resolve({
        ...buildablePreflight,
        semantic_contract_version: 'v-old-request',
        warnings: [{ code: 'REBUILDING_PUBLISHED_UNIT', message: '旧请求结果', doc_id: 'DOC_OLD', unit_id: 'UNIT_OLD' }],
      })
      await oldRequest.promise
    })

    const drawer = screen.getByRole('dialog', { name: '新建构建任务' })
    expect(within(drawer).getByText('选择已审核单元')).toBeInTheDocument()
    expect(within(drawer).queryByText('v-old-request')).not.toBeInTheDocument()
    expect(within(drawer).queryByText('旧请求结果')).not.toBeInTheDocument()
  })

  it('lands an asynchronous preflight result after StrictMode replays the mount effect', async () => {
    const user = userEvent.setup()
    const strictPreflight = deferred<KnowledgeBuildPreflight>()
    vi.mocked(preflightKnowledgeBuild).mockReturnValueOnce(strictPreflight.promise)

    render(
      <StrictMode>
        <KnowledgeBuildRoute />
      </StrictMode>,
    )
    await screen.findByLabelText('可构建单元摘要')
    await user.click(screen.getByRole('button', { name: '新建构建任务' }))
    await user.click(screen.getByRole('checkbox', { name: /第十二条.*REV_001_A/ }))
    await user.click(screen.getByRole('button', { name: '下一步：确认配置' }))
    await user.click(screen.getByRole('button', { name: '下一步：冲突预检' }))

    await act(async () => {
      strictPreflight.resolve(buildablePreflight)
      await strictPreflight.promise
    })

    const drawer = screen.getByRole('dialog', { name: '新建构建任务' })
    expect(within(drawer).getByText('语义契约 v2.3')).toBeInTheDocument()
    expect(within(drawer).getByRole('button', { name: '创建构建任务' })).toBeEnabled()
  })

  it('keeps every close route disabled while task creation is in flight', async () => {
    const user = userEvent.setup()
    const createRequest = deferred<KnowledgeBuildTask>()
    vi.mocked(createKnowledgeBuildTask).mockReturnValueOnce(createRequest.promise)

    render(<KnowledgeBuildRoute />)
    await openBuildablePreflight(user)
    await user.click(screen.getByRole('button', { name: '创建构建任务' }))

    const closeButton = screen.getByRole('button', { name: '关闭创建抽屉' })
    expect(closeButton).toBeDisabled()
    await user.keyboard('{Escape}')
    expect(screen.getByRole('dialog', { name: '新建构建任务' })).toBeInTheDocument()
    const overlay = document.querySelector<HTMLElement>('[data-slot="dialog-overlay"]')
    expect(overlay).not.toBeNull()
    await user.click(overlay!)
    expect(screen.getByRole('dialog', { name: '新建构建任务' })).toBeInTheDocument()

    await act(async () => {
      createRequest.resolve(makeTask({ task_id: 'TASK_DEFERRED', status: 'WAITING_REVIEW' }))
      await createRequest.promise
    })
    expect(await screen.findByRole('status')).toHaveTextContent('已生成待审知识')
  })

  it('uses the shared dialog primitive for the accessible drawer contract', async () => {
    const user = userEvent.setup()
    render(<KnowledgeBuildRoute />)
    await screen.findByLabelText('可构建单元摘要')
    await user.click(screen.getByRole('button', { name: '新建构建任务' }))

    expect(screen.getByRole('dialog', { name: '新建构建任务' })).toHaveAttribute(
      'data-slot',
      'dialog-content',
    )
  })

  it('submits an explicit published-unit rebuild with its reason and exact revision', async () => {
    const user = userEvent.setup()
    const rebuildPreflight: KnowledgeBuildPreflight = {
      ...buildablePreflight,
      rebuild_count: 1,
    }
    vi.mocked(preflightKnowledgeBuild).mockResolvedValue(rebuildPreflight)

    render(<KnowledgeBuildRoute />)
    await screen.findByLabelText('可构建单元摘要')
    await user.click(screen.getByRole('button', { name: '新建构建任务' }))
    await user.click(screen.getByRole('switch', { name: '重新构建已发布单元' }))
    await user.click(screen.getByRole('checkbox', { name: /第八条.*REV_003_C/ }))
    await user.click(screen.getByRole('button', { name: '下一步：确认配置' }))
    await user.type(screen.getByRole('textbox', { name: '重建原因' }), '发布后政策条款已更新')
    await user.click(screen.getByRole('button', { name: '下一步：冲突预检' }))
    await user.click(screen.getByRole('button', { name: '创建构建任务' }))

    expect(createKnowledgeBuildTask).toHaveBeenCalledWith(expect.objectContaining({
      created_by: 'policy-user-42',
      build_mode: 'REBUILD',
      rebuild_reason: '发布后政策条款已更新',
      unit_revisions: [{ doc_id: 'DOC_002', unit_id: 'UNIT_003', unit_revision_id: 'REV_003_C' }],
    }))
  })
})

async function openBuildablePreflight(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByLabelText('可构建单元摘要')
  await user.click(screen.getByRole('button', { name: '新建构建任务' }))
  await user.click(screen.getByRole('checkbox', { name: /第十二条.*REV_001_A/ }))
  await user.click(screen.getByRole('button', { name: '下一步：确认配置' }))
  await user.click(screen.getByRole('button', { name: '下一步：冲突预检' }))
}

function taskUnit(unitId: string, revisionId: string): KnowledgeBuildTask['units'][number] {
  return {
    doc_id: 'DOC_001',
    doc_title: '职工基本医疗保险办法',
    unit_id: unitId,
    unit_revision_id: revisionId,
    path: ['第三章', '第十二条'],
    status: 'BUILT',
    candidate_result_ids: [],
    error_code: null,
    error_message: null,
  }
}

function claimedUnit(unitId: string, taskId: string, targetHref: string): EligibleKnowledgeUnit {
  return {
    doc_id: 'DOC_CLAIMED',
    doc_title: '占用阶段测试政策',
    unit_id: unitId,
    unit_revision_id: `REV_${unitId}`,
    path: ['占用测试', unitId],
    source_preview: '用于校验占用阶段文案。',
    status: 'reviewed',
    knowledge_count: 0,
    availability: 'CLAIMED',
    occupied_by: taskId,
    target_href: targetHref,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function makeTask(overrides: Partial<KnowledgeBuildTask>): KnowledgeBuildTask {
  return {
    task_id: 'TASK_DEFAULT',
    name: '默认构建任务',
    status: 'WAITING_REVIEW',
    build_mode: 'INITIAL',
    semantic_contract_version: 'v2.3',
    pipeline_version: 'pipeline-2026.08',
    model_scene: 'policy_knowledge_build',
    config_hash: 'sha256:abc123',
    rebuild_reason: null,
    created_by: 'knowledge-admin',
    units: [taskUnit('UNIT_001', 'REV_001_A')],
    processed_units: 1,
    result_change_set_id: null,
    result_summary: {},
    issue_count: 0,
    created_at: '2026-08-05T08:00:00Z',
    updated_at: '2026-08-05T08:01:00Z',
    started_at: '2026-08-05T08:00:10Z',
    finished_at: '2026-08-05T08:01:00Z',
    ...overrides,
  }
}
