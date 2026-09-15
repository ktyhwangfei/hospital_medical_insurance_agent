import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import SettlementResultBlock from '@/components/policy-qa/settlement-result-block'
import type { PolicyQAResult } from '@/lib/policy-qa-stream'

afterEach(() => cleanup())

const result: PolicyQAResult = {
  answer: '本结算单费用构成为统筹支付 8,432.50 元、个人自付 2,953.90 元。',
  answerStatus: 'complete',
  calculationSteps: [{ stepName: '核对结算', description: '已核对金额。' }],
  definition: undefined,
  warnings: [],
  citations: [{ title: '住院待遇政策', excerpt: '统筹范围内按规定支付。' }],
  uncertainties: [],
  verificationSummary: {
    settlementChecked: true,
    calculationChecked: true,
    policyCount: 1,
    message: '已核对当前结算单与 1 条政策依据。',
  },
  settlementFields: [
    { fieldName: '统筹基金支付', value: 8432.5, state: 'non_zero' },
    { fieldName: '个人自付', value: 2953.9, state: 'non_zero' },
    { fieldName: '大额互助', value: 1000, state: 'non_zero' },
    { fieldName: '现金支付', value: 0, state: 'reported_zero' },
    { fieldName: '补充保险', value: null, state: 'missing' },
  ],
  caseContext: {
    totalAmount: 12386.4,
    queryScope: 'whole_admission',
    segmentCount: 1,
    matchedSegmentCount: 1,
    coverageStatus: 'complete',
  },
}

describe('SettlementResultBlock（单笔费用构成富块）', () => {
  it('总费用等宽大字 + 构成分段条 + 字段明细同时呈现', () => {
    render(<SettlementResultBlock settlementId="1671213" result={result} />)

    const block = screen.getByTestId('settlement-result-block')
    expect(block).toBeInTheDocument()
    expect(screen.getByText('结算单 1671213 · 费用构成')).toBeInTheDocument()
    // 总费用大字
    expect(screen.getByText('12,386.40')).toBeInTheDocument()
    // 单色分段条
    expect(screen.getByTestId('settlement-composition-bar')).toBeInTheDocument()
    // 字段明细：non_zero / reported_zero / missing 三种状态
    const list = screen.getByTestId('settlement-field-list')
    expect(list).toHaveTextContent('统筹基金支付')
    expect(list).toHaveTextContent('8,432.50 元')
    expect(list).toHaveTextContent('0.00 元')
    expect(list).toHaveTextContent('—')
    expect(list).toHaveTextContent('（缺失）')
  })

  it('解释文本、核验摘要与政策来源入口保留', () => {
    render(<SettlementResultBlock settlementId="1671213" result={result} />)

    expect(
      screen.getByText('本结算单费用构成为统筹支付 8,432.50 元、个人自付 2,953.90 元。'),
    ).toBeInTheDocument()
    expect(screen.getByText('已核对当前结算单与 1 条政策依据。')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: '查看 1 篇政策来源（1 条命中单元）' }),
    ).toBeInTheDocument()
  })

  it('分段条宽度按占比计算', () => {
    render(<SettlementResultBlock settlementId="1671213" result={result} />)

    const bar = screen.getByTestId('settlement-composition-bar')
    const segments = bar.querySelectorAll('span')
    // 三个 non_zero 字段进入分段条（8432.5 / 12386.4 ≈ 68.08%）
    expect(segments).toHaveLength(3)
    expect(segments[0]).toHaveStyle({ width: '68.08%' })
  })

  it('无总费用时不渲染分段条', () => {
    render(
      <SettlementResultBlock
        settlementId="X"
        result={{
          ...result,
          caseContext: { ...result.caseContext!, totalAmount: null },
        }}
      />,
    )
    expect(screen.queryByTestId('settlement-composition-bar')).not.toBeInTheDocument()
  })
})
