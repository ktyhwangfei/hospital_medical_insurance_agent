import { afterEach, describe, expect, it, vi } from 'vitest'

import {
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
})
