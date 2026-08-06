import { BuildContextBar, KnowledgeFlow } from '@/components/policy-knowledge/knowledge-governance-shared'
import { KnowledgeReleaseManagement } from '@/components/policy-knowledge/knowledge-release-management'

import { WorkspaceNav } from '../workspace-nav'

export default function KnowledgeReleasesPage() {
  return (
    <div className="space-y-4">
      <WorkspaceNav />
      <BuildContextBar availableUnitCount={null} semanticContractVersion={null} />
      <KnowledgeFlow current="release" />
      <KnowledgeReleaseManagement />
    </div>
  )
}
