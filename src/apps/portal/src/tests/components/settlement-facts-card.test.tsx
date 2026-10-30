import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SettlementFactsCard from '@/components/policy-qa/settlement-facts-card'
import type { PolicyQASettlementFacts } from '@/lib/policy-qa-stream'

afterEach(cleanup)
const facts: PolicyQASettlementFacts = {
  chain: 'special', identifier: '609', tradeDate: null, medicalCategory: '12', insuranceType: '3', personType: '21', hospitalLevel: null,
  metadataNames: { medical_category: '门诊特殊病', insurance_type: '基本医疗保险', person_type: '退休' },
  items: [{ label: '总费用', value: '-100.00' }, { label: '起付', value: '0.00' }, { label: '公疗', value: null }],
  paymentItems: [{ label: '现金支付', value: '15.75' }],
}
describe('SettlementFactsCard', () => {
  it('一行中文摘要默认可见，展开后可追溯字段与原单金额', async () => {
    const user = userEvent.setup()
    render(<SettlementFactsCard facts={facts} identifier="609" />)
    const summary = screen.getByText('详细交易信息').closest('summary')!
    expect(summary).toBeVisible()
    expect(summary).toHaveTextContent('退休 · 基本医疗保险 · 门诊特殊病')
    expect(screen.getByText('门诊特殊病')).not.toBeVisible()
    await user.click(summary)
    expect(screen.getByText('门诊特殊病')).toBeVisible()
    expect(screen.getByText('基本医疗保险')).toBeVisible()
    expect(screen.getByText('退休')).toBeVisible()
    expect(screen.getByText('-100.00 元')).toBeInTheDocument()
    expect(screen.getByText('0.00 元')).toBeInTheDocument()
    expect(screen.getByText('-100.00 元').closest('details')).not.toHaveAttribute('open')
    await user.click(screen.getByText('原单全部金额与原始代码'))
    expect(screen.getByText('-100.00 元')).toBeVisible()
    expect(screen.getByText('0.00 元')).toBeVisible()
    expect(screen.queryByRole('tab')).toBeNull()
  })
  it('未知字典值诚实降级，不猜测中文', () => {
    render(<SettlementFactsCard facts={{ ...facts, metadataNames: {} }} identifier="609" />)
    expect(screen.getAllByText('中文含义未取得')).toHaveLength(3)
  })
  it('旧响应缺事实保留单号及降级说明', () => {
    render(<SettlementFactsCard identifier="609" />)
    expect(screen.getByText(/单号 609：本次响应未提供原单事实/)).toBeVisible()
  })
})
