import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('Policy QA is the only business page', () => {
  it.each(['settlement', 'qc', 'dashboard'])('removes /%s', (route) => {
    expect(existsSync(resolve(process.cwd(), 'app', route, 'page.tsx'))).toBe(false)
  })

  it('keeps /policy-qa', () => {
    expect(existsSync(resolve(process.cwd(), 'app/policy-qa/page.tsx'))).toBe(true)
  })
})
