'use client'

// 属性面板：选中节点的参数表单（8 类）+ 定义级「来源契约 / 指标输出」编辑。
// 只产出 FlowDefinition JSON，绝不生成 SQL（契约 §3.3 序列化方向）。
import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import type {
  AggregateNodeDto, ConsumerNodeDto, DerivedMetricNodeDto, DimensionNodeDto,
  FilterNodeDto, FlowDefinitionDto, FlowNodeDto, FlowNodeType, JoinNodeDto,
  QualityCheckType, QualityGateNodeDto, SourceNodeDto,
  AggregateOperator, FilterOperator, ConsumerKind, PermissionLevel, ValidationSeverity,
} from '@/lib/flow-api'
import { NODE_TYPE_LABELS } from './canvas-dto'
import { listDataModels } from '@/lib/data-model-api'

const FILTER_OPERATORS: FilterOperator[] = [
  'eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'in', 'not_in', 'in_or_null', 'is_null', 'is_not_null',
]
const AGGREGATE_OPERATORS: AggregateOperator[] = ['count', 'count_distinct', 'sum', 'avg']
const CHECK_TYPES: QualityCheckType[] = [
  'caliber_signoff', 'identity_assertion', 'row_count', 'null_rate', 'freshness', 'permission',
]
const CONSUMER_KINDS: ConsumerKind[] = ['query_planner', 'skill', 'dashboard_card', 'weekly_report', 'assistant']
const PERMISSION_LEVELS: PermissionLevel[] = ['summary', 'detail']
const SEVERITIES: ValidationSeverity[] = ['blocking', 'warning']
const NO_VALUE_OPERATORS: FilterOperator[] = ['is_null', 'is_not_null']

const inputCls =
  'w-full rounded-md border border-slate-200 px-2 py-1.5 text-xs text-slate-900 focus:border-slate-400 focus:outline-none disabled:bg-slate-50'
const rowBtn =
  'rounded p-1 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:hidden'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-slate-500">{label}</span>
      {children}
    </label>
  )
}

/** 行容器：标签 + 跨行删除按钮 */
function Rows({ title, onAdd, addLabel, children, disabled }: {
  title: string; onAdd: () => void; addLabel: string
  children: React.ReactNode; disabled: boolean
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-slate-500">{title}</span>
        <button type="button" onClick={onAdd} disabled={disabled}
          className="inline-flex items-center gap-1 text-xs text-sky-600 hover:underline disabled:opacity-40">
          <Plus className="size-3" />{addLabel}
        </button>
      </div>
      {children}
    </div>
  )
}

/** 多行字符串编辑（每行一项）：fields / group_by / consumes 等 */
function StringList({ value, onChange, disabled, placeholder }: {
  value: string[]; onChange: (next: string[]) => void; disabled: boolean; placeholder?: string
}) {
  return (
    <textarea
      className={`${inputCls} font-mono leading-5`}
      rows={Math.min(Math.max(value.length, 2), 6)}
      value={value.join('\n')}
      placeholder={placeholder}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value.split('\n').map((s) => s.trim()).filter(Boolean))}
    />
  )
}

/** 标量/列表值输入：in* 算子逗号分列并尽量数值化，其余按标量解析 */
function FilterValueInput({ operator, value, onChange, disabled }: {
  operator: FilterOperator
  value: string | number | (string | number)[] | null | undefined
  onChange: (v: string | number | (string | number)[] | null) => void
  disabled: boolean
}) {
  if (NO_VALUE_OPERATORS.includes(operator)) return null
  const isList = operator === 'in' || operator === 'not_in' || operator === 'in_or_null'
  const text = isList
    ? Array.isArray(value) ? value.join(',') : ''
    : value === null || value === undefined ? '' : String(value)
  return (
    <input
      className={inputCls}
      value={text}
      disabled={disabled}
      placeholder={isList ? '逗号分隔，如 11,17,18' : '如 1'}
      onChange={(e) => {
        const raw = e.target.value
        if (!isList) {
          onChange(raw === '' ? null : /^\d+(\.\d+)?$/.test(raw) ? Number(raw) : raw)
          return
        }
        const parts = raw.split(',').map((s) => s.trim()).filter(Boolean)
        onChange(parts.length && parts.every((p) => /^\d+(\.\d+)?$/.test(p))
          ? parts.map(Number)
          : parts)
      }}
    />
  )
}

interface NodePropertyPanelProps {
  flow: FlowDefinitionDto
  selectedNodeId: string | null
  readOnly: boolean
  onNodeChange: (node: FlowNodeDto) => void
  onDeleteNode: (nodeId: string) => void
  onFlowPatch: (patch: Partial<FlowDefinitionDto>) => void
}

export function NodePropertyPanel({
  flow, selectedNodeId, readOnly, onNodeChange, onDeleteNode, onFlowPatch,
}: NodePropertyPanelProps) {
  const node = flow.nodes.find((n) => n.node_id === selectedNodeId) ?? null

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto p-3" data-testid="flow-property-panel">
      {node ? (
        <NodeEditor key={node.node_id} node={node} readOnly={readOnly}
          onChange={onNodeChange} onDelete={() => onDeleteNode(node.node_id)} />
      ) : (
        <p className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500">
          选中画布节点编辑参数；未选中时可编辑定义级契约与指标输出。
        </p>
      )}
      <DefinitionEditors flow={flow} readOnly={readOnly} onFlowPatch={onFlowPatch} />
    </div>
  )
}

// ── 单节点编辑器（按 node_type 分支）──

function NodeEditor({ node, readOnly, onChange, onDelete }: {
  node: FlowNodeDto; readOnly: boolean
  onChange: (node: FlowNodeDto) => void
  onDelete: () => void
}) {
  const patch = (p: Partial<FlowNodeDto>) => onChange({ ...node, ...p } as FlowNodeDto)
  return (
    <section className="space-y-3 rounded-lg border border-slate-200 p-3" data-testid="flow-node-editor">
      <header className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-900">
          {NODE_TYPE_LABELS[node.node_type as FlowNodeType]} · {node.node_id}
        </h3>
        <button type="button" onClick={onDelete} disabled={readOnly}
          className="inline-flex items-center gap-1 text-xs text-red-600 hover:underline disabled:opacity-40">
          <Trash2 className="size-3" />删除节点
        </button>
      </header>
      <Field label="节点名称">
        <input className={inputCls} value={node.name} disabled={readOnly}
          onChange={(e) => patch({ name: e.target.value })} />
      </Field>
      {node.node_type === 'source' && <SourceEditor node={node} readOnly={readOnly} patch={patch} />}
      {node.node_type === 'filter' && <FilterEditor node={node} readOnly={readOnly} patch={patch} />}
      {node.node_type === 'join' && <JoinEditor node={node} readOnly={readOnly} patch={patch} />}
      {node.node_type === 'aggregate' && <AggregateEditor node={node} readOnly={readOnly} patch={patch} />}
      {node.node_type === 'derived_metric' && <DerivedEditor node={node} readOnly={readOnly} patch={patch} />}
      {node.node_type === 'dimension' && <DimensionEditor node={node} readOnly={readOnly} patch={patch} />}
      {node.node_type === 'quality_gate' && <GateEditor node={node} readOnly={readOnly} patch={patch} />}
      {node.node_type === 'consumer' && <ConsumerEditor node={node} readOnly={readOnly} patch={patch} />}
    </section>
  )
}

function SourceEditor({ node, readOnly, patch }: {
  node: SourceNodeDto; readOnly: boolean; patch: (p: Partial<SourceNodeDto>) => void
}) {
  return (
    <>
      <Field label="数据集编码（须已在语义层登记）">
        <input className={inputCls} value={node.dataset_code} disabled={readOnly}
          onChange={(e) => patch({ dataset_code: e.target.value })} />
      </Field>
      <Field label="业务对象编码">
        <input className={inputCls} value={node.object_code} disabled={readOnly}
          onChange={(e) => patch({ object_code: e.target.value })} />
      </Field>
      <Field label="投影字段白名单（每行一个）">
        <StringList value={node.fields} disabled={readOnly}
          onChange={(fields) => patch({ fields })} placeholder="T_TradeNo" />
      </Field>
    </>
  )
}

function FilterEditor({ node, readOnly, patch }: {
  node: FilterNodeDto; readOnly: boolean; patch: (p: Partial<FilterNodeDto>) => void
}) {
  const conditions = node.conditions
  const setCondition = (i: number, next: (typeof conditions)[number]) =>
    patch({ conditions: conditions.map((c, j) => (j === i ? next : c)) })
  return (
    <Rows title="过滤条件（AND）" addLabel="加条件"
      disabled={readOnly}
      onAdd={() => patch({ conditions: [...conditions, { field_code: '', operator: 'eq', value: null }] })}>
      {conditions.map((c, i) => (
        <div key={i} className="space-y-1.5 rounded-md border border-slate-100 bg-slate-50/60 p-2">
          <div className="flex items-center gap-1.5">
            <input className={inputCls} value={c.field_code} disabled={readOnly} placeholder="字段，如 T_State"
              onChange={(e) => setCondition(i, { ...c, field_code: e.target.value })} />
            <button type="button" className={rowBtn} disabled={readOnly}
              onClick={() => patch({ conditions: conditions.filter((_, j) => j !== i) })}>
              <Trash2 className="size-3.5" />
            </button>
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            <select className={inputCls} value={c.operator} disabled={readOnly}
              onChange={(e) => {
                const operator = e.target.value as FilterOperator
                setCondition(i, {
                  ...c, operator,
                  value: NO_VALUE_OPERATORS.includes(operator) ? null : c.value ?? null,
                })
              }}>
              {FILTER_OPERATORS.map((op) => <option key={op} value={op}>{op}</option>)}
            </select>
            <FilterValueInput operator={c.operator} value={c.value} disabled={readOnly}
              onChange={(value) => setCondition(i, { ...c, value })} />
          </div>
          <input className={inputCls} value={c.value_domain ?? ''} disabled={readOnly}
            placeholder="值域（可选），如 MZ_CURE_TYPE"
            onChange={(e) => setCondition(i, { ...c, value_domain: e.target.value || null })} />
        </div>
      ))}
    </Rows>
  )
}

function JoinEditor({ node, readOnly, patch }: {
  node: JoinNodeDto; readOnly: boolean; patch: (p: Partial<JoinNodeDto>) => void
}) {
  return (
    <>
      <Field label="关联关系编码（须已登记，防笛卡尔积）">
        <input className={inputCls} value={node.relation_code} disabled={readOnly}
          onChange={(e) => patch({ relation_code: e.target.value })} />
      </Field>
      <Field label="关联类型">
        <select className={inputCls} value={node.join_type ?? 'inner'} disabled={readOnly}
          onChange={(e) => patch({ join_type: e.target.value as JoinNodeDto['join_type'] })}>
          <option value="inner">inner</option>
          <option value="left">left</option>
        </select>
      </Field>
    </>
  )
}

function AggregateEditor({ node, readOnly, patch }: {
  node: AggregateNodeDto; readOnly: boolean; patch: (p: Partial<AggregateNodeDto>) => void
}) {
  const measures = node.measures
  const setMeasure = (i: number, next: (typeof measures)[number]) =>
    patch({ measures: measures.map((m, j) => (j === i ? next : m)) })
  return (
    <>
      <Field label="分组维度（每行一个；空=全局单行快照）">
        <StringList value={node.group_by ?? []} disabled={readOnly}
          onChange={(group_by) => patch({ group_by })} placeholder="T_CureType" />
      </Field>
      <Rows title="聚合度量" addLabel="加度量" disabled={readOnly}
        onAdd={() => patch({ measures: [...measures, { output_code: '', source_field: '', operator: 'sum' }] })}>
        {measures.map((m, i) => (
          <div key={i} className="space-y-1.5 rounded-md border border-slate-100 bg-slate-50/60 p-2">
            <div className="flex items-center gap-1.5">
              <input className={inputCls} value={m.output_code} disabled={readOnly} placeholder="输出编码 op_total_fee"
                onChange={(e) => setMeasure(i, { ...m, output_code: e.target.value })} />
              <button type="button" className={rowBtn} disabled={readOnly}
                onClick={() => patch({ measures: measures.filter((_, j) => j !== i) })}>
                <Trash2 className="size-3.5" />
              </button>
            </div>
            <input className={inputCls} value={m.source_field} disabled={readOnly} placeholder="来源字段 T_FeeAll"
              onChange={(e) => setMeasure(i, { ...m, source_field: e.target.value })} />
            <div className="grid grid-cols-2 gap-1.5">
              <select className={inputCls} value={m.operator} disabled={readOnly}
                onChange={(e) => {
                  const operator = e.target.value as AggregateOperator
                  setMeasure(i, { ...m, operator, distinct_key: operator === 'count_distinct' ? m.distinct_key ?? '' : null })
                }}>
                {AGGREGATE_OPERATORS.map((op) => <option key={op} value={op}>{op}</option>)}
              </select>
              {m.operator === 'count_distinct' && (
                <input className={inputCls} value={m.distinct_key ?? ''} disabled={readOnly} placeholder="去重键"
                  onChange={(e) => setMeasure(i, { ...m, distinct_key: e.target.value })} />
              )}
            </div>
          </div>
        ))}
      </Rows>
    </>
  )
}

function DerivedEditor({ node, readOnly, patch }: {
  node: DerivedMetricNodeDto; readOnly: boolean; patch: (p: Partial<DerivedMetricNodeDto>) => void
}) {
  return (
    <Rows title="派生公式（仅 + - * / 与依赖变量）" addLabel="加指标" disabled={readOnly}
      onAdd={() => patch({ metrics: [...node.metrics, { output_code: '', expression: '' }] })}>
      {node.metrics.map((m, i) => (
        <div key={i} className="space-y-1.5 rounded-md border border-slate-100 bg-slate-50/60 p-2">
          <div className="flex items-center gap-1.5">
            <input className={inputCls} value={m.output_code} disabled={readOnly} placeholder="输出编码 avg_fee"
              onChange={(e) => patch({ metrics: node.metrics.map((x, j) => j === i ? { ...x, output_code: e.target.value } : x) })} />
            <button type="button" className={rowBtn} disabled={readOnly}
              onClick={() => patch({ metrics: node.metrics.filter((_, j) => j !== i) })}>
              <Trash2 className="size-3.5" />
            </button>
          </div>
          <input className={`${inputCls} font-mono`} value={m.expression} disabled={readOnly}
            placeholder="op_total_fee / op_valid_settle_count"
            onChange={(e) => patch({ metrics: node.metrics.map((x, j) => j === i ? { ...x, expression: e.target.value } : x) })} />
        </div>
      ))}
    </Rows>
  )
}

function DimensionEditor({ node, readOnly, patch }: {
  node: DimensionNodeDto; readOnly: boolean; patch: (p: Partial<DimensionNodeDto>) => void
}) {
  return (
    <Rows title="维度绑定" addLabel="加维度" disabled={readOnly}
      onAdd={() => patch({ dimensions: [...node.dimensions, { field_code: '', permission_level: 'summary' }] })}>
      {node.dimensions.map((d, i) => (
        <div key={i} className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-1.5">
          <input className={inputCls} value={d.field_code} disabled={readOnly} placeholder="字段编码"
            onChange={(e) => patch({ dimensions: node.dimensions.map((x, j) => j === i ? { ...x, field_code: e.target.value } : x) })} />
          <input className={inputCls} value={d.value_domain ?? ''} disabled={readOnly} placeholder="值域(可选)"
            onChange={(e) => patch({ dimensions: node.dimensions.map((x, j) => j === i ? { ...x, value_domain: e.target.value || null } : x) })} />
          <select className={inputCls} value={d.permission_level ?? 'summary'} disabled={readOnly}
            onChange={(e) => patch({ dimensions: node.dimensions.map((x, j) => j === i ? { ...x, permission_level: e.target.value as PermissionLevel } : x) })}>
            {PERMISSION_LEVELS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <button type="button" className={rowBtn} disabled={readOnly}
            onClick={() => patch({ dimensions: node.dimensions.filter((_, j) => j !== i) })}>
            <Trash2 className="size-3.5" />
          </button>
        </div>
      ))}
    </Rows>
  )
}

function GateEditor({ node, readOnly, patch }: {
  node: QualityGateNodeDto; readOnly: boolean; patch: (p: Partial<QualityGateNodeDto>) => void
}) {
  return (
    <Rows title="质量检查" addLabel="加检查" disabled={readOnly}
      onAdd={() => patch({ checks: [...node.checks, { check_type: 'caliber_signoff', params: {} }] })}>
      {node.checks.map((c, i) => (
        <CheckRow key={i} check={c} disabled={readOnly}
          onChange={(next) => patch({ checks: node.checks.map((x, j) => (j === i ? next : x)) })}
          onRemove={() => patch({ checks: node.checks.filter((_, j) => j !== i) })} />
      ))}
    </Rows>
  )
}

/** 检查行：check_type/severity + params JSON（解析失败红框不提交） */
function CheckRow({ check, disabled, onChange, onRemove }: {
  check: QualityGateNodeDto['checks'][number]
  disabled: boolean
  onChange: (next: QualityGateNodeDto['checks'][number]) => void
  onRemove: () => void
}) {
  const [jsonText, setJsonText] = useState(() => JSON.stringify(check.params ?? {}, null, 0))
  const [jsonError, setJsonError] = useState<string | null>(null)
  useEffect(() => {
    setJsonText(JSON.stringify(check.params ?? {}, null, 0))
    setJsonError(null)
  }, [check.check_type, check.params])
  return (
    <div className="space-y-1.5 rounded-md border border-slate-100 bg-slate-50/60 p-2">
      <div className="grid grid-cols-[1fr_auto_auto] items-center gap-1.5">
        <select className={inputCls} value={check.check_type} disabled={disabled}
          onChange={(e) => onChange({ ...check, check_type: e.target.value as QualityCheckType })}>
          {CHECK_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select className={inputCls} value={check.severity ?? 'blocking'} disabled={disabled}
          onChange={(e) => onChange({ ...check, severity: e.target.value as ValidationSeverity })}>
          {SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <button type="button" className={rowBtn} disabled={disabled} onClick={onRemove}>
          <Trash2 className="size-3.5" />
        </button>
      </div>
      <textarea
        className={`${inputCls} font-mono ${jsonError ? 'border-red-400' : ''}`} rows={2}
        value={jsonText} disabled={disabled}
        onChange={(e) => {
          setJsonText(e.target.value)
          try {
            const parsed = JSON.parse(e.target.value || '{}')
            setJsonError(null)
            if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
              onChange({ ...check, params: parsed })
            } else {
              setJsonError('params 必须是 JSON 对象')
            }
          } catch {
            setJsonError('JSON 语法错误，未提交')
          }
        }}
      />
      {jsonError && <p className="text-[11px] text-red-600">{jsonError}</p>}
    </div>
  )
}

function ConsumerEditor({ node, readOnly, patch }: {
  node: ConsumerNodeDto; readOnly: boolean; patch: (p: Partial<ConsumerNodeDto>) => void
}) {
  return (
    <>
      <Field label="消费方类型">
        <select className={inputCls} value={node.consumer_kind} disabled={readOnly}
          onChange={(e) => patch({ consumer_kind: e.target.value as ConsumerKind })}>
          {CONSUMER_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
      </Field>
      <Field label="消费指标（每行一个 metric_code）">
        <StringList value={node.consumes} disabled={readOnly}
          onChange={(consumes) => patch({ consumes })} placeholder="op_total_fee" />
      </Field>
    </>
  )
}

// ── 定义级编辑：来源契约 / 指标输出 ──

function DefinitionEditors({ flow, readOnly, onFlowPatch }: {
  flow: FlowDefinitionDto; readOnly: boolean
  onFlowPatch: (patch: Partial<FlowDefinitionDto>) => void
}) {
  const setContract = (i: number, next: (typeof flow.source_contracts)[number]) =>
    onFlowPatch({ source_contracts: flow.source_contracts.map((c, j) => (j === i ? next : c)) })
  const setOutput = (i: number, next: (typeof flow.metric_outputs)[number]) =>
    onFlowPatch({ metric_outputs: flow.metric_outputs.map((m, j) => (j === i ? next : m)) })
  return (
    <div className="mt-3 space-y-4">
      <section className="space-y-2 rounded-lg border border-slate-200 p-3" data-testid="flow-contracts-editor">
        <Rows title="来源契约（字段白名单）" addLabel="加契约" disabled={readOnly}
          onAdd={() => onFlowPatch({
            source_contracts: [...flow.source_contracts, { dataset_code: '', object_code: '', fields: [] }],
          })}>
          {flow.source_contracts.map((c, i) => (
            <div key={i} className="space-y-1.5 rounded-md border border-slate-100 bg-slate-50/60 p-2">
              <div className="grid grid-cols-2 gap-1.5">
                <input className={inputCls} value={c.dataset_code} disabled={readOnly} placeholder="dataset_code"
                  onChange={(e) => setContract(i, { ...c, dataset_code: e.target.value })} />
                <input className={inputCls} value={c.object_code} disabled={readOnly} placeholder="object_code"
                  onChange={(e) => setContract(i, { ...c, object_code: e.target.value })} />
              </div>
              <div className="flex items-start gap-1.5">
                <div className="min-w-0 flex-1">
                  <StringList value={c.fields} disabled={readOnly}
                    onChange={(fields) => setContract(i, { ...c, fields })} placeholder="契约字段" />
                </div>
                <button type="button" className={rowBtn} disabled={readOnly}
                  onClick={() => onFlowPatch({ source_contracts: flow.source_contracts.filter((_, j) => j !== i) })}>
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            </div>
          ))}
        </Rows>
      </section>
      <section className="space-y-2 rounded-lg border border-slate-200 p-3" data-testid="flow-outputs-editor">
        <Rows title="指标输出绑定（口径句必填，发布前须已签核）" addLabel="加指标" disabled={readOnly}
          onAdd={() => onFlowPatch({
            metric_outputs: [...flow.metric_outputs,
              { metric_code: '', name: '', node_id: '', policy_definition: '' }],
          })}>
          {flow.metric_outputs.map((m, i) => (
            <div key={i} className="space-y-1.5 rounded-md border border-slate-100 bg-slate-50/60 p-2">
              <div className="flex items-center gap-1.5">
                <input className={inputCls} value={m.metric_code} disabled={readOnly} placeholder="metric_code"
                  onChange={(e) => setOutput(i, { ...m, metric_code: e.target.value })} />
                <button type="button" className={rowBtn} disabled={readOnly}
                  onClick={() => onFlowPatch({ metric_outputs: flow.metric_outputs.filter((_, j) => j !== i) })}>
                  <Trash2 className="size-3.5" />
                </button>
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                <input className={inputCls} value={m.name} disabled={readOnly} placeholder="指标名称"
                  onChange={(e) => setOutput(i, { ...m, name: e.target.value })} />
                <input className={inputCls} value={m.node_id} disabled={readOnly} placeholder="产出节点 id"
                  onChange={(e) => setOutput(i, { ...m, node_id: e.target.value })} />
              </div>
              <textarea className={`${inputCls} font-mono leading-5`} rows={3} value={m.policy_definition}
                disabled={readOnly} placeholder="口径句（发布门禁按全文签核匹配）"
                onChange={(e) => setOutput(i, { ...m, policy_definition: e.target.value })} />
            </div>
          ))}
        </Rows>
      </section>
      <section className="space-y-2 rounded-lg border border-slate-200 p-3" data-testid="flow-materialize-editor">
        <FlowMaterializeTarget flow={flow} readOnly={readOnly} onFlowPatch={onFlowPatch} />
      </section>
    </div>
  )
}

// ── 物化目标（V3.0 Slice 2）：发布时按模型已确认映射物化明细视图并注册语义数据集 ──

function FlowMaterializeTarget({ flow, readOnly, onFlowPatch }: {
  flow: FlowDefinitionDto; readOnly: boolean
  onFlowPatch: (patch: Partial<FlowDefinitionDto>) => void
}) {
  const [models, setModels] = useState<{ model_code: string; name: string }[]>([])
  useEffect(() => {
    let cancelled = false
    void listDataModels().then((items) => {
      if (cancelled) return
      setModels(items.filter((m) => m.status === 'published').map((m) => ({ model_code: m.model_code, name: m.name })))
    }).catch(() => { /* 模型服务不可用时下拉为空 */ })
    return () => { cancelled = true }
  }, [])
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-slate-600">物化目标数据模型（可选）</p>
      <select
        className={inputCls}
        value={flow.materialize_model ?? ''}
        disabled={readOnly}
        data-testid="materialize-model-select"
        onChange={(e) => onFlowPatch({ materialize_model: e.target.value || null })}
      >
        <option value="">不物化（仅消费视图）</option>
        {models.map((m) => (
          <option key={m.model_code} value={m.model_code}>{m.name}（{m.model_code}）</option>
        ))}
      </select>
      <p className="mt-1 text-[11px] text-slate-400">
        发布后按模型已确认映射额外物化明细视图（视图名=模型编码），注册为语义数据集供受控查询。
      </p>
    </div>
  )
}
