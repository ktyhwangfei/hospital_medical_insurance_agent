import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  getCatalogAsset,
  getCatalogAssetLineage,
  getCatalogSla,
  listCatalogAssets,
  refreshCatalog,
} from '@/lib/data-catalog-api'

const API = '/api/v1/medical-insurance-ai-agent/data-catalog'

function mockFetchOnce(payload: unknown, status = 200) {
  const spy = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(payload), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', spy)
  return spy
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('data-catalog-api', () => {
  it('listCatalogAssets 透传 asset_type/keyword/limit 查询参数', async () => {
    const spy = mockFetchOnce({ items: [], limit: 200, offset: 0 })
    await listCatalogAssets({ asset_type: 'metric', keyword: '统筹', limit: 200 })
    const [url, init] = spy.mock.calls[0]
    expect(url).toBe(`${API}/assets?asset_type=metric&keyword=%E7%BB%9F%E7%AD%B9&limit=200`)
    expect(init?.method ?? 'GET').toBe('GET')
  })

  it('listCatalogAssets 无过滤时不带查询串', async () => {
    const spy = mockFetchOnce({ items: [], limit: 50, offset: 0 })
    await listCatalogAssets()
    expect(spy.mock.calls[0][0]).toBe(`${API}/assets`)
  })

  it('getCatalogAsset 按 asset_id 编码路径', async () => {
    const spy = mockFetchOnce({ asset_id: 'ca_1' })
    await getCatalogAsset('ca_1')
    expect(spy.mock.calls[0][0]).toBe(`${API}/assets/ca_1`)
  })

  it('getCatalogAssetLineage 解析节点与边', async () => {
    const payload = {
      root: 'm1',
      nodes: [
        { asset_id: 't1', asset_key: 'source_table:mz_trade', asset_type: 'source_table', name: '门诊交易表', semantic_version: '4', last_batch_id: 'b-1' },
      ],
      edges: [{ upstream: 't1', downstream: 'm1', relation: 'feeds' }],
    }
    const spy = mockFetchOnce(payload)
    const result = await getCatalogAssetLineage('m1')
    expect(spy.mock.calls[0][0]).toBe(`${API}/assets/m1/lineage`)
    expect(result.edges[0].relation).toBe('feeds')
    expect(result.nodes[0].last_batch_id).toBe('b-1')
  })

  it('refreshCatalog POST /refresh 返回 upsert/prune 统计', async () => {
    const spy = mockFetchOnce({ upserted: 139, pruned: 0 })
    const result = await refreshCatalog()
    const [url, init] = spy.mock.calls[0]
    expect(url).toBe(`${API}/refresh`)
    expect(init?.method).toBe('POST')
    expect(result).toEqual({ upserted: 139, pruned: 0 })
  })

  it('getCatalogSla 解析门诊同步与质量门禁', async () => {
    const payload = {
      outpatient_sync: {
        source_id: 'bjybdb',
        last_batch_id: 'b-1',
        last_published_at: null,
        p95_latency_seconds: 15.7,
        non_empty_sample_count: 2,
        quality_status: 'ok',
      },
      quality_gates: [
        { task_id: 'task_1', metric_code: 'mzjyxx.T_FundPay', status: 'completed', golden_score: { filling_rate: 0.9 }, created_at: null },
      ],
    }
    const spy = mockFetchOnce(payload)
    const result = await getCatalogSla()
    expect(spy.mock.calls[0][0]).toBe(`${API}/sla`)
    expect(result.outpatient_sync?.p95_latency_seconds).toBe(15.7)
    expect(result.quality_gates[0].golden_score.filling_rate).toBe(0.9)
  })
})
