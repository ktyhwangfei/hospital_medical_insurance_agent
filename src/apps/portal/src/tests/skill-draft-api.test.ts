import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  listSkillDrafts,
  createSkillDraft,
  saveSkillDraft,
  deleteSkillDraft,
  copySkill,
  validateSkillDraft,
  materializeSkill,
  disableSkill,
  importSkillZip,
} from '@/lib/skill-draft-api'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const DRAFT = {
  draft_id: 'd-1',
  skill_id: 'demo_skill',
  skill_name: 'Demo',
  status: 'editing',
  source_type: 'template',
  structured_config: { business_mounting: { business_action: 'explain', business_object: 'settlement' } },
  validation_blocking_ok: false,
  revision: 1,
  etag: 'etag-1',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  created_by: 'u',
}

describe('skill-draft-api client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lists drafts', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [DRAFT], total: 1 }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await listSkillDrafts()
    expect(result.total).toBe(1)
    expect(result.items[0].skill_id).toBe('demo_skill')
    expect(fetchMock.mock.calls[0][0]).toContain('/infra-skills/drafts')
  })

  it('creates a draft with idempotency key and auth header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(DRAFT, 201))
    vi.stubGlobal('fetch', fetchMock)

    await createSkillDraft(
      { skill_id: 'demo_skill', skill_name: 'Demo', business_action: 'explain', business_object: 'settlement' },
      'idem-key-1',
    )

    const init = fetchMock.mock.calls[0][1] as RequestInit
    const headers = new Headers(init.headers)
    expect(headers.get('Idempotency-Key')).toBe('idem-key-1')
    expect(headers.get('Authorization')).toMatch(/^Bearer /)
    expect(init.method).toBe('POST')
  })

  it('saves draft via PATCH with optimistic lock', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ...DRAFT, revision: 2 }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await saveSkillDraft('d-1', {
      structured_config: DRAFT.structured_config,
      expected_revision: 1,
    })
    expect(result.revision).toBe(2)
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('PATCH')
    expect(fetchMock.mock.calls[0][0]).toContain('/infra-skills/drafts/d-1')
  })

  it('deletes a draft', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await deleteSkillDraft('d-1')
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('DELETE')
  })

  it('copies a skill', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(DRAFT, 201))
    vi.stubGlobal('fetch', fetchMock)

    await copySkill({ source_skill_id: 'src', new_skill_id: 'demo_skill' }, 'idem-key-2')
    expect(fetchMock.mock.calls[0][0]).toContain('/infra-skills/src/copy')
    const body = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))
    expect(body.new_skill_id).toBe('demo_skill')
  })

  it('validates a draft', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ draft_id: 'd-1', report: { blocking: [], warnings: [] }, blocking_ok: true }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await validateSkillDraft('d-1')
    expect(result.blocking_ok).toBe(true)
  })

  it('materializes a draft with reason', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ skill_id: 'demo_skill', version_id: 'ver-1', artifact_written: true, draft_revision: 3 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await materializeSkill(
      { draft_id: 'd-1', expected_revision: 2, reason: '首次发布' },
      'idem-key-3',
    )
    expect(result.version_id).toBe('ver-1')
    const body = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))
    expect(body.reason).toBe('首次发布')
  })

  it('disables a skill with expected_revision', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ ...DRAFT, lifecycle_status: 'disabled', revision: 2 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await disableSkill('demo_skill', { expected_revision: 1, reason: '停用测试' })
    expect(fetchMock.mock.calls[0][0]).toContain('/infra-skills/demo_skill/disable')
    const body = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))
    expect(body.expected_revision).toBe(1)
  })

  it('imports a zip file as binary body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ...DRAFT, source_type: 'import' }, 201))
    vi.stubGlobal('fetch', fetchMock)

    const file = new File(['zip-content'], 'pkg.zip', { type: 'application/zip' })
    await importSkillZip(file, 'idem-key-4')

    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    expect(fetchMock.mock.calls[0][0]).toContain('source=zip')
    // body should be ArrayBuffer, not JSON string
    expect(init.body).toBeInstanceOf(ArrayBuffer)
  })

  it('parses error response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ detail: { error_code: 'SKILL_DRAFT_CONFLICT', message: 'revision mismatch' } }, 409),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(saveSkillDraft('d-1', {
      structured_config: DRAFT.structured_config,
      expected_revision: 99,
    })).rejects.toThrow('revision mismatch')
  })
})
