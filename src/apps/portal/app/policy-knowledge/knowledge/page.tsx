'use client'

import { useCallback, useEffect, useState } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'

import { KnowledgeWorkbench } from '@/components/policy-knowledge/knowledge-workbench'
import { MetricDraftDialog } from '@/components/policy-knowledge/metric-draft-dialog'
import {
  getWorkbenchDocument,
  getWorkbenchDocuments,
  bindExistingMetric,
  listSemanticMetrics,
  proposeStandardValue,
  type MetricDraftSource,
  type SemanticMetricSummary,
  type StandardizedField,
  type WorkbenchDocument,
  type WorkbenchDocumentSummary,
} from '@/lib/policy-knowledge-api'

export default function KnowledgePage() {
  const [documents, setDocuments] = useState<WorkbenchDocumentSummary[]>([])
  const [docId, setDocId] = useState('')
  const [document, setDocument] = useState<WorkbenchDocument | null>(null)
  const [draftSources, setDraftSources] = useState<MetricDraftSource[]>([])
  const [metrics, setMetrics] = useState<SemanticMetricSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    getWorkbenchDocuments().then((items) => {
      setDocuments(items)
      setDocId((current) => current || items[0]?.doc_id || '')
    }).catch((reason) => setError(reason.message)).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    void listSemanticMetrics().then(setMetrics).catch((reason) => setError(reason instanceof Error ? reason.message : '已有指标加载失败'))
  }, [])

  const loadDocument = useCallback(async () => {
    if (!docId) { setDocument(null); return }
    setLoading(true); setError('')
    try { setDocument(await getWorkbenchDocument(docId)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '知识工作台加载失败') }
    finally { setLoading(false) }
  }, [docId])

  useEffect(() => {
    if (!docId) return
    void getWorkbenchDocument(docId)
      .then(setDocument)
      .catch((reason) => setError(reason instanceof Error ? reason.message : '知识工作台加载失败'))
      .finally(() => setLoading(false))
  }, [docId])

  async function proposeValue(source: MetricDraftSource, field: StandardizedField) {
    if (!field.value_domain) { setError('该字段尚未绑定标准值域，需先在语义层配置值域'); return }
    const value = window.prompt(`为值域 ${field.value_domain} 新增标准值草稿：`, String(source.source_value ?? ''))
    if (!value) return
    try {
      await proposeStandardValue(source, field.value_domain, value)
      setNotice('标准值草稿已创建，待语义层审核发布')
    } catch (reason) { setError(reason instanceof Error ? reason.message : '标准值草稿创建失败') }
  }

  async function bindMetric(source: MetricDraftSource, metricCode: string) {
    setError('')
    try {
      await bindExistingMetric(source, metricCode)
      setNotice('已有指标绑定草稿已创建，待语义层审核发布')
      await loadDocument()
    } catch (reason) { setError(reason instanceof Error ? reason.message : '已有指标绑定失败') }
  }

  return <div className="space-y-4">
    <header className="flex flex-wrap items-end gap-3">
      <div><p className="text-xs font-semibold text-blue-700">Unit × Knowledge × Metric</p><h2 className="mt-1 text-xl font-semibold text-slate-900">政策知识对齐工作台</h2><p className="mt-1 text-xs text-slate-500">左侧只读取单元页审核通过的内容；指标和值域变更均创建人工审核草稿。</p></div>
      <div className="ml-auto flex items-center gap-2">
        <select aria-label="选择政策文档" value={docId} onChange={(event) => setDocId(event.target.value)} className="max-w-72 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700">
          {!documents.length && <option value="">暂无可用文档</option>}
          {documents.map((item) => <option key={item.doc_id} value={item.doc_id}>{item.doc_title} · {item.approved_unit_count} 单元 / {item.knowledge_count} 知识</option>)}
        </select>
        <button type="button" onClick={loadDocument} className="rounded-lg border border-slate-200 bg-white p-2 text-slate-500 hover:bg-slate-50"><RefreshCw className="size-4" /></button>
      </div>
    </header>

    {notice && <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">{notice}</div>}
    {error && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}
    {loading ? <div className="flex justify-center py-24"><Loader2 className="size-5 animate-spin text-slate-400" /></div> : document ? (
      <KnowledgeWorkbench document={document} metrics={metrics} onBindExisting={bindMetric} onCreateMetricDrafts={setDraftSources} onProposeValue={proposeValue} />
    ) : <div className="rounded-2xl border border-dashed border-slate-200 bg-white py-24 text-center text-sm text-slate-400">请先在“单元”页审核政策单元，并完成结构化提取。</div>}

    {!!draftSources.length && <MetricDraftDialog sources={draftSources} onClose={() => setDraftSources([])} onCreated={(count) => { setDraftSources([]); setNotice(`已创建 ${count} 个指标草稿，待语义层审核发布`) }} />}
    {(notice.includes('草稿') || notice.includes('绑定')) && <a href="/semantic-layer/metrics" className="inline-flex text-xs font-semibold text-blue-700 hover:underline">前往语义层审核指标与绑定</a>}
  </div>
}
