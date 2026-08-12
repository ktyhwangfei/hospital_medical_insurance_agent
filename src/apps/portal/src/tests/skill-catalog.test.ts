import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  getSkillGovernanceWorkbench,
  listInfraSkillCatalog,
  listInfraSkillVersions,
  syncInfraSkillVersion,
} from '@/lib/api-client'


function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}


describe('Skill catalog API client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('requests the paginated skill catalog with filters', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ items: [], page: 2, page_size: 10, total: 0 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await listInfraSkillCatalog({
      page: 2,
      page_size: 10,
      business_action: 'explain',
      artifact_status: 'changed',
    })

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/v1/medical-insurance-ai-agent/infra-skills/catalog?page=2&page_size=10&business_action=explain&artifact_status=changed',
    )
  })

  it('registers the current artifact without sending file content', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ version_id: 'version-1' }, 201),
    )
    vi.stubGlobal('fetch', fetchMock)

    await syncInfraSkillVersion('demo/skill', {
      source_commit: 'abc1234',
      created_by: 'portal-user',
    })

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/v1/medical-insurance-ai-agent/infra-skills/demo%2Fskill/versions/sync',
    )
    const request = fetchMock.mock.calls[0][1] as RequestInit
    expect(request.method).toBe('POST')
    expect(JSON.parse(String(request.body))).toEqual({
      source_commit: 'abc1234',
      created_by: 'portal-user',
    })
  })

  it('loads version evidence for one skill', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]))
    vi.stubGlobal('fetch', fetchMock)

    await listInfraSkillVersions('demo skill')

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/v1/medical-insurance-ai-agent/infra-skills/demo%20skill/versions',
    )
  })

  it('requests the governance workbench with URL-safe filters', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      summary: {
        total: 0,
        healthy: 0,
        needs_evaluation: 0,
        pending_approval: 0,
        test_active: 0,
        updated_at: '2026-08-05T06:00:00Z',
      },
      items: [],
      total: 0,
      page: 1,
      page_size: 50,
    }))
    vi.stubGlobal('fetch', fetchMock)

    await getSkillGovernanceWorkbench({
      query: '结算 skill',
      governance_status: 'needs_evaluation',
      business_action: 'explain',
      priority: 'blocked',
    })

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/v1/medical-insurance-ai-agent/infra-skills/workbench?business_action=explain&governance_status=needs_evaluation&priority=blocked&query=%E7%BB%93%E7%AE%97+skill',
    )
  })
})
