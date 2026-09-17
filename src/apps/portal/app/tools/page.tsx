'use client'

// Tool 可视化管理与 Workflow 编排 /tools 页 — 第一批增量的只读展示。
// Tool 页签：已注册 Tool 清单（契约类型/包装目标/风险等级/是否已绑定实现）。
// Workflow 页签：静态 Workflow 定义可视化为混合节点链（未绑定实现的节点高亮，对应
// fail-closed：该步骤运行时会报 unavailable，不会编造结果）。
import { useEffect, useState } from 'react'
import { ArrowRight, Boxes, Loader2, Power, Workflow as WorkflowIcon } from 'lucide-react'
import {
  listTools,
  listWorkflows,
  updateWorkflowConfig,
  hasWorkflowWritePermission,
  type ToolCatalogDto,
  type ToolFieldInfoDto,
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

// 输入/输出字段契约区块：优先展示 Tool 的输入参数与返回字段（字段名/类型/必填/说明）。
function ToolFieldTable({
  title,
  fields,
  testId,
}: {
  title: string
  fields: Record<string, ToolFieldInfoDto>
  testId: string
}) {
  const entries = Object.entries(fields)
  if (entries.length === 0) return null
  return (
    <div className="mt-2 min-w-0 overflow-hidden rounded-md border border-slate-100 bg-slate-50/60" data-testid={testId}>
      <div className="border-b border-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-500">{title}</div>
      <table className="w-full table-fixed border-collapse text-left">
        <tbody>
          {entries.map(([fieldName, info]) => (
            <tr key={fieldName} className="align-top">
              <td className="w-[30%] px-2.5 py-1 font-mono text-[11px] text-slate-700">{fieldName}</td>
              <td className="w-[18%] px-1 py-1 font-mono text-[10px] text-slate-500">
                {info.type}
                {'required' in info && (
                  <span className={info.required ? 'text-red-500' : 'text-slate-400'}>
                    {info.required ? ' 必填' : ' 可选'}
                  </span>
                )}
              </td>
              <td className="px-2.5 py-1 text-[11px] text-slate-600">{info.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function ToolsPage() {
  const [tab, setTab] = useState<'tools' | 'workflows'>('tools')
  const [tools, setTools] = useState<ToolCatalogDto | null>(null)
  const [workflows, setWorkflows] = useState<WorkflowCatalogDto | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  // 治理配置：启停开关 + 关键词编辑（写入治理库，同进程立即生效）
  const [savingId, setSavingId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [keywordDraft, setKeywordDraft] = useState('')
  const canWrite = hasWorkflowWritePermission()

  const reload = () =>
    Promise.all([listTools(), listWorkflows()])
      .then(([toolCatalog, workflowCatalog]) => {
        setTools(toolCatalog)
        setWorkflows(workflowCatalog)
        setError(null)
      })
      .catch((e) => setError(e instanceof ApiClientError ? e.message : String(e)))

  const saveConfig = async (
    workflowId: string,
    payload: { enabled: boolean; intent_keywords?: string[] | null },
  ) => {
    setSavingId(workflowId)
    setActionError(null)
    try {
      await updateWorkflowConfig(workflowId, payload)
      await reload()
      setEditingId(null)
    } catch (e) {
      setActionError(e instanceof ApiClientError ? e.message : String(e))
    } finally {
      setSavingId(null)
    }
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    reload().finally(() => {
      if (!cancelled) setLoading(false)
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
            Tool、确定性领域处理与输出节点统一编排；配置院区关键词与启停，不新增业务写入口
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
                <ToolFieldTable
                  title={`输入（${Object.keys(tool.input_schema).length} 个参数）`}
                  fields={tool.input_schema}
                  testId={`tool-input-fields-${tool.tool_id}`}
                />
                <ToolFieldTable
                  title={`输出（${Object.keys(tool.output_schema).length} 个字段）`}
                  fields={tool.output_schema}
                  testId={`tool-output-fields-${tool.tool_id}`}
                />
                {tool.execution_detail && (
                  <details className="mt-2 rounded-md border border-slate-200 bg-slate-900/95" data-testid={`tool-execution-detail-${tool.tool_id}`}>
                    <summary className="cursor-pointer select-none px-2.5 py-1.5 text-[11px] font-medium text-slate-300">
                      执行细节（SQL / 检索语句 / 核心公式）
                    </summary>
                    <pre className="overflow-x-auto border-t border-slate-700/60 px-2.5 py-2 font-mono text-[10px] leading-relaxed text-slate-200">
                      {tool.execution_detail}
                    </pre>
                  </details>
                )}
                <p className="mt-1 font-mono text-[11px] text-slate-400">target_ref: {tool.target_ref}</p>
              </li>
            ))}
            {tools.items.length === 0 && (
              <li className="px-3 py-6 text-center text-xs text-slate-400">暂无已注册 Tool</li>
            )}
          </ul>
        </section>
      )}

      {actionError && (
        <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700" data-testid="workflow-action-error">
          {actionError}
        </p>
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
                {workflow.enabled === false && (
                  <span className="rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-700">
                    已停用
                  </span>
                )}
                {workflow.keyword_source && workflow.keyword_source !== 'default' && (
                  <span
                    className="rounded border border-sky-200 bg-sky-50 px-1.5 py-0.5 text-[11px] text-sky-700"
                    data-testid={`workflow-keyword-source-${workflow.workflow_id}`}
                  >
                    关键词：治理配置（{workflow.keyword_source.replace('+env_disabled', '')}）
                  </span>
                )}
                <span className="ml-auto flex items-center gap-1.5">
                  <button
                    type="button"
                    disabled={!canWrite || savingId === workflow.workflow_id}
                    onClick={() =>
                      saveConfig(workflow.workflow_id, { enabled: workflow.enabled === false })
                    }
                    title={canWrite ? undefined : '缺少 workflow:write 权限'}
                    className="flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-[11px] text-slate-600 disabled:opacity-40"
                    data-testid={`workflow-toggle-${workflow.workflow_id}`}
                  >
                    <Power className="size-3" />
                    {workflow.enabled === false ? '启用' : '停用'}
                  </button>
                  <button
                    type="button"
                    disabled={!canWrite}
                    onClick={() => {
                      setEditingId(workflow.workflow_id)
                      setKeywordDraft(workflow.intent_keywords.join('、'))
                    }}
                    className="rounded border border-slate-200 px-2 py-1 text-[11px] text-slate-600 disabled:opacity-40"
                    data-testid={`workflow-edit-keywords-${workflow.workflow_id}`}
                  >
                    编辑关键词
                  </button>
                </span>
              </div>

              {editingId === workflow.workflow_id && (
                <div className="mt-2 rounded-md border border-slate-200 bg-slate-50 p-2" data-testid={`workflow-keyword-editor-${workflow.workflow_id}`}>
                  <label className="text-[11px] text-slate-500">
                    关键词（顿号/逗号分隔）——决定关键词 fallback 路由命中，改完立即生效
                  </label>
                  <textarea
                    rows={2}
                    value={keywordDraft}
                    onChange={(e) => setKeywordDraft(e.target.value)}
                    className="mt-1 w-full rounded border border-slate-300 px-2 py-1 font-mono text-[11px]"
                    data-testid={`workflow-keyword-input-${workflow.workflow_id}`}
                  />
                  <div className="mt-1.5 flex items-center gap-2">
                    <button
                      type="button"
                      disabled={savingId === workflow.workflow_id}
                      onClick={() =>
                        saveConfig(workflow.workflow_id, {
                          enabled: workflow.enabled !== false,
                          intent_keywords: keywordDraft
                            .split(/[、,，\n]/)
                            .map((item) => item.trim())
                            .filter(Boolean),
                        })
                      }
                      className="rounded bg-slate-900 px-2.5 py-1 text-[11px] font-medium text-white disabled:opacity-40"
                      data-testid={`workflow-keyword-save-${workflow.workflow_id}`}
                    >
                      保存
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingId(null)}
                      className="rounded border border-slate-200 px-2.5 py-1 text-[11px] text-slate-600"
                    >
                      取消
                    </button>
                    <span className="text-[11px] text-slate-400">保存后写入治理库，路由立即生效（无需重启）</span>
                  </div>
                </div>
              )}
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
