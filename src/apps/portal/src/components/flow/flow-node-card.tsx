'use client'

// 画布自定义节点卡片：8 类节点共用壳，按类型渲染徽标与参数摘要（契约 §3.3
// node_type→注册名 1:1；source 无入边、consumer 无出边由 Handle 摆位表达）。
import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import {
  Database, Filter, GitMerge, Sigma, FunctionSquare, Rows3, ShieldCheck, MonitorDot,
} from 'lucide-react'
import type { FlowNodeDto, FlowNodeType } from '@/lib/flow-api'
import { NODE_TYPE_LABELS, type FlowCanvasNodeData } from './canvas-dto'

const TYPE_STYLES: Record<FlowNodeType, { icon: React.ReactNode; ring: string; badge: string }> = {
  source: { icon: <Database className="size-3.5" />, ring: 'ring-sky-300', badge: 'bg-sky-100 text-sky-700' },
  filter: { icon: <Filter className="size-3.5" />, ring: 'ring-violet-300', badge: 'bg-violet-100 text-violet-700' },
  join: { icon: <GitMerge className="size-3.5" />, ring: 'ring-cyan-300', badge: 'bg-cyan-100 text-cyan-700' },
  aggregate: { icon: <Sigma className="size-3.5" />, ring: 'ring-amber-300', badge: 'bg-amber-100 text-amber-700' },
  derived_metric: { icon: <FunctionSquare className="size-3.5" />, ring: 'ring-orange-300', badge: 'bg-orange-100 text-orange-700' },
  dimension: { icon: <Rows3 className="size-3.5" />, ring: 'ring-teal-300', badge: 'bg-teal-100 text-teal-700' },
  quality_gate: { icon: <ShieldCheck className="size-3.5" />, ring: 'ring-rose-300', badge: 'bg-rose-100 text-rose-700' },
  consumer: { icon: <MonitorDot className="size-3.5" />, ring: 'ring-emerald-300', badge: 'bg-emerald-100 text-emerald-700' },
}

function summarize(definition: FlowNodeDto): string {
  switch (definition.node_type) {
    case 'source':
      return `${definition.dataset_code || '（未选数据集）'} · ${definition.fields.length} 字段`
    case 'filter':
      return `${definition.conditions.length} 个过滤条件（AND）`
    case 'join':
      return definition.relation_code || '（未选关联关系）'
    case 'aggregate':
      return definition.measures.map((m) => m.output_code).join('、') || '（无量度）'
    case 'derived_metric':
      return definition.metrics.map((m) => m.output_code).join('、') || '（无派生）'
    case 'dimension':
      return definition.dimensions.map((d) => d.field_code).join('、') || '（无维度）'
    case 'quality_gate':
      return definition.checks.map((c) => c.check_type).join('、') || '（无检查）'
    case 'consumer':
      return `${definition.consumer_kind} · 消费 ${definition.consumes.length} 指标`
  }
}

function GovernedFlowNodeInner({ data, selected }: NodeProps) {
  const { definition, issueCount } = data as FlowCanvasNodeData
  const style = TYPE_STYLES[definition.node_type]
  return (
    <div
      className={`w-56 rounded-lg border bg-white p-3 shadow-sm transition-shadow ${
        selected ? 'border-slate-900 shadow-md' : 'border-slate-200'
      } ${issueCount > 0 ? 'ring-2 ring-red-400' : `ring-1 ${style.ring}`}`}
      data-testid={`flow-node-${definition.node_id}`}
    >
      {definition.node_type !== 'source' && (
        <Handle type="target" position={Position.Left} />
      )}
      <div className="flex items-center gap-2">
        <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium ${style.badge}`}>
          {style.icon}
          {NODE_TYPE_LABELS[definition.node_type]}
        </span>
        {issueCount > 0 && (
          <span className="ml-auto rounded-full bg-red-100 px-1.5 text-xs font-semibold text-red-700">
            {issueCount}
          </span>
        )}
      </div>
      <p className="mt-2 truncate text-sm font-medium text-slate-900" title={definition.name}>
        {definition.name}
      </p>
      <p className="mt-1 line-clamp-2 text-xs text-slate-500">{summarize(definition)}</p>
      {definition.node_type !== 'consumer' && (
        <Handle type="source" position={Position.Right} />
      )}
    </div>
  )
}

export const GovernedFlowNode = memo(GovernedFlowNodeInner)

/** XYFlow nodeTypes 注册表：8 类节点共用卡片，注册名与 node_type 同名（契约 §3.3）。 */
export const FLOW_NODE_TYPES = Object.fromEntries(
  (Object.keys(NODE_TYPE_LABELS) as FlowNodeType[]).map((t) => [t, GovernedFlowNode]),
) as Record<FlowNodeType, typeof GovernedFlowNode>
