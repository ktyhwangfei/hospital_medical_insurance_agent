'use client'

// Tool 可视化管理与 Workflow 编排 /tools 页 — 第一批增量的只读展示。
// Tool 页签：已注册 Tool 清单（契约类型/包装目标/风险等级/是否已绑定实现）。
// Workflow 页签：静态 Workflow 定义可视化为混合节点链（未绑定实现的节点高亮，对应
// fail-closed：该步骤运行时会报 unavailable，不会编造结果）。
import { useEffect, useState } from 'react'
import { ArrowRight, Boxes, Loader2, Workflow as WorkflowIcon } from 'lucide-react'
import {
  listTools,
  listWorkflows,
  type ToolCatalogDto,
  type WorkflowCatalogDto,
} from '@/lib/tool-workflow-api'
import { ApiClientError } from '@/lib/types'

const RISK_BADGES: Record<string, string> = {
  low: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  medium: 'border-amber-200 bg-amber-50 text-amber-700',
  high: 'border-red-200 bg-red-50 text-red-700',
}

const CATEGORY_BADGES: Record<string, string> = {
  数据类: 'border-sky-200 bg-sky-50 text-sky-700',
  知识类: 'border-violet-200 bg-violet-50 text-violet-700',
}

const NODE_LABELS = {
  tool: 'Tool 节点',
  domain: '领域节点',
  decision: '决策节点',
  output: '输出节点',
} as const

function BoundBadge({ bound }: { bound: boolean }) {
  return (
    <span
      className={`rounded border px-1.5 py-0.5 text-[11px] font-medium ${
        bound
          ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
          : 'border-slate-300 bg-slate-100 text-slate-500'
      }`}
    >
      {bound ? '已绑定实现' : '未绑定 · 无数据源'}
    </span>
  )
}

export default function ToolsPage() {
  const [tab, setTab] = useState<'tools' | 'workflows'>('tools')
  const [tools, setTools] = useState<ToolCatalogDto | null>(null)
  const [workflows, setWorkflows] = useState<WorkflowCatalogDto | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([listTools(), listWorkflows()])
      .then(([toolCatalog, workflowCatalog]) => {
        if (cancelled) return
        setTools(toolCatalog)
        setWorkflows(workflowCatalog)
        setError(null)
      })
      .catch((e) => {
        if (cancelled) return
        setError(e instanceof ApiClientError ? e.message : String(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <header className="flex items-start gap-3">
        <div className="flex size-10 items-center justify-center rounded-lg bg-slate-900 text-white">
          <Boxes className="size-5" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Tool 与 Workflow</h1>
          <p className="mt-0.5 text-xs text-slate-500">
            Tool、确定性领域处理与输出节点统一编排；只读展示，不新增业务写入口
          </p>
        </div>
      </header>

      <div className="mt-4 flex gap-1 border-b border-slate-200" data-testid="tool-workflow-tabs">
        {(['tools', 'workflows'] as const).map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`-mb-px border-b-2 px-3 py-1.5 text-xs font-medium ${
              tab === key
                ? 'border-slate-900 text-slate-900'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            {key === 'tools' ? 'Tool 清单' : 'Workflow 编排'}
          </button>
        ))}
      </div>

      {error && (
        <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700" data-testid="tool-workflow-error">
          {error}
        </p>
      )}

      {loading && (
        <div className="flex h-20 items-center justify-center gap-2 text-sm text-slate-500">
          <Loader2 className="size-4 animate-spin" /> 加载中…
        </div>
      )}

      {!loading && tab === 'tools' && tools && (
        <section className="mt-4" data-testid="tool-catalog">
          <ul className="divide-y divide-slate-100 rounded-md border border-slate-200">
            {tools.items.map((tool) => (
              <li key={tool.tool_id} className="px-3 py-3" data-testid={`tool-item-${tool.tool_id}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-slate-800">{tool.name}</span>
                  <span className="font-mono text-[11px] text-slate-400">{tool.tool_id}</span>
                  {tool.tags[0] && (
                    <span
                      className={`rounded border px-1.5 py-0.5 text-[11px] font-medium ${
                        CATEGORY_BADGES[tool.tags[0]] ?? 'border-slate-200 bg-slate-50 text-slate-600'
                      }`}
                    >
                      {tool.tags[0]}
                    </span>
                  )}
                  <span className={`rounded border px-1.5 py-0.5 text-[11px] ${RISK_BADGES[tool.risk_level] ?? RISK_BADGES.low}`}>
                    风险：{tool.risk_level}
                  </span>
                  <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-600">
                    {tool.contract_kind === 'function' ? '函数包装' : 'Adapter Protocol'}
                  </span>
                  <BoundBadge bound={tool.bound} />
                </div>
                <p className="mt-1.5 text-xs text-slate-600">{tool.description}</p>
                <p className="mt-1 font-mono text-[11px] text-slate-400">target_ref: {tool.target_ref}</p>
              </li>
            ))}
            {tools.items.length === 0 && (
              <li className="px-3 py-6 text-center text-xs text-slate-400">暂无已注册 Tool</li>
            )}
          </ul>
        </section>
      )}

      {!loading && tab === 'workflows' && workflows && (
        <section className="mt-4 space-y-4" data-testid="workflow-catalog">
          {workflows.items.map((workflow) => (
            <div
              key={workflow.workflow_id}
              className="rounded-md border border-slate-200 p-3"
              data-testid={`workflow-item-${workflow.workflow_id}`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <WorkflowIcon className="size-4 text-slate-500" />
                <span className="text-sm font-medium text-slate-800">{workflow.name}</span>
                <span className="font-mono text-[11px] text-slate-400">{workflow.workflow_id}</span>
              </div>
              <p className="mt-1.5 text-xs text-slate-600">{workflow.description}</p>

              <div className="mt-2 flex flex-wrap gap-1.5">
                {workflow.intent_keywords.map((keyword) => (
                  <span
                    key={keyword}
                    className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600"
                  >
                    {keyword}
                  </span>
                ))}
              </div>

              {workflow.missing_evidence_rules.length > 0 && (
                <div className="mt-2 rounded-md border border-dashed border-slate-200 bg-slate-50 px-2.5 py-1.5 text-[11px] text-slate-500">
                  {workflow.missing_evidence_rules.map((rule) => (
                    <div key={rule.field_name}>
                      缺 <span className="font-mono text-slate-600">{rule.field_name}</span> → {rule.clarify_message}
                    </div>
                  ))}
                </div>
              )}

              <div className="mt-3 flex flex-wrap items-center gap-1.5" data-testid={`workflow-steps-${workflow.workflow_id}`}>
                {workflow.steps.map((step, index) => (
                  <div key={step.step_id} className="flex items-center gap-1.5">
                    <div
                      className={`rounded-md border px-2.5 py-1.5 text-xs ${
                        step.bound
                          ? 'border-slate-200 bg-white text-slate-700'
                          : 'border-dashed border-slate-300 bg-slate-50 text-slate-400'
                      }`}
                      title={step.description}
                    >
                      <div className="flex items-center gap-1.5">
                        <span className="font-medium">{step.step_id}</span>
                        <span className="rounded bg-slate-100 px-1 py-0.5 text-[9px] text-slate-500">
                          {NODE_LABELS[step.node_type]}
                        </span>
                      </div>
                      <div className="font-mono text-[10px]">
                        {step.node_type === 'tool' && step.tool_id}
                        {step.node_type === 'domain' && `${step.handler_id}:${step.handler_version}`}
                        {step.node_type === 'decision' && `${step.condition_ref} = ${String(step.expected_value)}`}
                        {step.node_type === 'output' && `输出 ← ${step.source_ref}`}
                      </div>
                      {step.node_type === 'decision' && (
                        <div className="mt-1 border-t border-slate-100 pt-1 font-mono text-[10px] text-slate-500">
                          是 → {step.match_step_id}；否 → {step.default_step_id}
                        </div>
                      )}
                      {step.node_type !== 'output' && Object.keys(step.input_mapping).length > 0 ? (
                        <div className="mt-1 space-y-0.5 border-t border-slate-100 pt-1">
                          {Object.entries(step.input_mapping).map(([param, ref]) => (
                            <div key={param} className="font-mono text-[10px] text-slate-500">
                              {param} ← {ref}
                            </div>
                          ))}
                        </div>
                      ) : step.node_type !== 'output' ? (
                        <div className="mt-1 border-t border-slate-100 pt-1 font-mono text-[10px] text-slate-400">
                          输入 ← 会话上下文
                        </div>
                      ) : null}
                      {!step.bound && (
                        <div className="mt-0.5 text-[10px] text-red-500">
                          {step.node_type === 'tool' ? '无数据源' : '未绑定实现'} → unavailable
                        </div>
                      )}
                    </div>
                    {index < workflow.steps.length - 1 && (
                      <ArrowRight className="size-3.5 shrink-0 text-slate-300" />
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
          {workflows.items.length === 0 && (
            <p className="rounded-md border border-dashed border-slate-200 px-3 py-6 text-center text-xs text-slate-400">
              暂无已声明 Workflow
            </p>
          )}
        </section>
      )}
    </main>
  )
}
