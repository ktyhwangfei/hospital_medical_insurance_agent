import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  activateSkillRelease,
  createSkillEvalRun,
  createSkillRelease,
  listSkillReleases,
} from '@/lib/api-client'


function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}


describe('Skill governance API client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('starts an immutable candidate route evaluation', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ run_id: 'run-1' }, 202))
    vi.stubGlobal('fetch', fetchMock)

    await createSkillEvalRun('demo/skill', {
      version_id: 'version-1',
      baseline_version_id: 'version-0',
    })

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/v1/medical-insurance-ai-agent/infra-skills/demo%2Fskill/eval-runs',
    )
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({
      version_id: 'version-1',
      baseline_version_id: 'version-0',
    })
  })

  it('sends idempotency evidence for candidate and activation mutations', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ release_id: 'release-1' }, 201))
      .mockResolvedValueOnce(jsonResponse({ release_id: 'release-1', status: 'active' }))
    vi.stubGlobal('fetch', fetchMock)

    await createSkillRelease(
      'demo skill',
      {
        version_id: 'version-1',
        eval_run_id: 'run-1',
        environment: 'test',
      },
      'candidate-key',
    )
    await activateSkillRelease(
      'demo skill',
      'release-1',
      { expected_revision: 3 },
      'activate-key',
    )

    const candidateInit = fetchMock.mock.calls[0][1] as RequestInit
    const activateInit = fetchMock.mock.calls[1][1] as RequestInit
    expect(new Headers(candidateInit.headers).get('Idempotency-Key')).toBe('candidate-key')
    expect(new Headers(activateInit.headers).get('Idempotency-Key')).toBe('activate-key')
    expect(JSON.parse(String(activateInit.body))).toEqual({ expected_revision: 3 })
  })

  it('reads the non-sensitive approval summary from releases', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      items: [{
        release_id: 'release-1',
        approval: {
          approved_by: 'information-admin',
          approver_role: 'information_department',
          approved_at: '2026-08-05T06:00:00Z',
        },
      }],
      total: 1,
    }))
    vi.stubGlobal('fetch', fetchMock)

    const response = await listSkillReleases('demo/skill')

    expect(response.items[0].approval?.approved_by).toBe('information-admin')
    expect(response.items[0].approval).not.toHaveProperty('reason')
  })
})
