import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  fetchSettlementBill,
  formatAmount,
  thisWeekRange,
  toDateInput,
  todayRange,
} from '@/lib/policy-qa-settlement-list'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('policy-qa-settlement-list 时段与格式化（纯逻辑）', () => {
  it('toDateInput 输出本地 YYYY-MM-DD', () => {
    expect(toDateInput(new Date(2026, 8, 14, 10, 30))).toBe('2026-09-14')
    expect(toDateInput(new Date(2026, 0, 5))).toBe('2026-01-05')
  })

  it('todayRange 返回同一天区间', () => {
    expect(todayRange(new Date(2026, 8, 14, 15, 0))).toEqual({
      dateFrom: '2026-09-14',
      dateTo: '2026-09-14',
    })
  })

  it('thisWeekRange 周起始（周一 00:00 周一 → 当天）', () => {
    const monday = new Date(2026, 8, 14, 10, 0)
    expect(thisWeekRange(monday)).toEqual({ dateFrom: '2026-09-14', dateTo: '2026-09-14' })
  })

  it('thisWeekRange 周日回溯到上周一', () => {
    const sunday = new Date(2026, 8, 20, 10, 0)
    expect(thisWeekRange(sunday)).toEqual({ dateFrom: '2026-09-14', dateTo: '2026-09-20' })
  })

  it('thisWeekRange 周三回溯到本周一', () => {
    const wednesday = new Date(2026, 8, 16, 10, 0)
    expect(thisWeekRange(wednesday)).toEqual({ dateFrom: '2026-09-14', dateTo: '2026-09-16' })
  })

  it('formatAmount 千分位两位小数；null 显示 —', () => {
    expect(formatAmount(12386.4)).toBe('12,386.40')
    expect(formatAmount(0)).toBe('0.00')
    expect(formatAmount(null)).toBe('—')
  })
})

describe('fetchSettlementBill', () => {
  it('转换费用构成与费用明细，并透传 service_type', async () => {
    const fetchMock = vi.fn(async (_input: string | URL | RequestInfo) =>
      ({
        ok: true,
        status: 200,
        json: async () => ({
          settlement_id: 'OUTP-1',
          service_type: '门诊',
          settlement_date: '2026-04-17 09:12:00',
          fields: [{ key: 'T_FeeAll', label: '费用总金额', amount: '88.50' }],
          fee_items: [
            {
              item_code: '310100001',
              item_name: '负压吸引（中心泵）',
              item_type: '诊疗项目',
              quantity: '1',
              unit_price: '6.00',
              total_amount: '6.00',
              insurance_inner: '6.00',
              insurance_outer: '0.00',
            },
          ],
          fee_items_state: 'complete',
          warnings: [],
        }),
      }) as Response,
    )
    vi.stubGlobal('fetch', fetchMock)

    const bill = await fetchSettlementBill('OUTP-1', '门诊')

    expect(bill.fields[0]).toEqual({
      key: 'T_FeeAll',
      label: '费用总金额',
      amount: '88.50',
    })
    expect(bill.feeItems[0].itemName).toBe('负压吸引（中心泵）')
    expect(bill.feeItems[0].insuranceOuter).toBe('0.00')
    expect(bill.feeItemsState).toBe('complete')
    const url = String(fetchMock.mock.calls[0][0])
    expect(url).toContain('/policy-qa/settlements/OUTP-1/bill')
    expect(url).toContain(`service_type=${encodeURIComponent('门诊')}`)
  })

  it('404 转为可展示的诚实提示', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) }) as Response),
    )

    await expect(fetchSettlementBill('NOPE')).rejects.toThrow('未找到该结算单的费用数据')
  })
})
