// FeeDecompositionBlock 组件测试 — Issue #78 Phase 2 + 解释投影 1.1。
// 覆盖：undefined 不渲染、四状态徽标、稀疏字段（null 金额/缺 coverage）不崩；
// 1.1 展开渲染（brief、sum 算式含负号操作数、中间量标注、来源确认状态、缺口 message、
// 无效引用降级提示）；键整体缺失的稀疏夹具经 toFeeDecomposition 解析后渲染不崩。
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'

import FeeDecompositionBlock from '@/components/policy-qa/fee-decomposition-block'
import { toFeeDecomposition, type PolicyQAFeeDecomposition } from '@/lib/policy-qa-stream'

const BASE: PolicyQAFeeDecomposition = {
  schemaVersion: '1.0',
  algorithmVersion: 'fee-decomp-v1',
  executionStatus: 'complete',
  reconciliationStatus: 'matched',
  summaryText: '本笔门诊费用分解核对完成。',
  summarySource: 'template',
  mayClaimFullExplanation: true,
  fields: [
    {
      fieldCode: 'fund_pay',
      label: '统筹基金支付',
      checkType: 'independent_recalculation',
      checkStatus: 'matched',
      observedAmount: '113.66',
      calculatedAmount: '113.66',
      difference: '0.00',
      explanationLevel: 'causally_explained',
      reasonCode: null,
      calculationRefs: [],
      sourceRefs: [],
      gapRefs: [],
      brief: null,
    },
  ],
  uncertainties: [],
  coverage: {
    targetFieldCount: 4,
    independentlyExplainedCount: 3,
    amountReconciledCount: 1,
    observedOnlyCount: 0,
  },
  calculations: [],
  sources: [],
  conditions: [],
}

afterEach(cleanup)

describe('FeeDecompositionBlock', () => {
  it('工作台逐字段提供算法、中文公式和明细起点，未知金额不当成零', () => {
    const payload: PolicyQAFeeDecomposition = {
      ...BASE,
      algorithmVersion: 'employee_outpatient_v1',
      fields: [{ ...BASE.fields[0], fieldCode: 'T_SelfPayAll', label: '最终个人承担',
        observedAmount: null, calculatedAmount: null, checkStatus: 'not_verifiable' }],
    }
    render(<FeeDecompositionBlock feeDecomposition={payload} showAlgorithms />)
    const explanation = screen.getByTestId('fee-field-algorithm-T_SelfPayAll')
    expect(explanation.textContent).toContain('从费用明细开始')
    expect(explanation.textContent).toContain('最终个人承担＝')
    expect(explanation.textContent).toContain('本单尚不能独立核对')
    expect(explanation.textContent).not.toContain('最终个人承担 0')
    expect(screen.getByText('查看「最终个人承担」的算法与中文解释')).toBeInTheDocument()
  })

  it('未启用工作台算法展示时保留原展示，问答调用不自动增加新说明', () => {
    render(<FeeDecompositionBlock feeDecomposition={BASE} />)
    expect(screen.queryByTestId('fee-field-algorithm-fund_pay')).toBeNull()
    expect(screen.getByText('查看「统筹基金支付」的构成解释')).toBeInTheDocument()
  })

  it('feeDecomposition 为 undefined 时不渲染任何区块', () => {
    const { container } = render(<FeeDecompositionBlock feeDecomposition={undefined} />)
    expect(container.innerHTML).toBe('')
    expect(screen.queryByTestId('fee-decomposition-block')).toBeNull()
  })

  it('complete + matched：完整/账实相符徽标、字段表与 coverage 计数条', () => {
    render(<FeeDecompositionBlock feeDecomposition={BASE} />)
    const block = screen.getByTestId('fee-decomposition-block')
    expect(block.textContent).toContain('分解完整')
    expect(block.textContent).toContain('账实相符')
    expect(block.textContent).toContain('候选口径·待业务签核')
    expect(block.textContent).toContain('本笔门诊费用分解核对完成。')
    const fields = screen.getByTestId('fee-decomposition-fields')
    expect(fields.textContent).toContain('统筹基金支付')
    expect(fields.textContent).toContain('113.66')
    expect(fields.textContent).toContain('相符')
    expect(fields.textContent).toContain('因果解释')
    const coverage = screen.getByTestId('fee-decomposition-coverage')
    expect(coverage.textContent).toContain('目标字段 4')
    expect(coverage.textContent).toContain('因果解释 3')
  })

  it('partial：部分徽标', () => {
    render(
      <FeeDecompositionBlock feeDecomposition={{ ...BASE, executionStatus: 'partial' }} />,
    )
    expect(screen.getByTestId('fee-decomposition-block').textContent).toContain('分解部分')
  })

  it('unavailable：灰徽标 + uncertainties 列表', () => {
    render(
      <FeeDecompositionBlock
        feeDecomposition={{
          ...BASE,
          executionStatus: 'unavailable',
          reconciliationStatus: 'not_verifiable',
          fields: [],
          coverage: undefined,
          uncertainties: [
            {
              code: 'UNSUPPORTED_PROFILE',
              message: '该险种门诊费用分解暂未支持',
              id: '',
              affectedFields: [],
            },
          ],
        }}
      />,
    )
    const block = screen.getByTestId('fee-decomposition-block')
    expect(block.textContent).toContain('分解不可用')
    expect(block.textContent).toContain('无法核对')
    const uncertainties = screen.getByTestId('fee-decomposition-uncertainties')
    expect(uncertainties.textContent).toContain('UNSUPPORTED_PROFILE')
    expect(uncertainties.textContent).toContain('该险种门诊费用分解暂未支持')
    expect(screen.queryByTestId('fee-decomposition-coverage')).toBeNull()
  })

  it('mismatched：字段行与头部均为不符徽标', () => {
    render(
      <FeeDecompositionBlock
        feeDecomposition={{
          ...BASE,
          reconciliationStatus: 'mismatched',
          fields: [{ ...BASE.fields[0]!, checkStatus: 'mismatched', difference: '2.50' }],
        }}
      />,
    )
    const block = screen.getByTestId('fee-decomposition-block')
    expect(block.textContent).toContain('账实不符')
    expect(block.textContent).toContain('不符')
    expect(block.textContent).toContain('2.50')
  })

  it('稀疏字段：金额键缺失（null）渲染为 —，缺 coverage 不崩', () => {
    render(
      <FeeDecompositionBlock
        feeDecomposition={{
          ...BASE,
          coverage: undefined,
          fields: [
            {
              fieldCode: 'civil_aid',
              label: '医疗救助',
              checkType: 'identity_check',
              checkStatus: 'not_applicable',
              observedAmount: null,
              calculatedAmount: null,
              difference: null,
              explanationLevel: 'observed_only',
              reasonCode: null,
              calculationRefs: [],
              sourceRefs: [],
              gapRefs: [],
              brief: null,
            },
          ],
        }}
      />,
    )
    const fields = screen.getByTestId('fee-decomposition-fields')
    expect(fields.textContent).toContain('医疗救助')
    expect(fields.textContent).toContain('—')
    expect(fields.textContent).toContain('不适用')
    expect(fields.textContent).toContain('仅账面')
    expect(screen.queryByTestId('fee-decomposition-coverage')).toBeNull()
  })
})

// ── 解释投影 1.1：字段行展开五层解释 ──

const FULL_11: PolicyQAFeeDecomposition = {
  ...BASE,
  schemaVersion: '1.1',
  algorithmVersion: 'fee-decomp-v2',
  fields: [
    {
      fieldCode: 'fund_pay',
      label: '统筹基金支付',
      checkType: 'independent_recalculation',
      checkStatus: 'matched',
      observedAmount: '113.66',
      calculatedAmount: '113.66',
      difference: '0.00',
      explanationLevel: 'causally_explained',
      reasonCode: null,
      calculationRefs: ['calc-fund'],
      sourceRefs: ['src-settle'],
      gapRefs: ['gap-1'],
      brief: '统筹基金支付由甲类统筹与乙类统筹相加构成。',
    },
  ],
  uncertainties: [
    {
      code: 'CIVIL_CAP_PRIOR_UNVERIFIABLE',
      message: '交易前累计无法独立核实',
      id: 'gap-1',
      affectedFields: ['fund_pay'],
    },
  ],
  calculations: [
    {
      calculationId: 'calc-fund',
      displayName: '统筹基金支付',
      formulaId: 'F-FUND-01',
      formulaVersion: '1.0',
      layout: 'sum',
      operands: [
        { displayName: '甲类统筹', value: '127.32', isIntermediate: false },
        { displayName: '起付线扣减', value: '-13.66', isIntermediate: true },
      ],
      unroundedResult: '113.66',
      roundingRule: '四舍五入到分',
      result: '113.66',
    },
  ],
  sources: [
    {
      refId: 'src-settle',
      title: '门诊结算单',
      category: 'settlement_record',
      confirmationStatus: '已与结算单核对一致',
      value: '统筹基金支付 113.66 元',
      values: [],
      link: 'https://example.com/policy/fund',
    },
  ],
  conditions: [
    {
      stepId: 'cond-deductible',
      moduleLabel: '起付线模块',
      description: '累计费用已超过起付线，超出部分进入统筹',
      actualDisplay: '累计 500.00 元',
      expectedDisplay: '起付线 300.00 元',
      outcome: 'pass',
      calculationRefs: ['calc-fund'],
    },
  ],
}

describe('FeeDecompositionBlock 解释投影 1.1 展开', () => {
  it('工作台按算法译文解释分配，原始输入不机械拼成加乘公式', () => {
    const payload: PolicyQAFeeDecomposition = {
      ...FULL_11,
      algorithmVersion: 'employee_outpatient_special_v1',
      fields: [{ ...FULL_11.fields[0], fieldCode: 'FEEIN_DB_PAY',
        label: '医保内个人自付一的大病支付', brief: '旧摘要：50 × 100 × 60' }],
      calculations: [{ ...FULL_11.calculations[0], layout: 'product', operands: [
        { displayName: '自付一', value: '50', isIntermediate: false },
        { displayName: '合规基数', value: '100', isIntermediate: false },
        { displayName: '分段支付', value: '60', isIntermediate: false },
      ] }],
    }
    render(<FeeDecompositionBlock feeDecomposition={payload} showAlgorithms />)
    expect(screen.getByTestId('fee-field-algorithm-FEEIN_DB_PAY').textContent).toContain('÷本笔大病合规费用基数')
    expect(screen.queryByText('旧摘要：50 × 100 × 60')).toBeNull()
    const inputs = screen.getByTestId('fee-calc-calc-fund')
    expect(inputs.textContent).toContain('计算记录结果')
    expect(inputs.textContent).not.toContain(' × ')
  })

  it('每行渲染原生 details/summary 展开入口，summary 有明确名称', () => {
    render(<FeeDecompositionBlock feeDecomposition={FULL_11} />)
    const detail = screen.getByTestId('fee-field-detail-fund_pay')
    expect(detail.tagName).toBe('DETAILS')
    const summary = detail.querySelector('summary')
    expect(summary?.textContent).toContain('统筹基金支付')
  })

  it('怎么来：brief 先行，sum 算式含负号操作数与中间量标注、取整说明', () => {
    render(<FeeDecompositionBlock feeDecomposition={FULL_11} />)
    const calc = screen.getByTestId('fee-calc-calc-fund')
    const detail = screen.getByTestId('fee-field-detail-fund_pay')
    expect(detail.textContent).toContain('统筹基金支付由甲类统筹与乙类统筹相加构成。')
    expect(calc.textContent).toContain(
      '统筹基金支付 113.66 元 ＝ 甲类统筹 127.32 元 － 起付线扣减 13.66 元（计算中间量）',
    )
    expect(calc.textContent).toContain('取整：四舍五入到分')
  })

  it('怎么来：subtract_rest 布局首项减其余，减号由布局给出（操作数无符号存储）', () => {
    const payload = {
      ...FULL_11,
      fields: [
        {
          ...FULL_11.fields[0],
          fieldCode: 'self_pay',
          label: '大额自付',
          calculationRefs: ['calc-self'],
          sourceRefs: [],
          gapRefs: [],
          brief: null,
        },
      ],
      calculations: [
        {
          calculationId: 'calc-self',
          displayName: '大额自付（差额）',
          formulaId: 'F-SELF-01',
          formulaVersion: '1.0',
          layout: 'subtract_rest' as const,
          operands: [
            { displayName: '共付段基数', value: '500.00', isIntermediate: true },
            { displayName: '大额支付', value: '60.00', isIntermediate: false },
          ],
          unroundedResult: '440.00',
          roundingRule: null,
          result: '440.00',
        },
      ],
      conditions: [],
    }
    render(<FeeDecompositionBlock feeDecomposition={payload} />)
    const calc = screen.getByTestId('fee-calc-calc-self')
    expect(calc.textContent).toContain(
      '大额自付（差额） 440.00 元 ＝ 共付段基数 500.00 元（计算中间量） － 大额支付 60.00 元',
    )
    expect(calc.textContent).not.toContain('＋')
  })

  it('是什么：explanation_level 原样状态码展示', () => {
    render(<FeeDecompositionBlock feeDecomposition={FULL_11} />)
    const detail = screen.getByTestId('fee-field-detail-fund_pay')
    expect(detail.textContent).toContain('是什么')
    expect(detail.textContent).toContain('causally_explained')
  })

  it('为什么这样算：与本字段计算有交集的条件展示 module_label/实际/期望/结果', () => {
    render(<FeeDecompositionBlock feeDecomposition={FULL_11} />)
    const condition = screen.getByTestId('fee-condition-cond-deductible')
    expect(condition.textContent).toContain('起付线模块')
    expect(condition.textContent).toContain('累计费用已超过起付线，超出部分进入统筹')
    expect(condition.textContent).toContain('实际 累计 500.00 元')
    expect(condition.textContent).toContain('期望 起付线 300.00 元')
    expect(condition.textContent).toContain('结果：pass')
  })

  it('依据在哪里：来源 title + 确认状态 + value，link 渲染为新窗口外链', () => {
    render(<FeeDecompositionBlock feeDecomposition={FULL_11} />)
    const source = screen.getByTestId('fee-source-src-settle')
    expect(source.textContent).toContain('门诊结算单')
    expect(source.textContent).toContain('已与结算单核对一致')
    expect(source.textContent).toContain('统筹基金支付 113.66 元')
    const link = source.querySelector('a')
    expect(link?.getAttribute('href')).toBe('https://example.com/policy/fund')
    expect(link?.getAttribute('target')).toBe('_blank')
    expect(link?.getAttribute('rel')).toBe('noreferrer')
  })

  it('解释到哪里：gap_refs 指向的缺口 message', () => {
    render(<FeeDecompositionBlock feeDecomposition={FULL_11} />)
    const detail = screen.getByTestId('fee-field-detail-fund_pay')
    expect(detail.textContent).toContain('解释到哪里')
    expect(detail.textContent).toContain('交易前累计无法独立核实')
  })

  it('无效引用降级：悬空 calculation/source/gap id 显示降级提示，行与金额照常显示', () => {
    render(
      <FeeDecompositionBlock
        feeDecomposition={{
          ...FULL_11,
          fields: [
            {
              ...FULL_11.fields[0]!,
              calculationRefs: ['calc-missing'],
              sourceRefs: ['src-missing'],
              gapRefs: ['gap-missing'],
            },
          ],
        }}
      />,
    )
    const detail = screen.getByTestId('fee-field-detail-fund_pay')
    expect(detail.textContent).toContain('未记录本步计算')
    expect(detail.textContent).toContain('依据尚未关联')
    const fields = screen.getByTestId('fee-decomposition-fields')
    expect(fields.textContent).toContain('统筹基金支付')
    expect(fields.textContent).toContain('113.66')
  })

  it('link 为 null 时不渲染链接', () => {
    render(
      <FeeDecompositionBlock
        feeDecomposition={{
          ...FULL_11,
          sources: [{ ...FULL_11.sources[0]!, link: null }],
        }}
      />,
    )
    const source = screen.getByTestId('fee-source-src-settle')
    expect(source.querySelector('a')).toBeNull()
  })

  it('键整体缺失的 1.0 稀疏夹具：经 toFeeDecomposition 解析后渲染不崩，展开仅「是什么」层', () => {
    const parsed = toFeeDecomposition({
      execution_status: 'complete',
      reconciliation_status: 'matched',
      fields: [
        {
          field_code: 'fund_pay',
          label: '统筹基金支付',
          check_status: 'matched',
          observed_amount: '113.66',
          // calculated_amount / difference / explanation_level / 1.1 新键整体缺失
        },
      ],
      // calculations / sources / conditions / uncertainties 键整体缺失
    })
    expect(parsed).toBeDefined()
    render(<FeeDecompositionBlock feeDecomposition={parsed} />)
    const detail = screen.getByTestId('fee-field-detail-fund_pay')
    expect(detail.textContent).toContain('是什么')
    expect(detail.textContent).not.toContain('怎么来')
    expect(detail.textContent).not.toContain('依据在哪里')
    expect(screen.getByTestId('fee-decomposition-fields').textContent).toContain('113.66')
  })
})
