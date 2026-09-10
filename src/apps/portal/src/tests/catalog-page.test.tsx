// 数据目录 /catalog 页测试 — #38：概览/防抖搜索/类型过滤/结果列表/详情抽屉+血缘/SLA 看板/错误与空态。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/catalog',
}))

vi.mock('@/lib/catalog-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/catalog-api')>()
  return {
    ...actual,
    searchCatalog: vi.fn(),
    getCatalogOverview: vi.fn(),
    getCatalogSla: vi.fn(),
    getCatalogAsset: vi.fn(),
    getCatalogLineage: vi.fn(),
  }
})

import CatalogPage from '../../app/catalog/page'
import {
  getCatalogAsset,
  getCatalogLineage,
  getCatalogOverview,
  getCatalogSla,
  searchCatalog,
} from '@/lib/catalog-api'
import type {
  CatalogAssetDetailDto,
  CatalogAssetDto,
  CatalogLineageDto,
  CatalogOverviewDto,
  CatalogSearchResultDto,
  CatalogSlaBoardDto,
} from '@/lib/catalog-api'

function asset(overrides: Partial<CatalogAssetDto> = {}): CatalogAssetDto {
  return {
    asset_type: 'metric',
    asset_id: 'Settlement.cash_pay',
    title: '现金自付金额',
    subtitle: 'Settlement.cash_pay',
    matched_on: ['同义词: 自付金额'],
    ...overrides,
  }
}

const overview: CatalogOverviewDto = {
  counts: { dataset: 2, field: 40, object: 1, metric: 2, consumer: 3 },
  sla_sources: 1,
}

const searchResult = (items: CatalogAssetDto[], total = items.length): CatalogSearchResultDto => ({
  query: '自付',
  total,
  items,
})

describe('CatalogPage 数据目录页', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getCatalogOverview).mockResolvedValue(overview)
    vi.mocked(searchCatalog).mockResolvedValue(searchResult([]))
  })
  afterEach(() => cleanup())

  it('初始渲染：概览计数徽标 + 搜索引导空态，未发起搜索', async () => {
    render(<CatalogPage />)
    await waitFor(() => expect(screen.getByTestId('catalog-overview-chips')).toBeTruthy())
    expect(screen.getByText('数据集 2')).toBeTruthy()
    expect(screen.getByText('指标 2')).toBeTruthy()
    expect(screen.getByText('数据源 1')).toBeTruthy()
    expect(screen.getByTestId('catalog-search-hint')).toBeTruthy()
    expect(searchCatalog).not.toHaveBeenCalled()
  })

  it('输入关键词防抖后搜索并渲染结果（类型徽标 + 命中字段）', async () => {
    vi.mocked(searchCatalog).mockResolvedValue(searchResult([
      asset(),
      asset({
        asset_type: 'dataset', asset_id: 'mz_trade', title: '门诊结算交易表',
        subtitle: 'outpatient_postgres.public.mz_trade', matched_on: ['名称'],
      }),
    ]))
    render(<CatalogPage />)
    await waitFor(() => expect(screen.getByTestId('catalog-overview-chips')).toBeTruthy())

    fireEvent.change(screen.getByTestId('catalog-search-input'), { target: { value: '自付' } })
    await waitFor(() => expect(searchCatalog).toHaveBeenCalledWith('自付', { limit: 20 }), { timeout: 2000 })
    await waitFor(() => expect(screen.getByTestId('catalog-search-results')).toBeTruthy())
    expect(screen.getByText('现金自付金额')).toBeTruthy()
    expect(screen.getByTestId('catalog-result-metric')).toBeTruthy()
    expect(screen.getByTestId('catalog-result-dataset')).toBeTruthy()
    expect(screen.getByText(/命中 同义词: 自付金额/)).toBeTruthy()
    expect(screen.getByTestId('catalog-search-results').textContent).toContain('共 2 个资产')
  })

  it('类型过滤变化后带 asset_type 重新搜索', async () => {
    render(<CatalogPage />)
    await waitFor(() => expect(screen.getByTestId('catalog-overview-chips')).toBeTruthy())
    fireEvent.change(screen.getByTestId('catalog-type-filter'), { target: { value: 'metric' } })
    fireEvent.change(screen.getByTestId('catalog-search-input'), { target: { value: '自付' } })
    await waitFor(
      () => expect(searchCatalog).toHaveBeenLastCalledWith('自付', { asset_type: 'metric', limit: 20 }),
      { timeout: 2000 },
    )
  })

  it('搜索无结果展示空态', async () => {
    vi.mocked(searchCatalog).mockResolvedValue(searchResult([], 0))
    render(<CatalogPage />)
    await waitFor(() => expect(screen.getByTestId('catalog-overview-chips')).toBeTruthy())
    fireEvent.change(screen.getByTestId('catalog-search-input'), { target: { value: '不存在' } })
    await waitFor(() => expect(screen.getByTestId('catalog-search-empty')).toBeTruthy(), { timeout: 2000 })
  })

  it('搜索失败展示错误条', async () => {
    vi.mocked(searchCatalog).mockRejectedValue(new Error('数据目录服务不可用'))
    render(<CatalogPage />)
    await waitFor(() => expect(screen.getByTestId('catalog-overview-chips')).toBeTruthy())
    fireEvent.change(screen.getByTestId('catalog-search-input'), { target: { value: '自付' } })
    await waitFor(() => expect(screen.getByTestId('catalog-error')).toBeTruthy(), { timeout: 2000 })
    expect(screen.getByTestId('catalog-error').textContent).toContain('数据目录服务不可用')
  })

  it('点击结果打开详情抽屉：摘要 + 值域码表，切到血缘页签加载血缘链', async () => {
    vi.mocked(searchCatalog).mockResolvedValue(searchResult([asset()]))
    const detail: CatalogAssetDetailDto = {
      asset: asset(),
      summary: [
        { key: '所属对象', value: '结算 Settlement' },
        { key: '生效期', value: '2024-01-01 起现行' },
      ],
      fields: [],
      metrics: [],
      datasets: [],
      consumers: [],
      batches: [],
      versions: [],
      value_mappings: [{ source_value: '1', standard_value: '已结算', description: null }],
    }
    const lineage: CatalogLineageDto = {
      asset: asset(),
      sources: ['bjybdb'],
      batches: [{
        batch_id: 'b1111111111', source_id: 'bjybdb', mode: 'incremental',
        semantic_version: '1.2.0', published_at: '2026-09-09T04:00:00+00:00',
        source_committed_at: null, row_count: 120, quality_status: 'passed',
        latency_seconds: 30,
      }],
      datasets: [{
        dataset_code: 'mz_trade', object_code: 'Settlement', datasource_id: 'outpatient_postgres',
        table_name: 'mz_trade', name: '门诊结算交易表', status: 'published',
      }],
      fields: [],
      metrics: [asset() && {
        metric_code: 'Settlement.cash_pay', name: '现金自付金额', object_code: 'Settlement',
        status: 'published', owner: '医保数据组', definition: null,
      }],
      consumers: [{
        consumer_id: 'mzsettlement_verify_skill', name: '门诊结算核验', kind: 'skill',
        consumed_objects: ['Settlement'], consumed_metrics: ['Settlement.cash_pay'],
      }],
      versions: [{
        version: '1', published_at: '2026-09-01T00:00:00+00:00',
        published_by: '语义治理组', changelog: null, metric_count: 2,
      }],
    }
    vi.mocked(getCatalogAsset).mockResolvedValue(detail)
    vi.mocked(getCatalogLineage).mockResolvedValue(lineage)
    render(<CatalogPage />)
    await waitFor(() => expect(screen.getByTestId('catalog-overview-chips')).toBeTruthy())
    fireEvent.change(screen.getByTestId('catalog-search-input'), { target: { value: '自付' } })
    await waitFor(() => expect(screen.getByTestId('catalog-search-results')).toBeTruthy(), { timeout: 2000 })

    fireEvent.click(screen.getByTestId('catalog-result-metric'))
    await waitFor(() => expect(getCatalogAsset).toHaveBeenCalledWith('metric', 'Settlement.cash_pay'))
    await waitFor(() => expect(screen.getByTestId('catalog-drawer')).toBeTruthy())
    expect(screen.getByText('2024-01-01 起现行')).toBeTruthy()
    expect(screen.getByText('已结算')).toBeTruthy()

    fireEvent.click(screen.getByTestId('catalog-drawer-tabs').children[1])
    await waitFor(() => expect(getCatalogLineage).toHaveBeenCalledWith('metric', 'Settlement.cash_pay'))
    await waitFor(() => expect(screen.getByTestId('catalog-lineage-view')).toBeTruthy())
    expect(screen.getByText('bjybdb')).toBeTruthy()
    expect(screen.getByText('门诊结算核验')).toBeTruthy()
  })

  it('SLA 页签渲染数据源卡片与最近批次表', async () => {
    const sla: CatalogSlaBoardDto = {
      generated_at: '2026-09-09T04:30:00+00:00',
      sources: [{
        source_id: 'bjybdb', source_name: '北京医保库', connection_status: 'HEALTHY',
        job_status: 'READY', p95_latency_seconds: 45.5, last_non_empty_latency_seconds: 42,
        non_empty_sample_count: 10, quality_status: 'passed', semantic_version: '1.2.0',
        last_batch: {
          batch_id: 'b2222222222', source_id: 'bjybdb', mode: 'incremental',
          semantic_version: '1.2.0', published_at: '2026-09-09T04:00:00+00:00',
          source_committed_at: null, row_count: 120, quality_status: 'passed', latency_seconds: 30,
        },
        recent_runs_total: 3, recent_runs_succeeded: 2, recent_runs_failed: 1,
        last_run_at: '2026-09-09T04:00:00+00:00', last_error_code: 'SYNC_TIMEOUT',
      }],
      recent_batches: [{
        batch_id: 'b2222222222', source_id: 'bjybdb', mode: 'incremental',
        semantic_version: '1.2.0', published_at: '2026-09-09T04:00:00+00:00',
        source_committed_at: null, row_count: 120, quality_status: 'passed', latency_seconds: 30,
      }],
    }
    vi.mocked(getCatalogSla).mockResolvedValue(sla)
    render(<CatalogPage />)
    await waitFor(() => expect(screen.getByTestId('catalog-overview-chips')).toBeTruthy())
    fireEvent.click(screen.getByTestId('catalog-tabs').children[1])
    await waitFor(() => expect(screen.getByTestId('catalog-sla-card')).toBeTruthy())
    expect(screen.getByText('北京医保库')).toBeTruthy()
    expect(screen.getByText(/45\.5 秒/)).toBeTruthy()
    expect(screen.getByText(/成功 2 \/ 失败 1/)).toBeTruthy()
    expect(screen.getByText('SYNC_TIMEOUT')).toBeTruthy()
    await waitFor(() => expect(screen.getByTestId('catalog-recent-batches')).toBeTruthy())
    expect(screen.getByTestId('catalog-recent-batches').textContent).toContain('b2222222')
  })
})
