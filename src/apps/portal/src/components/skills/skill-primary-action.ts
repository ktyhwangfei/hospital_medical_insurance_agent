import type {
  SkillEvalRunResponse,
  SkillNextAction,
  SkillReleaseResponse,
  SkillVersionResponse,
  SkillWorkbenchItem,
  SkillWorkbenchTab,
} from '@/lib/types'

// 把服务端给出的"下一个治理动作"映射为工作台顶层一键操作。

export type PrimaryActionKind =
  | 'run_evaluation' // 运行候选评测
  | 'create_candidate' // 从通过评测创建发布候选
  | 'request_approval' // 候选 → 申请审批
  | 'approve' // 待审批 → 信息科审批通过
  | 'activate' // 审批通过 → 激活 Test Shadow
  | 'navigate' // 仅跳转到某个 Tab（门禁失败看证据 / 未登记去版本页）
  | 'none' // 已激活，无待办

export interface PrimaryAction {
  kind: PrimaryActionKind
  label: string
  hint: string
  /** navigate / 完成态可视化用 */
  targetTab?: SkillWorkbenchTab
}

const UNAVAILABLE_ACTION: Readonly<PrimaryAction> = Object.freeze({
  kind: 'none',
  label: '治理状态暂不可用',
  hint: '无法识别下一步治理动作，请刷新后重试',
  targetTab: 'overview',
})

const PRIMARY_ACTIONS: Record<SkillNextAction, PrimaryAction> = {
  register_version: {
    kind: 'navigate',
    label: '登记当前版本',
    hint: '当前制品尚未登记或已发生变更',
    targetTab: 'versions',
  },
  run_evaluation: {
    kind: 'run_evaluation',
    label: '运行候选评测',
    hint: '使用当前登记版本运行固定评测',
    targetTab: 'evaluation',
  },
  create_fix_draft: {
    kind: 'navigate',
    label: '创建修复草稿',
    hint: '从失败证据进入可审阅修改',
    targetTab: 'development',
  },
  continue_draft: {
    kind: 'navigate',
    label: '继续修改',
    hint: '打开已关联修复草稿',
    targetTab: 'development',
  },
  materialize_draft: {
    kind: 'navigate',
    label: '人工物化',
    hint: '草稿已校验，需要人工确认物化',
    targetTab: 'development',
  },
  create_candidate: {
    kind: 'create_candidate',
    label: '创建发布候选',
    hint: '固定评测已通过',
    targetTab: 'release',
  },
  request_approval: {
    kind: 'request_approval',
    label: '申请复审',
    hint: '发布候选已就绪',
    targetTab: 'release',
  },
  review_approval: {
    kind: 'navigate',
    label: '进入人工复审',
    hint: '禁止创建人自审',
    targetTab: 'release',
  },
  activate_test_shadow: {
    kind: 'activate',
    label: '激活 Test Shadow',
    hint: '复审已通过',
    targetTab: 'release',
  },
  view_evidence: {
    kind: 'none',
    label: '查看运行证据',
    hint: 'Test Shadow 已激活',
    targetTab: 'overview',
  },
}

/** 最新一条未退役的发布记录（发布状态机的当前态） */
export function latestActiveRelease(
  releases: SkillReleaseResponse[],
): SkillReleaseResponse | undefined {
  return releases.find((release) => release.status !== 'retired')
}

/** 通过门禁、且版本匹配当前登记版本评测运行（创建候选的前提） */
export function eligibleEvalRun(
  evalRuns: SkillEvalRunResponse[],
  versions: SkillVersionResponse[],
): SkillEvalRunResponse | undefined {
  return evalRuns.find(
    (run) =>
      run.status === 'passed' &&
      run.metrics.gate_passed &&
      versions.some((version) => version.version_id === run.version_id),
  )
}

export function computePrimaryAction(
  item: SkillWorkbenchItem,
  _versions: SkillVersionResponse[],
  _evalRuns: SkillEvalRunResponse[],
  _releases: SkillReleaseResponse[],
): PrimaryAction {
  void _versions; void _evalRuns; void _releases
  if (item.next_action === 'view_evidence' && item.test_release_status !== 'active') {
    return item.next_action_reason
      ? Object.freeze({ ...UNAVAILABLE_ACTION, hint: item.next_action_reason })
      : UNAVAILABLE_ACTION
  }
  return PRIMARY_ACTIONS[item.next_action] ?? UNAVAILABLE_ACTION
}
