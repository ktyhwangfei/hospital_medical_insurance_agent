import type { ReactNode } from 'react'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ModelGovernancePage from '../../../app/model-governance/page'
import { LayoutShell, useRoleContext } from '../../../app/layout'
import {
  approveGovernanceDraft,
  createGovernanceDraft,
  createGovernanceVersion,
  getGovernanceAssets,
  getGovernanceReleases,
  getGovernanceVersions,
  publishGovernanceDraft,
  probeModelList,
  requestGovernanceReview,
  rollbackGovernanceRelease,
  testGovernanceConnection,
  validateGovernanceDraft,
  type GovernanceAssetContent,
  type GovernanceDraft,
  type GovernanceRelease,
  type GovernanceVersionsResult,
  updateGovernanceDraft,
} from '@/lib/model-governance-api'

vi.mock('next/navigation', () => ({ usePathname: () => '/policy-qa' }))
vi.mock('next/font/google', () => ({ Noto_Sans_SC: () => ({ variable: '' }) }))
vi.mock('@/lib/api-context', () => ({
  ApiProvider: ({ children }: { children: ReactNode }) => children,
  useApiContext: () => ({ connectionStatus: 'unknown' }),
}))
vi.mock('@/components/role-switcher', () => ({
  default: () => <button type="button">角色切换</button>,
}))
vi.mock('../../../app/layout', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../app/layout')>()),
  useRoleContext: vi.fn(),
}))
vi.mock('@/lib/model-governance-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/model-governance-api')>()),
  getGovernanceAssets: vi.fn(),
  getGovernanceReleases: vi.fn(),
  getGovernanceVersions: vi.fn(),
  createGovernanceDraft: vi.fn(),
  createGovernanceVersion: vi.fn(),
  updateGovernanceDraft: vi.fn(),
  validateGovernanceDraft: vi.fn(),
  requestGovernanceReview: vi.fn(),
  approveGovernanceDraft: vi.fn(),
  publishGovernanceDraft: vi.fn(),
  rollbackGovernanceRelease: vi.fn(),
  probeModelList: vi.fn(),
  testGovernanceConnection: vi.fn(),
}))

const promptContent: GovernanceAssetContent = {
  asset_type: 'prompt', asset_id: 'intent.classify', name: '意图分类',
  scene: 'intent_recognition', model_type: 'llm', system_prompt: '只输出结构化意图',
  user_prompt_template: '用户消息：{message}',
  variables: [{ name: 'message', required: true, description: '用户消息' }], output_mode: 'json',
}

const modelContent: GovernanceAssetContent = {
  asset_type: 'model_profile', asset_id: 'model.primary', name: '主模型',
  provider_id: 'openai_compatible', base_url: 'https://model.example/v1', model_name: 'deepseek-chat',
  credential_ref: 'credential.model.primary', timeout_seconds: 30, temperature: 0.1,
  max_tokens: 4096, enabled: true,
}

const routeContent: GovernanceAssetContent = {
  asset_type: 'route_rule', asset_id: 'route.policy_fact_extraction.llm', name: '政策结构化路由',
  scene: 'policy_fact_extraction', model_type: 'llm', profile_id: 'model.primary',
  fallback_profile_ids: [], enabled: true,
}

function draft(content: GovernanceAssetContent, status: GovernanceDraft['status'] = 'editing'): GovernanceDraft {
  return {
    draft_id: `draft-${content.asset_id}`, asset_id: content.asset_id, asset_type: content.asset_type,
    content, status, revision: 1, validation_issues: [], created_by: 'editor', last_edited_by: 'editor',
    created_at: '2026-08-17T00:00:00Z', updated_at: '2026-08-17T00:00:00Z',
  }
}

function published(content: GovernanceAssetContent) {
  return {
    asset_id: content.asset_id, asset_type: content.asset_type, version_id: `version-${content.asset_id}`,
    release_id: `release-${content.asset_id}`, content_hash: 'a'.repeat(64), content,
    runtime_status: 'governed_active' as const,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve
    reject = nextReject
  })
  return { promise, resolve, reject }
}

function versionHistory(content: GovernanceAssetContent, versionNumber: number, releaseStatus: 'active' | 'retired' = 'active'): GovernanceVersionsResult {
  const versionId = `version-${content.asset_id}-${versionNumber}`
  return {
    versions: [{
      version_id: versionId, asset_id: content.asset_id, asset_type: content.asset_type,
      version_number: versionNumber, content, content_hash: 'c'.repeat(64), approval_id: 'approval-1',
      created_by: 'editor', created_at: '2026-08-17T00:00:00Z',
    }],
    releases: [{
      release_id: `release-${content.asset_id}-${versionNumber}`, asset_id: content.asset_id,
      asset_type: content.asset_type, version_id: versionId, environment: 'dev', status: releaseStatus,
      previous_release_id: null, source_draft_id: null, created_by: 'editor', created_at: '2026-08-17T00:00:00Z',
      retired_at: releaseStatus === 'retired' ? '2026-08-17T01:00:00Z' : null,
    }],
  }
}

beforeEach(() => {
  window.sessionStorage.clear()
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
  vi.mocked(useRoleContext).mockReturnValue({ currentRole: 'information_department', setCurrentRole: vi.fn() })
  vi.mocked(getGovernanceAssets).mockReset().mockResolvedValue({ baselines: [], drafts: [], published: [] })
  vi.mocked(getGovernanceReleases).mockReset().mockResolvedValue([])
  vi.mocked(getGovernanceVersions).mockReset().mockResolvedValue({ versions: [], releases: [] })
  vi.mocked(createGovernanceDraft).mockReset()
  vi.mocked(createGovernanceVersion).mockReset()
  vi.mocked(updateGovernanceDraft).mockReset()
  vi.mocked(validateGovernanceDraft).mockReset()
  vi.mocked(requestGovernanceReview).mockReset()
  vi.mocked(approveGovernanceDraft).mockReset()
  vi.mocked(publishGovernanceDraft).mockReset()
  vi.mocked(rollbackGovernanceRelease).mockReset()
  vi.mocked(probeModelList).mockReset()
  vi.mocked(testGovernanceConnection).mockReset()
})

afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('模型治理资产中心', () => {
  it('只展示一组运行时指标和确定的环境文案', async () => {
    render(<ModelGovernancePage />)

    expect(screen.getByRole('heading', { name: '后台管理' })).toBeInTheDocument()
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      '概览', '提示词', '模型', '路由规则', '发布记录',
    ])
    const metrics = await screen.findByLabelText('治理指标')
    expect(within(metrics).getByText('活动资产')).toBeInTheDocument()
    expect(within(metrics).getByText('工作草稿')).toBeInTheDocument()
    expect(within(metrics).getByText('待审核')).toBeInTheDocument()
    expect(within(metrics).getByText('连接异常')).toBeInTheDocument()
    expect(screen.getByText('当前环境：dev · 治理发布已接入运行时')).toBeInTheDocument()
    expect(screen.queryByText(/尚未接入运行时/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Provider 凭据状态/)).not.toBeInTheDocument()
  })

  it('提示词按资产合并为一行，活动内容只读且只能新建版本编辑', async () => {
    const user = userEvent.setup()
    const sourceDraft = draft(promptContent, 'approved')
    const nextDraft = { ...draft(promptContent), draft_id: 'draft-intent-next' }
    vi.mocked(getGovernanceAssets).mockResolvedValue({
      baselines: [{ ...promptContent, runtime_status: 'fallback_static' }],
      drafts: [sourceDraft], published: [published(promptContent)],
    })
    vi.mocked(getGovernanceReleases).mockResolvedValue([{
      release_id: 'release-intent.classify', asset_id: 'intent.classify', asset_type: 'prompt',
      version_id: 'version-intent.classify', source_draft_id: sourceDraft.draft_id,
      environment: 'dev', status: 'active', previous_release_id: null, created_by: 'editor',
      created_at: '2026-08-17T00:00:00Z', retired_at: null,
    }])
    vi.mocked(getGovernanceVersions).mockResolvedValue({
      versions: [{ version_id: 'version-intent.classify', asset_id: 'intent.classify', asset_type: 'prompt', version_number: 1, content: promptContent, content_hash: 'a'.repeat(64), approval_id: 'approval-1', created_by: 'editor', created_at: '2026-08-17T00:00:00Z' }],
      releases: [{ release_id: 'release-intent.classify', asset_id: 'intent.classify', asset_type: 'prompt', version_id: 'version-intent.classify', source_draft_id: sourceDraft.draft_id, environment: 'dev', status: 'active', previous_release_id: null, created_by: 'editor', created_at: '2026-08-17T00:00:00Z', retired_at: null }],
    })
    vi.mocked(createGovernanceVersion).mockResolvedValue(nextDraft)

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '提示词' }))
    expect(screen.getAllByText('intent.classify')).toHaveLength(1)
    const trigger = screen.getByRole('button', { name: '查看 intent.classify' })
    await user.click(trigger)

    const drawer = screen.getByRole('dialog', { name: '提示词 · 意图分类' })
    expect(drawer).toHaveAttribute('aria-modal', 'true')
    expect(within(drawer).getByText('用户消息：{message}')).toBeInTheDocument()
    expect(within(drawer).queryByRole('textbox', { name: '用户提示词模板' })).not.toBeInTheDocument()
    expect(within(drawer).getByText('版本 1 · 活动')).toBeInTheDocument()
    await user.click(within(drawer).getByRole('button', { name: '新建版本' }))
    expect(createGovernanceVersion).toHaveBeenCalledWith('intent.classify', 'dev')
    expect(await within(drawer).findByRole('textbox', { name: '用户提示词模板' })).toBeEnabled()
    await user.keyboard('{Escape}')
    expect(trigger).toHaveFocus()
  })

  it('已发布来源草稿不覆盖内容不同的下一工作版本', async () => {
    const user = userEvent.setup()
    const nextContent = { ...promptContent, user_prompt_template: '下一版：{message}' }
    const sourceDraft = draft(promptContent, 'approved')
    const nextDraft = { ...draft(nextContent, 'approved'), draft_id: 'draft-intent-next', updated_at: '2026-08-17T01:00:00Z' }
    vi.mocked(getGovernanceAssets).mockResolvedValue({
      baselines: [{ ...promptContent, runtime_status: 'fallback_static' }],
      drafts: [sourceDraft, nextDraft],
      published: [published(promptContent)],
    })
    vi.mocked(getGovernanceReleases).mockResolvedValue([{
      release_id: 'release-intent.classify', asset_id: 'intent.classify', asset_type: 'prompt',
      version_id: 'version-intent.classify', source_draft_id: sourceDraft.draft_id,
      environment: 'dev', status: 'active', previous_release_id: null, created_by: 'editor',
      created_at: '2026-08-17T00:00:00Z', retired_at: null,
    }])

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '提示词' }))
    await user.click(screen.getByRole('button', { name: '查看 intent.classify' }))

    expect(screen.getByRole('textbox', { name: '用户提示词模板' })).toHaveValue('下一版：{message}')
    expect(screen.getByRole('button', { name: '发布到dev环境' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: '新建版本' })).not.toBeInTheDocument()
  })

  it('v2 活动时 v1 发布来源草稿不会变成工作版本', async () => {
    const user = userEvent.setup()
    const v1Content = { ...promptContent, user_prompt_template: 'v1：{message}' }
    const v2Content = { ...promptContent, user_prompt_template: 'v2：{message}' }
    const v1Draft = { ...draft(v1Content, 'approved'), draft_id: 'draft-intent-v1', updated_at: '2026-08-17T02:00:00Z' }
    const v2Draft = { ...draft(v2Content, 'approved'), draft_id: 'draft-intent-v2', updated_at: '2026-08-17T01:00:00Z' }
    vi.mocked(getGovernanceAssets).mockResolvedValue({
      baselines: [], drafts: [v1Draft, v2Draft], published: [published(v2Content)],
    })
    vi.mocked(getGovernanceReleases).mockResolvedValue([
      {
        release_id: 'release-intent-v2', asset_id: promptContent.asset_id, asset_type: 'prompt',
        version_id: 'version-intent.classify', environment: 'dev', status: 'active',
        previous_release_id: 'release-intent-v1', source_draft_id: v2Draft.draft_id,
        created_by: 'editor', created_at: '2026-08-17T01:00:00Z', retired_at: null,
      },
      {
        release_id: 'release-intent-v1', asset_id: promptContent.asset_id, asset_type: 'prompt',
        version_id: 'version-intent-v1', environment: 'dev', status: 'retired',
        previous_release_id: null, source_draft_id: v1Draft.draft_id,
        created_by: 'editor', created_at: '2026-08-17T00:00:00Z', retired_at: '2026-08-17T01:00:00Z',
      },
    ])

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '提示词' }))
    await user.click(screen.getByRole('button', { name: '查看 intent.classify' }))

    expect(screen.getByRole('button', { name: '新建版本' })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: '用户提示词模板' })).not.toBeInTheDocument()
  })

  it('内容相同但换了凭据的已审核草稿仍可测试并发布', async () => {
    const user = userEvent.setup()
    const sourceDraft = { ...draft(modelContent, 'approved'), draft_id: 'draft-model-v1' }
    const credentialDraft = {
      ...draft(modelContent, 'approved'), draft_id: 'draft-model-new-credential',
      revision: 5, updated_at: '2026-08-17T01:00:00Z',
    }
    const activeRelease: GovernanceRelease = {
      release_id: 'release-model-v1', asset_id: modelContent.asset_id, asset_type: 'model_profile',
      version_id: 'version-model.primary', environment: 'dev', status: 'active',
      previous_release_id: null, source_draft_id: sourceDraft.draft_id,
      created_by: 'editor', created_at: '2026-08-17T00:00:00Z', retired_at: null,
    }
    vi.mocked(getGovernanceAssets).mockResolvedValue({
      baselines: [], drafts: [sourceDraft, credentialDraft], published: [published(modelContent)],
    })
    vi.mocked(getGovernanceReleases).mockResolvedValue([activeRelease])
    vi.mocked(testGovernanceConnection).mockResolvedValue({
      status: 'success', latency_ms: 12, safe_message: '连接成功',
      tested_at: '2026-08-17T02:00:00Z', content_hash: 'b'.repeat(64),
    })
    vi.mocked(publishGovernanceDraft).mockResolvedValue(activeRelease)

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '模型' }))
    await user.click(screen.getByRole('button', { name: '查看 model.primary' }))

    expect(screen.getByLabelText('API 访问地址')).toHaveValue(modelContent.base_url)
    await user.click(screen.getByRole('button', { name: '测试连接' }))
    const publishButton = screen.getByRole('button', { name: '发布到dev环境' })
    expect(publishButton).toBeEnabled()
    await user.click(publishButton)
    await waitFor(() => expect(publishGovernanceDraft).toHaveBeenCalledWith(credentialDraft.draft_id, 5, 'dev'))
  })

  it('无活动版本的代码基线可创建首个草稿', async () => {
    const user = userEvent.setup()
    vi.mocked(getGovernanceAssets).mockResolvedValue({
      baselines: [{ ...promptContent, runtime_status: 'fallback_static' }], drafts: [], published: [],
    })
    vi.mocked(createGovernanceDraft).mockResolvedValue(draft(promptContent))

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '提示词' }))
    await user.click(screen.getByRole('button', { name: '查看 intent.classify' }))
    expect(screen.getAllByText('代码基线（回退）')).toHaveLength(2)
    await user.click(screen.getByRole('button', { name: '创建首个草稿' }))
    expect(createGovernanceDraft).toHaveBeenCalledWith(expect.objectContaining({ asset_id: 'intent.classify' }))
    expect(await screen.findByRole('textbox', { name: '用户提示词模板' })).toBeEnabled()
  })

  it('模型表单字段完整，API Key 只随写请求提交并在保存后清空', async () => {
    const user = userEvent.setup()
    vi.mocked(createGovernanceDraft).mockImplementation(async (content) => draft(content))

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '模型' }))
    await user.click(screen.getByRole('button', { name: '新建模型' }))

    const keyInput = await screen.findByLabelText('API Key')
    expect(keyInput).toHaveAttribute('type', 'password')
    expect(keyInput).toHaveAttribute('autocomplete', 'new-password')
    expect(keyInput).toHaveValue('')
    expect(screen.getByLabelText('Provider')).toHaveValue('OpenAI-compatible')
    expect(screen.getByLabelText('API 访问地址')).toBeInTheDocument()
    expect(screen.getByLabelText('超时（秒）')).toBeInTheDocument()
    expect(screen.getByLabelText('温度')).toBeInTheDocument()
    expect(screen.getByLabelText('最大 tokens')).toBeInTheDocument()
    await user.type(screen.getByLabelText('资产 ID'), 'model.demo')
    await user.type(screen.getByLabelText('显示名称'), '演示模型')
    await user.type(screen.getByLabelText('模型名'), 'demo-chat')
    await user.clear(screen.getByLabelText('Credential ID'))
    await user.type(screen.getByLabelText('Credential ID'), 'credential.model.demo')
    await user.type(keyInput, 'sk-request-only')
    await user.click(screen.getByRole('button', { name: '保存工作版本' }))

    expect(createGovernanceDraft).toHaveBeenCalledWith(
      expect.objectContaining({ base_url: 'https://api.openai.com/v1', timeout_seconds: 30 }),
      { credential_id: 'credential.model.demo', api_key: 'sk-request-only' },
    )
    expect(keyInput).toHaveValue('')
    expect(screen.getByText(/留空表示不更换/)).toBeInTheDocument()
  })

  it('探测中修改地址会立即解锁且忽略旧响应', async () => {
    const user = userEvent.setup()
    const stale = deferred<{ models: string[]; safe_message: string }>()
    vi.mocked(probeModelList)
      .mockReturnValueOnce(stale.promise)
      .mockResolvedValueOnce({ models: ['new-model'], safe_message: '已获取新列表' })
    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '模型' }))
    await user.click(screen.getByRole('button', { name: '新建模型' }))

    await user.click(screen.getByRole('button', { name: '获取模型列表' }))
    expect(screen.getByRole('button', { name: '正在获取…' })).toBeDisabled()
    await user.clear(screen.getByLabelText('API 访问地址'))
    await user.type(screen.getByLabelText('API 访问地址'), 'https://new.example/v1')

    const retry = screen.getByRole('button', { name: '获取模型列表' })
    expect(retry).toBeEnabled()
    await user.click(retry)
    expect(await screen.findByText('已获取新列表')).toBeInTheDocument()
    expect(screen.getByLabelText('模型名')).toHaveValue('new-model')

    stale.resolve({ models: ['stale-model'], safe_message: '旧列表' })
    await waitFor(() => expect(screen.queryByText('旧列表')).not.toBeInTheDocument())
    expect(screen.getByLabelText('模型名')).toHaveValue('new-model')
  })

  it('资产 ID 不符合后端规则时在提交前给出可读提示', async () => {
    const user = userEvent.setup()
    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '模型' }))
    await user.click(screen.getByRole('button', { name: '新建模型' }))

    await user.type(screen.getByLabelText('资产 ID'), 'DeepSeek V4')

    expect(screen.getByText('仅支持小写字母、数字、点、下划线和短横线，且至少 3 个字符')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存工作版本' })).toBeDisabled()
    expect(createGovernanceDraft).not.toHaveBeenCalled()
  })

  it('模型按真实生命周期审核，保存并连接成功后才允许发布', async () => {
    const user = userEvent.setup()
    const editing = draft(modelContent)
    const savedContent = { ...modelContent, temperature: 0.2 }
    const saved = { ...editing, content: savedContent, revision: 2 }
    const validated = { ...saved, status: 'validated' as const, revision: 3 }
    const reviewPending = { ...saved, status: 'review_pending' as const, revision: 4 }
    const approved = { ...saved, status: 'approved' as const, revision: 5 }
    vi.mocked(getGovernanceAssets).mockResolvedValue({ baselines: [], drafts: [editing], published: [] })
    vi.mocked(updateGovernanceDraft).mockResolvedValue(saved)
    vi.mocked(validateGovernanceDraft).mockResolvedValue(validated)
    vi.mocked(requestGovernanceReview).mockResolvedValue(reviewPending)
    vi.mocked(approveGovernanceDraft).mockResolvedValue(approved)
    vi.mocked(publishGovernanceDraft).mockResolvedValue(versionHistory(savedContent, 1).releases[0])
    vi.mocked(testGovernanceConnection).mockResolvedValue({
      status: 'success', latency_ms: 18, safe_message: '连接成功', tested_at: '2026-08-17T01:00:00Z', content_hash: 'b'.repeat(64),
    })

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '模型' }))
    await user.click(screen.getByRole('button', { name: '查看 model.primary' }))
    const publishButton = screen.getByRole('button', { name: '发布到dev环境' })
    const connectionButton = screen.getByRole('button', { name: '测试连接' })
    expect(publishButton).toBeDisabled()
    await user.clear(screen.getByLabelText('温度'))
    await user.type(screen.getByLabelText('温度'), '0.2')
    expect(connectionButton).toBeDisabled()
    expect(publishButton).toBeDisabled()
    expect(screen.getByText('请先保存模型工作版本，再测试连接。')).toBeInTheDocument()
    await user.type(screen.getByLabelText('API Key'), 'sk-replacement')
    expect(connectionButton).toBeDisabled()

    await user.click(screen.getByRole('button', { name: '保存工作版本' }))
    await waitFor(() => expect(updateGovernanceDraft).toHaveBeenCalledWith(
      editing.draft_id,
      savedContent,
      editing.revision,
      { credential_id: modelContent.credential_ref, api_key: 'sk-replacement' },
    ))
    expect(connectionButton).toBeEnabled()
    expect(screen.queryByText('请先保存模型工作版本，再测试连接。')).not.toBeInTheDocument()
    await user.click(connectionButton)

    expect(await screen.findByText(/连接成功/)).toBeInTheDocument()
    expect(testGovernanceConnection).toHaveBeenCalledWith(editing.draft_id)
    expect(publishButton).toBeDisabled()

    await user.click(screen.getByRole('button', { name: '校验' }))
    await user.click(await screen.findByRole('button', { name: '申请审核' }))
    await user.selectOptions(screen.getByLabelText('开发身份'), 'reviewer')
    await user.click(await screen.findByRole('button', { name: '审核通过' }))
    expect(publishButton).toBeDisabled()
    const reviewerConnectionButton = screen.getByRole('button', { name: '测试连接' })
    expect(reviewerConnectionButton).toBeDisabled()
    await user.click(reviewerConnectionButton)
    expect(testGovernanceConnection).toHaveBeenCalledTimes(1)
    await user.selectOptions(screen.getByLabelText('开发身份'), 'editor')
    expect(publishButton).toBeEnabled()
    await user.click(publishButton)
    await waitFor(() => expect(publishGovernanceDraft).toHaveBeenCalledWith(editing.draft_id, 5, 'dev'))
  })

  it('保存模型工作版本后必须重新测试连接', async () => {
    const user = userEvent.setup()
    const editing = draft(modelContent)
    vi.mocked(getGovernanceAssets).mockResolvedValue({ baselines: [], drafts: [editing], published: [] })
    vi.mocked(testGovernanceConnection).mockResolvedValue({
      status: 'success', latency_ms: 18, safe_message: '连接成功', tested_at: '2026-08-17T01:00:00Z', content_hash: 'b'.repeat(64),
    })
    vi.mocked(updateGovernanceDraft).mockResolvedValue({ ...editing, revision: 2 })

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '模型' }))
    await user.click(screen.getByRole('button', { name: '查看 model.primary' }))
    await user.click(screen.getByRole('button', { name: '测试连接' }))
    expect(screen.getByRole('button', { name: '发布到dev环境' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '保存工作版本' }))

    await waitFor(() => expect(updateGovernanceDraft).toHaveBeenCalledOnce())
    expect(screen.getByRole('button', { name: '发布到dev环境' })).toBeDisabled()
    expect(screen.queryByText(/连接成功/)).not.toBeInTheDocument()
  })

  it('A 资产慢版本请求不能覆盖后来打开的 B 资产', async () => {
    const user = userEvent.setup()
    const secondPrompt = { ...promptContent, asset_id: 'claim.explain', name: '理赔解释' }
    const slowA = deferred<GovernanceVersionsResult>()
    vi.mocked(getGovernanceAssets).mockResolvedValue({
      baselines: [], drafts: [draft(promptContent), draft(secondPrompt)], published: [],
    })
    vi.mocked(getGovernanceVersions).mockImplementation((assetId) => assetId === 'intent.classify'
      ? slowA.promise
      : Promise.resolve(versionHistory(secondPrompt, 2)))

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '提示词' }))
    await user.click(screen.getByRole('button', { name: '查看 intent.classify' }))
    await user.click(screen.getByRole('button', { name: '关闭详情抽屉' }))
    await user.click(screen.getByRole('button', { name: '查看 claim.explain' }))
    expect(await screen.findByText('版本 2 · 活动')).toBeInTheDocument()

    slowA.resolve(versionHistory(promptContent, 1))
    await waitFor(() => expect(screen.queryByText('版本 1 · 活动')).not.toBeInTheDocument())
    expect(screen.getByText('版本 2 · 活动')).toBeInTheDocument()
  })

  it('详情回滚后同时刷新当前版本历史与主资产', async () => {
    const user = userEvent.setup()
    const retiredHistory = versionHistory(promptContent, 1, 'retired')
    const activeHistory = versionHistory(promptContent, 1, 'active')
    vi.mocked(getGovernanceAssets).mockResolvedValue({ baselines: [], drafts: [], published: [published(promptContent)] })
    vi.mocked(getGovernanceVersions).mockResolvedValueOnce(retiredHistory).mockResolvedValueOnce(activeHistory)
    vi.mocked(rollbackGovernanceRelease).mockResolvedValue(activeHistory.releases[0])

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '提示词' }))
    await user.click(screen.getByRole('button', { name: '查看 intent.classify' }))
    await user.click(await screen.findByRole('button', { name: '回滚至此版本' }))

    await waitFor(() => expect(getGovernanceVersions).toHaveBeenCalledTimes(2))
    expect(getGovernanceVersions).toHaveBeenLastCalledWith('intent.classify', 'dev')
    expect(getGovernanceAssets).toHaveBeenCalledTimes(2)
    expect(screen.getByText('版本 1 · 活动')).toBeInTheDocument()
  })

  it('发布记录页无需打开资产详情也能回滚并刷新主资产', async () => {
    const user = userEvent.setup()
    const retiredRelease = versionHistory(promptContent, 1, 'retired').releases[0]
    const activeRelease = { ...retiredRelease, status: 'active' as const, retired_at: null }
    vi.mocked(getGovernanceReleases).mockResolvedValue([retiredRelease])
    vi.mocked(rollbackGovernanceRelease).mockResolvedValue(activeRelease)

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '发布记录' }))
    await user.click(await screen.findByRole('button', { name: '回滚' }))

    await waitFor(() => expect(rollbackGovernanceRelease).toHaveBeenCalledWith(retiredRelease.release_id))
    expect(getGovernanceAssets).toHaveBeenCalledTimes(2)
  })

  it('回滚请求中关闭抽屉仍刷新主资产但不再刷新版本历史', async () => {
    const user = userEvent.setup()
    const retiredHistory = versionHistory(promptContent, 1, 'retired')
    const rollbackRequest = deferred<GovernanceRelease>()
    vi.mocked(getGovernanceAssets).mockResolvedValue({ baselines: [], drafts: [], published: [published(promptContent)] })
    vi.mocked(getGovernanceVersions).mockResolvedValue(retiredHistory)
    vi.mocked(rollbackGovernanceRelease).mockReturnValue(rollbackRequest.promise)

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '提示词' }))
    await user.click(screen.getByRole('button', { name: '查看 intent.classify' }))
    await user.click(await screen.findByRole('button', { name: '回滚至此版本' }))
    await user.click(screen.getByRole('button', { name: '关闭详情抽屉' }))
    rollbackRequest.resolve({ ...retiredHistory.releases[0], status: 'active', retired_at: null })

    await waitFor(() => expect(getGovernanceAssets).toHaveBeenCalledTimes(2))
    expect(getGovernanceVersions).toHaveBeenCalledTimes(1)
  })

  it('旧 dev 回滚完成后不能覆盖已经切换成功的 test 资产', async () => {
    const user = userEvent.setup()
    const retiredRelease = versionHistory(promptContent, 1, 'retired').releases[0]
    const testContent = { ...promptContent, asset_id: 'test.prompt', name: '测试环境提示词' }
    const rollbackRequest = deferred<GovernanceRelease>()
    vi.mocked(getGovernanceAssets).mockImplementation(async (requestEnvironment) => requestEnvironment === 'test'
      ? { baselines: [], drafts: [draft(testContent)], published: [] }
      : { baselines: [], drafts: [], published: [published(promptContent)] })
    vi.mocked(getGovernanceReleases).mockImplementation(async (requestEnvironment) => requestEnvironment === 'test' ? [] : [retiredRelease])
    vi.mocked(rollbackGovernanceRelease).mockReturnValue(rollbackRequest.promise)

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '发布记录' }))
    await user.click(await screen.findByRole('button', { name: '回滚' }))
    const environmentSelect = screen.getByLabelText('环境')
    expect(environmentSelect).toBeDisabled()

    fireEvent.change(environmentSelect, { target: { value: 'test' } })
    expect(await screen.findByText('治理发布已接入运行时 · 当前 test 环境')).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: '提示词' }))
    expect(screen.getByText('test.prompt')).toBeInTheDocument()

    rollbackRequest.resolve({ ...retiredRelease, status: 'active', retired_at: null })
    await waitFor(() => expect(environmentSelect).toBeEnabled())
    expect(vi.mocked(getGovernanceAssets).mock.calls.map(([requestEnvironment]) => requestEnvironment)).toEqual(['dev', 'test'])
    expect(screen.getByText('test.prompt')).toBeInTheDocument()
    expect(screen.queryByText('intent.classify')).not.toBeInTheDocument()
  })

  it('关闭详情或切换环境会立即清空未保存 API Key', async () => {
    const user = userEvent.setup()
    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '模型' }))
    await user.click(screen.getByRole('button', { name: '新建模型' }))
    await user.type(screen.getByLabelText('API Key'), 'sk-close-secret')
    await user.click(screen.getByRole('button', { name: '关闭详情抽屉' }))
    await user.click(screen.getByRole('button', { name: '新建模型' }))
    expect(screen.getByLabelText('API Key')).toHaveValue('')
    await user.type(screen.getByLabelText('API Key'), 'sk-environment-secret')
    await user.selectOptions(screen.getByLabelText('环境'), 'test')
    await user.click(await screen.findByRole('tab', { name: '模型' }))
    await user.click(screen.getByRole('button', { name: '新建模型' }))
    expect(screen.getByLabelText('API Key')).toHaveValue('')
  })

  it('当前生效模型完整展示运行参数', async () => {
    const user = userEvent.setup()
    vi.mocked(getGovernanceAssets).mockResolvedValue({ baselines: [], drafts: [], published: [published(modelContent)] })

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '模型' }))
    await user.click(screen.getByRole('button', { name: '查看 model.primary' }))
    const drawer = screen.getByRole('dialog', { name: '模型 · 主模型' })
    expect(within(drawer).getByText('温度')).toBeInTheDocument()
    expect(within(drawer).getByText('0.1')).toBeInTheDocument()
    expect(within(drawer).getByText('最大 tokens')).toBeInTheDocument()
    expect(within(drawer).getByText('4096')).toBeInTheDocument()
    expect(within(drawer).getByText('启用状态')).toBeInTheDocument()
    expect(within(drawer).getByText('已启用')).toBeInTheDocument()
  })

  it('路由主备模型只能从已发布 enabled 模型中选择', async () => {
    const user = userEvent.setup()
    vi.mocked(getGovernanceAssets).mockResolvedValue({ baselines: [], drafts: [], published: [published(modelContent)] })

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '路由规则' }))
    await user.click(screen.getByRole('button', { name: '新建路由规则' }))
    expect(screen.getByLabelText('主模型').tagName).toBe('SELECT')
    expect(screen.getByLabelText('备用模型').tagName).toBe('SELECT')
    expect(within(screen.getByLabelText('主模型')).getByRole('option', { name: 'model.primary' })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: '主模型' })).not.toBeInTheDocument()
  })

  it('没有已发布模型时仍可用模型草稿新建路由', async () => {
    const user = userEvent.setup()
    vi.mocked(getGovernanceAssets).mockResolvedValue({ baselines: [], drafts: [draft(modelContent)], published: [] })
    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '路由规则' }))
    await user.click(screen.getByRole('button', { name: '新建路由规则' }))
    expect(within(screen.getByLabelText('主模型')).getByRole('option', { name: 'model.primary' })).toBeInTheDocument()
    expect(screen.getByText('可先配置路由草稿；发布路由前需先发布并启用所引用的模型。')).toBeInTheDocument()
  })

  it('展示路由草稿的模型发布校验错误', async () => {
    const user = userEvent.setup()
    const invalidRoute = {
      ...draft(routeContent),
      validation_issues: [{ code: 'MODEL_PROFILE_NOT_PUBLISHED', message: '模型档案未发布或已停用: model.primary', path: 'profile_id' }],
    }
    vi.mocked(getGovernanceAssets).mockResolvedValue({
      baselines: [], drafts: [draft(modelContent), invalidRoute], published: [],
    })
    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '路由规则' }))
    await user.click(screen.getByRole('button', { name: '查看 route.policy_fact_extraction.llm' }))
    expect(screen.getByText('模型档案未发布或已停用: model.primary')).toBeInTheDocument()
  })

  it('非信息部门可直接查看后台管理并加载治理资产', async () => {
    vi.mocked(useRoleContext).mockReturnValue({ currentRole: 'cashier', setCurrentRole: vi.fn() })
    render(<ModelGovernancePage />)
    expect(await screen.findByRole('heading', { name: '后台管理' })).toBeInTheDocument()
    expect(getGovernanceAssets).toHaveBeenCalledOnce()
    expect(screen.queryByText('信息科专属')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '切换到信息科' })).not.toBeInTheDocument()
  })

  it('工作区加载、错误和重试状态可被辅助技术感知', async () => {
    vi.mocked(getGovernanceAssets).mockReturnValueOnce(new Promise(() => undefined))
    const { unmount } = render(<ModelGovernancePage />)
    expect(screen.getByRole('heading', { name: '后台管理' })).toBeInTheDocument()
    expect(await screen.findByRole('status')).toHaveTextContent('正在加载治理资产')
    unmount()
    vi.mocked(getGovernanceAssets).mockReset().mockRejectedValueOnce(new Error('network down')).mockResolvedValue({ baselines: [], drafts: [], published: [] })
    render(<ModelGovernancePage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('治理资产与发布记录加载失败')
    await userEvent.setup().click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByLabelText('治理指标')).toBeInTheDocument()
  })

  it('切换环境失败时清空旧资产且错误不伪装为空数据', async () => {
    const user = userEvent.setup()
    vi.mocked(getGovernanceAssets).mockImplementation(async (environment) => {
      if (environment === 'test') throw new Error('test offline')
      return { baselines: [], drafts: [], published: [published(promptContent)] }
    })
    vi.mocked(getGovernanceReleases).mockImplementation(async (environment) => {
      if (environment === 'test') throw new Error('test offline')
      return []
    })

    render(<ModelGovernancePage />)
    expect(await screen.findByText('当前环境：dev · 治理发布已接入运行时')).toBeInTheDocument()
    expect(within(screen.getByLabelText('治理指标')).getByText('1')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('环境'), 'test')

    expect(await screen.findByRole('alert')).toHaveTextContent('test offline')
    expect(screen.queryByLabelText('治理指标')).not.toBeInTheDocument()
    expect(screen.queryByText('当前环境：test · 治理发布已接入运行时')).not.toBeInTheDocument()
    expect(screen.queryByText('intent.classify')).not.toBeInTheDocument()
    expect(screen.queryByText('暂无提示词资产')).not.toBeInTheDocument()
    expect(screen.queryByText('暂无发布记录')).not.toBeInTheDocument()
  })

  it('切换环境时保持 reviewer 身份与请求 token 同步', async () => {
    const user = userEvent.setup()
    render(<ModelGovernancePage />)
    expect(await screen.findByText('当前环境：dev · 治理发布已接入运行时')).toBeInTheDocument()
    const identitySelect = screen.getByLabelText('开发身份')
    const editorToken = window.sessionStorage.getItem('model-governance-token')

    await user.selectOptions(identitySelect, 'reviewer')
    const reviewerToken = window.sessionStorage.getItem('model-governance-token')
    expect(reviewerToken).toBeTruthy()
    expect(reviewerToken).not.toBe(editorToken)
    expect(identitySelect).toHaveValue('reviewer')

    await user.selectOptions(screen.getByLabelText('环境'), 'test')
    expect(await screen.findByText('当前环境：test · 治理发布已接入运行时')).toBeInTheDocument()
    expect(identitySelect).toHaveValue('reviewer')
    expect(window.sessionStorage.getItem('model-governance-token')).toBe(reviewerToken)
  })

  it('侧栏向所有角色提供底部后台管理入口', () => {
    vi.mocked(useRoleContext).mockReturnValue({ currentRole: 'cashier', setCurrentRole: vi.fn() })
    render(<LayoutShell><div>页面内容</div></LayoutShell>)
    const adminLink = screen.getByRole('link', { name: '后台管理' })
    expect(adminLink).toHaveAttribute('href', '/model-governance')
    const adminNav = adminLink.closest('nav')
    const sidebarFooter = screen.getByRole('contentinfo', { name: '侧栏页脚' })
    expect(adminNav).toHaveAccessibleName('后台管理')
    expect(adminNav?.nextElementSibling).toBe(sidebarFooter)
  })
})
