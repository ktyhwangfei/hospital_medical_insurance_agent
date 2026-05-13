'use client'

import { useState } from 'react'
import KnowledgeManagement from '@/components/knowledge-management'
import type { RoleId } from '@/lib/types'

export default function KnowledgePage() {
  const [role] = useState<RoleId>('cashier')
  return <KnowledgeManagement currentRole={role} />
}
