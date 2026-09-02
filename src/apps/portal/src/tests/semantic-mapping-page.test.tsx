import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import MappingCenterPage from '../../app/semantic-layer/mapping/page'

const semanticReviewJsonMock = vi.hoisted(() => vi.fn())

vi.mock('@/lib/policy-knowledge-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/policy-knowledge-api')>()),
  semanticReviewJson: semanticReviewJsonMock,
  updateSemanticMetric: vi.fn(),
}))

const EMPTY_MODEL = {
  object_code: 'djxx', datasets: [], keys: [], fields: [], relations: [], quality_rules: [],
  preferred_relation_paths: [], validation_issues: ['query model missing dataset'], queryable: false,
}
const SETTLEMENT_MODEL = {
  object_code: 'inpatient_settlement',
  datasets: [{ dataset_code: 'registration', object_code: 'inpatient_settlement', datasource_id: 'insurance_db', schema_name: 'dbo', table_name: 'yb_brdjxx', name: '住院登记', status: 'published' }],
  keys: [{ key_code: 'registration_pk', dataset_code: 'registration', entity_code: 'inpatient_admission', key_type: 'primary', columns: ['djh'] }],
  fields: [{ field_code: 'registration.registration_id', dataset_code: 'registration', column_name: 'djh', name: '结算单号', field_role: 'identifier', semantic_type: 'String', value_domain: null, nullable: false, status: 'published' }],
  relations: [],
  quality_rules: [{ rule_code: 'registration_not_null', object_code: 'inpatient_settlement', rule_type: 'not_null', target_dataset_or_relation: 'registration', severity: 'blocking', parameters: { field_code: 'registration.registration_id' }, status: 'published' }],
  preferred_relation_paths: [], validation_issues: [], queryable: true,
}

function response(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

function metric(code: string, objectCode: string, name: string) {
  return {
    metric_code: code, name, definition: name, object_code: objectCode, metric_type: 'Atomic', semantic_type: 'Amount', indexed: false,
    schema_version: 1, unit: '元', required: false, importance: 'core', value_domain: null, source_object: null,
    source_field: 'dbo.table.amount', source_adapter_port: null, usage_count: 0, quality_score: 1, version: '1', status: 'published',
  }
}

function installFetch() {
  const djMetric = metric('djxx.metric', 'djxx', '参保人登记指标')
  const settlementMetric = metric('inpatient_settlement.total_amount', 'inpatient_settlement', '住院结算指标')
  vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
    const url = String(input)
    if (url.endsWith('/objects')) return response([
      { object_code: 'djxx', name: '参保人登记', domain_code: 'ybdy', status: 'draft', current_version: null },
      { object_code: 'inpatient_settlement', name: '住院结算', domain_code: 'ybjs', status: 'published', current_version: '1' },
    ])
    if (url.includes('/objects/djxx/query-model')) return response(EMPTY_MODEL)
    if (url.includes('/objects/inpatient_settlement/query-model')) return response(SETTLEMENT_MODEL)
    if (url.includes('/metrics?object_code=djxx')) return response([djMetric])
    if (url.includes('/metrics?object_code=inpatient_settlement')) return response([settlementMetric])
    if (url.includes('/metrics/djxx.metric')) return response(djMetric)
    if (url.includes('/metrics/inpatient_settlement.total_amount')) return response(settlementMetric)
    if (url.endsWith('/summary')) return response({ domains_count: 2, objects_count: 2, metrics_count: 2, mapped_count: 2, unmapped_count: 0, value_missing_count: 0, mapping_rate: 1, skill_references: 0 })
    if (url.endsWith('/value-domains')) return response([])
    if (url.endsWith('/discovery/results')) return response({ fields: [] })
    throw new Error(`Unexpected request: ${url}`)
  }))
}

describe('MappingCenterPage', () => {
  beforeEach(() => {
    installFetch()
    semanticReviewJsonMock.mockReset()
    semanticReviewJsonMock.mockResolvedValue(SETTLEMENT_MODEL)
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('defaults to a queryable object and scopes metrics to it', async () => {
    render(<MappingCenterPage />)

    expect(await screen.findByLabelText('业务对象')).toHaveValue('inpatient_settlement')
    expect(await screen.findByText('每行代表')).toBeInTheDocument()
    expect(screen.getByText('住院结算指标')).toBeInTheDocument()
    expect(screen.queryByText('参保人登记指标')).not.toBeInTheDocument()
  })

  it('edits a dataset through the structured workbench and guides empty models', async () => {
    const user = userEvent.setup()
    render(<MappingCenterPage />)
    await screen.findByLabelText('业务对象')

    await user.click(screen.getByRole('button', { name: '数据集' }))
    const name = screen.getByLabelText('数据集名称 1')
    await user.clear(name)
    await user.type(name, '住院登记主数据')
    await user.click(screen.getByRole('button', { name: '校验并保存' }))
    await waitFor(() => expect(semanticReviewJsonMock).toHaveBeenCalled())
    expect(semanticReviewJsonMock.mock.calls[0][2].datasets[0].name).toBe('住院登记主数据')

    await user.selectOptions(screen.getByLabelText('业务对象'), 'djxx')
    expect(await screen.findByRole('button', { name: '添加数据集' })).toBeInTheDocument()
  })
})
