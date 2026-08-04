'use client'

import { useState, useMemo } from 'react'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import {
  ChevronDown,
  ChevronRight,
  BookOpen,
  Calculator,
  AlertTriangle,
  User,
  Circle,
  CheckCircle2,
  Database,
} from 'lucide-react'
import type {
  SettlementExplanationData,
  CaseContext,
  ProfileValue,
  OutputGroupValue,
  OutputItemValue,
} from '@/lib/settlement-explanation-types'
import { normalizeExplanationResult } from '@/lib/dedup'

/* ============================================================
   SettlementExplanationPage — 展示配置驱动的单模式解释页面（Light Theme）

   布局（自上而下，无 Tab 切换）:
   1. ProfileCard         — 参保信息卡（「您的参保信息」）
   2. ConclusionArea      — AI 生成结论（patient_answer + ✨ badge）
   3. OutputGroupsSection — 费用输出分组表格
   4. CollapsibleSection  — 政策依据 + 计算过程（默认折叠）
   5. DataTraceAccordion  — 数据追溯（默认折叠）
   6. WarningCard         — 重要提示
   ============================================================ */

// ── 工具函数 ──────────────────────────────────────────────────

/** 格式化金额（千分位，保留两位小数），0/null/undefined/NaN 返回'未获取' */
function formatMoney(value: number | undefined | null): string {
  if (value == null || isNaN(Number(value))) return '未获取'
  const num = Number(value)
  if (num === 0) return '未获取'
  return num.toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

/** 结算上下文字段 → 中文标签（仅供 DataTraceAccordion 使用） */
const FACT_LABELS: Record<keyof CaseContext, string> = {
  person_type: '人员类别',
  insurance_type: '险种类型',
  service_type: '医疗类别',
  hospital_level: '医院等级',
  deductible: '起付线',
  medical_insurance_inner_amount: '医保内费用',
  basic_pooling_payment: '统筹支付',
  basic_pooling_self_pay: '统筹自付',
  large_amount_payment: '大额支付',
  large_amount_self_pay: '大额自付',
  personal_total_pay: '个人总支付',
}

// ── 动画样式 ──────────────────────────────────────────────────

const PAGE_ANIMATIONS = `
@keyframes fade-in {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes scale-in {
  from { opacity: 0; transform: scale(0.92); }
  to   { opacity: 1; transform: scale(1); }
}
`

// ── 向后兼容：从 case_context 推导 Profile 数据 ──────────────

const DEFAULT_PROFILE_CONFIG = [
  { field: 'person_type', label: '人员类别' },
  { field: 'insurance_type', label: '参保类型' },
  { field: 'service_type', label: '医疗类别' },
  { field: 'hospital_level', label: '医院等级' },
]

function deriveProfile(context: CaseContext): ProfileValue[] {
  return DEFAULT_PROFILE_CONFIG.map((cfg) => ({
    field: cfg.field,
    label: cfg.label,
    value: String(context[cfg.field as keyof CaseContext] ?? ''),
  }))
}

// ── 向后兼容：从 case_context 推导 Output 分组 ───────────────

const DEFAULT_OUTPUT_GROUPS: Array<{
  group: string
  fields: Array<{
    field: keyof CaseContext
    label: string
    hint?: string
    highlight?: boolean
  }>
}> = [
  {
    group: '医保帮您付的',
    fields: [
      { field: 'basic_pooling_payment', label: '统筹基金支付' },
      { field: 'large_amount_payment', label: '大额基金支付' },
    ],
  },
  {
    group: '您个人承担的',
    fields: [
      { field: 'deductible', label: '起付线', hint: '报销门槛' },
      { field: 'basic_pooling_self_pay', label: '统筹自付', hint: '统筹段按比例', highlight: true },
      { field: 'large_amount_self_pay', label: '大额自付', hint: '大额段按比例' },
    ],
  },
  {
    group: '合计',
    fields: [
      { field: 'personal_total_pay', label: '个人总支付', hint: '以上合计' },
    ],
  },
]

function deriveOutputGroups(data: SettlementExplanationData): OutputGroupValue[] {
  return DEFAULT_OUTPUT_GROUPS.map((g) => ({
    group: g.group,
    items: g.fields.map((f) => ({
      label: f.label,
      value: Number(data.case_context?.[f.field] ?? 0),
      format: 'money' as const,
      hint: f.hint,
      highlight: f.highlight,
    })),
  }))
}

// ── Compare mode helpers ───────────────────────────────────────

interface CompareProfileSet {
  label?: string
  items: ProfileValue[]
}

/** 从数据中提取比较模式的 profile 集合（type-safe runtime access） */
function getCompareProfile(data: SettlementExplanationData): CompareProfileSet[] {
  const profile = (data as any).profile
  if (Array.isArray(profile) && profile.length > 0 && 'items' in profile[0]) {
    return profile as CompareProfileSet[]
  }
  return []
}

/** 从数据中提取比较模式的 output_groups 集合 */
function getCompareOutputGroups(data: SettlementExplanationData): OutputGroupValue[][] {
  const groups = (data as any).output_groups
  if (Array.isArray(groups) && groups.length > 0 && Array.isArray(groups[0])) {
    return groups as OutputGroupValue[][]
  }
  return []
}

/** 从数据中提取比较信息（diff_summary） */
function getComparison(data: SettlementExplanationData): { diff_summary?: string } | undefined {
  return (data as any).comparison
}

// ═══════════════════════════════════════════════════════════════
// ProfileCard — 您的参保信息
// ═══════════════════════════════════════════════════════════════

function ProfileCard({ data }: { data: SettlementExplanationData }) {
  // profile 运行期可能是 { items: [...] } 对象（比较模式），类型定义未覆盖 → 与本文件
  // getCompareProfile 一致使用运行时断言访问，随后由 deriveProfile 防御性回退
  const profileItems = (data as unknown as { profile?: { items?: ProfileValue[] } }).profile?.items
  const items = profileItems ?? deriveProfile(data.case_context)

  return (
    <div
      className="bg-white border border-slate-200 rounded-xl overflow-hidden"
      style={{ animation: 'fade-in 0.4s ease-out' }}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-5 py-3.5 border-b border-slate-200">
        <User className="w-4 h-4 text-[#2563EB]" />
        <span className="text-sm font-semibold text-[#111827]">您的参保信息</span>
        <Badge
          variant="outline"
          className="ml-auto bg-[#2563EB]/10 border-[#2563EB]/25 text-[#2563EB] text-[10px]"
        >
          {items.length} 项
        </Badge>
      </div>

      {/* Profile items */}
      <div className="px-5 py-4 space-y-0">
        {items.map((item) => (
          <div
            key={item.field}
            className="flex items-center justify-between py-2.5 border-b border-slate-100 last:border-b-0"
          >
            <span className="text-sm text-slate-500">{item.label}</span>
            <span className="text-sm font-medium text-slate-900">{item.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// ConclusionArea — AI 生成结论（支持双视角切换：患者 / 院端）
// ═══════════════════════════════════════════════════════════════

const DUAL_VIEW_TABS = [
  { key: 'patient' as const, label: '患者视角' },
  { key: 'office' as const, label: '院端视角' },
] as const

function ConclusionArea({ data }: { data: SettlementExplanationData }) {
  const [selectedView, setSelectedView] = useState<'patient' | 'office'>('patient')

  if (!data.patient_answer && !data.office_answer) return null

  // 仅单视角时直接展示，不显示 tab
  const hasPatient = !!data.patient_answer
  const hasOffice = !!data.office_answer
  const showTabs = hasPatient && hasOffice

  const currentAnswer = selectedView === 'patient' ? data.patient_answer : data.office_answer

  return (
    <div
      className="bg-white border border-slate-200 rounded-xl overflow-hidden"
      style={{ animation: 'fade-in 0.4s ease-out 0.05s both' }}
    >
      {/* Header with AI badge + tabs */}
      <div className="flex items-center gap-2 px-5 py-3.5 border-b border-slate-200">
        <Badge
          variant="outline"
          className="bg-purple-50 border-purple-200 text-purple-600 text-[10px]"
        >
          ✨ AI 生成
        </Badge>

        {showTabs && (
          <div className="flex gap-1 ml-4">
            {DUAL_VIEW_TABS.map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setSelectedView(tab.key)}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                  selectedView === tab.key
                    ? 'bg-[#2563EB] text-white'
                    : 'text-slate-500 hover:text-slate-700 hover:bg-slate-100'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Conclusion content */}
      <div className="px-5 py-4">
        <StructuredText text={currentAnswer || ''} />
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// OutputGroupsSection — 费用输出分组表格
// ═══════════════════════════════════════════════════════════════

function OutputGroupsSection({ data }: { data: SettlementExplanationData }) {
  const groups = data.output_groups ?? deriveOutputGroups(data)
  if (groups.length === 0) return null

  return (
    <div
      className="bg-white border border-slate-200 rounded-xl overflow-hidden"
      style={{ animation: 'fade-in 0.4s ease-out 0.1s both' }}
    >
      <div className="divide-y divide-slate-200">
        {groups.map((group) => (
          <div key={group.group}>
            {/* Group header */}
            <div className="px-5 py-3 bg-slate-50 border-b border-slate-200">
              <span className="text-sm font-semibold text-[#111827]">{group.group}</span>
            </div>

            {/* Group items */}
            <div className="px-5 py-1">
              {group.items.map((item) => (
                <OutputItemRow key={item.label} item={item} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** 单行输出项 */
function OutputItemRow({ item }: { item: OutputItemValue }) {
  const valueStr =
    item.format === 'money'
      ? `¥${formatMoney(item.value)}`
      : String(item.value)

  return (
    <div
      className={cn(
        'flex items-center justify-between py-2.5 px-3 rounded-lg -mx-3 my-1.5 transition-colors',
        item.highlight
          ? 'bg-amber-50 border border-amber-200'
          : 'border border-transparent',
      )}
    >
      <div className="flex items-center gap-1.5">
        <span
          className={cn(
            'text-sm',
            item.highlight ? 'font-semibold text-[#111827]' : 'text-slate-600',
          )}
        >
          {item.label}
          {item.highlight && <span className="text-amber-500 ml-1">★</span>}
        </span>
      </div>
      <div className="text-right">
        <span
          className={cn(
            'text-sm font-mono tabular-nums',
            item.highlight
              ? 'font-bold text-[#D97706]'
              : 'font-medium text-slate-900',
          )}
        >
          {valueStr}
        </span>
        {item.hint && (
          <div className="text-[10px] text-slate-400 leading-tight">
            {item.hint}
          </div>
        )}
      </div>
    </div>
  )
}

// ── 结构化文本解析 ──────────────────────────────────────────

/** 将含【】段落头的文本解析为结构化段 */
function parseStructuredText(
  text: string,
): Array<{ type: 'header' | 'content'; lines: string[] }> {
  const sections: Array<{
    type: 'header' | 'content'
    lines: string[]
  }> = []
  let current: { type: 'header' | 'content'; lines: string[] } | null = null

  for (const line of text.split('\n')) {
    const trimmed = line.trim()
    const isHeader = trimmed.startsWith('【') && trimmed.endsWith('】')

    if (isHeader) {
      if (current) sections.push(current)
      current = { type: 'header', lines: [trimmed] }
      sections.push(current)
      current = { type: 'content', lines: [] }
    } else {
      if (!current) {
        current = { type: 'content', lines: [] }
      }
      current.lines.push(line)
    }
  }
  if (current) sections.push(current)
  return sections
}

/** 渲染结构化段落文本 */
function StructuredText({ text }: { text: string }) {
  const sections = parseStructuredText(text)
  return (
    <div className="space-y-2">
      {sections.map((section, idx) => {
        if (section.type === 'header') {
          return (
            <div
              key={idx}
              className="text-sm font-bold text-[#2563EB] mt-3 first:mt-0"
            >
              {section.lines[0]}
            </div>
          )
        }
        // Content section: filter trailing empty lines
        const contentLines = section.lines.join('\n').trimEnd()
        if (!contentLines) return null
        return (
          <div
            key={idx}
            className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap"
          >
            {contentLines}
          </div>
        )
      })}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// PolicyEvidenceCard — 政策依据（移入折叠区域）
// ═══════════════════════════════════════════════════════════════

function PolicyEvidenceCard({ data }: { data: SettlementExplanationData }) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(0)

  // ★ Empty state: 无政策依据时渲染提示卡片（非 null）
  if (data.policy_evidence.length === 0) {
    return (
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-200">
          <BookOpen className="w-4 h-4 text-[#D97706]" />
          <span className="text-sm font-semibold text-[#111827]">政策依据</span>
          <Badge
            variant="outline"
            className="ml-auto bg-amber-50 border-amber-200 text-[#D97706] text-[10px]"
          >
            0 条
          </Badge>
        </div>
        <div className="px-4 py-4">
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
            <p className="text-sm text-[#D97706] leading-relaxed">
              暂未检索到可引用政策依据。当前页面仅完成真实结算数据解释，完整政策分段计算需接入政策依据后展示。
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-200">
        <BookOpen className="w-4 h-4 text-[#2563EB]" />
        <span className="text-sm font-semibold text-[#111827]">政策依据</span>
        <Badge
          variant="outline"
          className="ml-auto bg-[#2563EB]/10 border-[#2563EB]/25 text-[#2563EB] text-[10px]"
        >
          {data.policy_evidence.length} 条
        </Badge>
      </div>

      {/* Evidence list */}
      <div className="px-4 py-3 space-y-2">
        {data.policy_evidence.map((item, idx) => {
          const isOpen = expandedIndex === idx

          return (
            <div
              key={idx}
              className="rounded-lg border border-slate-200 bg-white overflow-hidden"
            >
              <button
                type="button"
                className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-slate-50 transition-colors text-left"
                onClick={() => setExpandedIndex(isOpen ? null : idx)}
              >
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  {isOpen ? (
                    <ChevronDown className="w-3 h-3 text-slate-500 shrink-0" />
                  ) : (
                    <ChevronRight className="w-3 h-3 text-slate-500 shrink-0" />
                  )}
                  <span className="text-[13px] text-slate-900 font-medium truncate">
                    {item.policy_title}
                  </span>
                </div>
                <Badge
                  variant="outline"
                  className="bg-[#2563EB]/10 border-[#2563EB]/20 text-[#2563EB] text-[10px] px-1.5 py-0 shrink-0 ml-2"
                >
                  政策
                </Badge>
              </button>

              {isOpen && (
                <div className="px-3 pb-3 space-y-3 border-t border-slate-200">
                  <div className="mt-2">
                    <div className="text-[10px] text-slate-500 mb-1">条文原文</div>
                    <pre className="font-mono text-[10px] text-slate-700 bg-slate-50 border border-slate-200 rounded-lg p-2.5 whitespace-pre-wrap leading-relaxed max-h-[140px] overflow-y-auto m-0">
                      {item.clause_text}
                    </pre>
                  </div>
                  {item.rule_tags.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {item.rule_tags.map((tag) => (
                        <Badge
                          key={tag}
                          variant="outline"
                          className="bg-[#2563EB]/8 border-[#2563EB]/20 text-[#2563EB]/70 text-[9px] px-1.5 py-0"
                        >
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  )}
                  <div className="flex items-start gap-2 text-[11px]">
                    <span className="text-slate-500 shrink-0 mt-0.5">
                      适用说明:
                    </span>
                    <span className="text-[#2563EB]/80 leading-relaxed">
                      {item.applied_reason}
                    </span>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// CalculationTraceCard — 计算过程时间线（移入折叠区域）
// ═══════════════════════════════════════════════════════════════

function CalculationTraceCard({ data }: { data: SettlementExplanationData }) {
  const TECHNICAL_KEYWORDS = ['待接入', 'RAG', '权威值', 'Milvus']
  const allSteps = data.calculation_trace.steps
  const steps = allSteps.filter(
    (s) =>
      !TECHNICAL_KEYWORDS.some(
        (kw) => s.step_name.includes(kw) || s.description.includes(kw),
      ),
  )
  if (steps.length === 0) return null

  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-200">
        <Calculator className="w-4 h-4 text-[#059669]" />
        <span className="text-sm font-semibold text-[#111827]">计算过程</span>
        <Badge
          variant="outline"
          className="ml-auto bg-[#059669]/10 border-[#059669]/25 text-[#059669] text-[10px]"
        >
          {steps.length} 步
        </Badge>
      </div>

      {/* Method statement */}
      {data.calculation_trace.method &&
        !data.calculation_trace.method.includes('待接入') &&
        !data.calculation_trace.method.includes('RAG') &&
        !data.calculation_trace.method.includes('Milvus') &&
        !data.calculation_trace.method.includes('权威值') && (
          <div className="px-4 pt-3 pb-1">
            <div className="flex items-center gap-2 text-[11px] text-slate-500 bg-slate-50 rounded-lg px-3 py-2 border border-slate-200">
              <span className="font-medium text-slate-600">计算方法:</span>
              <span className="font-mono text-slate-600">
                {data.calculation_trace.method}
              </span>
            </div>
          </div>
        )}

      {/* Timeline */}
      <div className="px-4 py-3">
        <div className="relative">
          <div className="absolute left-[15px] top-2 bottom-2 w-px bg-slate-200" />

          {steps.map((step, idx) => {
            const isLast = idx === steps.length - 1
            return (
              <div key={idx} className="relative flex gap-4 pb-5 last:pb-0">
                <div className="relative z-10 flex-shrink-0 mt-0.5">
                  {isLast ? (
                    <Circle className="w-[14px] h-[14px] text-[#2563EB] fill-[#2563EB]/20" />
                  ) : (
                    <CheckCircle2 className="w-[14px] h-[14px] text-[#059669]" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span
                      className={cn(
                        'text-[11px] font-semibold',
                        isLast ? 'text-[#2563EB]' : 'text-[#059669]',
                      )}
                    >
                      步骤 {idx + 1}
                    </span>
                    <span className="text-[12px] text-slate-900 font-medium">
                      {step.step_name}
                    </span>
                    {isLast && (
                      <Badge
                        variant="outline"
                        className="bg-[#2563EB]/10 border-[#2563EB]/20 text-[#2563EB] text-[9px] px-1.5 py-0"
                      >
                        结果
                      </Badge>
                    )}
                  </div>
                  <p className="text-[12px] text-slate-600 leading-relaxed">
                    {step.description}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// CollapsibleSection — 政策依据 · 计算过程（默认折叠）
// ═══════════════════════════════════════════════════════════════

function CollapsibleSection({ data }: { data: SettlementExplanationData }) {
  const [isOpen, setIsOpen] = useState(false)

  const hasPolicy = data.policy_evidence.length > 0
  const hasCalculation =
    data.calculation_trace?.steps?.length > 0
  if (!hasPolicy && !hasCalculation) return null

  return (
    <div
      className="bg-white border border-slate-200 rounded-xl overflow-hidden"
      style={{ animation: 'fade-in 0.4s ease-out 0.15s both' }}
    >
      <button
        type="button"
        className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-slate-50 transition-colors text-left"
        onClick={() => setIsOpen(!isOpen)}
      >
        <div className="flex items-center gap-2">
          {isOpen ? (
            <ChevronDown className="w-3.5 h-3.5 text-slate-500" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 text-slate-500" />
          )}
          <span className="text-sm font-medium text-[#111827]">
            政策依据 · 计算过程
          </span>
          <Badge
            variant="outline"
            className="bg-slate-100 border-slate-200 text-slate-500 text-[10px]"
          >
            {[hasPolicy && '政策', hasCalculation && '计算'].filter(Boolean).join(' + ')}
          </Badge>
        </div>
        <span className="text-[10px] text-slate-400">
          {isOpen ? '收起' : '展开'}
        </span>
      </button>

      {isOpen && (
        <div className="border-t border-slate-200 space-y-4 p-4">
          {hasPolicy && <PolicyEvidenceCard data={data} />}
          {hasCalculation && <CalculationTraceCard data={data} />}
        </div>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// WarningCard — 重要提示
// ═══════════════════════════════════════════════════════════════

function WarningCard({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null

  return (
    <div
      className="bg-white border border-slate-200 rounded-xl overflow-hidden"
      style={{ animation: 'fade-in 0.4s ease-out 0.25s both' }}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-200">
        <AlertTriangle className="w-4 h-4 text-[#D97706]" />
        <span className="text-sm font-semibold text-[#111827]">重要提示</span>
        <Badge
          variant="outline"
          className="ml-auto bg-amber-50 border-amber-200 text-[#D97706] text-[10px]"
        >
          {warnings.length} 项
        </Badge>
      </div>

      {/* Warning list */}
      <div className="px-4 py-3">
        <ul className="space-y-2.5">
          {warnings.map((warning, idx) => (
            <li key={idx} className="flex items-start gap-2.5">
              <span className="text-[#D97706] mt-0.5 shrink-0 text-[11px] font-mono font-bold">
                {idx + 1}.
              </span>
              <span className="text-sm text-slate-600 leading-relaxed">
                {warning}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// DataTraceAccordion — 数据追溯（默认折叠）
// ═══════════════════════════════════════════════════════════════

function DataTraceAccordion({ data }: { data: SettlementExplanationData }) {
  const [isOpen, setIsOpen] = useState(false)

  return (
    <div
      className="bg-white border border-slate-200 rounded-xl overflow-hidden"
      style={{ animation: 'fade-in 0.4s ease-out 0.3s both' }}
    >
      <button
        type="button"
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-50 transition-colors text-left"
        onClick={() => setIsOpen(!isOpen)}
      >
        <div className="flex items-center gap-2">
          {isOpen ? (
            <ChevronDown className="w-3.5 h-3.5 text-slate-500" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 text-slate-500" />
          )}
          <Database className="w-4 h-4 text-slate-500" />
          <span className="text-sm font-medium text-[#111827]">数据追溯</span>
          <Badge
            variant="outline"
            className="bg-slate-100 border-slate-200 text-slate-500 text-[10px]"
          >
            技术详情
          </Badge>
        </div>
        <span className="text-[10px] text-slate-400 font-mono">
          {isOpen ? '收起' : '展开'}
        </span>
      </button>

      {isOpen && (
        <div className="px-4 pb-4 space-y-3 border-t border-slate-200">
          <div className="mt-3">
            <div className="text-[10px] text-slate-500 mb-1.5">查询数据表</div>
            <div className="flex flex-wrap gap-1.5">
              {data.query_trace?.tables?.map((table) => (
                <Badge
                  key={table}
                  variant="outline"
                  className="bg-slate-50 border-slate-200 text-slate-600 text-[11px] font-mono"
                >
                  {table}
                </Badge>
              )) || (
                <span className="text-[11px] text-slate-400">无表信息</span>
              )}
            </div>
          </div>

          <div>
            <div className="text-[10px] text-slate-500 mb-1.5">SQL Profile</div>
            <pre className="font-mono text-[10px] text-slate-600 bg-slate-50 border border-slate-200 rounded-lg p-2.5 whitespace-pre-wrap m-0">
              {data.query_trace?.sql_profile || '未提供'}
            </pre>
          </div>

          <div className="flex items-center gap-3 text-[11px]">
            <span className="text-slate-500">数据来源:</span>
            <span
              className="font-mono font-semibold"
              style={{
                color: data.data_source === 'REAL_DB' ? '#059669' : '#d97706',
              }}
            >
              {data.data_source || 'UNKNOWN'}
            </span>
            {data.mock_used !== undefined && (
              <span
                className="font-mono"
                style={{ color: data.mock_used ? '#d97706' : '#059669' }}
              >
                mock_used={String(data.mock_used)}
              </span>
            )}
          </div>

          <div>
            <div className="text-[10px] text-slate-500 mb-1.5">关键字段来源</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
              {Object.keys(FACT_LABELS)
                .slice(0, 6)
                .map((key) => (
                  <div key={key} className="flex justify-between">
                    <span className="text-slate-500">
                      {FACT_LABELS[key as keyof CaseContext]}
                    </span>
                    <span className="text-slate-600 font-mono text-[10px]">
                      结算表
                    </span>
                  </div>
                ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// Compare mode: Profile card (single, with diff highlight)
// ═══════════════════════════════════════════════════════════════

function CompareProfileCard({
  items,
  label,
  diffFields,
}: {
  items: ProfileValue[]
  label: string
  diffFields: Set<string>
}) {
  return (
    <div
      className="bg-white border border-slate-200 rounded-xl overflow-hidden"
      style={{ animation: 'fade-in 0.4s ease-out' }}
    >
      {/* Label header */}
      <div className="px-5 py-3 bg-slate-50 border-b border-slate-200 text-center">
        <span className="text-sm font-semibold text-[#111827]">{label}</span>
      </div>

      {/* Profile items */}
      <div className="px-5 py-4 space-y-0">
        {items.map((item) => {
          const isDiff = diffFields.has(item.field)
          return (
            <div
              key={item.field}
              className={cn(
                'flex items-center justify-between py-2.5 border-b border-slate-100 last:border-b-0',
                isDiff && 'bg-amber-50 -mx-5 px-5',
              )}
            >
              <span className="text-sm text-slate-500">{item.label}</span>
              <span className="text-sm font-medium text-slate-900">
                {item.value}
                {isDiff && <span className="text-amber-500 ml-1">★</span>}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// Compare mode: Profile section (two cards side by side)
// ═══════════════════════════════════════════════════════════════

function CompareProfileSection({ data }: { data: SettlementExplanationData }) {
  const profileSets = getCompareProfile(data)
  if (profileSets.length < 2) return null

  const [primary, secondary] = profileSets

  // Find fields that differ between the two profiles
  const primaryMap = new Map(primary.items.map((i) => [i.field, i.value]))
  const secondaryMap = new Map(secondary.items.map((i) => [i.field, i.value]))
  const allFields = new Set([...primaryMap.keys(), ...secondaryMap.keys()])
  const diffFields = new Set<string>()
  allFields.forEach((f) => {
    if (primaryMap.get(f) !== secondaryMap.get(f)) {
      diffFields.add(f)
    }
  })

  return (
    <div
      className="grid grid-cols-2 gap-4"
      style={{ animation: 'fade-in 0.4s ease-out' }}
    >
      <CompareProfileCard
        items={primary.items}
        label={primary.label || '本次'}
        diffFields={diffFields}
      />
      <CompareProfileCard
        items={secondary.items}
        label={secondary.label || '上次'}
        diffFields={diffFields}
      />
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// Compare mode: Diff summary card
// ═══════════════════════════════════════════════════════════════

function DiffSummaryCard({ summary }: { summary: string }) {
  return (
    <div
      className="bg-amber-50 border border-amber-200 rounded-xl p-4"
      style={{ animation: 'fade-in 0.4s ease-out 0.05s both' }}
    >
      <div className="flex items-start gap-2.5">
        <AlertTriangle className="w-4 h-4 text-[#D97706] mt-0.5 shrink-0" />
        <p className="text-sm text-[#92400E] leading-relaxed">{summary}</p>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// Compare mode: Fee comparison table
// ═══════════════════════════════════════════════════════════════

function FeeComparisonTable({ data }: { data: SettlementExplanationData }) {
  const outputGroupSets = getCompareOutputGroups(data)
  if (outputGroupSets.length < 2) return null

  const [primaryGroups, secondaryGroups] = outputGroupSets

  // Flatten all items from all groups
  const primaryItems = primaryGroups.flatMap((g) => g.items)
  const secondaryItems = secondaryGroups.flatMap((g) => g.items)

  const secondaryMap = new Map(secondaryItems.map((i) => [i.label, i.value]))
  const secondaryHighlightMap = new Map(
    secondaryItems.map((i) => [i.label, i.highlight]),
  )

  // Build rows from primary items, matching by label
  const rows: Array<{
    label: string
    primaryValue: number
    secondaryValue: number
    diff: number
    highlight?: boolean
  }> = []

  const seenLabels = new Set<string>()

  for (const item of primaryItems) {
    const secondaryVal = secondaryMap.get(item.label) ?? 0
    rows.push({
      label: item.label,
      primaryValue: item.value,
      secondaryValue: secondaryVal,
      diff: item.value - secondaryVal,
      highlight: item.highlight || secondaryHighlightMap.get(item.label),
    })
    seenLabels.add(item.label)
  }

  // Add items only present in secondary
  for (const item of secondaryItems) {
    if (!seenLabels.has(item.label)) {
      rows.push({
        label: item.label,
        primaryValue: 0,
        secondaryValue: item.value,
        diff: -item.value,
        highlight: item.highlight,
      })
    }
  }

  const fmt = (v: number) =>
    `¥${v.toLocaleString('zh-CN', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`

  const fmtDiff = (v: number) =>
    `${v >= 0 ? '+' : ''}${v.toLocaleString('zh-CN', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`

  return (
    <div
      className="bg-white border border-slate-200 rounded-xl overflow-hidden"
      style={{ animation: 'fade-in 0.4s ease-out 0.1s both' }}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-5 py-3.5 border-b border-slate-200">
        <span className="text-sm font-semibold text-[#111827]">费用对比</span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-200">
              <th className="text-left px-5 py-3 text-xs font-medium text-slate-500">
                费用项
              </th>
              <th className="text-right px-4 py-3 text-xs font-medium text-slate-500">
                本次
              </th>
              <th className="text-right px-4 py-3 text-xs font-medium text-slate-500">
                上次
              </th>
              <th className="text-right px-5 py-3 text-xs font-medium text-slate-500">
                差额
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.label}
                className={cn(
                  'border-b border-slate-100 last:border-b-0',
                  row.highlight && 'bg-amber-50',
                )}
              >
                <td className="px-5 py-3">
                  <span
                    className={cn(
                      'text-sm',
                      row.highlight
                        ? 'font-semibold text-[#111827]'
                        : 'text-slate-900',
                    )}
                  >
                    {row.label}
                  </span>
                  {row.highlight && (
                    <span className="text-amber-500 ml-1 text-xs">★</span>
                  )}
                </td>
                <td className="px-4 py-3 text-right font-mono tabular-nums text-sm text-slate-900">
                  {fmt(row.primaryValue)}
                </td>
                <td className="px-4 py-3 text-right font-mono tabular-nums text-sm text-slate-900">
                  {fmt(row.secondaryValue)}
                </td>
                <td
                  className={cn(
                    'px-5 py-3 text-right font-mono tabular-nums text-sm font-medium',
                    row.diff > 0
                      ? 'text-red-600'
                      : row.diff < 0
                        ? 'text-green-600'
                        : 'text-slate-500',
                  )}
                >
                  {fmtDiff(row.diff)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// Main Component
// ═══════════════════════════════════════════════════════════════

export interface SettlementExplanationPageProps {
  data: SettlementExplanationData
  className?: string
}

/**
 * SettlementExplanationPage — 展示配置驱动的解释页面（Light Theme）
 *
 * 支持两种模式:
 * - single (默认):  ProfileCard → ConclusionArea → OutputGroupsSection → Collapsible → DataTrace → Warning
 * - compare:        CompareProfileSection → DiffSummaryCard → FeeComparisonTable → Collapsible → DataTrace → Warning
 *
 * 数据在渲染前通过 normalizeExplanationResult 去重。
 * 展示配置字段（profile / output_groups / display_config / mode）为可选，
 * 未提供时自动从 case_context 推导以保持向后兼容。
 */
export default function SettlementExplanationPage({
  data: rawData,
  className,
}: SettlementExplanationPageProps) {
  // 渲染前去重
  const data = useMemo(() => normalizeExplanationResult(rawData), [rawData])

  const isCompareMode = data.mode === 'compare'

  return (
    <div
      className={cn('space-y-4', className)}
      style={{ maxWidth: 1280, margin: '0 auto' }}
    >
      <style>{PAGE_ANIMATIONS}</style>

      {isCompareMode ? (
        <>
          {/* 1. 两栏参保信息对比 */}
          <CompareProfileSection data={data} />

          {/* 2. 差异摘要 */}
          {getComparison(data)?.diff_summary && (
            <DiffSummaryCard summary={getComparison(data)!.diff_summary!} />
          )}

          {/* 3. 费用对比表格 */}
          <FeeComparisonTable data={data} />

          {/* 4. 政策依据 · 计算过程（默认折叠） */}
          <CollapsibleSection data={data} />

          {/* 5. 数据追溯（默认折叠） */}
          <DataTraceAccordion data={data} />

          {/* 6. 重要提示 */}
          <WarningCard warnings={data.warnings} />
        </>
      ) : (
        <>
          {/* 1. 参保信息卡片 */}
          <ProfileCard data={data} />

          {/* 2. AI 生成结论 */}
          <ConclusionArea data={data} />

          {/* 3. 费用输出分组表格 */}
          <OutputGroupsSection data={data} />

          {/* 4. 政策依据 · 计算过程（默认折叠） */}
          <CollapsibleSection data={data} />

          {/* 5. 数据追溯（默认折叠） */}
          <DataTraceAccordion data={data} />

          {/* 6. 重要提示 */}
          <WarningCard warnings={data.warnings} />
        </>
      )}
    </div>
  )
}
