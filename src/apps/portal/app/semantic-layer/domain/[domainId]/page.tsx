'use client'

import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  ChevronDown,
  ChevronRight,
  FileText,
  FolderOpen,
  Loader2,
  ArrowLeft,
  Layers,
  BarChart3,
} from 'lucide-react'

// ── Types ───────────────────────────────────────────────────────

interface SemanticObject {
  object_code: string
  name: string
  definition?: string
  domain_code: string
  status: string
}

interface MetricItem {
  metric_code: string
  name: string
  object_code: string
}

interface TreeNode {
  id: string
  label: string
  children?: TreeNode[]
  isLeaf?: boolean
  objectCode?: string
}

interface ObjectCardData {
  object_code: string
  name: string
  definition?: string
  metric_count: number
}

// ── Constants ───────────────────────────────────────────────────

const OBJECTS_API = '/api/v1/medical-insurance-ai-agent/semantic/objects'
const METRICS_API = '/api/v1/medical-insurance-ai-agent/semantic/metrics'

// ── Recursive Tree Node Component ───────────────────────────────

function TreeNodeItem({
  node,
  depth = 0,
  selectedId,
  onSelect,
}: {
  node: TreeNode
  depth?: number
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const [expanded, setExpanded] = useState(depth < 2)

  const toggle = useCallback(() => {
    if (!node.isLeaf) setExpanded((prev) => !prev)
  }, [node.isLeaf])

  const handleClick = useCallback(() => {
    if (node.isLeaf && node.objectCode) {
      onSelect(node.objectCode)
    } else {
      toggle()
    }
  }, [node.isLeaf, node.objectCode, onSelect, toggle])

  const isSelected = node.isLeaf && selectedId === node.objectCode

  return (
    <div>
      <button
        type="button"
        onClick={handleClick}
        className={`flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-sm transition-colors ${
          isSelected
            ? 'bg-blue-50 text-blue-600'
            : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700'
        }`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {/* Expand/Collapse Icon */}
        {!node.isLeaf ? (
          <span className="shrink-0 text-slate-500">
            {expanded ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
          </span>
        ) : (
          <span className="shrink-0 text-slate-400">
            <FileText className="h-3.5 w-3.5" />
          </span>
        )}

        {/* Label */}
        <span className="truncate">{node.label}</span>

        {/* Leaf indicator badge */}
        {node.isLeaf && node.objectCode && (
          <span className="ml-auto shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
            {node.objectCode}
          </span>
        )}
      </button>

      {/* Children */}
      {!node.isLeaf && expanded && node.children && node.children.length > 0 && (
        <div>
          {node.children.map((child) => (
            <TreeNodeItem
              key={child.id}
              node={child}
              depth={depth + 1}
              selectedId={selectedId}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Object Card ─────────────────────────────────────────────────

function ObjectCardItem({ obj }: { obj: ObjectCardData }) {
  return (
    <Link href={`/semantic-layer/object?object_code=${obj.object_code}`}>
      <Card className="group h-full border-slate-200/70 bg-white/80 backdrop-blur shadow-sm transition-all duration-200 hover:border-blue-400/50 hover:bg-white hover:shadow-md">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-slate-800 transition-colors group-hover:text-blue-600">
            <FileText className="h-4 w-4 shrink-0 text-slate-400 group-hover:text-blue-600" />
            <span className="truncate">{obj.name}</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {/* Description */}
          <p className="line-clamp-2 text-xs leading-relaxed text-slate-500">
            {obj.definition || '暂无描述'}
          </p>

          {/* Metrics count badge */}
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            <BarChart3 className="h-3 w-3 text-purple-500" />
            <span>
              指标 <span className="font-mono tabular-nums text-slate-600">{obj.metric_count}</span>
            </span>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}

// ── Helpers ─────────────────────────────────────────────────────

/** Build a tree from objects grouped by status */
function buildTree(objects: SemanticObject[]): TreeNode {
  const groups: Record<string, SemanticObject[]> = {}
  for (const obj of objects) {
    const key = obj.status || 'unknown'
    if (!groups[key]) groups[key] = []
    groups[key].push(obj)
  }

  const statusLabels: Record<string, string> = {
    published: '已发布',
    draft: '草稿',
    deprecated: '已弃用',
    unknown: '未知',
  }

  const children: TreeNode[] = Object.entries(groups)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([status, items]) => ({
      id: `status-${status}`,
      label: `${statusLabels[status] || status} (${items.length})`,
      children: items.map((obj) => ({
        id: `obj-${obj.object_code}`,
        label: obj.name,
        isLeaf: true,
        objectCode: obj.object_code,
      })),
    }))

  return {
    id: 'root',
    label: `全部对象 (${objects.length})`,
    children,
  }
}

/** Fetch metric count for a single object */
async function fetchMetricCount(objectCode: string): Promise<number> {
  try {
    const res = await fetch(`${METRICS_API}?object_code=${encodeURIComponent(objectCode)}`)
    if (!res.ok) return 0
    const data = (await res.json()) as MetricItem[]
    return Array.isArray(data) ? data.length : 0
  } catch {
    return 0
  }
}

// ── Main Page ───────────────────────────────────────────────────

export default function DomainDetailPage() {
  const params = useParams()
  const domainId = params.domainId as string

  const [objects, setObjects] = useState<SemanticObject[]>([])
  const [objectCards, setObjectCards] = useState<ObjectCardData[]>([])
  const [selectedCode, setSelectedCode] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMetrics, setLoadingMetrics] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Fetch objects for this domain
  useEffect(() => {
    setLoading(true)
    setError(null)

    fetch(`${OBJECTS_API}?domain_code=${encodeURIComponent(domainId)}`)
      .then((res) => {
        if (!res.ok) throw new Error(`请求失败 (${res.status})`)
        return res.json() as Promise<SemanticObject[]>
      })
      .then((data) => {
        const list = Array.isArray(data) ? data : []
        setObjects(list)
        setLoading(false)
      })
      .catch((err: Error) => {
        setError(err.message)
        setLoading(false)
      })
  }, [domainId])

  // Fetch metrics for all objects in parallel
  useEffect(() => {
    if (objects.length === 0) {
      setObjectCards([])
      return
    }

    setLoadingMetrics(true)

    Promise.all(
      objects.map(async (obj) => {
        const count = await fetchMetricCount(obj.object_code)
        return {
          object_code: obj.object_code,
          name: obj.name,
          definition: obj.definition,
          metric_count: count,
        } satisfies ObjectCardData
      }),
    )
      .then((cards) => {
        setObjectCards(cards)
        setLoadingMetrics(false)
      })
      .catch(() => {
        // Fall back to showing objects without metric counts
        setObjectCards(
          objects.map((obj) => ({
            object_code: obj.object_code,
            name: obj.name,
            definition: obj.definition,
            metric_count: 0,
          })),
        )
        setLoadingMetrics(false)
      })
  }, [objects])

  const tree = objects.length > 0 ? buildTree(objects) : null

  // Scroll selected object card into view
  useEffect(() => {
    if (selectedCode) {
      const el = document.getElementById(`object-card-${selectedCode}`)
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [selectedCode])

  // ── Loading State ──────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex gap-6">
        {/* Sidebar skeleton */}
        <aside className="hidden w-[260px] shrink-0 lg:block">
          <Card className="border-slate-200/70 bg-white/80 backdrop-blur shadow-sm">
            <CardContent className="flex flex-col gap-2 px-4 py-4">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-8 w-full animate-pulse rounded bg-slate-200" />
              ))}
            </CardContent>
          </Card>
        </aside>

        {/* Content skeleton */}
        <div className="min-w-0 flex-1">
          <div className="mb-4 h-5 w-32 animate-pulse rounded bg-slate-200" />
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Card key={i} className="border-slate-200/70 bg-white/80 backdrop-blur shadow-sm">
                <CardContent className="flex flex-col gap-3 px-5 py-5">
                  <div className="h-4 w-3/5 animate-pulse rounded bg-slate-200" />
                  <div className="h-3 w-full animate-pulse rounded bg-slate-200" />
                  <div className="h-3 w-16 animate-pulse rounded bg-slate-200" />
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
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
  if (objects.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        {/* Back navigation */}
        <Link
          href="/semantic-layer/domain"
          className="flex w-fit items-center gap-1.5 text-sm text-slate-500 transition-colors hover:text-blue-600"
        >
          <ArrowLeft className="h-4 w-4" />
          返回领域列表
        </Link>

        <div className="flex flex-col items-center justify-center gap-4 py-20 text-slate-500">
          <FolderOpen className="h-12 w-12 text-slate-400" />
          <p className="text-base">该领域暂无对象</p>
        </div>
      </div>
    )
  }

  // ── Normal Render ──────────────────────────────────────────
  return (
    <div className="flex flex-col gap-6">
      {/* ── Header with Breadcrumb ──────────────────────────── */}
      <header className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">
            语义层
          </span>
          <Link href="/semantic-layer/domain" className="text-xs text-slate-500 transition-colors hover:text-blue-600">
            域管理
          </Link>
          <span className="text-xs text-slate-400">/</span>
          <span className="text-xs text-slate-700">{domainId}</span>
        </div>
        <h2 className="text-xl font-semibold tracking-tight text-slate-900">
          对象列表
          <span className="ml-2 font-mono text-sm font-normal text-slate-500">({objectCards.length})</span>
        </h2>
        {loadingMetrics && (
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            <Loader2 className="h-3 w-3 animate-spin" />
            加载指标数据...
          </div>
        )}
      </header>

      <div className="flex flex-col gap-6 lg:flex-row">
        {/* ── Left Sidebar: Object Tree ────────────────────────── */}
        <aside className="w-full shrink-0 lg:w-[260px]">
          <Card className="border-slate-200/70 bg-white/80 backdrop-blur shadow-sm">
            <CardHeader className="border-b border-slate-200 pb-3">
              <CardTitle className="flex items-center gap-2 text-sm font-medium text-slate-700">
                <Layers className="h-4 w-4 text-cyan-500" />
                对象导航
              </CardTitle>
            </CardHeader>
            <CardContent className="px-3 py-3">
              {tree && (
                <TreeNodeItem
                  node={tree}
                  depth={0}
                  selectedId={selectedCode}
                  onSelect={setSelectedCode}
                />
              )}
            </CardContent>
          </Card>
        </aside>

        {/* ── Right Content Area ──────────────────────────────── */}
        <div className="min-w-0 flex-1">
          {/* Object Cards Grid */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {objectCards.map((obj) => (
              <div key={obj.object_code} id={`object-card-${obj.object_code}`}>
                <ObjectCardItem obj={obj} />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
