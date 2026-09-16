import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import KnowledgeMapPage from '../../../app/policy-knowledge/knowledge-map/page'
import { getKnowledgeMap, type KnowledgeMapData, type KnowledgeMapRule } from '@/lib/policy-knowledge-api'

vi.mock('@/lib/policy-knowledge-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/policy-knowledge-api')>()),
  getKnowledgeMap: vi.fn(),
}))

const mockedGetKnowledgeMap = vi.mocked(getKnowledgeMap)

const ruleFixture = (overrides: Partial<KnowledgeMapRule>): KnowledgeMapRule => ({
  rule_id: 'rule_x',
  doc_id: 'doc_A',
  rule_type: '支付比例',
  insu_type: '职工医保',
  med_type: '住院-普通住院',
  hosp_lv: '三级',
  psn_type: '在职职工',
  setl_type: '',
  region: '北京',
  effective_date: '2024-01-01',
  expiry_date: '9999-12-31',
  publish_status: 'published',
  policy_version: '1.0',
  amount_band: '起付标准至3万元',
  amount_band_min: '1300',
  amount_band_max: '30000',
  admission_order: '',
  priority: '',
  payment_ratio: '85',
  personal_payment_ratio: '15',
  deductible_amount: '1300',
  cap_amount: '',
  rule_value: '统筹基金支付85%，职工支付15%',
  source_text: '起付标准至3万元的部分，统筹基金支付85%，职工支付15%',
  ...overrides,
})

const mapFixture: KnowledgeMapData = {
  active_release_id: 'REL_2026_001',
  rules_collection: 'policy_rules_REL_2026_001',
  facts_collection: 'policy_facts_REL_2026_001',
  collections: [
    { name: 'policy_facts_REL_2026_001', kind: 'facts', row_count: 269, active: true },
    { name: 'policy_rules_REL_2026_001', kind: 'rules', row_count: 2, active: true },
    { name: 'policy_rules_v2', kind: 'rules', row_count: 337, active: false },
  ],
  rules: [
    ruleFixture({ rule_id: 'rule_1' }),
    ruleFixture({
      rule_id: 'rule_2',
      rule_type: '起付线',
      insu_type: '居民医保',
      med_type: '门诊-普通门急诊',
      hosp_lv: '一级',
      psn_type: '',
      amount_band: '',
      amount_band_min: '0',
      amount_band_max: '0',
      payment_ratio: '',
      personal_payment_ratio: '',
      deductible_amount: '100',
      rule_value: '一级医院起付线100元',
      source_text: '一级医院起付标准为100元',
      effective_date: '1900-01-01',
    }),
  ],
  facts_by_doc: [
    { doc_id: 'doc_A', count: 2 },
    { doc_id: 'doc_B', count: 1 },
  ],
}

describe('KnowledgeMapPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
  })

  afterEach(() => {
    cleanup()
    window.localStorage.clear()
  })

  it('渲染集合盘点：active 标记、行数与向量化事实分布', async () => {
    mockedGetKnowledgeMap.mockResolvedValue(mapFixture)

    render(<KnowledgeMapPage />)

    expect(await screen.findByText('policy_rules_v2')).toBeInTheDocument()
    const table = screen.getByLabelText('Milvus 政策集合')
    expect(within(table).getAllByText('当前读路径')).toHaveLength(2)
    expect(within(table).getByText('337')).toBeInTheDocument()
    expect(within(table).getAllByText('历史 / 备用')).toHaveLength(1)

    // 向量化事实按文档分布 chips
    const facts = screen.getByText('向量化事实按文档分布')
    expect(within(facts.closest('div')!).getByText('doc_A')).toBeInTheDocument()
    expect(within(facts.closest('div')!).getByText('doc_B')).toBeInTheDocument()
  })

  it('按维度路线聚合成树，展开到叶子显示规则卡片', async () => {
    mockedGetKnowledgeMap.mockResolvedValue(mapFixture)
    const user = userEvent.setup()

    render(<KnowledgeMapPage />)

    // 默认路线首层 = 参保体系
    const tree = await screen.findByLabelText('知识体系树')
    expect(within(tree).getByRole('button', { name: /职工医保/ })).toBeInTheDocument()
    expect(within(tree).getByRole('button', { name: /居民医保/ })).toBeInTheDocument()

    // 精简路线为 参保体系→规则类型，便于两步展开到叶子
    await user.click(screen.getByRole('button', { name: '移除维度 医疗类别' }))
    await user.click(screen.getByRole('button', { name: '移除维度 医院等级' }))
    await user.click(screen.getByRole('button', { name: '移除维度 人群' }))

    await user.click(within(tree).getByRole('button', { name: /职工医保/ }))
    await user.click(within(tree).getByRole('button', { name: /支付比例/ }))

    expect(await screen.findByText('统筹基金支付85%，职工支付15%')).toBeInTheDocument()
    // 日期哨兵不渲染：1900/9999 不出现
    expect(screen.queryByText(/1900-01-01/)).not.toBeInTheDocument()
    expect(screen.queryByText(/9999-12-31/)).not.toBeInTheDocument()
  })

  it('维度路线变更后持久化到 localStorage', async () => {
    mockedGetKnowledgeMap.mockResolvedValue(mapFixture)
    const user = userEvent.setup()

    render(<KnowledgeMapPage />)
    await screen.findByText('policy_rules_v2')

    await user.click(screen.getByRole('button', { name: '移除维度 医疗类别' }))

    expect(JSON.parse(window.localStorage.getItem('policy-knowledge-map-route-v1') ?? '[]'))
      .toEqual(['insu_type', 'hosp_lv', 'psn_type', 'rule_type'])
  })

  it('读路径集合为空时显示引导空态', async () => {
    mockedGetKnowledgeMap.mockResolvedValue({
      ...mapFixture,
      rules: [],
      collections: [{ name: 'policy_rules_REL_empty', kind: 'rules', row_count: 0, active: true }],
    })

    render(<KnowledgeMapPage />)

    expect(await screen.findByText('当前读路径集合中没有规则')).toBeInTheDocument()
    expect(screen.getByText(/policy_rules_REL_empty/)).toBeInTheDocument()
  })

  it('动态字段缺失（键不存在）的规则展开到叶子不崩溃（真实 Milvus 行形态）', async () => {
    // 真实接口中动态字段按需存在：缺的键 JSON 里完全没有（undefined），不是空串
    const sparseRule = ruleFixture({
      rule_id: 'rule_sparse',
      insu_type: '居民医保',
      rule_type: '支付比例',
      rule_value: '居民医保支付60%',
      source_text: '居民医保统筹基金支付60%',
    }) as KnowledgeMapRule & Record<string, unknown>
    delete sparseRule.payment_ratio
    delete sparseRule.personal_payment_ratio
    delete sparseRule.deductible_amount
    delete sparseRule.cap_amount
    delete sparseRule.amount_band
    delete sparseRule.amount_band_min
    delete sparseRule.amount_band_max

    mockedGetKnowledgeMap.mockResolvedValue({
      ...mapFixture,
      rules: [ruleFixture({ rule_id: 'rule_1' }), sparseRule],
    })
    const user = userEvent.setup()

    render(<KnowledgeMapPage />)
    const tree = await screen.findByLabelText('知识体系树')

    await user.click(screen.getByRole('button', { name: '移除维度 医疗类别' }))
    await user.click(screen.getByRole('button', { name: '移除维度 医院等级' }))
    await user.click(screen.getByRole('button', { name: '移除维度 人群' }))

    await user.click(within(tree).getByRole('button', { name: /居民医保/ }))
    await user.click(within(tree).getByRole('button', { name: /支付比例/ }))

    expect(await screen.findByText('居民医保支付60%')).toBeInTheDocument()
  })

  it('加载失败显示降级提示，重试后恢复', async () => {
    mockedGetKnowledgeMap.mockRejectedValueOnce(new Error('milvus down'))
    const user = userEvent.setup()

    render(<KnowledgeMapPage />)

    expect(await screen.findByText('知识体系暂不可用（Milvus 连接失败或服务未就绪）')).toBeInTheDocument()
    mockedGetKnowledgeMap.mockResolvedValue(mapFixture)
    await user.click(screen.getByRole('button', { name: /重试/ }))

    expect(await screen.findByText('policy_rules_v2')).toBeInTheDocument()
  })
})
