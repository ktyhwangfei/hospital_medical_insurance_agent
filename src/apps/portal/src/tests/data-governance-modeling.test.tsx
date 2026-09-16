// 数据建模页：列表 / 新建草稿 / 发布冻结 / 映射确认流。
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import DataModelingPage from '../../app/data-governance/(manage)/modeling/page'
import {
  confirmDataModelMapping,
  createDataModel,
  listDataModelMappings,
  listDataModels,
  publishDataModel,
  type DataModel,
} from '@/lib/data-model-api'

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('@/lib/data-model-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/data-model-api')>()),
  listDataModels: vi.fn(),
  getDataModel: vi.fn(),
  createDataModel: vi.fn(),
  updateDataModel: vi.fn(),
  publishDataModel: vi.fn(),
  deprecateDataModel: vi.fn(),
  listDataModelMappings: vi.fn(),
  saveDataModelMapping: vi.fn(),
  confirmDataModelMapping: vi.fn(),
}))

function model(overrides: Partial<DataModel> = {}): DataModel {
  return {
    model_code: 'dwd_mz_settlement',
    name: '门诊结算明细模型',
    layer: 'dwd',
    grain: 'trade_no',
    entity_code: 'settlement',
    status: 'draft',
    owner: 'data_governance',
    description: '',
    fields: [
      { field_code: 'trade_no', name: '交易号', data_type: 'varchar', field_role: 'identifier' },
      { field_code: 'pooling_payment', name: '统筹支付', data_type: 'decimal', field_role: 'fact' },
    ],
    version: 1,
    revision: 1,
    created_at: '2026-09-15T00:00:00Z',
    updated_at: '2026-09-15T00:00:00Z',
    ...overrides,
  }
}

describe('数据建模页', () => {
  beforeEach(() => {
    vi.mocked(listDataModels).mockResolvedValue([model()])
    vi.mocked(listDataModelMappings).mockResolvedValue([])
  })
  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('列表展示模型结构与状态', async () => {
    render(<DataModelingPage />)
    await waitFor(() => screen.getByTestId('model-row-dwd_mz_settlement'))
    expect(screen.getByText('门诊结算明细模型')).toBeTruthy()
    expect(screen.getByText('DWD')).toBeTruthy()
    expect(screen.getByText('2 个')).toBeTruthy()
    expect(screen.getByText('草稿')).toBeTruthy()
  })

  it('草稿可编辑与发布；published 只显示退役', async () => {
    render(<DataModelingPage />)
    const row = await screen.findByTestId('model-row-dwd_mz_settlement')
    expect(row.textContent).toContain('编辑')
    expect(row.textContent).toContain('发布')

    vi.mocked(listDataModels).mockResolvedValue([model({ status: 'published', version: 2 })])
    vi.mocked(publishDataModel).mockResolvedValue(model({ status: 'published', version: 2 }))
    fireEvent.click(screen.getByRole('button', { name: /发布/ }))
    await waitFor(() => expect(publishDataModel).toHaveBeenCalledWith('dwd_mz_settlement'))
  })

  it('详情弹窗展示字段与映射确认流', async () => {
    vi.mocked(listDataModelMappings).mockResolvedValue([{
      model_code: 'dwd_mz_settlement', field_code: 'pooling_payment', source_id: 'bjybdb',
      physical_table: 'mz_trade', physical_column: 'T_FundPay',
      transform_rule: null, status: 'draft', revision: 1,
    }])
    render(<DataModelingPage />)
    fireEvent.click(await screen.findByText('门诊结算明细模型'))
    const detail = await screen.findByTestId('model-detail')
    expect(detail.textContent).toContain('pooling_payment')
    await waitFor(() => expect(detail.textContent).toContain('mz_trade.T_FundPay'))
    expect(detail.textContent).toContain('待确认')

    vi.mocked(confirmDataModelMapping).mockResolvedValue({} as never)
    fireEvent.click(screen.getByRole('button', { name: '确认' }))
    await waitFor(() =>
      expect(confirmDataModelMapping).toHaveBeenCalledWith('dwd_mz_settlement', 'pooling_payment', 'bjybdb'))
  })

  it('空态提示首个样板模型', async () => {
    vi.mocked(listDataModels).mockResolvedValue([])
    render(<DataModelingPage />)
    await waitFor(() => screen.getByText('暂无数据模型'))
    expect(screen.getByText(/dwd_mz_settlement/)).toBeTruthy()
  })

  it('新建走 createDataModel 并回显', async () => {
    vi.mocked(createDataModel).mockResolvedValue(model())
    render(<DataModelingPage />)
    fireEvent.click(await screen.findByRole('button', { name: /新建数据模型/ }))
    const form = await screen.findByTestId('model-edit-form')
    expect(form).toBeTruthy()
    // 填最简必填 + 一个 identifier 和一个 fact 字段
    fireEvent.change(screen.getByPlaceholderText('dwd_mz_settlement'), { target: { value: 'dwd_mz_settlement' } })
    fireEvent.change(screen.getByPlaceholderText('门诊结算明细模型'), { target: { value: '门诊结算明细模型' } })
    fireEvent.change(screen.getByPlaceholderText('trade_no'), { target: { value: 'trade_no' } })
    fireEvent.click(screen.getByRole('button', { name: /添加字段/ }))
    fireEvent.click(screen.getByRole('button', { name: /添加字段/ }))
    const codes = screen.getAllByLabelText('字段编码')
    fireEvent.change(codes[0], { target: { value: 'trade_no' } })
    fireEvent.change(codes[1], { target: { value: 'pooling_payment' } })
    fireEvent.change(screen.getAllByLabelText('字段名称')[0], { target: { value: '交易号' } })
    fireEvent.change(screen.getAllByLabelText('字段名称')[1], { target: { value: '统筹支付' } })
    const roles = screen.getAllByLabelText('字段角色')
    fireEvent.change(roles[0], { target: { value: 'identifier' } })
    fireEvent.submit(form)
    await waitFor(() => expect(createDataModel).toHaveBeenCalled())
    const payload = vi.mocked(createDataModel).mock.calls[0][0]
    expect(payload.model_code).toBe('dwd_mz_settlement')
    expect(payload.fields).toHaveLength(2)
  })
})
