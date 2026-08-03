import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { QualityDashboard } from '@/components/policy-knowledge/quality-dashboard'
import type { KnowledgeRelease, QualityRun } from '@/lib/policy-knowledge-api'

const release = (release_id: string, status: KnowledgeRelease['status']): KnowledgeRelease => ({
  release_id, status, facts_collection: `facts_${release_id}`, rules_collection: `rules_${release_id}`,
  contract_version: '2', case_set_version: 1, config_hash: 'cfg_1',
  quality_score: status === 'passed' ? 0.95 : 0.7, consistency_score: status === 'passed' ? 1 : 0.8,
})

const run: QualityRun = {
  run_id: 'run_1', release_id: 'candidate_passed', baseline_release_id: 'baseline',
  status: 'passed', candidate_score: 0.95, baseline_score: 0.8,
  consistency_score: 1, blocked_reasons: [], repeat_count: 3,
}

describe('QualityDashboard', () => {
  afterEach(cleanup)

  it('visualizes same-set comparison and requires a separate human publish click', () => {
    const promote = vi.fn()
    render(<QualityDashboard releases={[release('candidate_passed', 'passed')]} activeRelease={release('baseline', 'active')} latestRun={run} onRun={vi.fn()} onPromote={promote} />)

    expect(screen.getByText('95%')).toBeInTheDocument()
    expect(screen.getByText('80%')).toBeInTheDocument()
    expect(screen.getByText('测试通过，待人工发布')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '人工发布候选版本' }))
    expect(promote).toHaveBeenCalledWith('candidate_passed')
  })

  it('blocks publish when quality gate failed', () => {
    render(<QualityDashboard releases={[release('candidate_failed', 'failed')]} activeRelease={release('baseline', 'active')} latestRun={{ ...run, status: 'failed', release_id: 'candidate_failed', blocked_reasons: ['候选质量必须严格高于当前版本'] }} onRun={vi.fn()} onPromote={vi.fn()} />)

    expect(screen.getByRole('button', { name: '人工发布候选版本' })).toBeDisabled()
    expect(screen.getByText(/候选质量必须严格高于当前版本/)).toBeInTheDocument()
  })

  it('shows per-case failures and exposes rollback only for retired releases', () => {
    const rollback = vi.fn()
    render(<QualityDashboard releases={[release('candidate_failed', 'failed'), release('previous', 'retired')]} activeRelease={release('baseline', 'active')} latestRun={{ ...run, status: 'failed', release_id: 'candidate_failed', blocked_reasons: ['必测用例未全部通过'] }} caseResults={[{ run_id: 'run_1', target: 'candidate', case_id: 'case_1', repeat_index: 0, result_knowledge_ids: [], score: 0, passed: false, diagnostics: { recall: 0 } }]} onRun={vi.fn()} onPromote={vi.fn()} onRollback={rollback} />)

    expect(screen.getAllByText(/case_1/)).toHaveLength(2)
    expect(screen.getByText(/候选.*→.*基线/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '回滚到 previous' }))
    expect(rollback).toHaveBeenCalledWith('previous')
  })
})
