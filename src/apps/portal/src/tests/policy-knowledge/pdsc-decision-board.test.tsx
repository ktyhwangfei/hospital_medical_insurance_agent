import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { PdscDecisionBoard } from '@/components/policy-knowledge/pdsc-decision-board'
import * as api from '@/lib/policy-knowledge-api'
import type { PdscCluster, PdscDecisionPackage } from '@/lib/policy-knowledge-api'

vi.mock('@/lib/policy-knowledge-api', async () => {
  const actual = await vi.importActual<typeof api>('@/lib/policy-knowledge-api')
  return {
    ...actual,
    listPdscClusters: vi.fn(),
    getPdscDecisionPackage: vi.fn(),
    refreshPdscCluster: vi.fn(),
    decidePdscCluster: vi.fn(),
    adjustPdscCluster: vi.fn(),
    mergePdscClusters: vi.fn(),
    splitPdscCluster: vi.fn(),
    activatePdscCluster: vi.fn(),
    scanPdscSignals: vi.fn(),
  }
})

const CLUSTER: PdscCluster = {
  cluster_id: 'sdc_1',
  normalized_concept: '医疗机构类别',
  concept: '医疗机构类别',
  diagnosis: '政策原文对医疗机构类别（hosp_type）作了明确区分，但结构化结果缺失或只保留了单一值',
  semantic_role: 'dimension',
  semantic_type: 'Enum',
  policy_value_signature: ['三级医院'],
  status: 'pending',
  evidence: [{
    source_ref: 't1',
    evidence_kind: 'policy',
    excerpt: '三级医院住院支付比例',
    doc_id: 'doc_1',
    unit_id: 'unit_1',
    table_name: null,
    field_name: null,
    sample_values: ['三级医院', '二级医院'],
    extracted_values: ['三级医院'],
    rule_ids: [],
  }],
  suggested_merge_cluster_ids: [],
  policy_metric_code: 'zcgz.hosp_type',
  business_metric_code: null,
  cross_validation: {
    counts: { supporting: 2, extending: 1, temporal_variant: 0, conflicting: 1, irrelevant: 1 },
    extension_values: ['社区医院'],
    blocked: true,
    error: null,
    items: [
      { doc_id: 'doc_1', doc_title: '支持文档一', unit_id: 'unit_s', kind: 'supporting', found_values: ['三级医院'], excerpt: '报销比例调整通知' },
      { doc_id: 'doc_2', doc_title: '扩展文档', unit_id: 'unit_e', kind: 'extending', found_values: ['社区医院'] },
      { doc_id: 'doc_4', doc_title: '冲突文档', unit_id: 'unit_c', kind: 'conflicting' },
    ],
  },
  value_alignment: {
    trigger_values: ['三级医院'],
    full_policy_values: ['三级医院', '社区医院'],
    business_standard_values: ['三级医院'],
    database_values: [
      { value: 'A01', definition: null, classification: 'undecidable' },
      { value: '社区医院', definition: '社区卫生服务中心', classification: 'value_extension' },
    ],
    policy_coverage_rate: 0.5,
    db_definition_rate: 0.5,
    alignment_score: 0.4,
    notes: [],
  },
  score: {
    credibility: 0.7, landing_support: 0.4, policy_impact: 0.5, total: 0.545,
    explanations: ['可信度=0.7', '落地支持=0.4', '影响力=0.5'],
  },
  review_note: null,
  updated_at: '2026-08-21T00:00:00Z',
}

const PACKAGE: PdscDecisionPackage = {
  cluster: CLUSTER,
  recommended_policy_metric_code: 'zcgz.hosp_type',
  recommended_business_metric_code: null,
  value_domain_extension_values: ['社区医院'],
  affected_unit_ids: ['unit_1'],
  affected_rule_ids: ['rule_1'],
  affected_skill_usage: 0,
  business_metric_candidates: [{
    metric_code: 'djxx.hosp_type',
    name: '医疗机构类别',
    status: 'published',
    source_object: 'Institution',
    source_field: 'm_institution.H_TYPE',
    value_domain: 'HOSP_TYPE',
    value_overlap: ['三级医院'],
    match_reasons: ['名称匹配度 100%', '值域重合 1 值（三级医院）'],
  }],
  business_field_profile: {
    metric_code: 'djxx.hosp_type',
    source_field: 'm_institution.H_TYPE',
    table_name: 'm_institution',
    field_name: 'H_TYPE',
    non_null_rate: 100,
    distinct_count: 4,
    sample_values: ['三级医院', '社区卫生服务中心'],
    has_description: false,
    last_updated: null,
  },
}

/** 展开卡片详情（详情默认收起） */
async function openDetails() {
  fireEvent.click(screen.getByText(/详情（发现线索原文/))
  await waitFor(() => {
    expect(screen.getByLabelText('发现线索列表')).toBeInTheDocument()
  })
}

beforeEach(() => {
  vi.mocked(api.listPdscClusters).mockResolvedValue([CLUSTER])
  vi.mocked(api.getPdscDecisionPackage).mockResolvedValue(PACKAGE)
  vi.mocked(api.decidePdscCluster).mockResolvedValue(CLUSTER)
  vi.mocked(api.refreshPdscCluster).mockResolvedValue(CLUSTER)
  vi.mocked(api.adjustPdscCluster).mockResolvedValue(CLUSTER)
  vi.mocked(api.mergePdscClusters).mockResolvedValue(CLUSTER)
  vi.mocked(api.splitPdscCluster).mockResolvedValue(CLUSTER)
  vi.mocked(api.activatePdscCluster).mockResolvedValue({
    activation_id: 'act_x', cluster_id: 'sdc_1', status: 'succeeded',
    steps: [], failed_step: null, error: null,
  })
  vi.mocked(api.scanPdscSignals).mockResolvedValue({
    scanned_extractions: 0, intaked_clusters: 0, detectors: [],
  })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('PdscDecisionBoard 一屏多卡决策列表', () => {
  it('首屏展示系统假设、三子分、交叉验证摘要与裁决按钮；详情默认收起', async () => {
    render(<PdscDecisionBoard />)

    await waitFor(() => {
      expect(screen.getByLabelText('决策卡 医疗机构类别')).toBeInTheDocument()
    })

    // 1. 簇标题（概念直接作标题，无冗余前缀）+ 治理价值分（含三个子分，不可只显示总分）
    expect(screen.getByText('医疗机构类别')).toBeInTheDocument()
    expect(screen.getByLabelText('治理价值分')).toBeInTheDocument()
    expect(screen.getByText(/发现可信度 0.70/)).toBeInTheDocument()
    expect(screen.getByText(/落地支持 0.40/)).toBeInTheDocument()
    expect(screen.getByText(/全政策影响 0.50/)).toBeInTheDocument()

    // 区分摘要：政策值内容 + 证据/文档数量（同名字段多簇可区分）
    expect(screen.getByText(/政策值：三级医院 · 1 条证据 · 1 个文档/)).toBeInTheDocument()

    // 概念与诊断分离：首屏可见机器诊断句
    expect(screen.getByLabelText('机器诊断')).toHaveTextContent('作了明确区分')

    // 4. 全政策交叉验证：非零类展示（无关项 1 不出现在首屏）；冲突阻止提示
    expect(screen.getByLabelText('全政策交叉验证')).toBeInTheDocument()
    expect(screen.getByText('冲突 1')).toBeInTheDocument()
    expect(screen.queryByText('无关 1')).not.toBeInTheDocument()
    expect(screen.getByText(/不能一键批准/)).toBeInTheDocument()

    // 裁决按钮首屏可见
    expect(screen.getByText('接受完整方案')).toBeInTheDocument()
    expect(screen.getByText('不是问题（需理由）')).toBeInTheDocument()

    // 详情默认收起：原文、值域对齐、影响范围不在文档中
    expect(screen.queryByLabelText('发现线索列表')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('值域对齐')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('影响范围')).not.toBeInTheDocument()
  })

  it('一发现一卡片，按治理价值分降序排列', async () => {
    const low: PdscCluster = {
      ...CLUSTER,
      cluster_id: 'sdc_low',
      concept: '低分发现',
      score: { credibility: 0.3, landing_support: 0.1, policy_impact: 0.2, total: 0.21, explanations: [] },
    }
    const high: PdscCluster = {
      ...CLUSTER,
      cluster_id: 'sdc_high',
      concept: '高分发现',
      score: { credibility: 0.9, landing_support: 0.8, policy_impact: 0.8, total: 0.85, explanations: [] },
    }
    // 接口返回低分在前，页面必须重排为高分在前
    vi.mocked(api.listPdscClusters).mockResolvedValue([low, high])
    render(<PdscDecisionBoard />)

    await waitFor(() => {
      expect(screen.getByLabelText('决策卡 高分发现')).toBeInTheDocument()
      expect(screen.getByLabelText('决策卡 低分发现')).toBeInTheDocument()
    })
    const cards = screen.getAllByLabelText(/^决策卡 /)
    expect(cards[0]).toHaveAttribute('aria-label', '决策卡 高分发现')
    expect(cards[1]).toHaveAttribute('aria-label', '决策卡 低分发现')
    // 排序依据在页面可见
    expect(screen.getByText(/按治理价值分降序/)).toBeInTheDocument()
  })

  it('展开详情后展示发现线索、值域对齐、影响范围与指标建议', async () => {
    render(<PdscDecisionBoard />)
    await waitFor(() => {
      expect(screen.getByLabelText('决策卡 医疗机构类别')).toBeInTheDocument()
    })
    await openDetails()

    // 2. 发现线索（不使用"原始问题"措辞）；原文命中值 vs 提取落值并排可核实
    expect(screen.getByText(/三级医院住院支付比例/)).toBeInTheDocument()
    expect(screen.getByText('原文命中：三级医院、二级医院')).toBeInTheDocument()
    expect(screen.getByText('提取落值：三级医院')).toBeInTheDocument()

    // 6b. 业务字段画像：非空率/distinct/无释义警示摆上卡片
    expect(screen.getByLabelText('业务字段画像')).toHaveTextContent('distinct 4')
    expect(screen.getByLabelText('业务字段画像')).toHaveTextContent('无中文释义')

    // 7. 值域对齐：逐值 + 不可判断分类
    expect(screen.getByLabelText('值域对齐')).toBeInTheDocument()
    expect(screen.getByText('A01（不可判断）')).toBeInTheDocument()
    expect(screen.getByText('社区医院（值域扩展）')).toBeInTheDocument()

    // 8. 影响范围
    expect(screen.getByLabelText('影响范围')).toBeInTheDocument()
    expect(screen.getByText(/政策单元 1/)).toBeInTheDocument()

    // 交叉验证证据出处：支持/扩展/冲突逐条可见，无关项不罗咥
    expect(screen.getByLabelText('交叉验证证据出处')).toBeInTheDocument()
    expect(screen.getByText(/支持文档一/)).toBeInTheDocument()
    expect(screen.getByText(/冲突文档/)).toBeInTheDocument()

    // 5. 政策指标指向 Milvus 字段
    expect(screen.getByText('zcgz.hosp_type')).toBeInTheDocument()
  })

  it('存在冲突时接受完整方案被后端拒绝并显示错误', async () => {
    vi.mocked(api.decidePdscCluster).mockRejectedValueOnce(
      new Error('存在未解决语义冲突，不能一键批准'),
    )
    render(<PdscDecisionBoard />)
    await waitFor(() => {
      expect(screen.getByText('接受完整方案')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('接受完整方案'))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('不能一键批准')
    })
    expect(api.decidePdscCluster).toHaveBeenCalledWith('sdc_1', 'accept_full_plan', undefined)
  })

  it('不是问题需理由：无理由禁用，填写后调用驳回', async () => {
    render(<PdscDecisionBoard />)
    await waitFor(() => {
      expect(screen.getByText('不是问题（需理由）')).toBeInTheDocument()
    })

    expect(screen.getByText('不是问题（需理由）')).toBeDisabled()
    fireEvent.change(screen.getByLabelText('裁决理由'), {
      target: { value: '文字相似但业务角色不同' },
    })
    fireEvent.click(screen.getByText('不是问题（需理由）'))

    await waitFor(() => {
      expect(api.decidePdscCluster).toHaveBeenCalledWith(
        'sdc_1', 'not_issue', '文字相似但业务角色不同',
      )
    })
  })

  it('绑定业务指标：候选点选后走调整动作（候选为空时回退手填）', async () => {
    render(<PdscDecisionBoard />)
    await waitFor(() => {
      expect(screen.getByLabelText('决策卡 医疗机构类别')).toBeInTheDocument()
    })
    await openDetails()

    // 候选列表默认选中首项，点绑定即调 adjust
    fireEvent.click(screen.getByText('绑定'))

    await waitFor(() => {
      expect(api.adjustPdscCluster).toHaveBeenCalledWith('sdc_1', {
        reason: '绑定业务指标',
        business_metric_code: 'djxx.hosp_type',
      })
    })
  })

  it('候选为空时回退手填编码绑定', async () => {
    vi.mocked(api.getPdscDecisionPackage).mockResolvedValue({
      ...PACKAGE,
      business_metric_candidates: [],
      business_field_profile: null,
    })
    render(<PdscDecisionBoard />)
    await waitFor(() => {
      expect(screen.getByLabelText('决策卡 医疗机构类别')).toBeInTheDocument()
    })
    await openDetails()

    fireEvent.change(screen.getByLabelText('业务指标编码'), {
      target: { value: 'djxx.hosp_type' },
    })
    fireEvent.click(screen.getByText('绑定'))

    await waitFor(() => {
      expect(api.adjustPdscCluster).toHaveBeenCalledWith('sdc_1', {
        reason: '绑定业务指标',
        business_metric_code: 'djxx.hosp_type',
      })
    })
  })

  it('状态标签页：默认只显示待验证，已归档需切换后可见', async () => {
    const archived: PdscCluster = {
      ...CLUSTER,
      cluster_id: 'sdc_archived',
      concept: '已归档发现',
      status: 'not_issue',
    }
    vi.mocked(api.listPdscClusters).mockResolvedValue([CLUSTER, archived])
    render(<PdscDecisionBoard />)

    await waitFor(() => {
      expect(screen.getByLabelText('决策卡 医疗机构类别')).toBeInTheDocument()
    })
    expect(screen.queryByLabelText('决策卡 已归档发现')).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /已归档（1）/ })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: /已归档（1）/ }))
    await waitFor(() => {
      expect(screen.getByLabelText('决策卡 已归档发现')).toBeInTheDocument()
    })
    expect(screen.queryByLabelText('决策卡 医疗机构类别')).not.toBeInTheDocument()
  })

  it('重新验证调用刷新并重新加载', async () => {
    render(<PdscDecisionBoard />)
    await waitFor(() => {
      expect(screen.getByText('重新验证')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('重新验证'))

    await waitFor(() => {
      expect(api.refreshPdscCluster).toHaveBeenCalledWith('sdc_1')
    })
  })

  it('扫描按钮调用扫描接口并展示报告', async () => {
    vi.mocked(api.scanPdscSignals).mockResolvedValue({
      scanned_extractions: 42,
      intaked_clusters: 3,
      detectors: [{ detector: 'value_domain_violation', signals: 5 }],
    })
    render(<PdscDecisionBoard />)
    await waitFor(() => {
      expect(screen.getByText('扫描发现信号')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('扫描发现信号'))

    await waitFor(() => {
      expect(api.scanPdscSignals).toHaveBeenCalled()
      expect(screen.getByText(/扫描 42 条提取，新增 3 簇/)).toBeInTheDocument()
    })
  })

  it('已裁决簇展示激活按钮，失败时展示失败步骤与错误', async () => {
    const accepted = { ...CLUSTER, status: 'accepted' as const }
    vi.mocked(api.listPdscClusters).mockResolvedValue([accepted])
    vi.mocked(api.getPdscDecisionPackage).mockResolvedValue({ ...PACKAGE, cluster: accepted })
    vi.mocked(api.activatePdscCluster).mockResolvedValue({
      activation_id: 'act_1', cluster_id: 'sdc_1', status: 'failed',
      steps: [{ step: 'compile', passed: false, detail: 'stub 编译' }],
      failed_step: 'compile', error: '受影响政策单元编译未通过',
    })
    render(<PdscDecisionBoard />)
    // 已裁决簇在「已裁决」标签页下；等列表加载完（计数 1）再切换
    const decidedTab = await screen.findByRole('tab', { name: /已裁决（1）/ })
    fireEvent.click(decidedTab)
    await waitFor(() => {
      expect(screen.getByText(/激活候选方案/)).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText(/激活候选方案/))

    await waitFor(() => {
      expect(api.activatePdscCluster).toHaveBeenCalledWith('sdc_1')
      expect(screen.getByLabelText('激活结果')).toHaveTextContent('失败（compile）')
      expect(screen.getByLabelText('激活结果')).toHaveTextContent('✗ compile：stub 编译')
    })
  })

  it('勾选证据后可拆分到新簇（需理由）', async () => {
    const multi = {
      ...CLUSTER,
      evidence: [
        ...CLUSTER.evidence,
        { ...CLUSTER.evidence[0], source_ref: 't2' },
      ],
    }
    vi.mocked(api.listPdscClusters).mockResolvedValue([multi])
    vi.mocked(api.getPdscDecisionPackage).mockResolvedValue({ ...PACKAGE, cluster: multi })
    render(<PdscDecisionBoard />)
    await waitFor(() => {
      expect(screen.getByLabelText('决策卡 医疗机构类别')).toBeInTheDocument()
    })
    await openDetails()

    // 无理由时拆分按钮禁用
    fireEvent.click(screen.getByLabelText('选择证据 t1'))
    expect(screen.getByText('移出到新簇（拆分）')).toBeDisabled()

    fireEvent.change(screen.getByLabelText('裁决理由'), {
      target: { value: '按时间拆分' },
    })
    fireEvent.click(screen.getByText('移出到新簇（拆分）'))

    await waitFor(() => {
      expect(api.splitPdscCluster).toHaveBeenCalledWith('sdc_1', ['t1'], '按时间拆分')
    })
  })
})
