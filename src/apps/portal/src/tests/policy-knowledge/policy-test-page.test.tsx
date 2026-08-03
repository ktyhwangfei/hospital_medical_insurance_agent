import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import PolicyKnowledgeTestPage from '../../../app/policy-knowledge/test/page'

vi.mock('@/lib/policy-knowledge-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/policy-knowledge-api')>()
  const candidate = { release_id: 'candidate', status: 'passed', facts_collection: 'facts_candidate', rules_collection: 'rules_candidate', contract_version: '2', case_set_version: 1, config_hash: 'cfg', quality_score: 0.9, consistency_score: 1 }
  return {
    ...actual,
    listReleases: vi.fn().mockResolvedValue([candidate]),
    listTestCases: vi.fn().mockResolvedValue([]),
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
})
