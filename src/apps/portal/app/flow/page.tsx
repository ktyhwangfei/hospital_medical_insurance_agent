'use client'

// 治理 Flow 列表页（Phase 2 入口）：资产清单 + 新建骨架。
// 新建走最小结构模板（source→aggregate→consumer + 契约 + 指标输出占位），
// DSL 要求 nodes/source_contracts/metric_outputs 均非空，占位值在画布属性面板补全。
import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Loader2, Plus, Trash2, Workflow } from 'lucide-react'
import { createFlow, deleteFlow, listFlows } from '@/lib/flow-api'
import type { FlowDefinitionDto, FlowStatus } from '@/lib/flow-api'
import { ApiClientError } from '@/lib/types'

const STATUS_BADGES: Record<FlowStatus, string> = {
  draft: 'bg-slate-100 text-slate-700',
  validating: 'bg-sky-100 text-sky-700',
  pending_review: 'bg-amber-100 text-amber-700',
  published: 'bg-emerald-100 text-emerald-700',
  deprecated: 'bg-zinc-200 text-zinc-500',
}
const STATUS_LABELS: Record<FlowStatus, string> = {
  draft: '草稿', validating: '校验中', pending_review: '待评审',
  published: '已发布', deprecated: '已退役',
}

interface CreateForm {
  flow_id: string
  name: string
  owner: string
  dataset_code: string
  object_code: string
  field_code: string
}

const EMPTY_FORM: CreateForm = {
  flow_id: '', name: '', owner: 'data_governance',
  dataset_code: '', object_code: '', field_code: '',
}

/** 最小结构骨架：契约/门禁只查结构与引用一致性，占位口径句由画布补全后才能发布 */
function skeletonDefinition(form: CreateForm): FlowDefinitionDto {
  return {
    flow_id: form.flow_id,
    name: form.name || form.flow_id,
    owner: form.owner,
    status: 'draft',
    nodes: [
      {
        node_type: 'source', node_id: 'src_1', name: `数据源 ${form.dataset_code}`,
        dataset_code: form.dataset_code, object_code: form.object_code,
        fields: [form.field_code], position: { x: 40, y: 160 },
      },
      {
        node_type: 'aggregate', node_id: 'agg_1', name: '聚合（占位度量）',
        group_by: [],
        measures: [{ output_code: 'op_row_count', source_field: form.field_code, operator: 'count' }],
        position: { x: 320, y: 160 },
      },
      {
        node_type: 'consumer', node_id: 'consumer_1', name: '受控问数（query_planner）',
        consumer_kind: 'query_planner', consumes: ['op_row_count'],
        position: { x: 600, y: 160 },
      },
    ],
    edges: [
      { edge_id: 'e1', from_node: 'src_1', to_node: 'agg_1' },
      { edge_id: 'e2', from_node: 'agg_1', to_node: 'consumer_1' },
    ],
    source_contracts: [
      { dataset_code: form.dataset_code, object_code: form.object_code, fields: [form.field_code] },
    ],
    metric_outputs: [
      {
        metric_code: 'op_row_count', name: '行数（占位）', node_id: 'agg_1',
        policy_definition: '（占位口径句：请在画布补全并经知识签核）',
      },
    ],
    materialization: 'view',
    revision: 1,
  }
}

export default function FlowListPage() {
  const router = useRouter()
  const [flows, setFlows] = useState<FlowDefinitionDto[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const createBtnRef = useRef<HTMLButtonElement>(null)

  /** 关闭新建对话框并归还焦点给打开按钮（键盘全路径验收项） */
  const closeCreate = useCallback(() => {
    setShowCreate(false)
    setCreateError(null)
    requestAnimationFrame(() => createBtnRef.current?.focus())
  }, [])

  const reload = useCallback(async () => {
    try {
      setFlows(await listFlows())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => { reload() }, [reload])

  const handleCreate = async () => {
    if (!form.flow_id.trim() || !form.dataset_code.trim() || !form.field_code.trim()) {
      setCreateError('flow_id、数据集编码、首个契约字段必填')
      return
    }
    setCreating(true)
    setCreateError(null)
    try {
      await createFlow(skeletonDefinition(form))
      setShowCreate(false)
      setForm(EMPTY_FORM)
      router.push(`/flow/${encodeURIComponent(form.flow_id.trim())}`)
    } catch (e) {
      setCreateError(e instanceof ApiClientError ? `${e.detail.error_code}：${e.detail.message}` : String(e))
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (flow: FlowDefinitionDto) => {
    if (!window.confirm(`确认删除草稿 ${flow.flow_id}？`)) return
    try {
      await deleteFlow(flow.flow_id, flow.revision)
      reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const inputCls =
    'w-full rounded-md border border-slate-200 px-2 py-1.5 text-xs focus:border-slate-400 focus:outline-none'

  return (
    <div className="mx-auto max-w-5xl space-y-4" data-testid="flow-list-page">
      <header className="flex flex-wrap items-center gap-3">
        <span className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-slate-900 px-2.5 py-2 text-white">
          <Workflow className="size-4" />
        </span>
        <div className="min-w-0">
          <h1 className="text-base font-semibold text-slate-900">治理 Flow</h1>
          <p className="text-xs text-slate-500">
            数据加工 → 智能问数的可视化配置与复用闭环（画布编辑、口径签核发布、修订回滚）
          </p>
        </div>
        <button type="button" ref={createBtnRef} onClick={() => setShowCreate(true)}
          className="ml-auto inline-flex shrink-0 items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700">
          <Plus className="size-3.5" />新建 Flow
        </button>
      </header>

      {error && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700" data-testid="flow-list-error">{error}</p>
      )}

      {flows === null ? (
        <div className="flex h-40 items-center justify-center gap-2 text-sm text-slate-500">
          <Loader2 className="size-4 animate-spin" />加载 Flow 清单…
        </div>
      ) : flows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500">
          尚无治理 Flow。点击右上角「新建 Flow」从最小结构模板开始配置。
        </div>
      ) : (
        <ul className="space-y-2" data-testid="flow-list">
          {flows.map((flow) => (
            <li key={flow.flow_id}
              className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 transition-colors hover:border-slate-400">
              <button type="button" className="min-w-0 flex-1 text-left"
                onClick={() => router.push(`/flow/${encodeURIComponent(flow.flow_id)}`)}>
                <p className="truncate text-sm font-medium text-slate-900">
                  {flow.name}
                  <span className="ml-2 font-mono text-[11px] text-slate-400">{flow.flow_id}</span>
                </p>
                <p className="mt-0.5 truncate text-xs text-slate-500">
                  {flow.owner} · {flow.nodes.length} 节点 / {flow.edges.length} 边 · rev {flow.revision}
                  {flow.published_at ? ` · 发布于 ${flow.published_at}（${flow.published_by}）` : ''}
                </p>
              </button>
              <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_BADGES[flow.status]}`}>
                {STATUS_LABELS[flow.status]}
              </span>
              {(flow.status === 'draft' || flow.status === 'validating' || flow.status === 'pending_review') && (
                <button type="button" onClick={() => handleDelete(flow)} title="删除草稿"
                  className="shrink-0 rounded p-1.5 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600">
                  <Trash2 className="size-4" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div
            role="dialog" aria-modal="true" aria-label="新建 Flow（最小结构模板）"
            onKeyDown={(e) => { if (e.key === 'Escape' && !creating) closeCreate() }}
            className="w-full max-w-md space-y-3 rounded-lg bg-white p-5 shadow-xl" data-testid="flow-create-dialog">
            <h2 className="text-sm font-semibold text-slate-900">新建 Flow（最小结构模板）</h2>
            <p className="text-xs text-slate-500">
              模板生成 source → aggregate → consumer 骨架与契约/指标输出占位，创建后进入画布补全口径。
            </p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <label className="space-y-1">
                <span className="text-xs font-medium text-slate-500">flow_id</span>
                <input autoFocus className={inputCls} value={form.flow_id} placeholder="flow_op_xxx"
                  onChange={(e) => setForm({ ...form, flow_id: e.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-slate-500">名称</span>
                <input className={inputCls} value={form.name} placeholder="门诊xx加工视图"
                  onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-slate-500">负责人</span>
                <input className={inputCls} value={form.owner}
                  onChange={(e) => setForm({ ...form, owner: e.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-slate-500">数据集编码</span>
                <input className={inputCls} value={form.dataset_code} placeholder="mz_trade"
                  onChange={(e) => setForm({ ...form, dataset_code: e.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-slate-500">业务对象编码</span>
                <input className={inputCls} value={form.object_code} placeholder="mzjyxx"
                  onChange={(e) => setForm({ ...form, object_code: e.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-slate-500">首个契约字段</span>
                <input className={inputCls} value={form.field_code} placeholder="T_TradeNo"
                  onChange={(e) => setForm({ ...form, field_code: e.target.value })} />
              </label>
            </div>
            {createError && <p className="text-xs text-red-600">{createError}</p>}
            <div className="flex justify-end gap-2 pt-1">
              <button type="button" onClick={closeCreate} disabled={creating}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:border-slate-500">
                取消
              </button>
              <button type="button" onClick={handleCreate} disabled={creating}
                className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-40">
                {creating && <Loader2 className="size-3.5 animate-spin" />}创建并进入画布
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
