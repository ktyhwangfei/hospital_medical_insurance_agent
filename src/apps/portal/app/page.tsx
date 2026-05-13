'use client'

import { Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import SettlementChat from '@/components/settlement-chat'
import { useRoleContext } from './layout'

function ChatContent() {
  const { currentRole } = useRoleContext()
  const searchParams = useSearchParams()
  const prefilledMessage = searchParams.get('prefill')

  return (
    <div className="mx-auto max-w-5xl">
      <SettlementChat currentRole={currentRole} prefilledMessage={prefilledMessage ?? undefined} />
    </div>
  )
}

export default function ChatPage() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-5xl p-6 text-sm text-slate-400">加载中...</div>}>
      <ChatContent />
    </Suspense>
  )
}
