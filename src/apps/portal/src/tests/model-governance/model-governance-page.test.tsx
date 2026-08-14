import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ModelGovernancePage from '../../../app/model-governance/page'
import { useRoleContext } from '../../../app/layout'
import {
  createGovernanceDraft,
  deleteGovernanceDraft,
  getGovernanceAssets,
  getGovernanceReleases,
  getModelGovernanceSnapshot,
  importCurrentGovernanceAssets,
  type ModelGovernanceSnapshot,
} from '@/lib/model-governance-api'

vi.mock('../../../app/layout', () => ({ useRoleContext: vi.fn() }))
vi.mock('@/lib/model-governance-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/model-governance-api')>()),
  getModelGovernanceSnapshot: vi.fn(),
  getGovernanceAssets: vi.fn(),
  getGovernanceReleases: vi.fn(),
  createGovernanceDraft: vi.fn(),
  deleteGovernanceDraft: vi.fn(),
  importCurrentGovernanceAssets: vi.fn(),
}))

const emptyParameters = { temperature: null, max_tokens: null }

const promptFixture: ModelGovernanceSnapshot['prompts'] = Array.from({ length: 11 }, (_, index) => {
  const isSkill = index === 2
  return {
    prompt_id: index === 0 ? 'intent.classify' : isSkill ? 'skill.settlement_explain' : `prompt.${index}`,
    name: index === 0 ? '意图分类' : isSkill ? '结算解释技能' : `提示词 ${index}`,
    source_path: index === 0
      ? 'src/runtime/intent/prompts.py'
      : isSkill
        ? 'skills/settlement_explain_skill/templates/prompt_template.yaml'
        : `src/prompts/${index}.py`,
    related_source_paths: index === 3
      ? ['src/knowledge_extension/rule_explanation/policy_fact/deepseek_llm_client.py']
      : [],
    source_kind: isSkill ? 'yaml' : 'code',
    scene: index === 0 ? 'intent_recognition' : isSkill ? 'fee_explanation' : null,
    model_type: 'llm',
    gateway_status: index === 1 ? 'direct' : 'routed',
    management_status: index === 1 ? 'needs_migration' : 'source_managed',
    declared_parameters: isSkill
      ? { temperature: 0.3, max_tokens: 1024 }
      : emptyParameters,
    route_defaults: index === 1
      ? emptyParameters
      : { temperature: 0.1, max_tokens: 4096 },
    call_overrides: emptyParameters,
    effective_parameters: index === 1
      ? emptyParameters
      : { temperature: 0.1, max_tokens: 4096 },
    warnings: index === 1
      ? ['绕过统一网关']
      : isSkill
        ? ['声明参数 temperature=0.3/max_tokens=1024 与实际生效 temperature=0.1/max_tokens=4096 不一致']
        : [],
  }
})

const snapshotFixture: ModelGovernanceSnapshot = {
  prompts: promptFixture,
  models: [{ model_name: 'gpt-4.1-mini-with-a-very-long-model-name', temperature: 0.2, max_tokens: 2048 }],
  routes: [
    {
      scene: 'intent_recognition',
      model_type: 'llm',
      effective_model: 'gpt-4.1-mini-with-a-very-long-model-name',
      explicit: false,
      fallbacks: ['gpt-4.1-nano-with-a-very-long-model-name'],
      warnings: ['未显式登记，解析为 default 路由'],
    },
    {
      scene: 'fee_explanation',
      model_type: 'llm',
      effective_model: 'gpt-4.1-mini-with-a-very-long-model-name',
      explicit: true,
      fallbacks: [],
      warnings: [],
    },
  ],
  providers: [
    {
      provider_id: 'dummy',
      type: 'development_fixture',
      endpoint: 'dummy',
      credential_status: 'not_applicable',
    },
  ],
  citations: ['src/config/model_service.py'],
  uncertainties: ['遗留提示词调用可达性仍待核验'],
}

beforeEach(() => {
  vi.mocked(useRoleContext).mockReturnValue({
    currentRole: 'information_department',
    setCurrentRole: vi.fn(),
  })
  vi.mocked(getModelGovernanceSnapshot).mockReset()
  vi.mocked(getGovernanceAssets).mockReset()
  vi.mocked(getGovernanceReleases).mockReset()
  vi.mocked(createGovernanceDraft).mockReset()
  vi.mocked(deleteGovernanceDraft).mockReset()
  vi.mocked(importCurrentGovernanceAssets).mockReset()
  vi.mocked(getModelGovernanceSnapshot).mockResolvedValue(snapshotFixture)
  vi.mocked(getGovernanceAssets).mockResolvedValue({ drafts: [], published: [] })
  vi.mocked(getGovernanceReleases).mockResolvedValue([])
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('模型治理页', () => {
  it('信息部门可读取只读台账，并看到参数来源、不一致告警和开发夹具', async () => {
    render(<ModelGovernancePage />)

    expect(await screen.findByRole('heading', { name: '模型与提示词治理' })).toBeInTheDocument()
    expect(getModelGovernanceSnapshot).toHaveBeenCalledOnce()
    expect(screen.getByText('只读台账')).toBeInTheDocument()
    const governanceSummary = screen.getByLabelText('治理摘要')
    await waitFor(() => expect(within(governanceSummary).getByText('11')).toBeInTheDocument())

    const promptTable = screen.getByRole('table', { name: '提示词台账' })
    expect(within(promptTable).getByText('意图分类')).toBeInTheDocument()
    expect(within(promptTable).getByText('直连待迁移')).toBeInTheDocument()
    expect(within(promptTable).getByText(/deepseek_llm_client\.py/)).toBeInTheDocument()
    const skillRow = within(promptTable).getByText('结算解释技能').closest('tr')
    expect(skillRow).not.toBeNull()
    expect(within(skillRow!).getByText('声明：温度 0.3，最大 1024')).toBeInTheDocument()
    expect(within(skillRow!).getByText('路由默认：温度 0.1，最大 4096')).toBeInTheDocument()
    expect(within(skillRow!).getByText('调用覆盖：未覆盖')).toBeInTheDocument()
    expect(within(skillRow!).getByText('实际：温度 0.1，最大 4096')).toBeInTheDocument()
    expect(within(skillRow!).getByText(/声明参数.*实际生效/)).toBeInTheDocument()

    const routeTable = screen.getByRole('table', { name: '模型路由台账' })
    expect(within(routeTable).getByText('默认路由')).toBeInTheDocument()
    expect(within(routeTable).getByText('显式路由')).toBeInTheDocument()
    expect(within(routeTable).getAllByText('gpt-4.1-mini-with-a-very-long-model-name')[0]).toHaveClass('break-all')

    const providerOverview = screen.getByLabelText('Provider 概览')
    expect(within(providerOverview).getByText('开发夹具')).toBeInTheDocument()
    expect(within(providerOverview).getByText('凭据不适用')).toBeInTheDocument()
    expect(within(providerOverview).getByText('dummy')).toHaveClass('break-all')
    expect(screen.getByText('遗留提示词调用可达性仍待核验')).toBeInTheDocument()
    expect(screen.getByText('src/config/model_service.py')).toBeInTheDocument()
  })

  it('创建提示词草稿并明确展示尚未发布', async () => {
    const user = userEvent.setup()
    vi.mocked(createGovernanceDraft).mockResolvedValue({
      draft_id: 'draft-1',
      asset_id: 'prompt.demo',
      asset_type: 'prompt',
      content: {
        asset_type: 'prompt',
        asset_id: 'prompt.demo',
        name: '演示提示词',
        scene: 'policy_qa',
        model_type: 'llm',
        system_prompt: '只输出事实',
        user_prompt_template: '问题：{question}',
        variables: [{ name: 'question', required: true, description: '' }],
        output_mode: 'text',
      },
      status: 'editing',
      revision: 1,
      validation_issues: [],
      created_by: 'editor',
      last_edited_by: 'editor',
      created_at: '2026-08-14T00:00:00Z',
      updated_at: '2026-08-14T00:00:00Z',
    })

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '提示词' }))
    await user.click(screen.getByRole('button', { name: '新建提示词' }))
    await user.type(screen.getByLabelText('提示词标识'), 'prompt.demo')
    await user.type(screen.getByLabelText('用户提示词模板'), '问题：{question}')
    await user.click(screen.getByRole('button', { name: '保存草稿' }))

    expect(await screen.findByText('编辑中')).toBeInTheDocument()
    expect(screen.getByText('尚未发布')).toBeInTheDocument()
  })

  it('显式导入现有配置后展示可编辑提示词和导入统计', async () => {
    const user = userEvent.setup()
    const draft = {
      draft_id: 'imported-prompt',
      asset_id: 'intent.classify',
      asset_type: 'prompt' as const,
      content: {
        asset_type: 'prompt' as const,
        asset_id: 'intent.classify',
        name: '意图分类',
        scene: 'intent_recognition',
        model_type: 'llm',
        system_prompt: '',
        user_prompt_template: '用户消息：{message}',
        variables: [{ name: 'message', required: true, description: '用户消息' }],
        output_mode: 'json' as const,
      },
      status: 'editing' as const,
      revision: 1,
      validation_issues: [],
      created_by: 'editor',
      last_edited_by: 'editor',
      created_at: '2026-08-14T00:00:00Z',
      updated_at: '2026-08-14T00:00:00Z',
    }
    vi.mocked(importCurrentGovernanceAssets).mockResolvedValue({
      drafts: [draft],
      created_count: 18,
      skipped_count: 0,
      counts: { prompt: 11, model_profile: 2, route_rule: 5 },
    })

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('button', { name: '导入现有配置' }))

    const panel = screen.getByRole('tabpanel')
    expect(await within(panel).findByText('intent.classify')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('已导入 11 个提示词、2 个模型档案、5 条路由规则')
    await user.click(within(panel).getByRole('button', { name: '编辑' }))
    expect(screen.getByLabelText('输出模式')).toHaveValue('json')
    expect(screen.getByLabelText(/提示词变量/)).toHaveValue('message|必填|用户消息')
  })

  it('模型档案可编辑启用状态，未发布草稿可删除', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('confirm', vi.fn(() => true))
    vi.mocked(createGovernanceDraft).mockImplementation(async (content) => ({
      draft_id: 'model-draft',
      asset_id: content.asset_id,
      asset_type: content.asset_type,
      content,
      status: 'editing',
      revision: 1,
      validation_issues: [],
      created_by: 'editor',
      last_edited_by: 'editor',
      created_at: '2026-08-14T00:00:00Z',
      updated_at: '2026-08-14T00:00:00Z',
    }))
    vi.mocked(deleteGovernanceDraft).mockImplementation(async () => ({
      draft_id: 'model-draft',
      asset_id: 'model.demo',
      asset_type: 'model_profile',
      content: {
        asset_type: 'model_profile', asset_id: 'model.demo', name: '演示模型',
        provider_id: 'default', model_name: 'demo', credential_ref: 'MODEL_API_KEY',
        temperature: 0.1, max_tokens: 4096, enabled: false,
      },
      status: 'editing', revision: 1, validation_issues: [], created_by: 'editor',
      last_edited_by: 'editor', created_at: '2026-08-14T00:00:00Z', updated_at: '2026-08-14T00:00:00Z',
    }))

    render(<ModelGovernancePage />)
    await user.click(await screen.findByRole('tab', { name: '模型档案' }))
    await user.click(screen.getByRole('button', { name: '新建模型档案' }))
    await user.type(screen.getByLabelText('资产标识'), 'model.demo')
    await user.type(screen.getByLabelText('模型名'), 'demo')
    await user.click(screen.getByRole('checkbox', { name: '启用模型档案' }))
    await user.click(screen.getByRole('button', { name: '保存草稿' }))

    expect(createGovernanceDraft).toHaveBeenCalledWith(expect.objectContaining({ enabled: false }))
    await user.click(screen.getByRole('button', { name: '删除草稿' }))
    await waitFor(() => expect(screen.queryByText('model.demo')).not.toBeInTheDocument())
  })

  it('非信息部门可从无权限提示切换到信息科且不提前发起请求', async () => {
    const user = userEvent.setup()
    const setCurrentRole = vi.fn()
    vi.mocked(useRoleContext).mockReturnValue({
      currentRole: 'cashier',
      setCurrentRole,
    })

    render(<ModelGovernancePage />)

    expect(screen.getByRole('alert')).toHaveTextContent('无权查看模型治理台账')
    expect(getModelGovernanceSnapshot).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: '切换到信息科' }))
    expect(setCurrentRole).toHaveBeenCalledWith('information_department')
  })

  it('加载状态可被辅助技术感知', () => {
    vi.mocked(getModelGovernanceSnapshot).mockReturnValue(new Promise(() => undefined))

    render(<ModelGovernancePage />)

    const loading = screen.getByRole('status')
    expect(loading).toHaveAttribute('aria-live', 'polite')
    expect(loading).toHaveTextContent('正在加载治理快照')
  })

  it('快照请求失败时用警报提示不可用，不伪造空数据', async () => {
    vi.mocked(getModelGovernanceSnapshot).mockRejectedValue(new Error('network down'))

    render(<ModelGovernancePage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('治理快照暂不可用')
    expect(screen.queryByText('提示词台账')).not.toBeInTheDocument()
  })

  it('真实 Provider 未配置凭据时使用警告样式', async () => {
    vi.mocked(getModelGovernanceSnapshot).mockResolvedValue({
      ...snapshotFixture,
      providers: [{
        provider_id: 'default',
        type: 'openai_compatible',
        endpoint: 'https://provider.example:8443',
        credential_status: 'missing',
      }],
    })

    render(<ModelGovernancePage />)

    const credentialStatus = await screen.findByText('未配置凭据')
    expect(credentialStatus).toHaveClass('bg-amber-50')
    expect(credentialStatus).not.toHaveClass('bg-emerald-50')
  })

  it('侧栏仅向信息部门角色提供模型治理入口', () => {
    const layout = readFileSync(resolve(process.cwd(), 'app/layout.tsx'), 'utf8')

    expect(layout).toContain("label: '模型治理'")
    expect(layout).toContain("href: '/model-governance'")
    expect(layout).toContain("currentRole === 'information_department'")
  })
})
