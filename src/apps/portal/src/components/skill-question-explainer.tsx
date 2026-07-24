'use client'

import { useState, useEffect, useMemo } from 'react'
import {
  Loader2, ShieldAlert, Box, ChevronDown, ChevronRight,
  Link2, Database, CheckCircle2, AlertTriangle, XCircle,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { getSkillSemanticMetrics, getSemanticMetricDetail } from '@/lib/api-client'
import type { SemanticMetricDetail } from '@/lib/types'

// ── 策略定义：strategy_key → 业务定义 + 所需语义指标（真实编码）────────
// 策略是面向患者的「费用项解释」业务视角；每个策略声明它消费哪些语义层指标。
// 指标编码对齐最新语义层（域→对象→指标），与 skill_manifest.yaml 的 needed_objects 一致。
// [来源: skills/settlement_explain_skill/strategies/ 目录 + 语义层真实指标]

interface StrategyDef {
  label: string
  definition: string
  required_metrics: string[]   // 该策略计算结果直接依赖的指标
  context_metrics: string[]    // 影响该策略取值规则的上下文指标（人群/险种/级别等）
}

const STRATEGY_DEFS: Record<string, StrategyDef> = {
  deductible: {
    label: '起付线',
    definition: '医保开始报销前需先由个人承担的固定金额，超过起付线后的医保范围内费用才进入统筹基金支付计算。',
    required_metrics: ['zydyxx.bcqfje'],
    context_metrics: ['djxx.fund_type', 'djxx.yllb', 'zyjyxx.rylb'],
  },
  pooling_self_pay: {
    label: '统筹自付',
    definition: '基本医保统筹段内按政策比例由个人承担的金额。不包含起付线、大额自付、目录外自费。',
    required_metrics: ['zyfdxx.bdtczf', 'zydyxx.bcybnje'],
    context_metrics: ['zydyxx.bcqfje', 'djxx.fund_type', 'zyjyxx.rylb'],
  },
  pooling_payment: {
    label: '统筹支付',
    definition: '基本医保统筹基金按政策比例为患者支付的金额。',
    required_metrics: ['zyfdxx.bdtczfje', 'zyfdxx.bdtczf'],
    context_metrics: ['zydyxx.bcqfje', 'djxx.fund_type'],
  },
  large_amount_self_pay: {
    label: '大额自付',
    definition: '大额医疗互助基金段内按比例由个人承担的金额。进入大额段后的费用按大额段规则计算。',
    required_metrics: ['zyfdxx.bddezf', 'zyfdxx.bddezfje'],
    context_metrics: ['zydyxx.bcqfje', 'zyfdxx.bdtczf', 'djxx.fund_type'],
  },
  personal_total_pay: {
    label: '个人总支付',
    definition: '患者在本次住院中个人承担的全部费用总和（起付 + 统筹自付 + 大额自付 + 自费等）。',
    required_metrics: ['zyfdxx.bdgryf', 'zydyxx.bcqfje', 'zyfdxx.bdtczf', 'zyfdxx.bddezf'],
    context_metrics: ['djxx.fund_type', 'zyjyxx.rylb'],
  },
  out_of_scope: {
    label: '自费/目录外',
    definition: '医保目录范围外、完全由个人承担的费用。费用明细级别逐项累计。',
    required_metrics: ['zyfymx.ybwje', 'zyfymx.ybnje'],
    context_metrics: ['djxx.fund_type'],
  },
}

// ── 对象编码 → 中文名（与语义层一致）──────────────────────────────

const OBJECT_NAMES: Record<string, string> = {
  zydyxx: '住院待遇',
  zyfdxx: '住院分段',
  zyjyxx: '住院交易',
  djxx: '参保人登记',
  zyfymx: '住院费用明细',
}

const DOMAIN_NAMES: Record<string, string> = {
  ybdy: '医保待遇',
  ybjs: '医保结算',
  ybml: '医保目录',
}

// ── 映射状态判定（与后端 _is_mapped / 前端 determineMappingStatus 对齐）────

type MappingStatus = 'mapped' | 'value-missing' | 'unmapped'

function mappingStatus(m: SemanticMetricDetail): MappingStatus {
  if (!m.source_field) return 'unmapped'
  if (m.semantic_type === 'Enum' && !m.value_domain) return 'value-missing'
  return 'mapped'
}

const STATUS_META: Record<MappingStatus, { label: string; icon: typeof CheckCircle2; cls: string }> = {
  mapped: { label: '已映射', icon: CheckCircle2, cls: 'text-emerald-600 bg-emerald-50' },
  'value-missing': { label: '值域缺失', icon: AlertTriangle, cls: 'text-amber-600 bg-amber-50' },
  unmapped: { label: '未映射', icon: XCircle, cls: 'text-red-600 bg-red-50' },
}

function objectName(code: string): string {
  return OBJECT_NAMES[code] ?? code
}

function domainOf(objectCode: string): string {
  // zydyxx/djxx/zyjyxx → ybdy；zyfdxx/zyfymx → ybjs
  if (['zyfdxx', 'zyfymx'].includes(objectCode)) return DOMAIN_NAMES.ybjs
  if (['ypml'].includes(objectCode)) return DOMAIN_NAMES.ybml
  return DOMAIN_NAMES.ybdy
}

// ── Component ──────────────────────────────────────────────────────

export interface SkillQuestionExplainerProps {
  skillId: string
  strategies: string[]
}

export default function SkillQuestionExplainer({ skillId, strategies }: SkillQuestionExplainerProps) {
  const [details, setDetails] = useState<Record<string, SemanticMetricDetail | null>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getSkillSemanticMetrics(skillId)
      .then(async (metrics) => {
        // 拉取每个指标的详情（映射/质量/值域状态）
        const entries = await Promise.all(
          metrics.map(async (m) => {
            try {
              const d = await getSemanticMetricDetail(m.metric_code)
              return [m.metric_code, d] as const
            } catch {
              return [m.metric_code, null] as const
            }
          })
        )
        if (!cancelled) {
          setDetails(Object.fromEntries(entries))
          setLoading(false)
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message)
          setLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [skillId])

  const availableStrategies = useMemo(
    () => strategies.map(s => s.replace(/\/$/, '')).filter(s => s in STRATEGY_DEFS),
    [strategies]
  )

  const metricCount = Object.keys(details).length
  const objectCount = new Set(Object.values(details).filter(Boolean).map(d => d!.object_code)).size

  const detailByCode = (code: string) => details[code] ?? null

  const toggle = (key: string) => setExpanded(prev => ({ ...prev, [key]: !prev[key] }))

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3 text-xs text-slate-500 bg-blue-50/50 rounded-lg px-4 py-2.5 border border-blue-100">
          <ShieldAlert className="w-3.5 h-3.5 text-blue-500" />
          <span>正在从语义层加载技能引用的指标…</span>
        </div>
        <div className="flex justify-center py-12"><Loader2 className="size-6 animate-spin text-slate-300" /></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="py-8 text-center">
        <p className="text-sm text-red-500 mb-1">语义层加载失败</p>
        <p className="text-xs text-slate-400 font-mono">{error}</p>
        <p className="text-xs text-slate-400 mt-2">请确认语义层服务可用，且 skill_manifest.yaml 的 needed_objects 已对齐真实指标编码。</p>
      </div>
    )
  }

  if (availableStrategies.length === 0) {
    return <div className="py-12 text-center text-slate-500">此技能包未配置费用项策略。</div>
  }

  return (
    <div className="space-y-4">
      {/* 顶部摘要 */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 bg-blue-50/50 rounded-lg px-4 py-2.5 border border-blue-100">
        <ShieldAlert className="w-3.5 h-3.5 text-blue-500" />
        <span>
          该技能涵盖 <strong className="text-slate-700">{availableStrategies.length}</strong> 个费用项，
          消费语义层 <strong className="text-slate-700">{metricCount}</strong> 个指标，
          覆盖 <strong className="text-slate-700">{objectCount}</strong> 个业务对象。
        </span>
        {metricCount === 0 && (
          <span className="text-amber-600">（指标为空：请检查 manifest 的 needed_objects 是否对齐语义层编码）</span>
        )}
      </div>

      {availableStrategies.map(key => {
        const cfg = STRATEGY_DEFS[key]
        const isOpen = expanded[key] ?? false
        const reqMet = cfg.required_metrics.map(detailByCode).filter(Boolean) as SemanticMetricDetail[]
        const ctxMet = cfg.context_metrics.map(detailByCode).filter(Boolean) as SemanticMetricDetail[]
        // 按对象分组
        const byObject: Record<string, SemanticMetricDetail[]> = {}
        for (const m of reqMet) {
          (byObject[m.object_code] ??= []).push(m)
        }

        return (
          <div key={key} className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
            {/* 策略头 */}
            <button
              type="button"
              onClick={() => toggle(key)}
              className="w-full flex items-center gap-2 px-5 py-3.5 text-left hover:bg-slate-50 transition-colors"
            >
              {isOpen ? <ChevronDown className="w-4 h-4 text-slate-400 shrink-0" />
                : <ChevronRight className="w-4 h-4 text-slate-400 shrink-0" />}
              <span className="inline-flex h-7 items-center rounded-full bg-blue-50 px-2.5 text-xs font-semibold text-blue-700 ring-1 ring-blue-200/60">
                {cfg.label}
              </span>
              <code className="text-[11px] text-slate-400 font-mono">{key}</code>
              <span className="ml-auto flex items-center gap-2 text-[10px] text-slate-400">
                <span>{cfg.required_metrics.length} 指标</span>
                {reqMet.length > 0 && (
                  <span className="text-emerald-500">{reqMet.filter(m => mappingStatus(m) === 'mapped').length}/{reqMet.length} 已映射</span>
                )}
              </span>
            </button>

            {!isOpen && <div className="px-5 pb-3 -mt-1 text-sm text-slate-600 leading-relaxed">{cfg.definition}</div>}

            {isOpen && (
              <div className="px-5 pb-5 space-y-4">
                <p className="text-sm text-slate-600 leading-relaxed">{cfg.definition}</p>

                {/* 左：计算所需指标（按对象分组） */}
                <div>
                  <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                    <Box className="w-3.5 h-3.5 text-blue-500" />计算所需指标（来自语义层）
                  </h4>
                  {reqMet.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-amber-200 bg-amber-50/40 px-3 py-2 text-xs text-amber-600">
                      所需指标尚未在语义层声明：{cfg.required_metrics.join('、')}
                      <span className="block mt-0.5 text-amber-500/80">请确认 skill_manifest.yaml 的 needed_objects 已包含这些指标。</span>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {Object.entries(byObject).map(([objCode, inds]) => (
                        <div key={objCode}>
                          <div className="flex items-center gap-1.5 text-[10px] font-semibold text-slate-400 uppercase mb-1 ml-1">
                            <Link2 className="w-3 h-3" />
                            {objectName(objCode)}
                            <span className="text-slate-300 normal-case font-normal">· {domainOf(objCode)}</span>
                          </div>
                          <div className="space-y-1">
                            {inds.map(m => <MetricRow key={m.metric_code} m={m} />)}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* 右：上下文指标 */}
                {ctxMet.length > 0 && (
                  <div>
                    <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                      <Database className="w-3.5 h-3.5 text-purple-500" />影响取值的上下文指标
                    </h4>
                    <div className="flex flex-wrap gap-1.5">
                      {ctxMet.map(m => (
                        <span key={m.metric_code} className="inline-flex items-center gap-1 rounded-md bg-purple-50/60 px-2 py-1 text-xs">
                          <span className="font-medium text-slate-700">{m.name}</span>
                          <code className="text-[10px] text-slate-400">{m.metric_code}</code>
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── 单指标行 ──────────────────────────────────────────────────────

function MetricRow({ m }: { m: SemanticMetricDetail }) {
  const status = mappingStatus(m)
  const meta = STATUS_META[status]
  const StatusIcon = meta.icon
  return (
    <div className="flex items-center gap-2 rounded-md border border-slate-100 bg-white px-2.5 py-1.5 text-xs">
      <StatusIcon className={`w-3.5 h-3.5 shrink-0 ${meta.cls.split(' ')[0]}`} />
      <span className="font-medium text-slate-700">{m.name}</span>
      <code className="text-[10px] text-slate-400 font-mono">{m.metric_code}</code>
      {m.semantic_type && (
        <Badge variant="outline" className="text-[9px] border-slate-300 text-slate-500 px-1">{m.semantic_type}</Badge>
      )}
      {m.source_field && (
        <code className="text-[10px] text-orange-600 bg-orange-50/60 px-1 py-0.5 rounded font-mono ml-auto" title="物理来源字段">
          {m.source_field}
        </code>
      )}
      <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-medium ${meta.cls}`}>
        {meta.label}
      </span>
    </div>
  )
}
