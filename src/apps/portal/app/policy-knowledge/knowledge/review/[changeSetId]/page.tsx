import { BuildContextBar, KnowledgeFlow } from '@/components/policy-knowledge/knowledge-governance-shared'
import { KnowledgeReviewDetail } from '@/components/policy-knowledge/knowledge-review-detail'

import { WorkspaceNav } from '../../workspace-nav'

type KnowledgeReviewDetailPageProps = {
  params: Promise<{ changeSetId: string }>
}

export default async function KnowledgeReviewDetailPage({
  params,
}: KnowledgeReviewDetailPageProps) {
  const { changeSetId } = await params

  return (
    <div className="space-y-4">
      <WorkspaceNav />
      <BuildContextBar availableUnitCount={null} semanticContractVersion={null} />
      <KnowledgeFlow current="review" />
      <KnowledgeReviewDetail changeSetId={changeSetId} />
    </div>
  )
}
