import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { KnowledgeWorkbench } from '@/components/policy-knowledge/knowledge-workbench'
import type { WorkbenchDocument } from '@/lib/policy-knowledge-api'


const document: WorkbenchDocument = {
  doc_id: 'doc_1',
  doc_title: '职工医保政策',
  contract_version: '2',
  units: [
    {
      unit_id: 'unit_1', doc_id: 'doc_1', doc_title: '职工医保政策',
      path: ['第一条'], source_text: '在职职工住院政策原文', order_no: 1,
      status: 'reviewed', knowledge_count: 1,
      knowledge: [{
        knowledge_id: 'kn_1', unit_id: 'unit_1', extraction_id: 'ext_1',
        relationship_source: 'persisted',
        business_sentence: '在职职工住院时，统筹基金支付比例为80%。',
        source_text: '在职职工住院政策原文',
        fields: [{ field_code: 'payment_ratio', field_name: '支付比例', raw_value: '80%' }],
        standardized_fields: [{
          source_field: 'payment_ratio', source_value: { min: 0.8, max: 1 }, status: 'unmapped',
          metric_code: null, metric_name: null, value_domain: null,
          standard_value: null, binding_id: null,
        }],
        confidence: {
          completeness: 1, accuracy: null, source_fidelity: 1,
          model_confidence: 0.9, value_domain_compliance: null, overall: 0.96,
          uncertainties: ['准确性待经典用例验证'],
        },
        citations: [{ evidence: '第三条住院待遇', title: '职工医保政策原文' }],
      }],
    },
    {
      unit_id: 'unit_2', doc_id: 'doc_1', doc_title: '职工医保政策',
      path: ['第二条'], source_text: '退休职工原文', order_no: 2,
      status: 'published', knowledge_count: 0, knowledge: [],
    },
  ],
}


describe('KnowledgeWorkbench', () => {
  afterEach(cleanup)

  it('shows approved units, coherent knowledge, and standardized projection in three columns', () => {
    render(<KnowledgeWorkbench document={document} metrics={[]} onBindExisting={vi.fn()} onCreateMetricDrafts={vi.fn()} onProposeValue={vi.fn()} />)

    expect(screen.getByRole('heading', { name: '审核通过的单元' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '结构化知识' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '指标与值域标化' })).toBeInTheDocument()
    expect(screen.getByText('在职职工住院时，统筹基金支付比例为80%。')).toBeInTheDocument()
    expect(screen.getAllByText('待验证')).toHaveLength(2)
    expect(screen.getByText('未映射')).toBeInTheDocument()
    expect(screen.getByText('{"max":1,"min":0.8}')).toBeInTheDocument()
    expect(screen.getByText('模型置信')).toBeInTheDocument()
    expect(screen.getByText('值域合规')).toBeInTheDocument()
    expect(screen.getByText(/职工医保政策原文/)).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /第一条/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('option', { name: /知识 1/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('option', { name: /第一条/ }).id).toBe('policy-unit-unit_1')
    expect(screen.getByRole('option', { name: /知识 1/ }).id).toBe('policy-knowledge-kn_1')
  })

  it('requires a human click to create selected metric drafts', () => {
    const onCreate = vi.fn()
    render(<KnowledgeWorkbench document={document} metrics={[]} onBindExisting={vi.fn()} onCreateMetricDrafts={onCreate} onProposeValue={vi.fn()} />)

    fireEvent.click(screen.getByRole('checkbox', { name: '选择支付比例' }))
    fireEvent.click(screen.getByRole('button', { name: '批量生成指标草稿 (1)' }))

    expect(onCreate).toHaveBeenCalledWith([
      expect.objectContaining({ source_field: 'payment_ratio', knowledge_id: 'kn_1' }),
    ])
  })

  it('prefers binding an existing metric and advances through the mobile stages', () => {
    const onBind = vi.fn()
    render(<KnowledgeWorkbench document={document} metrics={[{ metric_code: 'zcgz.payment_ratio', name: '支付比例', object_code: 'zcgz', metric_type: 'Atomic', status: 'published' }]} onBindExisting={onBind} onCreateMetricDrafts={vi.fn()} onProposeValue={vi.fn()} />)

    expect(screen.getByRole('button', { name: '绑定已有指标' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('支付比例已有指标'), { target: { value: 'zcgz.payment_ratio' } })
    fireEvent.click(screen.getByRole('button', { name: '绑定已有指标' }))
    expect(onBind).toHaveBeenCalledWith(expect.objectContaining({ source_field: 'payment_ratio' }), 'zcgz.payment_ratio')

    expect(screen.getByRole('tab', { name: '单元阶段' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.click(screen.getByRole('option', { name: /第一条/ }))
    expect(screen.getByRole('tab', { name: '知识阶段' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.click(screen.getByRole('option', { name: /知识 1/ }))
    expect(screen.getByRole('tab', { name: '标准化阶段' })).toHaveAttribute('aria-selected', 'true')
  })
})
