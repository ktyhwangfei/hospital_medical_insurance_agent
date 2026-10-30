import PolicyAgentAnswer from '@/components/policy-qa/policy-agent-answer'
import type { PolicyQAChatMessage } from '@/lib/policy-qa-session'
import type { PatientSummaryDTO } from '@/lib/policy-qa-settlement-list'

interface PolicyMessageListProps {
  messages: PolicyQAChatMessage[]
  /** 已定位患者（脱敏摘要）：结算单式样费用构成的病人基本信息块 */
  patient?: PatientSummaryDTO | null
  /** 点结算单字段发起提问；缺省时字段不可点击 */
  onAskField?: (fieldLabel: string) => void
  showSettlementBill?: boolean
  settlementConversation?: boolean
}

export default function PolicyMessageList({ messages, patient, onAskField, showSettlementBill = true, settlementConversation = false }: PolicyMessageListProps) {
  return (
    <ol aria-label="政策问答消息" className="space-y-5">
      {messages.map((message, index) => (
        <li key={`${message.role}-${index}`}>
          {message.role === 'user' ? (
            <div className="ml-auto max-w-[78%] rounded-2xl rounded-br-md bg-slate-900 px-4 py-3 text-sm leading-6 text-white">
              {message.content}
            </div>
          ) : (
            <PolicyAgentAnswer message={message} patient={patient} onAskField={onAskField} showSettlementBill={showSettlementBill} settlementConversation={settlementConversation} />
          )}
        </li>
      ))}
    </ol>
  )
}
