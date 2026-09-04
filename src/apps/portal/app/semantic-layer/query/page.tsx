'use client'

import { useEffect, useMemo, useState } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { semanticReviewJson } from '@/lib/policy-knowledge-api'
import { Loader2, Play, Plus, ShieldCheck, Trash2, Database } from 'lucide-react'

const API = '/api/v1/medical-insurance-ai-agent/semantic'

interface ObjectSummary { object_code: string; name: string; current_version: string | null }
interface Dataset { dataset_code: string; name: string }
interface DatasetKey { key_code: string; dataset_code: string; entity_code: string; key_type: string; columns: string[] }
interface SemanticField { field_code: string; dataset_code: string; column_name: string; name: string; field_role: 'identifier' | 'dimension' | 'fact' }
interface QualityRule { rule_type: string; severity: string; parameters: Record<string, unknown> }
interface QueryMetric { metric_code: string; name: string; fact_field_code?: string | null; expression?: string | null; importance?: string }
interface QueryModel {
  object_code: string
  datasets: Dataset[]
  keys: DatasetKey[]
  fields: SemanticField[]
  quality_rules: QualityRule[]
  metrics: QueryMetric[]
  validation_issues: string[]
  queryable: boolean
}
interface FilterRow { field_code: string; operator: string; value: string }
interface OrderRow { field_code: string; direction: 'asc' | 'desc' }
interface ProcessedMetric { metric_code: string; name: string; value: number | null; unit: string | null; precision: number | null; definition: string }
interface ProcessedSnapshot { view: string; datasource_id: string; signoff: string; metrics: ProcessedMetric[] }
interface QueryResult {
  plan: Record<string, unknown>
  result: {
    rows: Record<string, unknown>[]
    result_grain: string[]
    query_scope: string
    quality_status: 'complete' | 'partial' | 'unavailable'
    evidence: { segment_count: number; matched_segment_count: number }
    warnings: string[]
  }
  parameterized_sql: string
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`加载失败（HTTP ${response.status}）`)
  return response.json() as Promise<T>
}

export default function SemanticQueryPage() {
  const [objects, setObjects] = useState<ObjectSummary[]>([])
  const [models, setModels] = useState<Record<string, QueryModel>>({})
  const [objectCode, setObjectCode] = useState('')
  const [entityCode, setEntityCode] = useState('')
  const [queryScope, setQueryScope] = useState<'whole_admission' | 'segment'>('whole_admission')
  const [anchorField, setAnchorField] = useState('')
  const [anchorValue, setAnchorValue] = useState('')
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>([])
  const [groupBy, setGroupBy] = useState<string[]>([])
  const [filters, setFilters] = useState<FilterRow[]>([])
  const [orderBy, setOrderBy] = useState<OrderRow[]>([])
  const [limit, setLimit] = useState(100)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [sampling, setSampling] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sampleError, setSampleError] = useState<string | null>(null)
  const [output, setOutput] = useState<QueryResult | null>(null)
  const [snapshot, setSnapshot] = useState<ProcessedSnapshot | null>(null)
  const [snapshotError, setSnapshotError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    semanticReviewJson<ProcessedSnapshot>(`${API}/query/processed-snapshot`, 'GET')
      .then((data) => { if (active) setSnapshot(data) })
      .catch((reason) => { if (active) setSnapshotError(reason instanceof Error ? reason.message : '快照加载失败') })
    return () => { active = false }
  }, [])

  useEffect(() => {
    let active = true
    async function load() {
      try {
        const allObjects = await fetchJson<ObjectSummary[]>(`${API}/objects`)
        const entries = await Promise.all(allObjects.map(async (object) => {
          if (!object.current_version) return [object.object_code, null] as const
          const model = await fetchJson<QueryModel>(
            `${API}/objects/${encodeURIComponent(object.object_code)}/query-model?published=true`,
          ).catch(() => null)
          return [object.object_code, model] as const
        }))
        if (!active) return
        const modelMap = Object.fromEntries(entries.filter((entry): entry is readonly [string, QueryModel] => entry[1] !== null))
        const available = allObjects.filter((object) => object.current_version && modelMap[object.object_code]?.queryable)
        setModels(modelMap)
        setObjects(available)
        setObjectCode(available[0]?.object_code ?? '')
        if (available.length === 0) setError('暂无已发布且可查询的业务对象')
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : '查询模型加载失败')
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => { active = false }
  }, [])

  const currentObject = objects.find((item) => item.object_code === objectCode)
  const model = models[objectCode]
  const entities = useMemo(
    () => [...new Set((model?.keys ?? []).map((key) => key.entity_code))],
    [model],
  )
  const anchorFields = useMemo(() => {
    if (!model || !entityCode) return []
    const keyColumns = new Set(
      model.keys
        .filter((key) => key.entity_code === entityCode)
        .flatMap((key) => key.columns.map((column) => `${key.dataset_code}:${column}`)),
    )
    return model.fields.filter(
      (field) => field.field_role === 'identifier' && keyColumns.has(`${field.dataset_code}:${field.column_name}`),
    )
  }, [entityCode, model])
  const metrics = useMemo(
    () => (model?.metrics ?? []).filter((metric) => metric.fact_field_code || metric.expression),
    [model],
  )
  const coverageDatasetCode = model?.quality_rules.find((rule) => rule.rule_type === 'coverage')?.parameters.reference_dataset
  const anchorDatasetCode = model?.fields.find((field) => field.field_code === anchorField)?.dataset_code
  const groupFields = useMemo(
    () => (model?.fields ?? []).filter(
      (field) => field.field_role !== 'fact' && field.dataset_code === coverageDatasetCode,
    ),
    [coverageDatasetCode, model],
  )
  const filterFields = useMemo(
    () => (model?.fields ?? []).filter(
      (field) => field.field_role !== 'fact' && [anchorDatasetCode, coverageDatasetCode].includes(field.dataset_code),
    ),
    [anchorDatasetCode, coverageDatasetCode, model],
  )

  function clearQueryState() {
    setAnchorValue('')
    setGroupBy([])
    setFilters([])
    setOrderBy([])
    setOutput(null)
    setError(null)
    setSampleError(null)
  }

  useEffect(() => {
    if (!model) return
    const firstEntity = [...new Set(model.keys.map((key) => key.entity_code))][0] ?? ''
    setEntityCode(firstEntity)
    const recommended = metrics.filter((metric) => metric.importance === 'core').slice(0, 4)
    setSelectedMetrics((recommended.length ? recommended : metrics.slice(0, 1)).map((metric) => metric.metric_code))
    clearQueryState()
  }, [model, metrics])

  useEffect(() => {
    if (!model || !entityCode) return
    const keyColumns = new Set(
      model.keys
        .filter((key) => key.entity_code === entityCode)
        .flatMap((key) => key.columns.map((column) => `${key.dataset_code}:${column}`)),
    )
    const available = model.fields.filter(
      (field) => field.field_role === 'identifier' && keyColumns.has(`${field.dataset_code}:${field.column_name}`),
    )
    const recommendedCode = model.quality_rules.find(
      (rule) => rule.rule_type === 'not_null' && rule.severity === 'blocking',
    )?.parameters.field_code
    const recommended = available.find((field) => field.field_code === recommendedCode) ?? available[0]
    setAnchorField(recommended?.field_code ?? '')
    clearQueryState()
  }, [entityCode, model])

  function changeObject(next: string) {
    setObjectCode(next)
    setEntityCode('')
    setAnchorField('')
    setSelectedMetrics([])
    clearQueryState()
  }

  function changeEntity(next: string) {
    setEntityCode(next)
    setAnchorField('')
    clearQueryState()
  }

  function changeAnchorField(next: string) {
    setAnchorField(next)
    clearQueryState()
  }

  async function sampleAnchor() {
    setSampling(true)
    setSampleError(null)
    try {
      const sampled = await semanticReviewJson<{ value: string | number }>(`${API}/query/anchor-sample`, 'POST', {
        object_code: objectCode,
        entity_code: entityCode,
        field_code: anchorField,
      })
      setAnchorValue(String(sampled.value))
      setOutput(null)
    } catch (reason) {
      setAnchorValue('')
      setSampleError(reason instanceof Error ? reason.message : '当前锚点字段没有可用样本')
    } finally {
      setSampling(false)
    }
  }

  async function runQuery() {
    setRunning(true)
    setError(null)
    setOutput(null)
    try {
      const result = await semanticReviewJson<QueryResult>(`${API}/query/test`, 'POST', {
        object_code: objectCode,
        scope: {
          entity_code: entityCode,
          anchor: { field_code: anchorField, value: anchorValue },
          query_scope: queryScope,
        },
        metrics: selectedMetrics,
        group_by: groupBy,
        filters: filters.map((item) => ({
          field_code: item.field_code,
          operator: item.operator,
          value: ['is_null', 'is_not_null'].includes(item.operator) ? null : item.value,
        })),
        order_by: orderBy,
        limit,
      })
      setOutput(result)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '查询验证失败')
    } finally {
      setRunning(false)
    }
  }

  if (loading) return <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />加载已发布查询模型...</div>

  return (
    <div className="space-y-5">
      {error && !objectCode && <Alert variant="destructive"><AlertTitle>加载失败</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
      {/* ── 门诊加工指标快照（#62 验收③：加工结果一屏可见）────────── */}
      <Card className="border-slate-200 bg-white shadow-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><Database className="h-4 w-4 text-cyan-600" />门诊加工指标快照</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {snapshotError && <p className="text-xs text-slate-400">快照不可用：{snapshotError}</p>}
          {snapshot && (
            <>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                {snapshot.metrics.map((metric) => (
                  <div key={metric.metric_code} className="rounded-lg border border-slate-200 bg-slate-50 p-3" title={metric.definition}>
                    <p className="text-[11px] text-slate-500">{metric.name}</p>
                    <p className="mt-1 font-mono text-xl font-bold tabular-nums text-cyan-700">
                      {metric.value === null ? '-' : metric.value.toLocaleString('zh-CN', { minimumFractionDigits: metric.precision ?? 0, maximumFractionDigits: metric.precision ?? 2 })}
                      {metric.unit && <span className="ml-1 text-[11px] font-normal text-slate-400">{metric.unit}</span>}
                    </p>
                  </div>
                ))}
              </div>
              <p className="text-[11px] text-slate-400">来源：{snapshot.view}（{snapshot.datasource_id}）· {snapshot.signoff}</p>
            </>
          )}
        </CardContent>
      </Card>
      <Card className="border-slate-200 bg-white shadow-sm">
        <CardHeader><CardTitle className="text-base">受限语义查询</CardTitle></CardHeader>
        <CardContent className="space-y-5">
          {model && (
            <div className="grid gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs sm:grid-cols-4">
              <div><p className="text-slate-500">发布版本</p><p className="mt-1 font-medium">v{currentObject?.current_version}</p></div>
              <div><p className="text-slate-500">主体实体</p><p className="mt-1 font-mono">{entityCode || '-'}</p></div>
              <div><p className="text-slate-500">数据集</p><p className="mt-1 font-medium">{model.datasets.length} 个</p></div>
              <div><p className="text-slate-500">模型状态</p><p className="mt-1 font-medium text-emerald-600">可查询</p></div>
            </div>
          )}

          <div className="grid gap-3 md:grid-cols-2">
            <label className="text-xs text-slate-500">业务对象
              <select aria-label="业务对象" value={objectCode} onChange={(event) => changeObject(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-slate-300 bg-white px-2 text-sm">
                {objects.map((item) => <option key={item.object_code} value={item.object_code}>{item.name} ({item.object_code})</option>)}
              </select>
            </label>
            <label className="text-xs text-slate-500">目标实体
              <select aria-label="目标实体" value={entityCode} onChange={(event) => changeEntity(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-slate-300 bg-white px-2 text-sm">
                {entities.map((entity) => <option key={entity} value={entity}>{entity}</option>)}
              </select>
            </label>
            <label className="text-xs text-slate-500">查询范围
              <select aria-label="查询范围" value={queryScope} onChange={(event) => { setQueryScope(event.target.value as 'whole_admission' | 'segment'); setOutput(null) }} className="mt-1 h-9 w-full rounded-md border border-slate-300 bg-white px-2 text-sm">
                <option value="whole_admission">整次住院</option><option value="segment">逐分段</option>
              </select>
            </label>
            <label className="text-xs text-slate-500">锚点字段
              <select aria-label="锚点字段" value={anchorField} onChange={(event) => changeAnchorField(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-slate-300 bg-white px-2 text-sm">
                {anchorFields.map((field) => <option key={field.field_code} value={field.field_code}>{field.name} ({field.field_code})</option>)}
              </select>
            </label>
            <div className="md:col-span-2">
              <label htmlFor="anchor-value" className="text-xs text-slate-500">锚点值</label>
              <div className="mt-1 flex gap-2">
                <Input id="anchor-value" aria-label="锚点值" value={anchorValue} onChange={(event) => { setAnchorValue(event.target.value); setOutput(null); setSampleError(null) }} />
                <button type="button" onClick={sampleAnchor} disabled={sampling || !anchorField} className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-blue-200 bg-blue-50 px-3 text-xs font-medium text-blue-700 hover:bg-blue-100 disabled:opacity-50">
                  {sampling && <Loader2 className="h-3.5 w-3.5 animate-spin" />}随机取值
                </button>
              </div>
              <p className="mt-1 text-[11px] text-slate-400">再次点击可重新取样。</p>
              {sampleError && <p className="mt-1 text-xs text-red-600">{sampleError}</p>}
            </div>
            <label className="text-xs text-slate-500 md:col-span-2">指标
              <select aria-label="指标" multiple value={selectedMetrics} onChange={(event) => { setSelectedMetrics([...event.target.selectedOptions].map((option) => option.value)); setOutput(null) }} className="mt-1 min-h-28 w-full rounded-md border border-slate-300 bg-white p-2 text-sm">
                {metrics.map((metric) => <option key={metric.metric_code} value={metric.metric_code}>{metric.name} ({metric.metric_code})</option>)}
              </select>
              <span className="mt-1 block text-[11px] text-slate-400">按 Ctrl/Cmd 可多选。</span>
            </label>
          </div>

          <details className="rounded-lg border border-slate-200 p-3">
            <summary className="cursor-pointer text-sm font-medium text-slate-700">高级条件</summary>
            <div className="mt-4 space-y-4">
              <label className="block text-xs text-slate-500">分组字段
                <select aria-label="分组字段" multiple value={groupBy} onChange={(event) => setGroupBy([...event.target.selectedOptions].map((option) => option.value))} className="mt-1 min-h-20 w-full rounded-md border border-slate-300 bg-white p-2 text-sm">
                  {groupFields.map((field) => <option key={field.field_code} value={field.field_code}>{field.name}</option>)}
                </select>
              </label>
              <div>
                <div className="mb-2 flex items-center justify-between"><span className="text-xs text-slate-500">过滤</span><button type="button" disabled={!filterFields[0]} onClick={() => setFilters((items) => [...items, { field_code: filterFields[0].field_code, operator: 'eq', value: '' }])} className="inline-flex items-center gap-1 text-xs text-blue-600 disabled:opacity-40"><Plus className="h-3 w-3" />添加过滤</button></div>
                {filters.map((item, index) => <div key={index} className="mb-2 grid gap-2 sm:grid-cols-[1fr_120px_1fr_auto]">
                  <select aria-label={`过滤字段 ${index + 1}`} value={item.field_code} onChange={(event) => setFilters((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, field_code: event.target.value } : row))} className="h-9 rounded-md border border-slate-300 bg-white px-2 text-xs">{filterFields.map((field) => <option key={field.field_code} value={field.field_code}>{field.name}</option>)}</select>
                  <select aria-label={`过滤操作 ${index + 1}`} value={item.operator} onChange={(event) => setFilters((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, operator: event.target.value } : row))} className="h-9 rounded-md border border-slate-300 bg-white px-2 text-xs">{['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'is_null', 'is_not_null'].map((operator) => <option key={operator}>{operator}</option>)}</select>
                  <Input aria-label={`过滤值 ${index + 1}`} value={item.value} disabled={['is_null', 'is_not_null'].includes(item.operator)} onChange={(event) => setFilters((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, value: event.target.value } : row))} />
                  <button type="button" aria-label={`删除过滤 ${index + 1}`} onClick={() => setFilters((rows) => rows.filter((_, rowIndex) => rowIndex !== index))} className="p-2 text-slate-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
                </div>)}
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <label className="text-xs text-slate-500">排序
                  <select aria-label="排序字段" value={orderBy[0]?.field_code ?? ''} onChange={(event) => setOrderBy(event.target.value ? [{ field_code: event.target.value, direction: orderBy[0]?.direction ?? 'asc' }] : [])} className="mt-1 h-9 w-full rounded-md border border-slate-300 bg-white px-2 text-sm"><option value="">不排序</option>{[...metrics.filter((metric) => selectedMetrics.includes(metric.metric_code)).map((metric) => ({ code: metric.metric_code, name: metric.name })), ...groupFields.filter((field) => groupBy.includes(field.field_code)).map((field) => ({ code: field.field_code, name: field.name }))].map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}</select>
                </label>
                <label className="text-xs text-slate-500">方向
                  <select aria-label="排序方向" value={orderBy[0]?.direction ?? 'asc'} disabled={orderBy.length === 0} onChange={(event) => setOrderBy((rows) => rows.length ? [{ ...rows[0], direction: event.target.value as 'asc' | 'desc' }] : [])} className="mt-1 h-9 w-full rounded-md border border-slate-300 bg-white px-2 text-sm"><option value="asc">升序</option><option value="desc">降序</option></select>
                </label>
                <label className="text-xs text-slate-500">Limit<Input type="number" min={1} max={100} className="mt-1" value={limit} onChange={(event) => setLimit(Number(event.target.value))} /></label>
              </div>
            </div>
          </details>

          {error && objectCode && <Alert variant="destructive"><AlertTitle>验证失败</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
          <div className="flex justify-end"><button type="button" onClick={runQuery} disabled={running || !objectCode || !entityCode || !anchorField || !anchorValue || selectedMetrics.length === 0} className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">{running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}执行验证</button></div>
        </CardContent>
      </Card>

      {output && (
        <div className="space-y-4">
          <Card className="border-slate-200 bg-white shadow-sm"><CardContent className="grid gap-4 px-5 py-4 sm:grid-cols-4"><div><p className="text-xs text-slate-500">查询范围</p><p className="mt-1 font-medium">{output.result.query_scope === 'whole_admission' ? '整次住院' : '单个分段'}</p></div><div><p className="text-xs text-slate-500">结果粒度</p><p className="mt-1 font-mono text-xs">{output.result.result_grain.join(', ')}</p></div><div><p className="text-xs text-slate-500">分段覆盖</p><p className="mt-1 font-medium">{output.result.evidence.matched_segment_count}/{output.result.evidence.segment_count}</p></div><div><p className="text-xs text-slate-500">质量状态</p><p className="mt-1 inline-flex items-center gap-1 font-medium"><ShieldCheck className="h-4 w-4" />{output.result.quality_status}</p></div></CardContent></Card>
          <Card><CardHeader><CardTitle className="text-sm">查询结果</CardTitle></CardHeader><CardContent><pre className="overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">{JSON.stringify(output.result.rows, null, 2)}</pre></CardContent></Card>
          <Card><CardHeader><CardTitle className="text-sm">逻辑计划（只读）</CardTitle></CardHeader><CardContent><pre className="max-h-96 overflow-auto rounded-md bg-slate-100 p-3 text-xs text-slate-700">{JSON.stringify(output.plan, null, 2)}</pre></CardContent></Card>
          <details className="rounded-lg border border-slate-200 bg-white p-4"><summary className="cursor-pointer text-sm font-medium text-slate-700">管理员技术详情：参数化 SQL（只读）</summary><pre className="mt-3 max-h-96 overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">{output.parameterized_sql}</pre></details>
        </div>
      )}
    </div>
  )
}
