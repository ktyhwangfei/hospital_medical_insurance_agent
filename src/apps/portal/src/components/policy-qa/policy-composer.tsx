'use client'

import { ReceiptText, SendHorizontal, BarChart3 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import type { PolicyQAMode } from '@/lib/use-policy-qa-stream'

interface PolicyComposerProps {
  mode: PolicyQAMode
  settlementId: string | null
  value: string
  onChange: (value: string) => void
  onSend: () => void
  isStreaming?: boolean
  /** 会话非活跃（挂起/升级中）时禁止输入 */
  disabled?: boolean
}

const MODE_META: Record<
  PolicyQAMode,
  {
    badge: string | null
    icon: React.ReactNode
    placeholder: string
    hint: string
    sendLabel: string
  }
> = {
  policy_chat: {
    badge: null,
    icon: null,
    placeholder: '直接问政策问题…',
    hint: '支持 @新会话；Shift + Enter 换行',
    sendLabel: '发送',
  },
  settlement_explain: {
    badge: null,
    icon: <ReceiptText className="size-3.5" aria-hidden />,
    placeholder: '输入结算单号或费用项目，例如：查询住院费用，结算单 1671213',
    hint: '结算解释模式下优先调用结算单结构化解释工作流',
    sendLabel: '发送',
  },
  data_query: {
    badge: null,
    icon: <BarChart3 className="size-3.5" aria-hidden />,
    placeholder: '用自然语言问运营数据…',
    hint: '回答同时给出数据表格与图表',
    sendLabel: '问数',
  },
}

export default function PolicyComposer({
  mode,
  settlementId,
  value,
  onChange,
  onSend,
  isStreaming = false,
  disabled = false,
}: PolicyComposerProps) {
  const locked = isStreaming || disabled
  const canSend = value.trim().length > 0 && !locked
  const meta = MODE_META[mode]

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
      <div className="mb-2 flex items-center gap-2">
        {settlementId ? (
          <div className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
            <ReceiptText className="size-3.5" aria-hidden />
            结算单 {settlementId}
          </div>
        ) : null}
        {meta.icon ? (
          <div className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
            {meta.icon}
            {mode === 'data_query' ? '运营问数' : '结算解释'}
          </div>
        ) : null}
      </div>
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
              : mode === 'settlement_explain' && !settlementId
                ? '首次请提供结算单号，例如：查询住院费用，结算单 1671213'
                : meta.placeholder
          }
          rows={2}
          className="min-h-20 resize-none border-0 px-2 shadow-none focus-visible:ring-2 focus-visible:ring-blue-500/25"
        />
        <Button type="button" onClick={onSend} disabled={!canSend} aria-label={meta.sendLabel}>
          <SendHorizontal aria-hidden />
          {meta.sendLabel}
        </Button>
      </div>
      <p className="px-2 pt-2 text-[11px] text-slate-400">{meta.hint}</p>
    </div>
  )
}
