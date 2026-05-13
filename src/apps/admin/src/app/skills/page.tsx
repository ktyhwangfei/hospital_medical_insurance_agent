'use client'

import { useState } from 'react'
import SkillManagement from '@/components/skill-management'
import type { RoleId } from '@/lib/types'

export default function SkillsPage() {
  const [role] = useState<RoleId>('cashier')
  return <SkillManagement currentRole={role} />
}
