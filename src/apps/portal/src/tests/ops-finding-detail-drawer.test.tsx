// 问题详情抽屉测试 — #50（证据快照 / 忽略与重开流转 / 时间线 / 冲突错误）
// + #53（白名单执行修复 / 修复留痕时间线 / 非白名单负例）。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/ops',
}))

vi.mock('@/lib/ops-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/ops-api')>()
  return {
    ...actual,
    getOpsFinding: vi.fn(),
    ignoreOpsFinding: vi.fn(),
    reopenOpsFinding: vi.fn(),
    listOpsRemediationActions: vi.fn(),
    remediateOpsFinding: vi.fn(),
    diagnoseOpsFinding: vi.fn(),
  }
})

import FindingDetailDrawer from '../../app/ops/finding-detail-drawer'
import {
  diagnoseOpsFinding,
  getOpsFinding,
  ignoreOpsFinding,
  listOpsRemediationActions,
  remediateOpsFinding,
  reopenOpsFinding,
  type OpsDiagnosisReportDto,
  type OpsDiagnosisResultDto,
  type OpsFindingDetailDto,
  type OpsFindingDto,
  type OpsFindingEventDto,
  type OpsRemediationActionDto,
  type OpsRemediationResultDto,
  type OpsRemediationRunDto,
} from '@/lib/ops-api'
import { ApiClientError } from '@/lib/types'

const ACTIONS: OpsRemediationActionDto[] = [
  {
    action: 'retry_data_sync',
    check_id: 'data_sync_failed',
    risk_level: 'L1',
    description: '重试失败/滞后的门诊同步任务（复用 data_governance 同步入口）',
  },
]

function finding(overrides: Partial<OpsFindingDto> = {}): OpsFindingDto {
  return {
    finding_id: 'f1',
    asset_type: 'data',
    asset_id: 'bjybdb',
    check_id: 'data_sync_failed',
    severity: 'warning',
    status: 'open',
    fingerprint: 'data:bjybdb:data_sync_failed',
    payload: {
      problem: 'sync_job_degraded',
      last_error_code: 'SOURCE_TIMEOUT',
      safe_probe_message: '连接超时',
      last_probed_at: '2026-09-09T04:10:00+00:00',
    },
    first_seen_at: '2026-09-09T04:00:00+00:00',
    last_seen_at: '2026-09-09T04:10:00+00:00',
    occurrence_count: 3,
    diagnosis: null,
    revision: 3,
    ...overrides,
  }
}

function event(overrides: Partial<OpsFindingEventDto> = {}): OpsFindingEventDto {
  return {
    event_id: 'e1',
    finding_id: 'f1',
    event_type: 'ignored',
    actor: 'portal-dev-ops',
    reason: 'DBA 排期维护',
    created_at: '2026-09-09T04:05:00+00:00',
    ...overrides,
  }
}

function run(overrides: Partial<OpsRemediationRunDto> = {}): OpsRemediationRunDto {
  return {
    run_id: 'r1',
    finding_id: 'f1',
    action: 'retry_data_sync',
    risk_level: 'L1',
    status: 'succeeded',
    before_evidence: { job_status: 'failed' },
    after_evidence: { job_status: 'running' },
    verification_result: 'passed',
    created_by: 'portal-dev-ops',
    created_at: '2026-09-09T04:06:00+00:00',
    ...overrides,
  }
}

function detail(overrides: Partial<OpsFindingDetailDto> = {}): OpsFindingDetailDto {
  return { finding: finding(), events: [], remediations: [], ...overrides }
}

function renderDrawer(findingId: string | null = 'f1', canWrite = true) {
  const onClose = vi.fn()
  const onMutated = vi.fn()
  render(
    <FindingDetailDrawer findingId={findingId} canWrite={canWrite} onClose={onClose} onMutated={onMutated} />,
  )
  return { onClose, onMutated }
}

describe('FindingDetailDrawer 详情抽屉', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getOpsFinding).mockResolvedValue(detail())
    vi.mocked(listOpsRemediationActions).mockResolvedValue(ACTIONS)
  })
  afterEach(() => cleanup())

  it('渲染证据快照、诊断占位与基础时间线', async () => {
    renderDrawer()
    await waitFor(() => expect(screen.getByTestId('ops-detail-drawer')).toBeTruthy())
    // 证据快照：已知键显示中文标签，问题码带翻译
    expect(screen.getByText('问题码')).toBeTruthy()
    expect(screen.getByText('同步任务降级（sync_job_degraded）')).toBeTruthy()
    expect(screen.getByText('错误码')).toBeTruthy()
    expect(screen.getByText('SOURCE_TIMEOUT')).toBeTruthy()
    expect(screen.getByText('连接探测')).toBeTruthy()
    // 诊断占位
    expect(screen.getByTestId('ops-diagnosis-empty').textContent).toContain('诊断报告未生成')
    // 时间线：首见 + 最近巡检确认（无流转事件）；「首次发现」在基础信息区也出现，用 getAll
    expect(screen.getAllByText('首次发现').length).toBeGreaterThan(0)
    expect(screen.getByText('最近巡检确认')).toBeTruthy()
    expect(screen.getByText('3 次')).toBeTruthy()
  })

  it('忽略流程：必填原因校验、提交带乐观锁版本、成功后回填详情并通知列表', async () => {
    const ignoredDetail = detail({
      finding: finding({ status: 'ignored', revision: 4 }),
      events: [event()],
    })
    vi.mocked(ignoreOpsFinding).mockResolvedValue(ignoredDetail)
    const { onMutated } = renderDrawer()
    await waitFor(() => expect(screen.getByTestId('ops-detail-ignore')).toBeTruthy())

    fireEvent.click(screen.getByTestId('ops-detail-ignore'))
    expect(screen.getByTestId('ops-detail-ignore-form')).toBeTruthy()
    // 空原因禁用确认
    expect(screen.getByTestId('ops-detail-ignore-confirm')).toHaveProperty('disabled', true)

    fireEvent.change(screen.getByTestId('ops-detail-ignore-reason'), {
      target: { value: 'DBA 排期维护' },
    })
    fireEvent.click(screen.getByTestId('ops-detail-ignore-confirm'))
    await waitFor(() =>
      expect(ignoreOpsFinding).toHaveBeenCalledWith('f1', 3, 'DBA 排期维护'),
    )
    // 详情以响应回填：状态徽标已忽略、重开按钮出现、时间线含忽略事件与原因
    await waitFor(() => expect(screen.getByTestId('ops-detail-reopen')).toBeTruthy())
    expect(screen.getByText('已忽略')).toBeTruthy()
    expect(screen.getByText(/由 portal-dev-ops 忽略/)).toBeTruthy()
    expect(screen.getByText(/原因：DBA 排期维护/)).toBeTruthy()
    expect(onMutated).toHaveBeenCalledTimes(1)
  })

  it('重开流程：对已忽略问题重开成功后回到开放状态', async () => {
    vi.mocked(getOpsFinding).mockResolvedValue(
      detail({ finding: finding({ status: 'ignored', revision: 4 }), events: [event()] }),
    )
    vi.mocked(reopenOpsFinding).mockResolvedValue(detail({ finding: finding({ revision: 5 }) }))
    const { onMutated } = renderDrawer()
    await waitFor(() => expect(screen.getByTestId('ops-detail-reopen')).toBeTruthy())

    fireEvent.click(screen.getByTestId('ops-detail-reopen'))
    await waitFor(() => expect(reopenOpsFinding).toHaveBeenCalledWith('f1', 4))
    await waitFor(() => expect(screen.getByTestId('ops-detail-ignore')).toBeTruthy())
    expect(screen.getByText('开放')).toBeTruthy()
    expect(onMutated).toHaveBeenCalledTimes(1)
  })

  it('版本冲突（409）时展示错误条且状态不变', async () => {
    vi.mocked(ignoreOpsFinding).mockRejectedValue(new ApiClientError(409, {
      error_code: 'FINDING_REVISION_CONFLICT',
      message: '问题 f1 版本冲突：期望 revision 3，实际 4',
    }))
    renderDrawer()
    await waitFor(() => expect(screen.getByTestId('ops-detail-ignore')).toBeTruthy())

    fireEvent.click(screen.getByTestId('ops-detail-ignore'))
    fireEvent.change(screen.getByTestId('ops-detail-ignore-reason'), {
      target: { value: '尝试忽略' },
    })
    fireEvent.click(screen.getByTestId('ops-detail-ignore-confirm'))
    await waitFor(() => expect(screen.getByTestId('ops-detail-action-error')).toBeTruthy())
    expect(screen.getByTestId('ops-detail-action-error').textContent).toContain('FINDING_REVISION_CONFLICT')
    // 仍处于开放态，可再次展开忽略表单
    expect(screen.getByText('开放')).toBeTruthy()
  })

  it('详情加载失败展示错误信息', async () => {
    vi.mocked(getOpsFinding).mockRejectedValue(new Error('无法连接健康运营服务'))
    renderDrawer()
    await waitFor(() => expect(screen.getByTestId('ops-detail-error')).toBeTruthy())
    expect(screen.getByTestId('ops-detail-error').textContent).toContain('无法连接健康运营服务')
  })

  it('findingId 为空时不渲染抽屉', () => {
    renderDrawer(null)
    expect(screen.queryByTestId('ops-detail-overlay')).toBeNull()
  })

  it('无写权限时不渲染状态操作', async () => {
    renderDrawer('f1', false)
    await waitFor(() => expect(screen.getByTestId('ops-detail-drawer')).toBeTruthy())
    expect(screen.queryByTestId('ops-detail-ignore')).toBeNull()
  })

  // ── #53 L1 自动修复 ──

  it('白名单检查项展示执行修复：提交带乐观锁版本，成功后回填已解决与修复留痕', async () => {
    const resolvedRun = run()
    const remediatedDetail = detail({
      finding: finding({ status: 'resolved', revision: 4 }),
      events: [{
        ...event(),
        event_type: 'resolved',
        reason: 'L1 修复动作 retry_data_sync 验证通过',
        created_at: '2026-09-09T04:06:00+00:00',
      }],
      remediations: [resolvedRun],
    })
    const result: OpsRemediationResultDto = { run: resolvedRun, detail: remediatedDetail }
    vi.mocked(remediateOpsFinding).mockResolvedValue(result)
    const { onMutated } = renderDrawer()
    await waitFor(() => expect(screen.getByTestId('ops-detail-remediate')).toBeTruthy())
    expect(screen.getByTestId('ops-detail-remediate').textContent).toContain('重试门诊同步')

    fireEvent.click(screen.getByTestId('ops-detail-remediate'))
    await waitFor(() => expect(remediateOpsFinding).toHaveBeenCalledWith('f1', 3))
    // 回填：已解决徽标、resolved 事件与修复留痕进入时间线，通知列表刷新
    await waitFor(() => expect(screen.getByText('已解决')).toBeTruthy())
    expect(screen.getByText(/由 portal-dev-ops 解决/)).toBeTruthy()
    expect(screen.getByText(/由 portal-dev-ops 执行修复（重试门诊同步）/)).toBeTruthy()
    expect(screen.getByText(/已执行 · 验证通过/)).toBeTruthy()
    expect(onMutated).toHaveBeenCalledTimes(1)
  })

  it('修复执行未发起（动作失败）时留痕展示原因且问题保持开放', async () => {
    const failedRun = run({
      status: 'failed',
      after_evidence: { error: '任务处于 paused 状态，不自动重试' },
      verification_result: null,
      created_at: '2026-09-09T04:06:00+00:00',
    })
    const result: OpsRemediationResultDto = {
      run: failedRun,
      detail: detail({ remediations: [failedRun] }),
    }
    vi.mocked(remediateOpsFinding).mockResolvedValue(result)
    renderDrawer()
    await waitFor(() => expect(screen.getByTestId('ops-detail-remediate')).toBeTruthy())

    fireEvent.click(screen.getByTestId('ops-detail-remediate'))
    await waitFor(() =>
      expect(screen.getByText(/未发起 · 未验证 · 原因：任务处于 paused 状态，不自动重试/)).toBeTruthy(),
    )
    expect(screen.getByText('开放')).toBeTruthy()  // 状态不动
  })

  it('非白名单检查项（data_source_down）不渲染执行修复入口', async () => {
    vi.mocked(getOpsFinding).mockResolvedValue(
      detail({ finding: finding({ check_id: 'data_source_down', severity: 'critical' }) }),
    )
    renderDrawer()
    await waitFor(() => expect(screen.getByTestId('ops-detail-ignore')).toBeTruthy())
    expect(screen.queryByTestId('ops-detail-remediate')).toBeNull()
    expect(screen.queryByTestId('ops-detail-remediate-block')).toBeNull()
  })

  it('修复版本冲突（409）时展示错误条', async () => {
    vi.mocked(remediateOpsFinding).mockRejectedValue(new ApiClientError(409, {
      error_code: 'FINDING_REVISION_CONFLICT',
      message: '问题 f1 版本冲突：期望 revision 3，实际 4',
    }))
    renderDrawer()
    await waitFor(() => expect(screen.getByTestId('ops-detail-remediate')).toBeTruthy())

    fireEvent.click(screen.getByTestId('ops-detail-remediate'))
    await waitFor(() => expect(screen.getByTestId('ops-detail-action-error')).toBeTruthy())
    expect(screen.getByTestId('ops-detail-action-error').textContent).toContain(
      'FINDING_REVISION_CONFLICT',
    )
    // 仍开放，修复按钮可重试
    expect(screen.getByTestId('ops-detail-remediate')).toBeTruthy()
  })

  // ── #51 LLM 智能诊断 ──

  const DIAGNOSIS_COMPLETE: OpsDiagnosisReportDto = {
    finding_id: 'f1',
    status: 'complete',
    root_cause: '同步任务连续失败，疑似源库连接超时',
    citations: [
      { citation_id: 'E1', source: 'payload.problem', quote: '"sync_job_degraded"' },
      { citation_id: 'E2', source: 'supplement.sync_attempts[0]', quote: 'status=failed error_code=SOURCE_TIMEOUT rows=0' },
    ],
    uncertainties: ['缺少最近一次成功同步时间'],
    actions: [
      { level: 'L1', description: '重试同步任务', citation_ids: ['E1'] },
      { level: 'L2', description: '人工核对源库凭据', citation_ids: ['E1', 'E2'] },
    ],
    model_route: { scene: 'asset_diagnosis', model_type: 'llm', model_name: 'deepseek-chat' },
    generated_by: 'portal-dev-ops',
    generated_at: '2026-09-10T04:20:00+00:00',
  }

  it('发起诊断：调用端点并以响应回填报告卡片（只读不刷新列表）', async () => {
    const result: OpsDiagnosisResultDto = {
      finding: finding({ diagnosis: { ...DIAGNOSIS_COMPLETE } }),
      report: DIAGNOSIS_COMPLETE,
    }
    vi.mocked(diagnoseOpsFinding).mockResolvedValue(result)
    const { onMutated } = renderDrawer()
    await waitFor(() => expect(screen.getByTestId('ops-diagnose-button')).toBeTruthy())

    fireEvent.click(screen.getByTestId('ops-diagnose-button'))
    await waitFor(() => expect(screen.getByTestId('ops-diagnosis-report')).toBeTruthy())
    expect(diagnoseOpsFinding).toHaveBeenCalledWith('f1')
    // 根因、可展开引用、分级建议与不确定性齐备
    expect(screen.getByTestId('ops-diagnosis-root-cause').textContent).toContain('连接超时')
    expect(screen.getAllByTestId('ops-diagnosis-citation').length).toBe(2)
    expect(screen.getByText('L1 可自动')).toBeTruthy()
    expect(screen.getByText('L2 需人工确认')).toBeTruthy()
    expect(screen.getByTestId('ops-diagnosis-uncertainties').textContent).toContain('成功同步时间')
    // 模型路由审计信息
    expect(screen.getByTestId('ops-diagnosis-meta').textContent).toContain('deepseek-chat')
    // 诊断只读：不通知列表刷新
    expect(onMutated).not.toHaveBeenCalled()
  })

  it('insufficient_evidence 专属态：不渲染根因与建议，只显示证据不足提示', async () => {
    const insufficient = {
      ...DIAGNOSIS_COMPLETE,
      status: 'insufficient_evidence' as const,
      root_cause: null,
      citations: [],
      actions: [],
      uncertainties: ['模型未给出可验证的证据引用，诊断不成立'],
    }
    vi.mocked(getOpsFinding).mockResolvedValue(
      detail({ finding: finding({ diagnosis: insufficient }) }),
    )
    renderDrawer()
    await waitFor(() => expect(screen.getByTestId('ops-diagnosis-insufficient')).toBeTruthy())
    expect(screen.getByTestId('ops-diagnosis-insufficient').textContent).toContain('证据不足')
    expect(screen.queryByTestId('ops-diagnosis-root-cause')).toBeNull()
    expect(screen.queryByTestId('ops-diagnosis-actions')).toBeNull()
    expect(screen.queryAllByTestId('ops-diagnosis-citation')).toEqual([])
  })

  it('诊断不可用（503）时展示错误条且不落报告', async () => {
    vi.mocked(diagnoseOpsFinding).mockRejectedValue(new ApiClientError(503, {
      error_code: 'DIAGNOSIS_UNAVAILABLE',
      message: '诊断不可用：模型调用失败：ModelConfigError',
    }))
    renderDrawer()
    await waitFor(() => expect(screen.getByTestId('ops-diagnose-button')).toBeTruthy())

    fireEvent.click(screen.getByTestId('ops-diagnose-button'))
    await waitFor(() => expect(screen.getByTestId('ops-detail-action-error')).toBeTruthy())
    expect(screen.getByTestId('ops-detail-action-error').textContent).toContain('DIAGNOSIS_UNAVAILABLE')
    // 未落报告：占位仍在
    expect(screen.getByTestId('ops-diagnosis-empty')).toBeTruthy()
  })

  it('只读模式（canWrite=false）不渲染发起诊断入口', async () => {
    renderDrawer('f1', false)
    await waitFor(() => expect(screen.getByTestId('ops-detail-drawer')).toBeTruthy())
    expect(screen.queryByTestId('ops-diagnose-block')).toBeNull()
    expect(screen.getByTestId('ops-diagnosis-empty')).toBeTruthy()
  })
})
