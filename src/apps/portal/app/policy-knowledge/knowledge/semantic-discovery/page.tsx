import SemanticProposalsContent from '../../../semantic-layer/proposals/page'

import { WorkspaceNav } from '../workspace-nav'

export default function SemanticDiscoveryPage() {
  return (
    <div className="space-y-4">
      <WorkspaceNav />
      <header className="space-y-1">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">语义发现</h1>
        <p className="text-sm text-slate-600">
          统一审核队列：政策抽取未知概念、值域取值与规则冲突维度候选合并为一个待审核列表，按类型徽标区分，核对原文证据后发布到正式语义注册表。
        </p>
      </header>
      <SemanticProposalsContent />
    </div>
  )
}
