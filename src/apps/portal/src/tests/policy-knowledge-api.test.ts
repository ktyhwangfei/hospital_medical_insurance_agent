import { readFileSync } from 'node:fs'

import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  createKnowledgeBuildTask,
  createRelease,
  getRuleCompilationTrace,
  getReleaseGateStatus,
  getKnowledgeBuildTask,
  getWorkbenchDocuments,
  listEligibleKnowledgeUnits,
  listKnowledgeBuildTasks,
  PolicyKnowledgeApiError,
  preflightKnowledgeBuild,
  promoteGovernedRelease,
  promoteRelease,
  returnKnowledgeReview,
  resetUnitMedType,
  semanticReviewJson,
  semanticReviewRequest,
  setUnitMedType,
  updateSemanticMetric,
  type CreateKnowledgeBuildTaskRequest,
  type KnowledgeChangeSet,
} from '@/lib/policy-knowledge-api'

const WORKBENCH_API = '/api/v1/medical-insurance-ai-agent/policy-workbench'

const buildRequest: CreateKnowledgeBuildTaskRequest = {
  name: '湖南省医保政策初始构建',
  created_by: 'reviewer-1',
  build_mode: 'INITIAL',
  unit_revisions: [{
    doc_id: 'doc/1',
    unit_id: 'unit-1',
    unit_revision_id: 'rev-1',
  }],
}

const buildTask = {
  task_id: 'task-1',
  name: buildRequest.name,
  status: 'WAITING_REVIEW',
  build_mode: 'INITIAL',
  semantic_contract_version: 'v1',
  pipeline_version: 'pipeline-v1',
  model_scene: 'policy_knowledge_build',
  config_hash: 'hash-1',
  rebuild_reason: null,
  created_by: buildRequest.created_by,
  units: [{
    doc_id: 'doc/1',
    doc_title: '湖南省医保政策',
    unit_id: 'unit-1',
    unit_revision_id: 'rev-1',
    path: ['第一章'],
    status: 'BUILT',
    candidate_result_ids: ['candidate-1'],
    error_code: null,
    error_message: null,
  }],
  processed_units: 1,
  result_change_set_id: 'change-set-1',
  result_summary: {
    additions: 1,
    modifications: 0,
    replacements: 0,
    expirations: 0,
    unchanged: 0,
  },
  issue_count: 0,
  created_at: '2026-08-05T12:00:00Z',
  updated_at: '2026-08-05T12:01:00Z',
  started_at: '2026-08-05T12:00:01Z',
  finished_at: '2026-08-05T12:01:00Z',
}

const returnedChangeSet = {
  change_set_id: 'change-set-1',
  source_document_version_id: 'rev-1',
  doc_id: 'doc/1',
  doc_title: '湖南省医保政策',
  build_task_id: 'task-1',
  source_units: [{
    doc_id: 'doc/1',
    doc_title: '湖南省医保政策',
    unit_id: 'unit-1',
    unit_revision_id: 'rev-1',
    path: ['第一章'],
  }],
  semantic_contract_version: 'v1',
  supersedes_candidate_id: null,
  status: 'RETURNED',
  summary: buildTask.result_summary,
  items: [],
  quality_report: {
    source_fidelity: 1,
    structural_completeness: 1,
    semantic_consistency: 1,
    rule_consistency: 1,
  },
  risk_summary: {},
  blockers: [],
  review_decision: { reviewer: 'reviewer-1', note: '需补证据' },
  created_at: '2026-08-05T12:00:00Z',
  updated_at: '2026-08-05T12:02:00Z',
} satisfies KnowledgeChangeSet

function stubFetchJson(body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}


describe('policy knowledge api', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
    window.sessionStorage.clear()
  })

  it('uses the configured local review token when the browser session has none', async () => {
    window.sessionStorage.removeItem('semantic-review-token')
    vi.stubEnv('NODE_ENV', 'development')
    vi.stubEnv('NEXT_PUBLIC_SEMANTIC_REVIEW_TOKEN', 'signed-local-review-token')

    const init = await semanticReviewRequest()

    expect(init.headers).toEqual({ Authorization: 'Bearer signed-local-review-token' })
  })

  it('authenticates semantic metric updates and adds the expected version only for contract changes', async () => {
    window.sessionStorage.setItem('semantic-review-token', 'review-token')
    const fetchMock = stubFetchJson({
      status: 'ok', metric_code: 'zcgz.payment_amount', schema_version: 5,
      requires_reextract: true, task_id: 'task-1', task_status: 'pending',
    })
    const current = { semantic_type: 'Amount', indexed: false, schema_version: 4 }

    await updateSemanticMetric('zcgz.payment_amount', current, { semantic_type: 'Ratio', indexed: true })

    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/v1/medical-insurance-ai-agent/semantic/metrics/zcgz.payment_amount',
      {
        method: 'PUT',
        headers: { Authorization: 'Bearer review-token', 'Content-Type': 'application/json' },
        body: JSON.stringify({ semantic_type: 'Ratio', indexed: true, expected_schema_version: 4 }),
      },
    )

    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      status: 'ok', metric_code: 'zcgz.payment_amount', schema_version: 4,
      requires_reextract: false, task_id: null, task_status: null,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await updateSemanticMetric('zcgz.payment_amount', current, { source_field: 'claims.amount' })
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/v1/medical-insurance-ai-agent/semantic/metrics/zcgz.payment_amount',
      {
        method: 'PUT',
        headers: { Authorization: 'Bearer review-token', 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_field: 'claims.amount' }),
      },
    )
  })

  it('authenticates medical category overrides without sending a client actor', async () => {
    window.sessionStorage.setItem('semantic-review-token', 'review-token')
    const fetchMock = stubFetchJson({ reset: true })

    await setUnitMedType('doc/1', 'unit-1', '门诊')
    expect(fetchMock).toHaveBeenLastCalledWith(
      `${WORKBENCH_API}/knowledge-build/unit-med-types`,
      {
        method: 'POST',
        headers: { Authorization: 'Bearer review-token', 'Content-Type': 'application/json' },
        body: JSON.stringify({ doc_id: 'doc/1', unit_id: 'unit-1', med_type: '门诊' }),
      },
    )

    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ reset: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    await resetUnitMedType('doc/1', 'unit-1')
    expect(fetchMock).toHaveBeenLastCalledWith(
      `${WORKBENCH_API}/knowledge-build/unit-med-types/doc%2F1/unit-1`,
      { method: 'DELETE', headers: { Authorization: 'Bearer review-token' } },
    )
  })

  it('rejects governed semantic writes when the backend returns forbidden', async () => {
    window.sessionStorage.setItem('semantic-review-token', 'review-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: {
        error_code: 'SEMANTIC_REVIEW_PERMISSION_REQUIRED',
        message: '缺少语义审核权限',
        audit_event: {},
      },
    }), { status: 403, headers: { 'Content-Type': 'application/json' } })))

    await expect(semanticReviewJson('/semantic/write', 'POST', { value: 1 }))
      .rejects.toMatchObject({ status: 403, message: '缺少语义审核权限' })
  })

  it('surfaces typed backend error messages', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: {
        error_code: 'SEMANTIC_CONTRACT_UNAVAILABLE',
        message: '语义契约不可用',
        audit_event: { release_id: 'release-1' },
      },
    }), { status: 503, headers: { 'Content-Type': 'application/json' } })))

    const error = await getWorkbenchDocuments().catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(PolicyKnowledgeApiError)
    if (!(error instanceof PolicyKnowledgeApiError)) throw error
    expect(error.message).toBe('语义契约不可用')
    expect(error.status).toBe(503)
    expect(error.errorCode).toBe('SEMANTIC_CONTRACT_UNAVAILABLE')
    expect(error.auditEvent.release_id).toBe('release-1')
  })

  it('preserves claim conflict metadata in typed API errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: {
        error_code: 'UNIT_ALREADY_CLAIMED',
        message: '政策单元修订已被占用',
        audit_event: {
          task_id: 'task-claimed',
          unit_revision_id: 'rev-1',
          target_href: '/policy-knowledge/knowledge/build?task_id=task-claimed',
        },
      },
    }), { status: 409, headers: { 'Content-Type': 'application/json' } })))

    const error = await createKnowledgeBuildTask(buildRequest).catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(PolicyKnowledgeApiError)
    if (!(error instanceof PolicyKnowledgeApiError)) throw error
    expect(error.status).toBe(409)
    expect(error.errorCode).toBe('UNIT_ALREADY_CLAIMED')
    expect(error.auditEvent.task_id).toBe('task-claimed')
    expect(error.auditEvent.target_href).toBe(
      '/policy-knowledge/knowledge/build?task_id=task-claimed',
    )
  })

  it('uses a typed fallback when an error response is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('upstream unavailable', {
      status: 502,
      headers: { 'Content-Type': 'text/plain' },
    })))

    const error = await getWorkbenchDocuments().catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(PolicyKnowledgeApiError)
    if (!(error instanceof PolicyKnowledgeApiError)) throw error
    expect(error.message).toBe('请求失败 (502)')
    expect(error.status).toBe(502)
    expect(error.errorCode).toBeNull()
    expect(error.auditEvent).toEqual({})
  })

  it('lists eligible knowledge units from the build endpoint', async () => {
    const fetchMock = stubFetchJson([])

    await listEligibleKnowledgeUnits()

    expect(fetchMock).toHaveBeenCalledWith(
      `${WORKBENCH_API}/knowledge-build/eligible-units`,
      undefined,
    )
  })

  it('posts the exact build revision selection for preflight', async () => {
    const fetchMock = stubFetchJson({
      selected_count: 1,
      buildable_count: 1,
      blocking_count: 0,
      rebuild_count: 0,
      can_submit: true,
      semantic_contract_version: 'v1',
      blockers: [],
      warnings: [],
    })

    await preflightKnowledgeBuild(buildRequest)

    expect(fetchMock).toHaveBeenCalledWith(
      `${WORKBENCH_API}/knowledge-build/preflight`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildRequest),
      },
    )
  })

  it('posts the exact build revision selection when creating a task', async () => {
    const fetchMock = stubFetchJson(buildTask)

    await createKnowledgeBuildTask(buildRequest)

    expect(fetchMock).toHaveBeenCalledWith(
      `${WORKBENCH_API}/knowledge-build/tasks`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildRequest),
      },
    )
  })

  it('lists build tasks and gets encoded task details', async () => {
    const fetchMock = stubFetchJson([buildTask])

    await listKnowledgeBuildTasks()
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(buildTask), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    await getKnowledgeBuildTask('task/1')

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      `${WORKBENCH_API}/knowledge-build/tasks`,
      undefined,
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `${WORKBENCH_API}/knowledge-build/tasks/task%2F1`,
      undefined,
    )
  })

  it('returns a change set for rebuild with the exact review decision', async () => {
    const fetchMock = stubFetchJson(returnedChangeSet)

    await returnKnowledgeReview('change/set-1', 'reviewer-1', '需补证据')

    expect(fetchMock).toHaveBeenCalledWith(
      `${WORKBENCH_API}/change-sets/change%2Fset-1/return`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewer: 'reviewer-1', note: '需补证据' }),
      },
    )
    expect(returnedChangeSet.source_units[0]).toMatchObject({
      unit_revision_id: 'rev-1',
      path: ['第一章'],
    })
  })

  it('creates releases with an optional source change set and preserves legacy calls', async () => {
    const release = {
      release_id: 'release-1',
      status: 'building',
      facts_collection: 'policy_facts_release-1',
      rules_collection: 'policy_rules_release-1',
      contract_version: 'v1',
      case_set_version: 1,
      config_hash: 'hash-1',
      source_change_set_id: 'change-set-1',
      quality_score: null,
      consistency_score: null,
      created_at: '2026-08-06T01:00:00Z',
      promoted_at: null,
      promoted_by: null,
    }
    const fetchMock = stubFetchJson(release)
    const baseRequest = {
      release_id: 'release-1',
      contract_version: 'v1',
      config_hash: 'hash-1',
    }

    const created = await createRelease({ ...baseRequest, source_change_set_id: 'change-set-1' })
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      ...release,
      release_id: 'legacy-release',
      source_change_set_id: null,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await createRelease({ ...baseRequest, release_id: 'legacy-release' })

    expect(created).toMatchObject({
      created_at: '2026-08-06T01:00:00Z',
      promoted_at: null,
      promoted_by: null,
    })

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      `${WORKBENCH_API}/releases`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...baseRequest, source_change_set_id: 'change-set-1' }),
      },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `${WORKBENCH_API}/releases`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...baseRequest, release_id: 'legacy-release' }),
      },
    )
  })

  it('loads the authoritative encoded release gate status', async () => {
    const gate = {
      release_id: 'release/1',
      can_promote: false,
      current_case_set_version: 8,
      active_release_id: 'active-1',
      latest_run: null,
      blocked_reasons: ['缺少正式来源知识变更集'],
      sync_pending: true,
      sync_pending_reasons: ['发布快照尚未落库'],
    }
    const fetchMock = stubFetchJson(gate)

    const result = await getReleaseGateStatus('release/1')

    expect(result).toEqual(gate)
    expect(fetchMock).toHaveBeenCalledWith(
      `${WORKBENCH_API}/releases/release%2F1/gate-status`,
      undefined,
    )
  })

  it('loads an encoded rule compilation trace', async () => {
    const trace = { rule: { rule_id: 'rule/1' }, steps: [] }
    const fetchMock = stubFetchJson(trace)

    const result = await getRuleCompilationTrace('rule/1', 'run/1')

    expect(result).toEqual(trace)
    expect(fetchMock).toHaveBeenCalledWith(
      `${WORKBENCH_API}/rules/rule%2F1/trace?run_id=run%2F1`,
      undefined,
    )
  })

  it('separates governed promotion from deprecated legacy compatibility', async () => {
    const fetchMock = stubFetchJson({ release_id: 'release/1', status: 'active' })

    await promoteGovernedRelease('release/1', 'reviewer-1')
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ release_id: 'legacy/1', status: 'active' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    await promoteRelease('legacy/1', 'legacy-reviewer')

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      `${WORKBENCH_API}/releases/release%2F1/promote`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewed_by: 'reviewer-1' }),
      },
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `${WORKBENCH_API}/releases/legacy%2F1/promote-legacy`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewed_by: 'legacy-reviewer' }),
      },
    )
  })

  it('keeps the document-level change set builder explicitly deprecated', () => {
    const source = readFileSync(
      'src/lib/policy-knowledge-api.ts',
      'utf8',
    )

    expect(source).toMatch(
      /\/\*\*[\s\S]*?@deprecated[\s\S]*?\*\/\s*export const buildChangeSet/,
    )
  })
})
