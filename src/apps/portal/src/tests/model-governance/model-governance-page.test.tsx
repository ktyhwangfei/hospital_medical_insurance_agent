import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ModelGovernancePage from '../../../app/model-governance/page'
import {
  getModelGovernanceSnapshot,
  type ModelGovernanceSnapshot,
} from '@/lib/model-governance-api'

vi.mock('@/lib/model-governance-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/model-governance-api')>()),
  getModelGovernanceSnapshot: vi.fn(),
}))

const promptFixture: ModelGovernanceSnapshot['prompts'] = Array.from({ length: 11 }, (_, index) => ({
  prompt_id: index === 0 ? 'intent.classify' : `prompt.${index}`,
  name: index === 0 ? '意图分类' : `提示词 ${index}`,
  source_path: index === 0 ? 'src/runtime/intent/prompts.py' : `src/prompts/${index}.py`,
  source_kind: 'code',
  scene: index === 0 ? 'intent_recognition' : null,
  model_type: 'llm',
  gateway_status: index === 1 ? 'direct' : 'routed',
  management_status: index === 1 ? 'needs_migration' : 'source_managed',
  warnings: index === 1 ? ['绕过统一网关'] : [],
}))

const snapshotFixture: ModelGovernanceSnapshot = {
  prompts: promptFixture,
  models: [{ model_name: 'gpt-4.1-mini', temperature: 0.2, max_tokens: 2048 }],
  routes: [
    {
      scene: 'intent_recognition',
      model_type: 'llm',
      effective_model: 'gpt-4.1-mini',
      explicit: false,
      fallbacks: ['gpt-4.1-nano'],
      warnings: ['未显式登记，解析为 default 路由'],
    },
    {
      scene: 'fee_explanation',
      model_type: 'llm',
      effective_model: 'gpt-4.1-mini',
      explicit: true,
      fallbacks: [],
      warnings: [],
    },
  ],
  providers: [
    {
      provider_id: 'default',
      type: 'openai_compatible',
      endpoint: 'https://user:secret@provider.example:8443/v1?api_key=secret',
      credential_status: 'configured',
    },
  ],
  citations: ['src/config/model_service.py'],
  uncertainties: ['遗留提示词调用可达性仍待核验'],
}

beforeEach(() => {
  vi.mocked(getModelGovernanceSnapshot).mockReset()
  vi.mocked(getModelGovernanceSnapshot).mockResolvedValue(snapshotFixture)
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('模型治理页', () => {
  it('展示只读台账、快照计数、路由状态和来源说明', async () => {
    render(<ModelGovernancePage />)

    expect(await screen.findByRole('heading', { name: '模型与提示词治理' })).toBeInTheDocument()
    expect(screen.getByText('只读台账')).toBeInTheDocument()
    const governanceSummary = screen.getByLabelText('治理摘要')
    await waitFor(() => expect(within(governanceSummary).getByText('11')).toBeInTheDocument())
    expect(within(governanceSummary).getByText('提示词')).toBeInTheDocument()
    expect(within(governanceSummary).getByText('模型')).toBeInTheDocument()
    expect(within(governanceSummary).getByText('路由')).toBeInTheDocument()
    expect(within(governanceSummary).getByText('Provider')).toBeInTheDocument()
    expect(within(governanceSummary).getByText('2')).toBeInTheDocument()
    expect(within(governanceSummary).getAllByText('1')).toHaveLength(2)

    const promptTable = screen.getByRole('table', { name: '提示词台账' })
    expect(within(promptTable).getByText('意图分类')).toBeInTheDocument()
    expect(within(promptTable).getByText('src/runtime/intent/prompts.py')).toBeInTheDocument()
    expect(within(promptTable).getByText('直连待迁移')).toBeInTheDocument()

    const routeTable = screen.getByRole('table', { name: '模型路由台账' })
    expect(within(routeTable).getByText('intent_recognition')).toBeInTheDocument()
    expect(within(routeTable).getByText('默认路由')).toBeInTheDocument()
    expect(within(routeTable).getByText('fee_explanation')).toBeInTheDocument()
    expect(within(routeTable).getByText('显式路由')).toBeInTheDocument()

    const providerOverview = screen.getByLabelText('Provider 概览')
    expect(within(providerOverview).getByText('https://provider.example:8443')).toBeInTheDocument()
    expect(within(providerOverview).getByText('凭据已配置')).toBeInTheDocument()
    expect(within(providerOverview).queryByText(/secret/)).not.toBeInTheDocument()
    expect(screen.getByText('遗留提示词调用可达性仍待核验')).toBeInTheDocument()
    expect(screen.getByText('src/config/model_service.py')).toBeInTheDocument()
  })

  it('快照请求失败时提示不可用，不伪造空数据', async () => {
    vi.mocked(getModelGovernanceSnapshot).mockRejectedValue(new Error('network down'))

    render(<ModelGovernancePage />)

    expect(await screen.findByText('治理快照暂不可用')).toBeInTheDocument()
    expect(screen.queryByText('提示词台账')).not.toBeInTheDocument()
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })

  it('Provider 未配置凭据时使用警告样式', async () => {
    vi.mocked(getModelGovernanceSnapshot).mockResolvedValue({
      ...snapshotFixture,
      providers: [{
        ...snapshotFixture.providers[0],
        credential_status: 'missing',
      }],
    })

    render(<ModelGovernancePage />)

    const credentialStatus = await screen.findByText('未配置凭据')
    expect(credentialStatus).toHaveClass('bg-amber-50')
    expect(credentialStatus).not.toHaveClass('bg-emerald-50')
  })

  it('侧栏提供模型治理入口', () => {
    const layout = readFileSync(resolve(process.cwd(), 'app/layout.tsx'), 'utf8')

    expect(layout).toContain("label: '模型治理'")
    expect(layout).toContain("href: '/model-governance'")
  })
})
