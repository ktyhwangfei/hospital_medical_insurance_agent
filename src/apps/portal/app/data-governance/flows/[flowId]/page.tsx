'use client'

// 治理 Flow 画布编辑页（Phase 2）：/data-governance/flows/<flowId>。
// 位于 (manage) 路由组之外：编辑器需要全屏画布，不套数据治理中心的头部与 tabs。
// 画布状态为唯一节点真源（data.definition 全量随行，保存时组装 FlowDefinition PUT）；
// 生命周期动作按状态机门控（draft→validating→pending_review→published→deprecated）。
import { useCallback, useEffect, useMemo, useRef, useState, use } from 'react'
import { useRouter } from 'next/navigation'
import {
  addEdge, useEdgesState, useNodesState,
  type Connection, type NodeSelectionChange, type OnNodesChange,
} from '@xyflow/react'
import { ArrowLeft, Loader2, Play, Save, Send, Trash2, FileCode2 } from 'lucide-react'
import {
  deprecateFlow, getFlow, listFlowRevisions, previewFlow,
  publishFlow, rollbackFlow, submitFlowReview, updateFlow, validateFlow,
} from '@/lib/flow-api'
import type {
  CompiledFlowArtifactDto, FlowDefinitionDto, FlowNodeType,
  FlowRevisionViewDto, FlowStatus, FlowValidationReportDto,
} from '@/lib/flow-api'
import { ApiClientError } from '@/lib/types'
import { MAX_FLOW_NODES } from '@/lib/flow-api'
import {
  canvasToDefinition, definitionToCanvas, newNodeDefinition, nextEdgeId,
  type FlowCanvasEdge, type FlowCanvasNode,
} from '@/components/flow/canvas-dto'
import { FlowCanvas } from '@/components/flow/flow-canvas'
import { NodePropertyPanel } from '@/components/flow/node-property-panel'
import { PreviewPanel, RevisionsPanel, ValidationPanel } from '@/components/flow/flow-detail-panels'

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

type DetailTab = 'validation' | 'preview' | 'revisions'

export default function FlowEditorPage({ params }: { params: Promise<{ flowId: string }> }) {
  const { flowId } = use(params)
  const router = useRouter()

  const [flow, setFlow] = useState<FlowDefinitionDto | null>(null)
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowCanvasNode>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowCanvasEdge>([])
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [report, setReport] = useState<FlowValidationReportDto | null>(null)
  const [artifact, setArtifact] = useState<CompiledFlowArtifactDto | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [revisions, setRevisions] = useState<FlowRevisionViewDto[]>([])
  const [detailTab, setDetailTab] = useState<DetailTab>('validation')

  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [publishedBy, setPublishedBy] = useState('')
  const nodeSeq = useRef(0)

  const readOnly = flow?.status === 'deprecated'

  const reportFromError = useCallback((error: unknown, fallback: string) => {
    if (error instanceof ApiClientError) {
      const issues = error.detail.audit_event?.issues
      if (Array.isArray(issues) && issues.length > 0) {
        setReport({ issues, has_blocking: issues.some((i: { severity: string }) => i.severity === 'blocking') })
        setDetailTab('validation')
      }
      if (error.status === 409) {
        setMessage(`${error.detail.message}（他人可能已保存新版，请刷新页面重载）`)
        return
      }
    }
    setMessage(fallback + (error instanceof Error ? `：${error.message}` : ''))
  }, [])

  const reloadRevisions = useCallback(async () => {
    try {
      setRevisions(await listFlowRevisions(flowId))
    } catch {
      /* 无发布证据时 404 不打断编辑 */
    }
  }, [flowId])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const loaded = await getFlow(flowId)
        if (cancelled) return
        const canvas = definitionToCanvas(loaded)
        setFlow(loaded)
        setNodes(canvas.nodes)
        setEdges(canvas.edges)
        setPublishedBy(loaded.owner)
        nodeSeq.current = loaded.nodes.length
        reloadRevisions()
      } catch (error) {
        if (!cancelled) setLoadError(error instanceof Error ? error.message : String(error))
      }
    })()
    return () => { cancelled = true }
  }, [flowId, setNodes, setEdges, reloadRevisions])

  // 校验问题数注入节点徽标（报告变化时重算；报告清空时归零）
  useEffect(() => {
    const counts = new Map<string, number>()
    for (const issue of report?.issues ?? []) {
      if (issue.node_id) counts.set(issue.node_id, (counts.get(issue.node_id) ?? 0) + 1)
    }
    setNodes((current) => current.map((n) => ({
      ...n,
      data: { ...n.data, issueCount: counts.get(n.id) ?? 0 },
    })))
  }, [report, setNodes])

  const mutateNode = useCallback((node: FlowCanvasNode['data']['definition']) => {
    setNodes((current) => current.map((n) =>
      n.id === node.node_id ? { ...n, data: { ...n.data, definition: node } } : n,
    ))
  }, [setNodes])

  // 键盘 Enter 选中节点只产生 selection change（不经 onNodeClick），此处同步属性面板
  const handleNodesChange: OnNodesChange<FlowCanvasNode> = useCallback((changes) => {
    onNodesChange(changes)
    const picked = changes.find((c): c is NodeSelectionChange => c.type === 'select' && c.selected)
    const dropped = changes.some((c) => c.type === 'select' && !c.selected)
    if (picked) setSelectedNodeId(picked.id)
    else if (dropped) setSelectedNodeId(null)
  }, [onNodesChange])

  const deleteNode = useCallback((nodeId: string) => {
    setNodes((current) => current.filter((n) => n.id !== nodeId))
    setEdges((current) => current.filter((e) => e.source !== nodeId && e.target !== nodeId))
    setSelectedNodeId(null)
  }, [setNodes, setEdges])

  const addNode = useCallback((nodeType: FlowNodeType) => {
    if (nodes.length >= MAX_FLOW_NODES) return
    nodeSeq.current += 1
    const definition = newNodeDefinition(nodeType, nodeSeq.current)
    setNodes((current) => [
      ...current,
      {
        id: definition.node_id,
        type: nodeType,
        position: { x: 80 + (current.length % 5) * 220, y: 60 + Math.floor(current.length / 5) * 140 },
        data: { definition, issueCount: 0 },
        selected: true,
      },
    ])
    setSelectedNodeId(definition.node_id)
  }, [nodes.length, setNodes])

  const onConnect = useCallback((connection: Connection) => {
    if (connection.source === connection.target) return
    setEdges((current) => addEdge({ ...connection, id: nextEdgeId() }, current))
  }, [setEdges])

  const run = useCallback(async (key: string, action: () => Promise<void>) => {
    setBusy(key)
    setMessage(null)
    try {
      await action()
    } catch (error) {
      reportFromError(error, '操作失败')
    } finally {
      setBusy(null)
    }
  }, [reportFromError])

  const handleSave = () => run('save', async () => {
    if (!flow) return
    const saved = await updateFlow(flowId, canvasToDefinition(flow, nodes, edges), flow.revision)
    setFlow(saved)
    setMessage(`已保存为修订 ${saved.revision}（草稿）`)
  })

  const handleValidate = () => run('validate', async () => {
    const result = await validateFlow(flowId)
    setReport(result)
    setDetailTab('validation')
    const refreshed = await getFlow(flowId)
    setFlow(refreshed)
    setMessage(result.has_blocking ? '校验存在阻断问题' : '校验完成')
  })

  const handleSubmit = () => run('submit', async () => {
    setFlow(await submitFlowReview(flowId))
    setMessage('已提交评审（pending_review），可发布')
  })

  const handlePublish = () => run('publish', async () => {
    if (!publishedBy.trim()) {
      setMessage('发布人不能为空')
      return
    }
    await publishFlow(flowId, publishedBy.trim())
    setFlow(await getFlow(flowId))
    await reloadRevisions()
    setMessage('发布成功，发布证据不可变、可回滚')
  })

  const handleDeprecate = () => run('deprecate', async () => {
    setFlow(await deprecateFlow(flowId))
    setMessage('已退役（终态）；历史发布证据保留')
  })

  const handleRollback = (revisionId: string) => run(`rollback:${revisionId}`, async () => {
    const target = await rollbackFlow(flowId, revisionId)
    await reloadRevisions()
    setMessage(`已回滚并激活 ${target.revision.revision_id}（历史证据未删除）`)
  })

  const loadPreview = useCallback(() => {
    void run('preview', async () => {
      setPreviewLoading(true)
      try {
        setArtifact(await previewFlow(flowId))
        setDetailTab('preview')
      } finally {
        setPreviewLoading(false)
      }
    })
  }, [flowId, run])

  const focusNode = useCallback((nodeId: string) => {
    setSelectedNodeId(nodeId)
    setNodes((current) => current.map((n) => (n.id === nodeId ? { ...n, selected: true } : { ...n, selected: false })))
  }, [setNodes])

  const nodeCount = nodes.length

  const actionBtn = useMemo(() => ({
    base: 'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-40',
    primary: 'bg-slate-900 text-white hover:bg-slate-700',
    secondary: 'border border-slate-300 text-slate-700 hover:border-slate-500',
    danger: 'border border-red-300 text-red-600 hover:bg-red-50',
  }), [])

  if (loadError) {
    return (
      <div className="mx-auto max-w-xl space-y-3 py-16 text-center">
        <p className="text-sm text-red-600">加载 Flow 失败：{loadError}</p>
        <button type="button" onClick={() => router.push('/data-governance/flows')}
          className="inline-flex items-center gap-1 text-xs text-sky-600 hover:underline">
          <ArrowLeft className="size-3.5" />返回列表
        </button>
      </div>
    )
  }
  if (!flow) {
    return (
      <div className="flex h-64 items-center justify-center gap-2 text-sm text-slate-500">
        <Loader2 className="size-4 animate-spin" />加载 Flow…
      </div>
    )
  }

  const canValidate = flow.status === 'draft' || flow.status === 'validating'
  const canSubmit = flow.status === 'draft' || flow.status === 'validating'
  const canPublish = flow.status === 'pending_review'
  const canDeprecate = flow.status === 'published'

  // 窄屏（390px）中段纵向堆叠由内容撑高、外层 main 滚动；桌面恢复 h-full 画布布局
  return (
    <div className="flex flex-col md:h-full md:min-h-0" data-testid="flow-editor-page">
      <header className="space-y-2 border-b border-slate-200 bg-white px-4 py-3">
        <div className="flex items-center gap-3">
          <button type="button" onClick={() => router.push('/data-governance/flows')}
            className="text-slate-400 transition-colors hover:text-slate-700" title="返回列表">
            <ArrowLeft className="size-4" />
          </button>
          <input
            className="min-w-0 flex-1 rounded-md border border-transparent px-1 py-0.5 text-sm font-semibold text-slate-900 hover:border-slate-200 focus:border-slate-400 focus:outline-none disabled:opacity-60"
            value={flow.name} disabled={readOnly}
            onChange={(e) => setFlow({ ...flow, name: e.target.value })} />
          <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_BADGES[flow.status]}`}>
            {STATUS_LABELS[flow.status]}
          </span>
          <span className="shrink-0 text-xs text-slate-400">rev {flow.revision}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={handleSave} disabled={!!busy || readOnly}
            className={`${actionBtn.base} ${actionBtn.primary}`}>
            {busy === 'save' ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
            保存修订
          </button>
          <button type="button" onClick={handleValidate} disabled={!!busy || !canValidate}
            className={`${actionBtn.base} ${actionBtn.secondary}`}>
            {busy === 'validate' ? <Loader2 className="size-3.5 animate-spin" /> : <Play className="size-3.5" />}
            校验
          </button>
          <button type="button" onClick={handleSubmit} disabled={!!busy || !canSubmit}
            className={`${actionBtn.base} ${actionBtn.secondary}`}>
            {busy === 'submit' ? <Loader2 className="size-3.5 animate-spin" /> : <Send className="size-3.5" />}
            提交评审
          </button>
          <span className="flex items-center gap-1">
            <input
              className="w-28 rounded-md border border-slate-200 px-2 py-1.5 text-xs focus:border-slate-400 focus:outline-none"
              value={publishedBy} placeholder="发布人"
              onChange={(e) => setPublishedBy(e.target.value)} />
            <button type="button" onClick={handlePublish} disabled={!!busy || !canPublish}
              className={`${actionBtn.base} ${canPublish ? 'bg-emerald-600 text-white hover:bg-emerald-500' : actionBtn.secondary}`}>
              {busy === 'publish' ? <Loader2 className="size-3.5 animate-spin" /> : <Send className="size-3.5" />}
              发布
            </button>
          </span>
          <button type="button" onClick={handleDeprecate} disabled={!!busy || !canDeprecate}
            className={`${actionBtn.base} ${actionBtn.danger}`}>
            {busy === 'deprecate' ? <Loader2 className="size-3.5 animate-spin" /> : <Trash2 className="size-3.5" />}
            退役
          </button>
          <button type="button" onClick={loadPreview} disabled={!!busy}
            className={`${actionBtn.base} ${actionBtn.secondary}`}>
            {busy === 'preview' ? <Loader2 className="size-3.5 animate-spin" /> : <FileCode2 className="size-3.5" />}
            预览编译产物
          </button>
          {message && <span className="ml-auto max-w-md truncate text-xs text-slate-600" title={message}>{message}</span>}
        </div>
      </header>

      {/* 390px 矩阵：窄屏画布在上（显式高度 + flex-none，纵向 flex 的 basis:0 会压掉 height），属性面板全宽在下；≥md 恢复左画布右面板 */}
      <div className="flex min-h-0 flex-1 flex-col md:flex-row" data-testid="flow-editor-mid">
        <div className="h-[320px] min-w-0 flex-none border-b border-slate-200 md:h-auto md:min-h-0 md:flex-1 md:border-b-0 md:border-r">
          <FlowCanvas
            nodes={nodes} edges={edges}
            onNodesChange={handleNodesChange} onEdgesChange={onEdgesChange}
            onConnect={onConnect} onAddNode={addNode}
            onSelectNode={setSelectedNodeId}
            readOnly={readOnly} nodeCount={nodeCount} maxNodes={MAX_FLOW_NODES} />
        </div>
        <aside
          className="w-full shrink-0 border-t border-slate-200 bg-white md:w-80 md:border-t-0 md:border-l"
          data-testid="flow-editor-aside">
          <NodePropertyPanel
            flow={canvasToDefinition(flow, nodes, edges)}
            selectedNodeId={selectedNodeId} readOnly={readOnly}
            onNodeChange={mutateNode} onDeleteNode={deleteNode}
            onFlowPatch={(patch) => setFlow((current) => (current ? { ...current, ...patch } : current))} />
        </aside>
      </div>

      <section className="h-64 shrink-0 border-t border-slate-200 bg-white" data-testid="flow-detail-section">
        <div className="flex items-center gap-1 border-b border-slate-100 px-3 pt-2">
          {([['validation', '校验报告'], ['preview', '编译预览'], ['revisions', '发布修订']] as const).map(([key, label]) => (
            <button key={key} type="button"
              onClick={() => {
                setDetailTab(key)
                if (key === 'preview' && !artifact) loadPreview()
              }}
              className={`rounded-t-md px-3 py-1.5 text-xs font-medium transition-colors ${
                detailTab === key ? 'border border-b-white border-slate-200 text-slate-900' : 'text-slate-500 hover:text-slate-700'
              }`}>
              {label}
              {key === 'validation' && report?.issues.length
                ? <span className="ml-1 rounded-full bg-red-100 px-1.5 text-[10px] text-red-700">{report.issues.length}</span>
                : null}
            </button>
          ))}
        </div>
        <div className="h-[calc(100%-2.25rem)] overflow-y-auto p-3">
          {detailTab === 'validation' && <ValidationPanel report={report} onFocusNode={focusNode} />}
          {detailTab === 'preview' && (
            <PreviewPanel artifact={artifact} loading={previewLoading} onRefresh={loadPreview} />
          )}
          {detailTab === 'revisions' && (
            <RevisionsPanel revisions={revisions} onRollback={handleRollback}
              rollbackBusy={busy?.startsWith('rollback:') ? busy.slice(9) : null} />
          )}
        </div>
      </section>
    </div>
  )
}
