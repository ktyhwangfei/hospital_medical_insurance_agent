import type {
  SkillEvalRunResponse,
  SkillReleaseResponse,
  SkillVersionResponse,
  SkillWorkbenchItem,
  SkillWorkbenchTab,
} from '@/lib/types'

// 把"下一个治理动作"从发布/评测 Tab 里提出来，作为工作台顶层一键操作。
// 纯函数：只依据已加载的证据数据推导，无副作用，便于单测。

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

const DONE: PrimaryAction = {
  kind: 'none',
  label: 'Test Shadow 已激活',
  hint: '当前版本已在 Test 环境激活，可用于治理验证',
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

/**
 * 推导当前 Skill 的下一个主治理动作。
 * 优先级：已激活(完成) → 发布状态机(候选/待审批/审批通过) → 门禁失败(看证据)
 *        → 有通过评测(创建候选) → 已登记(运行评测) → 未登记(去版本页)
 */
export function computePrimaryAction(
  item: SkillWorkbenchItem,
  versions: SkillVersionResponse[],
  evalRuns: SkillEvalRunResponse[],
  releases: SkillReleaseResponse[],
): PrimaryAction {
  if (item.test_release_status === 'active') return DONE

  const registered =
    item.artifact_status === 'registered' && item.validation_status === 'passed'
  const release = latestActiveRelease(releases)

  // 发布状态机优先：已有候选在流，沿状态推进
  if (release) {
    if (release.status === 'candidate') {
      return {
        kind: 'request_approval',
        label: '申请审批',
        hint: '候选版已就绪，提交信息科审批后即可激活',
        targetTab: 'release',
      }
    }
    if (release.status === 'approval_pending') {
      return {
        kind: 'approve',
        label: '人工审批通过',
        hint: '等待信息科角色审批',
        targetTab: 'release',
      }
    }
    if (release.status === 'approved') {
      return {
        kind: 'activate',
        label: '激活 Test Shadow',
        hint: '审批通过，可激活到 Test 影子流量',
        targetTab: 'release',
      }
    }
    // active 已在上方返回；retired 被 latestActiveRelease 过滤
  }

  // 门禁失败 → 先看回归证据
  if (item.governance_status === 'gate_failed') {
    return {
      kind: 'navigate',
      label: '查看评测回归证据',
      hint: '最近评测未通过门禁，请检查回归用例',
      targetTab: 'evaluation',
    }
  }

  // 有通过门禁的评测、尚无候选 → 创建候选
  if (eligibleEvalRun(evalRuns, versions)) {
    return {
      kind: 'create_candidate',
      label: '从通过评测创建候选',
      hint: '评测已通过门禁，可创建 Test 发布候选',
      targetTab: 'release',
    }
  }

  // 已登记但未评测 → 运行评测
  if (registered) {
    return {
      kind: 'run_evaluation',
      label: '运行候选评测',
      hint: '需要先通过当前版本的固定评测门禁',
      targetTab: 'evaluation',
    }
  }

  // 未登记 → 去版本页登记制品
  return {
    kind: 'navigate',
    label: '登记制品版本',
    hint: '当前制品未登记或未通过校验，先在「版本」页登记',
    targetTab: 'versions',
  }
}
