import { BuildContextBar, KnowledgeFlow } from '@/components/policy-knowledge/knowledge-governance-shared'
import { KnowledgeReviewPage as KnowledgeReviewContent } from '@/components/policy-knowledge/knowledge-review-page'

import { WorkspaceNav } from '../workspace-nav'

export default function KnowledgeReviewPage() {
  return (
    <div className="space-y-4">
      <WorkspaceNav />
      <BuildContextBar availableUnitCount={null} semanticContractVersion={null} />
      <KnowledgeFlow current="review" />
      <KnowledgeReviewContent />
    </div>
  )
}
