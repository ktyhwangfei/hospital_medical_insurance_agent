import type { AgentResponse, Citation, IntentTrace } from '@/lib/types'

// ── Shared UI types ──────────────────────────────────────────

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  fallback?: boolean
  kind?: 'normal' | 'clarification' | 'confirmation'
}

export interface PendingConfirmation {
  taskId: string
  description: string
}

export type StageStatus = 'pending' | 'running' | 'done' | 'blocked'

export interface PipelineStage {
  id: string
  label: string
  description: string
  status: StageStatus
}

export interface IntentCandidateLocal {
  id: string
  label: string
  score: number
  status: '已实现' | '规划中' | '需澄清'
}

export interface RagEvidence {
  title: string
  source: string
  summary: string
  score: number
}

export interface GuideTrace {
  originalQuery: string
  rewrittenQuery: string
  intentLabel: string
  confidence: number
  routeStatus: string
  candidates: IntentCandidateLocal[]
  evidences: RagEvidence[]
  stages: PipelineStage[]
  citations: Citation[]
  auditId?: string
}

// ── Helpers ──────────────────────────────────────────────────

const streamTextFields = ['token', 'delta', 'content', 'text', 'message'] as const

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function hasFallbackFlag(value: unknown): boolean {
  return isRecord(value) && value.fallback === true
}

function streamContent(data: unknown): string {
  if (typeof data === 'string' || typeof data === 'number' || typeof data === 'boolean') {
    return String(data)
  }

  if (isRecord(data)) {
    for (const field of streamTextFields) {
      const value = data[field]
      if (typeof value === 'string') return value
    }
  }

  return ''
}

export function extractContent(result: Record<string, unknown>): string {
  const content = result.content
  if (typeof content === 'string') return content

  if (result.skill_name && result.steps_completed) {
    const outputs = result.outputs as Record<string, unknown> | undefined
    let text = `📋 技能执行完成: ${result.skill_name}\n`
    const steps = result.steps_completed as string[]
    text += `✅ 已完成步骤: ${steps.join(' → ')}\n`
    if (outputs && typeof outputs === 'object') {
      for (const [stepId, stepResult] of Object.entries(outputs)) {
        const sr = stepResult as Record<string, unknown>
        const output = sr.output as Record<string, unknown> | undefined
        if (output && typeof output === 'object' && Object.keys(output).length > 0) {
          text += `\n📌 ${stepId}:\n`
          for (const [key, val] of Object.entries(output)) {
            if (val !== null && val !== undefined && val !== '') {
              text += `  - ${key}: ${typeof val === 'string' ? val : JSON.stringify(val)}\n`
            }
          }
        }
      }
    }
    return text
  }

  if (result.exception_type || result.error_code) {
    let text = '🔍 结算异常分析结果\n\n'
    if (result.error_code) text += `❌ 错误码: ${result.error_code}\n`
    if (result.exception_type) text += `⚠️ 异常类型: ${result.exception_type}\n`
    if (result.error_explanation) text += `📝 说明: ${result.error_explanation}\n`
    if (result.responsible_role) text += `👤 责任角色: ${result.responsible_role}\n`
    const steps = result.recommended_steps as string[] | undefined
    if (steps && steps.length > 0) {
      text += '\n📋 处理建议:\n'
      steps.forEach((s, i) => { text += `  ${i + 1}. ${s}\n` })
    }
    return text
  }

  if (result.qc_recommendation || result.risks) {
    let text = '🏥 出院前质控分析结果\n\n'
    const risks = result.risks as Array<Record<string, unknown>> | undefined
    if (risks && risks.length > 0) {
      text += '⚠️ 风险项:\n'
      risks.forEach((r, i) => {
        text += `  ${i + 1}. [${r.risk_level || '中'}] ${r.risk_type || ''} - ${r.recommendation || ''}\n`
        if (r.responsible_role) text += `     责任角色: ${r.responsible_role}\n`
      })
    }
    if (result.qc_recommendation) text += `\n💡 建议: ${result.qc_recommendation}\n`
    return text
  }

  if (result.message && typeof result.message === 'string') {
    return result.message
  }

  if (content === null || content === undefined) {
    const meaningfulKeys = Object.keys(result).filter(
      (k) => result[k] !== null && result[k] !== undefined && result[k] !== ''
    )
    if (meaningfulKeys.length === 0) return '🤔 未能获取到有效信息，请换个方式提问试试。'
    return JSON.stringify(result, null, 2)
  }

  if (typeof content === 'object' && Object.keys(content as object).length === 0) {
    const resultKeys = Object.keys(result).filter((k) => k !== 'content')
    if (resultKeys.length === 0) return '🤔 未能获取到有效信息，请换个方式提问试试。'
    return JSON.stringify(result, null, 2)
  }

  return JSON.stringify(content, null, 2)
}

export function roleDisplayName(role: string): string {
  const names: Record<string, string> = {
    cashier: '收费员',
    medical_office: '医保办',
    information_department: '信息科',
    medical_record_staff: '病案室',
    clinician: '临床医生',
  }
  return names[role] ?? '院内用户'
}

export function scenarioLabel(scenario?: string | null): string {
  const labels: Record<string, string> = {
    settlement_exception_guidance: '医保结算异常导办',
    pre_discharge_quality_control: '出院前联合质控',
    high_risk_action_confirmation: '高风险动作确认',
    mcp_tool_invocation: 'MCP 工具调用',
    denial_appeal_assistant: '拒付申诉助手',
    policy_rule_explanation: '政策规则解释',
    unknown: '待澄清场景',
  }
  return labels[scenario || 'unknown'] ?? (scenario || '待澄清场景')
}

export function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, value))
}

export function inferIntentLabel(message: string, response?: AgentResponse): string {
  if (response?.scenario) return scenarioLabel(response.scenario)
  if (/出院|质控|风险/.test(message)) return '出院前联合质控'
  if (/拒付|申诉/.test(message)) return '拒付申诉助手'
  if (/政策|规则|目录|报销/.test(message)) return '政策规则解释'
  if (/画图|流程图|drawio|diagram|导出/.test(message)) return 'MCP 工具调用'
  if (/结算|错误码|报错|收费/.test(message)) return '医保结算异常导办'
  return '待澄清场景'
}

function mockCandidates(message: string, response?: AgentResponse): IntentCandidateLocal[] {
  const primary = inferIntentLabel(message, response)
  const base: IntentCandidateLocal[] = [
    { id: 'settlement_exception_guidance', label: '医保结算异常导办', score: 86, status: '已实现' },
    { id: 'pre_discharge_quality_control', label: '出院前联合质控', score: 73, status: '已实现' },
    { id: 'policy_rule_explanation', label: '政策规则解释', score: 58, status: '规划中' },
  ]
  const selected = base.find((item) => item.label === primary)
  if (selected) {
    return [
      { ...selected, score: response?.status === 'needs_clarification' ? 62 : 91 },
      ...base.filter((item) => item.id !== selected.id).slice(0, 2),
    ]
  }
  return [
    { id: 'unknown', label: '需要补充业务场景', score: 45, status: '需澄清' },
    ...base.slice(0, 2),
  ]
}

function evidenceFromResponse(response?: AgentResponse): RagEvidence[] {
  const citations = response?.citations || []
  if (citations.length > 0) {
    return citations.slice(0, 3).map((citation, index) => ({
      title: citation.source_type || `依据 ${index + 1}`,
      source: citation.source_id || 'runtime-citation',
      summary: citation.summary || '系统返回的业务依据',
      score: 88 - index * 6,
    }))
  }
  return [
    {
      title: '意图知识库 · 医保场景边界',
      source: 'intent-knowledge-base',
      summary: '用于区分结算异常、出院质控、政策解释和拒付申诉等入口场景。',
      score: 84,
    },
    {
      title: '运行时上下文 · 当前患者',
      source: 'runtime-context',
      summary: '结合当前角色、患者 P001、就诊 E001 和页面入口补全导办语义。',
      score: 79,
    },
  ]
}

export function buildGuideTrace(message: string, role: string, response?: AgentResponse): GuideTrace {
  const needsClarification = response?.status === 'needs_clarification'
  const waitingConfirmation = response?.status === 'waiting_human_confirmation'
  const blocked = (response?.blocked_actions?.length || 0) > 0
  const intentLabel = inferIntentLabel(message, response)
  const confidence = needsClarification ? 48 : waitingConfirmation ? 89 : response?.status === 'not_implemented' ? 64 : 92

  return {
    originalQuery: message,
    rewrittenQuery: `以${roleDisplayName(role)}身份，围绕当前患者 P001 / E001 处理：${message}`,
    intentLabel,
    confidence,
    routeStatus: needsClarification ? '需要业务澄清' : waitingConfirmation ? '等待人工确认' : response?.status === 'not_implemented' ? '能力未开通' : '已进入导办流程',
    candidates: mockCandidates(message, response),
    evidences: evidenceFromResponse(response),
    stages: [
      { id: 'rewrite', label: 'Query Rewrite', description: '结合角色、患者和页面上下文补全问题', status: 'done' },
      { id: 'retrieval', label: 'RAG 候选召回', description: '召回意图定义、业务术语和场景边界', status: 'done' },
      { id: 'intent', label: 'LLM 意图判别', description: '在候选场景中进行结构化判别', status: needsClarification ? 'blocked' : 'done' },
      { id: 'guardrail', label: '安全与路由校验', description: '检查权限、高风险动作、未开通能力和缺失字段', status: blocked || waitingConfirmation ? 'blocked' : 'done' },
    ],
    citations: response?.citations || [],
    auditId: typeof response?.audit?.workflow_id === 'string' ? response.audit.workflow_id : 'wf-preview-intent',
  }
}
