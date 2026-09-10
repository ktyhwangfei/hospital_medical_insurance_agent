import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { GoldenCaseCoverage } from '../../components/policy-knowledge/golden-case-coverage'
import type {
  PolicyTestCase,
  QualityCaseResult,
  WorkbenchDocumentSummary,
} from '../../lib/policy-knowledge-api'

const documents: WorkbenchDocumentSummary[] = [
  { doc_id: 'doc_a', doc_title: '本市城镇职工医疗保险待遇', approved_unit_count: 10, knowledge_count: 20 },
  { doc_id: 'doc_b', doc_title: '城乡居民基本医疗保险办法', approved_unit_count: 8, knowledge_count: 12 },
  { doc_id: 'doc_c', doc_title: '用药管理暂行办法', approved_unit_count: 5, knowledge_count: 6 },
]

function goldenCase(overrides: Partial<PolicyTestCase>): PolicyTestCase {
  return {
    case_id: 'golden_doc_a_1',
    name: '黄金·待遇·在职门诊',
    query: '在职职工门诊2万元以下医院报销比例是多少',
    mode: 'precise',
    expected_knowledge_ids: ['rule_1'],
    filters: { psn_type: '在职职工', doc_id: 'doc_a' },
    required: true,
    active: true,
    case_set_version: 1,
    ...overrides,
  }
}

function caseResult(overrides: Partial<QualityCaseResult>): QualityCaseResult {
  return {
    run_id: 'run_1',
    target: 'candidate',
    case_id: 'golden_doc_a_1',
    repeat_index: 0,
    result_knowledge_ids: ['rule_1'],
    score: 1,
    passed: true,
    diagnostics: {},
    ...overrides,
  }
}

describe('GoldenCaseCoverage', () => {
  it('groups golden cases by document and shows coverage stats', () => {
    render(
      <GoldenCaseCoverage
        cases={[
          goldenCase({}),
          goldenCase({ case_id: 'golden_doc_a_2', query: '在职住院一级报销比例' }),
          goldenCase({ case_id: 'golden_doc_b_1', query: '居民门诊一级报销比例', filters: { doc_id: 'doc_b' } }),
          // 非黄金用例与普通用例不参与分组
          goldenCase({ case_id: 'case_normal_1', query: '普通用例', filters: {} }),
          // 停用的黄金用例不计入覆盖
          goldenCase({ case_id: 'golden_doc_c_1', active: false, filters: { doc_id: 'doc_c' } }),
        ]}
        documents={documents}
        caseResults={[]}
      />,
    )

    expect(screen.getByTestId('golden-case-coverage')).toBeInTheDocument()
    expect(screen.getByText(/3 条用例 · 覆盖 2\/3 篇文档/)).toBeInTheDocument()
    // 文档标题分组
    expect(screen.getByText('本市城镇职工医疗保险待遇')).toBeInTheDocument()
    expect(screen.getByText('城乡居民基本医疗保险办法')).toBeInTheDocument()
    // 未覆盖文档提示
    expect(screen.getByText(/未覆盖文档（1 篇）/)).toBeInTheDocument()
    expect(screen.getByText(/用药管理暂行办法/)).toBeInTheDocument()
  })

  it('shows latest run pass/fail badge per case', () => {
    render(
      <GoldenCaseCoverage
        cases={[
          goldenCase({}),
          goldenCase({ case_id: 'golden_doc_a_2', query: '退休住院一级报销比例' }),
        ]}
        documents={documents}
        caseResults={[
          caseResult({}),
          caseResult({ case_id: 'golden_doc_a_2', passed: false, result_knowledge_ids: [] }),
        ]}
      />,
    )

    expect(screen.getByText('通过')).toBeInTheDocument()
    expect(screen.getByText('未通过')).toBeInTheDocument()
  })

  it('marks cases without run results as 未运行', () => {
    render(
      <GoldenCaseCoverage
        cases={[goldenCase({})]}
        documents={documents}
        caseResults={[]}
      />,
    )
    expect(screen.getAllByText('未运行').length).toBeGreaterThan(0)
  })
})
