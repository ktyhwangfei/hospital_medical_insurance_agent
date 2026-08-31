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
  /** 会话非活跃（挂起/升级中）时禁止输入 */
  disabled?: boolean
}

export default function PolicyComposer({
  settlementId,
  value,
  onChange,
  onSend,
  isStreaming = false,
  disabled = false,
}: PolicyComposerProps) {
  const locked = isStreaming || disabled
  const canSend = value.trim().length > 0 && !locked

  return (
    <div
      data-testid="policy-qa-composer"
      className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm"
    >
      {!isStreaming ? (
        <span data-testid="policy-qa-stream-done" className="sr-only" aria-hidden="true">
          回答生成完成
        </span>
      ) : null}
      {settlementId ? (
        <div className="mb-2 inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
          <ReceiptText className="size-3.5" aria-hidden />
          结算单 {settlementId}
        </div>
      ) : null}
      <div className="flex items-end gap-2">
        <Textarea
          aria-label="政策问题"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault()
              if (canSend) onSend()
            }
          }}
          disabled={locked}
          placeholder={
            disabled
              ? '会话已挂起或升级中，恢复后可继续提问'
              : settlementId
                ? '继续追问当前结算单…'
                : '首次请提供结算单号，例如：查询住院费用，结算单 1671213'
          }
          rows={2}
          className="min-h-20 resize-none border-0 px-2 shadow-none focus-visible:ring-2 focus-visible:ring-blue-500/25"
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
