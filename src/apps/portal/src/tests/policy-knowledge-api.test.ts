import { afterEach, describe, expect, it, vi } from 'vitest'

import { getWorkbenchDocuments } from '@/lib/policy-knowledge-api'


describe('policy knowledge api', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('surfaces typed backend error messages', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ detail: { message: '语义契约不可用' } }),
    }))

    await expect(getWorkbenchDocuments()).rejects.toThrow('语义契约不可用')
  })
})
