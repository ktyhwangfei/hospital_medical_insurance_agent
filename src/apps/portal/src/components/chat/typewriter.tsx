'use client'

import { useState, useEffect, useRef } from 'react'

export interface TypewriterProps {
  /** The full text content to display (increases as streaming progresses) */
  text: string
  /** Whether the typewriter is actively typing (shows cursor) */
  isTyping?: boolean
  /** Characters per second (default: 30) */
  speed?: number
  /** Whether tool call is in progress (pause cursor blink) */
  awaitingToolCall?: boolean
  /** Optional className */
  className?: string
}

/** Unique style element ID so we only inject keyframes once */
const STYLE_ID = 'typewriter-injected-styles'

function ensureKeyframes() {
  if (typeof document === 'undefined') return
  if (document.getElementById(STYLE_ID)) return
  const style = document.createElement('style')
  style.id = STYLE_ID
  style.textContent = `
    @keyframes tw-blink {
      0%, 49% { opacity: 1; }
      50%, 100% { opacity: 0; }
    }
    @keyframes tw-pulse-dot {
      0%, 100% { opacity: 0.3; }
      50% { opacity: 1; }
    }
  `
  document.head.appendChild(style)
}

export function Typewriter({
  text,
  isTyping = false,
  speed = 30,
  awaitingToolCall = false,
  className,
}: TypewriterProps) {
  const [displayedLength, setDisplayedLength] = useState(0)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Inject keyframe animations once on mount
  useEffect(() => {
    ensureKeyframes()
  }, [])

  // Reset displayed length when text is replaced with shorter content
  useEffect(() => {
    if (text.length < displayedLength) {
      setDisplayedLength(0)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text])

  // Main typing animation loop
  useEffect(() => {
    // If not actively typing, reveal all text immediately
    if (!isTyping) {
      setDisplayedLength(text.length)
      return
    }

    // Clear any stale interval before starting a new one
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }

    const baseInterval = 1000 / speed

    const tick = () => {
      setDisplayedLength(prev => {
        if (prev >= text.length) {
          // All text revealed — stop the interval
          if (intervalRef.current) {
            clearInterval(intervalRef.current)
            intervalRef.current = null
          }
          return prev
        }
        // Accelerate batch size when far behind for smoother catch-up
        const remaining = text.length - prev
        const batchSize = remaining > 50 ? 3 : remaining > 20 ? 2 : 1
        return Math.min(prev + batchSize, text.length)
      })
    }

    // Small random variation per tick for more natural feel
    const jitter = (Math.random() - 0.5) * 10 // ±5ms
    intervalRef.current = setInterval(tick, Math.max(16, baseInterval + jitter))

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [text, isTyping, speed])

  // Guard against text being replaced with shorter content mid-animation
  const safeLength = Math.min(displayedLength, text.length)
  const displayedText = text.slice(0, safeLength)

  return (
    <div className={className}>
      <span
        data-testid="typewriter-text"
        className="whitespace-pre-wrap leading-relaxed"
      >
        {displayedText}
      </span>
      {isTyping && (
        <span
          data-testid="typewriter-cursor"
          className="inline-block ml-0.5"
          style={{
            color: '#22d3ee',
            lineHeight: 1,
            ...(awaitingToolCall
              ? {
                  fontSize: '1.1em',
                  animation: 'tw-pulse-dot 1.4s ease-in-out infinite',
                }
              : {
                  fontWeight: 300,
                  animation: 'tw-blink 530ms step-end infinite',
                }),
          }}
        >
          {awaitingToolCall ? '\u22EF' : '|'}
        </span>
      )}
    </div>
  )
}
