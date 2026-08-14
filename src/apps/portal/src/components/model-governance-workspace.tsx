'use client'

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

import {
  approveGovernanceDraft,
  createGovernanceDraft,
  deleteGovernanceDraft,
  getGovernanceAssets,
  getGovernanceReleases,
  importCurrentGovernanceAssets,
  previewGovernanceDraft,
  publishGovernanceDraft,
  requestGovernanceReview,
  rollbackGovernanceRelease,
  selectGovernanceDevIdentity,
  updateGovernanceDraft,
  validateGovernanceDraft,
  type GovernanceAssetContent,
  type GovernanceAssetPreview,
  type GovernanceAssetType,
  type GovernanceDevIdentity,
  type GovernanceDraft,
  type GovernanceRelease,
  type ModelGovernanceSnapshot,
} from '@/lib/model-governance-api'

type WorkspaceTab = GovernanceAssetType | 'overview' | 'releases'

const tabs: Array<{ value: WorkspaceTab; label: string }> = [
  { value: 'overview', label: '概览' },
  { value: 'prompt', label: '提示词' },
  { value: 'model_profile', label: '模型档案' },
  { value: 'route_rule', label: '路由规则' },
  { value: 'releases', label: '发布记录' },
]

const statusLabel = {
  editing: '编辑中',
  validated: '已校验',
  review_pending: '待审核',
  approved: '已审核',
} as const

interface FormState {
  assetId: string
  name: string
  scene: string
  systemPrompt: string
  userPrompt: string
  variables: string
  outputMode: 'text' | 'json'
  providerId: string
  modelName: string
  credentialRef: string
  temperature: string
  maxTokens: string
  profileId: string
  fallbacks: string
  enabled: boolean
}

function emptyForm(type: GovernanceAssetType): FormState {
  return {
    assetId: '',
    name: '',
    scene: type === 'route_rule' ? '' : 'policy_qa',
    systemPrompt: '只输出可追溯事实',
    userPrompt: '',
    variables: 'question|必填|用户问题',
    outputMode: 'text',
    providerId: 'openai-compatible',
    modelName: '',
    credentialRef: 'MODEL_API_KEY',
    temperature: '0.1',
    maxTokens: '4096',
    profileId: '',
    fallbacks: '',
    enabled: true,
  }
}

function formContent(type: GovernanceAssetType, form: FormState): GovernanceAssetContent {
  if (type === 'prompt') {
    return {
      asset_type: 'prompt',
      asset_id: form.assetId,
      name: form.name || form.assetId,
      scene: form.scene,
      model_type: 'llm',
      system_prompt: form.systemPrompt,
      user_prompt_template: form.userPrompt,
      variables: form.variables.split('\n').map((line) => line.trim()).filter(Boolean)
        .map((line) => {
          const [name, required = '必填', ...description] = line.split('|')
          return {
            name: name.trim(),
            required: required.trim() !== '可选',
            description: description.join('|').trim(),
          }
        }),
      output_mode: form.outputMode,
    }
  }
  if (type === 'model_profile') {
    return {
      asset_type: 'model_profile',
      asset_id: form.assetId,
      name: form.name || form.assetId,
      provider_id: form.providerId,
      model_name: form.modelName,
      credential_ref: form.credentialRef,
      temperature: Number(form.temperature),
      max_tokens: Number(form.maxTokens),
      enabled: form.enabled,
    }
  }
  return {
    asset_type: 'route_rule',
    asset_id: form.assetId,
    name: form.name || form.assetId,
    scene: form.scene,
    model_type: 'llm',
    profile_id: form.profileId,
    fallback_profile_ids: form.fallbacks.split(',').map((item) => item.trim()).filter(Boolean),
    enabled: form.enabled,
  }
}

function formFromDraft(draft: GovernanceDraft): FormState {
  const form = emptyForm(draft.asset_type)
  const content = draft.content
  form.assetId = content.asset_id
  form.name = content.name
  if (content.asset_type === 'prompt') {
    form.scene = content.scene
    form.systemPrompt = content.system_prompt
    form.userPrompt = content.user_prompt_template
    form.variables = content.variables
      .map((item) => `${item.name}|${item.required ? '必填' : '可选'}|${item.description}`)
      .join('\n')
    form.outputMode = content.output_mode
  } else if (content.asset_type === 'model_profile') {
    form.providerId = content.provider_id
    form.modelName = content.model_name
    form.credentialRef = content.credential_ref
    form.temperature = String(content.temperature)
    form.maxTokens = String(content.max_tokens)
    form.enabled = content.enabled
  } else {
    form.scene = content.scene
    form.profileId = content.profile_id
    form.fallbacks = content.fallback_profile_ids.join(',')
    form.enabled = content.enabled
  }
  return form
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : '请求失败'
}

function codeSource(snapshot: ModelGovernanceSnapshot, draft: GovernanceDraft): string {
  if (draft.asset_type === 'prompt') {
    return snapshot.prompts.find((item) => item.prompt_id === draft.asset_id)?.source_path
      ?? '未发现代码当前值'
  }
  if (draft.asset_type === 'model_profile') {
    const content = draft.content
    return content.asset_type === 'model_profile'
      && snapshot.models.some((item) => item.model_name === content.model_name)
      ? '已在当前模型配置中登记'
      : '未发现代码当前值'
  }
  const content = draft.content
  return content.asset_type === 'route_rule'
    && snapshot.routes.some((item) => item.scene === content.scene)
    ? '已在当前路由中登记'
    : '未发现代码当前值'
}

export function ModelGovernanceWorkspace({
  codeSnapshot,
  children,
}: {
  codeSnapshot: ModelGovernanceSnapshot
  children: ReactNode
}) {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('overview')
  const [identity, setIdentity] = useState<GovernanceDevIdentity>('editor')
  const [drafts, setDrafts] = useState<GovernanceDraft[]>([])
  const [publishedIds, setPublishedIds] = useState<Set<string>>(new Set())
  const [releases, setReleases] = useState<GovernanceRelease[]>([])
  const [formOpen, setFormOpen] = useState(false)
  const [editingDraft, setEditingDraft] = useState<GovernanceDraft | null>(null)
  const [form, setForm] = useState<FormState>(emptyForm('prompt'))
  const [preview, setPreview] = useState<GovernanceAssetPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [initialLoadError, setInitialLoadError] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const drawerCloseRef = useRef<HTMLButtonElement>(null)
  const drawerTriggerRef = useRef<HTMLButtonElement | null>(null)

  const refresh = useCallback(async () => {
    const [assets, releaseItems] = await Promise.all([
      getGovernanceAssets('dev'),
      getGovernanceReleases('dev'),
    ])
    setDrafts(assets.drafts)
    setPublishedIds(new Set(assets.published.map((item) => item.asset_id)))
    setReleases(releaseItems)
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (process.env.NODE_ENV !== 'production') {
        selectGovernanceDevIdentity('editor')
      }
      void refresh()
        .then(() => setInitialLoadError(''))
        .catch((reason) => setInitialLoadError(`治理资产与发布记录加载失败：${errorText(reason)}`))
    }, 0)
    return () => window.clearTimeout(timer)
  }, [refresh])

  function closeDrawer() {
    setFormOpen(false)
    setEditingDraft(null)
    setError('')
  }

  function openNew(type: GovernanceAssetType, trigger: HTMLButtonElement) {
    drawerTriggerRef.current = trigger
    setEditingDraft(null)
    setForm(emptyForm(type))
    setFormOpen(true)
    setPreview(null)
    setError('')
  }

  function openEdit(draft: GovernanceDraft, trigger: HTMLButtonElement) {
    drawerTriggerRef.current = trigger
    setEditingDraft(draft)
    setForm(formFromDraft(draft))
    setFormOpen(true)
    setPreview(null)
    setError('')
  }

  async function submitDraft() {
    if (activeTab === 'overview' || activeTab === 'releases') return
    setBusy(true)
    setError('')
    try {
      const content = formContent(activeTab, form)
      const saved = editingDraft
        ? await updateGovernanceDraft(
          editingDraft.draft_id,
          content,
          editingDraft.revision,
        )
        : await createGovernanceDraft(content)
      setDrafts((items) => [saved, ...items.filter((item) => item.draft_id !== saved.draft_id)])
      closeDrawer()
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  async function importCurrent() {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await importCurrentGovernanceAssets()
      setDrafts((items) => [
        ...result.drafts,
        ...items.filter((item) => !result.drafts.some((draft) => draft.draft_id === item.draft_id)),
      ])
      setNotice(
        result.created_count === 0
          ? `现有配置已全部纳管，本次跳过 ${result.skipped_count} 项`
          : `已导入 ${result.counts.prompt} 个提示词、${result.counts.model_profile} 个模型档案、${result.counts.route_rule} 条路由规则`,
      )
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  async function removeDraft(draft: GovernanceDraft) {
    if (!window.confirm(`确认删除草稿“${draft.content.name}”？`)) return
    setBusy(true)
    setError('')
    try {
      await deleteGovernanceDraft(draft.draft_id, draft.revision)
      setDrafts((items) => items.filter((item) => item.draft_id !== draft.draft_id))
      setNotice(`已删除草稿：${draft.content.name}`)
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  async function changeDraft(
    draft: GovernanceDraft,
    action: () => Promise<GovernanceDraft>,
  ) {
    setBusy(true)
    setError('')
    try {
      const updated = await action()
      setDrafts((items) => items.map((item) => item.draft_id === updated.draft_id ? updated : item))
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  async function showPreview(draft: GovernanceDraft) {
    setBusy(true)
    setError('')
    try {
      const variables = draft.content.asset_type === 'prompt'
        ? Object.fromEntries(draft.content.variables.map((item) => [item.name, `测试${item.name}`]))
        : {}
      setPreview(await previewGovernanceDraft(draft.draft_id, variables))
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  async function publish(draft: GovernanceDraft) {
    setBusy(true)
    setError('')
    try {
      await publishGovernanceDraft(draft.draft_id, draft.revision, 'dev')
      await refresh()
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  async function rollback(releaseId: string) {
    setBusy(true)
    setError('')
    try {
      await rollbackGovernanceRelease(releaseId)
      await refresh()
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  const visibleDrafts = activeTab === 'overview' || activeTab === 'releases'
    ? []
    : drafts.filter((draft) => draft.asset_type === activeTab)
  const typeLabel = tabs.find((tab) => tab.value === activeTab)?.label ?? ''
  const drawerTitle = `${editingDraft ? '编辑' : '新建'}${typeLabel}${form.name ? ` · ${form.name}` : ''}`

  return (
    <section className="rounded-xl border border-blue-200 bg-white shadow-sm" aria-labelledby="governance-workspace-title">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div>
          <h3 id="governance-workspace-title" className="text-sm font-semibold text-slate-800">治理库管理</h3>
          <p className="mt-1 text-xs text-slate-500">开发环境治理资产与发布流程</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {process.env.NODE_ENV !== 'production' && (
            <label className="text-xs text-slate-600">
              开发身份
              <select
                className="ml-2 rounded border border-slate-300 bg-white px-2 py-1"
                value={identity}
                onChange={(event) => {
                  const next = event.target.value as GovernanceDevIdentity
                  setIdentity(next)
                  selectGovernanceDevIdentity(next)
                }}
              >
                <option value="editor">编辑/发布人</option>
                <option value="reviewer">审核人</option>
              </select>
            </label>
          )}
        </div>
      </div>

      <div role="tablist" aria-label="治理工作区" className="flex overflow-x-auto border-b border-slate-100 px-3">
        {tabs.map((tab) => (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.value}
            aria-controls={`governance-panel-${tab.value}`}
            className={`whitespace-nowrap border-b-2 px-4 py-3 text-sm ${activeTab === tab.value ? 'border-blue-600 font-medium text-blue-700' : 'border-transparent text-slate-500'}`}
            onClick={() => {
              setActiveTab(tab.value)
              setFormOpen(false)
              setEditingDraft(null)
              drawerTriggerRef.current = null
              setPreview(null)
              setError('')
              setNotice('')
            }}
          >{tab.label}</button>
        ))}
      </div>

      <div
        id={`governance-panel-${activeTab}`}
        role="tabpanel"
        className="p-5"
        aria-busy={busy}
      >
        {initialLoadError && <p role="alert" className="mb-4 rounded bg-rose-50 p-3 text-sm text-rose-700">{initialLoadError}</p>}
        {error && !formOpen && <p role="alert" className="mb-4 rounded bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
        {notice && <p role="status" className="mb-4 rounded bg-emerald-50 p-3 text-sm text-emerald-700">{notice}</p>}

        {activeTab === 'overview' && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <div className="rounded-lg border border-slate-200 p-3"><p className="text-xs text-slate-500">草稿</p><p className="mt-1 text-lg font-semibold text-slate-800">{initialLoadError ? '—' : drafts.filter((draft) => draft.status === 'editing' || draft.status === 'validated').length}</p></div>
              <div className="rounded-lg border border-slate-200 p-3"><p className="text-xs text-slate-500">待审核</p><p className="mt-1 text-lg font-semibold text-slate-800">{initialLoadError ? '—' : drafts.filter((draft) => draft.status === 'review_pending').length}</p></div>
              <div className="rounded-lg border border-slate-200 p-3"><p className="text-xs text-slate-500">已发布</p><p className="mt-1 text-lg font-semibold text-slate-800">{initialLoadError ? '—' : publishedIds.size}</p></div>
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3"><p className="text-xs text-amber-700">运行时接入</p><p className="mt-1 text-sm font-semibold text-amber-800">尚未接入</p></div>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
              <p className="text-sm text-amber-800">发布内容尚未接入运行时，不会改变当前业务调用。</p>
              <button
                type="button"
                onClick={() => void importCurrent()}
                disabled={busy || identity !== 'editor'}
                className="rounded border border-blue-300 bg-white px-3 py-2 text-xs font-medium text-blue-700 disabled:opacity-50"
              >导入现有配置</button>
            </div>
            {children}
          </div>
        )}

        {activeTab !== 'overview' && activeTab !== 'releases' && (
          <>
            <button
              type="button"
              className="rounded bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
              onClick={(event) => openNew(activeTab, event.currentTarget)}
              disabled={busy}
            >新建{typeLabel}</button>

            <Dialog open={formOpen} onOpenChange={(open) => {
              if (!open) closeDrawer()
            }}>
              <DialogContent
                showCloseButton={false}
                aria-modal="true"
                initialFocus={drawerCloseRef}
                finalFocus={drawerTriggerRef}
                className="top-0! right-0! bottom-0! left-auto! flex! h-full! w-full flex-col gap-0! rounded-none! p-0! shadow-2xl translate-x-0! translate-y-0! max-md:max-w-none! md:max-w-[560px]"
              >
                  <DialogHeader className="flex-row items-start justify-between gap-3 border-b border-slate-200 px-5 py-4">
                    <div>
                      <DialogTitle className="font-semibold text-slate-800">{drawerTitle}</DialogTitle>
                      <DialogDescription className="mt-1 font-mono text-xs text-slate-500">
                        资产 ID：{form.assetId || '尚未分配'} · {editingDraft ? `revision ${editingDraft.revision}` : '尚未保存'}
                      </DialogDescription>
                    </div>
                    <DialogClose ref={drawerCloseRef} aria-label="关闭编辑抽屉" className="rounded p-2 text-xl leading-none text-slate-500 hover:bg-slate-100">×</DialogClose>
                  </DialogHeader>
                  <div className="flex-1 overflow-y-auto p-5">
                    {error && <p role="alert" className="mb-4 rounded bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
                    <div className="grid gap-3 md:grid-cols-2">
                      <label className="text-xs text-slate-600">{activeTab === 'prompt' ? '提示词标识' : '资产标识'}
                        <input required disabled={Boolean(editingDraft)} value={form.assetId} onChange={(e) => setForm({ ...form, assetId: e.target.value })} className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm" />
                      </label>
                      <label className="text-xs text-slate-600">显示名称
                        <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm" />
                      </label>
                      {activeTab === 'prompt' && <>
                        <label className="text-xs text-slate-600">场景<input value={form.scene} onChange={(e) => setForm({ ...form, scene: e.target.value })} className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm" /></label>
                        <label className="text-xs text-slate-600">输出模式<select value={form.outputMode} onChange={(e) => setForm({ ...form, outputMode: e.target.value as 'text' | 'json' })} className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm"><option value="text">文本</option><option value="json">JSON</option></select></label>
                        <label className="text-xs text-slate-600 md:col-span-2">提示词变量（每行：名称|必填/可选|说明）<textarea value={form.variables} onChange={(e) => setForm({ ...form, variables: e.target.value })} className="mt-1 min-h-20 w-full rounded border border-slate-300 bg-white px-3 py-2 font-mono text-sm" /></label>
                        <label className="text-xs text-slate-600 md:col-span-2">系统提示词<textarea value={form.systemPrompt} onChange={(e) => setForm({ ...form, systemPrompt: e.target.value })} className="mt-1 min-h-20 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm" /></label>
                        <label className="text-xs text-slate-600 md:col-span-2">用户提示词模板<textarea value={form.userPrompt} onChange={(e) => setForm({ ...form, userPrompt: e.target.value })} className="mt-1 min-h-20 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm" /></label>
                      </>}
                      {activeTab === 'model_profile' && <>
                        <label className="text-xs text-slate-600">Provider 标识<input value={form.providerId} onChange={(e) => setForm({ ...form, providerId: e.target.value })} className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm" /></label>
                        <label className="text-xs text-slate-600">模型名<input value={form.modelName} onChange={(e) => setForm({ ...form, modelName: e.target.value })} className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm" /></label>
                        <label className="text-xs text-slate-600">凭据引用<input value={form.credentialRef} onChange={(e) => setForm({ ...form, credentialRef: e.target.value })} className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm" /></label>
                        <label className="text-xs text-slate-600">温度<input type="number" step="0.1" value={form.temperature} onChange={(e) => setForm({ ...form, temperature: e.target.value })} className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm" /></label>
                        <label className="text-xs text-slate-600">最大 tokens<input type="number" value={form.maxTokens} onChange={(e) => setForm({ ...form, maxTokens: e.target.value })} className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm" /></label>
                        <label className="flex items-center gap-2 text-xs text-slate-600"><input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />启用模型档案</label>
                      </>}
                      {activeTab === 'route_rule' && <>
                        <label className="text-xs text-slate-600">场景<input value={form.scene} onChange={(e) => setForm({ ...form, scene: e.target.value })} className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm" /></label>
                        <label className="text-xs text-slate-600">主模型档案<input value={form.profileId} onChange={(e) => setForm({ ...form, profileId: e.target.value })} className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm" /></label>
                        <label className="text-xs text-slate-600 md:col-span-2">备用档案（逗号分隔）<input value={form.fallbacks} onChange={(e) => setForm({ ...form, fallbacks: e.target.value })} className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm" /></label>
                        <label className="flex items-center gap-2 text-xs text-slate-600"><input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />启用路由规则</label>
                      </>}
                    </div>
                  </div>
                  <DialogFooter className="m-0! flex-row! justify-end rounded-none! bg-white px-5 py-4">
                    <DialogClose className="rounded border border-slate-300 px-3 py-2 text-sm text-slate-600">取消</DialogClose>
                    <button type="button" disabled={busy || !form.assetId} onClick={() => void submitDraft()} className="rounded bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">保存草稿</button>
                  </DialogFooter>
              </DialogContent>
            </Dialog>

            <div className="mt-4 space-y-3">
              {visibleDrafts.length === 0 && !initialLoadError && <p className="text-sm text-slate-500">暂无{typeLabel}草稿</p>}
              {visibleDrafts.map((draft) => (
                <article key={draft.draft_id} className="rounded-lg border border-slate-200 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div><h4 className="font-medium text-slate-800">{draft.content.name}</h4><p className="font-mono text-xs text-slate-500">{draft.asset_id}</p></div>
                    <div className="flex gap-2 text-xs"><span className="rounded bg-slate-100 px-2 py-1">{statusLabel[draft.status]}</span><span className="rounded bg-amber-50 px-2 py-1 text-amber-700">{publishedIds.has(draft.asset_id) ? '已发布，待接入' : '尚未发布'}</span></div>
                  </div>
                  <div className="mt-3 grid gap-2 text-xs text-slate-600 md:grid-cols-2"><p>代码当前值：{codeSource(codeSnapshot, draft)}</p><p>治理库 revision：{draft.revision}</p></div>
                  {draft.validation_issues.map((issue) => <p key={`${issue.code}:${issue.path}`} className="mt-2 text-xs text-rose-700">{issue.message}</p>)}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button type="button" disabled={busy} onClick={(event) => openEdit(draft, event.currentTarget)} className="rounded border border-slate-300 px-2.5 py-1.5 text-xs">编辑</button>
                    {draft.status !== 'approved' && !publishedIds.has(draft.asset_id) && <button type="button" disabled={busy} onClick={() => void removeDraft(draft)} className="rounded border border-rose-300 px-2.5 py-1.5 text-xs text-rose-700">删除草稿</button>}
                    {draft.status === 'editing' && <button type="button" disabled={busy} onClick={() => void changeDraft(draft, () => validateGovernanceDraft(draft.draft_id, draft.revision))} className="rounded bg-blue-50 px-2.5 py-1.5 text-xs text-blue-700">校验</button>}
                    {draft.status === 'validated' && <><button type="button" disabled={busy} onClick={() => void showPreview(draft)} className="rounded border border-blue-200 px-2.5 py-1.5 text-xs text-blue-700">预览</button><button type="button" disabled={busy || identity !== 'editor'} onClick={() => void changeDraft(draft, () => requestGovernanceReview(draft.draft_id, draft.revision))} className="rounded bg-blue-600 px-2.5 py-1.5 text-xs text-white">申请审核</button></>}
                    {draft.status === 'review_pending' && identity === 'reviewer' && <button type="button" disabled={busy} onClick={() => void changeDraft(draft, () => approveGovernanceDraft(draft.draft_id, draft.revision, '开发环境审核通过'))} className="rounded bg-emerald-600 px-2.5 py-1.5 text-xs text-white">审核通过</button>}
                    {draft.status === 'approved' && <button type="button" disabled={busy || identity !== 'editor'} onClick={() => void publish(draft)} className="rounded bg-indigo-600 px-2.5 py-1.5 text-xs text-white">发布到开发环境</button>}
                  </div>
                </article>
              ))}
            </div>
            {preview && <pre className="mt-4 overflow-x-auto rounded bg-slate-900 p-4 text-xs text-slate-100">{JSON.stringify(preview, null, 2)}</pre>}
          </>
        )}

        {activeTab === 'releases' && (
          <div className="space-y-3">
            {releases.length === 0 && !initialLoadError && <p className="text-sm text-slate-500">暂无发布记录</p>}
            {releases.map((release) => (
              <article key={release.release_id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 p-4 text-sm">
                <div><p className="font-medium text-slate-800">{release.asset_id}</p><p className="mt-1 font-mono text-xs text-slate-500">{release.version_id}</p></div>
                <div className="flex items-center gap-2"><span className="rounded bg-slate-100 px-2 py-1 text-xs">{release.status === 'active' ? '活动发布' : '历史版本'}</span>{release.status === 'retired' && identity === 'editor' && <button type="button" disabled={busy} onClick={() => void rollback(release.release_id)} className="rounded border border-indigo-300 px-2.5 py-1.5 text-xs text-indigo-700">回滚至此版本</button>}</div>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
