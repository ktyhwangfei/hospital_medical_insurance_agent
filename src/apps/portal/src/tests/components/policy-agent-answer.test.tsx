import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import PolicyAgentAnswer from '@/components/policy-qa/policy-agent-answer'
import type { PolicyQAChatMessage } from '@/lib/policy-qa-session'

afterEach(() => cleanup())

const completeMessage: PolicyQAChatMessage = {
  role: 'assistant',
  content: '本次统筹自付为 4,962.67 元。',
  answerStatus: 'complete',
  calculationSteps: [
    { stepName: '核对结算', description: '已核对统筹支付与个人支付金额。' },
  ],
  definition: {
    name: '统筹自付',
    plainText: '医保统筹范围内按政策由个人承担的金额。',
    excludes: ['目录外全自费费用'],
  },
  warnings: ['最终结算结果以医保系统为准。'],
  citations: [
    { title: '基本医疗保险住院待遇政策', excerpt: '参保人员按规定承担统筹范围内费用。' },
    { title: '住院费用结算说明', excerpt: '结算单分别列示统筹支付与个人支付。' },
  ],
  uncertainties: ['结算单未提供部分费用项目的逐项明细。'],
  verificationSummary: {
    settlementChecked: true,
    calculationChecked: true,
    policyCount: 2,
    message: '已核对当前结算单与 2 条政策依据。',
  },
}

describe('PolicyAgentAnswer', () => {
  it('renders one answer with progressive disclosure', () => {
    render(<PolicyAgentAnswer message={completeMessage} />)

    expect(screen.getByText('本次统筹自付为 4,962.67 元。')).toBeInTheDocument()
    expect(screen.getByText('已核对当前结算单与 2 条政策依据。')).toBeInTheDocument()
    expect(screen.queryByText('本轮执行链路')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '查看 2 条政策来源' })).toBeInTheDocument()
    expect(screen.getByText('计算依据')).toBeInTheDocument()
    expect(screen.getByText('计算依据').closest('details')).not.toHaveAttribute('open')
  })

  it('shows only policy title and excerpt in the sources dialog', () => {
    render(<PolicyAgentAnswer message={completeMessage} />)

    fireEvent.click(screen.getByRole('button', { name: '查看 2 条政策来源' }))

    expect(screen.getByText('基本医疗保险住院待遇政策')).toBeInTheDocument()
    expect(screen.getByText('参保人员按规定承担统筹范围内费用。')).toBeInTheDocument()
    expect(screen.queryByText(/yb_zyfdxx|sql_profile|结算数据来源/)).not.toBeInTheDocument()
  })

  it('renders uncertainties and sends the suggested follow-up', () => {
    const onFollowUp = vi.fn()
    render(<PolicyAgentAnswer message={completeMessage} onFollowUp={onFollowUp} />)

    expect(screen.getByText('结算单未提供部分费用项目的逐项明细。')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '请用更通俗的话解释' }))
    expect(onFollowUp).toHaveBeenCalledWith('请用更通俗的语言解释刚才的回答')
  })
})
