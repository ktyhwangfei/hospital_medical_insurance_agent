import { redirect } from 'next/navigation'

export default async function LegacyKnowledgeChangeSetPage({
  params,
}: {
  params: Promise<{ changeSetId: string }>
}) {
  const { changeSetId } = await params
  redirect(`/policy-knowledge/knowledge/review/${encodeURIComponent(changeSetId)}`)
}
