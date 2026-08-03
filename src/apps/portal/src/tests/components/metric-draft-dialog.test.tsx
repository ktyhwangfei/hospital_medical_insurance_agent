import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { MetricDraftDialog } from '@/components/policy-knowledge/metric-draft-dialog'

vi.mock('@/lib/policy-knowledge-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/policy-knowledge-api')>()
  return { ...actual, createMetricDraft: vi.fn().mockResolvedValue({}) }
})

describe('MetricDraftDialog', () => {
  afterEach(cleanup)

  it('lets reviewers confirm semantic type, unit, and value domain without fixed Amount defaults', async () => {
    const { createMetricDraft } = await import('@/lib/policy-knowledge-api')
    render(<MetricDraftDialog sources={[{
      doc_id: 'doc_1', unit_id: 'unit_1', knowledge_id: 'kn_1', source_field: 'payment_ratio',
      field_name: '支付比例', source_value: '80%', source_text: '原文', contract_version: '2',
    }]} onClose={vi.fn()} onCreated={vi.fn()} />)

    expect(screen.getByLabelText('支付比例语义类型')).toHaveValue('Ratio')
    fireEvent.change(screen.getByLabelText('支付比例单位'), { target: { value: '%' } })
    fireEvent.change(screen.getByLabelText('支付比例值域'), { target: { value: 'PAYMENT_RATIO' } })
    fireEvent.click(screen.getByRole('button', { name: '确认生成 1 个草稿' }))

    await waitFor(() => expect(createMetricDraft).toHaveBeenCalledWith(
      expect.anything(), expect.any(String), '支付比例',
      expect.objectContaining({ semanticType: 'Ratio', unit: '%', valueDomain: 'PAYMENT_RATIO' }),
    ))
  })
})
