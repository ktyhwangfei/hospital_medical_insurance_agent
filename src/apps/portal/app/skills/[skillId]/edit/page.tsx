'use client'

import { use, useCallback, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import {
  ArrowLeft, Save, ShieldCheck, Package, Rocket, AlertCircle,
  Loader2, CheckCircle2, XCircle, Sparkles,
} from 'lucide-react'
import {
  getSkillDraft, saveSkillDraft, validateSkillDraft, previewSkillPackage, materializeSkill,
  getSkillInputSelector, validateSkillInputs, optimizeSkillAIDraft,
  ApiClientError,
} from '@/lib/skill-draft-api'
import { SkillGenerationDiff } from '@/components/skills/skill-generation-diff'
import { SkillCandidateEvaluationPanel } from '@/components/skills/skill-candidate-evaluation-panel'
import ExecutionContractEditor from '@/components/skills/execution-contract-editor'
import type {
  SkillDraftResponse, SkillStructuredConfig, SkillValidationResponse,
  SkillPackagePreviewResponse, SkillInputSelectorResponse, SkillInputValidationResponse,
  SkillAIOptimizationProposal,
} from '@/lib/types'

// /skills/[skillId]/edit 草稿编辑器（设计 §4.3 §5）：
// 结构化编辑为主，输入指标契约，校验，包预览，物化
export default function SkillEditorPage({ params }: { params: Promise<{ skillId: string }> }) {
  const { skillId } = use(params)
  const router = useRouter()
  const searchParams = useSearchParams()
  const draftId = searchParams.get('draft') ?? ''

  const [draft, setDraft] = useState<SkillDraftResponse | null>(null)
  const [config, setConfig] = useState<SkillStructuredConfig | null>(null)
  const [savedConfig, setSavedConfig] = useState<SkillStructuredConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saveMsg, setSaveMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null) // 'save' | 'validate' | 'preview' | 'materialize'

  const [validation, setValidation] = useState<SkillValidationResponse | null>(null)
  const [packagePreview, setPackagePreview] = useState<SkillPackagePreviewResponse | null>(null)
  const [selector, setSelector] = useState<SkillInputSelectorResponse | null>(null)
  const [inputValidation, setInputValidation] = useState<SkillInputValidationResponse | null>(null)
  const [optimizationRequest, setOptimizationRequest] = useState('')
  const [optimizationProposal, setOptimizationProposal] = useState<SkillAIOptimizationProposal | null>(null)
  const [optimizationError, setOptimizationError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!draftId) {
      setError('缺少 draft 参数，请从草稿列表进入')
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const [d, sel] = await Promise.all([
        getSkillDraft(draftId),
        getSkillInputSelector().catch(() => null),
      ])
      setDraft(d)
      setConfig(d.structured_config)
      setSavedConfig(d.structured_config)
      setSelector(sel)
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '加载草稿失败')
    } finally {
      setLoading(false)
    }
  }, [draftId])

  useEffect(() => {
    // 页面进入时加载服务端草稿；load 内的状态更新发生在异步请求完成后。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [load])

  // dirty 状态：config 与上次保存的快照不一致时为脏，底部保存条据此显隐
  const isDirty = config !== null && savedConfig !== null
    && JSON.stringify(config) !== JSON.stringify(savedConfig)

  // dirty 时离开页面提示（防止误关丢失修改）
  useEffect(() => {
    if (!isDirty) return
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault()
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [isDirty])

  function discardChanges() {
    if (savedConfig) setConfig(savedConfig)
  }

  async function handleSave() {
    if (!draft || !config) return
    setBusy('save')
    setSaveMsg(null)
    try {
      const updated = await saveSkillDraft(draft.draft_id, {
        structured_config: config,
        expected_revision: draft.revision,
        etag: draft.etag,
      })
      setDraft(updated)
      setSavedConfig(config)
      setSaveMsg('保存成功')
    } catch (err) {
      setSaveMsg(err instanceof ApiClientError ? err.detail.message : '保存失败')
    } finally {
      setBusy(null)
    }
  }

  async function handleOptimize() {
    if (!draft || !config || !optimizationRequest.trim()) return
    // 收集 metric_codes：优先 execution_contract（common ∪ profiles），兼容旧 inputs
    const ecMetrics: string[] = config.execution_contract
      ? [
          ...config.execution_contract.common.metric_inputs.map((m) => m.metric_code),
          ...config.execution_contract.profiles.flatMap((p) => (p.metric_inputs ?? []).map((m) => m.metric_code)),
        ]
      : []
    const metricCodes = ecMetrics.length > 0
      ? Array.from(new Set(ecMetrics))
      : (config.inputs ?? []).map((input) => input.metric_code)
    if (metricCodes.length === 0) {
      setOptimizationError('请先为草稿选择至少一个输入指标。')
      return
    }
    setBusy('optimize')
    setOptimizationError(null)
    try {
      const proposal = await optimizeSkillAIDraft(draft.draft_id, {
        description: optimizationRequest.trim(),
        metric_codes: metricCodes,
        expected_revision: draft.revision,
      })
      setOptimizationProposal(proposal)
    } catch (err) {
      setOptimizationError(
        err instanceof ApiClientError ? err.detail.message : 'AI 优化失败，请稍后重试。',
      )
    } finally {
      setBusy(null)
    }
  }

  async function handleAcceptOptimization(proposal: SkillAIOptimizationProposal) {
    if (!draft) return
    setBusy('accept-optimize')
    setOptimizationError(null)
    try {
      const updated = await saveSkillDraft(draft.draft_id, {
        structured_config: proposal.structured_config,
        raw_files: proposal.raw_files,
        expected_revision: proposal.base_revision,
      })
      setDraft(updated)
      setConfig(updated.structured_config)
      setSavedConfig(updated.structured_config)
      setOptimizationProposal(null)
      setSaveMsg('优化已接受并保存')
    } catch (err) {
      if (err instanceof ApiClientError && err.status === 409) {
        setOptimizationError('草稿已被其他操作更新。差异提案已保留，请重新加载草稿后再生成。')
      } else {
        setOptimizationError(
          err instanceof ApiClientError ? err.detail.message : '接受优化失败，当前草稿未改变。',
        )
      }
    } finally {
      setBusy(null)
    }
  }

  async function handleValidate() {
    if (!draft) return
    setBusy('validate')
    try {
      const result = await validateSkillDraft(draft.draft_id)
      setValidation(result)
      setDraft((current) => current ? {
        ...current,
        status: result.blocking_ok ? 'validated' : 'editing',
        revision: result.revision,
      } : current)
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '校验失败')
    } finally {
      setBusy(null)
    }
  }

  async function handlePreview() {
    if (!draft) return
    setBusy('preview')
    setPackagePreview(null)
    try {
      const result = await previewSkillPackage(draft.draft_id)
      setPackagePreview(result)
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '预览失败')
    } finally {
      setBusy(null)
    }
  }

  async function handleMaterialize() {
    if (!draft) return
    const reason = window.prompt('请输入物化发布原因（将记录到审计）')
    if (!reason) return
    setBusy('materialize')
    try {
      await materializeSkill(
        { draft_id: draft.draft_id, expected_revision: draft.revision, reason },
        `materialize-${draft.draft_id}-${Date.now()}`,
      )
      router.push(`/skills/${encodeURIComponent(skillId)}`)
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '物化失败')
    } finally {
      setBusy(null)
    }
  }

  async function checkInputs(metricCodes: string[]) {
    if (metricCodes.length === 0) {
      setInputValidation(null)
      return
    }
    try {
      const result = await validateSkillInputs(metricCodes)
      setInputValidation(result)
    } catch {
      setInputValidation(null)
    }
  }

  if (loading) {
    return <div className="mt-10 text-center text-slate-400"><Loader2 className="mx-auto h-8 w-8 animate-spin" /></div>
  }

  if (error && !draft) {
    return (
      <div className="mt-4 space-y-3">
        <button onClick={() => router.push('/skills/drafts')} className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900">
          <ArrowLeft className="h-4 w-4" /> 返回草稿列表
        </button>
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" /> {error}
        </div>
      </div>
    )
  }

  if (!draft || !config) return null

  const bm = config.business_mounting ?? { business_action: 'explain', business_object: 'settlement' }
  // 后端规范字段（draft_service._build_template_config / AI schema / package_generator 一致）：
  //   basic.{skill_id, skill_name, description, owner}
  //   business_mounting.{business_action, business_object, include_keywords, excluded_intents}
  // 读取兼容历史草稿（顶层 description/owner、business_mounting.keywords），
  // 写回一律归一到规范字段——包生成器只读 include_keywords，写入旧 keywords 会失效。
  const keywords = bm.include_keywords ?? bm.keywords ?? []
  const description = config.basic?.description ?? config.description ?? ''
  const owner = config.basic?.owner ?? config.owner ?? ''
  function updateBm(patch: Partial<typeof bm>) {
    setConfig({
      ...config!,
      business_mounting: {
        business_action: bm.business_action,
        business_object: bm.business_object,
        include_keywords: keywords,
        excluded_intents: bm.excluded_intents ?? [],
        ...patch,
      },
    })
  }
  function updateBasic(patch: Partial<NonNullable<SkillStructuredConfig['basic']>>) {
    setConfig({
      ...config!,
      basic: {
        ...(config!.basic ?? {
          skill_id: draft!.skill_id,
          skill_name: draft!.skill_name,
          description: '',
          owner: '',
        }),
        ...patch,
      },
    })
  }

  return (
    <div className="mt-4 space-y-4">
      <button onClick={() => router.push('/skills/drafts')} className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900">
        <ArrowLeft className="h-4 w-4" /> 返回草稿列表
      </button>

      <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-slate-900">
            编辑草稿：{draft.skill_name}
          </h2>
          <p className="text-sm text-slate-500">
            <code className="rounded bg-slate-100 px-1 text-xs">{draft.skill_id}</code>
            {' · '}状态: {draft.status} · revision: {draft.revision}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button onClick={() => void handleSave()} disabled={busy === 'save'} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
            {busy === 'save' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} 保存
          </button>
          <button onClick={() => void handleValidate()} disabled={!!busy} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
            {busy === 'validate' ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />} 校验
          </button>
          <button onClick={() => void handlePreview()} disabled={!!busy} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
            {busy === 'preview' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Package className="h-4 w-4" />} 包预览
          </button>
          <button onClick={() => void handleMaterialize()} disabled={!!busy || draft.status !== 'validated'} className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50">
            {busy === 'materialize' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />} 物化发布
          </button>
        </div>
      </header>

      {saveMsg && (
        <div className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm ${saveMsg === '保存成功' ? 'border border-emerald-200 bg-emerald-50 text-emerald-700' : 'border border-red-200 bg-red-50 text-red-700'}`}>
          {saveMsg === '保存成功' ? <CheckCircle2 className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />} {saveMsg}
        </div>
      )}
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" /> {error}
        </div>
      )}

      <section className="space-y-3 rounded-xl border border-violet-200 bg-violet-50/40 p-4">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Sparkles className="h-4 w-4 text-violet-600" /> AI 优化草稿
          </h3>
          <p className="mt-1 text-xs text-slate-500">先生成只读差异提案；只有点击“接受优化”后才会保存。</p>
        </div>
        <textarea
          value={optimizationRequest}
          onChange={(event) => setOptimizationRequest(event.target.value)}
          rows={2}
          maxLength={4000}
          placeholder="例如：补充面向收费员的解释示例，并简化输出措辞"
          aria-label="AI 优化要求"
          className="w-full rounded-lg border border-violet-200 bg-white px-3 py-2 text-sm"
        />
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-slate-500">使用当前 revision {draft.revision} 与已选输入指标生成提案。</p>
          <button
            type="button"
            onClick={() => void handleOptimize()}
            disabled={!!busy || !optimizationRequest.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy === 'optimize' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            生成优化提案
          </button>
        </div>
        {optimizationError && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800" role="alert">
            <span>{optimizationError}</span>
            {optimizationError.includes('重新加载') && (
              <button type="button" onClick={() => void load()} className="shrink-0 font-medium underline">
                重新加载草稿
              </button>
            )}
          </div>
        )}
      </section>

      {optimizationProposal && (
        <SkillGenerationDiff
          proposal={optimizationProposal}
          accepting={busy === 'accept-optimize'}
          onAccept={handleAcceptOptimization}
          onDismiss={() => {
            setOptimizationProposal(null)
            setOptimizationError(null)
          }}
        />
      )}

      <SkillCandidateEvaluationPanel
        draftId={draft.draft_id}
        disabled={draft.status !== 'validated'}
      />

      <div className="flex flex-col gap-4">
        {/* 结构化编辑 */}
        <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-800">结构化配置</h3>
          <div>
            <label className="block text-sm font-medium text-slate-700">说明</label>
            <textarea value={description} onChange={(e) => updateBasic({ description: e.target.value })} rows={2} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">负责人</label>
            <input value={owner} onChange={(e) => updateBasic({ owner: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-slate-700">BusinessAction</label>
              <input value={bm.business_action} onChange={(e) => updateBm({ business_action: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">BusinessObject</label>
              <input value={bm.business_object} onChange={(e) => updateBm({ business_object: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">触发关键词（逗号分隔）</label>
            <input
              value={keywords.join(', ')}
              onChange={(e) => updateBm({ include_keywords: e.target.value.split(/[,，\s]+/).filter(Boolean) })}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
        </section>

        {/* 输入输出契约：执行契约编辑器（设计 §44，替换旧自由文本 inputs） */}
        {config && (
          <ExecutionContractEditor
            contract={config.execution_contract}
            selector={selector}
            onChange={(ec) => setConfig({ ...config, execution_contract: ec })}
          />
        )}

        {/* 旧版输入指标契约（无 execution_contract 时展示，提示升级） */}
        {config && !config.execution_contract && (config.inputs ?? []).length > 0 && (
          <section className="space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-800">旧版输入指标契约</h3>
              <span className="text-xs text-amber-700">该草稿使用旧版 inputs，建议升级为执行契约</span>
            </div>
            <div className="space-y-2">
              {(config.inputs ?? []).map((input, i) => (
                <div key={i} className="flex items-center gap-2 rounded-lg border border-slate-100 bg-white p-2 text-sm">
                  <code className="flex-1 font-mono text-xs text-blue-700">{input.metric_code}</code>
                  <input
                    value={input.alias ?? ''}
                    onChange={(e) => {
                      const inputs = [...(config.inputs ?? [])]
                      inputs[i] = { ...input, alias: e.target.value }
                      setConfig({ ...config, inputs })
                    }}
                    placeholder="别名"
                    className="w-24 rounded border border-slate-200 px-2 py-1 text-xs"
                  />
                  <label className="flex items-center gap-1 text-xs text-slate-600">
                    <input
                      type="checkbox"
                      checked={input.required}
                      onChange={(e) => {
                        const inputs = [...(config.inputs ?? [])]
                        inputs[i] = { ...input, required: e.target.checked }
                        setConfig({ ...config, inputs })
                      }}
                    />
                    必填
                  </label>
                  <button
                    type="button"
                    onClick={() => setConfig({ ...config, inputs: (config.inputs ?? []).filter((_, j) => j !== i) })}
                    className="text-red-500 hover:text-red-700"
                  >
                    <XCircle className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>

      {/* 校验结果 */}
      {validation && (
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-800">
            <ShieldCheck className="h-4 w-4" /> 校验结果 {validation.blocking_ok ? '✓ 通过' : '✗ 有阻塞'}
          </h3>
          {validation.issues.some((i) => i.severity === 'blocking') && (
            <div className="space-y-1">
              {validation.issues.filter((i) => i.severity === 'blocking').map((issue, i) => (
                <div key={`b-${i}`} className="flex items-center gap-2 rounded bg-red-50 px-3 py-1.5 text-xs text-red-700">
                  <XCircle className="h-3.5 w-3.5 shrink-0" /> [{issue.code}] {issue.path ?? '—'}: {issue.message}
                </div>
              ))}
            </div>
          )}
          {validation.issues.some((i) => i.severity === 'warning') && (
            <div className="mt-1 space-y-1">
              {validation.issues.filter((i) => i.severity === 'warning').map((issue, i) => (
                <div key={`w-${i}`} className="flex items-center gap-2 rounded bg-amber-50 px-3 py-1.5 text-xs text-amber-700">
                  <AlertCircle className="h-3.5 w-3.5 shrink-0" /> [{issue.code}] {issue.path ?? '—'}: {issue.message}
                </div>
              ))}
            </div>
          )}
          {validation.blocking_ok && (
            <p className="text-xs text-emerald-700">校验通过，可进行物化发布。</p>
          )}
        </section>
      )}

      {/* 包预览 */}
      {packagePreview && (
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Package className="h-4 w-4" /> 包预览
          </h3>
          <div className="space-y-2">
            {packagePreview.files.map((f) => (
              <details key={f.path} className="rounded-lg bg-slate-900 p-2">
                <summary className="cursor-pointer font-mono text-xs text-emerald-400">{f.path}</summary>
                <pre className="mt-2 max-h-48 overflow-auto text-xs text-slate-100">{f.content}</pre>
              </details>
            ))}
          </div>
        </section>
      )}

      {/* 底部固定保存条：config 有未保存修改时显示 */}
      {isDirty && (
        <div className="sticky bottom-0 z-10 flex items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-2.5 shadow-lg">
          <span className="flex items-center gap-2 text-sm text-amber-800">
            <AlertCircle className="h-4 w-4 shrink-0" />
            有未保存的修改
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={discardChanges}
              disabled={!!busy}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              放弃修改
            </button>
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={!!busy}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {busy === 'save' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              保存
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
