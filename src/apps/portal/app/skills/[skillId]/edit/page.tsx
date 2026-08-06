'use client'

import { use, useCallback, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import {
  ArrowLeft, Save, ShieldCheck, Package, Rocket, AlertCircle,
  Loader2, CheckCircle2, XCircle,
} from 'lucide-react'
import {
  getSkillDraft, saveSkillDraft, validateSkillDraft, previewSkillPackage, materializeSkill,
  getSkillInputSelector, validateSkillInputs,
  ApiClientError,
} from '@/lib/skill-draft-api'
import type {
  SkillDraftResponse, SkillStructuredConfig, SkillValidationResponse,
  SkillPackagePreviewResponse, SkillInputSelectorResponse, SkillInputValidationResponse,
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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saveMsg, setSaveMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null) // 'save' | 'validate' | 'preview' | 'materialize'

  const [validation, setValidation] = useState<SkillValidationResponse | null>(null)
  const [packagePreview, setPackagePreview] = useState<SkillPackagePreviewResponse | null>(null)
  const [selector, setSelector] = useState<SkillInputSelectorResponse | null>(null)
  const [inputValidation, setInputValidation] = useState<SkillInputValidationResponse | null>(null)

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
      setSelector(sel)
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '加载草稿失败')
    } finally {
      setLoading(false)
    }
  }, [draftId])

  useEffect(() => {
    void load()
  }, [load])

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
      setSaveMsg('保存成功')
    } catch (err) {
      setSaveMsg(err instanceof ApiClientError ? err.detail.message : '保存失败')
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
  function updateBm(patch: Partial<typeof bm>) {
    setConfig({ ...config!, business_mounting: { ...bm, ...patch } })
  }

  return (
    <div className="mt-4 space-y-4">
      <button onClick={() => router.push('/skills/drafts')} className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900">
        <ArrowLeft className="h-4 w-4" /> 返回草稿列表
      </button>

      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-slate-900">
            编辑草稿：{draft.skill_name}
          </h2>
          <p className="text-sm text-slate-500">
            <code className="rounded bg-slate-100 px-1 text-xs">{draft.skill_id}</code>
            {' · '}状态: {draft.status} · revision: {draft.revision}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => void handleSave()} disabled={busy === 'save'} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
            {busy === 'save' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} 保存
          </button>
          <button onClick={() => void handleValidate()} disabled={!!busy} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
            {busy === 'validate' ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />} 校验
          </button>
          <button onClick={() => void handlePreview()} disabled={!!busy} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
            {busy === 'preview' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Package className="h-4 w-4" />} 包预览
          </button>
          <button onClick={() => void handleMaterialize()} disabled={!!busy || draft.status !== 'validated'} className="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50">
            {busy === 'materialize' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />} 物化发布
          </button>
        </div>
      </header>

      {saveMsg && (
        <div className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm ${saveMsg === '保存成功' ? 'border border-green-200 bg-green-50 text-green-700' : 'border border-red-200 bg-red-50 text-red-700'}`}>
          {saveMsg === '保存成功' ? <CheckCircle2 className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />} {saveMsg}
        </div>
      )}
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" /> {error}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {/* 结构化编辑 */}
        <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-800">结构化配置</h3>
          <div>
            <label className="block text-sm font-medium text-slate-700">说明</label>
            <textarea value={config.description ?? ''} onChange={(e) => setConfig({ ...config, description: e.target.value })} rows={2} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">负责人</label>
            <input value={config.owner ?? ''} onChange={(e) => setConfig({ ...config, owner: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
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
              value={(bm.keywords ?? []).join(', ')}
              onChange={(e) => updateBm({ keywords: e.target.value.split(/[,，\s]+/).filter(Boolean) })}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
        </section>

        {/* 输入指标契约 */}
        <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-800">输入指标契约</h3>
            {inputValidation && (
              <span className={`inline-flex items-center gap-1 text-xs font-medium ${inputValidation.ok ? 'text-green-700' : 'text-amber-700'}`}>
                {inputValidation.ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertCircle className="h-3.5 w-3.5" />}
                {inputValidation.ok ? '指标可用' : '存在问题'}
              </span>
            )}
          </div>
          <div className="space-y-2">
            {(config.inputs ?? []).map((input, i) => (
              <div key={i} className="flex items-center gap-2 rounded-lg border border-slate-100 p-2 text-sm">
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

          {/* 输入选择器：级联 域→对象→指标 */}
          {selector && selector.tree && (
            <details className="rounded-lg border border-slate-100 p-2">
              <summary className="cursor-pointer text-xs font-medium text-slate-600">从语义层选择指标</summary>
              <div className="mt-2 max-h-60 space-y-1 overflow-auto">
                {selector.tree.map((domain) => (
                  <div key={domain.domain_code}>
                    <div className="text-xs font-semibold text-slate-700">{domain.domain_name}</div>
                    {domain.objects.map((obj) => (
                      <div key={obj.object_code} className="ml-3">
                        <div className="text-xs text-slate-500">{obj.object_name} ({obj.source_type})</div>
                        {obj.metrics.filter((m) => m.published).map((m) => (
                          <button
                            key={m.metric_code}
                            type="button"
                            onClick={() => {
                              const exists = (config.inputs ?? []).some((inp) => inp.metric_code === m.metric_code)
                              if (exists) return
                              const inputs = [...(config.inputs ?? []), { metric_code: m.metric_code, required: true }]
                              setConfig({ ...config, inputs })
                              void checkInputs(inputs.map((i) => i.metric_code))
                            }}
                            className="ml-3 block w-full text-left text-xs text-blue-600 hover:underline"
                          >
                            + {m.metric_code} — {m.metric_name}
                          </button>
                        ))}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </details>
          )}
        </section>
      </div>

      {/* 校验结果 */}
      {validation && (
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-800">
            <ShieldCheck className="h-4 w-4" /> 校验结果 {validation.blocking_ok ? '✓ 通过' : '✗ 有阻塞'}
          </h3>
          {validation.report.blocking.length > 0 && (
            <div className="space-y-1">
              {validation.report.blocking.map((issue, i) => (
                <div key={i} className="flex items-center gap-2 rounded bg-red-50 px-3 py-1.5 text-xs text-red-700">
                  <XCircle className="h-3.5 w-3.5 shrink-0" /> [{issue.code}] {issue.field}: {issue.message}
                </div>
              ))}
            </div>
          )}
          {validation.report.warnings.length > 0 && (
            <div className="mt-1 space-y-1">
              {validation.report.warnings.map((issue, i) => (
                <div key={i} className="flex items-center gap-2 rounded bg-amber-50 px-3 py-1.5 text-xs text-amber-700">
                  <AlertCircle className="h-3.5 w-3.5 shrink-0" /> [{issue.code}] {issue.field}: {issue.message}
                </div>
              ))}
            </div>
          )}
          {validation.blocking_ok && (
            <p className="text-xs text-green-700">校验通过，可进行物化发布。</p>
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
                <summary className="cursor-pointer font-mono text-xs text-green-400">{f.path}</summary>
                <pre className="mt-2 max-h-48 overflow-auto text-xs text-slate-100">{f.content}</pre>
              </details>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
