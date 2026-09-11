import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  listFlows, getFlow, createFlow, updateFlow, deleteFlow,
  validateFlow, submitFlowReview, publishFlow, rollbackFlow,
  deprecateFlow, listFlowRevisions, previewFlow,
} from '@/lib/flow-api'
import type { FlowDefinitionDto } from '@/lib/flow-api'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const FLOW: FlowDefinitionDto = {
  flow_id: 'flow_op_outpatient_processed',
  name: '门诊有效结算加工视图',
  owner: 'data_governance',
  status: 'draft',
  nodes: [
    {
      node_type: 'source', node_id: 'src_trade', name: '门诊结算落地表',
      dataset_code: 'mz_trade', object_code: 'mzjyxx', fields: ['T_TradeNo'],
      position: { x: 40, y: 200 },
    },
    {
      node_type: 'aggregate', node_id: 'agg_snapshot', name: '聚合',
      group_by: [],
      measures: [{ output_code: 'op_total_fee', source_field: 'T_FeeAll', operator: 'sum' }],
      position: { x: 520, y: 200 },
    },
    {
      node_type: 'consumer', node_id: 'consumer_qp', name: '受控问数',
      consumer_kind: 'query_planner', consumes: ['op_total_fee'],
      position: { x: 1000, y: 200 },
    },
  ],
  edges: [
    { edge_id: 'e1', from_node: 'src_trade', to_node: 'agg_snapshot' },
    { edge_id: 'e2', from_node: 'agg_snapshot', to_node: 'consumer_qp' },
  ],
  source_contracts: [
    { dataset_code: 'mz_trade', object_code: 'mzjyxx', fields: ['T_TradeNo', 'T_FeeAll'] },
  ],
  metric_outputs: [
    {
      metric_code: 'op_total_fee', name: '门诊总费用', node_id: 'agg_snapshot',
      policy_definition: '口径句v4：T_State IN (2,3)',
    },
  ],
  materialization: 'view',
  revision: 3,
}

describe('flow-api client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lists flows', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([FLOW]))
    vi.stubGlobal('fetch', fetchMock)
    const result = await listFlows()
    expect(result).toHaveLength(1)
    expect(fetchMock.mock.calls[0][0]).toContain('/flow')
    expect(fetchMock.mock.calls[0][0]).not.toContain('/flow/')
  })

  it('creates flow with snake_case definition body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(FLOW, 201))
    vi.stubGlobal('fetch', fetchMock)
    await createFlow(FLOW)
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    const body = JSON.parse(init.body as string)
    expect(body.nodes[0].node_id).toBe('src_trade')
    expect(body.edges[0].from_node).toBe('src_trade')
  })

  it('updates flow with expected_revision query param', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ...FLOW, revision: 4 }))
    vi.stubGlobal('fetch', fetchMock)
    const saved = await updateFlow('flow_op_outpatient_processed', FLOW, 3)
    expect(saved.revision).toBe(4)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/flow/flow_op_outpatient_processed?expected_revision=3')
    expect(init.method).toBe('PUT')
  })

  it('deletes flow with expected_revision', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ deleted: 'x' }))
    vi.stubGlobal('fetch', fetchMock)
    await deleteFlow('x', 2)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/flow/x?expected_revision=2')
    expect(init.method).toBe('DELETE')
  })

  it('posts lifecycle actions with correct bodies', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ issues: [], has_blocking: false }))
      .mockResolvedValueOnce(jsonResponse(FLOW))
      .mockResolvedValueOnce(jsonResponse({ ...FLOW, status: 'published' }))
      .mockResolvedValueOnce(jsonResponse({ revision: { revision_id: 'r1' }, is_active: true }))
    vi.stubGlobal('fetch', fetchMock)

    await validateFlow('f')
    await submitFlowReview('f')
    await publishFlow('f', '医保数据组')
    await rollbackFlow('f', 'r1')

    const validate = fetchMock.mock.calls[0]
    expect(validate[0]).toContain('/flow/f/validate')
    expect(validate[1].method).toBe('POST')

    const publish = fetchMock.mock.calls[2]
    expect(publish[0]).toContain('/flow/f/publish')
    expect(JSON.parse(publish[1].body)).toEqual({ published_by: '医保数据组' })

    const rollback = fetchMock.mock.calls[3]
    expect(rollback[0]).toContain('/flow/f/rollback')
    expect(JSON.parse(rollback[1].body)).toEqual({ revision_id: 'r1' })
  })

  it('fetches revisions and preview artifacts', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse([{ revision: { revision_id: 'r1' }, is_active: true }]))
      .mockResolvedValueOnce(jsonResponse({
        view_name: 'v_flow_f', view_sql: 'CREATE OR REPLACE VIEW ...',
        query_plan: [], artifact_hash: 'a'.repeat(64),
      }))
    vi.stubGlobal('fetch', fetchMock)

    const revisions = await listFlowRevisions('f')
    expect(revisions[0].is_active).toBe(true)
    const artifact = await previewFlow('f')
    expect(artifact.view_name).toBe('v_flow_f')
    expect(fetchMock.mock.calls[1][0]).toContain('/flow/f/preview')
  })

  it('throws ApiClientError with FLOW_* code on 409 conflict', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      error_code: 'FLOW_REVISION_CONFLICT',
      message: '期望修订 3，实际 4',
      audit_event: {},
    }, 409))
    vi.stubGlobal('fetch', fetchMock)
    await expect(getFlow('f')).rejects.toMatchObject({
      status: 409,
      detail: { error_code: 'FLOW_REVISION_CONFLICT' },
    })
  })
})
