import { Buffer } from 'node:buffer'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  createGovernanceDraft,
  getModelGovernanceSnapshot,
} from '@/lib/model-governance-api'

const result = {
  prompts: [],
  models: [],
  routes: [],
  providers: [],
  citations: ['src/model_service/governance.py'],
  uncertainties: [],
}

function responseEnvelope(payload: unknown = result) {
  return new Response(JSON.stringify({
    scenario: 'model_governance',
    status: 'success',
    result: payload,
    citations: [],
    tasks: [],
    missing_fields: [],
    uncertainties: [],
    blocked_actions: [],
    audit: { mode: 'read_only' },
  }), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => {
  window.sessionStorage.clear()
  vi.unstubAllGlobals()
})

describe('模型治理 API 客户端', () => {
  it('读取 sessionStorage 中的治理令牌并解包 AgentResponse.result', async () => {
    window.sessionStorage.setItem('model-governance-token', 'stored-token')
    const fetchMock = vi.fn().mockResolvedValue(responseEnvelope())
    vi.stubGlobal('fetch', fetchMock)

    await expect(getModelGovernanceSnapshot()).resolves.toEqual(result)
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer stored-token')
  })

  it('开发环境令牌包含信息部门角色和只读权限', async () => {
    const fetchMock = vi.fn().mockResolvedValue(responseEnvelope())
    vi.stubGlobal('fetch', fetchMock)

    await getModelGovernanceSnapshot()

    const init = fetchMock.mock.calls[0][1] as RequestInit
    const authorization = new Headers(init.headers).get('Authorization') ?? ''
    const payload = JSON.parse(
      Buffer.from(authorization.replace('Bearer ', '').split('.')[1], 'base64url').toString(),
    ) as { roles: string[]; permissions: string[] }
    expect(payload.roles).toContain('information_department')
    expect(payload.permissions).toContain('model_governance:read')
  })

  it('创建草稿时发送写权限令牌并解包结果', async () => {
    window.sessionStorage.setItem('model-governance-token', 'writer-token')
    const draft = { draft_id: 'draft-1', revision: 1 }
    const fetchMock = vi.fn().mockResolvedValue(responseEnvelope(draft))
    vi.stubGlobal('fetch', fetchMock)

    await expect(createGovernanceDraft({
      asset_type: 'prompt',
      asset_id: 'prompt.demo',
      name: '演示提示词',
      scene: 'policy_qa',
      model_type: 'llm',
      system_prompt: '只输出事实',
      user_prompt_template: '问题：{question}',
      variables: [{ name: 'question', required: true, description: '' }],
      output_mode: 'text',
    })).resolves.toEqual(draft)

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/model-governance/drafts')
    expect(init?.method).toBe('POST')
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer writer-token')
  })
})
