import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import CitationCards from '@/components/policy-qa/citation-card'
import { groupCitationsByDocument } from '@/lib/policy-qa-citations'
import type { PolicyQAResult } from '@/lib/policy-qa-stream'

afterEach(() => cleanup())

const citations: PolicyQAResult['citations'] = [
  {
    title: '京医保发〔2024〕12号',
    excerpt: '门诊大额医疗互助费用由统筹基金按 80% 报销，年度封顶 10 万元。',
    docId: 'doc_7173172eb649',
  },
  {
    title: '京医保发〔2024〕12号',
    excerpt: '退休人员门诊起付标准为 1300 元。',
    docId: 'doc_7173172eb649',
  },
  { title: '国家医保目录说明', excerpt: '目录内药品按报销比例支付。' },
]

describe('groupCitationsByDocument（纯逻辑）', () => {
  it('同一文档命中多条合并为一个分组，无 docId 用标题兜底', () => {
    const groups = groupCitationsByDocument(citations)
    expect(groups).toHaveLength(2)
    expect(groups[0]).toMatchObject({ title: '京医保发〔2024〕12号', docId: 'doc_7173172eb649' })
    expect(groups[0].excerpts).toHaveLength(2)
    expect(groups[1].docId).toBeUndefined()
  })

  it('同 excerpt 去重', () => {
    const groups = groupCitationsByDocument([
      { title: 'A', excerpt: 'same' },
      { title: 'A', excerpt: 'same' },
    ])
    expect(groups[0].excerpts).toHaveLength(1)
  })

  it('空引用返回空数组', () => {
    expect(groupCitationsByDocument([])).toEqual([])
  })
})

describe('CitationCards（内联常显来源卡片）', () => {
  it('常显所有来源分组与原文链接，不做折叠按钮', () => {
    render(<CitationCards citations={citations} />)

    const section = screen.getByTestId('policy-qa-citation-cards')
    expect(section).toBeInTheDocument()
    // 同一文档标题只出现一次
    expect(screen.getAllByText('京医保发〔2024〕12号')).toHaveLength(1)
    expect(
      screen.getByText('门诊大额医疗互助费用由统筹基金按 80% 报销，年度封顶 10 万元。'),
    ).toBeInTheDocument()
    // 折叠对话框入口不应出现（常显是重点）
    expect(screen.queryByRole('button', { name: /查看.*政策来源/ })).not.toBeInTheDocument()
    const link = screen.getByRole('link', { name: '查看原文 →' })
    expect(link).toHaveAttribute('href', '/policy-document/doc_7173172eb649')
  })

  it('空引用不渲染', () => {
    const { container } = render(<CitationCards citations={[]} />)
    expect(container.firstElementChild).toBeNull()
  })
})
