import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RuleGovernanceWizard } from '@/components/policy-knowledge/rule-governance-wizard'
import {
  createRuleGovernanceDraft,
  diagnoseRuleGovernance,
  type RuleGovernanceDiagnosis,
} from '@/lib/policy-knowledge-api'


vi.mock('@/lib/policy-knowledge-api', () => ({
  createRuleGovernanceDraft: vi.fn(),
  diagnoseRuleGovernance: vi.fn(),
}))

const diagnosis: RuleGovernanceDiagnosis = {
  diagnosis_id: 'diagnosis_1',
  fingerprint: 'fingerprint_1',
  release_id: 'REL_202608182',
  rules: [
    {
      rule_id: 'rule_69fc18433e6a7364',
      release_id: 'REL_202608182',
      compile_run_id: 'run_1',
      extraction_id: 'ext_1',
      unit_id: 'unit_1',
      doc_id: 'doc_1',
      subject: '门诊报销比例',
      conditions: { hosp_lv: '一级' },
      result: { ratio: 0.9 },
      excerpt: '在本市社区卫生服务机构就医。',
    },
  ],
  items: [
    {
      issue_id: 'issue_inst',
      issue_type: 'institution_category',
      title: '医疗机构类别被误提取为医院等级',
      rule_ids: ['rule_69fc18433e6a7364'],
      current_structure_summary: 'hosp_lv=一级',
      problem: '政策区分社区与非社区定点医疗机构。',
      missing_concept: '医疗机构类别',
      candidate_values: ['社区卫生服务机构', '其他定点医疗机构'],
      recommended_decision: 'add_and_bind',
      recommended_reason: 'H_TYPE 表达医疗机构类别，H_LEVEL 仅表达医院等级。',
      proposed_changes: '清除 hosp_lv=一级；新增 institution_category。',
      policy_evidence: [],
      database_evidence: [
        {
          source_ref: 'database:m_institution.H_TYPE',
          evidence_kind: 'database',
          evidence_grade: 'strong',
          excerpt: '医疗机构类型',
          occurrence_count: 1,
          table_name: 'm_institution',
          field_name: 'H_TYPE',
          sample_values: ['01', '02'],
          match_reasons: ['字段业务角色直接表达医疗机构类别'],
          rejection_reasons: [],
        },
        {
          source_ref: 'database:m_institution.H_LEVEL',
          evidence_kind: 'database',
          evidence_grade: 'rejected',
          excerpt: '医院等级',
          occurrence_count: 1,
          table_name: 'm_institution',
          field_name: 'H_LEVEL',
          sample_values: ['一级', '二级'],
          match_reasons: [],
          rejection_reasons: ['医院等级不是医疗机构类别'],
        },
      ],
      uncertainties: [],
    },
  ],
  uncertainties: [],
}


describe('RuleGovernanceWizard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.history.replaceState(
      {},
      '',
      '/policy-knowledge/knowledge/semantic-discovery?release_id=REL_202608182&rule_ids=rule_69fc18433e6a7364',
    )
    vi.mocked(diagnoseRuleGovernance).mockResolvedValue(diagnosis)
    vi.mocked(createRuleGovernanceDraft).mockResolvedValue({
      proposal_id: 'proposal_1',
      status: 'proposed',
      proposal_type: 'rule_governance',
      governance_change_plan: {
        release_id: 'REL_202608182',
        proposed_changes: '清除 hosp_lv=一级；新增 institution_category。',
      },
    } as never)
  })

  it('从规则深链完成诊断、证据检查和未发布草稿创建', async () => {
    render(<RuleGovernanceWizard />)

    expect(await screen.findByText('医疗机构类别被误提取为医院等级')).toBeInTheDocument()
    expect(screen.getByText(/问题发生版本：REL_202608182/)).toBeInTheDocument()
    expect(screen.queryByText('rule_69fc18433e6a7364')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '查看数据库证据' }))
    expect(screen.getByText('医疗机构类型')).toBeInTheDocument()
    expect(screen.getByText('m_institution.H_TYPE')).toBeInTheDocument()
    expect(screen.getByText('医院等级不是医疗机构类别')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '查看建模建议' }))
    expect(screen.getAllByText('新增政策指标并绑定数据库字段')).not.toHaveLength(0)
    expect(screen.getAllByText(/历史版本保持不变/)).not.toHaveLength(0)

    fireEvent.click(screen.getByRole('button', { name: '确认并生成治理草稿' }))

    await waitFor(() => expect(createRuleGovernanceDraft).toHaveBeenCalledWith({
      release_id: 'REL_202608182',
      rule_ids: ['rule_69fc18433e6a7364'],
      issue_id: 'issue_inst',
      decision: 'add_and_bind',
      review_note: undefined,
    }))
    expect(await screen.findByText('治理草稿已生成')).toBeInTheDocument()
    expect(screen.getByText('未执行')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /发布/ })).not.toBeInTheDocument()
  })
})
