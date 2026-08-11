import { describe, expect, it } from 'vitest'

import {
  computePrimaryAction,
  eligibleEvalRun,
  latestActiveRelease,
} from '@/components/skills/skill-primary-action'
import type {
  SkillEvalRunResponse,
  SkillNextAction,
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
  current_stage: 'evaluate',
  priority: 'normal',
  latest_eval_run_id: null,
  candidate_version: null,
  baseline_version: null,
  regression_count: 0,
  required_failure_count: 0,
  linked_draft_id: null,
  linked_draft_status: null,
  waiting_since: '2026-08-05T06:00:00Z',
  next_action: 'run_evaluation',
  next_action_reason: null,
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
  it.each<[
    SkillNextAction,
    ReturnType<typeof computePrimaryAction>,
  ]>([
    ['register_version', { kind: 'navigate', label: '登记当前版本', hint: '当前制品尚未登记或已发生变更', targetTab: 'versions' }],
    ['run_evaluation', { kind: 'run_evaluation', label: '运行候选评测', hint: '使用当前登记版本运行固定评测', targetTab: 'evaluation' }],
    ['create_fix_draft', { kind: 'navigate', label: '创建修复草稿', hint: '从失败证据进入可审阅修改', targetTab: 'development' }],
    ['continue_draft', { kind: 'navigate', label: '继续修改', hint: '打开已关联修复草稿', targetTab: 'development' }],
    ['materialize_draft', { kind: 'navigate', label: '人工物化', hint: '草稿已校验，需要人工确认物化', targetTab: 'development' }],
    ['create_candidate', { kind: 'create_candidate', label: '创建发布候选', hint: '固定评测已通过', targetTab: 'release' }],
    ['request_approval', { kind: 'request_approval', label: '申请复审', hint: '发布候选已就绪', targetTab: 'release' }],
    ['review_approval', { kind: 'navigate', label: '进入人工复审', hint: '禁止创建人自审', targetTab: 'release' }],
    ['activate_test_shadow', { kind: 'activate', label: '激活 Test Shadow', hint: '复审已通过', targetTab: 'release' }],
    ['view_evidence', { kind: 'none', label: '查看运行证据', hint: 'Test Shadow 已激活', targetTab: 'overview' }],
  ])('服务端动作 %s 映射为唯一主动作', (nextAction, expected) => {
    expect(computePrimaryAction(
      { ...baseItem, next_action: nextAction },
      [version],
      [passedRun],
      [release('approved')],
    )).toEqual(expected)
  })

  it.each([undefined, 'future_action'])('对缺失或未知服务端动作 %s 只读降级', (nextAction) => {
    const malformedItem = { ...baseItem, next_action: nextAction } as unknown as SkillWorkbenchItem

    expect(computePrimaryAction(malformedItem, [], [], [])).toEqual({
      kind: 'none',
      label: '治理状态暂不可用',
      hint: '无法识别下一步治理动作，请刷新后重试',
      targetTab: 'overview',
    })
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
