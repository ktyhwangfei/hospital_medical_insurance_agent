'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { Card, CardContent } from '@/components/ui/card'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Box, FileText, Loader2, Search, Layers, Pencil, Check, X, Plus, Trash2, AlertTriangle,
  ChevronDown, ChevronUp, ShieldCheck, ShieldAlert, History,
} from 'lucide-react'

// ── Types ───────────────────────────────────────────────────────

interface SemanticObject {
  object_code: string
  name: string
  definition?: string
  domain_code: string
  domain_name?: string
  status: string
  identifier?: string
  version?: string
  current_version?: string | null
}

interface DomainInfo {
  domain_code: string
  name: string
}

// ── Constants ───────────────────────────────────────────────────

const SEMANTIC_API = '/api/v1/medical-insurance-ai-agent/semantic'

const STATUS_LABELS: Record<string, string> = {
  published: '已发布', draft: '草稿', deprecated: '已弃用',
}
const STATUS_COLORS: Record<string, string> = {
  published: 'bg-emerald-50 text-emerald-600 border-emerald-200',
  draft: 'bg-amber-50 text-amber-600 border-amber-200',
  deprecated: 'bg-slate-100 text-slate-500 border-slate-200',
}
const STATUS_BTN: Record<string, string> = {
  draft: 'bg-amber-500 hover:bg-amber-600',
  published: 'bg-emerald-600 hover:bg-emerald-700',
  deprecated: 'bg-slate-400 hover:bg-slate-500',
}

// ── Helpers ─────────────────────────────────────────────────────

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    throw new Error(err.detail || `请求失败 (${res.status})`)
  }
  return res.json() as Promise<T>
}

// ── Publish Check Dialog ────────────────────────────────────────

function PublishCheckDialog({ obj, onCancel, onPublished }: {
  obj: SemanticObject; onCancel: () => void; onPublished: () => void
}) {
  const [checking, setChecking] = useState(true)
  const [result, setResult] = useState<{ ok: boolean; skills: string[]; warnings: string[] } | null>(null)

  useEffect(() => {
    (async () => {
      try {
        // 获取该对象的所有指标，检查哪些 skill 引用了它们
        const metrics = await fetchJson<any[]>(`${SEMANTIC_API}/metrics?object_code=${encodeURIComponent(obj.object_code)}`)
        const usedMetrics = metrics.filter((m: any) => m.usage_count > 0)
        const skillNames = [...new Set(usedMetrics.map((m: any) => m.metric_code))]
        // 简化版质量检查：有引用 → 需人工确认
        const warnings: string[] = []
        if (usedMetrics.length === 0) {
          warnings.push('该对象下无可被 Skill 引用的指标，发布后可能无实际作用')
        } else {
          warnings.push(`${usedMetrics.length} 个指标被 ${usedMetrics.reduce((s: number, m: any) => s + m.usage_count, 0)} 个 Skill 引用`)
          warnings.push('请确认相关 Skill 测试通过后再发布')
        }
        setResult({ ok: true, skills: skillNames, warnings })
      } catch (err: any) {
        setResult({ ok: false, skills: [], warnings: [err.message || '质量检查失败'] })
      }
      setChecking(false)
    })()
  }, [obj.object_code])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-xl">
        <div className="flex items-start gap-3">
          <div className="shrink-0 rounded-full bg-blue-50 p-2">
            <ShieldCheck className="h-5 w-5 text-blue-500" />
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-slate-800">发布前质量检查</h3>
            <p className="text-xs text-slate-500">对象: {obj.name}</p>
          </div>
        </div>

        <div className="mt-4 space-y-2">
          {checking ? (
            <div className="flex items-center gap-2 py-4 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              检查中...
            </div>
          ) : result ? (
            <>
              {result.warnings.map((w, i) => (
                <div key={i} className="flex items-start gap-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
                  <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                  {w}
                </div>
              ))}
              {!result.ok && (
                <div className="flex items-start gap-2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-600">
                  <ShieldAlert className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                  质量检查未通过，无法发布
                </div>
              )}
            </>
          ) : null}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onCancel} className="rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">取消</button>
          {result?.ok && (
            <button onClick={onPublished} className="rounded-md bg-emerald-500 px-4 py-1.5 text-xs font-medium text-white hover:bg-emerald-600">
              确认发布
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Version History Dialog ─────────────────────────────────────

interface ObjectVersionInfo {
  version_id: string
  object_code: string
  version: string
  published_at: string
  published_by?: string | null
  changelog?: string | null
  metric_count: number
}

function VersionHistoryDialog({ obj, onClose }: { obj: SemanticObject; onClose: () => void }) {
  const [versions, setVersions] = useState<ObjectVersionInfo[]>([])
  const [locks, setLocks] = useState<{ skill_id: string; locked_version: string | null }[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([
      fetchJson<ObjectVersionInfo[]>(`${SEMANTIC_API}/objects/${encodeURIComponent(obj.object_code)}/versions`),
      fetchJson<{ locked_by_skills?: { skill_id: string; locked_version: string | null }[] }>(`${SEMANTIC_API}/objects/${encodeURIComponent(obj.object_code)}`),
    ]).then(([vs, d]) => {
      setVersions(Array.isArray(vs) ? vs : [])
      setLocks(d.locked_by_skills ?? [])
    }).catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [obj.object_code])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="flex max-h-[80vh] w-full max-w-lg flex-col rounded-xl border border-slate-200 bg-white p-6 shadow-xl">
        <div className="flex items-start gap-3">
          <div className="shrink-0 rounded-full bg-purple-50 p-2"><History className="h-5 w-5 text-purple-500" /></div>
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-slate-800">版本历史</h3>
            <p className="text-xs text-slate-500">{obj.name}（<code className="text-[10px]">{obj.object_code}</code>）</p>
          </div>
          <button onClick={onClose} className="rounded-md p-1 text-slate-400 hover:bg-slate-100"><X className="h-4 w-4" /></button>
        </div>

        {/* locked_by_skills */}
        {locks.length > 0 && (
          <div className="mt-3 rounded-md bg-blue-50 px-3 py-2 text-xs text-blue-700">
            <span className="font-medium">技能锁定：</span>
            {locks.map((l, i) => (
              <span key={i} className="ml-1">
                {l.skill_id}{l.locked_version ? `@v${l.locked_version}` : '（跟随最新）'}
                {i < locks.length - 1 ? '、' : ''}
              </span>
            ))}
          </div>
        )}

        <div className="mt-4 flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center gap-2 py-8 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />加载中...</div>
          ) : error ? (
            <div className="py-8 text-center text-sm text-red-500">{error}</div>
          ) : versions.length === 0 ? (
            <div className="py-8 text-center text-sm text-slate-400">尚未发布任何版本</div>
          ) : (
            <div className="space-y-2">
              {[...versions].reverse().map((v) => (
                <div key={v.version_id} className={`rounded-lg border px-3 py-2 ${v.version === obj.current_version ? 'border-emerald-300 bg-emerald-50/50' : 'border-slate-200 bg-slate-50/50'}`}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="rounded-md bg-slate-700 px-2 py-0.5 font-mono text-[10px] font-medium text-white">v{v.version}</span>
                      {v.version === obj.current_version && <Badge variant="outline" className="text-[9px] text-emerald-600 border-emerald-300">当前</Badge>}
                      <span className="text-xs text-slate-500">{v.metric_count} 个指标</span>
                    </div>
                    <span className="text-[10px] text-slate-400">{new Date(v.published_at).toLocaleString('zh-CN')}</span>
                  </div>
                  {v.changelog && <p className="mt-1 text-xs text-slate-600">{v.changelog}</p>}
                  {v.published_by && <p className="text-[10px] text-slate-400">发布人：{v.published_by}</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Delete Confirm ───────────────────────────────────────────────

function DeleteConfirmDialog({ obj, onConfirm, onCancel }: {
  obj: SemanticObject; onConfirm: () => void; onCancel: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-6 shadow-xl">
        <div className="flex items-start gap-3">
          <div className="shrink-0 rounded-full bg-amber-50 p-2"><AlertTriangle className="h-5 w-5 text-amber-500" /></div>
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-slate-800">确认删除</h3>
            <p className="mt-1 text-xs text-slate-600">确定要删除对象 <strong>{obj.name}</strong>（<code className="text-[10px]">{obj.object_code}</code>）？</p>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onCancel} className="rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">取消</button>
          <button onClick={onConfirm} className="rounded-md bg-red-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-600">确认删除</button>
        </div>
      </div>
    </div>
  )
}

// ── Add Object Form ──────────────────────────────────────────────

function AddObjectForm({ domains, onAdd, onCancel }: {
  domains: DomainInfo[]; onAdd: (obj: SemanticObject) => void; onCancel: () => void
}) {
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [domainCode, setDomainCode] = useState(domains[0]?.domain_code ?? '')
  const [definition, setDefinition] = useState('')
  const [saving, setSaving] = useState(false)

  const handleSubmit = useCallback(async () => {
    if (!code.trim() || !name.trim() || !domainCode) return
    setSaving(true)
    try {
      await fetchJson(`${SEMANTIC_API}/objects`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ object_code: code.trim(), domain_code: domainCode, name: name.trim(), definition: definition.trim() || null }),
      })
      onAdd({ object_code: code.trim(), name: name.trim(), domain_code: domainCode, definition: definition.trim() || undefined, status: 'draft' })
    } catch (err: any) { alert(err.message) }
    setSaving(false)
  }, [code, name, domainCode, definition, onAdd])

  return (
    <Card className="border-2 border-dashed border-cyan-300 bg-cyan-50/30 shadow-none">
      <CardContent className="flex flex-col gap-3 px-5 py-4">
        <h4 className="text-xs font-medium text-cyan-700">新建业务对象</h4>
        <div className="grid grid-cols-2 gap-2">
          <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="对象编码 (PascalCase)" className="h-8 text-xs" />
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="对象中文名" className="h-8 text-xs" />
          <select value={domainCode} onChange={(e) => setDomainCode(e.target.value)} className="h-8 rounded-md border border-slate-200 bg-white px-2 text-xs text-slate-700">
            {domains.map((d) => <option key={d.domain_code} value={d.domain_code}>{d.name}</option>)}
          </select>
          <Input value={definition} onChange={(e) => setDefinition(e.target.value)} placeholder="业务定义（可选）" className="h-8 text-xs" />
        </div>
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="rounded-md px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-200">取消</button>
          <button onClick={handleSubmit} disabled={!code.trim() || !name.trim() || !domainCode || saving} className="rounded-md bg-cyan-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-cyan-600 disabled:opacity-40">
            {saving ? '创建中...' : '创建'}
          </button>
        </div>
      </CardContent>
    </Card>
  )
}

// ── Object Card Row (with expandable edit) ──────────────────────

function ObjectCardRow({ obj, domainName, domains, onSave, onDelete }: {
  obj: SemanticObject
  domainName: string
  domains: DomainInfo[]
  onSave: (updated: SemanticObject) => void
  onDelete: (obj: SemanticObject) => void
}) {
  const [editDraft, setEditDraft] = useState<Record<string, string> | null>(null)
  const [saving, setSaving] = useState(false)
  const [showPublishCheck, setShowPublishCheck] = useState(false)
  const [showVersionHistory, setShowVersionHistory] = useState(false)

  const startEdit = useCallback(() => {
    setEditDraft({
      name: obj.name,
      definition: obj.definition || '',
      domain_code: obj.domain_code,
      identifier: obj.identifier || '',
      version: obj.version || '1.0',
    })
  }, [obj])

  const handleSave = useCallback(async () => {
    if (!editDraft) return
    setSaving(true)
    const body: Record<string, string> = {}
    const def = editDraft.definition.trim()
    if (editDraft.name !== obj.name) body.name = editDraft.name
    if (def !== (obj.definition || '')) body.definition = def
    if (editDraft.domain_code !== obj.domain_code) body.domain_code = editDraft.domain_code
    if (editDraft.identifier !== (obj.identifier || '')) body.identifier = editDraft.identifier
    if (editDraft.version !== (obj.version || '1.0')) body.version = editDraft.version
    try {
      await fetchJson(`${SEMANTIC_API}/objects/${encodeURIComponent(obj.object_code)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      })
      onSave({
        ...obj,
        name: editDraft.name,
        definition: def || undefined,
        domain_code: editDraft.domain_code,
        identifier: editDraft.identifier || undefined,
        version: editDraft.version,
      })
      setEditDraft(null)
    } catch (err: any) { alert(err.message) }
    setSaving(false)
  }, [editDraft, obj, onSave])

  const handleStatusChange = useCallback(async (newStatus: string) => {
    if (newStatus === 'published') {
      setShowPublishCheck(true)
      return
    }
    try {
      await fetchJson(`${SEMANTIC_API}/objects/${encodeURIComponent(obj.object_code)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      })
      onSave({ ...obj, status: newStatus })
    } catch (err: any) { alert(err.message) }
  }, [obj, onSave])

  const handlePublish = useCallback(async () => {
    try {
      const result = await fetchJson<{ version: string }>(`${SEMANTIC_API}/objects/${encodeURIComponent(obj.object_code)}/publish`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ changelog: '前端发布' }),
      })
      onSave({ ...obj, status: 'published', current_version: result.version })
      setShowPublishCheck(false)
    } catch (err: any) { alert(err.message) }
  }, [obj, onSave])

  const editing = editDraft !== null

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm transition-all hover:border-blue-300 hover:shadow-md">
      {/* ── Card Header ── */}
      <div className="flex items-center gap-4 px-5 py-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-cyan-50 text-cyan-600">
          <FileText className="h-5 w-5" />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-800 truncate">{obj.name}</span>
            <code className="font-mono text-[10px] text-slate-400">{obj.object_code}</code>
          </div>
          <div className="mt-0.5 flex items-center gap-3 text-xs text-slate-500">
            <span className="flex items-center gap-1"><Layers className="h-3 w-3 text-blue-500" />{domainName}</span>
            {obj.current_version
              ? <span className="font-mono text-emerald-500">已发布 v{obj.current_version}</span>
              : <span className="font-mono text-slate-400">未发布</span>}
          </div>
          {obj.definition && (
            <p className="mt-1 line-clamp-2 text-xs text-slate-500">{obj.definition}</p>
          )}
        </div>

        {/* Status button */}
        <div className="flex items-center gap-1 shrink-0">
          <div className="relative group/status">
            <Badge variant="outline" className={`cursor-pointer text-[10px] ${STATUS_COLORS[obj.status] ?? STATUS_COLORS.draft}`}>
              {STATUS_LABELS[obj.status] || obj.status}
            </Badge>
            {/* Status dropdown on hover */}
            <div className="absolute right-0 top-full mt-1 hidden group-hover/status:block z-10">
              <div className="rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
                {['draft', 'published', 'deprecated'].filter(s => s !== obj.status).map(s => (
                  <button key={s} onClick={() => handleStatusChange(s)} className="block w-full px-3 py-1.5 text-left text-xs text-slate-600 hover:bg-slate-50 whitespace-nowrap">
                    切换为{STATUS_LABELS[s]}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <button onClick={startEdit} className="rounded-md p-1.5 text-slate-400 hover:text-blue-600 hover:bg-blue-50" title="编辑">
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button onClick={() => onDelete(obj)} className="rounded-md p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50" title="删除">
            <Trash2 className="h-3.5 w-3.5" />
          </button>
          <button onClick={() => setShowVersionHistory(true)} className="rounded-md p-1.5 text-slate-400 hover:text-purple-600 hover:bg-purple-50" title="版本历史">
            <History className="h-3.5 w-3.5" />
          </button>
          <button onClick={() => editing ? setEditDraft(null) : startEdit()} className="rounded-md p-1.5 text-slate-400 hover:text-slate-600" title={editing ? '收起' : '展开'}>
            {editing ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>

      {/* ── Expandable Edit Form ── */}
      {editing && (
        <div className="border-t border-slate-200 bg-slate-50/50 px-5 py-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-[11px] text-slate-500">名称</label>
              <Input value={editDraft.name} onChange={(e) => setEditDraft((d) => d ? { ...d, name: e.target.value } : d)} className="h-8 text-xs" />
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-slate-500">所属域</label>
              <select value={editDraft.domain_code} onChange={(e) => setEditDraft((d) => d ? { ...d, domain_code: e.target.value } : d)} className="h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs">
                {domains.map((d) => <option key={d.domain_code} value={d.domain_code}>{d.name} ({d.domain_code})</option>)}
              </select>
            </div>
            <div className="col-span-2">
              <label className="mb-1 block text-[11px] text-slate-500">业务定义</label>
              <Input value={editDraft.definition} onChange={(e) => setEditDraft((d) => d ? { ...d, definition: e.target.value } : d)} placeholder="标准业务定义" className="h-8 text-xs" />
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-slate-500">业务主键</label>
              <Input value={editDraft.identifier} onChange={(e) => setEditDraft((d) => d ? { ...d, identifier: e.target.value } : d)} placeholder="如 settlement_id" className="h-8 text-xs font-mono" />
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-slate-500">版本号</label>
              <Input value={editDraft.version} onChange={(e) => setEditDraft((d) => d ? { ...d, version: e.target.value } : d)} className="h-8 w-28 text-xs font-mono" />
            </div>
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <button onClick={() => setEditDraft(null)} className="rounded-md border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50">取消</button>
            <button onClick={handleSave} disabled={saving} className="rounded-md bg-blue-500 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-600 disabled:opacity-40">
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        </div>
      )}

      {/* ── Publish Check ── */}
      {showPublishCheck && (
        <PublishCheckDialog obj={obj} onCancel={() => setShowPublishCheck(false)} onPublished={handlePublish} />
      )}

      {/* ── Version History ── */}
      {showVersionHistory && (
        <VersionHistoryDialog obj={obj} onClose={() => setShowVersionHistory(false)} />
      )}
    </div>
  )
}

// ── Loading Skeleton ────────────────────────────────────────────

function ObjectPageSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i} className="border-slate-200 bg-white/80"><CardContent className="px-4 py-4"><div className="h-3 w-16 animate-pulse rounded bg-slate-200" /><div className="mt-2 h-6 w-12 animate-pulse rounded bg-slate-200" /></CardContent></Card>
        ))}
      </div>
      <div className="space-y-2">{Array.from({ length: 6 }).map((_, i) => (<div key={i} className="h-16 w-full animate-pulse rounded-xl bg-slate-200" />))}</div>
    </div>
  )
}

// ── Main Page ───────────────────────────────────────────────────

export default function ObjectListPage() {
  const searchParams = useSearchParams()
  const initialDomain = searchParams.get('domain_code') || '全部域'

  const [objects, setObjects] = useState<SemanticObject[]>([])
  const [domains, setDomains] = useState<DomainInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [searchText, setSearchText] = useState('')
  const [domainFilter, setDomainFilter] = useState<string>(initialDomain)
  const [statusFilter, setStatusFilter] = useState<string>('全部状态')
  const [showAddForm, setShowAddForm] = useState(false)
  const [deletingObj, setDeletingObj] = useState<SemanticObject | null>(null)

  const fetchData = useCallback(() => {
    setLoading(true); setError(null)
    Promise.all([
      fetchJson<SemanticObject[]>(`${SEMANTIC_API}/objects`),
      fetchJson<DomainInfo[]>(`${SEMANTIC_API}/domains`).catch(() => [] as DomainInfo[]),
    ]).then(([objs, doms]) => {
      setObjects(Array.isArray(objs) ? objs : [])
      setDomains(Array.isArray(doms) ? doms : [])
      setLoading(false)
    }).catch((err: Error) => { setError(err.message); setLoading(false) })
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const domainMap = useMemo(() => {
    const map: Record<string, string> = {}
    for (const d of domains) map[d.domain_code] = d.name
    return map
  }, [domains])

  const filteredObjects = useMemo(() => {
    let list = [...objects]
    if (domainFilter !== '全部域') list = list.filter((o) => o.domain_code === domainFilter)
    if (statusFilter !== '全部状态') list = list.filter((o) => o.status === statusFilter)
    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase()
      list = list.filter((o) => o.name.toLowerCase().includes(q) || o.object_code.toLowerCase().includes(q) || (o.definition ?? '').toLowerCase().includes(q) || (domainMap[o.domain_code] ?? '').toLowerCase().includes(q))
    }
    return list
  }, [objects, domainFilter, statusFilter, searchText, domainMap])

  const domainOptions = useMemo(() => {
    const codes = new Set(objects.map((o) => o.domain_code))
    return Array.from(codes).sort()
  }, [objects])

  const handleSave = useCallback((updated: SemanticObject) => {
    setObjects((prev) => prev.map((o) => o.object_code === updated.object_code ? updated : o))
  }, [])

  const handleAdd = useCallback((obj: SemanticObject) => {
    setObjects((prev) => [...prev, obj]); setShowAddForm(false)
  }, [])

  const handleDeleteConfirm = useCallback(async () => {
    if (!deletingObj) return
    try {
      await fetchJson(`${SEMANTIC_API}/objects/${encodeURIComponent(deletingObj.object_code)}`, { method: 'DELETE' })
      setObjects((prev) => prev.filter((o) => o.object_code !== deletingObj.object_code))
    } catch (err: any) { alert(err.message) }
    setDeletingObj(null)
  }, [deletingObj])

  if (loading) return <ObjectPageSkeleton />
  if (error) return <Alert variant="destructive" className="border-red-200 bg-red-50"><AlertTitle className="text-red-600">数据加载失败</AlertTitle><AlertDescription className="text-red-600">{error}</AlertDescription></Alert>

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Card className="border-slate-200 bg-white shadow-sm"><CardContent className="px-4 py-3"><div className="text-[11px] text-slate-500">对象总数</div><div className="text-xl font-bold tabular-nums text-cyan-600">{objects.length}</div></CardContent></Card>
        <Card className="border-slate-200 bg-white shadow-sm"><CardContent className="px-4 py-3"><div className="text-[11px] text-slate-500">已发布</div><div className="text-xl font-bold tabular-nums text-emerald-600">{objects.filter((o) => o.status === 'published').length}</div></CardContent></Card>
        <Card className="border-slate-200 bg-white shadow-sm"><CardContent className="px-4 py-3"><div className="text-[11px] text-slate-500">草稿</div><div className="text-xl font-bold tabular-nums text-amber-600">{objects.filter((o) => o.status === 'draft').length}</div></CardContent></Card>
        <Card className="border-slate-200 bg-white shadow-sm"><CardContent className="px-4 py-3"><div className="text-[11px] text-slate-500">域数</div><div className="text-xl font-bold tabular-nums text-purple-600">{domains.length}</div></CardContent></Card>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-slate-500">域:</span>
          <select value={domainFilter} onChange={(e) => setDomainFilter(e.target.value)} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs focus:border-blue-500 focus:outline-none">
            <option value="全部域">全部域</option>
            {domainOptions.map((code) => <option key={code} value={code}>{code}</option>)}
          </select>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-slate-500">状态:</span>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs focus:border-blue-500 focus:outline-none">
            <option value="全部状态">全部状态</option>
            <option value="draft">草稿</option>
            <option value="published">已发布</option>
            <option value="deprecated">已弃用</option>
          </select>
        </div>
        <div className="relative flex-1 max-w-[240px]">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
          <Input type="text" placeholder="搜索对象..." value={searchText} onChange={(e) => setSearchText(e.target.value)} className="h-8 rounded-md border border-slate-300 bg-white pl-8 text-xs" />
        </div>
        <div className="text-xs text-slate-500">共 <span className="font-mono text-slate-600">{filteredObjects.length}</span> 个</div>
        <div className="ml-auto">
          <button type="button" onClick={() => setShowAddForm((p) => !p)} className="flex items-center gap-1 rounded-md bg-cyan-50 px-2.5 py-1.5 text-xs font-medium text-cyan-600 hover:bg-cyan-100">
            <Plus className="h-3.5 w-3.5" />新建对象
          </button>
        </div>
      </div>

      {showAddForm && <AddObjectForm domains={domains} onAdd={handleAdd} onCancel={() => setShowAddForm(false)} />}

      <div className="flex flex-col gap-3">
        {filteredObjects.length === 0 ? (
          <div className="py-16 text-center text-sm text-slate-400">{objects.length === 0 ? '暂无业务对象' : '无匹配的对象'}</div>
        ) : (
          filteredObjects.map((obj) => (
            <ObjectCardRow key={obj.object_code} obj={obj} domainName={domainMap[obj.domain_code] ?? obj.domain_code} domains={domains} onSave={handleSave} onDelete={setDeletingObj} />
          ))
        )}
      </div>

      {deletingObj && <DeleteConfirmDialog obj={deletingObj} onConfirm={handleDeleteConfirm} onCancel={() => setDeletingObj(null)} />}
    </div>
  )
}
