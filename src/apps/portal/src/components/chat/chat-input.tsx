'use client'

import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Send, Loader2 } from 'lucide-react'

// ── Props ────────────────────────────────────────────────────

interface ChatInputProps {
  input: string
  setInput: (value: string) => void
  isLoading: boolean
  onSend: () => void
  /** 可选：覆盖输入框占位符（默认导办场景文案） */
  placeholder?: string
  /** 可选：覆盖容器样式（默认暗色底；政策问答等浅色页面可覆写） */
  containerClassName?: string
  /** 可选：覆盖输入框样式 */
  inputClassName?: string
}

// ── Component ────────────────────────────────────────────────

export default function ChatInput({
  input,
  setInput,
  isLoading,
  onSend,
  placeholder = '描述您的问题，例如：这个患者为什么结不了，或者这条规则什么意思…',
  containerClassName,
  inputClassName,
}: ChatInputProps) {
  return (
    <div className={containerClassName ?? 'p-3 border-t border-white/[0.06] bg-slate-900/80 backdrop-blur-sm'}>
      <div className="flex gap-2.5 items-end">
        <Input
          data-testid="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && onSend()}
          placeholder={placeholder}
          className={inputClassName ?? 'flex-1 h-auto py-2.5 px-3.5 text-sm bg-white/[0.06] text-white/90 placeholder:text-slate-500 border-white/[0.08] rounded-xl focus:bg-white/[0.1] focus:ring-2 focus:ring-blue-400/15 focus:border-blue-400/40 transition-all duration-200'}
          disabled={isLoading}
        />
        <Button
          data-testid="send-button"
          onClick={onSend}
          disabled={isLoading || !input.trim()}
          size="icon"
          className="h-[42px] w-[42px] rounded-xl bg-gradient-to-br from-blue-500 to-blue-600 text-white hover:from-blue-400 hover:to-blue-500 disabled:from-slate-700 disabled:to-slate-700 disabled:text-slate-500 disabled:cursor-not-allowed transition-all duration-200 shadow-lg shadow-blue-900/30 active:scale-95"
        >
          {isLoading ? (
            <Loader2 data-testid="loader-icon" className="w-4.5 h-4.5 animate-spin" />
          ) : (
            <Send className="w-4.5 h-4.5" />
          )}
        </Button>
      </div>
    </div>
  )
}
