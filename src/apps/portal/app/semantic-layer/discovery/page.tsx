'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Database,
  ScanSearch,
  Loader2,
  ChevronRight,
  ChevronDown,
  CheckCircle2,
  Clock,
  History,
  Search,
  ArrowUpDown,
  PlusCircle,
  X,
  FileSpreadsheet,
  Download,
  Upload,
  Tag,
} from 'lucide-react'
import { semanticReviewJson } from '@/lib/policy-knowledge-api'

// ── Types ───────────────────────────────────────────────────────

interface ScanSampleStats {
  max: string | null
  min: string | null
  top_freq: Array<{ value: string; count: number }> | null
  enum_type: string | null  // "枚举类型" | "海量枚举类型"
  is_long_text: boolean
  non_null_count: number
}

interface ScanResultField {
  field_name: string
  table_name: string
  suggested_object: string | null
  description: string | null
  data_type: string
  non_null_rate: number
  non_null_row_count: number
  distinct_count: number | null
  sample_value: string | null
  sample_values: string[] | null
  sample_stats: ScanSampleStats | null
  is_dictionary: boolean
  last_updated: string | null
  mapped: boolean
  table_schema?: string | null
  is_nullable?: string | null
  is_primary_key: boolean
  remark: string | null
  quality_score: number
  value_score: {
    total: number; grade: string; non_null_score: number; non_null_rate: number
    desc_score: number; has_desc: boolean; sample_score: number; has_sample: boolean
    recency_score: number; last_updated: string | null; usage_score: number; usage_count: number
  } | null
}

interface DiscoveryResultsResponse {
  tables_count: number
  fields_count: number
  mapped_fields: number
  unmapped_fields: number
  fields: ScanResultField[]
}

interface HistoryItem {
  scan_id: string
  started_at: string
  duration_seconds: number | null
  status: string
  tables_scanned: number
  unmapped_found: number
  new_found: number
}

interface ScanProgressEvent {
  table: string
  status: 'scanning' | 'completed' | 'waiting' | 'error'
  fields: number
  new: number
  cached?: boolean
}

interface ScanDoneEvent {
  tables_scanned: number
  unmapped_found: number
  new_found: number
}

interface ScanStatus {
  scan_id: string
  status: string
  start_time: string | null
  last_scan: string | null
  duration_seconds: number | null
}

interface QuickMetricForm {
  name: string
  metric_type: string
  semantic_type: string
  value_domain: string
  unit: string
  object_code: string
}

// ── Constants ───────────────────────────────────────────────────

const API_BASE = '/api/v1/medical-insurance-ai-agent/semantic'
const SCAN_SCOPE_OPTIONS = ['全部已接入表'] as const

const METRIC_TYPE_OPTIONS = ['Atomic', 'Derived'] as const
const SEMANTIC_TYPE_OPTIONS = ['Amount', 'Ratio', 'Enum', 'Date', 'Count'] as const

const SORT_OPTIONS = [
  { value: 'value_score', label: '按价值分' },
  { value: 'non_null_rate', label: '按非空率' },
  { value: 'table', label: '按表' },
] as const

type SortField = (typeof SORT_OPTIONS)[number]['value']

interface EnrichedField extends ScanResultField {
  _expanded: boolean
}

// ── Helpers ─────────────────────────────────────────────────────

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`请求失败 (${res.status})`)
  return res.json() as Promise<T>
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '-'
  if (seconds < 60) return `${seconds.toFixed(0)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}m ${s}s`
}

function formatDateTime(iso: string | null): string {
  if (!iso) return '-'
  try {
    const d = new Date(iso)
    const y = d.getFullYear()
    const mo = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    const h = String(d.getHours()).padStart(2, '0')
    const mi = String(d.getMinutes()).padStart(2, '0')
    const s = String(d.getSeconds()).padStart(2, '0')
    return `${y}-${mo}-${day} ${h}:${mi}:${s}`
  } catch {
    return iso
  }
}

function statusLabel(status: string): string {
  switch (status) {
    case 'completed':
      return '已完成'
    case 'running':
      return '运行中'
    case 'failed':
      return '失败'
    default:
      return status
  }
}

function statusColor(status: string): string {
  switch (status) {
    case 'completed':
      return 'text-emerald-600'
    case 'running':
      return 'text-blue-600'
    case 'failed':
      return 'text-red-600'
    default:
      return 'text-slate-600'
  }
}

function statusBg(status: string): string {
  switch (status) {
    case 'completed':
      return 'bg-emerald-50'
    case 'running':
      return 'bg-blue-50'
    case 'failed':
      return 'bg-red-50'
    default:
      return 'bg-slate-100'
  }
}

function nonNullBarColor(rate: number): string {
  if (rate >= 90) return 'bg-emerald-500'
  if (rate >= 70) return 'bg-blue-500'
  if (rate >= 50) return 'bg-amber-500'
  return 'bg-red-500'
}

// ── SSE Scan Reader ─────────────────────────────────────────────

function readScanSseStream(
  body: ReadableStream<Uint8Array>,
  onProgress: (event: ScanProgressEvent) => void,
  onDone: (event: ScanDoneEvent) => void,
  onError: (err: string) => void,
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  return (async () => {
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          buffer += decoder.decode()
          break
        }
        buffer += decoder.decode(value, { stream: true })
        const chunks = buffer.split(/\r?\n\r?\n/)
        buffer = chunks.pop() ?? ''

        for (const chunk of chunks) {
          const lines = chunk.replace(/\r\n/g, '\n').split('\n')
          let eventType = ''
          const dataLines: string[] = []
          for (const line of lines) {
            if (line.startsWith('event:')) {
              eventType = line.slice('event:'.length).trim()
            } else if (line.startsWith('data:')) {
              dataLines.push(line.slice('data:'.length).trimStart())
            }
          }

          if (!eventType || dataLines.length === 0) continue
          const rawData = dataLines.join('\n').trim()
          if (!rawData) continue

          try {
            const data = JSON.parse(rawData)
            if (eventType === 'progress') {
              onProgress(data as ScanProgressEvent)
            } else if (eventType === 'done') {
              onDone(data as ScanDoneEvent)
            } else if (eventType === 'error') {
              onError((data as { message?: string }).message || '扫描失败')
            }
          } catch {
            // ignore malformed SSE events
          }
        }
      }
    } catch {
      onError('扫描连接中断')
    } finally {
      reader.releaseLock()
    }
  })()
}

// ── Loading Skeleton ────────────────────────────────────────────

function DiscoveryPageSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      {/* Trigger skeleton */}
      <Card className="rounded-2xl border border-slate-200/70 bg-white/80 shadow-sm backdrop-blur">
        <CardContent className="flex items-center justify-between px-5 py-4">
          <div className="flex flex-col gap-2">
            <div className="h-3 w-40 animate-pulse rounded bg-slate-200" />
            <div className="h-3 w-24 animate-pulse rounded bg-slate-200" />
          </div>
          <div className="h-8 w-28 animate-pulse rounded-md bg-slate-200" />
        </CardContent>
      </Card>

      {/* Results skeleton */}
      <Card className="rounded-2xl border border-slate-200/70 bg-white/80 shadow-sm backdrop-blur">
        <CardHeader className="pb-2">
          <div className="h-4 w-32 animate-pulse rounded bg-slate-200" />
        </CardHeader>
        <CardContent className="space-y-3 px-5 py-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="flex items-center gap-4">
              <div className="h-4 w-28 animate-pulse rounded bg-slate-200" />
              <div className="h-3 w-16 animate-pulse rounded bg-slate-200" />
              <div className="h-3 w-24 animate-pulse rounded bg-slate-200" />
              <div className="h-4 w-20 animate-pulse rounded bg-slate-200" />
            </div>
          ))}
        </CardContent>
      </Card>

      {/* History skeleton */}
      <Card className="rounded-2xl border border-slate-200/70 bg-white/80 shadow-sm backdrop-blur">
        <CardHeader className="pb-2">
          <div className="h-4 w-28 animate-pulse rounded bg-slate-200" />
        </CardHeader>
        <CardContent className="space-y-2 px-5 py-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-8 w-full animate-pulse rounded bg-slate-200" />
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

// ── Scan Progress ───────────────────────────────────────────────

function ScanProgressList({
  progressEvents,
  totalTables,
}: {
  progressEvents: Map<string, ScanProgressEvent>
  totalTables: number
}) {
  const entries = Array.from(progressEvents.entries())
  const completedCount = entries.filter(
    ([_, e]) => e.status === 'completed',
  ).length
  const totalFields = entries.reduce((s, [_, e]) => s + e.fields, 0)
  const totalNew = entries.reduce((s, [_, e]) => s + e.new, 0)

  return (
    <div className="space-y-3">
      {/* Summary */}
      <div className="text-xs text-slate-600">
        {completedCount}/{totalTables} 表 · 已发现{' '}
        <span className="font-mono text-slate-700">{totalFields}</span> 个字段
        {totalNew > 0 && (
          <>
            ，其中{' '}
            <span className="font-mono text-cyan-600">{totalNew}</span> 个新字段
          </>
        )}
      </div>

      {/* Per-table progress */}
      <div className="space-y-1.5">
        {entries.map(([table, ev]) => (
          <div
            key={table}
            className="flex items-center justify-between rounded-md border border-slate-200 bg-slate-50 px-3 py-2"
          >
            <div className="flex items-center gap-2">
              {ev.status === 'completed' ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
              ) : ev.status === 'scanning' ? (
                <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
              ) : (
                <Clock className="h-4 w-4 text-slate-400" />
              )}
              <span className="font-mono text-xs text-slate-700">{table}</span>
            </div>
            <div className="flex items-center gap-3 text-[11px] text-slate-500">
              {ev.fields > 0 && <span>{ev.fields} 字段</span>}
              {ev.cached && (
                <Badge variant="outline" className="border-green-200 bg-green-50 text-[10px] text-green-600">缓存</Badge>
              )}
              {ev.new > 0 && (
                <Badge variant="outline" className="border-cyan-200 bg-cyan-50 text-[10px] text-cyan-600">
                  +{ev.new} 新
                </Badge>
              )}
              <span className="text-slate-400">
                {ev.status === 'error' ? '✗' : ev.status === 'completed'
                  ? '✓'
                  : ev.status === 'scanning'
                    ? '⟳'
                    : '⏸'}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Quick Metric Form ───────────────────────────────────────────

function QuickMetricForm({
  field,
  onSuccess,
  onCancel,
}: {
  field: ScanResultField
  onSuccess: () => void
  onCancel: () => void
}) {
  const [form, setForm] = useState<QuickMetricForm>({
    name: field.description || field.field_name,
    metric_type: 'Atomic',
    semantic_type: 'Amount',
    value_domain: '',
    unit: '',
    object_code: field.suggested_object || '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  const handleSubmit = useCallback(async () => {
    setSubmitting(true)
    setError(null)
    try {
      await semanticReviewJson(`${API_BASE}/metrics`, 'POST', {
          name: form.name,
          metric_type: form.metric_type,
          semantic_type: form.semantic_type || null,
          value_domain: form.value_domain || null,
          unit: form.unit || null,
          object_code: form.object_code,
          source_table: field.table_name,
          source_field: field.field_name,
        })
      setSuccess(true)
      setTimeout(() => onSuccess(), 1500)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '创建失败')
    } finally {
      setSubmitting(false)
    }
  }, [form, field, onSuccess])

  if (success) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-600">
        <CheckCircle2 className="h-4 w-4" />
        指标创建成功
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <h4 className="text-xs font-medium text-slate-700">快速创建指标</h4>

      {/* Name */}
      <div>
        <label className="mb-1 block text-[11px] text-slate-500">名称</label>
        <Input
          value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          className="h-7 rounded-md border border-slate-300 bg-white px-2 text-xs text-slate-700 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none"
          placeholder="指标名称"
        />
      </div>

      {/* Type + Semantic Type row */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="mb-1 block text-[11px] text-slate-500">类型</label>
          <select
            value={form.metric_type}
            onChange={(e) => setForm((f) => ({ ...f, metric_type: e.target.value }))}
            className="w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 focus:border-blue-500 focus:outline-none"
          >
            {METRIC_TYPE_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-[11px] text-slate-500">语义类型</label>
          <select
            value={form.semantic_type}
            onChange={(e) => setForm((f) => ({ ...f, semantic_type: e.target.value }))}
            className="w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 focus:border-blue-500 focus:outline-none"
          >
            {SEMANTIC_TYPE_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Value Domain + Unit row */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="mb-1 block text-[11px] text-slate-500">
            值域 <span className="text-slate-400">(可选)</span>
          </label>
          <Input
            value={form.value_domain}
            onChange={(e) => setForm((f) => ({ ...f, value_domain: e.target.value }))}
            className="h-7 rounded-md border border-slate-300 bg-white px-2 text-xs text-slate-700 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none"
            placeholder="如: y/n"
          />
        </div>
        <div>
          <label className="mb-1 block text-[11px] text-slate-500">
            单位 <span className="text-slate-400">(可选)</span>
          </label>
          <Input
            value={form.unit}
            onChange={(e) => setForm((f) => ({ ...f, unit: e.target.value }))}
            className="h-7 rounded-md border border-slate-300 bg-white px-2 text-xs text-slate-700 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none"
            placeholder="如: 元"
          />
        </div>
      </div>

      {/* Object */}
      <div>
        <label className="mb-1 block text-[11px] text-slate-500">归属对象</label>
        <Input
          value={form.object_code}
          onChange={(e) => setForm((f) => ({ ...f, object_code: e.target.value }))}
          className="h-7 rounded-md border border-slate-300 bg-white px-2 text-xs text-slate-700 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none"
          placeholder="对象编码"
        />
      </div>

      {/* Error */}
      {error && (
        <p className="text-[11px] text-red-600">{error}</p>
      )}

      {/* Buttons */}
      <div className="flex items-center gap-2">
        <Button
          variant="default"
          size="sm"
          onClick={handleSubmit}
          disabled={submitting || !form.name.trim() || !form.object_code.trim()}
          className="gap-1 bg-blue-50 text-blue-600 text-xs hover:bg-blue-100"
        >
          {submitting ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <PlusCircle className="h-3 w-3" />
          )}
          创建指标并关联此字段
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onCancel}
          className="text-xs text-slate-500 hover:text-slate-700"
        >
          取消
        </Button>
      </div>
    </div>
  )
}

// ── Sample Value Cell (仅展示样本值示例) ───────────────────────

function SampleValueCell({ field }: { field: ScanResultField }) {
  const stats = field.sample_stats

  // 长文本：截断展示
  if (stats?.is_long_text) {
    const sampleStr = field.sample_value || field.sample_values?.[0] || ''
    return (
      <code className="font-mono text-[10px] text-slate-400 whitespace-nowrap">
        {sampleStr.length > 5 ? sampleStr.slice(0, 5) + '…' : sampleStr || '-'}
      </code>
    )
  }

  const sampleValues = field.sample_values
  if (sampleValues && sampleValues.length > 0) {
    return (
      <div className="flex items-center gap-1 whitespace-nowrap">
        {sampleValues.slice(0, 3).map((sv, i) => (
          <code key={i} className="rounded border border-slate-200 bg-white px-1 py-0.5 font-mono text-[10px] text-slate-500 max-w-[70px] truncate" title={sv}>
            {sv.length > 8 ? sv.slice(0, 8) + '…' : sv}
          </code>
        ))}
        {sampleValues.length > 3 && <span className="text-[10px] text-slate-400">+{sampleValues.length - 3}</span>}
      </div>
    )
  }

  return <span className="text-xs text-slate-400">-</span>
}

// ── 字段分析弹窗 ───────────────────────────────────────────────

function FieldAnalysisModal({ field, onClose }: { field: ScanResultField; onClose: () => void }) {
  const stats = field.sample_stats
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm" onClick={onClose}>
      <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-slate-200 bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-800">{field.field_name}</h3>
            <p className="text-xs text-slate-500">{field.table_name} · {field.data_type}</p>
          </div>
          <button onClick={onClose} className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"><X className="h-4 w-4" /></button>
        </div>

        {/* Body */}
        <div className="grid grid-cols-2 gap-4 px-6 py-4">
          {/* 基本信息 */}
          <div className="col-span-2 space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
            <h4 className="text-[11px] font-medium text-slate-500">基本信息</h4>
            <div className="grid grid-cols-4 gap-2 text-xs">
              <div><span className="text-slate-400">非空行数</span><p className="font-mono text-slate-700">{stats?.non_null_count?.toLocaleString() ?? '-'}</p></div>
              <div><span className="text-slate-400">非空率</span><p className="font-mono text-slate-700">{field.non_null_rate.toFixed(1)}%</p></div>
              <div><span className="text-slate-400">去重计数</span><p className="font-mono text-slate-700">{field.distinct_count?.toLocaleString() ?? '-'}</p></div>
              <div><span className="text-slate-400">是否主键</span><p className="text-slate-700">{field.is_primary_key ? '是' : '否'}</p></div>
            </div>
          </div>

          {/* 枚举类型 */}
          {stats?.enum_type && (
            <div className="col-span-2 space-y-2 rounded-lg border border-purple-200 bg-purple-50 p-3">
              <h4 className="text-[11px] font-medium text-purple-600">值域分类</h4>
              <Badge variant="outline" className={`text-[10px] ${stats.enum_type === '海量枚举类型' ? 'border-orange-200 bg-orange-50 text-orange-600' : 'border-purple-200 bg-purple-50 text-purple-600'}`}>
                {stats.enum_type}（{field.distinct_count} 种不同值）
              </Badge>
            </div>
          )}

          {/* 数值/时间：最大最小值 */}
          {(stats?.max || stats?.min) && (
            <div className="col-span-2 space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
              <h4 className="text-[11px] font-medium text-slate-500">数值范围</h4>
              <div className="flex gap-3">
                {stats.max && <code className="rounded border border-slate-200 bg-white px-2 py-1 font-mono text-xs text-slate-700">最大值: {stats.max}</code>}
                {stats.min && <code className="rounded border border-slate-200 bg-white px-2 py-1 font-mono text-xs text-slate-700">最小值: {stats.min}</code>}
              </div>
            </div>
          )}

          {/* 频率前五 */}
          {stats?.top_freq && stats.top_freq.length > 0 && (
            <div className="col-span-2 space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
              <h4 className="text-[11px] font-medium text-slate-500">频率分布 TOP 5</h4>
              <div className="flex flex-wrap gap-2">
                {stats.top_freq.map((f, i) => (
                  <code key={i} className="rounded border border-blue-200 bg-blue-50 px-2 py-1 font-mono text-[11px] text-blue-700" title={`出现 ${f.count} 次`}>
                    {f.value} <span className="text-blue-400">×{f.count}</span>
                  </code>
                ))}
              </div>
            </div>
          )}

          {/* 样本值 */}
          {field.sample_values && field.sample_values.length > 0 && (
            <div className="col-span-2 space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
              <h4 className="text-[11px] font-medium text-slate-500">样本值（前 {Math.min(20, field.sample_values.length)} / 共 {field.sample_values.length}）</h4>
              <div className="max-h-32 overflow-y-auto flex flex-wrap gap-1">
                {field.sample_values.slice(0, 20).map((sv, i) => (
                  <code key={i} className="rounded border border-slate-200 bg-white px-1.5 py-0.5 font-mono text-[11px] text-slate-600" title={sv}>
                    {stats?.is_long_text && sv.length > 20 ? sv.slice(0, 20) + '…' : sv}
                  </code>
                ))}
              </div>
            </div>
          )}

          {/* 描述 & 备注 */}
          <div className="col-span-2 space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
            <h4 className="text-[11px] font-medium text-slate-500">描述与备注</h4>
            <p className="text-xs text-slate-600">{field.description || <span className="text-slate-400">暂无描述</span>}</p>
            {field.remark && <p className="text-xs text-slate-500">备注: {field.remark}</p>}
          </div>

          {/* 最后修改时间 */}
          {field.last_updated && (
            <div className="col-span-2 text-[11px] text-slate-400">
              最后修改: {formatDateTime(field.last_updated)}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── 编辑字段描述弹窗 ───────────────────────────────────────────

function FieldEditModal({ field, onSave, onClose }: { field: ScanResultField; onSave: (desc: string, remark: string) => void; onClose: () => void }) {
  const [desc, setDesc] = useState(field.description || '')
  const [remark, setRemark] = useState(field.remark || '')
  const [submitting, setSubmitting] = useState(false)

  const handleSave = async () => {
    setSubmitting(true)
    await onSave(desc, remark)
    setSubmitting(false)
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h3 className="text-sm font-semibold text-slate-800">编辑 {field.field_name}</h3>
          <button onClick={onClose} className="rounded-md p-1 text-slate-400 hover:bg-slate-100"><X className="h-4 w-4" /></button>
        </div>
        <div className="space-y-4 px-5 py-4">
          <p className="text-xs text-slate-500">{field.table_name} · {field.data_type}</p>
          <div>
            <label className="mb-1 block text-xs text-slate-500">字段描述</label>
            <Input value={desc} onChange={(e) => setDesc(e.target.value)} className="h-8 rounded-md border border-slate-300 bg-white text-xs" placeholder="输入字段描述" />
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">备注</label>
            <Input value={remark} onChange={(e) => setRemark(e.target.value)} className="h-8 rounded-md border border-slate-300 bg-white text-xs" placeholder="输入备注信息" />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={onClose} className="text-xs">取消</Button>
            <Button size="sm" onClick={handleSave} disabled={submitting || !desc.trim()} className="gap-1 bg-blue-50 text-blue-600 text-xs hover:bg-blue-100">
              {submitting ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
              保存
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Field Expand Detail ─────────────────────────────────────────

function FieldExpandDetail({
  field,
  onMetricCreated,
}: {
  field: ScanResultField
  onMetricCreated: () => void
}) {
  const [showCreateForm, setShowCreateForm] = useState(false)

  return (
    <div className="border-t border-slate-200 bg-slate-50 px-5 py-4">
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        {/* Left: Field Quality */}
        <div className="space-y-3">
          <h4 className="text-xs font-medium text-slate-600">字段质量</h4>

          {/* Non-null rate bar */}
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[11px] text-slate-500">非空率</span>
              <span className="font-mono text-xs tabular-nums text-slate-700">
                {field.non_null_rate.toFixed(1)}%
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
              <div
                className={`h-full rounded-full transition-all ${nonNullBarColor(field.non_null_rate)}`}
                style={{ width: `${field.non_null_rate}%` }}
              />
            </div>
          </div>

          {/* Sample value */}
          {field.sample_value && (
            <div>
              <span className="text-[11px] text-slate-500">样本值</span>
              <div className="mt-0.5 font-mono text-xs text-slate-700">
                {field.sample_value}
              </div>
            </div>
          )}

          {/* Description */}
          <div>
            <span className="text-[11px] text-slate-500">描述</span>
            <div className="mt-0.5 text-xs text-slate-600">
              {field.description || (
                <span className="text-slate-400">暂无描述</span>
              )}
            </div>
          </div>
        </div>

        {/* Right: Quick Metric Create */}
        <div>
          {showCreateForm ? (
            <QuickMetricForm
              field={field}
              onSuccess={() => {
                setShowCreateForm(false)
                onMetricCreated()
              }}
              onCancel={() => setShowCreateForm(false)}
            />
          ) : (
            <div className="flex flex-col items-start gap-3">
              <p className="text-xs text-slate-500">
                此字段尚未关联指标。可快速创建指标并与当前字段关联。
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowCreateForm(true)}
                className="gap-1 border-slate-300 text-xs text-slate-600 hover:text-slate-800"
              >
                <PlusCircle className="h-3 w-3" />
                快速创建指标
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Main Page ───────────────────────────────────────────────────

export default function DiscoveryCenterPage() {
  // ── Scan state ──
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null)
  const [scanning, setScanning] = useState(false)
  const [updating, setUpdating] = useState(false)
  const [scanScope, setScanScope] = useState<string>(SCAN_SCOPE_OPTIONS[0])
  const [progressEvents, setProgressEvents] = useState<Map<string, ScanProgressEvent>>(new Map())
  const [scanDoneData, setScanDoneData] = useState<ScanDoneEvent | null>(null)
  const [scanError, setScanError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  // ── Results state ──
  const [results, setResults] = useState<DiscoveryResultsResponse | null>(null)
  const [resultsLoading, setResultsLoading] = useState(true)
  const [resultsError, setResultsError] = useState<string | null>(null)

  // ── UI state ──
  const [hideLowQuality, setHideLowQuality] = useState(false)
  const [searchText, setSearchText] = useState('')
  const [sortField, setSortField] = useState<SortField>('value_score')
  const [expandedFields, setExpandedFields] = useState<Set<string>>(new Set())
  const [showDataSourceConfig, setShowDataSourceConfig] = useState(false)
  const [metricCreatedTables, setMetricCreatedTables] = useState<Set<string>>(new Set())

  // ── Excel import state ──
  const [showExcelImport, setShowExcelImport] = useState(false)
  const [excelImporting, setExcelImporting] = useState(false)
  const [excelImportResult, setExcelImportResult] = useState<{ imported_count: number; skipped_count?: number; skipped_tables?: string[]; message: string } | null>(null)
  const [excelImportError, setExcelImportError] = useState<string | null>(null)
  const [showSkippedDetail, setShowSkippedDetail] = useState(false)

  // ── Sample limit config ──
  const [sampleLimit, setSampleLimit] = useState(10000)

  // ── Batch mode state ──
  const [batchMode, setBatchMode] = useState(false)
  const [selectedFieldKeys, setSelectedFieldKeys] = useState<Set<string>>(new Set())
  const [batchAssignments, setBatchAssignments] = useState<Map<string, { object_code: string; name: string }>>(new Map())
  const [batchSubmitting, setBatchSubmitting] = useState(false)
  const [batchResult, setBatchResult] = useState<Array<{ index: number; metric_code: string; name: string; status: string; error: string | null }> | null>(null)
  const [objects, setObjects] = useState<Array<{ object_code: string; name: string }>>([])

  // ── Analysis / Edit modal state ──
  const [analyzingField, setAnalyzingField] = useState<ScanResultField | null>(null)
  const [editingField, setEditingField] = useState<ScanResultField | null>(null)

  // ── Pagination ──
  const PAGE_SIZE = 50
  const [currentPage, setCurrentPage] = useState(1)

  // ── Data source config state ──
  const [dataSourceConfig, setDataSourceConfig] = useState<{
    host: string
    port: string
    database: string
    user: string
    password: string
    driver: string
    schema: string
    tables: string
  } | null>(null)

  // Load data source config from localStorage on mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem('discovery_datasource_config')
      if (saved) setDataSourceConfig(JSON.parse(saved))
    } catch {
      // ignore
    }
  }, [])

  const saveDataSourceConfig = (cfg: typeof dataSourceConfig) => {
    setDataSourceConfig(cfg)
    if (cfg) {
      localStorage.setItem('discovery_datasource_config', JSON.stringify(cfg))
    } else {
      localStorage.removeItem('discovery_datasource_config')
    }
  }

  // ── History state ──
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)

  // ── Load initial data ──
  const loadAll = useCallback(async () => {
    setResultsLoading(true)
    setHistoryLoading(true)
    try {
      const [resultsData, historyData] = await Promise.all([
        fetchJson<DiscoveryResultsResponse>(`${API_BASE}/discovery/results`).catch(() => null),
        fetchJson<HistoryItem[]>(`${API_BASE}/discovery/history`).catch(() => []),
      ])
      if (resultsData) setResults(resultsData)
      setHistory(historyData)
    } catch {
      // silent
    } finally {
      setResultsLoading(false)
      setHistoryLoading(false)
    }
  }, [])

  useEffect(() => { void loadAll() }, [loadAll])

  // ── Trigger scan ──
  const startScan = useCallback(async () => {
    setScanning(true)
    setScanError(null)
    setProgressEvents(new Map())
    setScanDoneData(null)

    const controller = new AbortController()
    abortRef.current = controller

    // Build source_config from saved data source config
    const sourceConfig = dataSourceConfig?.database ? {
      sqlserver: {
        host: dataSourceConfig.host || "127.0.0.1",
        port: Number(dataSourceConfig.port) || 1433,
        database: dataSourceConfig.database,
        user: dataSourceConfig.user,
        password: dataSourceConfig.password,
        driver: dataSourceConfig.driver || "ODBC Driver 18 for SQL Server",
        schema: dataSourceConfig.schema || "dbo",
        tables: dataSourceConfig.tables ? dataSourceConfig.tables.split(",").map(s => s.trim()).filter(Boolean) : [],
      },
    } : null

    try {
      const res = await fetch(`${API_BASE}/discovery/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scope: scanScope,
          source_config: sourceConfig,
          sample_limit: sampleLimit,
        }),
        signal: controller.signal,
      })

      if (!res.ok) {
        const errBody = await res.text().catch(() => '')
        throw new Error(`扫描启动失败 (${res.status})${errBody ? `: ${errBody}` : ''}`)
      }

      const initData = (await res.json()) as { task_id: string; status: string }
      const taskId = initData.task_id

      // Connect to SSE stream
      const sseRes = await fetch(`${API_BASE}/discovery/scan/${encodeURIComponent(taskId)}/status`, {
        signal: controller.signal,
      })

      if (!sseRes.ok || !sseRes.body) {
        throw new Error('无法连接扫描状态流')
      }

      await readScanSseStream(
        sseRes.body,
        (progress) => {
          setProgressEvents((prev) => {
            const next = new Map(prev)
            next.set(progress.table, progress)
            return next
          })
        },
        (done) => {
          setScanDoneData(done)
          setScanning(false)
          // Refresh results
          void fetchJson<DiscoveryResultsResponse>(`${API_BASE}/discovery/results`).then(
            (r) => setResults(r),
            () => {},
          )
          // Refresh history
          void fetchJson<HistoryItem[]>(`${API_BASE}/discovery/history`).then(
            (h) => setHistory(h),
            () => {},
          )
        },
        (errMsg) => {
          setScanError(errMsg)
          setScanning(false)
        },
      )
    } catch (err: unknown) {
      if (controller.signal.aborted) return
      setScanError(err instanceof Error ? err.message : '扫描失败')
      setScanning(false)
    }
  }, [scanScope, dataSourceConfig])

  // ── Incremental update ──
  const handleIncrementalUpdate = useCallback(async () => {
    setUpdating(true)
    try {
      await fetch(`${API_BASE}/discovery/incremental-update`, { method: 'POST' })
      await loadAll()
    } catch (err: any) {
      alert(err instanceof Error ? err.message : '增量更新失败')
    }
    setUpdating(false)
  }, [])

  // ── Toggle expand field ──
  const toggleExpand = useCallback((fieldName: string) => {
    setExpandedFields((prev) => {
      const next = new Set(prev)
      if (next.has(fieldName)) {
        next.delete(fieldName)
      } else {
        next.add(fieldName)
      }
      return next
    })
  }, [])

  // ── Load objects list for batch mode ──
  useEffect(() => {
    fetch(`${API_BASE}/objects`)
      .then(r => r.ok ? r.json() : [])
      .then((list: Array<{ object_code: string; name: string }>) => setObjects(list || []))
      .catch(() => {})
  }, [])

  // ── Handle metric created ──
  const handleMetricCreated = useCallback((fieldName: string) => {
    setMetricCreatedTables((prev) => {
      const next = new Set(prev)
      next.add(fieldName)
      return next
    })
  }, [])

  // ── Filter & sort results ──
  const processedFields = useMemo(() => {
    if (!results) return []

    let list = [...results.fields]

    // Hide mapped fields (since they have a metric now)
    list = list.filter((f) => !f.mapped && !metricCreatedTables.has(f.field_name))

    // Hide low non-null rate
    if (hideLowQuality) {
      list = list.filter((f) => f.non_null_rate >= 50)
    }

    // Search
    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase()
      list = list.filter(
        (f) =>
          f.field_name.toLowerCase().includes(q) ||
          f.table_name.toLowerCase().includes(q) ||
          (f.description ?? '').toLowerCase().includes(q),
      )
    }

    // Sort
    list.sort((a, b) => {
      if (sortField === 'value_score') {
        return (b.value_score?.total ?? 0) - (a.value_score?.total ?? 0)
      }
      if (sortField === 'non_null_rate') {
        return b.non_null_rate - a.non_null_rate
      }
      return a.table_name.localeCompare(b.table_name) || a.field_name.localeCompare(b.field_name)
    })

    return list
  }, [results, hideLowQuality, searchText, sortField, metricCreatedTables])

  // ── Pagination derived ──
  const totalPages = Math.max(1, Math.ceil(processedFields.length / PAGE_SIZE))
  const safePage = Math.min(currentPage, totalPages)
  const pagedFields = processedFields.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)

  // Reset to page 1 when filters change
  useEffect(() => { setCurrentPage(1) }, [hideLowQuality, searchText, sortField])

  // ── Loading state ──
  if (resultsLoading && !results) {
    return <DiscoveryPageSkeleton />
  }

  // ── Error state ──
  if (resultsError && !results) {
    return (
      <Alert variant="destructive" className="border-red-200 bg-red-50">
        <AlertTitle className="text-red-600">数据加载失败</AlertTitle>
        <AlertDescription className="text-red-600/80">{resultsError}</AlertDescription>
      </Alert>
    )
  }

  // ── Render ──
  return (<>
    <div className="flex flex-col gap-6">
      {/* ── Section 1: Scan Trigger (compact strip) ─────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200/70 bg-white/80 px-5 py-3 backdrop-blur shadow-sm">
        <div className="flex items-center gap-3 text-xs text-slate-500">
          {history.length > 0 && history[0] ? (
            <>
              <span>上次扫描: <span className="text-slate-600">{formatDateTime(history[0].started_at)}</span></span>
              <span className="text-slate-300">|</span>
              <span>耗时: <span className="font-mono text-slate-600">{formatDuration(history[0].duration_seconds)}</span></span>
              <span className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium ${statusBg(history[0].status)} ${statusColor(history[0].status)}`}>
                {statusLabel(history[0].status)}
              </span>
            </>
          ) : (
            <span>尚未执行过扫描</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <select
            value={scanScope}
            onChange={(e) => setScanScope(e.target.value)}
            disabled={scanning}
            className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-blue-500 focus:outline-none disabled:opacity-50"
          >
            {SCAN_SCOPE_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>

          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowDataSourceConfig((v) => !v)}
            className="gap-1.5 border-slate-300 text-xs text-slate-700 hover:text-slate-900"
          >
            <Database className="h-3.5 w-3.5" />
            数据源
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowExcelImport((v) => !v)}
            className="gap-1.5 border-slate-300 text-xs text-slate-700 hover:text-slate-900"
          >
            <FileSpreadsheet className="h-3.5 w-3.5" />
            导入Excel
          </Button>

          <Button
            variant={batchMode ? "default" : "outline"}
            size="sm"
            onClick={() => { setBatchMode((v) => !v); setSelectedFieldKeys(new Set()); setBatchResult(null) }}
            className={`gap-1.5 text-xs ${batchMode ? 'bg-blue-50 text-blue-600 hover:bg-blue-100' : 'border-slate-300 text-slate-700 hover:text-slate-900'}`}
          >
            <Tag className="h-3.5 w-3.5" />
            {batchMode ? '退出批量' : '批量映射'}
          </Button>

          {/* Sample limit config */}
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-slate-400">样本行数</span>
            <Input
              type="number"
              value={sampleLimit}
              onChange={(e) => setSampleLimit(Number(e.target.value) || 10000)}
              className="h-7 w-20 rounded-md border border-slate-300 bg-white px-2 text-xs text-slate-700 focus:border-blue-500 focus:outline-none"
              min={1}
              max={100000}
            />
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={startScan}
            disabled={scanning}
            className="gap-1.5 border-slate-300 text-xs text-slate-700 hover:text-slate-900"
          >
            {scanning ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <ScanSearch className="h-3.5 w-3.5" />
            )}
            {scanning ? '扫描中...' : '重新扫描'}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={scanning || updating}
            onClick={handleIncrementalUpdate}
            className="h-8 gap-1.5 rounded-lg border-slate-300 bg-white px-3 text-xs text-slate-700 hover:text-blue-600 hover:border-blue-300"
          >
            {updating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <span className="text-sm">🔄</span>
            )}
            {updating ? '更新中...' : '增量更新'}
          </Button>
        </div>
      </div>

      {/* ── Data source config panel ─────────────────────────────── */}
      {showDataSourceConfig && (
        <Card className="rounded-2xl border border-slate-200/70 bg-white/80 shadow-sm backdrop-blur">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm font-medium text-slate-800">
              <Database className="h-4 w-4 text-blue-600" />
              SQL Server 数据源配置
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 px-5 py-4">
            <DataSourceConfigForm
              initial={dataSourceConfig}
              onSave={saveDataSourceConfig}
              onCancel={() => setShowDataSourceConfig(false)}
            />
          </CardContent>
        </Card>
      )}

      {/* ── Excel import panel ────────────────────────────────────── */}
      {showExcelImport && (
        <Card className="rounded-2xl border border-slate-200/70 bg-white/80 shadow-sm backdrop-blur">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm font-medium text-slate-800">
              <FileSpreadsheet className="h-4 w-4 text-green-600" />
              导入字段中文释义
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 px-5 py-4">
            {/* Template download */}
            <div className="flex flex-wrap items-center gap-3">
              <a
                href={`${API_BASE}/field-descriptions/template`}
                download="field_description_template.xlsx"
                className="inline-flex items-center gap-1.5 rounded-md border border-green-300 bg-green-50 px-3 py-1.5 text-xs text-green-700 hover:bg-green-100 transition-colors"
              >
                <Download className="h-3.5 w-3.5" />
                下载模版
              </a>
              <span className="text-[11px] text-slate-400">
                下载标准模版，按格式填写后上传
              </span>
            </div>

            {/* File upload */}
            <div className="flex flex-wrap items-center gap-3">
              <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-blue-300 bg-blue-50 px-3 py-1.5 text-xs text-blue-700 hover:bg-blue-100 transition-colors">
                <Upload className="h-3.5 w-3.5" />
                选择文件
                <input
                  type="file"
                  accept=".xlsx,.xls"
                  className="hidden"
                  onChange={async (e) => {
                    const file = e.target.files?.[0]
                    if (!file) return
                    setExcelImporting(true)
                    setExcelImportError(null)
                    setExcelImportResult(null)
                    try {
                      const formData = new FormData()
                      formData.append('file', file)
                      const res = await fetch(`${API_BASE}/field-descriptions/import`, {
                        method: 'POST',
                        body: formData,
                      })
                      if (!res.ok) {
                        const errBody = await res.json().catch(() => ({ detail: '导入失败' }))
                        throw new Error((errBody as { detail?: string }).detail || '导入失败')
                      }
                      const data = await res.json() as { imported_count: number; message: string }
                      setExcelImportResult(data)
                    } catch (err: unknown) {
                      setExcelImportError(err instanceof Error ? err.message : '导入失败')
                    } finally {
                      setExcelImporting(false)
                    }
                  }}
                />
              </label>
              {excelImporting && (
                <span className="flex items-center gap-1 text-xs text-blue-600">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  导入中...
                </span>
              )}
            </div>

            {/* Result */}
            {excelImportResult && (
              <div className="space-y-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2">
                <div className="flex items-center gap-2 text-xs text-emerald-600">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  <span>成功 <span className="font-semibold">{excelImportResult.imported_count}</span> 条</span>
                  {excelImportResult.skipped_count ? (
                    <>
                      <span className="text-slate-300">|</span>
                      <span className="text-amber-600">跳过 <span className="font-semibold">{excelImportResult.skipped_count}</span> 条</span>
                      <button
                        className="text-blue-500 underline hover:text-blue-700"
                        onClick={() => setShowSkippedDetail((v) => !v)}
                      >
                        {showSkippedDetail ? '收起' : '查看'} ({excelImportResult.skipped_tables?.length || 0} 个未扫描表)
                      </button>
                    </>
                  ) : null}
                </div>
                {showSkippedDetail && excelImportResult.skipped_tables && excelImportResult.skipped_tables.length > 0 && (
                  <div className="max-h-32 overflow-y-auto rounded border border-amber-200 bg-white p-2 text-[10px] text-slate-600">
                    {excelImportResult.skipped_tables.map((t, i) => (
                      <code key={i} className="mr-1.5 mb-1 inline-block rounded bg-amber-50 px-1 py-0.5">{t}</code>
                    ))}
                  </div>
                )}
              </div>
            )}
            {excelImportError && (
              <div className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
                {excelImportError}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Scan progress */}
      {scanning && progressEvents.size > 0 && (
        <Card className="rounded-2xl border border-slate-200/70 bg-white/80 shadow-sm backdrop-blur">
          <CardContent className="px-5 py-4">
            <ScanProgressList
              progressEvents={progressEvents}
              totalTables={
                scanDoneData?.tables_scanned ?? progressEvents.size
              }
            />
          </CardContent>
        </Card>
      )}

      {/* Completion summary */}
      {!scanning && scanDoneData && progressEvents.size > 0 && (
        <div className="flex items-center justify-between rounded-2xl border border-slate-200/70 bg-white/80 px-5 py-3 backdrop-blur shadow-sm">
          <div className="flex items-center gap-2 text-xs text-emerald-600">
            <CheckCircle2 className="h-4 w-4" />
            扫描完成 · {scanDoneData.tables_scanned} 表 ·{' '}
            {scanDoneData.unmapped_found} 未映射 · {scanDoneData.new_found} 新增
          </div>
          <button
            type="button"
            onClick={() => {
              setProgressEvents(new Map())
              setScanDoneData(null)
            }}
            className="text-slate-400 transition-colors hover:text-slate-600"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* Scan error */}
      {scanError && (
        <div className="rounded-2xl border border-red-200/70 bg-red-50/80 px-5 py-3 backdrop-blur shadow-sm">
          <div className="flex items-center gap-2 text-xs text-red-600">
            <span>扫描失败: {scanError}</span>
          </div>
        </div>
      )}

      {/* ── Section 2: Scan Results ────────────────────────────── */}
      <Card className="rounded-2xl border border-slate-200/70 bg-white/80 shadow-sm backdrop-blur">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-slate-800">
            <Database className="h-4 w-4 text-cyan-600" />
            扫描结果
          </CardTitle>
        </CardHeader>

        <CardContent className="space-y-4 px-5 py-4">
          {/* Stat cards */}
          {results && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
                <div className="text-[11px] text-slate-500">已接入表</div>
                <div className="text-xl font-bold tabular-nums text-blue-600">{results.tables_count}</div>
              </div>
              <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
                <div className="text-[11px] text-slate-500">字段总数</div>
                <div className="text-xl font-bold tabular-nums text-slate-700">{results.fields_count}</div>
              </div>
              <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
                <div className="text-[11px] text-slate-500">已映射</div>
                <div className="text-xl font-bold tabular-nums text-emerald-600">{results.mapped_fields}</div>
              </div>
              <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
                <div className="text-[11px] text-slate-500">未映射</div>
                <div className="text-xl font-bold tabular-nums text-amber-600">{results.unmapped_fields}</div>
              </div>
            </div>
          )}

          {/* Batch mode panel */}
          {batchMode && selectedFieldKeys.size > 0 && (
            <div className="rounded-xl border-2 border-blue-300 bg-blue-50/50 p-4 space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Tag className="h-4 w-4 text-blue-600" />
                  <span className="text-sm font-medium text-blue-700">
                    已选 <span className="font-mono">{selectedFieldKeys.size}</span> 个字段
                  </span>
                </div>
                <button
                  onClick={() => { setSelectedFieldKeys(new Set()); setBatchAssignments(new Map()); setBatchResult(null) }}
                  className="text-xs text-slate-500 hover:text-slate-700"
                >
                  清空选择
                </button>
              </div>

              {/* Quick assign: select object for all selected fields */}
              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-500 whitespace-nowrap">统一分配对象:</span>
                <select
                  className="h-8 rounded-md border border-slate-300 bg-white px-2 text-xs text-slate-700 focus:border-blue-500 focus:outline-none"
                  defaultValue=""
                  onChange={(e) => {
                    const oc = e.target.value
                    if (!oc) return
                    const obj = objects.find(o => o.object_code === oc)
                    const next = new Map(batchAssignments)
                    selectedFieldKeys.forEach(k => {
                      const field = processedFields.find(f => `${f.table_name}:${f.field_name}` === k)
                      if (field) next.set(k, { object_code: oc, name: field.description || field.field_name })
                    })
                    setBatchAssignments(next)
                  }}
                >
                  <option value="" disabled>选择对象...</option>
                  {objects.map(obj => (
                    <option key={obj.object_code} value={obj.object_code}>{obj.object_code} - {obj.name}</option>
                  ))}
                </select>
              </div>

              {/* Per-field assignment table */}
              <div className="max-h-64 overflow-y-auto rounded-lg border border-slate-200 bg-white">
                <table className="w-full text-left text-[11px]">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-50 text-slate-500 sticky top-0">
                      <th className="px-3 py-2 font-medium">源字段</th>
                      <th className="px-3 py-2 font-medium">指标名</th>
                      <th className="px-3 py-2 font-medium">归属对象</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Array.from(selectedFieldKeys).map(key => {
                      const field = processedFields.find(f => `${f.table_name}:${f.field_name}` === key)
                      if (!field) return null
                      const assignment = batchAssignments.get(key)
                      return (
                        <tr key={key} className="border-b border-slate-100">
                          <td className="px-3 py-2">
                            <span className="font-mono text-slate-600">{field.table_name}.{field.field_name}</span>
                          </td>
                          <td className="px-3 py-2">
                            <input
                              type="text"
                              className="h-7 w-full rounded border border-slate-300 px-2 text-[11px] text-slate-700 focus:border-blue-500 focus:outline-none"
                              placeholder="指标名称"
                              value={assignment?.name || field.description || field.field_name}
                              onChange={(e) => {
                                const next = new Map(batchAssignments)
                                next.set(key, {
                                  object_code: assignment?.object_code || field.suggested_object || '',
                                  name: e.target.value,
                                })
                                setBatchAssignments(next)
                              }}
                            />
                          </td>
                          <td className="px-3 py-2">
                            <select
                              className="h-7 w-full rounded border border-slate-300 text-[11px] text-slate-700 focus:border-blue-500 focus:outline-none"
                              value={assignment?.object_code || field.suggested_object || ''}
                              onChange={(e) => {
                                const next = new Map(batchAssignments)
                                next.set(key, {
                                  object_code: e.target.value,
                                  name: assignment?.name || field.description || field.field_name,
                                })
                                setBatchAssignments(next)
                              }}
                            >
                              <option value="">未分配</option>
                              {objects.map(obj => (
                                <option key={obj.object_code} value={obj.object_code}>{obj.object_code}</option>
                              ))}
                            </select>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* Action buttons */}
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  onClick={async () => {
                    const items = Array.from(selectedFieldKeys).map(key => {
                      const field = processedFields.find(f => `${f.table_name}:${f.field_name}` === key)!
                      const assignment = batchAssignments.get(key)
                      return {
                        object_code: assignment?.object_code || field.suggested_object || '',
                        name: assignment?.name || field.description || field.field_name,
                        metric_code: field.field_name,
                        definition: field.remark || null,
                        metric_type: 'Atomic' as const,
                        semantic_type: 'Amount' as const,
                        source_table: field.table_name,
                        source_field: `${field.table_name}.${field.field_name}`,
                      }
                    })

                    const invalidItems = items.filter(i => !i.object_code)
                    if (invalidItems.length > 0) {
                      alert(`${invalidItems.length} 个字段未分配对象，请先分配`)
                      return
                    }

                    setBatchSubmitting(true)
                    setBatchResult(null)
                    try {
                      const data = await semanticReviewJson<Array<{ index: number; metric_code: string; name: string; status: string; error: string | null }>>(`${API_BASE}/metrics/batch`, 'POST', { items })
                      setBatchResult(data)
                      if (data.some(d => d.status === 'created')) {
                        // Mark created fields as done locally
                        const created = new Set(metricCreatedTables)
                        data.forEach(d => {
                          if (d.status === 'created' && items[d.index]) {
                            created.add(items[d.index].source_field)
                          }
                        })
                        setMetricCreatedTables(created)
                        setSelectedFieldKeys(new Set())
                        setBatchAssignments(new Map())
                      }
                    } catch (err: any) {
                      alert(err.message || '批量创建失败')
                    } finally {
                      setBatchSubmitting(false)
                    }
                  }}
                  disabled={batchSubmitting || selectedFieldKeys.size === 0}
                  className="gap-1 bg-blue-50 text-blue-600 text-xs hover:bg-blue-100"
                >
                  {batchSubmitting ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <PlusCircle className="h-3 w-3" />
                  )}
                  批量创建指标 ({selectedFieldKeys.size})
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => { setBatchMode(false); setSelectedFieldKeys(new Set()); setBatchAssignments(new Map()); setBatchResult(null) }}
                  className="text-xs text-slate-500 hover:text-slate-700"
                >
                  取消
                </Button>
              </div>

              {/* Batch result */}
              {batchResult && (
                <div className="rounded-md border border-slate-200 bg-white p-3 text-xs">
                  <div className="flex items-center gap-2 mb-2">
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                    <span className="font-medium text-slate-700">批量创建结果</span>
                  </div>
                  <div className="flex gap-3 text-[11px] text-slate-500">
                    <span>成功: <span className="font-mono font-medium text-emerald-600">{batchResult.filter(r => r.status === 'created').length}</span></span>
                    <span>跳过: <span className="font-mono font-medium text-amber-600">{batchResult.filter(r => r.status === 'skipped').length}</span></span>
                    <span>失败: <span className="font-mono font-medium text-red-600">{batchResult.filter(r => r.status === 'error').length}</span></span>
                  </div>
                  {batchResult.filter(r => r.status !== 'created').length > 0 && (
                    <div className="mt-2 max-h-24 overflow-y-auto space-y-0.5">
                      {batchResult.filter(r => r.status !== 'created').map(r => (
                        <div key={r.index} className="text-[10px] text-slate-600">
                          [{r.metric_code}] {r.error}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3">
              {/* Hide low quality checkbox */}
              <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-600">
                <input
                  type="checkbox"
                  checked={hideLowQuality}
                  onChange={(e) => setHideLowQuality(e.target.checked)}
                  className="h-3.5 w-3.5 rounded border-slate-300 bg-white text-blue-600 focus:ring-blue-500/20"
                />
                隐藏非空率&lt;50%
              </label>

              {/* Search */}
              <div className="relative">
                <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-slate-500" />
                <Input
                  type="text"
                  placeholder="搜索字段名/表名..."
                  value={searchText}
                  onChange={(e) => setSearchText(e.target.value)}
                  className="h-7 w-44 rounded-md border border-slate-300 bg-white pl-7 text-xs text-slate-700 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none"
                />
              </div>
            </div>

            <div className="flex items-center gap-2">
              {/* Sort */}
              <div className="flex items-center gap-1.5">
                <ArrowUpDown className="h-3 w-3 text-slate-500" />
                <select
                  value={sortField}
                  onChange={(e) => setSortField(e.target.value as SortField)}
                  className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 focus:border-blue-500 focus:outline-none"
                >
                  {SORT_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>

              {/* Count */}
              <span className="text-xs text-slate-500">
                共{' '}
                <span className="font-mono text-slate-600">
                  {processedFields.length}
                </span>{' '}
                条
              </span>
            </div>
          </div>

          {/* Results Table */}
          {resultsLoading && !results ? (
            <div className="flex items-center justify-center py-8 text-slate-500">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : processedFields.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 py-8 text-slate-500">
              <Database className="h-8 w-8 text-slate-300" />
              <p className="text-sm">
                {results?.fields.length === 0
                  ? '无未映射字段'
                  : '无匹配结果'}
              </p>
            </div>
          ) : (
            <>
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-[11px] text-slate-500">
                    {batchMode && (
                      <th className="px-2.5 py-2 font-medium whitespace-nowrap w-8">
                        <input
                          type="checkbox"
                          checked={processedFields.length > 0 && selectedFieldKeys.size === processedFields.length}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSelectedFieldKeys(new Set(processedFields.map(f => `${f.table_name}:${f.field_name}`)))
                            } else {
                              setSelectedFieldKeys(new Set())
                            }
                          }}
                          className="h-3.5 w-3.5 rounded border-slate-300 text-blue-600"
                        />
                      </th>
                    )}
                    <th className="px-2.5 py-2 font-medium whitespace-nowrap">源表</th>
                    <th className="px-2.5 py-2 font-medium whitespace-nowrap">字段名</th>
                    <th className="px-2.5 py-2 font-medium whitespace-nowrap">主键</th>
                    <th className="px-2.5 py-2 font-medium whitespace-nowrap">字段类型</th>
                    <th className="px-2.5 py-2 font-medium whitespace-nowrap">字段描述</th>
                    <th className="px-2.5 py-2 font-medium whitespace-nowrap">修改时间</th>
                    <th className="px-2.5 py-2 font-medium whitespace-nowrap">备注</th>
                    <th className="px-2.5 py-2 font-medium whitespace-nowrap">非空行数</th>
                    <th className="px-2.5 py-2 font-medium whitespace-nowrap">非空率</th>
                    <th className="px-2.5 py-2 font-medium whitespace-nowrap" title="非空率×50 + 描述0/5/10 + 示例0/10 + 活跃度0-15 + 使用度0-15 | A≥85 B≥70 C≥50 D≥30 E<30">价值分</th>
                    <th className="px-2.5 py-2 font-medium whitespace-nowrap">样本值</th>
                    <th className="px-2.5 py-2 font-medium whitespace-nowrap">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {pagedFields.map((field) => {
                    const isExpanded = expandedFields.has(field.field_name)
                    const compositeKey = `${field.table_name}:${field.field_name}`
                    const isSelected = selectedFieldKeys.has(compositeKey)
                    const stats = field.sample_stats
                    const rows = [
                      <tr
                        key={`${compositeKey}-row`}
                        className={`cursor-pointer border-b border-slate-200 transition-colors ${batchMode ? (isSelected ? 'bg-blue-50' : 'hover:bg-slate-50') : 'hover:bg-slate-50'}`}
                        onClick={() => {
                          if (batchMode) {
                            setSelectedFieldKeys(prev => {
                              const next = new Set(prev)
                              if (next.has(compositeKey)) next.delete(compositeKey)
                              else next.add(compositeKey)
                              return next
                            })
                          } else {
                            toggleExpand(field.field_name)
                          }
                        }}
                      >
                        {batchMode && (
                          <td className="px-2.5 py-2 w-8" onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => {
                                setSelectedFieldKeys(prev => {
                                  const next = new Set(prev)
                                  if (next.has(compositeKey)) next.delete(compositeKey)
                                  else next.add(compositeKey)
                                  return next
                                })
                              }}
                              className="h-3.5 w-3.5 rounded border-slate-300 text-blue-600"
                            />
                          </td>
                        )}
                        {/* 源表 */}
                        <td className="px-2.5 py-2">
                          <span className="font-mono text-[11px] text-slate-600 whitespace-nowrap">{field.table_name}</span>
                        </td>

                        {/* 字段名 */}
                        <td className="px-2.5 py-2">
                          <span className="font-mono text-[11px] text-slate-700 whitespace-nowrap">{field.field_name}</span>
                        </td>

                        {/* 是否主键 */}
                        <td className="px-2.5 py-2">
                          <span className={`text-[11px] whitespace-nowrap ${field.is_primary_key ? 'font-medium text-amber-600' : 'text-slate-400'}`}>
                            {field.is_primary_key ? '是' : '否'}
                          </span>
                        </td>

                        {/* 字段类型 */}
                        <td className="px-2.5 py-2">
                          <span className="font-mono text-[10px] text-slate-500 whitespace-nowrap">{field.data_type}</span>
                        </td>

                        {/* 字段描述 */}
                        <td className="max-w-[140px] truncate px-2.5 py-2">
                          <span className="text-[11px] text-slate-600 whitespace-nowrap">{field.description || <span className="text-slate-400">-</span>}</span>
                        </td>

                        {/* 最后修改时间 */}
                        <td className="px-2.5 py-2">
                          <span className="text-[10px] text-slate-500 whitespace-nowrap tabular-nums">{field.last_updated ? formatDateTime(field.last_updated) : '-'}</span>
                        </td>

                        {/* 备注 */}
                        <td className="max-w-[100px] truncate px-2.5 py-2">
                          <span className="text-[11px] text-slate-500 whitespace-nowrap">{field.remark || '-'}</span>
                        </td>

                        {/* 非空行数 */}
                        <td className="px-2.5 py-2">
                          <span className="font-mono text-[11px] tabular-nums text-slate-600 whitespace-nowrap">{stats?.non_null_count ? stats.non_null_count.toLocaleString() : '-'}</span>
                        </td>

                        {/* 非空率 */}
                        <td className="px-2.5 py-2">
                          <div className="flex items-center gap-1.5 whitespace-nowrap">
                            <div className="h-1.5 w-12 overflow-hidden rounded-full bg-slate-200">
                              <div className={`h-full rounded-full ${nonNullBarColor(field.non_null_rate)}`} style={{ width: `${Math.min(field.non_null_rate, 100)}%` }} />
                            </div>
                            <span className="font-mono text-[11px] tabular-nums text-slate-600">{field.non_null_rate.toFixed(0)}%</span>
                          </div>
                        </td>

                        {/* 价值分 */}
                        <td className="px-2.5 py-2">
                          {field.value_score ? (
                            <span
                              className="inline-flex items-center gap-1 cursor-help"
                              title={`非空率 ${(field.value_score.non_null_rate * 100).toFixed(0)}% → ${field.value_score.non_null_score.toFixed(0)}/50
描述 ${field.value_score.has_desc ? '有' : '无'} → ${field.value_score.desc_score}/10
示例 ${field.value_score.has_sample ? '有' : '无'} → ${field.value_score.sample_score}/10
活跃度 → ${field.value_score.recency_score}/15
使用度 ${field.value_score.usage_count}次 → ${field.value_score.usage_score}/15`}
                            >
                              <span className={`rounded px-1 py-0.5 text-[10px] font-bold ${
                                field.value_score.grade === 'A' ? 'bg-emerald-100 text-emerald-700' :
                                field.value_score.grade === 'B' ? 'bg-blue-100 text-blue-700' :
                                field.value_score.grade === 'C' ? 'bg-amber-100 text-amber-700' :
                                field.value_score.grade === 'D' ? 'bg-orange-100 text-orange-700' :
                                'bg-red-100 text-red-700'
                              }`}>{field.value_score.grade}</span>
                              <span className="font-mono text-[11px] tabular-nums text-slate-600">{field.value_score.total.toFixed(0)}</span>
                            </span>
                          ) : (
                            <span className="text-[10px] text-slate-400">-</span>
                          )}
                        </td>

                        {/* 样本值 */}
                        <td className="max-w-[180px] px-2.5 py-2">
                          <SampleValueCell field={field} />
                        </td>

                        {/* 操作 */}
                        <td className="px-2.5 py-2" onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center gap-1 whitespace-nowrap">
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-6 border-slate-300 px-1.5 text-[10px] text-slate-600 hover:text-slate-800"
                              onClick={() => { setAnalyzingField(field) }}
                            >
                              分析
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-6 border-slate-300 px-1.5 text-[10px] text-slate-600 hover:text-slate-800"
                              onClick={() => { setEditingField(field) }}
                            >
                              编辑
                            </Button>
                          </div>
                        </td>
                      </tr>,
                    ]
                    return rows
                  })}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between pt-3">
                <span className="text-xs text-slate-500">
                  第 <span className="font-mono text-slate-700">{safePage}</span> / {totalPages} 页 · 共 {processedFields.length} 条
                </span>
                <div className="flex items-center gap-1">
                  <Button variant="outline" size="sm" disabled={safePage <= 1} onClick={() => setCurrentPage(1)} className="h-7 border-slate-300 px-2 text-xs text-slate-600">首页</Button>
                  <Button variant="outline" size="sm" disabled={safePage <= 1} onClick={() => setCurrentPage((p) => p - 1)} className="h-7 border-slate-300 px-2 text-xs text-slate-600">上一页</Button>
                  <Button variant="outline" size="sm" disabled={safePage >= totalPages} onClick={() => setCurrentPage((p) => p + 1)} className="h-7 border-slate-300 px-2 text-xs text-slate-600">下一页</Button>
                  <Button variant="outline" size="sm" disabled={safePage >= totalPages} onClick={() => setCurrentPage(totalPages)} className="h-7 border-slate-300 px-2 text-xs text-slate-600">末页</Button>
                </div>
              </div>
            )}
          </>
          )}
        </CardContent>
      </Card>

      {/* ── Section 4: Scan History ────────────────────────────── */}
      <Card className="rounded-2xl border border-slate-200/70 bg-white/80 shadow-sm backdrop-blur">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-slate-800">
            <History className="h-4 w-4 text-purple-600" />
            扫描历史
          </CardTitle>
        </CardHeader>

        <CardContent className="px-5 py-4">
          {historyLoading ? (
            <div className="flex items-center justify-center py-4 text-slate-500">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : history.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 py-6 text-slate-500">
              <History className="h-6 w-6 text-slate-300" />
              <p className="text-sm">暂无扫描历史</p>
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-xs text-slate-500">
                    <th className="px-3 py-2.5 font-medium">时间</th>
                    <th className="px-3 py-2.5 font-medium">状态</th>
                    <th className="px-3 py-2.5 font-medium">扫描表数</th>
                    <th className="px-3 py-2.5 font-medium">未映射字段</th>
                    <th className="px-3 py-2.5 font-medium">新增字段</th>
                    <th className="px-3 py-2.5 font-medium">耗时</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((item) => (
                    <tr
                      key={item.scan_id}
                      className="border-b border-slate-200 transition-colors hover:bg-slate-50"
                    >
                      <td className="px-3 py-3">
                        <span className="text-xs text-slate-700">
                          {formatDateTime(item.started_at)}
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium ${statusBg(item.status)} ${statusColor(item.status)}`}
                        >
                          {statusLabel(item.status)}
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        <span className="font-mono text-xs text-slate-600">
                          {item.tables_scanned}
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        <span className="font-mono text-xs text-amber-600">
                          {item.unmapped_found}
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        <span className="font-mono text-xs text-cyan-600">
                          {item.new_found}
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        <span className="font-mono text-xs text-slate-500">
                          {formatDuration(item.duration_seconds)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>

    {/* 分析弹窗 */}
    {analyzingField && (
      <FieldAnalysisModal field={analyzingField} onClose={() => setAnalyzingField(null)} />
    )}

    {/* 编辑弹窗 */}
    {editingField && (
      <FieldEditModal
        field={editingField}
        onClose={() => setEditingField(null)}
        onSave={async (desc: string, remark: string) => {
          try {
            await fetch(`${API_BASE}/field-descriptions`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                table: editingField.table_name,
                field: editingField.field_name,
                description: desc,
                remark: remark || null,
              }),
            })
            const res = await fetch(`${API_BASE}/discovery/results`)
            if (res.ok) { setResults(await res.json()) }
          } catch { /* silent */ }
        }}
      />
    )}
  </>
)
}

// ── Data Source Config Form ─────────────────────────────────────

function DataSourceConfigForm({
  initial,
  onSave,
  onCancel,
}: {
  initial: {
    host: string
    port: string
    database: string
    user: string
    password: string
    driver: string
    schema: string
    tables: string
  } | null
  onSave: (cfg: {
    host: string
    port: string
    database: string
    user: string
    password: string
    driver: string
    schema: string
    tables: string
  }) => void
  onCancel: () => void
}) {
  const [form, setForm] = useState({
    host: initial?.host || '127.0.0.1',
    port: initial?.port || '1433',
    database: initial?.database || '',
    user: initial?.user || 'sa',
    password: initial?.password || '',
    driver: initial?.driver || 'ODBC Driver 18 for SQL Server',
    schema: initial?.schema || 'dbo',
    tables: initial?.tables || '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  const handleSave = useCallback(async () => {
    if (!form.database.trim()) {
      setError('数据库名不能为空')
      return
    }
    setSaving(true)
    setError(null)
    // Actual connection test happens during scan; just persist here.
    await new Promise((r) => setTimeout(r, 200))
    onSave(form)
    setSuccess(true)
    setTimeout(() => onCancel(), 600)
    setSaving(false)
  }, [form, onSave, onCancel])

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="mb-1 block text-[11px] text-slate-500">主机</label>
          <Input
            value={form.host}
            onChange={(e) => setForm((f) => ({ ...f, host: e.target.value }))}
            className="h-7 rounded-md border border-slate-300 bg-white px-2 text-xs text-slate-700 focus:border-blue-500 focus:outline-none"
            placeholder="127.0.0.1"
          />
        </div>
        <div>
          <label className="mb-1 block text-[11px] text-slate-500">端口</label>
          <Input
            value={form.port}
            onChange={(e) => setForm((f) => ({ ...f, port: e.target.value }))}
            className="h-7 rounded-md border border-slate-300 bg-white px-2 text-xs text-slate-700 focus:border-blue-500 focus:outline-none"
            placeholder="1433"
          />
        </div>
      </div>

      <div>
        <label className="mb-1 block text-[11px] text-slate-500">数据库名 *</label>
        <Input
          value={form.database}
          onChange={(e) => setForm((f) => ({ ...f, database: e.target.value }))}
          className="h-7 rounded-md border border-slate-300 bg-white px-2 text-xs text-slate-700 focus:border-blue-500 focus:outline-none"
          placeholder="hospital_mcp"
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="mb-1 block text-[11px] text-slate-500">用户名</label>
          <Input
            value={form.user}
            onChange={(e) => setForm((f) => ({ ...f, user: e.target.value }))}
            className="h-7 rounded-md border border-slate-300 bg-white px-2 text-xs text-slate-700 focus:border-blue-500 focus:outline-none"
            placeholder="sa"
          />
        </div>
        <div>
          <label className="mb-1 block text-[11px] text-slate-500">密码</label>
          <Input
            type="password"
            value={form.password}
            onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
            className="h-7 rounded-md border border-slate-300 bg-white px-2 text-xs text-slate-700 focus:border-blue-500 focus:outline-none"
            placeholder="••••••"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="mb-1 block text-[11px] text-slate-500">ODBC 驱动</label>
          <Input
            value={form.driver}
            onChange={(e) => setForm((f) => ({ ...f, driver: e.target.value }))}
            className="h-7 rounded-md border border-slate-300 bg-white px-2 text-xs text-slate-700 focus:border-blue-500 focus:outline-none"
            placeholder="ODBC Driver 18 for SQL Server"
          />
        </div>
        <div>
          <label className="mb-1 block text-[11px] text-slate-500">Schema</label>
          <Input
            value={form.schema}
            onChange={(e) => setForm((f) => ({ ...f, schema: e.target.value }))}
            className="h-7 rounded-md border border-slate-300 bg-white px-2 text-xs text-slate-700 focus:border-blue-500 focus:outline-none"
            placeholder="dbo"
          />
        </div>
      </div>

      <div>
        <label className="mb-1 block text-[11px] text-slate-500">
          表名过滤 <span className="text-slate-400">(可选，逗号分隔，空=全部)</span>
        </label>
        <Input
          value={form.tables}
          onChange={(e) => setForm((f) => ({ ...f, tables: e.target.value }))}
          className="h-7 rounded-md border border-slate-300 bg-white px-2 text-xs text-slate-700 focus:border-blue-500 focus:outline-none"
          placeholder="yb_settlement, yb_fee_detail"
        />
      </div>

      {error && <p className="text-[11px] text-red-600">{error}</p>}
      {success && (
        <p className="text-[11px] text-emerald-600">配置已保存，下次扫描将使用此连接</p>
      )}

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          onClick={handleSave}
          disabled={saving}
          className="gap-1 bg-blue-50 text-blue-600 text-xs hover:bg-blue-100"
        >
          {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
          保存配置
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onCancel}
          className="text-xs text-slate-500 hover:text-slate-700"
        >
          取消
        </Button>
      </div>
    </div>
  )
}
