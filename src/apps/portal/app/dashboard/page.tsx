'use client'

import Dashboard from '@/components/dashboard'
import { useRoleContext } from '../layout'

export default function DashboardPage() {
  const { currentRole } = useRoleContext()

  return (
    <div className="mx-auto max-w-6xl">
      <Dashboard currentRole={currentRole} />
    </div>
  )
}
