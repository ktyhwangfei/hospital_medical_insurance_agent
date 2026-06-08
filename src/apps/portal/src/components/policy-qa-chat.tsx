'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { Loader2, Send, Bot, User } from 'lucide-react'
import ThinkingChain from '@/components/thinking-chain'
import type { ThinkingStep } from '@/components/thinking-chain'
import PolicyAnswerCard from '@/components/policy-answer-card'
import type {
  TreatmentItem,
  FeeBreakdownItem,
  EvidenceItem,
} from '@/components/policy-answer-card'

interface PolicyQAMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

interface PolicyQAStep {
  step: string
  status: 'pending' | 'running' | 'done' | 'error' | 'streaming'
  detail?: Record<string, unknown>
  /** 用户可展示的结构化数据 */
  publicDetail?: Record<string, unknown>
  /** ★ 用户可展示的纯文本摘要（优先渲染） */
  publicMessage?: string
  chunk?: string
  error?: string
  startTime?: number
  endTime?: number
}

/** RAG 政策卡片 */
interface PolicyCardItem {
  title: string
  clause: string
  evidenceText: string
  matchedReason: string
  ruleType?: string
  score?: number
}

interface PolicyQAChatProps {
  settlementId?: string
}

// ── SSE 不可达时的步骤模拟降级方案 ──────────────────────────────
const SIMULATED_STEPS = [
  { step: '识别问题意图', message: '正在识别问题意图' },
  { step: '查询结算数据', message: '正在查询结算数据' },
  { step: '重写用户问题', message: '正在结合患者信息精准化问题' },
  { step: '检索政策依据', message: '正在检索相关政策依据' },
  { step: '生成费用解释', message: '正在生成费用解释' },
  { step: '输出双视角答案', message: '正在生成患者视角和院端视角答案' },
]

async function simulateSteps(
  setSteps: React.Dispatch<React.SetStateAction<PolicyQAStep[]>>,
  setTypewriterText: React.Dispatch<React.SetStateAction<string>>,
  setIsTyping: React.Dispatch<React.SetStateAction<boolean>>,
  _setTreatments: React.Dispatch<React.SetStateAction<TreatmentItem[]>>,
  _setFeeBreakdown: React.Dispatch<React.SetStateAction<FeeBreakdownItem[]>>,
  _setEvidence: React.Dispatch<React.SetStateAction<EvidenceItem[]>>,
  setPatientView: React.Dispatch<React.SetStateAction<string>>,
  setOfficeView: React.Dispatch<React.SetStateAction<string>>,
  setRagMiss: React.Dispatch<React.SetStateAction<boolean>>,
) {
  for (let i = 0; i < SIMULATED_STEPS.length; i++) {
    const s = SIMULATED_STEPS[i]
    // running
    setSteps(prev => [...prev, { step: s.step, status: 'running', publicMessage: s.message, startTime: Date.now() }])
    await new Promise(r => setTimeout(r, 400 + Math.random() * 300))
    // done（最后一步保持 running 直至结束）
    const isLast = i === SIMULATED_STEPS.length - 1
    setSteps(prev => prev.map(st => st.step === s.step ? { ...st, status: isLast ? 'running' : 'done' as const, endTime: Date.now() } : st))
  }

  setTypewriterText('当前后端服务不可达，已切换到离线演示模式。\n请启动后端服务后重新尝试。')
  setIsTyping(false)
  setPatientView('后端服务不可达，无法生成患者视角解释。')
  setOfficeView('后端服务不可达，无法生成院端视角解释。')
  setRagMiss(true)
}

export default function PolicyQAChat({ settlementId }: PolicyQAChatProps) {
  const [messages, setMessages] = useState<PolicyQAMessage[]>([
    {
      role: 'assistant',
      content: '您好！我是医保政策问答助手 🤖\n\n我可以帮您：\n• 解释费用构成\n• 了解待遇计算\n• 查询起付线规则\n• 了解报销比例\n• 分析封顶线\n\n请输入您的问题，或提供结算ID开始查询。',
      timestamp: new Date(),
    },
  ])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [steps, setSteps] = useState<PolicyQAStep[]>([])
  const [typewriterText, setTypewriterText] = useState('')
  const [isTyping, setIsTyping] = useState(false)
  const [treatments, setTreatments] = useState<TreatmentItem[]>([])
  const [feeBreakdown, setFeeBreakdown] = useState<FeeBreakdownItem[]>([])
  const [evidence, setEvidence] = useState<EvidenceItem[]>([])
  const [policyCards, setPolicyCards] = useState<PolicyCardItem[]>([])
  const [patientView, setPatientView] = useState('')
  const [officeView, setOfficeView] = useState('')
  const [ragMiss, setRagMiss] = useState(false)
  const [selectedView, setSelectedView] = useState<'patient' | 'office'>('patient')
  const [showPolicyPanel, setShowPolicyPanel] = useState(false) // 政策知识侧面板
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const typewriterRef = useRef<NodeJS.Timeout | null>(null)

  // ── 数据防泄漏：过滤 SSE 数据中禁止展示的字段 ──────────────────
  const FORBIDDEN_KEY_PATTERNS = [
    'reasoning', 'reasoning_content', 'chain_of_thought', 'thought',
    'scratchpad', 'debug', 'internal', 'prompt', 'messages',
    'raw_response', 'tool_calls', 'agent_trace',
  ]

  function stripForbiddenFields(obj: Record<string, unknown>): Record<string, unknown> {
    const result: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(obj)) {
      const keyLower = key.toLowerCase()
      const isForbidden = FORBIDDEN_KEY_PATTERNS.some(p => keyLower.includes(p))
      if (isForbidden) continue
      if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
        result[key] = stripForbiddenFields(value as Record<string, unknown>)
      } else if (Array.isArray(value)) {
        result[key] = (value as unknown[]).map(item =>
          item !== null && typeof item === 'object' && !Array.isArray(item)
            ? stripForbiddenFields(item as Record<string, unknown>)
            : item
        )
      } else {
        result[key] = value
      }
    }
    return result
  }

  // ── 步骤展示映射 ──────────────────────────────────────────
  const STEP_DISPLAY_NAMES: Record<string, string> = {
    intent: '识别问题意图',
    query_sql_data: '查询结算数据',
    search_policy_rules: '检索政策依据',
    calculate_explanation: '费用计算',
    generate_explanation: '生成解释',
    // 向后兼容旧步骤名
    sql_query: '查询结算数据',
    rewrite: '重写用户问题',
    search: '检索政策依据',
    decomposition: '生成费用解释',
    explain: '输出双视角答案',
  }

  // 事件队列机制：逐步展示步骤
  const eventQueueRef = useRef<Array<{ data: PolicyQAStep; timestamp: number }>>([])
  const queueTimerRef = useRef<NodeJS.Timeout | null>(null)
  const isProcessingQueueRef = useRef(false)

  // 处理队列中的事件
  const processQueue = useCallback(() => {
    if (eventQueueRef.current.length === 0) {
      isProcessingQueueRef.current = false
      return
    }

    isProcessingQueueRef.current = true
    const { data } = eventQueueRef.current.shift()!

    setSteps((prev) => {
      const existing = prev.findIndex((s) => s.step === data.step)
      if (existing >= 0) {
        const updated = [...prev]
        updated[existing] = {
          ...updated[existing],
          ...data,
          endTime: data.status === 'done' ? Date.now() : updated[existing].endTime,
        }
        return updated
      }
      return [...prev, {
        ...data,
        startTime: Date.now()
      }]
    })

    // 继续处理下一个事件
    queueTimerRef.current = setTimeout(processQueue, 300)
  }, [])

  // 入队事件
  const enqueueEvent = useCallback((data: PolicyQAStep) => {
    eventQueueRef.current.push({ data, timestamp: Date.now() })

    if (!isProcessingQueueRef.current) {
      processQueue()
    }
  }, [processQueue])

  // 清理队列定时器
  useEffect(() => {
    return () => {
      if (queueTimerRef.current) {
        clearTimeout(queueTimerRef.current)
      }
    }
  }, [])

  // 自动滚动到底部
  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (scrollRef.current) {
          scrollRef.current.scrollTop = scrollRef.current.scrollHeight
        }
      })
    })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, steps, typewriterText, scrollToBottom])

  // 打字机效果
  const startTypewriter = useCallback((text: string) => {
    setIsTyping(true)
    setTypewriterText('')
    let index = 0
    const speed = { min: 20, max: 50 }

    const type = () => {
      if (index < text.length) {
        const char = text.charAt(index)
        setTypewriterText(prev => prev + char)
        index++
        scrollToBottom()
        const delay = speed.min + Math.random() * (speed.max - speed.min)
        typewriterRef.current = setTimeout(type, delay)
      } else {
        setIsTyping(false)
      }
    }

    type()
  }, [scrollToBottom])

  // 清理打字机
  useEffect(() => {
    return () => {
      if (typewriterRef.current) {
        clearTimeout(typewriterRef.current)
      }
    }
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return

    const userMessage = input.trim()
    setInput('')
    setIsLoading(true)
    setSteps([])
    setTypewriterText('')
    setIsTyping(false)
    setTreatments([])
    setFeeBreakdown([])
    setEvidence([])
    setPolicyCards([])
    setPatientView('')
    setOfficeView('')
    setRagMiss(false)
    setSelectedView('patient')
    setShowPolicyPanel(false)

    // 添加用户消息
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: userMessage, timestamp: new Date() },
    ])

    // 清空事件队列
    eventQueueRef.current = []
    if (queueTimerRef.current) {
      clearTimeout(queueTimerRef.current)
    }
    isProcessingQueueRef.current = false

    // 构建请求
    const request = {
      question: userMessage,
      settlement_id: settlementId || '1671213',
    }

    try {
      // 使用SSE流式请求
      const response = await fetch('/api/v1/medical-insurance-ai-agent/policy-qa/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(request),
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('No reader available')
      }

      const decoder = new TextDecoder()
      let buffer = ''
      let fullResponse = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          // 解析 SSE event: 前缀
          let eventType = "step"  // 默认
          let dataStr = ""
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim()
            continue
          }
          if (line.startsWith('data: ')) {
            dataStr = line.slice(6).trim()
          } else {
            continue
          }
          if (dataStr === '[DONE]') {
            break
          }

          try {
            const rawData = JSON.parse(dataStr)
            // ★ 防泄漏：过滤禁止展示的字段
            const data = stripForbiddenFields(rawData as Record<string, unknown>)

            // ── 处理 result 事件（只提取结果数据，不覆写步骤）──
            // ★ 步骤已在流式过程中逐条构建，result 事件不应覆盖
            if (eventType === 'result') {
              // 提取 result 内容
              const resultData = data.result as Record<string, unknown> | undefined
              if (resultData) {
                if (resultData.patient_view) setPatientView(String(resultData.patient_view))
                if (resultData.office_view) setOfficeView(String(resultData.office_view))
                if (resultData.policy_evidence && Array.isArray(resultData.policy_evidence)) {
                  setPolicyCards((resultData.policy_evidence as Array<Record<string, unknown>>).map(c => ({
                    title: String(c.title || ''),
                    clause: String(c.clause || ''),
                    evidenceText: String(c.evidence_text || c.evidenceText || ''),
                    matchedReason: String(c.matched_reason || c.matchedReason || ''),
                    ruleType: String(c.rule_type || c.ruleType || ''),
                    score: Number(c.score || 0),
                  })))
                }
              }
            }

            // ── 处理 step 事件 ──
            else if (data.step && data.status) {
                // ★ 构建步骤数据，分离内部 detail 与用户可展示字段
                const stepData: PolicyQAStep = {
                  step: String(data.step),
                  status: String(data.status) as PolicyQAStep['status'],
                  detail: data.detail as Record<string, unknown> | undefined,
                  publicDetail: (data.public_detail || data.publicDetail) as Record<string, unknown> | undefined,
                  publicMessage: String(data.public_message || data.publicMessage || ''),
                  chunk: typeof data.chunk === 'string' ? data.chunk : undefined,
                  error: typeof data.error === 'string' ? data.error : undefined,
                }

                // ★ 提取 RAG 政策卡片（search_policy_rules 步骤 done 时）
                if (data.step === 'search_policy_rules' && data.status === 'done') {
                  const cards = data.policy_cards || data.policyCards
                  if (cards && Array.isArray(cards)) {
                    setPolicyCards(cards.map((c: Record<string, unknown>) => ({
                      title: String(c.title || ''),
                      clause: String(c.clause || ''),
                      evidenceText: String(c.evidence_text || c.evidenceText || ''),
                      matchedReason: String(c.matched_reason || c.matchedReason || ''),
                      ruleType: String(c.rule_type || c.ruleType || ''),
                      score: Number(c.score || 0),
                    })))
                  }
                  // 检测 RAG 未命中
                  const pd = (data.public_detail || data.publicDetail) as Record<string, unknown> | undefined
                  if (pd && pd.rag_miss) {
                    setRagMiss(true)
                  }
                }

                // ★ 提取双视角解释（generate_explanation 步骤 done 时）
                if (data.step === 'generate_explanation' && data.status === 'done') {
                  if (data.patient_view || data.patientView) {
                    setPatientView(String(data.patient_view || data.patientView || ''))
                  }
                  if (data.office_view || data.officeView) {
                    setOfficeView(String(data.office_view || data.officeView || ''))
                  }
                }

                // 使用事件队列逐步展示步骤（running 状态立即显示，done 状态入队）
                if (data.status === 'running') {
                  // running 状态立即显示，给用户即时反馈
                  setSteps((prev) => {
                    const existing = prev.findIndex((s) => s.step === data.step)
                    if (existing >= 0) {
                      const updated = [...prev]
                      updated[existing] = { ...updated[existing], ...stepData, status: 'running' as const }
                      return updated
                    }
                    return [...prev, { ...stepData, startTime: Date.now(), status: 'running' as const }]
                  })
                } else {
                  // done/streaming/error 状态入队，按间隔逐步展示
                  enqueueEvent(stepData)
                }

                // 如果是流式内容，累积到完整响应
                if (data.status === 'streaming' && data.chunk) {
                  fullResponse += data.chunk
                  // 实时更新打字机文本（流式效果）
                  setTypewriterText(fullResponse)
                  scrollToBottom()
                }

                // 提取费用分解数据（calculate_explanation 步骤完成时）
                if (data.step === 'calculate_explanation' && data.status === 'done' && data.detail) {
                  const detail = data.detail as Record<string, unknown>

                  // 提取待遇分解
                  if (detail.treatment && typeof detail.treatment === 'object') {
                    const treatment = detail.treatment as Record<string, number>
                    const treatmentItems: TreatmentItem[] = [
                      { label: '总费用', value: treatment.total_fee || 0, variant: 'primary' },
                      { label: '医保内', value: treatment.in_scope || 0, variant: 'primary' },
                      { label: '起付线', value: treatment.deductible || 0 },
                      { label: '统筹支付', value: treatment.pooling_payment || 0 },
                      { label: '统筹自付', value: treatment.pooling_self_pay || 0 },
                      { label: '大额支付', value: treatment.major_payment || 0 },
                      { label: '大额自付', value: treatment.major_self_pay || 0 },
                      { label: '个人应负', value: treatment.personal_liability || 0 },
                      { label: '医保外', value: treatment.out_of_scope || 0 },
                    ]
                    setTreatments(treatmentItems)
                  }

                  // 提取费用分解（后端返回 fees，前端兼容 fee_breakdown）
                  const fees = detail.fees || detail.fee_breakdown
                  if (fees && typeof fees === 'object' && 'categories' in fees) {
                    const feesData = fees as { categories: Array<{ category: string; total_amount: number; in_scope_amount: number; out_of_scope_amount: number }> }
                    const feeBreakdownItems: FeeBreakdownItem[] = feesData.categories.map(cat => ({
                      label: cat.category,
                      amount: cat.total_amount,
                      description: `医保内 ${cat.in_scope_amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })} 元，医保外 ${cat.out_of_scope_amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })} 元`,
                    }))
                    setFeeBreakdown(feeBreakdownItems)
                  }

                  // 提取分段计算数据（新增：展示分段计算详情）
                  if (detail.segments && typeof detail.segments === 'object') {
                    const segments = detail.segments as {
                      total_pay: number
                      segments: Array<{
                        lower: number
                        upper: number
                        amount: number
                        base_ratio: number
                        person_ratio: number
                        actual_ratio: number
                        pay: number
                        calculation: string
                        rule_id: string
                        policy_source: string
                      }>
                    }

                    // 将分段计算转换为证据项展示
                    const segmentEvidence: EvidenceItem[] = segments.segments.map((seg, idx) => ({
                      item: `第${idx + 1}段 (${seg.lower.toLocaleString('zh-CN')}-${seg.upper === Infinity ? '∞' : seg.upper.toLocaleString('zh-CN')}元)`,
                      value: seg.pay,
                      sourceTable: `段内金额: ${seg.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}元`,
                      policyRule: seg.policy_source || '未关联政策条文',
                      calculation: `基础比例 ${seg.base_ratio * 100}% × 人员系数 ${seg.person_ratio * 100}% = 实际比例 ${seg.actual_ratio * 100}%\n${seg.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })} × ${seg.actual_ratio * 100}% = ${seg.pay.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}元`,
                    }))

                    // 添加合计项
                    segmentEvidence.push({
                      item: '统筹自付合计',
                      value: segments.total_pay,
                      sourceTable: '分段计算合计',
                      policyRule: '各段自付金额之和',
                      calculation: segments.segments.map((s, i) => `第${i + 1}段: ${s.pay.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}元`).join(' + ') + ` = ${segments.total_pay.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}元`,
                    })

                    // 合并到现有证据中
                    setEvidence(prev => [...prev, ...segmentEvidence])
                  }

                  // 提取溯源证据
                  if (detail.evidence && Array.isArray(detail.evidence)) {
                    setEvidence(detail.evidence as EvidenceItem[])
                  }
                }

                // 如果是最后一步完成，启动打字机效果
                if (data.step === 'generate_explanation' && data.status === 'done') {
                  if (fullResponse) {
                    startTypewriter(fullResponse)
                  } else {
                    // 如果没有流式内容，显示默认消息
                    setTypewriterText('费用分解完成，请查看上方查询进度了解详细步骤。')
                    setIsTyping(false)
                  }
                }
              }
            } catch {
              // 忽略解析错误
            }
          }
        }
    } catch (error) {
      console.warn('[Policy QA] 后端不可达，使用步骤模拟模式:', error)
      // ── 模拟步骤逐步展示（后端不可达时的降级方案）──
      await simulateSteps(
        setSteps, setTypewriterText, setIsTyping,
        setTreatments, setFeeBreakdown, setEvidence,
        setPatientView, setOfficeView, setRagMiss,
      )
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <Card
      className="h-full flex flex-col"
      style={{
        background: '#0f1520',
        border: '1px solid rgba(255,255,255,0.06)',
        borderRadius: '16px',
        boxShadow: '0 4px 24px rgba(0,0,0,0.3)',
      }}
    >
      <CardHeader className="pb-2" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <CardTitle className="text-lg" style={{ color: '#f1f5f9', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Bot className="h-5 w-5" style={{ color: '#06b6d4' }} />
          <span style={{
            background: 'linear-gradient(135deg, #06b6d4, #14b8a6, #10b981)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            backgroundClip: 'text',
          }}>
            医保政策问答
          </span>
          {settlementId && (
            <Badge
              variant="outline"
              className="ml-2 text-xs"
              style={{
                background: 'rgba(6,182,212,0.1)',
                border: '1px solid rgba(6,182,212,0.3)',
                color: '#06b6d4',
              }}
            >
              结算ID: {settlementId}
            </Badge>
          )}
        </CardTitle>
      </CardHeader>

      <CardContent className="flex-1 flex flex-col p-0" style={{ background: '#0a0e17' }}>
        {/* 消息列表 */}
        <ScrollArea className="flex-1 p-4" ref={scrollRef}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {messages.map((message, index) => (
              <div
                key={index}
                style={{
                  display: 'flex',
                  justifyContent: message.role === 'user' ? 'flex-end' : 'flex-start',
                  animation: 'message-in 0.45s ease-out',
                }}
              >
                <div
                  style={{
                    maxWidth: '85%',
                    borderRadius: '16px',
                    padding: '12px 16px',
                    background: message.role === 'user'
                      ? 'linear-gradient(135deg, #2563eb, #06b6d4)'
                      : 'rgba(255,255,255,0.03)',
                    border: message.role === 'user' ? 'none' : '1px solid rgba(255,255,255,0.06)',
                    color: '#f1f5f9',
                    borderBottomLeftRadius: message.role === 'assistant' ? '4px' : '16px',
                    borderBottomRightRadius: message.role === 'user' ? '4px' : '16px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                    {message.role === 'assistant' && (
                      <div
                        style={{
                          width: '28px',
                          height: '28px',
                          borderRadius: '50%',
                          background: 'linear-gradient(135deg, #06b6d4, #10b981)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: '14px',
                          flexShrink: 0,
                        }}
                      >
                        🤖
                      </div>
                    )}
                    <div style={{ whiteSpace: 'pre-wrap', fontSize: '14px', lineHeight: 1.6 }}>
                      {message.content}
                    </div>
                    {message.role === 'user' && (
                      <div
                        style={{
                          width: '28px',
                          height: '28px',
                          borderRadius: '50%',
                          background: 'linear-gradient(135deg, #2563eb, #06b6d4)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: '14px',
                          flexShrink: 0,
                        }}
                      >
                        👤
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}

            {/* 查询进度卡片 - 使用 ThinkingChain 组件 */}
            {steps.length > 0 && (
              <>
                <ThinkingChain
                  steps={steps as ThinkingStep[]}
                  isLoading={isLoading}
                />
                {/* ★ 查询相关知识按钮 */}
                {!isLoading && (
                  <div style={{ display: 'flex', justifyContent: 'flex-start', animation: 'message-in 0.45s ease-out' }}>
                    <button
                      onClick={() => setShowPolicyPanel(!showPolicyPanel)}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '6px',
                        padding: '8px 16px',
                        borderRadius: '10px',
                        background: showPolicyPanel
                          ? 'rgba(6,182,212,0.12)'
                          : 'rgba(255,255,255,0.03)',
                        border: showPolicyPanel
                          ? '1px solid rgba(6,182,212,0.3)'
                          : '1px solid rgba(255,255,255,0.08)',
                        color: showPolicyPanel ? '#06b6d4' : '#94a3b8',
                        fontSize: '13px',
                        fontFamily: 'inherit',
                        cursor: 'pointer',
                        transition: 'all 0.2s',
                      }}
                    >
                      <span style={{ fontSize: '15px' }}>📚</span>
                      查询相关知识
                    </button>
                  </div>
                )}
              </>
            )}

            {/* RAG 未命中警告 */}
            {ragMiss && (
              <div
                style={{
                  display: 'flex', alignItems: 'flex-start', gap: '8px',
                  padding: '12px 16px', borderRadius: '12px',
                  background: 'rgba(234,179,8,0.08)',
                  border: '1px solid rgba(234,179,8,0.2)',
                  color: '#eab308', fontSize: '13px', lineHeight: 1.5,
                  animation: 'message-in 0.45s ease-out',
                }}
              >
                <span style={{ fontSize: '16px', flexShrink: 0 }}>⚠️</span>
                <span>未检索到匹配的政策规则，以下解释基于系统已有结算数据。建议咨询医院医保办确认。</span>
              </div>
            )}

            {/* ★ 政策知识侧面板 */}
            {showPolicyPanel && !isLoading && (
              <div
                style={{
                  borderRadius: '16px',
                  background: 'rgba(255,255,255,0.02)',
                  border: '1px solid rgba(6,182,212,0.15)',
                  overflow: 'hidden',
                  animation: 'message-in 0.45s ease-out',
                }}
              >
                {/* 面板头部 */}
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '12px 16px',
                  borderBottom: '1px solid rgba(255,255,255,0.04)',
                  background: 'rgba(6,182,212,0.04)',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '16px' }}>📚</span>
                    <span style={{ fontSize: '14px', fontWeight: 600, color: '#e2e8f0' }}>
                      相关政策知识
                    </span>
                    <span style={{
                      fontSize: '11px', color: '#64748b',
                      background: 'rgba(255,255,255,0.04)',
                      padding: '2px 8px', borderRadius: '9999px',
                    }}>
                      {policyCards.length + evidence.length} 条
                    </span>
                  </div>
                  <button
                    onClick={() => setShowPolicyPanel(false)}
                    style={{
                      background: 'none', border: 'none', color: '#64748b',
                      cursor: 'pointer', fontSize: '18px', padding: '2px 6px',
                    }}
                  >
                    ✕
                  </button>
                </div>

                {/* 面板内容 */}
                <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {/* 政策卡片 */}
                  {policyCards.map((card, idx) => (
                    <div
                      key={idx}
                      style={{
                        padding: '10px 14px',
                        borderRadius: '10px',
                        background: 'rgba(255,255,255,0.02)',
                        border: '1px solid rgba(255,255,255,0.05)',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                        <span style={{
                          fontSize: '10px', fontWeight: 600, padding: '1px 6px',
                          borderRadius: '4px',
                          background: card.score && card.score > 0
                            ? 'rgba(16,185,129,0.12)' : 'rgba(148,163,184,0.08)',
                          color: card.score && card.score > 0 ? '#10b981' : '#94a3b8',
                        }}>
                          {card.ruleType || '政策规则'}
                        </span>
                        <span style={{ fontSize: '13px', fontWeight: 600, color: '#e2e8f0', flex: 1 }}>
                          {card.title}
                        </span>
                        {card.score !== undefined && (
                          <span style={{
                            fontSize: '10px', color: '#64748b',
                            fontFamily: 'monospace',
                          }}>
                            相关度 {Math.abs(card.score).toFixed(2)}
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: '12px', color: '#94a3b8', lineHeight: 1.5 }}>
                        {card.evidenceText}
                      </div>
                      <div style={{ fontSize: '11px', color: '#64748b', marginTop: '4px', lineHeight: 1.4 }}>
                        📎 {card.clause}
                      </div>
                      {card.matchedReason && (
                        <div style={{ fontSize: '10px', color: '#475569', marginTop: '4px' }}>
                          匹配原因: {card.matchedReason}
                        </div>
                      )}
                    </div>
                  ))}

                  {/* 证据项 */}
                  {evidence.map((ev, idx) => (
                    <div
                      key={`ev-${idx}`}
                      style={{
                        padding: '10px 14px',
                        borderRadius: '10px',
                        background: 'rgba(16,185,129,0.03)',
                        border: '1px solid rgba(16,185,129,0.08)',
                      }}
                    >
                      <div style={{ fontSize: '12px', fontWeight: 600, color: '#e2e8f0', marginBottom: '4px' }}>
                        {ev.item}
                      </div>
                      <div style={{ fontSize: '12px', color: '#10b981', fontFamily: 'monospace' }}>
                        {ev.value?.toLocaleString?.('zh-CN', { minimumFractionDigits: 2 }) ?? ev.value} 元
                      </div>
                      {ev.sourceTable && (
                        <div style={{ fontSize: '11px', color: '#64748b', marginTop: '4px' }}>
                          📊 {ev.sourceTable}
                        </div>
                      )}
                      {ev.policyRule && (
                        <div style={{ fontSize: '10px', color: '#475569', marginTop: '2px' }}>
                          📎 {ev.policyRule}
                        </div>
                      )}
                      {ev.calculation && (
                        <div style={{
                          fontSize: '10px', color: '#64748b', marginTop: '4px',
                          background: 'rgba(0,0,0,0.2)', padding: '6px 8px',
                          borderRadius: '6px', fontFamily: 'monospace', whiteSpace: 'pre-wrap',
                        }}>
                          {ev.calculation}
                        </div>
                      )}
                    </div>
                  ))}

                  {/* 空状态 */}
                  {policyCards.length === 0 && evidence.length === 0 && (
                    <div style={{
                      textAlign: 'center', padding: '20px',
                      color: '#64748b', fontSize: '13px',
                    }}>
                      <span style={{ fontSize: '24px', display: 'block', marginBottom: '8px' }}>📭</span>
                      暂未检索到相关政策和证据
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* 政策问答结果卡片 — 步骤完成后总是展示 */}
            {!isLoading && steps.some(s => s.status === 'done') && (
              <PolicyAnswerCard
                treatments={treatments}
                feeBreakdown={feeBreakdown}
                evidence={evidence}
                policyCards={policyCards}
              />
            )}

            {/* 打字机效果消息 - 匹配v3原型 */}
            {typewriterText && (
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'flex-start',
                  animation: 'message-in 0.45s ease-out',
                }}
              >
                <div
                  style={{
                    maxWidth: '85%',
                    borderRadius: '16px',
                    padding: '12px 16px',
                    background: 'rgba(255,255,255,0.03)',
                    border: '1px solid rgba(255,255,255,0.06)',
                    color: '#f1f5f9',
                    borderBottomLeftRadius: '4px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                    <div
                      style={{
                        width: '28px',
                        height: '28px',
                        borderRadius: '50%',
                        background: 'linear-gradient(135deg, #06b6d4, #10b981)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '14px',
                        flexShrink: 0,
                      }}
                    >
                      🤖
                    </div>
                    <div style={{ whiteSpace: 'pre-wrap', fontSize: '14px', lineHeight: 1.6 }}>
                      {typewriterText}
                      {isTyping && (
                        <span
                          style={{
                            display: 'inline-block',
                            width: '2px',
                            height: '16px',
                            background: '#06b6d4',
                            marginLeft: '2px',
                            verticalAlign: 'text-bottom',
                            animation: 'blink 1s step-end infinite',
                          }}
                        />
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* ★ 双视角解释 — 步骤完成后总是展示 */}
            {!isLoading && steps.some(s => s.status === 'done') && (
              <div
                style={{
                  borderRadius: '16px',
                  background: 'rgba(255,255,255,0.03)',
                  border: '1px solid rgba(255,255,255,0.06)',
                  overflow: 'hidden',
                  animation: 'message-in 0.45s ease-out',
                }}
              >
                {/* 标签切换 */}
                <div style={{
                  display: 'flex',
                  borderBottom: '1px solid rgba(255,255,255,0.06)',
                }}>
                  <button
                    onClick={() => setSelectedView('patient')}
                    style={{
                      flex: 1, padding: '10px 16px',
                      fontSize: '13px', fontWeight: selectedView === 'patient' ? 600 : 400,
                      color: selectedView === 'patient' ? '#06b6d4' : '#94a3b8',
                      background: selectedView === 'patient' ? 'rgba(6,182,212,0.06)' : 'transparent',
                      border: 'none',
                      borderBottom: selectedView === 'patient' ? '2px solid #06b6d4' : '2px solid transparent',
                      cursor: 'pointer', transition: 'all 0.2s',
                    }}
                  >
                    👤 患者视角
                  </button>
                  <button
                    onClick={() => setSelectedView('office')}
                    style={{
                      flex: 1, padding: '10px 16px',
                      fontSize: '13px', fontWeight: selectedView === 'office' ? 600 : 400,
                      color: selectedView === 'office' ? '#a855f7' : '#94a3b8',
                      background: selectedView === 'office' ? 'rgba(168,85,247,0.06)' : 'transparent',
                      border: 'none',
                      borderBottom: selectedView === 'office' ? '2px solid #a855f7' : '2px solid transparent',
                      cursor: 'pointer', transition: 'all 0.2s',
                    }}
                  >
                    🏥 院端视角
                  </button>
                </div>
                {/* 内容区域 */}
                <div style={{
                  padding: '16px', whiteSpace: 'pre-wrap', fontSize: '14px',
                  lineHeight: 1.6, color: '#f1f5f9',
                }}>
                  {selectedView === 'patient'
                    ? (patientView || '暂无患者视角解释。请检查后端服务是否正常运行，或尝试重新提问。')
                    : (officeView || '暂无院端视角解释。请检查后端服务是否正常运行，或尝试重新提问。')}
                </div>
              </div>
            )}

            {/* 加载状态 */}
            {isLoading && steps.length === 0 && (
              <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
                <div
                  style={{
                    borderRadius: '16px',
                    padding: '12px 16px',
                    background: 'rgba(255,255,255,0.03)',
                    border: '1px solid rgba(255,255,255,0.06)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Loader2 className="h-4 w-4 animate-spin" style={{ color: '#06b6d4' }} />
                    <span style={{ fontSize: '14px', color: '#94a3b8' }}>处理中...</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </ScrollArea>

        {/* 输入区域 - 匹配v3原型 */}
        <div style={{ padding: '12px 16px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
          <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '10px' }}>
            <div
              style={{
                flex: 1,
                display: 'flex',
                alignItems: 'center',
                background: 'rgba(15,21,32,0.8)',
                border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: '12px',
                padding: '8px 8px 8px 16px',
                transition: 'border-color 0.25s, box-shadow 0.25s',
              }}
            >
              <Input
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="描述您的问题，例如：统筹自付为什么是4962.67元？"
                disabled={isLoading}
                style={{
                  flex: 1,
                  background: 'transparent',
                  border: 'none',
                  outline: 'none',
                  color: '#f1f5f9',
                  fontSize: '14px',
                  boxShadow: 'none',
                }}
              />
            </div>
            <Button
              type="submit"
              disabled={isLoading || !input.trim()}
              style={{
                background: 'linear-gradient(135deg, #06b6d4, #10b981)',
                borderRadius: '8px',
                width: '40px',
                height: '40px',
                border: 'none',
                cursor: isLoading || !input.trim() ? 'not-allowed' : 'pointer',
                opacity: isLoading || !input.trim() ? 0.5 : 1,
                transition: 'all 0.25s',
              }}
            >
              {isLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </Button>
          </form>
        </div>
      </CardContent>

      {/* 全局动画样式 */}
      <style jsx global>{`
        @keyframes message-in {
          from { opacity: 0; transform: translateY(12px) scale(0.98); }
          to { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes thinking-in {
          from { opacity: 0; transform: translateY(16px) scale(0.97); }
          to { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes pulse-ring {
          0% { box-shadow: 0 0 0 0 rgba(6,182,212,0.4); }
          70% { box-shadow: 0 0 0 10px rgba(6,182,212,0); }
          100% { box-shadow: 0 0 0 0 rgba(6,182,212,0); }
        }
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
      `}</style>
    </Card>
  )
}
