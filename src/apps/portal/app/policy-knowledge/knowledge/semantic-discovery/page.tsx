import { PdscDecisionBoard } from '@/components/policy-knowledge/pdsc-decision-board'
import { RuleGovernanceWizard } from '@/components/policy-knowledge/rule-governance-wizard'
import { WorkspaceNav } from '../workspace-nav'

// 规则治理向导仅在规则追溯"发起结构治理"深链（release_id + rule_ids）进入时渲染，
// 默认视图只保留语义发现决策列表。
export default async function SemanticDiscoveryPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}) {
  const params = await searchParams
  const governanceDeepLink = Boolean(params.release_id && params.rule_ids)

  return (
    <div className="space-y-4">
      <WorkspaceNav />
      <header className="space-y-1">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">语义发现（政策—数据协同）</h1>
        <p className="text-sm text-slate-600">
          机器发现的政策结构线索经全政策交叉验证后聚合为语义发现，按治理价值分排序，逐卡完成建模裁决。
        </p>
      </header>
      {governanceDeepLink && (
        <section className="space-y-1">
          <h2 className="text-base font-semibold text-slate-900">规则治理向导</h2>
          <RuleGovernanceWizard />
        </section>
      )}
      <PdscDecisionBoard />
    </div>
  )
}
