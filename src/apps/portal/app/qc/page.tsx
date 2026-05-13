'use client'

import DischargeQC from '@/components/discharge-qc'
import { useRoleContext } from '../layout'

export default function QcPage() {
  const { currentRole } = useRoleContext()

  return (
    <div className="mx-auto max-w-6xl">
      <DischargeQC currentRole={currentRole} />
    </div>
  )
}
