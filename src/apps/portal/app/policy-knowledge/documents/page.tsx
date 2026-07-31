'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import Link from 'next/link'
import { Plus, Search, FileText, Trash2, Play, Eye, Loader2, Upload, Globe, Edit3, Download } from 'lucide-react'

const API = '/api/v1/medical-insurance-ai-agent/policy-pipeline'

interface Document {
  doc_id: string
  title: string
  category: string
  publish_date: string
  abolition_date: string
  validity: string
  document_date: string
  effective_date: string
  issuing_agency: string
  document_number: string
  file_source: string
  policy_region: string
  policy_level: string
  source_type: string
  source_url: string
  content_text: string
  content_hash: string
  content_size: number
  attachments: { name: string; url: string; local_path: string }[]
  crawl_status: string
  crawl_time: string
  status: string
  rule_ids: string[]
  coverage_ratio: number
  coverage_detail: { ratio: number; covered_chars: number; total_chars: number }
  created_at: string
  updated_at: string
}

const statusLabel: Record<string, string> = {
  raw: '待提取',
  processing: '提取中',
  extracted: '已提取',
  archived: '已归档',
}
const statusColor: Record<string, string> = {
  raw: 'bg-slate-100 text-slate-600',
  processing: 'bg-blue-100 text-blue-700',
  extracted: 'bg-emerald-100 text-emerald-700',
  archived: 'bg-amber-100 text-amber-700',
}
const sourceLabel: Record<string, string> = {
  manual: '手动录入',
  upload: '文件上传',
  crawl: '爬虫导入',
}

export default function PolicyDocumentsPage() {
  const [docs, setDocs] = useState<Document[]>([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

  // Create modal - 全部政策元数据字段
  const [showCreate, setShowCreate] = useState(false)
  const [newForm, setNewForm] = useState<Record<string, string>>({})
  const [creating, setCreating] = useState(false)

  // Detail modal
  const [detail, setDetail] = useState<Document | null>(null)

  // Extract loading
  const [extracting, setExtracting] = useState<string | null>(null)

  // Batch upload
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const PAGE = 20

  const fetchDocs = useCallback(async () => {
    setLoading(true)
    try {
      const p = new URLSearchParams({ page: String(page), page_size: String(PAGE) })
      if (keyword.trim()) p.set('keyword', keyword.trim())
      if (status) p.set('status', status)
      const r = await fetch(`${API}/documents?${p}`)
      const d = await r.json()
      setDocs(d.items || [])
      setTotal(d.total || 0)
    } catch {
      setError('加载失败')
    } finally {
      setLoading(false)
    }
  }, [page, keyword, status])

  useEffect(() => { fetchDocs() }, [fetchDocs])

  async function handleCreate() {
    if (!newForm.title?.trim() || !newForm.content_text?.trim()) return
    setCreating(true)
    try {
      await fetch(`${API}/documents`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newForm) })
      setShowCreate(false)
      setNewForm({})
      fetchDocs()
    } catch { setError('创建失败') }
    finally { setCreating(false) }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setError('')
    try {
      const form = new FormData()
      form.append('file', file)
      const r = await fetch(`${API}/documents/upload`, { method: 'POST', body: form })
      const d = await r.json()
      if (r.ok) {
        alert(`导入完成：成功 ${d.created} 条，跳过 ${d.skipped} 条`)
        fetchDocs()
      } else {
        setError(d.detail || '导入失败')
      }
    } catch {
      setError('上传失败')
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function handleDelete(docId: string) {
    if (!confirm('确认删除该政策原文？关联的提取记录也会一并删除。')) return
    try {
      await fetch(`${API}/documents/${docId}`, { method: 'DELETE' })
      fetchDocs()
    } catch { setError('删除失败') }
  }

  async function handleExtract(docId: string) {
    setExtracting(docId)
    setError('')
    try {
      const r = await fetch(`${API}/documents/${docId}/extract`, { method: 'POST' })
      const d = await r.json()
      if (d.success) {
        const cov = d.coverage
        const covMsg = cov ? `\n覆盖率: ${(cov.ratio * 100).toFixed(0)}% (${cov.covered_chars}/${cov.total_chars} 字符)` : ''
        alert(`提取完成：${d.total_facts} 个事实，${d.total_rules} 条规则${covMsg}`)
        fetchDocs()
      } else {
        setError(d.error || '提取失败')
      }
    } catch {
      setError('提取请求失败')
    } finally {
      setExtracting(null)
    }
  }

  async function handleViewDetail(docId: string) {
    try {
      const r = await fetch(`${API}/documents/${docId}`)
      setDetail(await r.json())
    } catch { setError('加载详情失败') }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">Step 1</span>
          <h2 className="text-xl font-semibold tracking-tight text-slate-900 mt-1">政策原文管理</h2>
        </div>
        <div className="flex items-center gap-2">
          <a href={`${API}/documents/template`} download className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50 transition-colors">
            <Download className="size-3.5" /> 下载模板
          </a>
          <label className={`flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50 transition-colors cursor-pointer ${uploading ? 'opacity-50 pointer-events-none' : ''}`}>
            <Upload className="size-3.5" /> {uploading ? '导入中...' : '批量导入'}
            <input type="file" ref={fileRef} accept=".xlsx,.xls" onChange={handleUpload} className="hidden" />
          </label>
          <button onClick={() => setShowCreate(true)} className="flex items-center gap-1.5 rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8] transition-colors shadow-sm">
            <Plus className="size-4" /> 新增原文
          </button>
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px] max-w-[320px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-slate-400 pointer-events-none" />
          <input className="w-full pl-9 pr-4 py-2 bg-white border border-slate-200 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
            placeholder="搜索标题..." value={keyword} onChange={e => setKeyword(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && fetchDocs()} />
        </div>
        <select className="bg-white border border-slate-200 rounded-lg px-2.5 py-2 text-xs text-slate-600" value={status} onChange={e => { setStatus(e.target.value); setPage(1) }}>
          <option value="">全部状态</option>
          <option value="raw">待提取</option>
          <option value="processing">提取中</option>
          <option value="extracted">已提取</option>
        </select>
        <span className="text-xs text-slate-400 ml-auto">共 {total} 条</span>
      </div>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">{error}</div>}

      {/* Table */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
        <table className="w-full text-sm">
          <thead><tr className="bg-slate-50/95 border-b border-slate-200">
            <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase">标题</th>
            <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase w-[90px]">发文机构</th>
            <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase w-[80px]">来源</th>
            <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase w-[80px]">状态</th>
            <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase w-[80px]">发布日期</th>
            <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase w-[60px]">规则</th>
            <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase w-[70px]">覆盖</th>
            <th className="px-4 py-2.5 text-right text-[11px] font-semibold text-slate-500 uppercase w-[180px]">操作</th>
          </tr></thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr><td colSpan={8} className="px-4 py-16 text-center"><Loader2 className="size-5 text-blue-500 animate-spin mx-auto" /></td></tr>
            ) : docs.length === 0 ? (
              <tr><td colSpan={8} className="px-4 py-16 text-center text-sm text-slate-400">暂无政策原文，点击新增原文开始</td></tr>
            ) : docs.map(d => (
              <tr key={d.doc_id} className="hover:bg-blue-50/20 transition-colors">
                <td className="px-4 py-3">
                  <button onClick={() => handleViewDetail(d.doc_id)} className="text-sm font-medium text-slate-800 hover:text-blue-600 text-left">{d.title}</button>
                </td>
                <td className="px-4 py-3 text-xs text-slate-500">{d.issuing_agency || '-'}</td>
                <td className="px-4 py-3">
                  <span className="inline-flex items-center gap-1 rounded-md bg-slate-50 px-2 py-0.5 text-xs text-slate-500 ring-1 ring-slate-200">
                    {d.source_type === 'crawl' ? <Globe className="size-3" /> : d.source_type === 'upload' ? <Upload className="size-3" /> : <Edit3 className="size-3" />}
                    {sourceLabel[d.source_type] || d.source_type}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${statusColor[d.status] || 'bg-slate-100 text-slate-500'}`}>
                    {statusLabel[d.status] || d.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs text-slate-500">{d.publish_date || '-'}</td>
                <td className="px-4 py-3 text-xs text-slate-500">{(d.rule_ids || []).length}</td>
                <td className="px-4 py-3">
                  {d.status === 'extracted' && d.coverage_ratio > 0 ? (
                    <div className="flex items-center gap-1.5">
                      <div className="w-10 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                        <div className="h-full bg-emerald-400 rounded-full" style={{ width: `${Math.round(d.coverage_ratio * 100)}%` }} />
                      </div>
                      <span className="text-[10px] text-slate-500">{Math.round(d.coverage_ratio * 100)}%</span>
                    </div>
                  ) : (
                    <span className="text-xs text-slate-300">-</span>
                  )}
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-1">
                    <button onClick={() => handleViewDetail(d.doc_id)} className="rounded px-2 py-0.5 text-xs font-medium text-slate-600 hover:bg-slate-100"><Eye className="size-3.5" /></button>
                    <button onClick={() => handleExtract(d.doc_id)} disabled={extracting === d.doc_id || d.status === 'processing'}
                      className="rounded px-2.5 py-0.5 text-xs font-medium text-blue-600 hover:bg-blue-50 disabled:opacity-40 disabled:cursor-not-allowed">
                      {extracting === d.doc_id ? <Loader2 className="size-3.5 animate-spin" /> : <Play className="size-3.5" />}
                      <span className="ml-1">提取</span>
                    </button>
                    <Link href={`/policy-knowledge/knowledge?doc_id=${d.doc_id}&sub=audit`} className="rounded px-2 py-0.5 text-xs font-medium text-amber-600 hover:bg-amber-50">审核</Link>
                    <button onClick={() => handleDelete(d.doc_id)} className="rounded px-2 py-0.5 text-xs font-medium text-rose-600 hover:bg-rose-50"><Trash2 className="size-3.5" /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {total > PAGE && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-slate-100 bg-slate-50/50">
            <span className="text-xs text-slate-500">共 {total} 条 · 第 {page}/{Math.ceil(total / PAGE)} 页</span>
            <div className="flex gap-1">
              <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="rounded-md px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-200 disabled:opacity-30">上一页</button>
              <button disabled={page * PAGE >= total} onClick={() => setPage(p => p + 1)} className="rounded-md px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-200 disabled:opacity-30">下一页</button>
            </div>
          </div>
        )}
      </div>

      {/* Create Modal - 完整政策元数据 */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30 backdrop-blur-sm px-4" onClick={() => setShowCreate(false)}>
          <div className="bg-white border border-slate-200 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="sticky top-0 flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-white/95 backdrop-blur rounded-t-2xl">
              <span className="font-semibold text-slate-800">新增政策原文</span>
              <button onClick={() => setShowCreate(false)} className="rounded-lg p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100">
                <svg className="size-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>
            <div className="p-6 space-y-4">
              {/* 基本信息 */}
              <fieldset className="border border-slate-200 rounded-lg p-4">
                <legend className="text-[11px] font-semibold text-slate-500 uppercase px-1">基本信息</legend>
                <div className="grid grid-cols-2 gap-3 mt-2">
                  <div className="col-span-2">
                    <label className="block text-[10px] text-slate-400 mb-0.5">标题 *</label>
                    <input className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={newForm.title || ''}
                      onChange={e => setNewForm(f => ({ ...f, title: e.target.value }))} placeholder="如：北京市基本医疗保险规定" />
                  </div>
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-0.5">来源类型</label>
                    <select className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={newForm.source_type || 'manual'}
                      onChange={e => setNewForm(f => ({ ...f, source_type: e.target.value }))}>
                      <option value="manual">手动录入</option>
                      <option value="upload">文件上传</option>
                      <option value="crawl">爬虫导入</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-0.5">政策地区</label>
                    <input className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={newForm.policy_region || ''}
                      onChange={e => setNewForm(f => ({ ...f, policy_region: e.target.value }))} placeholder="如：北京 / 全国" />
                  </div>
                </div>
                {(newForm.source_type === 'crawl') && (
                  <div className="mt-3">
                    <label className="block text-[10px] text-slate-400 mb-0.5">来源URL</label>
                    <input className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm font-mono" value={newForm.source_url || ''}
                      onChange={e => setNewForm(f => ({ ...f, source_url: e.target.value }))} placeholder="https://..." />
                  </div>
                )}
              </fieldset>

              {/* 发文信息 */}
              <fieldset className="border border-slate-200 rounded-lg p-4">
                <legend className="text-[11px] font-semibold text-slate-500 uppercase px-1">发文信息</legend>
                <div className="grid grid-cols-3 gap-3 mt-2">
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-0.5">发文机构</label>
                    <input className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={newForm.issuing_agency || ''}
                      onChange={e => setNewForm(f => ({ ...f, issuing_agency: e.target.value }))} placeholder="如：北京市医保局" />
                  </div>
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-0.5">发文字号</label>
                    <input className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={newForm.document_number || ''}
                      onChange={e => setNewForm(f => ({ ...f, document_number: e.target.value }))} placeholder="如：京医保发〔2024〕1号" />
                  </div>
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-0.5">主题分类</label>
                    <input className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={newForm.category || ''}
                      onChange={e => setNewForm(f => ({ ...f, category: e.target.value }))} placeholder="如：医保待遇" />
                  </div>
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-0.5">政策层级</label>
                    <select className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={newForm.policy_level || ''}
                      onChange={e => setNewForm(f => ({ ...f, policy_level: e.target.value }))}>
                      <option value="">不限</option><option value="national">国家级</option><option value="provincial">省级</option><option value="municipal">市级</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-0.5">文件来源</label>
                    <input className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={newForm.file_source || ''}
                      onChange={e => setNewForm(f => ({ ...f, file_source: e.target.value }))} placeholder="如：北京市人民政府" />
                  </div>
                </div>
              </fieldset>

              {/* 日期信息 */}
              <fieldset className="border border-slate-200 rounded-lg p-4">
                <legend className="text-[11px] font-semibold text-slate-500 uppercase px-1">日期与效力</legend>
                <div className="grid grid-cols-3 gap-3 mt-2">
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-0.5">发布日期</label>
                    <input type="date" className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={newForm.publish_date || ''}
                      onChange={e => setNewForm(f => ({ ...f, publish_date: e.target.value }))} />
                  </div>
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-0.5">实施日期</label>
                    <input type="date" className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={newForm.effective_date || ''}
                      onChange={e => setNewForm(f => ({ ...f, effective_date: e.target.value }))} />
                  </div>
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-0.5">废止日期</label>
                    <input type="date" className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={newForm.abolition_date || ''}
                      onChange={e => setNewForm(f => ({ ...f, abolition_date: e.target.value }))} />
                  </div>
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-0.5">成文日期</label>
                    <input type="date" className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={newForm.document_date || ''}
                      onChange={e => setNewForm(f => ({ ...f, document_date: e.target.value }))} />
                  </div>
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-0.5">有效性</label>
                    <select className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" value={newForm.validity || 'unknown'}
                      onChange={e => setNewForm(f => ({ ...f, validity: e.target.value }))}>
                      <option value="unknown">未知</option><option value="valid">有效</option><option value="abolished">已废止</option>
                    </select>
                  </div>
                </div>
              </fieldset>

              {/* 正文 */}
              <div>
                <label className="block text-[11px] font-medium text-slate-500 uppercase mb-1">政策原文内容 *</label>
                <textarea className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm min-h-[200px] resize-y font-mono"
                  value={newForm.content_text || ''} onChange={e => setNewForm(f => ({ ...f, content_text: e.target.value }))}
                  placeholder="粘贴政策原文完整内容..." />
              </div>
            </div>
            <div className="sticky bottom-0 flex justify-end gap-3 px-6 py-4 border-t border-slate-100 bg-white/95">
              <button onClick={() => setShowCreate(false)} className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">取消</button>
              <button onClick={handleCreate} disabled={creating || !newForm.title?.trim() || !newForm.content_text?.trim()}
                className="rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:opacity-50">
                {creating ? '创建中...' : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Detail Modal */}
      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30 backdrop-blur-sm px-4" onClick={() => setDetail(null)}>
          <div className="bg-white border border-slate-200 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="sticky top-0 flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-white/95 rounded-t-2xl">
              <div className="flex items-center gap-3">
                <FileText className="size-5 text-blue-500" />
                <span className="font-semibold text-slate-800">{detail.title}</span>
              </div>
              <button onClick={() => setDetail(null)} className="rounded-lg p-1.5 text-slate-400 hover:text-slate-600">
                <svg className="size-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>
            <div className="p-6 space-y-3">
              <div className="grid grid-cols-3 gap-2 text-sm">
                <div><span className="text-[10px] text-slate-400">标题</span><p className="text-sm font-medium">{detail.title}</p></div>
                <div><span className="text-[10px] text-slate-400">发文字号</span><p className="font-mono text-xs">{detail.document_number || '-'}</p></div>
                <div><span className="text-[10px] text-slate-400">主题分类</span><p>{detail.category || '-'}</p></div>
                <div><span className="text-[10px] text-slate-400">发文机构</span><p>{detail.issuing_agency || '-'}</p></div>
                <div><span className="text-[10px] text-slate-400">文件来源</span><p>{detail.file_source || '-'}</p></div>
                <div><span className="text-[10px] text-slate-400">政策地区</span><p>{detail.policy_region || '-'}</p></div>
                <div><span className="text-[10px] text-slate-400">政策层级</span><p>{detail.policy_level || '-'}</p></div>
                <div><span className="text-[10px] text-slate-400">来源类型</span><p>{sourceLabel[detail.source_type]}</p></div>
                <div><span className="text-[10px] text-slate-400">状态</span><p>{statusLabel[detail.status]}</p></div>
                <div><span className="text-[10px] text-slate-400">发布日期</span><p>{detail.publish_date || '-'}</p></div>
                <div><span className="text-[10px] text-slate-400">实施日期</span><p>{detail.effective_date || '-'}</p></div>
                <div><span className="text-[10px] text-slate-400">废止日期</span><p>{detail.abolition_date || '-'}</p></div>
                <div><span className="text-[10px] text-slate-400">成文日期</span><p>{detail.document_date || '-'}</p></div>
                <div><span className="text-[10px] text-slate-400">有效性</span><p>{detail.validity || 'unknown'}</p></div>
                <div><span className="text-[10px] text-slate-400">关联规则</span><p>{detail.rule_ids?.length || 0} 条</p></div>
                <div><span className="text-[10px] text-slate-400">覆盖率</span>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <div className="w-16 h-2 bg-slate-100 rounded-full overflow-hidden">
                      <div className="h-full bg-emerald-400 rounded-full" style={{ width: `${Math.round((detail.coverage_ratio || 0) * 100)}%` }} />
                    </div>
                    <span className="text-xs font-medium text-slate-700">{Math.round((detail.coverage_ratio || 0) * 100)}%</span>
                  </div>
                </div>
                {detail.source_url && <div className="col-span-3"><span className="text-[10px] text-slate-400">来源URL</span><p className="font-mono text-xs break-all">{detail.source_url}</p></div>}
                <div className="col-span-3"><span className="text-[10px] text-slate-400">内容大小</span><p>{detail.content_size || 0} 字符</p></div>
              </div>
              <div>
                <span className="text-xs text-slate-400">政策原文内容</span>
                <pre className="mt-1 bg-slate-50 rounded-lg p-4 text-xs text-slate-700 whitespace-pre-wrap max-h-[300px] overflow-y-auto border border-slate-100">{detail.content_text}</pre>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
