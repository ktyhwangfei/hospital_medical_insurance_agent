import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import MetricSuggestionPanel from '@/components/policy-qa/metric-suggestion-panel'
import OpsAnswerBlock from '@/components/policy-qa/ops-answer-block'
import type { PolicyQADataQueryResult } from '@/lib/policy-qa-session'

afterEach(() => cleanup())

const screeningResult: PolicyQADataQueryResult = {
  metricId: 'screening.top',
  metricName: '金额最高的疑点',
  summary: '全量 1 条，100.00 元。',
  caliber: '最新成功执行批次；只含明显对不上；主疑点去重。',
  table: {
    columns: [
      { key: 'finding_no', title: '疑点编号' },
      { key: 'settlement_no', title: '结算单号' },
      { key: 'amount', title: '金额（元）' },
    ],
    rows: [{ finding_no: 'F1', settlement_no: 'T001', amount: 100 }],
  },
}

describe('运营问数筛查入口', () => {
  it('空状态给出筛查问法，没有规则管理动作', () => {
    render(<MetricSuggestionPanel onSelectQuestion={() => undefined} />)

    expect(screen.getByRole('button', { name: '本月待核实疑点有多少条，涉及金额多少？' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '材料不足的有哪些？' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /上传|批准|关闭规则/ })).not.toBeInTheDocument()
  })

  it('名单可以下钻和记核实结论，不能改规则', async () => {
    const onFollowUp = vi.fn()
    const user = userEvent.setup()
    render(<OpsAnswerBlock result={screeningResult} onFollowUp={onFollowUp} />)

    expect(screen.getByText(/只含明显对不上/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '查看依据' }))
    await user.click(screen.getByRole('button', { name: '标为跟' }))
    expect(onFollowUp).toHaveBeenNthCalledWith(1, '打开结算单 T001，看看依据是什么')
    expect(onFollowUp).toHaveBeenNthCalledWith(2, '把疑点 F1 标为跟')
    expect(screen.queryByRole('button', { name: /上传|批准|关闭规则/ })).not.toBeInTheDocument()
  })
})
