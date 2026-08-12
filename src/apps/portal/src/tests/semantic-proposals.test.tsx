import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SemanticProposalsPage from '../../app/semantic-layer/proposals/page'
import type { SemanticProposal } from '@/lib/policy-knowledge-api'

const METRIC: SemanticProposal = {
  proposal_id: 'proposal-metric',
  fingerprint: 'metric-fingerprint',
  proposal_type: 'metric',
  trigger_source: 'EXTRACTION_UNKNOWN',
  status: 'proposed',
  concept: '大额互助起付标准',
  object_code: 'zcgz',
  axis_metric_code: null,
  metric_draft: {
    metric_code: 'mutual_aid_deductible',
    object_code: 'zcgz',
    name: '大额互助起付标准',
    definition: '大额互助的起付金额',
    metric_type: 'Atomic',
    semantic_type: 'Amount',
    unit: '元',
    value_domain: null,
    metric_kind: 'field',
    indexed: true,
    extraction_hint: null,
    schema_version: 1,
  },
  value_draft: null,
  suggested_mappings: [],
  mapping_only: false,
  formula: null,
  evidence: [{
    source_ref: 'doc-1/unit-1/ext-1',
    excerpt: '大额互助起付标准为 1200 元',
    doc_id: 'doc-1',
    unit_id: 'unit-1',
    extraction_id: 'ext-1',
    occurrence_count: 2,
  }],
  confidence: 0.91,
  occurrence_count: 2,
  reviewed_by: null,
  reviewed_at: null,
  review_note: null,
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
}

const VALUE: SemanticProposal = {
  ...METRIC,
  proposal_id: 'proposal-value',
  fingerprint: 'value-fingerprint',
  proposal_type: 'value',
  concept: '灵活就业人员',
  metric_draft: null,
  value_draft: {
    domain_code: 'person_type',
    standard_value: '灵活就业人员',
    evidence: '参保人群包含灵活就业人员',
    source_ref: 'doc-2/unit-2/ext-2',
  },
  suggested_mappings: [{
    metric_code: 'psn_type',
    domain_code: 'person_type',
    binding_id: 'binding-1',
    source_value: '灵活就业',
    standard_value: '灵活就业人员',
  }],
  evidence: [{
    source_ref: 'doc-2/unit-2/ext-2',
    excerpt: '灵活就业人员可参加城镇职工医保',
    doc_id: 'doc-2',
    unit_id: 'unit-2',
    extraction_id: 'ext-2',
    occurrence_count: 1,
  }],
  confidence: 0.84,
  occurrence_count: 1,
}

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function installFetch(metric = METRIC, value = VALUE) {
  const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (method === 'GET' && url.includes('proposal_type=metric')) return response([metric])
    if (method === 'GET' && url.includes('proposal_type=value')) return response([value])
    if (url.endsWith('/review')) return response({ ...metric, status: 'reviewing' })
    if (url.endsWith('/accept')) return response({ ...metric, status: 'accepted' })
    if (url.endsWith('/publish')) return response({ ...metric, status: 'published' })
    if (url.endsWith('/reject')) return response({ ...metric, status: 'rejected', review_note: '概念与现有指标重复' })
    throw new Error(`Unexpected request: ${method} ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('SemanticProposalsPage', () => {
  beforeEach(() => sessionStorage.clear())
  afterEach(() => {
    cleanup()
    sessionStorage.clear()
    vi.unstubAllGlobals()
  })

  it('shows metric and value proposals in separate tabs', async () => {
    sessionStorage.setItem('semantic-review-token', 'review-token')
    installFetch()
    render(<SemanticProposalsPage />)

    expect(await screen.findByText('mutual_aid_deductible')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '值域提议' }))
    expect(await screen.findByText('person_type')).toBeInTheDocument()
    expect(screen.getByText('灵活就业 → 灵活就业人员')).toBeInTheDocument()
  })

  it('marks a proposed item as reviewing when evidence is expanded', async () => {
    sessionStorage.setItem('semantic-review-token', 'review-token')
    const fetchMock = installFetch()
    render(<SemanticProposalsPage />)

    fireEvent.click(await screen.findByRole('button', { name: '展开 mutual_aid_deductible 证据' }))
    expect(await screen.findAllByText('大额互助起付标准为 1200 元')).toHaveLength(2)
    expect(screen.getByText('doc-1')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('审核中')).toBeInTheDocument())
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/proposal-metric\/review$/),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer review-token' }),
      }),
    )
  })

  it('accepts then publishes in one reviewer action', async () => {
    sessionStorage.setItem('semantic-review-token', 'review-token')
    const fetchMock = installFetch({ ...METRIC, status: 'reviewing' })
    render(<SemanticProposalsPage />)

    fireEvent.click(await screen.findByRole('button', { name: '通过并发布 mutual_aid_deductible' }))
    await waitFor(() => expect(screen.getByText('已发布')).toBeInTheDocument())
    expect(screen.getByRole('status')).toHaveTextContent('已通过并发布')
    const mutationUrls = fetchMock.mock.calls
      .filter(([, init]) => init?.method === 'POST')
      .map(([url]) => String(url))
    expect(mutationUrls).toEqual([
      expect.stringMatching(/proposal-metric\/accept$/),
      expect.stringMatching(/proposal-metric\/publish$/),
    ])
  })

  it('requires a nonblank rejection reason and submits the trimmed value', async () => {
    sessionStorage.setItem('semantic-review-token', 'review-token')
    const fetchMock = installFetch({ ...METRIC, status: 'reviewing' })
    render(<SemanticProposalsPage />)

    fireEvent.click(await screen.findByRole('button', { name: '驳回 mutual_aid_deductible' }))
    const submit = screen.getByRole('button', { name: '确认驳回 mutual_aid_deductible' })
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByLabelText('驳回原因 mutual_aid_deductible'), {
      target: { value: '  概念与现有指标重复  ' },
    })
    fireEvent.click(submit)

    await waitFor(() => expect(screen.getByText('已驳回')).toBeInTheDocument())
    const rejectCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/reject'))
    expect(JSON.parse(String(rejectCall?.[1]?.body))).toEqual({ reason: '概念与现有指标重复' })
  })

  it('shows loading then an empty state', async () => {
    sessionStorage.setItem('semantic-review-token', 'review-token')
    const resolvers: Array<(value: Response) => void> = []
    const fetchMock = vi.fn(() => new Promise<Response>((resolve) => { resolvers.push(resolve) }))
    vi.stubGlobal('fetch', fetchMock)
    render(<SemanticProposalsPage />)
    expect(screen.getByText('正在加载提议…')).toBeInTheDocument()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    resolvers.forEach((resolve) => resolve(response([])))
    await waitFor(() => expect(screen.getByText('暂无待审核指标提议')).toBeInTheDocument())
  })

  it('shows an actionable load error', async () => {
    sessionStorage.setItem('semantic-review-token', 'review-token')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('网络不可用')))
    render(<SemanticProposalsPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('网络不可用')
  })

  it('renders an authentication error when the review token is missing', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    render(<SemanticProposalsPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('缺少语义审核登录凭证')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
