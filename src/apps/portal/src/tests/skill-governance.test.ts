import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  activateSkillRelease,
  createSkillEvalRun,
  createSkillRelease,
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
      created_by: 'quality-user',
    })

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/v1/medical-insurance-ai-agent/infra-skills/demo%2Fskill/eval-runs',
    )
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({
      version_id: 'version-1',
      baseline_version_id: 'version-0',
      created_by: 'quality-user',
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
        created_by: 'developer',
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
})
