'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

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
  createGovernanceVersion,
  getGovernanceAssets,
  getGovernanceReleases,
  getGovernanceVersions,
  publishGovernanceDraft,
  requestGovernanceReview,
  rollbackGovernanceRelease,
  selectGovernanceDevIdentity,
  testGovernanceConnection,
  updateGovernanceDraft,
  validateGovernanceDraft,
  type GovernanceAssetContent,
  type GovernanceAssetType,
  type GovernanceAssetsResult,
  type GovernanceConnectionTest,
  type GovernanceDevIdentity,
  type GovernanceDraft,
  type GovernanceEnvironment,
  type GovernanceRelease,
  type GovernanceVersionsResult,
  type ModelCredentialInput,
  type PublishedGovernanceAsset,
} from '@/lib/model-governance-api'

type WorkspaceTab = GovernanceAssetType | 'overview' | 'releases'

const tabs: Array<{ value: WorkspaceTab; label: string }> = [
  { value: 'overview', label: '概览' },
  { value: 'prompt', label: '提示词' },
  { value: 'model_profile', label: '模型' },
  { value: 'route_rule', label: '路由规则' },
  { value: 'releases', label: '发布记录' },
]

const typeLabel: Record<GovernanceAssetType, string> = {
  prompt: '提示词',
  model_profile: '模型',
  route_rule: '路由规则',
}

const statusLabel = {
  editing: '编辑中',
  validated: '已校验',
  review_pending: '待审核',
  approved: '已审核',
} as const

interface AssetRow {
  assetId: string
  assetType: GovernanceAssetType
  name: string
  baseline?: GovernanceAssetContent
  draft?: GovernanceDraft
  published?: PublishedGovernanceAsset
}

interface FormState {
  assetId: string
  name: string
  scene: string
  systemPrompt: string
  userPrompt: string
  variables: string
  outputMode: 'text' | 'json'
  baseUrl: string
  modelName: string
  credentialRef: string
  apiKey: string
  timeoutSeconds: string
  temperature: string
  maxTokens: string
  profileId: string
  fallbackProfileIds: string[]
  enabled: boolean
}

const emptyAssets: GovernanceAssetsResult = { baselines: [], drafts: [], published: [] }

function emptyForm(type: GovernanceAssetType): FormState {
  return {
    assetId: '',
    name: '',
    scene: type === 'route_rule' ? '' : 'policy_qa',
    systemPrompt: '只输出可追溯事实',
    userPrompt: '',
    variables: 'question|必填|用户问题',
    outputMode: 'text',
    baseUrl: 'https://api.openai.com/v1',
    modelName: '',
    credentialRef: 'credential.model.default',
    apiKey: '',
    timeoutSeconds: '30',
    temperature: '0.1',
    maxTokens: '4096',
    profileId: '',
    fallbackProfileIds: [],
    enabled: true,
  }
}

function formFromContent(content: GovernanceAssetContent): FormState {
  const form = emptyForm(content.asset_type)
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
    form.baseUrl = content.base_url
    form.modelName = content.model_name
    form.credentialRef = content.credential_ref
    form.timeoutSeconds = String(content.timeout_seconds)
    form.temperature = String(content.temperature)
    form.maxTokens = String(content.max_tokens)
    form.enabled = content.enabled
  } else {
    form.scene = content.scene
    form.profileId = content.profile_id
    form.fallbackProfileIds = content.fallback_profile_ids
    form.enabled = content.enabled
  }
  return form
}

function formContent(type: GovernanceAssetType, form: FormState): GovernanceAssetContent {
  if (type === 'prompt') {
    return {
      asset_type: 'prompt', asset_id: form.assetId, name: form.name || form.assetId,
      scene: form.scene, model_type: 'llm', system_prompt: form.systemPrompt,
      user_prompt_template: form.userPrompt,
      variables: form.variables.split('\n').map((line) => line.trim()).filter(Boolean).map((line) => {
        const [name, required = '必填', ...description] = line.split('|')
        return { name: name.trim(), required: required.trim() !== '可选', description: description.join('|').trim() }
      }),
      output_mode: form.outputMode,
    }
  }
  if (type === 'model_profile') {
    return {
      asset_type: 'model_profile', asset_id: form.assetId, name: form.name || form.assetId,
      provider_id: 'openai_compatible', base_url: form.baseUrl, model_name: form.modelName,
      credential_ref: form.credentialRef, timeout_seconds: Number(form.timeoutSeconds),
      temperature: Number(form.temperature), max_tokens: Number(form.maxTokens), enabled: form.enabled,
    }
  }
  return {
    asset_type: 'route_rule', asset_id: form.assetId, name: form.name || form.assetId,
    scene: form.scene, model_type: 'llm', profile_id: form.profileId,
    fallback_profile_ids: form.fallbackProfileIds, enabled: form.enabled,
  }
}

function rowsFromAssets(assets: GovernanceAssetsResult): AssetRow[] {
  const rows = new Map<string, AssetRow>()
  const merge = (content: GovernanceAssetContent, extra: Partial<AssetRow>) => {
    rows.set(content.asset_id, {
      ...rows.get(content.asset_id),
      assetId: content.asset_id,
      assetType: content.asset_type,
      name: content.name,
      ...extra,
    })
  }
  assets.baselines.forEach(({ runtime_status: _, ...baseline }) => {
    const content = baseline as GovernanceAssetContent
    merge(content, { baseline: content })
  })
  assets.published.forEach((item) => merge(item.content, { published: item }))
  assets.drafts.forEach((draft) => {
    const existing = rows.get(draft.asset_id)?.draft
    if (!existing || Date.parse(draft.updated_at) > Date.parse(existing.updated_at)) {
      merge(draft.content, { draft })
    }
  })
  return [...rows.values()].sort((left, right) => left.assetId.localeCompare(right.assetId))
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : '请求失败'
}

function ReadOnlyContent({ content }: { content: GovernanceAssetContent }) {
  if (content.asset_type === 'prompt') {
    return <div className="space-y-3 text-sm text-slate-700">
      <div><p className="text-xs font-medium text-slate-500">系统提示词</p><p className="mt-1 whitespace-pre-wrap break-words rounded bg-slate-50 p-3">{content.system_prompt || '（空）'}</p></div>
      <div><p className="text-xs font-medium text-slate-500">用户提示词模板</p><p className="mt-1 whitespace-pre-wrap break-words rounded bg-slate-50 p-3">{content.user_prompt_template}</p></div>
    </div>
  }
  if (content.asset_type === 'model_profile') {
    return <dl className="grid gap-2 text-sm sm:grid-cols-2">
      <div><dt className="text-xs text-slate-500">Provider</dt><dd>OpenAI-compatible</dd></div>
      <div><dt className="text-xs text-slate-500">模型名</dt><dd className="break-all">{content.model_name}</dd></div>
      <div className="sm:col-span-2"><dt className="text-xs text-slate-500">API 访问地址</dt><dd className="break-all">{content.base_url}</dd></div>
      <div><dt className="text-xs text-slate-500">Credential ID</dt><dd className="break-all">{content.credential_ref}</dd></div>
      <div><dt className="text-xs text-slate-500">超时</dt><dd>{content.timeout_seconds} 秒</dd></div>
    </dl>
  }
  return <dl className="grid gap-2 text-sm sm:grid-cols-2">
    <div><dt className="text-xs text-slate-500">场景</dt><dd>{content.scene}</dd></div>
    <div><dt className="text-xs text-slate-500">主模型</dt><dd className="break-all">{content.profile_id}</dd></div>
    <div className="sm:col-span-2"><dt className="text-xs text-slate-500">备用模型</dt><dd className="break-all">{content.fallback_profile_ids.join('，') || '无'}</dd></div>
  </dl>
}

export function ModelGovernanceWorkspace() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('overview')
  const [environment, setEnvironment] = useState<GovernanceEnvironment>('dev')
  const [identity, setIdentity] = useState<GovernanceDevIdentity>('editor')
  const [assets, setAssets] = useState<GovernanceAssetsResult>(emptyAssets)
  const [releases, setReleases] = useState<GovernanceRelease[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [drawerType, setDrawerType] = useState<GovernanceAssetType>('prompt')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [form, setForm] = useState<FormState>(emptyForm('prompt'))
  const [versions, setVersions] = useState<GovernanceVersionsResult>({ versions: [], releases: [] })
  const [connectionTests, setConnectionTests] = useState<Record<string, GovernanceConnectionTest>>({})
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const closeRef = useRef<HTMLButtonElement>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [nextAssets, nextReleases] = await Promise.all([
        getGovernanceAssets(environment), getGovernanceReleases(environment),
      ])
      setAssets(nextAssets)
      setReleases(nextReleases)
      setError('')
    } catch (reason) {
      setError(`治理资产与发布记录加载失败：${errorText(reason)}`)
    } finally {
      setLoading(false)
    }
  }, [environment])

  useEffect(() => {
    if (process.env.NODE_ENV !== 'production') selectGovernanceDevIdentity('editor')
    void refresh()
  }, [refresh])

  const rows = useMemo(() => rowsFromAssets(assets), [assets])
  const selected = selectedId ? rows.find((row) => row.assetId === selectedId) : undefined
  const publishedModels = assets.published
    .filter((item) => item.content.asset_type === 'model_profile' && item.content.enabled)
    .map((item) => item.content.asset_id)
  const visibleRows = activeTab === 'overview' || activeTab === 'releases'
    ? [] : rows.filter((row) => row.assetType === activeTab)

  function upsertDraft(draft: GovernanceDraft) {
    setAssets((current) => ({
      ...current,
      drafts: [draft, ...current.drafts.filter((item) => item.draft_id !== draft.draft_id)],
    }))
    setSelectedId(draft.asset_id)
    setForm(formFromContent(draft.content))
  }

  function openRow(row: AssetRow, trigger: HTMLButtonElement) {
    triggerRef.current = trigger
    setSelectedId(row.assetId)
    setDrawerType(row.assetType)
    setForm(formFromContent(row.draft?.content ?? row.published?.content ?? row.baseline!))
    setDrawerOpen(true)
    setError('')
    setVersions({ versions: [], releases: [] })
    void getGovernanceVersions(row.assetId, environment).then(setVersions).catch((reason) => setError(errorText(reason)))
  }

  function openNew(type: GovernanceAssetType, trigger: HTMLButtonElement) {
    triggerRef.current = trigger
    setSelectedId(null)
    setDrawerType(type)
    setForm(emptyForm(type))
    setVersions({ versions: [], releases: [] })
    setDrawerOpen(true)
    setError('')
  }

  async function saveDraft() {
    const content = formContent(drawerType, form)
    const credential: ModelCredentialInput | undefined = drawerType === 'model_profile' && form.apiKey
      ? { credential_id: form.credentialRef, api_key: form.apiKey }
      : undefined
    setBusy(true)
    setError('')
    try {
      const saved = selected?.draft
        ? await updateGovernanceDraft(selected.draft.draft_id, content, selected.draft.revision, credential)
        : await createGovernanceDraft(content, credential)
      upsertDraft(saved)
      setForm((current) => ({ ...current, apiKey: '' }))
      setNotice('工作版本已保存')
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  async function startVersion() {
    if (!selected) return
    setBusy(true)
    setError('')
    try {
      const draft = selected.published
        ? await createGovernanceVersion(selected.assetId, environment)
        : await createGovernanceDraft(selected.baseline!)
      upsertDraft(draft)
      setNotice(selected.published ? '已从当前生效版本创建工作版本' : '已创建首个工作版本')
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  async function changeDraft(action: (draft: GovernanceDraft) => Promise<GovernanceDraft>) {
    if (!selected?.draft) return
    setBusy(true)
    setError('')
    try {
      upsertDraft(await action(selected.draft))
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  async function testConnection() {
    if (!selected?.draft) return
    setBusy(true)
    setError('')
    try {
      const result = await testGovernanceConnection(selected.draft.draft_id)
      setConnectionTests((current) => ({ ...current, [selected.draft!.draft_id]: result }))
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  async function publish() {
    if (!selected?.draft) return
    setBusy(true)
    setError('')
    try {
      await publishGovernanceDraft(selected.draft.draft_id, selected.draft.revision, environment)
      setDrawerOpen(false)
      await refresh()
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  async function rollback(releaseId: string) {
    setBusy(true)
    try {
      await rollbackGovernanceRelease(releaseId)
      await refresh()
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  const currentContent = selected?.published?.content ?? selected?.baseline
  const modelTest = selected?.draft ? connectionTests[selected.draft.draft_id] : undefined
  const noPublishedModels = publishedModels.length === 0
  const routeUnavailable = drawerType === 'route_rule' && noPublishedModels

  return <section className="min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm" aria-labelledby="governance-workspace-title">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-4 sm:px-5">
      <div>
        <h3 id="governance-workspace-title" className="text-sm font-semibold text-slate-800">资产中心</h3>
        <p className="mt-1 text-xs text-slate-500">治理发布已接入运行时 · 当前 {environment} 环境</p>
      </div>
      <div className="flex flex-wrap gap-2 text-xs">
        <label className="text-slate-600">环境
          <select aria-label="环境" className="ml-2 rounded border border-slate-300 bg-white px-2 py-1.5" value={environment} onChange={(event) => setEnvironment(event.target.value as GovernanceEnvironment)}>
            <option value="dev">dev</option><option value="test">test</option>
          </select>
        </label>
        {process.env.NODE_ENV !== 'production' && <label className="text-slate-600">开发身份
          <select aria-label="开发身份" className="ml-2 rounded border border-slate-300 bg-white px-2 py-1.5" value={identity} onChange={(event) => {
            const next = event.target.value as GovernanceDevIdentity
            setIdentity(next); selectGovernanceDevIdentity(next)
          }}><option value="editor">编辑/发布人</option><option value="reviewer">审核人</option></select>
        </label>}
      </div>
    </header>

    <nav role="tablist" aria-label="治理工作区" className="flex overflow-x-auto border-b border-slate-100 px-2">
      {tabs.map((tab) => <button key={tab.value} type="button" role="tab" aria-selected={activeTab === tab.value} aria-controls={`governance-panel-${tab.value}`} className={`shrink-0 border-b-2 px-3 py-3 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-blue-600 ${activeTab === tab.value ? 'border-blue-600 font-medium text-blue-700' : 'border-transparent text-slate-500 hover:text-slate-800'}`} onClick={() => { setActiveTab(tab.value); setNotice('') }}>{tab.label}</button>)}
    </nav>

    <div id={`governance-panel-${activeTab}`} role="tabpanel" aria-busy={busy || loading} className="min-w-0 p-4 sm:p-5">
      {error && !drawerOpen && <p role="alert" className="mb-4 rounded bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
      {notice && <p role="status" className="mb-4 rounded bg-emerald-50 p-3 text-sm text-emerald-700">{notice}</p>}
      {loading && <p role="status" aria-live="polite" className="text-sm text-slate-500">正在加载治理资产</p>}

      {!loading && activeTab === 'overview' && <div className="space-y-5">
        <section aria-label="治理指标" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[
            ['活动资产', assets.published.length], ['工作草稿', assets.drafts.length],
            ['待审核', assets.drafts.filter((draft) => draft.status === 'review_pending').length],
            ['连接异常', Object.values(connectionTests).filter((item) => item.status === 'failure').length],
          ].map(([label, value]) => <div key={String(label)} className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-xl font-semibold tabular-nums text-slate-800">{value}</p></div>)}
        </section>
        <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">当前环境：{environment} · 治理发布已接入运行时</p>
      </div>}

      {!loading && activeTab !== 'overview' && activeTab !== 'releases' && <div className="min-w-0">
        <div className="mb-4 flex items-center justify-between gap-3">
          <p className="text-sm text-slate-500">基线、工作版本与活动发布按资产合并展示。</p>
          <button type="button" disabled={busy || (activeTab === 'route_rule' && noPublishedModels)} onClick={(event) => openNew(activeTab, event.currentTarget)} className="shrink-0 rounded bg-blue-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 active:translate-y-px disabled:opacity-50">新建{typeLabel[activeTab]}</button>
        </div>
        {activeTab === 'route_rule' && noPublishedModels && <p className="mb-4 text-sm text-amber-700">请先发布并启用模型，再创建路由规则。</p>}
        {visibleRows.length === 0 ? <p className="rounded bg-slate-50 p-6 text-center text-sm text-slate-500">暂无{typeLabel[activeTab]}资产</p> : <div className="overflow-hidden rounded-lg border border-slate-200">
          <table className="w-full table-fixed text-left text-sm">
            <caption className="sr-only">{typeLabel[activeTab]}资产</caption>
            <thead className="bg-slate-50 text-xs text-slate-500"><tr><th className="w-1/2 px-3 py-2 font-medium sm:w-2/5">名称 / ID</th><th className="hidden px-3 py-2 font-medium sm:table-cell">当前版本</th><th className="hidden px-3 py-2 font-medium md:table-cell">工作状态</th><th className="w-24 px-3 py-2 text-right font-medium">操作</th></tr></thead>
            <tbody className="divide-y divide-slate-100">{visibleRows.map((row) => <tr key={row.assetId}>
              <td className="px-3 py-3"><p className="truncate font-medium text-slate-800">{row.name}</p><p className="break-all font-mono text-xs text-slate-500">{row.assetId}</p></td>
              <td className="hidden px-3 py-3 text-xs text-slate-600 sm:table-cell">{row.published ? `${environment} 活动版本` : '代码基线（回退）'}</td>
              <td className="hidden px-3 py-3 text-xs text-slate-600 md:table-cell">{row.draft ? statusLabel[row.draft.status] : '无工作版本'}</td>
              <td className="px-3 py-3 text-right"><button type="button" aria-label={`查看 ${row.assetId}`} onClick={(event) => openRow(row, event.currentTarget)} className="rounded border border-slate-300 px-2.5 py-1.5 text-xs text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-blue-600">查看</button></td>
            </tr>)}</tbody>
          </table>
        </div>}
      </div>}

      {!loading && activeTab === 'releases' && <div className="space-y-3">
        {releases.length === 0 ? <p className="text-sm text-slate-500">暂无发布记录</p> : releases.map((release) => <article key={release.release_id} className="flex min-w-0 flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 p-4 text-sm">
          <div className="min-w-0"><p className="break-all font-medium">{release.asset_id}</p><p className="break-all font-mono text-xs text-slate-500">{release.version_id}</p></div>
          <div className="flex items-center gap-2"><span className="text-xs">{release.status === 'active' ? '活动版本' : '历史版本'}</span>{release.status === 'retired' && <button type="button" disabled={busy || identity !== 'editor'} onClick={() => void rollback(release.release_id)} className="rounded border border-blue-300 px-2 py-1 text-xs text-blue-700 disabled:opacity-50">回滚</button>}</div>
        </article>)}
      </div>}
    </div>

    <Dialog open={drawerOpen} onOpenChange={(open) => { setDrawerOpen(open); if (!open) setError('') }}>
      <DialogContent showCloseButton={false} aria-modal="true" initialFocus={closeRef} finalFocus={triggerRef} className="top-0! right-0! bottom-0! left-auto! flex! h-full! w-full flex-col gap-0! overflow-hidden rounded-none! p-0! shadow-2xl translate-x-0! translate-y-0! max-md:max-w-none! md:max-w-[640px]">
        <DialogHeader className="flex-row items-start justify-between gap-3 border-b border-slate-200 px-4 py-4 sm:px-5">
          <div className="min-w-0"><DialogTitle className="break-words font-semibold text-slate-800">{selected ? `${typeLabel[drawerType]} · ${selected.name}` : `新建${typeLabel[drawerType]}`}</DialogTitle><DialogDescription className="mt-1 break-all font-mono text-xs">{selected?.assetId ?? '尚未保存'}</DialogDescription></div>
          <DialogClose ref={closeRef} aria-label="关闭详情抽屉" className="rounded p-2 text-xl leading-none text-slate-500 hover:bg-slate-100">×</DialogClose>
        </DialogHeader>
        <div className="flex-1 space-y-6 overflow-y-auto overflow-x-hidden p-4 sm:p-5">
          {error && <p role="alert" className="rounded bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
          {selected && <section aria-labelledby="current-version-title"><div className="mb-3 flex flex-wrap items-center justify-between gap-2"><h4 id="current-version-title" className="font-semibold text-slate-800">当前生效</h4><span className="text-xs text-slate-500">{selected.published ? '治理发布 · 运行时生效' : '代码基线（回退）'}</span></div>{currentContent ? <ReadOnlyContent content={currentContent} /> : <p className="text-sm text-slate-500">尚无活动发布或代码基线。</p>}</section>}

          <section aria-labelledby="working-version-title" className="border-t border-slate-200 pt-5">
            <div className="mb-3 flex items-center justify-between gap-3"><h4 id="working-version-title" className="font-semibold text-slate-800">工作版本</h4>{selected?.draft && <span className="text-xs text-slate-500">{statusLabel[selected.draft.status]} · revision {selected.draft.revision}</span>}</div>
            {selected && !selected.draft ? <button type="button" disabled={busy} onClick={() => void startVersion()} className="rounded bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">{selected.published ? '新建版本' : '创建首个草稿'}</button> : <AssetForm type={drawerType} form={form} setForm={setForm} lockedId={Boolean(selected)} publishedModels={publishedModels} />}
            {(!selected || selected.draft) && <div className="mt-4 flex flex-wrap gap-2">
              <button type="button" disabled={busy || !form.assetId || routeUnavailable} onClick={() => void saveDraft()} className="rounded bg-blue-600 px-3 py-2 text-xs font-medium text-white disabled:opacity-50">保存工作版本</button>
              {selected?.draft?.status === 'editing' && <button type="button" disabled={busy} onClick={() => void changeDraft((draft) => validateGovernanceDraft(draft.draft_id, draft.revision))} className="rounded border border-blue-300 px-3 py-2 text-xs text-blue-700">校验</button>}
              {selected?.draft?.status === 'validated' && <button type="button" disabled={busy || identity !== 'editor'} onClick={() => void changeDraft((draft) => requestGovernanceReview(draft.draft_id, draft.revision))} className="rounded border border-blue-300 px-3 py-2 text-xs text-blue-700">申请审核</button>}
              {selected?.draft?.status === 'review_pending' && identity === 'reviewer' && <button type="button" disabled={busy} onClick={() => void changeDraft((draft) => approveGovernanceDraft(draft.draft_id, draft.revision, '开发环境审核通过'))} className="rounded bg-emerald-600 px-3 py-2 text-xs text-white">审核通过</button>}
              {selected?.draft?.content.asset_type === 'model_profile' && <button type="button" disabled={busy} onClick={() => void testConnection()} className="rounded border border-slate-300 px-3 py-2 text-xs">测试连接</button>}
              {selected?.draft?.status === 'approved' && <button type="button" disabled={busy || identity !== 'editor' || (selected.draft.content.asset_type === 'model_profile' && modelTest?.status !== 'success')} onClick={() => void publish()} className="rounded bg-indigo-600 px-3 py-2 text-xs text-white disabled:opacity-50">发布到{environment}环境</button>}
            </div>}
            {modelTest && <p role="status" className={`mt-3 rounded p-3 text-xs ${modelTest.status === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>{modelTest.safe_message} · {new Date(modelTest.tested_at).toLocaleString('zh-CN')} · {modelTest.latency_ms}ms</p>}
          </section>

          {selected && <section aria-labelledby="version-history-title" className="border-t border-slate-200 pt-5"><h4 id="version-history-title" className="mb-3 font-semibold text-slate-800">版本历史</h4>{versions.versions.length === 0 ? <p className="text-sm text-slate-500">暂无已发布版本</p> : <div className="space-y-2">{versions.versions.map((version) => {
            const release = versions.releases.find((item) => item.version_id === version.version_id)
            return <div key={version.version_id} className="flex flex-wrap items-center justify-between gap-2 rounded bg-slate-50 p-3 text-xs"><div><p className="font-medium">版本 {version.version_number} · {release?.status === 'active' ? '活动' : '历史'}</p><p className="mt-1 text-slate-500">{release?.created_by ?? version.created_by} · {new Date(release?.created_at ?? version.created_at).toLocaleString('zh-CN')}</p></div>{release?.status === 'retired' && <button type="button" disabled={busy || identity !== 'editor'} onClick={() => void rollback(release.release_id)} className="rounded border border-blue-300 px-2 py-1 text-blue-700">回滚至此版本</button>}</div>
          })}</div>}</section>}
        </div>
        <DialogFooter className="m-0! flex-row! justify-end rounded-none! border-t border-slate-200 bg-white px-4 py-3 sm:px-5"><DialogClose className="rounded border border-slate-300 px-3 py-2 text-sm text-slate-600">关闭</DialogClose></DialogFooter>
      </DialogContent>
    </Dialog>
  </section>
}

function AssetForm({ type, form, setForm, lockedId, publishedModels }: {
  type: GovernanceAssetType
  form: FormState
  setForm: (form: FormState) => void
  lockedId: boolean
  publishedModels: string[]
}) {
  const inputClass = 'mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-blue-600 disabled:bg-slate-100'
  return <div className="grid min-w-0 gap-3 sm:grid-cols-2">
    <label className="min-w-0 text-xs text-slate-600">资产 ID<input required disabled={lockedId} value={form.assetId} onChange={(event) => setForm({ ...form, assetId: event.target.value })} className={inputClass} /></label>
    <label className="min-w-0 text-xs text-slate-600">显示名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} className={inputClass} /></label>
    {type === 'prompt' && <>
      <label className="text-xs text-slate-600">场景<input value={form.scene} onChange={(event) => setForm({ ...form, scene: event.target.value })} className={inputClass} /></label>
      <label className="text-xs text-slate-600">输出模式<select value={form.outputMode} onChange={(event) => setForm({ ...form, outputMode: event.target.value as 'text' | 'json' })} className={inputClass}><option value="text">文本</option><option value="json">JSON</option></select></label>
      <label className="text-xs text-slate-600 sm:col-span-2">提示词变量（每行：名称|必填/可选|说明）<textarea value={form.variables} onChange={(event) => setForm({ ...form, variables: event.target.value })} className={`${inputClass} min-h-20 font-mono`} /></label>
      <label className="text-xs text-slate-600 sm:col-span-2">系统提示词<textarea value={form.systemPrompt} onChange={(event) => setForm({ ...form, systemPrompt: event.target.value })} className={`${inputClass} min-h-24`} /></label>
      <label className="text-xs text-slate-600 sm:col-span-2">用户提示词模板<textarea value={form.userPrompt} onChange={(event) => setForm({ ...form, userPrompt: event.target.value })} className={`${inputClass} min-h-24`} /></label>
    </>}
    {type === 'model_profile' && <>
      <label className="text-xs text-slate-600">Provider<input readOnly value="OpenAI-compatible" className={inputClass} /></label>
      <label className="text-xs text-slate-600">模型名<input value={form.modelName} onChange={(event) => setForm({ ...form, modelName: event.target.value })} className={inputClass} /></label>
      <label className="text-xs text-slate-600 sm:col-span-2">API 访问地址<input type="url" value={form.baseUrl} onChange={(event) => setForm({ ...form, baseUrl: event.target.value })} className={inputClass} /></label>
      <label className="text-xs text-slate-600">Credential ID<input value={form.credentialRef} onChange={(event) => setForm({ ...form, credentialRef: event.target.value })} className={inputClass} /></label>
      <label className="text-xs text-slate-600">API Key<input aria-label="API Key" type="password" autoComplete="new-password" value={form.apiKey} onChange={(event) => setForm({ ...form, apiKey: event.target.value })} className={inputClass} /><span className="mt-1 block text-[11px] text-slate-500">留空表示不更换</span></label>
      <label className="text-xs text-slate-600">超时（秒）<input type="number" min="1" max="300" value={form.timeoutSeconds} onChange={(event) => setForm({ ...form, timeoutSeconds: event.target.value })} className={inputClass} /></label>
      <label className="text-xs text-slate-600">温度<input type="number" min="0" max="2" step="0.1" value={form.temperature} onChange={(event) => setForm({ ...form, temperature: event.target.value })} className={inputClass} /></label>
      <label className="text-xs text-slate-600">最大 tokens<input type="number" min="1" max="65536" value={form.maxTokens} onChange={(event) => setForm({ ...form, maxTokens: event.target.value })} className={inputClass} /></label>
      <label className="flex items-center gap-2 self-end py-2 text-xs text-slate-600"><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} />启用模型</label>
    </>}
    {type === 'route_rule' && <>
      <label className="text-xs text-slate-600">场景<input value={form.scene} onChange={(event) => setForm({ ...form, scene: event.target.value })} className={inputClass} /></label>
      <label className="text-xs text-slate-600">主模型<select value={form.profileId} onChange={(event) => setForm({ ...form, profileId: event.target.value })} className={inputClass} disabled={publishedModels.length === 0}><option value="">请选择</option>{publishedModels.map((id) => <option key={id} value={id}>{id}</option>)}</select></label>
      <label className="text-xs text-slate-600 sm:col-span-2">备用模型<select multiple value={form.fallbackProfileIds} onChange={(event) => setForm({ ...form, fallbackProfileIds: [...event.target.selectedOptions].map((option) => option.value) })} className={`${inputClass} min-h-24`} disabled={publishedModels.length === 0}>{publishedModels.filter((id) => id !== form.profileId).map((id) => <option key={id} value={id}>{id}</option>)}</select></label>
      <label className="flex items-center gap-2 text-xs text-slate-600"><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} />启用路由规则</label>
    </>}
  </div>
}
