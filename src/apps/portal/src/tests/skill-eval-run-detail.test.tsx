import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import RunDetail from '@/components/skills/skill-eval-run-detail'
import type { SkillEvalRunResponse } from '@/lib/types'

const mocks = vi.hoisted(() => ({
  clusters: vi.fn(),
  improve: vi.fn(),
  retest: vi.fn(),
}))

vi.mock('@/lib/api-client', () => ({
  listSkillEvalFailureClusters: (...args: unknown[]) => mocks.clusters(...args),
  createSkillEvalImprovementTask: (...args: unknown[]) => mocks.improve(...args),
  retestSkillEvalRun: (...args: unknown[]) => mocks.retest(...args),
}))

afterEach(cleanup)

beforeEach(() => {
  vi.clearAllMocks()
  mocks.clusters.mockResolvedValue([])
})

const displayName = (id: string | null | undefined) => (id ? `技能(${id})` : '—')

function makeRun(overrides: Partial<SkillEvalRunResponse> = {}): SkillEvalRunResponse {
  return {
    run_id: 'run-1',
    skill_id: 'skill-a',
    version_id: 'v1',
    baseline_version_id: null,
    suite_version: 3,
    config_hash: 'a'.repeat(64),
    routing_manifest_hash: 'b'.repeat(64),
    status: 'passed',
    metrics: {
      total: 4,
      passed: 3,
      required_total: 2,
      required_passed: 2,
      top1_accuracy: 0.75,
      baseline_top1_accuracy: 0.5,
      regression_count: 1,
      new_false_takeover_count: 0,
      gate_passed: true,
    },
    results: [
      {
        case_id: 'case-1',
        expected_skill_id: 'skill-a',
        candidate_skill_id: 'skill-a',
        baseline_skill_id: 'skill-a',
        candidate_confidence: 0.9,
        baseline_confidence: 0.8,
        candidate_passed: true,
        baseline_passed: true,
        required: true,
        diff: 'unchanged_pass',
        candidate_keywords: [],
        baseline_keywords: [],
      },
      {
        case_id: 'case-2',
        candidate_skill_id: 'skill-b',
        baseline_skill_id: 'skill-a',
        candidate_confidence: 0.4,
        baseline_confidence: 0.8,
        candidate_passed: false,
        baseline_passed: true,
        required: true,
        diff: 'new_failure',
        candidate_keywords: [],
        baseline_keywords: [],
      },
    ],
    case_snapshots: [],
    dataset_version_id: 'EVD_1',
    benchmark_id: 'EVB_1',
    task_results: [],
    trajectory_summary: [],
    failure_attributions: [],
    failure_clusters: [],
    dimension_summary: [],
    created_by: 'tester',
    created_at: '2026-08-10T00:00:00Z',
    completed_at: '2026-08-10T00:00:01Z',
    ...overrides,
  }
}

describe('RunDetail — 门禁指标与逐用例差异', () => {
  it('渲染 metrics 卡片', () => {
    render(<RunDetail run={makeRun()} displayName={displayName} />)
    expect(screen.getByText('75%')).toBeInTheDocument() // top1
    expect(screen.getByText('50%')).toBeInTheDocument() // baseline top1
    expect(screen.getByText('2/2')).toBeInTheDocument() // 必测通过
    expect(screen.getByText('v3')).toBeInTheDocument() // 测试集版本
  })

  it('渲染逐用例路由差异表（diff 标签 + 候选/基线技能）', () => {
    render(<RunDetail run={makeRun()} displayName={displayName} />)
    expect(screen.getByText('case-1')).toBeInTheDocument()
    expect(screen.getByText('持续通过')).toBeInTheDocument()
    expect(screen.getByText('新增失败')).toBeInTheDocument()
    expect(screen.getAllByText('技能(skill-a)').length).toBeGreaterThan(0)
    expect(screen.getByText('技能(skill-b)')).toBeInTheDocument()
  })

  it('回归数 > 0 时标红', () => {
    const { container } = render(<RunDetail run={makeRun()} displayName={displayName} />)
    expect(container.querySelector('.text-rose-700')).not.toBeNull()
  })

  it('门禁未过时显示未过并标红', () => {
    const run = makeRun({
      status: 'failed',
      metrics: {
        total: 4,
        passed: 2,
        required_total: 2,
        required_passed: 1,
        top1_accuracy: 0.5,
        baseline_top1_accuracy: 0.5,
        regression_count: 0,
        new_false_takeover_count: 0,
        gate_passed: false,
      },
    })
    render(<RunDetail run={run} displayName={displayName} />)
    expect(screen.getByText('未过')).toBeInTheDocument()
  })

  it('results 为空时提示无结果', () => {
    render(<RunDetail run={makeRun({ results: [] })} displayName={displayName} />)
    expect(screen.getByText('无逐用例结果')).toBeInTheDocument()
  })

  it('按维度展示失败簇并创建改进任务', async () => {
    const cluster = {
      cluster_id: 'EVC_1',
      cluster_key: 'calculation:key',
      owner_type: 'agent' as const,
      stage: 'calculation' as const,
      failure_code: 'CALCULATION_TOLERANCE_EXCEEDED',
      dimension: 'calculation' as const,
      target_skill_id: 'skill-a',
      task_ids: ['task-1'],
      representative_task_id: 'task-1',
      business_tags: ['outpatient'],
    }
    mocks.clusters.mockResolvedValue([{ cluster, improvement_tasks: [] }])
    mocks.improve.mockResolvedValue({
      task_id: 'tsk_1',
      run_id: 'run-1',
      cluster_id: 'EVC_1',
      status: 'pending',
      description: '修复金额计算',
    })
    render(<RunDetail run={makeRun({
      status: 'failed',
      failure_clusters: [cluster],
      dimension_summary: [{
        dimension: 'calculation',
        total: 1,
        passed: 0,
        failed: 1,
        blocked: 0,
        needs_review: 0,
        invalid_dataset: 0,
      }],
    })} displayName={displayName} />)

    expect(screen.getByText('计算')).toBeVisible()
    expect(await screen.findByText('CALCULATION_TOLERANCE_EXCEEDED')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '创建改进任务' }))
    await waitFor(() => expect(mocks.improve).toHaveBeenCalledWith('EVC_1'))
    expect(await screen.findByText('改进任务 tsk_1')).toBeVisible()
  })
})
