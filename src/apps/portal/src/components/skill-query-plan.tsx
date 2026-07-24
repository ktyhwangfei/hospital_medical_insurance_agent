'use client'

import { useEffect, useState } from 'react'
import {
  Database, Filter, Layers, Play, Loader2, CheckCircle2, XCircle,
  AlertTriangle, Table2, ArrowRight, GitCompare,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { getSkillQueryPlan, executeSkillQuery, checkSkillConsistency } from '@/lib/api-client'
import type { SkillQueryPlan, SkillQueryExecuteResult, ConsistencyCheckResult } from '@/lib/types'

export interface SkillQueryPlanProps {
  skillId: string
}

export default function SkillQueryPlan({ skillId }: SkillQueryPlanProps) {
  const [plan, setPlan] = useState<SkillQueryPlan | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // 试运行
  const [djh, setDjh] = useState('1')
  const [result, setResult] = useState<SkillQueryExecuteResult | null>(null)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)

  // 一致性验证
  const [consResult, setConsResult] = useState<ConsistencyCheckResult | null>(null)
  const [checking, setChecking] = useState(false)
  const [consError, setConsError] = useState<string | null>(null)

  const loadPlan = () => {
    setLoading(true)
    setError(null)
    getSkillQueryPlan(skillId)
      .then(setPlan)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadPlan() }, [skillId]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleRun = () => {
    if (!djh.trim()) return
    setRunning(true)
    setRunError(null)
    setResult(null)
    executeSkillQuery(skillId, djh.trim())
      .then(setResult)
      .catch((err: Error) => setRunError(err.message))
      .finally(() => setRunning(false))
  }

  const handleConsistency = () => {
    if (!djh.trim()) return
    setChecking(true)
    setConsError(null)
    setConsResult(null)
    checkSkillConsistency(skillId, djh.trim())
      .then(setConsResult)
      .catch((err: Error) => setConsError(err.message))
      .finally(() => setChecking(false))
  }

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="size-6 animate-spin text-slate-300" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="py-8 text-center">
        <p className="text-sm text-red-500 mb-1">查询计划加载失败</p>
        <p className="text-xs text-slate-400 font-mono">{error}</p>
      </div>
    )
  }

  if (!plan) return null

  const nullCount = result?.items.filter(i => i.value === null).length ?? 0
  const gotCount = result ? result.items.length - nullCount : 0

  return (
    <div className="space-y-5">
      {/* 顶部摘要 */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat icon={Layers} color="text-blue-600 bg-blue-50" label="指标总数" value={plan.total_metrics} />
        <Stat icon={CheckCircle2} color="text-emerald-600 bg-emerald-50" label="已映射" value={plan.mapped_count} />
        <Stat icon={Database} color="text-purple-600 bg-purple-50" label="涉及物理表" value={plan.tables.length} />
        <Stat icon={XCircle} color={plan.unmapped_count > 0 ? 'text-red-600 bg-red-50' : 'text-slate-400 bg-slate-50'} label="未映射" value={plan.unmapped_count} />
      </div>

      {/* 行过滤说明 */}
      <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50/50 px-4 py-2.5 text-xs text-amber-700">
        <Filter className="w-3.5 h-3.5 shrink-0" />
        <span>
          行过滤：每张表按物理列 <code className="font-mono text-amber-800">[{plan.filter_column}]</code> 过滤，
          取值来自上下文键 <code className="font-mono text-amber-800">context.{plan.filter_context_key}</code>（医保登记号）
        </span>
      </div>

      {/* 取数计划：按表分组 */}
      <div>
        <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
          <Table2 className="w-3.5 h-3.5 text-blue-500" />取数计划（按物理表批量分组）
        </h4>
        <div className="space-y-2">
          {plan.tables.map((t) => (
            <div key={t.table} className="rounded-lg border border-slate-200 bg-white px-4 py-3">
              <div className="flex items-center gap-2 mb-2">
                <code className="text-sm font-mono font-semibold text-slate-800">{t.table}</code>
                <Badge variant="outline" className="text-[10px] text-slate-500 border-slate-300">
                  {t.columns.length} 列 / 1 次查询
                </Badge>
                <ArrowRight className="w-3 h-3 text-slate-300 ml-auto" />
                <code className="text-[10px] text-slate-400 font-mono">
                  SELECT TOP 1 [{t.columns.join('], [')}] FROM {t.table} WHERE [{plan.filter_column}]=?
                </code>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {t.metrics.map((m) => (
                  <span key={m.metric_code} className="inline-flex items-center gap-1 rounded-md bg-slate-50 px-2 py-1 text-[11px]">
                    <span className="font-medium text-slate-700">{m.name}</span>
                    <code className="text-[10px] text-orange-600 font-mono">{m.column}</code>
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 未映射项 */}
      {plan.unmapped.length > 0 && (
        <div>
          <h4 className="flex items-center gap-1.5 text-xs font-semibold text-red-500 uppercase tracking-wide mb-2">
            <AlertTriangle className="w-3.5 h-3.5" />未映射指标（无法取数）
          </h4>
          <div className="space-y-1">
            {plan.unmapped.map((u) => (
              <div key={u.metric_code} className="rounded-md border border-red-100 bg-red-50/40 px-3 py-1.5 text-xs">
                <code className="font-mono text-red-700">{u.metric_code}</code>
                {u.reason && <span className="text-red-500 ml-2">{u.reason}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 试运行 */}
      <div className="rounded-lg border border-blue-200 bg-blue-50/30 p-4">
        <h4 className="flex items-center gap-1.5 text-xs font-semibold text-blue-700 uppercase tracking-wide mb-3">
          <Play className="w-3.5 h-3.5" />试运行（真实取数）
        </h4>
        <div className="flex items-end gap-2">
          <div className="flex-1 max-w-[200px]">
            <label className="block text-[11px] text-slate-500 mb-1">登记号 djh</label>
            <Input
              value={djh}
              onChange={e => setDjh(e.target.value)}
              placeholder="如：1"
              className="h-8 font-mono text-sm"
              onKeyDown={e => e.key === 'Enter' && handleRun()}
            />
          </div>
          <Button onClick={handleRun} disabled={running || !djh.trim()} size="sm">
            {running ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <Play className="w-3.5 h-3.5 mr-1" />}
            {running ? '执行中...' : '运行'}
          </Button>
          <span className="text-[11px] text-slate-400 ml-2">复用 discovery 的 SQL Server 通道</span>
        </div>

        {runError && (
          <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
            执行失败：{runError}
          </div>
        )}

        {result && (
          <div className="mt-3">
            <div className="flex items-center gap-3 text-[11px] text-slate-500 mb-2">
              <span>取到 <strong className="text-emerald-600">{gotCount}</strong> 个值</span>
              {nullCount > 0 && (
                <span className="text-amber-600">{nullCount} 个为空（该 djh 在对应表无数据或值为 NULL）</span>
              )}
            </div>
            <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-slate-50 text-left text-slate-500">
                    <th className="px-3 py-1.5 font-medium">指标</th>
                    <th className="px-3 py-1.5 font-medium">物理字段</th>
                    <th className="px-3 py-1.5 font-medium text-right">实际值</th>
                  </tr>
                </thead>
                <tbody>
                  {result.items.map(it => (
                    <tr key={it.metric_code} className="border-b last:border-0">
                      <td className="px-3 py-1.5">
                        <span className="font-medium text-slate-700">{it.name}</span>
                        <code className="ml-1.5 text-[10px] text-slate-400 font-mono">{it.metric_code}</code>
                      </td>
                      <td className="px-3 py-1.5">
                        <code className="text-[10px] text-orange-600 font-mono">{it.source_field ?? '—'}</code>
                      </td>
                      <td className={`px-3 py-1.5 text-right font-mono tabular-nums ${it.value === null ? 'text-slate-300' : 'text-slate-800 font-semibold'}`}>
                        {formatValue(it.value)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* 路径一致性验证：语义层 vs business_sql */}
      <div className="rounded-lg border border-purple-200 bg-purple-50/30 p-4">
        <h4 className="flex items-center gap-1.5 text-xs font-semibold text-purple-700 uppercase tracking-wide mb-1">
          <GitCompare className="w-3.5 h-3.5" />路径一致性验证
        </h4>
        <p className="text-[11px] text-slate-500 mb-3">
          对比「语义层动态 SQL」与「现有 business_sql.yaml 手写 JOIN」在同一 djh 下的取数结果，暴露转换差异与 JOIN 过滤差异。
        </p>
        <div className="flex items-center gap-2">
          <Button onClick={handleConsistency} disabled={checking || !djh.trim()} size="sm" variant="outline">
            {checking ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <GitCompare className="w-3.5 h-3.5 mr-1" />}
            {checking ? '校验中...' : `验证 djh=${djh || '?'}`}
          </Button>
        </div>

        {consError && (
          <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">{consError}</div>
        )}

        {consResult && !consResult.supported && (
          <div className="mt-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">
            {consResult.message}
          </div>
        )}

        {consResult?.supported && (
          <div className="mt-3">
            {consResult.business_sql_error ? (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                business_sql 路径不可用：{consResult.business_sql_error}
              </div>
            ) : (
              <>
                <div className="mb-2 flex items-center gap-3 text-[11px]">
                  <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-blue-700 ring-1 ring-blue-200">
                    flat 吻合 {consResult.summary.flat_matched}/{consResult.summary.compared}
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-full bg-purple-50 px-2 py-0.5 text-purple-700 ring-1 ring-purple-200">
                    <GitCompare className="w-3 h-3" />joined 吻合 {consResult.summary.joined_matched}/{consResult.summary.compared}
                  </span>
                </div>
                <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b bg-slate-50 text-left text-slate-500">
                        <th className="px-3 py-1.5 font-medium">指标</th>
                        <th className="px-3 py-1.5 font-medium text-right">语义层 flat</th>
                        <th className="px-3 py-1.5 font-medium text-right">语义层 joined</th>
                        <th className="px-3 py-1.5 font-medium text-right">business_sql</th>
                      </tr>
                    </thead>
                    <tbody>
                      {consResult.items.filter(it => it.compared).map(it => (
                        <tr key={it.metric_code} className="border-b last:border-0">
                          <td className="px-3 py-1.5">
                            <span className="font-medium text-slate-700">{it.name}</span>
                            <code className="ml-1.5 text-[10px] text-slate-400 font-mono">{it.metric_code}</code>
                          </td>
                          <td className={`px-3 py-1.5 text-right font-mono tabular-nums ${it.semantic_value === null ? 'text-slate-300' : 'text-slate-800'}`}>
                            {formatValue(it.semantic_value)}
                          </td>
                          <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                            <span className={it.semantic_joined_value === null ? 'text-slate-300' : 'text-slate-800'}>{formatValue(it.semantic_joined_value)}</span>
                            {it.joined_match
                              ? <CheckCircle2 className="inline w-3 h-3 ml-1 text-purple-500 align-middle" />
                              : <XCircle className="inline w-3 h-3 ml-1 text-red-500 align-middle" />}
                          </td>
                          <td className={`px-3 py-1.5 text-right font-mono tabular-nums ${it.business_sql_value === null ? 'text-slate-300' : 'text-slate-800'}`}>
                            {formatValue(it.business_sql_value)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-2 text-[10px] text-slate-400">
                  <b>flat</b>：每表单独 SELECT（简单通用）； <b>joined</b>：复用 business_sql.yaml 的多表 JOIN（含日期语义条件）。
                  joined 达 100% 吻合即证明语义层能产出与手写 SQL 等价的结果。
                </p>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function Stat({ icon: Icon, color, label, value }: {
  icon: typeof Database; color: string; label: string; value: number
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2.5">
      <div className={`mb-1 inline-flex h-6 w-6 items-center justify-center rounded ${color}`}>
        <Icon className="w-3.5 h-3.5" />
      </div>
      <div className="text-lg font-bold tabular-nums text-slate-800">{value}</div>
      <div className="text-[10px] text-slate-400">{label}</div>
    </div>
  )
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return 'NULL'
  if (typeof v === 'number') return v.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
  return String(v)
}
