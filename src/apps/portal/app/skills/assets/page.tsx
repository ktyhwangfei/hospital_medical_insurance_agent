'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'

import { listInfraSkillCatalog } from '@/lib/api-client'
import type { InfraSkillCatalogItem } from '@/lib/types'

export default function SkillAssetsPage() {
  const [items, setItems] = useState<InfraSkillCatalogItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let current = true
    listInfraSkillCatalog({ page: 1, page_size: 50 })
      .then((response) => {
        if (current) setItems(response.items)
      })
      .catch((reason: unknown) => {
        if (current) setError(reason instanceof Error ? reason.message : '无法加载 Skill 资产')
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => { current = false }
  }, [])

  return (
    <section aria-labelledby="skill-assets-title" className="space-y-6 py-6">
      <div>
        <h2 id="skill-assets-title" className="text-xl font-semibold text-slate-950">Skill 资产</h2>
        <p className="mt-1 text-sm text-slate-500">浏览已发现的 Skill 与登记版本</p>
      </div>
      {error && <p role="alert" className="border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>}
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        {loading ? (
          <p className="p-4 text-sm text-slate-500">正在加载 Skill 资产…</p>
        ) : items.length === 0 ? (
          <p className="p-4 text-sm text-slate-500">暂无 Skill 资产</p>
        ) : (
          <ul className="divide-y divide-slate-200">
            {items.map((item) => (
              <li key={item.skill_id}>
                <Link
                  href={`/skills/${encodeURIComponent(item.skill_id)}`}
                  className="flex min-h-11 items-center justify-between gap-4 px-4 py-3 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-slate-900">{item.skill_name}</span>
                    <span className="block truncate font-mono text-xs text-slate-500">{item.skill_id}</span>
                  </span>
                  <span className="shrink-0 text-xs text-slate-500">v{item.semantic_version}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
