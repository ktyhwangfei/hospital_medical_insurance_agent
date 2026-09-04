import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import OutpatientSelfTestPanel from '@/components/skills/outpatient-self-test-panel'
import {
  listSettlementSelfTests,
  importOutpatientEvalTasks,
  freezeSkillEvalDataset,
  runSettlementSelfTests,
  updateSettlementSelfTest,
} from '@/lib/api-client'
import type { SettlementSelfTestCase } from '@/lib/types'

vi.mock('@/lib/api-client', () => ({
  listSettlementSelfTests: vi.fn(),
  importOutpatientEvalTasks: vi.fn(),
  freezeSkillEvalDataset: vi.fn(),
  runSettlementSelfTests: vi.fn(),
  updateSettlementSelfTest: vi.fn(),
}))

const target: SettlementSelfTestCase = {
  case_id: 'person-21',
  settlement_id: '011100030X260417004975',
  expected_self_pay_one: '510.96',
  enabled: true,
  note: '补充保险样例',
  context: {
    insurance_type: '城镇职工',
    person_type: '退休',
    service_type: '普通门诊',
    in_scope_amount: '2554.76',
    fund_total_amount: '2427.02',
    self_pay_one: '510.96',
    supplementary_insurance_payment: '383.22',
    unit_supplement_payment: '255.47',
  },
}

describe('OutpatientSelfTestPanel', () => {
  beforeEach(() => {
    vi.mocked(listSettlementSelfTests).mockResolvedValue({ items: [target], total: 1, enabled: 1 })
    vi.mocked(importOutpatientEvalTasks).mockResolvedValue({ items: [], total: 28 })
    vi.mocked(freezeSkillEvalDataset).mockResolvedValue({
      dataset_version_id: 'EVD_1',
      task_snapshots: [],
    } as never)
    vi.mocked(runSettlementSelfTests).mockResolvedValue({
      total: 1,
      passed: 1,
      failed: 0,
      results: [{
        case_id: target.case_id,
        status: 'passed',
        actual_self_pay_one: '510.96',
        expected_self_pay_one: '510.96',
        message: '结算单个人自付一原值已正确保留。',
      }],
    })
    vi.mocked(updateSettlementSelfTest).mockImplementation(async (caseId, request) => ({
      case_id: caseId,
      ...request,
    }))
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('shows coverage, runs all cases, and saves an edited source amount', async () => {
    render(<OutpatientSelfTestPanel suiteId="EVS_mz" />)

    expect(await screen.findByText(target.settlement_id)).toBeInTheDocument()
    expect(screen.getByText('补充保险、公务员或公疗')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '导入 28 条任务' }))
    await waitFor(() => expect(importOutpatientEvalTasks).toHaveBeenCalledWith('EVS_mz'))
    fireEvent.click(screen.getByRole('button', { name: '冻结数据集' }))
    await waitFor(() => expect(freezeSkillEvalDataset).toHaveBeenCalledWith('EVS_mz'))

    fireEvent.click(screen.getByRole('button', { name: '运行固定样例' }))
    expect(await screen.findByText('1/1 通过，全部通过')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '编辑' }))
    fireEvent.change(screen.getByLabelText('预期个人自付一'), { target: { value: '511.00' } })
    fireEvent.click(screen.getByRole('button', { name: '保存样例' }))

    await waitFor(() => expect(updateSettlementSelfTest).toHaveBeenCalledWith(
      'person-21',
      expect.objectContaining({ expected_self_pay_one: '511.00' }),
    ))
  })
})
