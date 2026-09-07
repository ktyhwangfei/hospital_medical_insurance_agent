'use client'

// 画布主体：左侧 8 类节点面板 + XYFlow 画布（命名导入 ReactFlow，Phase 0 §5 陷阱 1）。
// 受控状态由编辑页持有（useNodesState/useEdgesState），本组件只渲染与转发变更。
import {
  ReactFlow, Background, BackgroundVariant, Controls, MiniMap,
  type Connection, type Edge, type Node, type NodeChange, type EdgeChange,
  type OnNodesChange, type OnEdgesChange,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { FlowNodeType } from '@/lib/flow-api'
import { NODE_TYPE_LABELS, type FlowCanvasEdge, type FlowCanvasNode } from './canvas-dto'
import { FLOW_NODE_TYPES } from './flow-node-card'

interface FlowCanvasProps {
  nodes: FlowCanvasNode[]
  edges: FlowCanvasEdge[]
  onNodesChange: OnNodesChange<FlowCanvasNode>
  onEdgesChange: OnEdgesChange<FlowCanvasEdge>
  onConnect: (connection: Connection) => void
  onAddNode: (nodeType: FlowNodeType) => void
  onSelectNode: (nodeId: string | null) => void
  readOnly: boolean
  nodeCount: number
  maxNodes: number
}

export function FlowCanvas({
  nodes, edges, onNodesChange, onEdgesChange, onConnect, onAddNode, onSelectNode,
  readOnly, nodeCount, maxNodes,
}: FlowCanvasProps) {
  return (
    // 窄屏（390px）纵向堆叠：节点面板在上横向滚动，画布在下；≥md 恢复左栏右画布
    <div className="flex h-full min-h-0 flex-col md:flex-row">
      {!readOnly && (
        <aside
          className="flex w-full shrink-0 flex-row items-center gap-1.5 overflow-x-auto border-b border-slate-200 bg-white p-2.5 md:w-36 md:flex-col md:items-stretch md:overflow-visible md:border-b-0 md:border-r"
          data-testid="flow-palette">
          <p className="shrink-0 whitespace-nowrap px-1 text-xs font-medium text-slate-500">添加节点</p>
          {(Object.keys(NODE_TYPE_LABELS) as FlowNodeType[]).map((type) => (
            <button
              key={type}
              type="button"
              onClick={() => onAddNode(type)}
              disabled={nodeCount >= maxNodes}
              className="w-auto shrink-0 whitespace-nowrap rounded-md border border-slate-200 px-2 py-1.5 text-left text-xs text-slate-700 transition-colors hover:border-slate-400 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 md:w-full"
              title={nodeCount >= maxNodes ? `已达节点上限 ${maxNodes}` : `添加${NODE_TYPE_LABELS[type]}节点`}
            >
              {NODE_TYPE_LABELS[type]}
            </button>
          ))}
          <p className="shrink-0 whitespace-nowrap px-1 text-[11px] text-slate-400 md:pt-1">
            节点 {nodeCount}/{maxNodes}
          </p>
        </aside>
      )}
      <div className="min-w-0 flex-1" data-testid="flow-canvas-pane">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={FLOW_NODE_TYPES}
          onNodesChange={onNodesChange as OnNodesChange<Node>}
          onEdgesChange={onEdgesChange as OnEdgesChange<Edge>}
          onConnect={onConnect}
          onNodeClick={(_, node) => onSelectNode(node.id)}
          onPaneClick={() => onSelectNode(null)}
          nodesDraggable={!readOnly}
          nodesConnectable={!readOnly}
          edgesReconnectable={false}
          deleteKeyCode={readOnly ? null : ['Backspace', 'Delete']}
          fitView
          proOptions={{ hideAttribution: false }}
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
          <Controls showInteractive={!readOnly} />
          <MiniMap pannable zoomable className="!bg-slate-50" />
        </ReactFlow>
      </div>
    </div>
  )
}

export type { NodeChange, EdgeChange }
