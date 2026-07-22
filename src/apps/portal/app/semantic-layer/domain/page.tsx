'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { Card, CardContent } from '@/components/ui/card'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Building2,
  Layers,
  BarChart3,
  Loader2,
  Search,
  Pencil,
  Check,
  X,
  Plus,
  Box,
  ArrowRight,
  Trash2,
  Lock,
  AlertTriangle,
} from 'lucide-react'

// ── API Response Types ──────────────────────────────────────────

interface DomainProgress {
  domain_code: string
  name: string
  total_metrics: number
  mapped_metrics: number
  percentage: number
  skill_refs: number
}

interface SemanticSummary {
  domain_progress: DomainProgress[]
  domains_count: number
  objects_count: number
  metrics_count: number
  mapped_count: number
  unmapped_count: number
  mapping_rate: number
  skill_references: number
}

interface SemanticObject {
  object_code: string
  name: string
  domain_code: string
  status: string
}

interface DomainCard {
  domain_code: string
  name: string
  object_count: number
  metric_count: number
  mapped_count: number
  percentage: number
  skill_refs: number
}

// ── Constants & Helpers ─────────────────────────────────────────

const SUMMARY_API = '/api/v1/medical-insurance-ai-agent/semantic/summary'
const OBJECTS_API = '/api/v1/medical-insurance-ai-agent/semantic/objects'
const SEMANTIC_API = '/api/v1/medical-insurance-ai-agent/semantic'

function progressColor(pct: number): string {
  if (pct >= 100) return 'bg-emerald-500'
  if (pct > 70) return 'bg-blue-500'
  return 'bg-amber-500'
}

function badgeStyle(pct: number): string {
  if (pct >= 100) return 'bg-emerald-50 text-emerald-600 border-emerald-200'
  if (pct > 70) return 'bg-blue-50 text-blue-600 border-blue-200'
  return 'bg-amber-50 text-amber-600 border-amber-200'
}

// ── Delete Confirm Dialog ────────────────────────────────────────

function DeleteConfirmDialog({
  domain,
  onConfirm,
  onCancel,
}: {
  domain: DomainCard
  onConfirm: () => void
  onCancel: () => void
}) {
  const locked = domain.skill_refs > 0
  const hasObjects = domain.object_count > 0

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-6 shadow-xl">
        <div className="flex items-start gap-3">
          <div className={`shrink-0 rounded-full p-2 ${locked ? 'bg-red-50' : 'bg-amber-50'}`}>
            {locked ? (
              <Lock className="h-5 w-5 text-red-500" />
            ) : (
              <AlertTriangle className="h-5 w-5 text-amber-500" />
            )}
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-slate-800">
              {locked ? '无法删除' : '确认删除'}
            </h3>
            <p className="mt-1 text-xs text-slate-600">
              {locked ? (
                <>
                  域 <strong>{domain.name}</strong> 下有{' '}
                  <strong>{domain.skill_refs}</strong> 个指标被 Skill 引用，
                  请先解除引用后再删除。
                </>
              ) : hasObjects ? (
                <>
                  确定要删除域 <strong>{domain.name}</strong>？
                  域下 <strong>{domain.object_count}</strong> 个对象和{' '}
                  <strong>{domain.metric_count}</strong> 个指标将被一并移除。
                </>
              ) : (
                <>
                  确定要删除空域 <strong>{domain.name}</strong>？
                </>
              )}
            </p>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            取消
          </button>
          {!locked && (
            <button
              onClick={onConfirm}
              className="rounded-md bg-red-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-600"
            >
              确认删除
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Inline Edit ──────────────────────────────────────────────────

function InlineEdit({
  value,
  onSave,
  onCancel,
}: {
  value: string
  onSave: (v: string) => void
  onCancel: () => void
}) {
  const [draft, setDraft] = useState(value)

  return (
    <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
      <Input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        className="h-7 w-full rounded-md border border-blue-300 bg-white px-2 text-sm font-semibold focus:border-blue-500 focus:outline-none"
        autoFocus
        onKeyDown={(e) => {
          if (e.key === 'Enter') { onSave(draft) }
          if (e.key === 'Escape') { onCancel() }
        }}
      />
      <button
        onClick={() => onSave(draft)}
        className="shrink-0 rounded p-1 text-emerald-600 hover:bg-emerald-50"
      >
        <Check className="h-3.5 w-3.5" />
      </button>
      <button
        onClick={onCancel}
        className="shrink-0 rounded p-1 text-slate-400 hover:bg-slate-100"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}

// ── Add Domain Form ──────────────────────────────────────────────

function AddDomainForm({
  onAdd,
  onCancel,
}: {
  onAdd: (code: string, name: string) => void
  onCancel: () => void
}) {
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)

  const handleSubmit = useCallback(async () => {
    if (!code.trim() || !name.trim()) return
    setSaving(true)
    try {
      const res = await fetch(`${SEMANTIC_API}/domains`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain_code: code.trim(), name: name.trim() }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
        alert(err.detail || '创建失败')
        setSaving(false)
        return
      }
      onAdd(code.trim(), name.trim())
    } catch {
      alert('网络错误，创建失败')
    }
    setSaving(false)
  }, [code, name, onAdd])

  return (
    <Card className="border-2 border-dashed border-blue-300 bg-blue-50/30 shadow-none">
      <CardContent className="flex flex-col gap-3 px-5 py-4">
        <h4 className="text-xs font-medium text-blue-700">新建业务域</h4>
        <div className="flex items-center gap-3">
          <Input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="域编码 (snake_case)"
            className="h-8 flex-1 rounded-md border border-slate-200 bg-white px-2.5 text-xs"
          />
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="域中文名"
            className="h-8 flex-1 rounded-md border border-slate-200 bg-white px-2.5 text-xs"
          />
          <button
            onClick={handleSubmit}
            disabled={!code.trim() || !name.trim() || saving}
            className="shrink-0 rounded-md bg-blue-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-600 disabled:opacity-40"
          >
            {saving ? '创建中...' : '创建'}
          </button>
          <button
            onClick={onCancel}
            className="shrink-0 rounded-md px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-200"
          >
            取消
          </button>
        </div>
      </CardContent>
    </Card>
  )
}

// ── Domain Card Skeleton ─────────────────────────────────────────

function DomainCardSkeleton() {
  return (
    <Card className="border-slate-200/70 bg-white/80 backdrop-blur shadow-sm">
      <CardContent className="flex flex-col gap-4 px-6 py-6">
        <div className="h-6 w-3/5 animate-pulse rounded bg-slate-200" />
        <div className="h-3 w-full animate-pulse rounded bg-slate-200" />
        <div className="flex items-center gap-6">
          <div className="h-4 w-16 animate-pulse rounded bg-slate-200" />
          <div className="h-4 w-16 animate-pulse rounded bg-slate-200" />
        </div>
      </CardContent>
    </Card>
  )
}

// ── Domain Card ──────────────────────────────────────────────────

function DomainCardItem({
  domain,
  onRename,
  onDelete,
}: {
  domain: DomainCard
  onRename: (code: string, name: string) => void
  onDelete: (domain: DomainCard) => void
}) {
  const [editing, setEditing] = useState(false)
  const locked = domain.skill_refs > 0

  return (
    <div className="group/card relative">
      <Link href={`/semantic-layer/domain/${domain.domain_code}`}>
        <Card className="h-full border-slate-200/70 bg-white/80 backdrop-blur shadow-sm transition-all duration-200 hover:border-blue-400/50 hover:bg-white hover:shadow-md">
          <CardContent className="flex flex-col gap-4 px-6 py-5">
            {/* Domain Name */}
            <div className="flex items-center justify-between">
              {editing ? (
                <InlineEdit
                  value={domain.name}
                  onSave={(v) => { onRename(domain.domain_code, v); setEditing(false) }}
                  onCancel={() => setEditing(false)}
                />
              ) : (
                <h3 className="text-lg font-semibold leading-tight text-slate-800 transition-colors group-hover/card:text-blue-600">
                  {domain.name}
                </h3>
              )}
              <ArrowRight className="h-4 w-4 text-slate-300 transition-all group-hover/card:translate-x-0.5 group-hover/card:text-blue-500" />
            </div>

            {/* Progress Bar */}
            <div className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-500">
                  {domain.mapped_count}/{domain.metric_count} 指标已映射
                </span>
                <Badge variant="outline" className={badgeStyle(domain.percentage)}>
                  {domain.percentage.toFixed(0)}%
                </Badge>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
                <div
                  className={`h-full rounded-full transition-all ${progressColor(domain.percentage)}`}
                  style={{ width: `${Math.min(domain.percentage, 100)}%` }}
                />
              </div>
            </div>

            {/* Stats Row */}
            <div className="flex items-center gap-5 pt-1">
              <div className="flex items-center gap-1.5 text-xs text-slate-500">
                <Box className="h-3.5 w-3.5 text-cyan-500" />
                <span>
                  对象 <span className="font-mono tabular-nums font-medium text-slate-700">{domain.object_count}</span>
                </span>
              </div>
              <div className="flex items-center gap-1.5 text-xs text-slate-500">
                <BarChart3 className="h-3.5 w-3.5 text-purple-500" />
                <span>
                  指标 <span className="font-mono tabular-nums font-medium text-slate-700">{domain.metric_count}</span>
                </span>
              </div>
              {locked && (
                <div className="flex items-center gap-1 text-xs text-amber-600" title={`${domain.skill_refs} 个指标被 Skill 引用`}>
                  <Lock className="h-3 w-3" />
                  <span className="font-mono tabular-nums">{domain.skill_refs}</span>
                </div>
              )}
              <code className="ml-auto font-mono text-[10px] text-slate-400">
                {domain.domain_code}
              </code>
            </div>
          </CardContent>
        </Card>
      </Link>

      {/* Action Buttons — on hover */}
      <div className="absolute right-3 top-3 flex items-center gap-1 opacity-0 transition-opacity group-hover/card:opacity-100">
        <button
          onClick={(e) => { e.preventDefault(); setEditing(true) }}
          className="rounded-md border border-slate-200 bg-white p-1.5 text-slate-500 hover:border-blue-300 hover:text-blue-600 hover:bg-blue-50 shadow-sm"
          title="重命名"
        >
          <Pencil className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={(e) => { e.preventDefault(); onDelete(domain) }}
          className={`rounded-md border p-1.5 shadow-sm ${
            locked
              ? 'border-slate-200 bg-white text-slate-300 cursor-not-allowed'
              : 'border-slate-200 bg-white text-slate-500 hover:border-red-300 hover:text-red-500 hover:bg-red-50'
          }`}
          title={locked ? '被 Skill 引用，无法删除' : '删除域'}
          disabled={locked}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  )
}

// ── Main Page ───────────────────────────────────────────────────

export default function DomainPage() {
  const [domainCards, setDomainCards] = useState<DomainCard[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // UI state
  const [showAddForm, setShowAddForm] = useState(false)
  const [searchText, setSearchText] = useState('')
  const [deletingDomain, setDeletingDomain] = useState<DomainCard | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)

    Promise.all([
      fetch(SUMMARY_API).then((res) => {
        if (!res.ok) throw new Error(`摘要请求失败 (${res.status})`)
        return res.json() as Promise<SemanticSummary>
      }),
      fetch(OBJECTS_API).then((res) => {
        if (!res.ok) throw new Error(`对象请求失败 (${res.status})`)
        return res.json() as Promise<SemanticObject[]>
      }),
    ])
      .then(([summary, objects]) => {
        const objectsByDomain: Record<string, number> = {}
        for (const obj of objects) {
          objectsByDomain[obj.domain_code] = (objectsByDomain[obj.domain_code] || 0) + 1
        }

        const cards: DomainCard[] = summary.domain_progress.map((dp) => ({
          domain_code: dp.domain_code,
          name: dp.name,
          object_count: objectsByDomain[dp.domain_code] ?? 0,
          metric_count: dp.total_metrics,
          mapped_count: dp.mapped_metrics,
          percentage: dp.percentage,
          skill_refs: dp.skill_refs ?? 0,
        }))

        setDomainCards(cards)
        setLoading(false)
      })
      .catch((err: Error) => {
        setError(err.message)
        setLoading(false)
      })
  }, [])

  // Handle rename
  const handleRename = useCallback(
    async (domainCode: string, newName: string) => {
      if (!newName.trim()) return
      setDomainCards((prev) =>
        prev.map((d) =>
          d.domain_code === domainCode ? { ...d, name: newName } : d,
        ),
      )
      try {
        await fetch(`${SEMANTIC_API}/domains/${encodeURIComponent(domainCode)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: newName }),
        })
      } catch {
        // Optimistic update already done
      }
    },
    [],
  )

  // Handle add domain
  const handleAddDomain = useCallback(
    (code: string, name: string) => {
      setDomainCards((prev) => [
        ...prev,
        {
          domain_code: code,
          name,
          object_count: 0,
          metric_count: 0,
          mapped_count: 0,
          percentage: 0,
          skill_refs: 0,
        },
      ])
      setShowAddForm(false)
    },
    [],
  )

  // Handle delete domain
  const handleDeleteConfirm = useCallback(async () => {
    if (!deletingDomain) return
    const code = deletingDomain.domain_code
    try {
      const res = await fetch(`${SEMANTIC_API}/domains/${encodeURIComponent(code)}`, {
        method: 'DELETE',
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
        alert(err.detail || '删除失败')
        setDeletingDomain(null)
        return
      }
      setDomainCards((prev) => prev.filter((d) => d.domain_code !== code))
    } catch {
      alert('网络错误，删除失败')
    }
    setDeletingDomain(null)
  }, [deletingDomain])

  // Filtered domains
  const filteredCards = useMemo(() => {
    if (!searchText.trim()) return domainCards
    const q = searchText.trim().toLowerCase()
    return domainCards.filter(
      (d) =>
        d.name.toLowerCase().includes(q) ||
        d.domain_code.toLowerCase().includes(q),
    )
  }, [domainCards, searchText])

  // ── Loading State ──────────────────────────────────────────
  if (loading) {
    return (
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <DomainCardSkeleton key={i} />
        ))}
      </div>
    )
  }

  // ── Error State ────────────────────────────────────────────
  if (error) {
    return (
      <Alert variant="destructive" className="border-red-200 bg-red-50">
        <AlertTitle className="text-red-600">数据加载失败</AlertTitle>
        <AlertDescription className="text-red-600">{error}</AlertDescription>
      </Alert>
    )
  }

  // ── Empty State ────────────────────────────────────────────
  if (domainCards.length === 0) {
    return (
      <div className="flex flex-col gap-6">
        <div className="flex flex-col items-center justify-center gap-4 py-16 text-slate-500">
          <Layers className="h-12 w-12 text-slate-400" />
          <p className="text-base">暂无领域数据</p>
          <button
            onClick={() => setShowAddForm(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-600 hover:bg-blue-100"
          >
            <Plus className="h-3.5 w-3.5" />
            创建第一个域
          </button>
        </div>
        {showAddForm && <AddDomainForm onAdd={handleAddDomain} onCancel={() => setShowAddForm(false)} />}
      </div>
    )
  }

  // ── Card Grid ──────────────────────────────────────────────
  return (
    <div className="flex flex-col gap-5">
      {/* ── Quick Stats ──────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card className="border-slate-200 bg-white shadow-sm">
          <CardContent className="px-4 py-3">
            <div className="text-[11px] text-slate-500">域总数</div>
            <div className="text-xl font-bold tabular-nums text-blue-600">
              {domainCards.length}
            </div>
          </CardContent>
        </Card>
        <Card className="border-slate-200 bg-white shadow-sm">
          <CardContent className="px-4 py-3">
            <div className="text-[11px] text-slate-500">对象总数</div>
            <div className="text-xl font-bold tabular-nums text-cyan-600">
              {domainCards.reduce((s, d) => s + d.object_count, 0)}
            </div>
          </CardContent>
        </Card>
        <Card className="border-slate-200 bg-white shadow-sm">
          <CardContent className="px-4 py-3">
            <div className="text-[11px] text-slate-500">指标总数</div>
            <div className="text-xl font-bold tabular-nums text-purple-600">
              {domainCards.reduce((s, d) => s + d.metric_count, 0)}
            </div>
          </CardContent>
        </Card>
        <Card className="border-slate-200 bg-white shadow-sm">
          <CardContent className="px-4 py-3">
            <div className="text-[11px] text-slate-500">已映射</div>
            <div className="text-xl font-bold tabular-nums text-emerald-600">
              {domainCards.reduce((s, d) => s + d.mapped_count, 0)}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── Filters + Add Button ─────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="relative w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
          <Input
            type="text"
            placeholder="搜索域名称或编码..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            className="h-8 rounded-md border border-slate-300 bg-white pl-8 text-xs text-slate-700 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none"
          />
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">
            共 <span className="font-mono text-slate-600">{filteredCards.length}</span> 个域
          </span>
          <button
            onClick={() => setShowAddForm((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-600 hover:bg-blue-100"
          >
            {showAddForm ? '收起' : <><Plus className="h-3.5 w-3.5" />新建域</>}
          </button>
        </div>
      </div>

      {/* ── Add Form ─────────────────────────────────────────── */}
      {showAddForm && <AddDomainForm onAdd={handleAddDomain} onCancel={() => setShowAddForm(false)} />}

      {/* ── Card Grid ────────────────────────────────────────── */}
      {filteredCards.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-4 py-16 text-slate-500">
          <Building2 className="h-12 w-12 text-slate-300" />
          <p className="text-base">无匹配的域</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {filteredCards.map((domain) => (
            <DomainCardItem
              key={domain.domain_code}
              domain={domain}
              onRename={handleRename}
              onDelete={setDeletingDomain}
            />
          ))}
        </div>
      )}

      {/* ── Delete Confirm Dialog ────────────────────────────── */}
      {deletingDomain && (
        <DeleteConfirmDialog
          domain={deletingDomain}
          onConfirm={handleDeleteConfirm}
          onCancel={() => setDeletingDomain(null)}
        />
      )}
    </div>
  )
}
