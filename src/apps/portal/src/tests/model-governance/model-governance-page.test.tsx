import type { ReactNode } from 'react'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ModelGovernancePage from '../../../app/model-governance/page'
import { LayoutShell, useRoleContext } from '../../../app/layout'
import {
  createGovernanceDraft,
  createGovernanceVersion,
  getGovernanceAssets,
  getGovernanceReleases,
  getGovernanceVersions,
  getModelGovernanceSnapshot,
  testGovernanceConnection,
  type GovernanceAssetContent,
  type GovernanceDraft,
  type ModelGovernanceSnapshot,
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
  getModelGovernanceSnapshot: vi.fn(),
  getGovernanceAssets: vi.fn(),
  getGovernanceReleases: vi.fn(),
  getGovernanceVersions: vi.fn(),
  createGovernanceDraft: vi.fn(),
  createGovernanceVersion: vi.fn(),
  updateGovernanceDraft: vi.fn(),
  testGovernanceConnection: vi.fn(),
}))

const snapshotFixture: ModelGovernanceSnapshot = {
  prompts: [], models: [], routes: [], providers: [], citations: [], uncertainties: [],
}

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

beforeEach(() => {
  window.sessionStorage.clear()
  vi.mocked(useRoleContext).mockReturnValue({ currentRole: 'information_department', setCurrentRole: vi.fn() })
  vi.mocked(getModelGovernanceSnapshot).mockReset().mockResolvedValue(snapshotFixture)
  vi.mocked(getGovernanceAssets).mockReset().mockResolvedValue({ baselines: [], drafts: [], published: [] })
  vi.mocked(getGovernanceReleases).mockReset().mockResolvedValue([])
  vi.mocked(getGovernanceVersions).mockReset().mockResolvedValue({ versions: [], releases: [] })
  vi.mocked(createGovernanceDraft).mockReset()
  vi.mocked(createGovernanceVersion).mockReset()
  vi.mocked(updateGovernanceDraft).mockReset()
  vi.mocked(testGovernanceConnection).mockReset()
})

afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('模型治理资产中心', () => {
  it('只展示一组运行时指标和确定的环境文案', async () => {
    render(<ModelGovernancePage />)

    expect(await screen.findByRole('heading', { name: '后台管理' })).toBeInTheDocument()
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
    const nextDraft = draft(promptContent)
    vi.mocked(getGovernanceAssets).mockResolvedValue({
      baselines: [{ ...promptContent, runtime_status: 'fallback_static' }],
      drafts: [draft(promptContent, 'approved')], published: [published(promptContent)],
    })
    vi.mocked(getGovernanceVersions).mockResolvedValue({
      versions: [{ version_id: 'version-intent.classify', asset_id: 'intent.classify', asset_type: 'prompt', version_number: 1, content: promptContent, content_hash: 'a'.repeat(64), approval_id: 'approval-1', created_by: 'editor', created_at: '2026-08-17T00:00:00Z' }],
      releases: [{ release_id: 'release-intent.classify', asset_id: 'intent.classify', asset_type: 'prompt', version_id: 'version-intent.classify', environment: 'dev', status: 'active', previous_release_id: null, created_by: 'editor', created_at: '2026-08-17T00:00:00Z', retired_at: null }],
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

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '提示词' }))
    await user.click(screen.getByRole('button', { name: '查看 intent.classify' }))

    expect(screen.getByRole('textbox', { name: '用户提示词模板' })).toHaveValue('下一版：{message}')
    expect(screen.getByRole('button', { name: '发布到dev环境' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: '新建版本' })).not.toBeInTheDocument()
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
    expect(screen.getByText('留空表示不更换')).toBeInTheDocument()
  })

  it('模型配置必须先保存再测试，测试通过后才能发布', async () => {
    const user = userEvent.setup()
    const approved = draft(modelContent, 'approved')
    const savedContent = { ...modelContent, temperature: 0.2 }
    vi.mocked(getGovernanceAssets).mockResolvedValue({ baselines: [], drafts: [approved], published: [] })
    vi.mocked(updateGovernanceDraft).mockResolvedValue({ ...approved, content: savedContent, revision: 2 })
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
      approved.draft_id,
      savedContent,
      approved.revision,
      { credential_id: modelContent.credential_ref, api_key: 'sk-replacement' },
    ))
    expect(connectionButton).toBeEnabled()
    expect(screen.queryByText('请先保存模型工作版本，再测试连接。')).not.toBeInTheDocument()
    await user.click(connectionButton)

    expect(await screen.findByText(/连接成功/)).toBeInTheDocument()
    expect(testGovernanceConnection).toHaveBeenCalledWith(approved.draft_id)
    expect(publishButton).toBeEnabled()
  })

  it('保存模型工作版本后必须重新测试连接', async () => {
    const user = userEvent.setup()
    const approved = draft(modelContent, 'approved')
    vi.mocked(getGovernanceAssets).mockResolvedValue({ baselines: [], drafts: [approved], published: [] })
    vi.mocked(testGovernanceConnection).mockResolvedValue({
      status: 'success', latency_ms: 18, safe_message: '连接成功', tested_at: '2026-08-17T01:00:00Z', content_hash: 'b'.repeat(64),
    })
    vi.mocked(updateGovernanceDraft).mockResolvedValue({ ...approved, revision: 2 })

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '模型' }))
    await user.click(screen.getByRole('button', { name: '查看 model.primary' }))
    await user.click(screen.getByRole('button', { name: '测试连接' }))
    expect(screen.getByRole('button', { name: '发布到dev环境' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: '保存工作版本' }))

    await waitFor(() => expect(updateGovernanceDraft).toHaveBeenCalledOnce())
    expect(screen.getByRole('button', { name: '发布到dev环境' })).toBeDisabled()
    expect(screen.queryByText(/连接成功/)).not.toBeInTheDocument()
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

  it('没有可用已发布模型时禁用新建路由', async () => {
    const user = userEvent.setup()
    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '路由规则' }))
    expect(screen.getByRole('button', { name: '新建路由规则' })).toBeDisabled()
    expect(screen.getByText('请先发布并启用模型，再创建路由规则。')).toBeInTheDocument()
  })

  it('非信息部门可直接查看后台管理并加载治理快照', async () => {
    vi.mocked(useRoleContext).mockReturnValue({ currentRole: 'cashier', setCurrentRole: vi.fn() })
    render(<ModelGovernancePage />)
    expect(await screen.findByRole('heading', { name: '后台管理' })).toBeInTheDocument()
    expect(getModelGovernanceSnapshot).toHaveBeenCalledOnce()
    expect(screen.queryByText('信息科专属')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '切换到信息科' })).not.toBeInTheDocument()
  })

  it('加载与错误状态可被辅助技术感知', async () => {
    vi.mocked(getModelGovernanceSnapshot).mockReturnValueOnce(new Promise(() => undefined))
    const { unmount } = render(<ModelGovernancePage />)
    expect(screen.getByRole('status')).toHaveTextContent('正在加载治理快照')
    unmount()
    vi.mocked(getModelGovernanceSnapshot).mockReset().mockRejectedValue(new Error('network down'))
    render(<ModelGovernancePage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('治理快照暂不可用')
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
