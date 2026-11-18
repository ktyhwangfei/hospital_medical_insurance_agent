import { describe, expect, it } from 'vitest'

import { buildBillCompareMessage } from '@/lib/policy-qa-bill-compare'
import type {
  SettlementBillDTO,
  SettlementBillFeeItemDTO,
  SettlementListItemDTO,
} from '@/lib/policy-qa-settlement-list'

function item(partial: Partial<SettlementListItemDTO> & { settlementId: string }): SettlementListItemDTO {
  return {
    settlementDate: '2025-02-01 09:00:00',
    personType: '退休人员',
    insuranceType: '城镇职工',
    serviceType: '门诊特殊病',
    totalAmount: null,
    coverageStatus: 'complete',
    ...partial,
  }
}

const OLDER = item({ settlementId: '609', settlementDate: '2025-01-06 10:00:00' })
const NEWER = item({ settlementId: '814', settlementDate: '2025-02-10 10:00:00' })

function bill(
  settlementId: string,
  fields: Array<[string, string | null]>,
  feeItems: SettlementBillFeeItemDTO[] = [],
  feeItemsState: 'complete' | 'missing' = 'complete',
): SettlementBillDTO {
  return {
    settlementId,
    serviceType: '门诊特殊病',
    settlementDate: '2025-02-01',
    fields: fields.map(([label, amount]) => ({ key: label, label, amount })),
    feeItems,
    feeItemsState,
    warnings: [],
  }
}

const OLDER_BILL = bill(
  '609',
  [
    ['费用总金额', '2657.22'],
    ['个人支付总金额', '68.85'],
    ['起付金额', '1300.00'],
    ['统筹基金支付', '200.20'],
    ['当次门诊大额基金支付金额', '0.00'],
    ['残疾军人补助支付金额', '654.95'],
    ['单位补充医疗保险（原公疗）支付金额', '585.00'],
    ['大病支付', '0.00'],
    ['当次个人帐户支付金额', '0.00'],
    ['当次个人现金支付金额', '68.85'],
  ],
  [
    {
      itemCode: 'DRUG-TAC',
      itemName: '他克莫司胶囊',
      itemType: '药品',
      quantity: '10',
      unitPrice: '152.00',
      totalAmount: '1520.00',
      insuranceInner: '1520.00',
      insuranceOuter: '0.00',
    },
    {
      itemCode: 'DRUG-ONLY-OLD',
      itemName: '仅第一次出现',
      itemType: '药品',
      quantity: '1',
      unitPrice: '30.00',
      totalAmount: '30.00',
      insuranceInner: '30.00',
      insuranceOuter: '0.00',
    },
  ],
)

const NEWER_BILL = bill(
  '814',
  [
    ['费用总金额', '1932.12'],
    ['个人支付总金额', '15.75'],
    ['起付金额', '0.00'],
    ['统筹基金支付', '0.00'],
    ['当次门诊大额基金支付金额', '840.00'],
    ['残疾军人补助支付金额', '52.50'],
    ['单位补充医疗保险（原公疗）支付金额', '0.00'],
    ['大病支付', '23.62'],
    ['当次个人帐户支付金额', '0.00'],
    ['当次个人现金支付金额', '15.75'],
  ],
  [
    {
      itemCode: 'DRUG-TAC',
      itemName: '他克莫司胶囊',
      itemType: '药品',
      quantity: '25',
      unitPrice: '42.00',
      totalAmount: '1050.00',
      insuranceInner: '1050.00',
      insuranceOuter: '0.00',
    },
  ],
)

describe('buildBillCompareMessage（两单费用分解对比）', () => {
  it('逐单呈现个人支付与构成差异，不把两单金额混合成合计', () => {
    const message = buildBillCompareMessage({
      older: OLDER,
      newer: NEWER,
      olderBill: OLDER_BILL,
      newerBill: NEWER_BILL,
    })

    expect(message.role).toBe('assistant')
    expect(message.answerStatus).toBe('partial')
    // 基准 = 较早一张
    expect(message.content).toContain('以较早的结算单 609')
    expect(message.content).toContain('结算单 814')
    // 个人支付：两张单各自金额 + 差额
    expect(message.content).toContain('【个人支付】')
    expect(message.content).toContain('609：个人支付总金额 68.85 元')
    expect(message.content).toContain('814：个人支付总金额 15.75 元')
    expect(message.content).toContain('相差 53.10 元')
    // 构成差异逐字段呈现：旧值 → 新值，同向差额
    expect(message.content).toContain('起付金额：609 1,300.00 元 → 814 0.00 元')
    expect(message.content).toContain('残疾军人补助支付金额')
    // 不作合规判断、不提供加总结论
    expect(message.content).not.toContain('符合')
    expect(message.content).not.toContain('总共该付')
    expect(message.content).not.toContain('合计')
  })

  it('相同收费项目按编码匹配，指出单价/数量差异', () => {
    const message = buildBillCompareMessage({
      older: OLDER,
      newer: NEWER,
      olderBill: OLDER_BILL,
      newerBill: NEWER_BILL,
    })

    expect(message.content).toContain('【相同的收费项目】')
    expect(message.content).toContain('他克莫司胶囊：609 数量 10、单价 152.00 元、金额 1,520.00 元')
    expect(message.content).toContain('814 数量 25、单价 42.00 元、金额 1,050.00 元')
    expect(message.content).toContain('两次单价不同')
    expect(message.content).not.toContain('仅第一次出现')
  })

  it('政策依据缺失如实声明，不生成确定性的政策归因', () => {
    const message = buildBillCompareMessage({
      older: OLDER,
      newer: NEWER,
      olderBill: OLDER_BILL,
      newerBill: NEWER_BILL,
    })

    expect(message.content).toContain('未做政策归因')
    expect(message.uncertainties?.join('')).toContain('未检索到可展示的政策依据')
  })

  it('费用明细缺失时声明未做项目级对比', () => {
    const message = buildBillCompareMessage({
      older: OLDER,
      newer: NEWER,
      olderBill: { ...OLDER_BILL, feeItems: [], feeItemsState: 'missing' },
      newerBill: NEWER_BILL,
    })

    expect(message.content).not.toContain('【相同的收费项目】')
    expect(message.uncertainties?.join('')).toContain('609 的费用明细缺失')
  })
})
