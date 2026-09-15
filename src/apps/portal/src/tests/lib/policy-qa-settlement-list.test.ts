import { describe, expect, it } from 'vitest'

import {
  formatAmount,
  thisWeekRange,
  toDateInput,
  todayRange,
} from '@/lib/policy-qa-settlement-list'

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
