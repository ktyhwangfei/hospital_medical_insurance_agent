'use client'

// 数据建模页（数据治理中心一级模块）：数据模型列表 + 新建/编辑 + 发布/退役 + 多源映射确认。
// 数据模型是可信数据的结构契约（粒度 + 字段 + 角色）；published 结构冻结，只可退役。
import { useCallback, useEffect, useState, type FormEvent, type ReactNode, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { Layers, Loader2, Plus, RefreshCw, Send, Trash2, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { listFlows } from '@/lib/flow-api'
import { NextStepCard } from '@/components/next-step-card'
import {
  confirmDataModelMapping,
  createDataModel,
  deprecateDataModel,
  getDataModel,
  listDataModelMappings,
  listDataModels,
  publishDataModel,
  saveDataModelMapping,
  submitDataModelReview,
  updateDataModel,
  type DataModel,
  type DataModelField,
  type DataModelLayer,
  type DataModelMapping,
  type ModelFieldRole,
} from '@/lib/data-model-api'

const LAYER_LABELS: Record<DataModelLayer, string> = { ods: 'ODS', dwd: 'DWD', dws: 'DWS', ads: 'ADS' }
const STATUS_LABELS: Record<string, string> = { draft: '草稿', pending_review: '待评审', published: '已发布', deprecated: '已退役' }
const STATUS_BADGES: Record<string, string> = {
  draft: 'bg-slate-100 text-slate-700',
  pending_review: 'bg-amber-100 text-amber-700',
  published: 'bg-emerald-100 text-emerald-700',
  deprecated: 'bg-zinc-200 text-zinc-500',
}
const ROLE_LABELS: Record<ModelFieldRole, string> = {
  identifier: '标识', dimension: '维度', fact: '事实', datetime: '时间',
}

const EMPTY_FIELD: DataModelField = { field_code: '', name: '', data_type: 'decimal', field_role: 'fact' }

function Modal({ title, children, onClose, wide }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4" role="presentation">
    <section role="dialog" aria-modal="true" aria-label={title}
      className={`max-h-[90dvh] w-full overflow-y-auto rounded-xl bg-white shadow-xl ${wide ? 'max-w-4xl' : 'max-w-2xl'}`}>
      <header className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
        <h2 className="font-semibold text-slate-900">{title}</h2>
        <button type="button" aria-label="关闭" onClick={onClose} className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100"><X className="size-4" /></button>
      </header>
      {children}
    </section>
  </div>
}

const inputClass = 'h-8 rounded-md border border-slate-300 bg-white px-2 text-xs text-slate-800 outline-none focus:border-blue-500'

export default function DataModelingPage() {
  return (
    <Suspense fallback={<div className="py-16 text-center text-sm text-slate-400">加载数据建模…</div>}>
      <DataModelingContent />
    </Suspense>
  )
}

function DataModelingContent() {
  const [models, setModels] = useState<DataModel[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [editing, setEditing] = useState<DataModel | null>(null)
  const [detail, setDetail] = useState<DataModel | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  // 探查页「纳入建模」入口：?table=&field=&field_code=&name= 预填新建表单
  const searchParams = useSearchParams()
  const prefillField = searchParams.get('field')
  useEffect(() => {
    if (!prefillField) return
    const table = searchParams.get('table') ?? ''
    const fieldCode = searchParams.get('field_code') ?? ''
    const fieldName = searchParams.get('name') ?? prefillField
    setEditing({
      model_code: '', name: '', layer: 'dwd', grain: '', entity_code: 'settlement',
      status: 'draft', owner: 'data_governance',
      description: table ? `来源表 ${table}（数据探查纳入）` : '',
      fields: fieldCode ? [{
        field_code: fieldCode, name: fieldName, data_type: 'varchar', field_role: 'fact',
      }] : [],
      version: 1, revision: 1,
    })
  }, [prefillField, searchParams])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setModels(await listDataModels())
      setError(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '数据模型服务暂不可用')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const act = async (key: string, action: () => Promise<unknown>, ok: string) => {
    setBusy(key)
    setError(null)
    try {
      await action()
      setMessage(ok)
      await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '操作失败')
    } finally {
      setBusy(null)
    }
  }

  return <div className="space-y-5" data-testid="data-modeling-page">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="font-semibold text-slate-900">数据模型</h2>
        <p className="mt-1 text-sm text-slate-600">
          可信数据的结构契约：粒度 + 字段 + 角色；语义指标绑定模型字段，Flow 以模型为物化输出契约。
        </p>
      </div>
      <Button onClick={() => setEditing({
        model_code: '', name: '', layer: 'dwd', grain: '', entity_code: 'settlement',
        status: 'draft', owner: 'data_governance', description: '', fields: [], version: 1, revision: 1,
      })}><Plus />新建数据模型</Button>
    </div>

    {(message || error) && <div role={error ? 'alert' : 'status'}
      className={`rounded-lg border px-4 py-3 text-sm ${error ? 'border-red-200 bg-red-50 text-red-800' : 'border-emerald-200 bg-emerald-50 text-emerald-800'}`}>
      {error ?? message}
    </div>}

    {loading ? <p className="py-10 text-center text-sm text-slate-500">正在读取数据模型…</p>
      : models.length === 0 ? <section className="rounded-xl border border-dashed border-slate-300 bg-white py-12 text-center">
        <Layers className="mx-auto size-8 text-slate-400" />
        <p className="mt-3 font-medium text-slate-800">暂无数据模型</p>
        <p className="mt-1 text-sm text-slate-500">首个样板：门诊结算明细模型（dwd_mz_settlement），见架构设计 V3.0 §8。</p>
      </section> : <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full min-w-[860px] text-left text-sm" data-testid="data-model-list">
          <thead className="bg-slate-50 text-xs text-slate-600">
            <tr><th className="px-4 py-3 font-medium">模型</th><th className="px-4 py-3 font-medium">分层</th><th className="px-4 py-3 font-medium">粒度</th><th className="px-4 py-3 font-medium">字段</th><th className="px-4 py-3 font-medium">状态</th><th className="px-4 py-3 font-medium">版本</th><th className="px-4 py-3 font-medium">操作</th></tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {models.map((model) => <tr key={model.model_code} data-testid={`model-row-${model.model_code}`}>
              <td className="px-4 py-3">
                <button type="button" className="text-left" onClick={() => setDetail(model)}>
                  <p className="font-medium text-blue-700 hover:underline">{model.name}</p>
                  <p className="mt-0.5 font-mono text-xs text-slate-500">{model.model_code}</p>
                </button>
              </td>
              <td className="px-4 py-3"><span className="rounded bg-indigo-50 px-1.5 py-0.5 text-xs font-medium text-indigo-700">{LAYER_LABELS[model.layer]}</span></td>
              <td className="px-4 py-3 font-mono text-xs text-slate-600">{model.grain}</td>
              <td className="px-4 py-3 text-slate-600">{model.fields.length} 个</td>
              <td className="px-4 py-3"><span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_BADGES[model.status]}`}>{STATUS_LABELS[model.status]}</span></td>
              <td className="px-4 py-3 text-xs text-slate-500">v{model.version} / rev {model.revision}</td>
              <td className="px-4 py-3"><div className="flex flex-wrap gap-1.5">
                {model.status === 'draft' && <>
                  <Button size="sm" variant="outline" onClick={() => setEditing(model)}>编辑</Button>
                  <Button size="sm" variant="outline" disabled={busy !== null}
                    onClick={() => void act(`review:${model.model_code}`, () => submitDataModelReview(model.model_code), `已提交评审 ${model.model_code}`)}>
                    <Send />提交评审
                  </Button>
                </>}
                {model.status === 'pending_review' && (
                  <Button size="sm" variant="outline" disabled={busy !== null}
                    onClick={() => void act(`publish:${model.model_code}`, () => publishDataModel(model.model_code), `已发布 ${model.model_code}`)}>
                    <Send />发布
                  </Button>
                )}
                {model.status === 'published' && (
                  <Button size="sm" variant="outline" disabled={busy !== null}
                    onClick={() => void act(`deprecate:${model.model_code}`, () => deprecateDataModel(model.model_code), `已退役 ${model.model_code}`)}>
                    <Trash2 />退役
                  </Button>
                )}
              </div></td>
            </tr>)}
          </tbody>
        </table>
      </section>}

    {editing && <ModelEditModal
      model={editing}
      onClose={() => setEditing(null)}
      onSaved={(text) => { setEditing(null); setMessage(text); void load() }}
    />}
    {detail && <ModelDetailModal model={detail} onClose={() => setDetail(null)} />}
  </div>
}

// ── 新建/编辑（字段结构编辑器）─────────────────────────────────────

function ModelEditModal({ model, onClose, onSaved }: {
  model: DataModel
  onClose: () => void
  onSaved: (text: string) => void
}) {
  const isNew = !model.created_at
  const [form, setForm] = useState<DataModel>({ ...model, fields: model.fields.map((f) => ({ ...f })) })
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const setField = (index: number, patch: Partial<DataModelField>) =>
    setForm((current) => ({
      ...current,
      fields: current.fields.map((f, i) => (i === index ? { ...f, ...patch } : f)),
    }))

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (isNew) {
        await createDataModel(form)
        onSaved(`已创建数据模型 ${form.model_code}（草稿）`)
      } else {
        await updateDataModel(form)
        onSaved(`已保存 ${form.model_code} 修订`)
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存失败')
    } finally {
      setBusy(false)
    }
  }

  return <Modal title={isNew ? '新建数据模型' : `编辑 ${model.model_code}`} onClose={onClose} wide>
    <form onSubmit={submit} className="space-y-4 p-5" data-testid="model-edit-form">
      {error && <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="grid gap-1 text-xs font-medium text-slate-600">模型编码
          <input className={inputClass} required disabled={!isNew} pattern="[a-z][a-z0-9_]+"
            value={form.model_code} onChange={(e) => setForm({ ...form, model_code: e.target.value })}
            placeholder="dwd_mz_settlement" /></label>
        <label className="grid gap-1 text-xs font-medium text-slate-600">名称
          <input className={inputClass} required value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="门诊结算明细模型" /></label>
        <label className="grid gap-1 text-xs font-medium text-slate-600">分层
          <select className={inputClass} value={form.layer}
            onChange={(e) => setForm({ ...form, layer: e.target.value as DataModelLayer })}>
            {(['ods', 'dwd', 'dws', 'ads'] as const).map((l) => <option key={l} value={l}>{LAYER_LABELS[l]}</option>)}
          </select></label>
        <label className="grid gap-1 text-xs font-medium text-slate-600">粒度字段（identifier）
          <input className={inputClass} required value={form.grain}
            onChange={(e) => setForm({ ...form, grain: e.target.value })} placeholder="trade_no" /></label>
        <label className="grid gap-1 text-xs font-medium text-slate-600">业务实体
          <input className={inputClass} required value={form.entity_code}
            onChange={(e) => setForm({ ...form, entity_code: e.target.value })} placeholder="settlement" /></label>
        <label className="grid gap-1 text-xs font-medium text-slate-600">负责人
          <input className={inputClass} required value={form.owner}
            onChange={(e) => setForm({ ...form, owner: e.target.value })} /></label>
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-xs font-semibold text-slate-700">模型字段（{form.fields.length}）</h3>
          <Button type="button" size="sm" variant="outline"
            onClick={() => setForm({ ...form, fields: [...form.fields, { ...EMPTY_FIELD }] })}>
            <Plus />添加字段
          </Button>
        </div>
        <div className="space-y-1.5">
          {form.fields.map((field, index) => (
            <div key={index} className="flex items-center gap-1.5" data-testid={`field-row-${index}`}>
              <input aria-label="字段编码" className={`${inputClass} w-36 font-mono`} required pattern="[a-z][a-z0-9_]+"
                value={field.field_code} placeholder="pooling_payment"
                onChange={(e) => setField(index, { field_code: e.target.value })} />
              <input aria-label="字段名称" className={`${inputClass} w-28`} required
                value={field.name} placeholder="统筹支付"
                onChange={(e) => setField(index, { name: e.target.value })} />
              <input aria-label="数据类型" className={`${inputClass} w-24`} required
                value={field.data_type}
                onChange={(e) => setField(index, { data_type: e.target.value })} />
              <select aria-label="字段角色" className={inputClass} value={field.field_role}
                onChange={(e) => setField(index, { field_role: e.target.value as ModelFieldRole })}>
                {(['identifier', 'dimension', 'fact', 'datetime'] as const).map((r) => (
                  <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                ))}
              </select>
              {field.field_role === 'fact' && (
                <input aria-label="派生表达式" className={`${inputClass} flex-1 font-mono`}
                  value={field.expression ?? ''} placeholder="派生表达式（可空）"
                  onChange={(e) => setField(index, { expression: e.target.value || null })} />
              )}
              <button type="button" aria-label="删除字段"
                className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600"
                onClick={() => setForm({ ...form, fields: form.fields.filter((_, i) => i !== index) })}>
                <Trash2 className="size-3.5" />
              </button>
            </div>
          ))}
          {form.fields.length === 0 && (
            <p className="rounded-md border border-dashed border-slate-200 px-3 py-4 text-center text-xs text-slate-400">
              尚无字段；发布前至少需要一个 identifier（粒度）和一个 fact 字段
            </p>
          )}
        </div>
      </div>

      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onClose}>取消</Button>
        <Button type="submit" disabled={busy}>{busy ? <Loader2 className="animate-spin" /> : null}保存</Button>
      </div>
    </form>
  </Modal>
}

// ── 详情（字段清单 + 多源映射确认流）─────────────────────────────

function ModelDetailModal({ model, onClose }: { model: DataModel; onClose: () => void }) {
  const [mappings, setMappings] = useState<DataModelMapping[]>([])
  const [materializedBy, setMaterializedBy] = useState<{ flowId: string; name: string } | null>(null)
  const [mappingForm, setMappingForm] = useState({ field_code: '', source_id: '', physical_table: '', physical_column: '' })
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const loadMappings = useCallback(async () => {
    try {
      setMappings(await listDataModelMappings(model.model_code))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '映射加载失败')
    }
  }, [model.model_code])

  useEffect(() => { void loadMappings() }, [loadMappings])

  // 物化状态：哪个已发布 Flow 以本模型为物化目标（Slice 2 链路可见性）
  useEffect(() => {
    let cancelled = false
    void listFlows().then((flows) => {
      if (cancelled) return
      const hit = flows.find((f) => f.materialize_model === model.model_code && f.status === 'published')
      setMaterializedBy(hit ? { flowId: hit.flow_id, name: hit.name } : null)
    }).catch(() => { /* 物化状态加载失败降级隐藏 */ })
    return () => { cancelled = true }
  }, [model.model_code])

  const saveMapping = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await saveDataModelMapping({ model_code: model.model_code, ...mappingForm })
      setMappingForm({ field_code: '', source_id: '', physical_table: '', physical_column: '' })
      await loadMappings()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存映射失败')
    } finally {
      setBusy(false)
    }
  }

  return <Modal title={`${model.name}（${model.model_code}）`} onClose={onClose} wide>
    <div className="space-y-5 p-5" data-testid="model-detail">
      {/* 物化状态：模型 → Flow 物化 → 明细视图 链路可见 */}
      <section className="rounded-lg border border-slate-200 bg-slate-50/60 px-3 py-2.5" data-testid="materialize-status">
        <h3 className="text-xs font-semibold text-slate-700">物化状态</h3>
        {model.status !== 'published' ? (
          <p className="mt-1 text-xs text-slate-500">模型未发布，不可物化</p>
        ) : materializedBy ? (
          <p className="mt-1 text-xs text-slate-600">
            已由 Flow <Link href={`/data-governance/flows/${encodeURIComponent(materializedBy.flowId)}`} className="font-medium text-blue-700 hover:underline">{materializedBy.name}</Link> 物化为明细视图
            <code className="ml-1 rounded bg-white px-1 py-0.5 font-mono text-[11px] text-slate-700">{model.model_code}</code>
            ，可在语义层受控查询。
          </p>
        ) : (
          <p className="mt-1 text-xs text-slate-500">
            未被物化。到 <Link href="/data-governance/flows" className="text-blue-600 hover:underline">数据加工</Link> 创建 Flow 并在属性面板选择物化目标为本模型。
          </p>
        )}
      </section>

      <section>
        <h3 className="mb-2 text-xs font-semibold text-slate-700">模型字段</h3>
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-50 text-slate-500">
            <tr><th className="px-3 py-2">编码</th><th className="px-3 py-2">名称</th><th className="px-3 py-2">类型</th><th className="px-3 py-2">角色</th><th className="px-3 py-2">派生表达式</th></tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {model.fields.map((field) => <tr key={field.field_code}>
              <td className="px-3 py-2 font-mono">{field.field_code}</td>
              <td className="px-3 py-2">{field.name}</td>
              <td className="px-3 py-2 font-mono">{field.data_type}</td>
              <td className="px-3 py-2">{ROLE_LABELS[field.field_role]}</td>
              <td className="px-3 py-2 font-mono text-slate-500">{field.expression ?? '—'}</td>
            </tr>)}
          </tbody>
        </table>
      </section>

      <section>
        <h3 className="mb-2 text-xs font-semibold text-slate-700">多源映射（物理列 → 模型字段）</h3>
        {error && <p role="alert" className="mb-2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}
        {mappings.length > 0 && (
          <table className="mb-3 w-full text-left text-xs" data-testid="mapping-list">
            <thead className="bg-slate-50 text-slate-500">
              <tr><th className="px-3 py-2">模型字段</th><th className="px-3 py-2">数据源</th><th className="px-3 py-2">物理表.列</th><th className="px-3 py-2">标准化规则</th><th className="px-3 py-2">状态</th><th className="px-3 py-2"></th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {mappings.map((mapping) => <tr key={`${mapping.field_code}@${mapping.source_id}`}>
                <td className="px-3 py-2 font-mono">{mapping.field_code}</td>
                <td className="px-3 py-2">{mapping.source_id}</td>
                <td className="px-3 py-2 font-mono">{mapping.physical_table}.{mapping.physical_column}</td>
                <td className="px-3 py-2 text-slate-500">{mapping.transform_rule ?? '直通'}</td>
                <td className="px-3 py-2">
                  <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${mapping.status === 'confirmed' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
                    {mapping.status === 'confirmed' ? '已确认' : '待确认'}
                  </span>
                </td>
                <td className="px-3 py-2">
                  {mapping.status === 'draft' && (
                    <Button size="sm" variant="outline" disabled={busy}
                      onClick={() => void confirmDataModelMapping(model.model_code, mapping.field_code, mapping.source_id).then(loadMappings)}>
                      确认
                    </Button>
                  )}
                </td>
              </tr>)}
            </tbody>
          </table>
        )}
        <form onSubmit={saveMapping} className="flex flex-wrap items-center gap-1.5" data-testid="mapping-form">
          <select aria-label="模型字段" className={inputClass} required value={mappingForm.field_code}
            onChange={(e) => setMappingForm({ ...mappingForm, field_code: e.target.value })}>
            <option value="">选择模型字段</option>
            {model.fields.map((f) => <option key={f.field_code} value={f.field_code}>{f.field_code}</option>)}
          </select>
          <input aria-label="数据源" className={`${inputClass} w-28`} required placeholder="数据源 bjybdb"
            value={mappingForm.source_id} onChange={(e) => setMappingForm({ ...mappingForm, source_id: e.target.value })} />
          <input aria-label="物理表" className={`${inputClass} w-28 font-mono`} required placeholder="mz_trade"
            value={mappingForm.physical_table} onChange={(e) => setMappingForm({ ...mappingForm, physical_table: e.target.value })} />
          <input aria-label="物理列" className={`${inputClass} w-32 font-mono`} required placeholder="T_FundPay"
            value={mappingForm.physical_column} onChange={(e) => setMappingForm({ ...mappingForm, physical_column: e.target.value })} />
          <Button type="submit" size="sm" variant="outline" disabled={busy}>保存映射（待确认）</Button>
        </form>
      </section>
    
      <NextStepCard href="C:/Program Files/Git/data-governance/flows" title="编排 Flow 把模型加工为消费视图"
        description="加工产出可消费的指标" />
</div>
  </Modal>
}
