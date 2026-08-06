import PolicyAgentAnswer from '@/components/policy-qa/policy-agent-answer'
import type { PolicyQAChatMessage } from '@/lib/policy-qa-session'

interface PolicyMessageListProps {
  messages: PolicyQAChatMessage[]
  onFollowUp: (question: string) => void
}

export default function PolicyMessageList({ messages, onFollowUp }: PolicyMessageListProps) {
  return (
    <ol aria-label="政策问答消息" className="space-y-5">
      {messages.map((message, index) => (
        <li key={`${message.role}-${index}`}>
          {message.role === 'user' ? (
            <div className="ml-auto max-w-[78%] rounded-2xl rounded-br-md bg-slate-900 px-4 py-3 text-sm leading-6 text-white">
              {message.content}
            </div>
          ) : (
            <PolicyAgentAnswer message={message} onFollowUp={onFollowUp} />
          )}
        </li>
      ))}
    </ol>
  )
}
