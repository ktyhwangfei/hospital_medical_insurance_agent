import { redirect } from 'next/navigation'

export default function LegacyKnowledgeDecisionsPage() {
  redirect('/policy-knowledge/knowledge/review?view=issues')
}
