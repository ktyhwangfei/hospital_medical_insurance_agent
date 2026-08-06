import { KnowledgeBuildPage as KnowledgeBuildPageContent } from '@/components/policy-knowledge/knowledge-build-page'

import { WorkspaceNav } from '../workspace-nav'

export default function KnowledgeBuildPage() {
  return <KnowledgeBuildPageContent navigation={<WorkspaceNav />} />
}
