import SemanticProposalsContent from '../../../semantic-layer/proposals/page'

import { WorkspaceNav } from '../workspace-nav'

export default function SemanticDiscoveryPage() {
  return (
    <div className="space-y-4">
      <WorkspaceNav />
      <header className="space-y-1">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">语义发现</h1>
        <p className="text-sm text-slate-600">
          审核政策抽取主动发现的指标与值域提议，核对原文证据后发布到正式语义注册表。
        </p>
      </header>
      <SemanticProposalsContent />
    </div>
  )
}
