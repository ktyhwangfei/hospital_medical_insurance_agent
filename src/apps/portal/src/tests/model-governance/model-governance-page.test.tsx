import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ModelGovernancePage from '../../../app/model-governance/page'
import { useRoleContext } from '../../../app/layout'
import {
  createGovernanceDraft,
  getGovernanceAssets,
  getGovernanceReleases,
  getModelGovernanceSnapshot,
  type ModelGovernanceSnapshot,
} from '@/lib/model-governance-api'

vi.mock('../../../app/layout', () => ({ useRoleContext: vi.fn() }))
vi.mock('@/lib/model-governance-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/model-governance-api')>()),
  getModelGovernanceSnapshot: vi.fn(),
  getGovernanceAssets: vi.fn(),
  getGovernanceReleases: vi.fn(),
  createGovernanceDraft: vi.fn(),
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

  it('非信息部门直接显示无权限且不发起快照请求', () => {
    vi.mocked(useRoleContext).mockReturnValue({
      currentRole: 'cashier',
      setCurrentRole: vi.fn(),
    })

    render(<ModelGovernancePage />)

    expect(screen.getByRole('alert')).toHaveTextContent('无权查看模型治理台账')
    expect(getModelGovernanceSnapshot).not.toHaveBeenCalled()
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
