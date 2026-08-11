'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'

import { listInfraSkillCatalog } from '@/lib/api-client'
import type { InfraSkillCatalogItem } from '@/lib/types'

const PAGE_SIZE = 50

function appendUnique(current: InfraSkillCatalogItem[], incoming: InfraSkillCatalogItem[]): InfraSkillCatalogItem[] {
  const seen = new Set(current.map((item) => item.skill_id))
  return current.concat(incoming.filter((item) => !seen.has(item.skill_id) && seen.add(item.skill_id)))
}

export default function SkillAssetsPage() {
  const [items, setItems] = useState<InfraSkillCatalogItem[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [hasPagination, setHasPagination] = useState(false)

  useEffect(() => {
    let current = true
    listInfraSkillCatalog({ page: 1, page_size: PAGE_SIZE })
      .then((response) => {
        if (!current) return
        setItems(appendUnique([], response.items))
        setPage(response.page)
        setTotal(response.total)
        setHasPagination(response.total > response.items.length)
      })
      .catch((reason: unknown) => {
        if (current) setError(reason instanceof Error ? reason.message : '无法加载 Skill 资产')
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => { current = false }
  }, [])

  async function loadMore(): Promise<void> {
    if (loadingMore || items.length >= total) return
    setLoadingMore(true)
    setError(null)
    try {
      const response = await listInfraSkillCatalog({ page: page + 1, page_size: PAGE_SIZE })
      setItems((current) => appendUnique(current, response.items))
      setPage(response.page)
      setTotal(response.total)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法加载更多 Skill 资产')
    } finally {
      setLoadingMore(false)
    }
  }

  return (
    <section aria-labelledby="skill-assets-title" className="space-y-6 py-6">
      <div>
        <h2 id="skill-assets-title" className="text-xl font-semibold text-slate-950">Skill 资产</h2>
        <p className="mt-1 text-sm text-slate-500">浏览已发现的 Skill 与登记版本</p>
      </div>
      {error && items.length > 0 && <p role="alert" className="border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>}
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        {loading ? (
          <p className="p-4 text-sm text-slate-500">正在加载 Skill 资产…</p>
        ) : error && items.length === 0 ? (
          <p role="alert" className="bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>
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
        {!loading && hasPagination && (
          <div className="border-t border-slate-200 p-3 text-center">
            <button
              type="button"
              aria-disabled={loadingMore || items.length >= total}
              aria-live="polite"
              onClick={() => void loadMore()}
              className="min-h-11 rounded-lg px-4 text-sm font-medium text-blue-600 hover:bg-blue-50 aria-disabled:text-slate-400"
            >
              {loadingMore ? '正在加载…' : items.length >= total ? '已加载全部 Skill 资产' : '加载更多'}
            </button>
          </div>
        )}
      </div>
    </section>
  )
}
