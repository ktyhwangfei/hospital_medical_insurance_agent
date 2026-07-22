'use client'

import { useState, useEffect, useMemo } from 'react'
import { Loader2, ShieldAlert, Box, FileText, ChevronDown, ChevronRight } from 'lucide-react'
import { Badge } from '@/components/ui/badge'

// ── Types ──────────────────────────────────────────────────────────

interface IndicatorDef {
  indicator_id: string; name: string; description: string
  category: 'dimension' | 'numeric' | 'condition' | 'meta'
  unit: string; depends_on: string[]; computation: string | null
}
interface IndResp { indicators: IndicatorDef[]; total: number }

// ── Entity → Indicator 归属 ───────────────────────────────────────

const ENTITY_INDICATORS: Record<string, string[]> = {
  '参保人': ['psn_type', 'insu_type'],
  '结算单': ['setl_type', 'admission_order', 'pooling_pay', 'pooling_self_pay', 'total_fee', 'self_fee', 'first_pay_fee', 'in_scope_total', 'payment_ratio'],
  '医疗机构': ['hosp_lv'],
  '医保政策': ['insu_type', 'med_type', 'payment_ratio', 'deductible_amount', 'cap_amount', 'amount_band', 'time_period', 'rule_type', 'rule_value', 'source_text'],
}

// ── 策略 → 所需语义层指标 ────────────────────────────────────────

interface StrategyConfig {
  label: string; definition: string
  required_indicators: string[]
  policy_indicators: string[]
}

const STRATEGIES: Record<string, StrategyConfig> = {
  deductible: {
    label: '起付线',
    definition: '医保开始报销前需先由个人承担的固定金额，超过起付线后的医保范围内费用才进入统筹基金支付计算。',
    required_indicators: ['insu_type', 'med_type', 'hosp_lv', 'psn_type', 'admission_order', 'deductible_amount'],
    policy_indicators: ['deductible_amount', 'rule_type'],
  },
  pooling_self_pay: {
    label: '统筹自付',
    definition: '基本医保统筹段内按政策比例由个人承担的金额。不包含起付线、大额自付、目录外自费。',
    required_indicators: ['insu_type', 'med_type', 'hosp_lv', 'psn_type', 'deductible_amount', 'in_scope_total', 'pooling_self_pay', 'pooling_pay', 'large_amount_self_pay'],
    policy_indicators: ['payment_ratio', 'amount_band', 'rule_type', 'psn_type'],
  },
  pooling_payment: {
    label: '统筹支付',
    definition: '基本医保统筹基金按政策比例为患者支付的金额。统筹支付 = 统筹范围内费用 - 起付金额 - 统筹自付 - 大额自付（进入大额段前）。',
    required_indicators: ['insu_type', 'med_type', 'hosp_lv', 'psn_type', 'deductible_amount', 'in_scope_total', 'pooling_pay', 'pooling_self_pay', 'large_amount_payment', 'large_amount_self_pay'],
    policy_indicators: ['payment_ratio', 'amount_band', 'rule_type', 'psn_type'],
  },
  personal_total_pay: {
    label: '个人总支付',
    definition: '患者在本次住院中个人承担的全部费用总和。个人总支付 = 起付金额 + 统筹自付 + 大额自付 + 自费费用 + 乙类先行自付（如有）。',
    required_indicators: ['insu_type', 'med_type', 'hosp_lv', 'psn_type', 'total_fee', 'self_fee', 'first_pay_fee', 'deductible_amount', 'pooling_self_pay', 'large_amount_self_pay', 'pooling_pay', 'large_amount_payment'],
    policy_indicators: ['deductible_amount', 'payment_ratio', 'amount_band', 'rule_type', 'psn_type'],
  },
  large_amount_self_pay: {
    label: '大额自付',
    definition: '大额医疗互助基金段内按比例由个人承担的金额。进入大额段后的费用按大额段规则计算。',
    required_indicators: ['insu_type', 'med_type', 'hosp_lv', 'psn_type', 'large_amount_self_pay', 'deductible_amount', 'pooling_self_pay', 'large_amount_payment', 'cap_amount'],
    policy_indicators: ['payment_ratio', 'cap_amount', 'amount_band', 'rule_type', 'psn_type'],
  },
}

// ── Constants ──────────────────────────────────────────────────────

const API = '/api/v1/medical-insurance-ai-agent/semantic-layer'
const CAT_COLORS: Record<string, string> = { dimension: 'border-blue-200 bg-blue-50 text-blue-700', numeric: 'border-orange-200 bg-orange-50 text-orange-700', condition: 'border-purple-200 bg-purple-50 text-purple-700', meta: 'border-slate-200 bg-slate-50 text-slate-600' }
const CAT_LABEL: Record<string, string> = { dimension: '维度', numeric: '数值', condition: '条件', meta: '元数据' }

async function fj<T>(url: string): Promise<T | null> {
  try { const r = await fetch(url); return r.ok ? await r.json() as T : null } catch { return null }
}

// ── 实体归属查找 ──────────────────────────────────────────────────

function findEntity(indicatorId: string): string | null {
  for (const [entity, fields] of Object.entries(ENTITY_INDICATORS)) {
    if (fields.includes(indicatorId)) return entity
  }
  return null
}

// ── Component ──────────────────────────────────────────────────────

export interface SkillQuestionExplainerProps {
  strategies: string[]
}

export default function SkillQuestionExplainer({ strategies }: SkillQuestionExplainerProps) {
  const [indicators, setIndicators] = useState<IndicatorDef[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedLineage, setExpandedLineage] = useState<Record<string, boolean>>({})

  useEffect(() => {
    let c = false
    ;(async () => {
      setLoading(true)
      const ind = await fj<IndResp>(`${API}/indicators`)
      if (!c && ind) setIndicators(ind.indicators ?? [])
      if (!c) setLoading(false)
    })()
    return () => { c = true }
  }, [])

  const byId = useMemo(() => { const m: Record<string, IndicatorDef> = {}; for (const i of indicators) m[i.indicator_id] = i; return m }, [indicators])

  const availableStrategies = strategies.map(s => s.replace(/\/$/, '')).filter(s => s in STRATEGIES)
  if (availableStrategies.length === 0) {
    return <div className="py-12 text-center text-slate-500">此技能包未配置费用项策略。</div>
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 text-xs text-slate-500 bg-blue-50/50 rounded-lg px-4 py-2.5 border border-blue-100">
        <ShieldAlert className="w-3.5 h-3.5 text-blue-500" />
        <span>
          该技能共涵盖 <strong className="text-slate-700">{availableStrategies.length}</strong> 个费用项。
          数据来源于 <strong className="text-slate-700">语义层</strong>（{loading ? '加载中…' : `${indicators.length} 个指标`}）。
        </span>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Loader2 className="size-6 animate-spin text-slate-300" /></div>
      ) : (
        availableStrategies.map(key => {
          const cfg = STRATEGIES[key]
          const reqInds = cfg.required_indicators.map(id => byId[id]).filter(Boolean)
          const polInds = cfg.policy_indicators.map(id => byId[id]).filter(Boolean)

          // Group required indicators by entity
          const byEntity: Record<string, IndicatorDef[]> = {}
          for (const ind of reqInds) {
            const entity = findEntity(ind.indicator_id) ?? '其他'
            if (!byEntity[entity]) byEntity[entity] = []
            byEntity[entity].push(ind)
          }

          return (
            <div key={key} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              {/* Header */}
              <div className="flex items-center gap-2 mb-3">
                <span className="inline-flex h-7 items-center rounded-full bg-blue-50 px-2.5 text-xs font-semibold text-blue-700 ring-1 ring-blue-200/60">{cfg.label}</span>
                <code className="text-[11px] text-slate-400 font-mono">{key}</code>
              </div>
              <p className="text-sm text-slate-600 leading-relaxed mb-4">{cfg.definition}</p>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Left: Required indicators by entity */}
                <div>
                  <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                    <Box className="w-3.5 h-3.5 text-blue-500" />需要的语义层指标
                  </h4>
                  <div className="space-y-2">
                    {Object.entries(byEntity).map(([entity, inds]) => (
                      <div key={entity}>
                        <div className="text-[10px] font-semibold text-slate-400 uppercase mb-1 ml-1">{entity}</div>
                        <div className="space-y-1">
                          {inds.map(ind => {
                            const lineageKey = `${key}:${ind.indicator_id}`
                            const showLineage = expandedLineage[lineageKey] ?? false
                            const hasDep = (ind.depends_on?.length ?? 0) > 0
                            const hasFormula = (ind.computation?.length ?? 0) > 0
                            const hasLineage = hasDep || hasFormula
                            return (
                              <div key={ind.indicator_id}>
                                <button
                                  type="button"
                                  onClick={() => hasLineage && setExpandedLineage(prev => ({ ...prev, [lineageKey]: !showLineage }))}
                                  className={`w-full flex items-center gap-1.5 text-xs py-1 px-2 rounded text-left transition-colors ${hasLineage ? 'hover:bg-slate-50 cursor-pointer' : 'cursor-default'}`}
                                >
                                  {hasLineage ? (showLineage ? <ChevronDown className="size-3 text-slate-400 shrink-0" /> : <ChevronRight className="size-3 text-slate-400 shrink-0" />) : <span className="w-3 shrink-0" />}
                                  <Badge className={`text-[9px] shrink-0 ${CAT_COLORS[ind.category]}`}>{CAT_LABEL[ind.category]}</Badge>
                                  <span className="font-medium text-slate-700">{ind.name}</span>
                                  {ind.unit && <span className="text-[10px] text-slate-400">{ind.unit}</span>}
                                </button>

                                {/* Lineage detail */}
                                {showLineage && hasLineage && (
                                  <div className="ml-6 pl-3 border-l-2 border-slate-200 space-y-1.5 py-1">
                                    {hasDep && (
                                      <div className="rounded bg-slate-50 px-2 py-1 text-[10px]">
                                        <span className="text-slate-400">依赖：</span>
                                        <span className="text-slate-600">{ind.depends_on.map(d => byId[d]?.name ?? d).join('、')}</span>
                                      </div>
                                    )}
                                    {hasFormula && (
                                      <div className="rounded bg-orange-50/50 px-2 py-1 text-[10px]">
                                        <span className="text-slate-400">公式：</span>
                                        <code className="text-orange-700 font-mono">{ind.computation}</code>
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Right: Policy indicators */}
                <div>
                  <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                    <FileText className="w-3.5 h-3.5 text-purple-500" />需要的政策规则指标
                  </h4>
                  <div className="space-y-1">
                    {polInds.map(ind => (
                      <div key={ind.indicator_id} className="flex items-center gap-1.5 text-xs py-1 px-2 rounded bg-purple-50/50">
                        <Badge className={`text-[9px] shrink-0 ${CAT_COLORS[ind.category]}`}>{CAT_LABEL[ind.category]}</Badge>
                        <span className="font-medium text-slate-700">{ind.name}</span>
                        <span className="text-[11px] text-slate-400 ml-auto">{ind.description}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )
        })
      )}
    </div>
  )
}
