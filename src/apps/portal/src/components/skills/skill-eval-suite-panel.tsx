'use client'

import { useEffect, useState } from 'react'

import {
  createSkillEvalSuite,
  listSkillEvalSuites,
  updateSkillEvalSuite,
} from '@/lib/api-client'
import { ApiClientError } from '@/lib/types'
import type { SkillEvalSuiteResponse } from '@/lib/types'

interface SkillEvalSuitePanelProps {
  skillId: string | null
  selectedSuiteId: string | null
  onSelect: (suiteId: string) => void
}

function errorMessage(error: unknown): string {
  return error instanceof ApiClientError ? error.detail.message : '测评集操作失败'
}

export default function SkillEvalSuitePanel({
  skillId,
  selectedSuiteId,
  onSelect,
}: SkillEvalSuitePanelProps) {
  const [suites, setSuites] = useState<SkillEvalSuiteResponse[]>([])
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    listSkillEvalSuites({
      skillId: skillId ?? undefined,
      includeInactive: true,
    })
      .then((response) => {
        if (!active) return
        setSuites(response.items)
        const selectedExists = response.items.some(
          (item) => item.suite_id === selectedSuiteId,
        )
        if (!selectedExists) {
          const first = response.items.find((item) => item.status === 'active') ?? response.items[0]
          if (first) onSelect(first.suite_id)
        }
      })
      .catch((reason) => {
        if (active) setError(errorMessage(reason))
      })
    return () => { active = false }
  }, [onSelect, selectedSuiteId, skillId])

  async function createSuite(): Promise<void> {
    const normalized = name.trim()
    if (!normalized) return
    setBusy(true)
    setError(null)
    try {
      const created = await createSkillEvalSuite({
        name: normalized,
        scope: skillId ? 'skill' : 'platform',
        skill_id: skillId,
        purpose: '',
      })
      setSuites((current) => [...current, created])
      setName('')
      onSelect(created.suite_id)
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  async function toggleSelected(): Promise<void> {
    const selected = suites.find((item) => item.suite_id === selectedSuiteId)
    if (!selected || selected.suite_id === 'EVS_platform_routing') return
    setBusy(true)
    setError(null)
    try {
      const updated = await updateSkillEvalSuite(selected.suite_id, {
        name: selected.name,
        purpose: selected.purpose,
        status: selected.status === 'active' ? 'inactive' : 'active',
        expected_revision: selected.revision,
      })
      setSuites((current) => current.map((item) => (
        item.suite_id === updated.suite_id ? updated : item
      )))
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  const selected = suites.find((item) => item.suite_id === selectedSuiteId)

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] md:items-end">
        <label className="text-xs font-medium text-slate-600">
          选择测评集
          <select
            aria-label="选择测评集"
            value={selectedSuiteId ?? ''}
            onChange={(event) => onSelect(event.target.value)}
            className="mt-1 h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm"
          >
            <option value="" disabled>请选择测评集</option>
            {suites.map((suite) => (
              <option
                key={suite.suite_id}
                value={suite.suite_id}
              >
                {suite.name}{suite.status === 'inactive' ? '（已停用）' : ''}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-medium text-slate-600">
          测评集名称
          <input
            aria-label="测评集名称"
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="mt-1 h-9 w-full rounded-md border border-slate-200 px-2 text-sm"
            maxLength={256}
          />
        </label>
        <button
          type="button"
          onClick={() => void createSuite()}
          disabled={busy || !name.trim()}
          className="h-9 rounded-md bg-blue-600 px-3 text-sm font-medium text-white disabled:opacity-50"
        >
          新建测评集
        </button>
        <button
          type="button"
          onClick={() => void toggleSelected()}
          disabled={busy || !selected || selected.suite_id === 'EVS_platform_routing'}
          className="h-9 rounded-md border border-slate-200 px-3 text-sm font-medium text-slate-700 disabled:opacity-50"
        >
          {selected?.status === 'inactive' ? '启用测评集' : '停用测评集'}
        </button>
      </div>
      {error ? <p role="alert" className="mt-2 text-xs text-rose-700">{error}</p> : null}
    </section>
  )
}
