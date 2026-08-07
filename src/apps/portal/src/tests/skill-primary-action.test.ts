import { describe, expect, it } from 'vitest'

import {
  computePrimaryAction,
  eligibleEvalRun,
  latestActiveRelease,
} from '@/components/skills/skill-primary-action'
import type {
  SkillEvalRunResponse,
  SkillReleaseResponse,
  SkillVersionResponse,
  SkillWorkbenchItem,
} from '@/lib/types'

const baseItem: SkillWorkbenchItem = {
  skill_id: 'settlement_explain_skill',
  skill_name: '结算费用解释',
  business_action: 'explain',
  business_object: 'settlement',
  semantic_version: '1.0.0',
  artifact_status: 'registered',
  validation_status: 'passed',
  latest_eval_status: null,
  test_release_status: null,
  test_active_version: null,
  governance_status: 'needs_evaluation',
  attention_reason: 'passed_evaluation_required',
}

const version: SkillVersionResponse = {
  version_id: 'version-1',
  skill_id: 'settlement_explain_skill',
  semantic_version: '1.0.0',
  source_commit: 'main',
  source_path: 'skills/settlement_explain_skill',
  artifact_hash: 'a'.repeat(64),
  manifest_snapshot: {},
  dependency_snapshot: {},
  file_count: 1,
  validation_status: 'passed',
  validation_issues: [],
  created_by: 'portal-user',
  created_at: '2026-08-05T06:00:00Z',
}

const passedRun: SkillEvalRunResponse = {
  run_id: 'run-1',
  skill_id: 'settlement_explain_skill',
  version_id: 'version-1',
  baseline_version_id: null,
  suite_version: 1,
  config_hash: 'c'.repeat(64),
  routing_manifest_hash: 'd'.repeat(64),
  status: 'passed',
  metrics: {
    total: 5,
    passed: 5,
    required_passed: 5,
    required_total: 5,
    top1_accuracy: 1,
    baseline_top1_accuracy: 1,
    regression_count: 0,
    new_false_takeover_count: 0,
    gate_passed: true,
  },
  results: [],
  case_snapshots: [],
  created_at: '2026-08-05T06:10:00Z',
  created_by: 'portal-user',
}

function release(status: SkillReleaseResponse['status']): SkillReleaseResponse {
  return {
    release_id: 'release-1',
    skill_id: 'settlement_explain_skill',
    version_id: 'version-1',
    environment: 'test',
    status,
    baseline_release_id: null,
    eval_run_id: 'run-1',
    artifact_hash: 'a'.repeat(64),
    config_hash: 'b'.repeat(64),
    rollout_percent: 0,
    runtime_mode: 'shadow',
    revision: 3,
    created_by: 'portal-user',
    created_at: '2026-08-05T06:00:00Z',
    activated_at: null,
    retired_at: null,
    approval: null,
  }
}

describe('computePrimaryAction', () => {
  it('已激活 → 完成（无按钮）', () => {
    const action = computePrimaryAction(
      { ...baseItem, test_release_status: 'active' },
      [version],
      [passedRun],
      [release('active')],
    )
    expect(action.kind).toBe('none')
    expect(action.label).toBe('Test Shadow 已激活')
  })

  it('已登记、未评测 → 运行候选评测', () => {
    const action = computePrimaryAction(baseItem, [version], [], [])
    expect(action.kind).toBe('run_evaluation')
    expect(action.targetTab).toBe('evaluation')
  })

  it('有通过门禁的评测、无候选 → 创建候选', () => {
    const action = computePrimaryAction(baseItem, [version], [passedRun], [])
    expect(action.kind).toBe('create_candidate')
  })

  it('候选版 → 申请审批（发布状态机优先）', () => {
    const action = computePrimaryAction(baseItem, [version], [passedRun], [release('candidate')])
    expect(action.kind).toBe('request_approval')
  })

  it('待审批 → 人工审批通过', () => {
    const action = computePrimaryAction(baseItem, [version], [passedRun], [release('approval_pending')])
    expect(action.kind).toBe('approve')
    expect(action.label).toBe('人工审批通过')
  })

  it('审批通过 → 激活 Test Shadow', () => {
    const action = computePrimaryAction(baseItem, [version], [passedRun], [release('approved')])
    expect(action.kind).toBe('activate')
  })

  it('门禁失败 → 跳转看证据', () => {
    const action = computePrimaryAction(
      { ...baseItem, governance_status: 'gate_failed' },
      [version],
      [],
      [],
    )
    expect(action.kind).toBe('navigate')
    expect(action.targetTab).toBe('evaluation')
  })

  it('未登记制品 → 去版本页', () => {
    const action = computePrimaryAction(
      { ...baseItem, artifact_status: 'changed', validation_status: 'pending' },
      [],
      [],
      [],
    )
    expect(action.kind).toBe('navigate')
    expect(action.targetTab).toBe('versions')
  })

  it('退役发布不参与状态机（视为无候选）', () => {
    const action = computePrimaryAction(baseItem, [version], [passedRun], [release('retired')])
    expect(action.kind).toBe('create_candidate')
  })
})

describe('helpers', () => {
  it('latestActiveRelease 跳过 retired', () => {
    expect(latestActiveRelease([release('retired'), release('candidate')])?.status).toBe('candidate')
    expect(latestActiveRelease([release('retired')])).toBeUndefined()
  })

  it('eligibleEvalRun 要求 passed + gate_passed + 版本匹配', () => {
    expect(eligibleEvalRun([passedRun], [version])?.run_id).toBe('run-1')
    const failedGate = { ...passedRun, metrics: { ...passedRun.metrics, gate_passed: false } }
    expect(eligibleEvalRun([failedGate], [version])).toBeUndefined()
    const otherVersion = { ...passedRun, version_id: 'other' }
    expect(eligibleEvalRun([otherVersion], [version])).toBeUndefined()
  })
})
