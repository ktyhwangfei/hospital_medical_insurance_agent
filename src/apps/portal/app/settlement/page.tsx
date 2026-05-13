'use client'

import SettlementExceptionList from '@/components/settlement-exception-list'
import { useRoleContext } from '../layout'

export default function SettlementPage() {
  const { currentRole } = useRoleContext()

  return <SettlementExceptionList currentRole={currentRole} />
}
