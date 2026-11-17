import PolicyAgentAnswer from '@/components/policy-qa/policy-agent-answer'
import type { PolicyQAChatMessage } from '@/lib/policy-qa-session'

interface PolicyMessageListProps {
  messages: PolicyQAChatMessage[]
  /** 结算解释会话：答案块隐藏通用核验摘要/计算依据/内部质检入口（对齐 #85 展示口径） */
  settlementConversation?: boolean
}

export default function PolicyMessageList({ messages, settlementConversation = false }: PolicyMessageListProps) {
  return (
    <ol aria-label="政策问答消息" className="space-y-5">
      {messages.map((message, index) => (
        <li key={`${message.role}-${index}`}>
          {message.role === 'user' ? (
            <div className="ml-auto max-w-[78%] rounded-2xl rounded-br-md bg-slate-900 px-4 py-3 text-sm leading-6 text-white">
              {message.content}
            </div>
          ) : (
            <PolicyAgentAnswer message={message} settlementConversation={settlementConversation} />
          )}
        </li>
      ))}
    </ol>
  )
}
