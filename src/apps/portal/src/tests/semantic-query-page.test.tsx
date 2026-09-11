import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SemanticQueryPage from '../../app/semantic-layer/query/page'

const semanticReviewJsonMock = vi.hoisted(() => vi.fn())

vi.mock('@/lib/policy-knowledge-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/policy-knowledge-api')>()),
  semanticReviewJson: semanticReviewJsonMock,
}))

const MODELS = {
  djxx: {
    object_code: 'djxx', datasets: [], keys: [], fields: [], relations: [],
    quality_rules: [], preferred_relation_paths: [], metrics: [], validation_issues: ['对象没有已发布查询模型'], queryable: false,
  },
  inpatient_settlement: {
    object_code: 'inpatient_settlement',
    datasets: [{ dataset_code: 'registration', object_code: 'inpatient_settlement', datasource_id: 'insurance_db', schema_name: 'dbo', table_name: 'yb_brdjxx', name: '住院登记', status: 'published' }],
    keys: [{ key_code: 'registration_pk', dataset_code: 'registration', entity_code: 'inpatient_admission', key_type: 'primary', columns: ['djh'] }],
    fields: [
      { field_code: 'registration.registration_id', dataset_code: 'registration', column_name: 'djh', name: '结算单号', field_role: 'identifier', semantic_type: 'String', nullable: false, status: 'published' },
      { field_code: 'registration.total_amount', dataset_code: 'registration', column_name: 'total_amount', name: '总费用', field_role: 'fact', semantic_type: 'Amount', nullable: false, status: 'published' },
    ],
    relations: [], quality_rules: [{ rule_code: 'registration_not_null', object_code: 'inpatient_settlement', rule_type: 'not_null', target_dataset_or_relation: 'registration', severity: 'blocking', parameters: { field_code: 'registration.registration_id' }, status: 'published' }],
    preferred_relation_paths: [], metrics: [{ metric_code: 'total_amount', name: '总费用', status: 'published', fact_field_code: 'registration.total_amount', expression: null }], validation_issues: [], queryable: true,
  },
  second_queryable: {
    object_code: 'second_queryable',
    datasets: [{ dataset_code: 'second_data', object_code: 'second_queryable', datasource_id: 'insurance_db', schema_name: 'dbo', table_name: 'second_table', name: '第二数据集', status: 'published' }],
    keys: [{ key_code: 'second_pk', dataset_code: 'second_data', entity_code: 'second_entity', key_type: 'primary', columns: ['second_id'] }],
    fields: [
      { field_code: 'second_data.second_id', dataset_code: 'second_data', column_name: 'second_id', name: '第二锚点', field_role: 'identifier', semantic_type: 'String', nullable: false, status: 'published' },
      { field_code: 'second_data.amount', dataset_code: 'second_data', column_name: 'amount', name: '第二金额', field_role: 'fact', semantic_type: 'Amount', nullable: false, status: 'published' },
    ],
    relations: [], quality_rules: [], preferred_relation_paths: [], metrics: [{ metric_code: 'second_amount', name: '第二金额', status: 'published', fact_field_code: 'second_data.amount', expression: null }], validation_issues: [], queryable: true,
  },
}

const METRICS = {
  inpatient_settlement: [{ metric_code: 'total_amount', name: '总费用', object_code: 'inpatient_settlement', status: 'published' }],
  second_queryable: [{ metric_code: 'second_amount', name: '第二金额', object_code: 'second_queryable', status: 'published' }],
}

function response(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

function installFetch() {
  vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
    const url = String(input)
    if (url.endsWith('/objects')) return response([
      { object_code: 'djxx', name: '参保人登记', current_version: null },
      { object_code: 'inpatient_settlement', name: '住院结算', current_version: '1' },
      { object_code: 'second_queryable', name: '第二对象', current_version: '1' },
    ])
    const modelCode = Object.keys(MODELS).find((code) => url.includes(`/objects/${code}/query-model`)) as keyof typeof MODELS | undefined
    if (modelCode) return response(MODELS[modelCode])
    const metricObject = Object.keys(METRICS).find((code) => url.includes(`/metrics?object_code=${code}`)) as keyof typeof METRICS | undefined
    if (metricObject) return response(METRICS[metricObject])
    if (url.includes('/metrics/total_amount')) return response({ ...METRICS.inpatient_settlement[0], fact_field_code: 'registration.total_amount', expression: null })
    if (url.includes('/metrics/second_amount')) return response({ ...METRICS.second_queryable[0], fact_field_code: 'second_data.amount', expression: null })
    if (url.endsWith('/question-library/questions')) {
      return new Response(JSON.stringify({ question_id: 'tq_new', status: 'draft' }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    throw new Error(`Unexpected request: ${url}`)
  }))
}

describe('SemanticQueryPage', () => {
  beforeEach(() => {
    installFetch()
    semanticReviewJsonMock.mockReset()
    // 加工快照卡默认不可用（页面应降级不阻塞）；需要时在用例内重新 mockResolvedValue
    semanticReviewJsonMock.mockRejectedValue(new Error('快照不可用'))
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('derives dependent fields from the selected published query model', async () => {
    const user = userEvent.setup()
    render(<SemanticQueryPage />)

    expect(await screen.findByLabelText('业务对象')).toHaveValue('inpatient_settlement')
    expect(screen.getByLabelText('目标实体').tagName).toBe('SELECT')
    expect(screen.getByLabelText('目标实体')).toHaveValue('inpatient_admission')
    await waitFor(() => expect(screen.getByLabelText('锚点字段')).toHaveValue('registration.registration_id'))

    await user.type(screen.getByLabelText('锚点值'), 'old-value')
    await user.selectOptions(screen.getByLabelText('业务对象'), 'second_queryable')

    await waitFor(() => expect(screen.getByLabelText('目标实体')).toHaveValue('second_entity'))
    expect(screen.getByLabelText('锚点字段')).toHaveValue('second_data.second_id')
    expect(screen.getByLabelText('锚点值')).toHaveValue('')
    expect(screen.queryByText('过滤（JSON 数组）')).not.toBeInTheDocument()
  })

  it('fills the anchor only after an explicit random sample request', async () => {
    semanticReviewJsonMock.mockResolvedValueOnce(null) // 首个调用是加工快照卡（不可用即降级）
    semanticReviewJsonMock.mockResolvedValueOnce({ value: '1671213' })
    const user = userEvent.setup()
    render(<SemanticQueryPage />)

    await waitFor(() => expect(screen.getByLabelText('锚点字段')).toHaveValue('registration.registration_id'))
    expect(screen.getByLabelText('锚点值')).toHaveValue('')
    await user.click(screen.getByRole('button', { name: '随机取值' }))

    await waitFor(() => expect(screen.getByLabelText('锚点值')).toHaveValue('1671213'))
    expect(screen.getByText('再次点击可重新取样。')).toBeInTheDocument()
    expect(semanticReviewJsonMock).toHaveBeenCalledWith(
      expect.stringContaining('/query/anchor-sample'),
      'POST',
      {
        object_code: 'inpatient_settlement',
        entity_code: 'inpatient_admission',
        field_code: 'registration.registration_id',
      },
    )
  })

  it('执行验证成功后可存为可信问题草稿，提交体携带 query_plan 与指标/维度元数据', async () => {
    const queryResult = {
      plan: { kind: 'logical' },
      result: {
        rows: [{ total_amount: 1234.5 }],
        result_grain: ['registration.registration_id'],
        query_scope: 'whole_admission',
        quality_status: 'complete',
        evidence: { segment_count: 1, matched_segment_count: 1 },
        warnings: [],
      },
      parameterized_sql: 'SELECT total_amount FROM dbo.yb_brdjxx',
    }
    semanticReviewJsonMock.mockImplementation(async (url: string) => {
      if (url.includes('/query/test')) return queryResult
      throw new Error('快照不可用')
    })
    const user = userEvent.setup()
    render(<SemanticQueryPage />)

    await waitFor(() => expect(screen.getByLabelText('锚点字段')).toHaveValue('registration.registration_id'))
    expect(screen.queryByRole('button', { name: '存为可信问题草稿' })).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('锚点值'), '1671213')
    await user.click(screen.getByRole('button', { name: '执行验证' }))

    // 执行验证成功后出现“存为可信问题草稿”入口
    await user.click(await screen.findByRole('button', { name: '存为可信问题草稿' }))
    await user.type(await screen.findByLabelText('标准问题'), '住院总费用是多少？')
    await user.type(screen.getByLabelText('同义表达'), '住院费用总额，住院花了多少')
    await user.click(screen.getByRole('button', { name: '保存草稿' }))

    // 成功提示 + 可信问题库链接（main 版 question_library 页）
    expect(await screen.findByText('已保存为草稿，请到可信问题库提交审核')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '前往可信问题库' })).toHaveAttribute('href', '/question-library')

    // 提交体：query_plan 为发给 /query/test 的同一请求对象，metrics/dimensions 与计划一致
    const testCall = semanticReviewJsonMock.mock.calls.find(([url]) => String(url).includes('/query/test'))
    expect(testCall).toBeDefined()
    const fetchMock = vi.mocked(fetch)
    const createCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/question-library/questions'))
    expect(createCall).toBeDefined()
    expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({
      standard_question: '住院总费用是多少？',
      synonyms: ['住院费用总额', '住院花了多少'],
      roles: [],
      object_code: 'inpatient_settlement',
      metrics: ['total_amount'],
      dimensions: [],
      time_scope: null,
      filters: [],
      query_plan: testCall?.[2],
      allow_drilldown: true,
      expected_result: {},
    })
  })
})
