'use client'

/** Issue #19：知识构建页医疗类别分类面板 + 新建任务向导按医疗类别筛选。 */
import { StrictMode } from 'react'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import KnowledgeBuildRoute from '../../../app/policy-knowledge/knowledge/build/page'
import {
  listEligibleKnowledgeUnits,
  listKnowledgeBuildTasks,
  preflightKnowledgeBuild,
  setUnitMedType,
  type EligibleKnowledgeUnit,
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
  setUnitMedType: vi.fn(),
  resetUnitMedType: vi.fn(),
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
    med_type: '住院',
    med_type_source: 'auto',
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
    availability: 'AVAILABLE',
    occupied_by: null,
    target_href: null,
    med_type: '通用',
    med_type_source: 'auto',
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
    med_type: '门诊特殊病',
    med_type_source: 'auto',
  },
]

const tasks: KnowledgeBuildTask[] = []

beforeEach(() => {
  vi.mocked(listEligibleKnowledgeUnits).mockReset().mockResolvedValue(eligibleUnits)
  vi.mocked(listKnowledgeBuildTasks).mockReset().mockResolvedValue(tasks)
  vi.mocked(preflightKnowledgeBuild).mockReset().mockResolvedValue({
    selected_count: 0, buildable_count: 0, blocking_count: 0, rebuild_count: 0,
    can_submit: false, semantic_contract_version: 'v2.3',
    blockers: [], warnings: [],
  })
  vi.mocked(setUnitMedType).mockReset().mockResolvedValue({
    doc_id: 'DOC_001', unit_id: 'UNIT_001', med_type: '急诊', updated_by: 'policy-user-42',
  })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

async function renderPage() {
  render(<StrictMode><KnowledgeBuildRoute /></StrictMode>)
}

describe('med type classification panel', () => {
  it('classifies units, opens detail drawer, fuzzy searches, and corrects manually', async () => {
    const user = userEvent.setup()
    await renderPage()

    // 执行分类前不展示统计
    expect(screen.queryByRole('group', { name: '医疗类别数量' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /执行分类/ }))

    // 类别数量卡片（含计数）
    const group = await screen.findByRole('group', { name: '医疗类别数量' })
    expect(within(group).getByText('住院')).toBeInTheDocument()
    expect(within(group).getByText('通用')).toBeInTheDocument()
    expect(within(group).getByText('门诊特殊病')).toBeInTheDocument()

    // 点击类别卡片 → 侧边抽屉展示明细（通用 1 个单元）
    await user.click(within(group).getByText('通用'))
    const drawer = await screen.findByRole('dialog', { name: /通用/ })
    expect(within(drawer).queryByText('在职职工住院起付标准按医院等级确定。')).not.toBeInTheDocument()
    expect(within(drawer).getByText('退休人员待遇调整需经人工复核。')).toBeInTheDocument()
    expect(within(drawer).getByText('自动')).toBeInTheDocument()

    // 模糊搜索：无命中时显示空态
    const search = within(drawer).getByRole('searchbox', { name: '搜索单元' })
    await user.type(search, '不存在的条款')
    expect(within(drawer).getByText('没有匹配的单元')).toBeInTheDocument()
    await user.clear(search)
    await waitFor(() => expect(within(drawer).getByText('退休人员待遇调整需经人工复核。')).toBeInTheDocument())

    // 抽屉内切换类别下拉：通用 → 住院
    const categorySelect = within(drawer).getByRole('combobox', { name: '切换医疗类别' })
    await user.selectOptions(categorySelect, '住院')
    expect(within(drawer).getByText('在职职工住院起付标准按医院等级确定。')).toBeInTheDocument()

    // 人工修正：住院 → 急诊
    await user.click(within(drawer).getByRole('button', { name: /修改/ }))
    const select = within(drawer).getByRole('combobox', { name: '选择医疗类别' })
    await user.selectOptions(select, '急诊')
    await user.click(within(drawer).getByRole('button', { name: '保存' }))

    await waitFor(() => expect(setUnitMedType).toHaveBeenCalledWith(
      'DOC_001', 'UNIT_001', '急诊', 'policy-user-42',
    ))
    // 修正后刷新单元列表
    await waitFor(() => expect(vi.mocked(listEligibleKnowledgeUnits).mock.calls.length).toBeGreaterThanOrEqual(3))

    // 关闭抽屉
    await user.click(within(drawer).getByRole('button', { name: '关闭单元明细抽屉' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: /通用|住院/ })).not.toBeInTheDocument())
  })
})

describe('build wizard med type filter', () => {
  it('filters selectable units by medical category in step 1', async () => {
    const user = userEvent.setup()
    await renderPage()

    await user.click(await screen.findByRole('button', { name: /新建构建任务/ }))

    const medTypeSelect = await screen.findByRole('combobox', { name: '按医疗类别筛选' })
    // 默认全部：三个单元卡片都在
    expect(screen.getByText('在职职工住院起付标准按医院等级确定。')).toBeInTheDocument()
    expect(screen.getByText('门诊慢特病支付范围按病种目录执行。')).toBeInTheDocument()

    // 只看住院
    await user.selectOptions(medTypeSelect, '住院')
    expect(screen.getByText('在职职工住院起付标准按医院等级确定。')).toBeInTheDocument()
    expect(screen.queryByText('门诊慢特病支付范围按病种目录执行。')).not.toBeInTheDocument()

    // 切到门诊特殊病
    await user.selectOptions(medTypeSelect, '门诊特殊病')
    expect(screen.queryByText('在职职工住院起付标准按医院等级确定。')).not.toBeInTheDocument()
    expect(screen.getByText('门诊慢特病支付范围按病种目录执行。')).toBeInTheDocument()
  })
})
