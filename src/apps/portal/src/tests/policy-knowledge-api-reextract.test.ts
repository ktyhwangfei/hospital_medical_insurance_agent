import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  getExtractionConfig,
  getPromptPreview,
  listExtractionModels,
  reextractChangeSet,
} from '@/lib/policy-knowledge-api'

const WORKBENCH_API = '/api/v1/medical-insurance-ai-agent/policy-workbench'

function stubFetchJson(body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe('迭代 18 重新提取 API', () => {
  it('getExtractionConfig 请求提取配置', async () => {
    const fetchMock = stubFetchJson({
      default_prompt_mode: 'schema',
      default_model: 'deepseek-chat',
      default_max_tokens: 8192,
      schema_version: 3,
      metrics: [{ code: 'payment_ratio', name: '支付比例', kind: 'field' }],
      note: 'schema 模式实时读指标',
    })
    const result = await getExtractionConfig()
    expect(fetchMock).toHaveBeenCalledWith(`${WORKBENCH_API}/extraction-config`, undefined)
    expect(result.default_model).toBe('deepseek-chat')
    expect(result.metrics[0].code).toBe('payment_ratio')
  })

  it('listExtractionModels 请求可选模型列表', async () => {
    const fetchMock = stubFetchJson([
      { model_name: 'deepseek-chat', display_name: 'deepseek-chat', available: true },
    ])
    const result = await listExtractionModels()
    expect(fetchMock).toHaveBeenCalledWith(`${WORKBENCH_API}/extraction-config/models`, undefined)
    expect(result[0].model_name).toBe('deepseek-chat')
  })

  it('getPromptPreview schema 模式不带 custom_prompt', async () => {
    const fetchMock = stubFetchJson({ prompt: '...', schema_version: 3, field_count: 19 })
    await getPromptPreview({ prompt_mode: 'schema' })
    expect(fetchMock).toHaveBeenCalledWith(
      `${WORKBENCH_API}/extraction-config/prompt-preview?prompt_mode=schema`,
      undefined,
    )
  })

  it('getPromptPreview custom 模式带 custom_prompt 参数', async () => {
    const fetchMock = stubFetchJson({ prompt: '自定义', schema_version: 3, field_count: 0 })
    await getPromptPreview({ prompt_mode: 'custom', custom_prompt: '自定义提示词' })
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`${WORKBENCH_API}/extraction-config/prompt-preview?`),
      undefined,
    )
    const calledUrl = fetchMock.mock.calls[0][0] as string
    expect(calledUrl).toContain('prompt_mode=custom')
    expect(calledUrl).toContain('custom_prompt=')
  })

  it('reextractChangeSet POST 带 item_ids 与 override', async () => {
    const fetchMock = stubFetchJson({
      change_set_id: 'CS_test',
      total: 1,
      succeeded: 1,
      failed: 0,
      items: [],
      override_applied: { model_name: 'my-model' },
    })
    const result = await reextractChangeSet('CS_test', {
      item_ids: ['ci_1'],
      override: { model_name: 'my-model', prompt_mode: 'schema', operator: 'rev1' },
    })
    expect(fetchMock).toHaveBeenCalledWith(
      `${WORKBENCH_API}/change-sets/CS_test/reextract`,
      expect.objectContaining({ method: 'POST' }),
    )
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string)
    expect(body.item_ids).toEqual(['ci_1'])
    expect(body.override.model_name).toBe('my-model')
    expect(result.succeeded).toBe(1)
  })
})
