'use client'

import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Bot } from 'lucide-react'
import { Typewriter } from './typewriter'
import type { StreamStepDisplay } from '@/lib/sse-hooks'

// ── Props ────────────────────────────────────────────────────

interface StreamingBubbleProps {
  isStreaming: boolean
  streamingContent: string
  steps: StreamStepDisplay[]
}

// ── Component ────────────────────────────────────────────────

export default function StreamingBubble({ isStreaming, streamingContent, steps }: StreamingBubbleProps) {
  return (
    <div className="flex items-end gap-3 flex-row" data-testid="streaming-indicator">
      <Avatar className="h-9 w-9 shrink-0 bg-gradient-to-br from-cyan-400 to-blue-500 shadow-lg shadow-cyan-900/20 ring-2 ring-white/10">
        <AvatarFallback>
          <Bot className="h-5 w-5 text-white" />
        </AvatarFallback>
      </Avatar>
      <div className="max-w-[80%]">
        <div className="bg-white/95 text-slate-800 border border-white/20 rounded-2xl rounded-tl-md shadow-sm px-4 py-2.5">
          <Typewriter
            text={streamingContent}
            isTyping={isStreaming}
            awaitingToolCall={steps.some(s => s.status === 'running' || s.status === 'pending')}
          />
        </div>
      </div>
    </div>
  )
}
