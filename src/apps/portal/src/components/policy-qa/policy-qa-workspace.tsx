'use client'

import PolicyConversation from '@/components/policy-qa/policy-conversation'
import { usePolicyQAStream } from '@/lib/use-policy-qa-stream'

export default function PolicyQAWorkspace() {
  const stream = usePolicyQAStream()

  return (
    <div
      data-testid="policy-qa-reading-column"
      className="mx-auto flex w-full max-w-[840px] flex-col px-6 py-8"
    >
      <PolicyConversation stream={stream} />
    </div>
  )
}
