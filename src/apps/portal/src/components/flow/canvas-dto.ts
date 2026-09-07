// 画布 ↔ FlowDefinition DTO 映射（Phase 0 契约 §3.3）。
// 画布 XYFlow camelCase（id/position/type/source/target）与后端 snake_case
// （node_id/from_node/to_node）在此双向转换；序列化方向：画布状态 →
// 前端组装 FlowDefinition JSON → 后端 Pydantic 校验，前端绝不产出 SQL。
import type { Edge, Node } from '@xyflow/react'
import type { FlowDefinitionDto, FlowNodeDto, FlowNodeType } from '@/lib/flow-api'

export interface FlowCanvasNodeData extends Record<string, unknown> {
  definition: FlowNodeDto
  issueCount: number
}

export type FlowCanvasNode = Node<FlowCanvasNodeData>
export type FlowCanvasEdge = Edge

let edgeSeq = 0

export function nextEdgeId(): string {
  edgeSeq += 1
  return `e_${Date.now().toString(36)}_${edgeSeq}`
}

/** FlowDefinition → 画布节点/边；缺 position 的节点落到原点网格。 */
export function definitionToCanvas(flow: FlowDefinitionDto): {
  nodes: FlowCanvasNode[]
  edges: FlowCanvasEdge[]
} {
  return {
    nodes: flow.nodes.map((definition, index) => ({
      id: definition.node_id,
      type: definition.node_type,
      position: definition.position ?? { x: (index % 4) * 240, y: Math.floor(index / 4) * 160 },
      data: { definition, issueCount: 0 },
    })),
    edges: flow.edges.map((e) => ({
      id: e.edge_id,
      source: e.from_node,
      target: e.to_node,
    })),
  }
}

/** 画布状态 → FlowDefinition；definition-level 字段（契约/指标输出/生命周期）原样保留。 */
export function canvasToDefinition(
  flow: FlowDefinitionDto,
  nodes: FlowCanvasNode[],
  edges: FlowCanvasEdge[],
): FlowDefinitionDto {
  return {
    ...flow,
    nodes: nodes.map((n) => ({
      ...n.data.definition,
      position: { x: n.position.x, y: n.position.y },
    })),
    edges: edges.map((e) => ({
      edge_id: e.id,
      from_node: e.source,
      to_node: e.target,
    })),
  }
}

/** 新建节点的最小合法骨架（必填字段留空，属性面板补全后才能过后端校验）。 */
export function newNodeDefinition(nodeType: FlowNodeType, nodeSeq: number): FlowNodeDto {
  const node_id = `${nodeType}_${nodeSeq}`
  const base = { node_id, name: NODE_TYPE_LABELS[nodeType], position: null }
  switch (nodeType) {
    case 'source':
      return { ...base, node_type: 'source', dataset_code: '', object_code: '', fields: [] }
    case 'filter':
      return { ...base, node_type: 'filter', conditions: [{ field_code: '', operator: 'eq', value: null }] }
    case 'join':
      return { ...base, node_type: 'join', relation_code: '', join_type: 'inner' }
    case 'aggregate':
      return {
        ...base, node_type: 'aggregate', group_by: [],
        measures: [{ output_code: '', source_field: '', operator: 'sum' }],
      }
    case 'derived_metric':
      return { ...base, node_type: 'derived_metric', metrics: [{ output_code: '', expression: '' }] }
    case 'dimension':
      return {
        ...base, node_type: 'dimension',
        dimensions: [{ field_code: '', permission_level: 'summary' }],
      }
    case 'quality_gate':
      return { ...base, node_type: 'quality_gate', checks: [{ check_type: 'caliber_signoff', params: {} }] }
    case 'consumer':
      return { ...base, node_type: 'consumer', consumer_kind: 'query_planner', consumes: [] }
  }
}

export const NODE_TYPE_LABELS: Record<FlowNodeType, string> = {
  source: '数据源',
  filter: '口径过滤',
  join: '关联',
  aggregate: '聚合',
  derived_metric: '派生指标',
  dimension: '维度',
  quality_gate: '质量门禁',
  consumer: '消费方',
}
