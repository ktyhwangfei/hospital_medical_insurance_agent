import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import PolicyKnowledgeTestPage from '../../../app/policy-knowledge/test/page'

vi.mock('@/lib/policy-qa-feedback', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/policy-qa-feedback')>()
  return {
    ...actual,
    verifyPolicyQAAnswer: vi.fn(),
  }
})

vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>()
  return {
    ...actual,
    fetchQAHistory: vi.fn().mockResolvedValue({ items: [] }),
  }
})

vi.mock('@/lib/policy-knowledge-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/policy-knowledge-api')>()
  const candidate = { release_id: 'candidate', status: 'passed', facts_collection: 'facts_candidate', rules_collection: 'rules_candidate', contract_version: '2', case_set_version: 1, config_hash: 'cfg', quality_score: 0.9, consistency_score: 1 }
  return {
    ...actual,
    listReleases: vi.fn().mockResolvedValue([candidate]),
    listTestCases: vi.fn().mockResolvedValue([{ case_id: 'case_1', name: '经典用例', query: '住院比例', mode: 'hybrid', expected_knowledge_ids: ['kn_1'], filters: { psn_type: '职工' }, required: false, active: true, case_set_version: 1 }]),
    saveTestCase: vi.fn().mockResolvedValue({}),
    createRelease: vi.fn().mockResolvedValue(candidate),
    buildRelease: vi.fn().mockResolvedValue(candidate),
    getActiveRelease: vi.fn().mockResolvedValue({ ...candidate, release_id: 'baseline', status: 'active' }),
    getLatestReleaseQuality: vi.fn().mockResolvedValue({
      run: { run_id: 'run_latest', release_id: 'candidate', baseline_release_id: 'baseline', case_set_version: 2, config_hash: 'cfg', repeat_count: 3, status: 'failed', candidate_score: 0.7, baseline_score: 0.8, consistency_score: 0.5, blocked_reasons: ['重复运行一致性低于门槛'] },
      case_results: [{ run_id: 'run_latest', target: 'candidate', case_id: 'case_1', repeat_index: 0, result_knowledge_ids: ['kn_b', 'kn_a'], score: 0.5, passed: false, diagnostics: { rank_score: 0.5 } }],
    }),
  }
})

describe('PolicyKnowledgeTestPage', () => {
  afterEach(cleanup)

  it('restores the latest quality run and case diff after refresh', async () => {
    render(<PolicyKnowledgeTestPage />)

    await waitFor(() => expect(screen.getByText('质量门禁未通过')).toBeInTheDocument())
    expect(screen.getByText(/重复运行一致性低于门槛/)).toBeInTheDocument()
    expect(screen.getAllByText(/case_1/)).toHaveLength(2)
  })

  it('preserves mode filters and required when editing a test case', async () => {
    const api = await import('@/lib/policy-knowledge-api')
    render(<PolicyKnowledgeTestPage />)
    fireEvent.click(await screen.findByRole('button', { name: '编辑' }))

    expect(screen.getByLabelText('用例模式')).toHaveValue('hybrid')
    expect(screen.getByLabelText('过滤条件 JSON')).toHaveValue('{\n  "psn_type": "职工"\n}')
    expect(screen.getByLabelText('必测用例')).not.toBeChecked()
    fireEvent.click(screen.getByRole('button', { name: '保存用例修改' }))

    await waitFor(() => expect(api.saveTestCase).toHaveBeenCalledWith(expect.objectContaining({
      case_id: 'case_1', mode: 'hybrid', filters: { psn_type: '职工' }, required: false,
    })))
  })

  it('renders the answer verification panel entry on the test page', async () => {
    render(<PolicyKnowledgeTestPage />)
    await waitFor(() => expect(screen.getByText('答案验证')).toBeInTheDocument())
    expect(screen.getByText('对政策问答回答做引用/结论/计算/覆盖五维交叉验证')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '验证' })).toBeInTheDocument()
  })
})
