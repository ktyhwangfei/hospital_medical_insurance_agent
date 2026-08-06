'use client'

import { ReceiptText, SendHorizontal } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

interface PolicyComposerProps {
  settlementId: string | null
  value: string
  onChange: (value: string) => void
  onSend: () => void
  isStreaming?: boolean
}

export default function PolicyComposer({
  settlementId,
  value,
  onChange,
  onSend,
  isStreaming = false,
}: PolicyComposerProps) {
  const canSend = value.trim().length > 0 && !isStreaming

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
      {settlementId ? (
        <div className="mb-2 inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
          <ReceiptText className="size-3.5" aria-hidden />
          结算单 {settlementId}
        </div>
      ) : null}
      <div className="flex items-end gap-2">
        <Textarea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              if (canSend) onSend()
            }
          }}
          disabled={isStreaming}
          placeholder={
            settlementId
              ? '继续追问当前结算单…'
              : '首次请提供结算单号，例如：查询住院费用，结算单 1671213'
          }
          rows={2}
          className="min-h-20 resize-none border-0 px-2 shadow-none focus-visible:ring-0"
        />
        <Button type="button" onClick={onSend} disabled={!canSend} aria-label="发送">
          <SendHorizontal aria-hidden />
          发送
        </Button>
      </div>
      <p className="px-2 pt-2 text-[11px] text-slate-400">
        支持 <span className="font-mono">@换结算 &lt;单号&gt;</span> 与{' '}
        <span className="font-mono">@新会话</span>；Shift + Enter 换行
      </p>
    </div>
  )
}
