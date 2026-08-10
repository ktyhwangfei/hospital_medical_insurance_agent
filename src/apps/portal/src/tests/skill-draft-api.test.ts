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
  restoreSkill,
  archiveSkill,
  importSkillZip,
  generateSkillAIProposal,
  acceptSkillAIProposal,
  optimizeSkillAIDraft,
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

  it('generates a typed AI proposal and accepts it with an idempotency key', async () => {
    const proposal = {
      generation_id: 'gen_abc_1',
      proposal_hash: 'a'.repeat(64),
      structured_config: {
        basic: { skill_id: 'ai_skill', skill_name: 'AI Skill', description: 'demo', owner: 'it' },
        business_mounting: { business_action: 'explain', business_object: 'settlement', include_keywords: [], excluded_intents: [] },
        inputs: [{ metric_code: 'Settlement.amount', alias: 'amount', required: true, purpose: 'explain' }],
        schemas: { input: { type: 'object' }, output: { type: 'object' } },
      },
      raw_files: { 'assembler.py': 'def assemble(data): return data', 'prompt_template.yaml': 'system: explain' },
      validation_preview: { issues: [], has_blocking: false, blocking_ok: true },
      provenance: {
        model_type: 'test-model', scene: 'skill_authoring', prompt_version: 'v1',
        metric_versions: [{ metric_code: 'Settlement.amount', object_code: 'Settlement', object_version: 2, status: 'published' }],
        generated_at: '2026-08-10T00:00:00Z', content_hash: 'b'.repeat(64),
      },
      citations: [{ source_type: 'metric_registry', source_id: 'Settlement.amount@2', summary: 'published snapshot' }],
      uncertainties: ['人工确认政策范围'],
    } as const
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(proposal))
      .mockResolvedValueOnce(jsonResponse({ ...DRAFT, draft_id: 'd-ai', source_type: 'ai_generated' }, 201))
    vi.stubGlobal('fetch', fetchMock)

    const generated = await generateSkillAIProposal({
      description: '解释结算金额',
      metric_codes: ['Settlement.amount'],
    })
    await acceptSkillAIProposal(generated, 'accept-ai-1')

    expect(fetchMock.mock.calls[0][0]).toContain('/infra-skills/ai-generate')
    expect(fetchMock.mock.calls[1][0]).toContain('/infra-skills/drafts/from-ai')
    const acceptInit = fetchMock.mock.calls[1][1] as RequestInit
    expect(new Headers(acceptInit.headers).get('Idempotency-Key')).toBe('accept-ai-1')
    const body = JSON.parse(String(acceptInit.body))
    expect(body.provenance).toEqual(proposal.provenance)
    expect(body.proposal_hash).toBe(proposal.proposal_hash)
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
    const headers = new Headers(init.headers)
    expect(init.method).toBe('PATCH')
    expect(headers.get('Authorization')).toMatch(/^Bearer /)
    expect(fetchMock.mock.calls[0][0]).toContain('/infra-skills/drafts/d-1')
  })

  it('requests a typed read-only AI optimization proposal', async () => {
    const proposal = {
      base_revision: 3,
      proposal_hash: 'e'.repeat(64),
      structured_config: {
        basic: { skill_id: 'demo_skill', skill_name: 'Demo', description: 'optimized', owner: 'it' },
        business_mounting: { business_action: 'explain', business_object: 'settlement', include_keywords: [], excluded_intents: [] },
        inputs: [{ metric_code: 'Settlement.amount', alias: 'amount', required: true, purpose: 'explain' }],
        schemas: { input: { type: 'object' }, output: { type: 'object' } },
      },
      raw_files: { 'assembler.py': 'def assemble(data): return data' },
      validation_preview: { issues: [], has_blocking: false, blocking_ok: true },
      provenance: {
        model_type: 'test-model', scene: 'skill_authoring', prompt_version: 'v1',
        metric_versions: [{ metric_code: 'Settlement.amount', object_code: 'Settlement', object_version: 2, status: 'published' }],
        generated_at: '2026-08-10T00:00:00Z', content_hash: 'b'.repeat(64),
      },
      diff: [{ scope: 'field', change_type: 'changed', path: 'structured_config.basic.description', before: 'old', after: 'optimized' }],
      citations: [],
      uncertainties: ['人工确认'],
    }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(proposal))
    vi.stubGlobal('fetch', fetchMock)

    const result = await optimizeSkillAIDraft('d-1', {
      description: '优化说明',
      metric_codes: ['Settlement.amount'],
      expected_revision: 3,
    })

    expect(result.base_revision).toBe(3)
    expect(fetchMock.mock.calls[0][0]).toContain('/infra-skills/drafts/d-1/ai-optimize')
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body)).expected_revision).toBe(3)
  })

  it('deletes a draft with expected_revision and auth header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ...DRAFT, status: 'deleted' }))
    vi.stubGlobal('fetch', fetchMock)

    await deleteSkillDraft('d-1', 3)
    const init = fetchMock.mock.calls[0][1] as RequestInit
    const headers = new Headers(init.headers)
    expect(init.method).toBe('DELETE')
    expect(fetchMock.mock.calls[0][0]).toContain('/infra-skills/drafts/d-1')
    expect(fetchMock.mock.calls[0][0]).toContain('expected_revision=3')
    expect(headers.get('Authorization')).toMatch(/^Bearer /)
  })

  it('copies a skill', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(DRAFT, 201))
    vi.stubGlobal('fetch', fetchMock)

    await copySkill({ source_skill_id: 'src', new_skill_id: 'demo_skill' }, 'idem-key-2')
    expect(fetchMock.mock.calls[0][0]).toContain('/infra-skills/src/copy')
    const body = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))
    expect(body.new_skill_id).toBe('demo_skill')
  })

  it('validates a draft with auth header and parses issues', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        draft_id: 'd-1',
        issues: [
          { code: 'MISSING_SKILL_ID', message: '缺少 skill_id', severity: 'blocking', path: 'basic.skill_id' },
        ],
        has_blocking: true,
        blocking_ok: false,
        revision: 2,
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await validateSkillDraft('d-1')
    expect(result.blocking_ok).toBe(false)
    expect(result.issues[0].severity).toBe('blocking')
    expect(result.issues[0].path).toBe('basic.skill_id')
    const headers = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers)
    expect(headers.get('Authorization')).toMatch(/^Bearer /)
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
    const init = fetchMock.mock.calls[0][1] as RequestInit
    const headers = new Headers(init.headers)
    expect(headers.get('Authorization')).toMatch(/^Bearer /)
    const body = JSON.parse(String(init.body))
    expect(body.expected_revision).toBe(1)
  })

  it('restores a skill with auth header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ ...DRAFT, lifecycle_status: 'enabled', revision: 3 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await restoreSkill('demo_skill', { expected_revision: 2, reason: '恢复' })
    expect(fetchMock.mock.calls[0][0]).toContain('/infra-skills/demo_skill/restore')
    const headers = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers)
    expect(headers.get('Authorization')).toMatch(/^Bearer /)
  })

  it('archives a skill with auth header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ ...DRAFT, lifecycle_status: 'archived', revision: 4 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await archiveSkill('demo_skill', { expected_revision: 3, reason: '归档' })
    expect(fetchMock.mock.calls[0][0]).toContain('/infra-skills/demo_skill/archive')
    const headers = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers)
    expect(headers.get('Authorization')).toMatch(/^Bearer /)
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
