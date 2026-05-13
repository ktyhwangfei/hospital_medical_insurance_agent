'use client'

import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, FileText, Pencil, Plus, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import {
  listAssets,
  createAsset,
  updateAsset,
  deleteAsset,
  listAssetChunks,
  createAssetChunk,
} from '@/lib/api-client'

const ASSET_TYPE_LABELS: Record<string, string> = {
  policy_doc: '政策文档',
  regulation: '法规',
  guideline: '指南',
  template: '模板',
  other: '其他',
}

const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  archived: '已归档',
}

const STATUS_COLORS: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-600',
  published: 'bg-green-100 text-green-800',
  archived: 'bg-yellow-100 text-yellow-800',
}

const INDEX_STATUS_LABELS: Record<string, string> = {
  pending: '待索引',
  indexing: '索引中',
  completed: '已完成',
  failed: '失败',
}

const INDEX_STATUS_COLORS: Record<string, string> = {
  pending: 'bg-gray-100 text-gray-600',
  indexing: 'bg-blue-100 text-blue-800',
  completed: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
}

interface AssetItem {
  asset_id: string
  title: string
  source: string
  asset_type: string
  version: string
  status: string
  index_status: string
  summary: string
  visibility: Record<string, unknown>
  fallback?: boolean
}

interface ChunkItem {
  chunk_id: string
  section: string
  content: string
  fallback?: boolean
}

interface AssetFormState {
  asset_id: string
  title: string
  source: string
  asset_type: string
  version: string
  summary: string
  visibility: string
}

interface ChunkFormState {
  chunk_id: string
  section: string
  content: string
}

const emptyAssetForm: AssetFormState = {
  asset_id: '',
  title: '',
  source: '',
  asset_type: 'policy_doc',
  version: '1.0.0',
  summary: '',
  visibility: JSON.stringify({ roles: [] }, null, 2),
}

const emptyChunkForm: ChunkFormState = {
  chunk_id: '',
  section: '',
  content: '',
}

export default function KnowledgeAssetCrud() {
  const [assets, setAssets] = useState<AssetItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [typeFilter, setTypeFilter] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const [editing, setEditing] = useState<AssetItem | null>(null)
  const [form, setForm] = useState<AssetFormState>(emptyAssetForm)
  const [submitting, setSubmitting] = useState(false)

  // Chunk management state
  const [expandedAsset, setExpandedAsset] = useState<string | null>(null)
  const [chunks, setChunks] = useState<Record<string, ChunkItem[]>>({})
  const [chunksLoading, setChunksLoading] = useState<Record<string, boolean>>({})
  const [chunkDialogOpen, setChunkDialogOpen] = useState(false)
  const [chunkForm, setChunkForm] = useState<ChunkFormState>(emptyChunkForm)
  const [chunkSubmitting, setChunkSubmitting] = useState(false)
  const [chunkAssetId, setChunkAssetId] = useState<string | null>(null)

  useEffect(() => {
    loadAssets()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typeFilter, statusFilter])

  const loadAssets = async () => {
    setLoading(true)
    setError(null)
    try {
      const params: { type?: string; status?: string } = {}
      if (typeFilter) params.type = typeFilter
      if (statusFilter) params.status = statusFilter
      const result = await listAssets(Object.keys(params).length > 0 ? params : undefined)
      setAssets(result as unknown as AssetItem[])
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载知识资产失败')
    } finally {
      setLoading(false)
    }
  }

  const openCreate = () => {
    setEditing(null)
    setForm({ ...emptyAssetForm })
    setDialogOpen(true)
  }

  const openEdit = (asset: AssetItem) => {
    setEditing(asset)
    setForm({
      asset_id: asset.asset_id,
      title: asset.title,
      source: asset.source,
      asset_type: asset.asset_type,
      version: asset.version,
      summary: asset.summary,
      visibility:
        typeof asset.visibility === 'object' && asset.visibility !== null
          ? JSON.stringify(asset.visibility, null, 2)
          : '{}',
    })
    setDialogOpen(true)
  }

  const submit = async () => {
    setError(null)
    if (!form.asset_id.trim() || !form.title.trim()) {
      setError('资产ID和标题不能为空')
      return
    }

    let parsedVisibility: Record<string, unknown> = {}
    try {
      parsedVisibility = JSON.parse(form.visibility) as Record<string, unknown>
    } catch {
      setError('visibility 字段不是合法的 JSON')
      return
    }

    setSubmitting(true)
    try {
      const payload = {
        asset_id: form.asset_id.trim(),
        title: form.title.trim(),
        source: form.source.trim(),
        asset_type: form.asset_type,
        version: form.version.trim(),
        summary: form.summary.trim(),
        visibility: parsedVisibility,
      }
      if (editing) {
        await updateAsset(editing.asset_id, payload)
      } else {
        await createAsset(payload)
      }
      setDialogOpen(false)
      await loadAssets()
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败')
    } finally {
      setSubmitting(false)
    }
  }

  const openDelete = (assetId: string) => {
    setDeleteTarget(assetId)
    setDeleteDialogOpen(true)
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setError(null)
    try {
      await deleteAsset(deleteTarget)
      setDeleteDialogOpen(false)
      setDeleteTarget(null)
      if (expandedAsset === deleteTarget) {
        setExpandedAsset(null)
      }
      await loadAssets()
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败')
    }
  }

  // Chunk management
  const toggleExpandAsset = async (assetId: string) => {
    if (expandedAsset === assetId) {
      setExpandedAsset(null)
      return
    }
    setExpandedAsset(assetId)
    if (!chunks[assetId]) {
      setChunksLoading((prev) => ({ ...prev, [assetId]: true }))
      try {
        const result = await listAssetChunks(assetId)
        setChunks((prev) => ({ ...prev, [assetId]: result as unknown as ChunkItem[] }))
      } catch {
        setChunks((prev) => ({ ...prev, [assetId]: [] }))
      } finally {
        setChunksLoading((prev) => ({ ...prev, [assetId]: false }))
      }
    }
  }

  const openCreateChunk = (assetId: string) => {
    setChunkAssetId(assetId)
    setChunkForm({ ...emptyChunkForm })
    setChunkDialogOpen(true)
  }

  const submitChunk = async () => {
    if (!chunkAssetId) return
    setError(null)
    if (!chunkForm.chunk_id.trim() || !chunkForm.section.trim()) {
      setError('切片ID和章节不能为空')
      return
    }
    setChunkSubmitting(true)
    try {
      await createAssetChunk(chunkAssetId, {
        chunk_id: chunkForm.chunk_id.trim(),
        section: chunkForm.section.trim(),
        content: chunkForm.content,
      })
      setChunkDialogOpen(false)
      setChunkAssetId(null)
      // Refresh chunks for the expanded asset
      if (expandedAsset) {
        const result = await listAssetChunks(expandedAsset)
        setChunks((prev) => ({ ...prev, [expandedAsset]: result as unknown as ChunkItem[] }))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建切片失败')
    } finally {
      setChunkSubmitting(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span className="flex items-center gap-2">
              <FileText className="w-5 h-5" />
              知识资产管理
            </span>
            <div className="flex items-center gap-2">
              <Select value={typeFilter} onValueChange={(v) => { setTypeFilter(v ?? '') }}>
                <SelectTrigger className="w-[140px]">
                  <SelectValue placeholder="全部类型" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">全部类型</SelectItem>
                  <SelectItem value="policy_doc">政策文档</SelectItem>
                  <SelectItem value="regulation">法规</SelectItem>
                  <SelectItem value="guideline">指南</SelectItem>
                  <SelectItem value="template">模板</SelectItem>
                  <SelectItem value="other">其他</SelectItem>
                </SelectContent>
              </Select>
              <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v ?? '') }}>
                <SelectTrigger className="w-[130px]">
                  <SelectValue placeholder="全部状态" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">全部状态</SelectItem>
                  <SelectItem value="draft">草稿</SelectItem>
                  <SelectItem value="published">已发布</SelectItem>
                  <SelectItem value="archived">已归档</SelectItem>
                </SelectContent>
              </Select>
              <Button variant="outline" size="sm" onClick={loadAssets} disabled={loading}>
                {loading ? '加载中...' : '刷新'}
              </Button>
              <Button size="sm" onClick={openCreate}>
                <Plus className="w-4 h-4 mr-1" />
                添加资产
              </Button>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm mb-4">
              {error}
            </div>
          )}
          {loading ? (
            <div className="text-center py-8 text-gray-500">加载中...</div>
          ) : assets.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              <p>暂无知识资产</p>
              <Button variant="outline" size="sm" className="mt-2" onClick={openCreate}>
                <Plus className="w-4 h-4 mr-1" />
                创建第一条资产
              </Button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left">
                    <th className="pb-3 pr-4 font-medium text-gray-600 w-8" />
                    <th className="pb-3 pr-4 font-medium text-gray-600">资产ID</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">标题</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">来源</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">类型</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">版本</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">状态</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">索引状态</th>
                    <th className="pb-3 font-medium text-gray-600">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {assets.map((asset) => (
                    <>
                      <tr
                        key={asset.asset_id}
                        className="border-b hover:bg-gray-50 cursor-pointer"
                        onClick={() => toggleExpandAsset(asset.asset_id)}
                      >
                        <td className="py-3 pr-4">
                          {expandedAsset === asset.asset_id ? (
                            <ChevronDown className="w-4 h-4 text-gray-400" />
                          ) : (
                            <ChevronRight className="w-4 h-4 text-gray-400" />
                          )}
                        </td>
                        <td className="py-3 pr-4 font-mono text-xs">{asset.asset_id}</td>
                        <td className="py-3 pr-4">
                          <div className="font-medium">{asset.title}</div>
                        </td>
                        <td className="py-3 pr-4 text-gray-600">{asset.source}</td>
                        <td className="py-3 pr-4">
                          <Badge variant="outline">
                            {ASSET_TYPE_LABELS[asset.asset_type] ?? asset.asset_type}
                          </Badge>
                        </td>
                        <td className="py-3 pr-4">{asset.version}</td>
                        <td className="py-3 pr-4">
                          <Badge className={STATUS_COLORS[asset.status] ?? 'bg-gray-100 text-gray-600'}>
                            {STATUS_LABELS[asset.status] ?? asset.status}
                          </Badge>
                        </td>
                        <td className="py-3 pr-4">
                          <Badge
                            className={INDEX_STATUS_COLORS[asset.index_status] ?? 'bg-gray-100 text-gray-600'}
                          >
                            {INDEX_STATUS_LABELS[asset.index_status] ?? asset.index_status}
                          </Badge>
                        </td>
                        <td className="py-3" onClick={(e) => e.stopPropagation()}>
                          <div className="flex gap-1">
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              onClick={() => openEdit(asset)}
                              title="编辑"
                            >
                              <Pencil className="w-4 h-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              onClick={() => openDelete(asset.asset_id)}
                              title="删除"
                            >
                              <Trash2 className="w-4 h-4 text-red-500" />
                            </Button>
                          </div>
                        </td>
                      </tr>
                      {/* Expanded chunk section */}
                      {expandedAsset === asset.asset_id && (
                        <tr key={`${asset.asset_id}-chunks`}>
                          <td colSpan={9} className="bg-gray-50 px-6 py-4">
                            <div className="space-y-3">
                              <div className="flex items-center justify-between">
                                <h4 className="text-sm font-semibold text-gray-700">
                                  知识切片 ({chunks[asset.asset_id]?.length ?? 0})
                                </h4>
                                <Button size="sm" variant="outline" onClick={() => openCreateChunk(asset.asset_id)}>
                                  <Plus className="w-3 h-3 mr-1" />
                                  添加切片
                                </Button>
                              </div>
                              {chunksLoading[asset.asset_id] ? (
                                <div className="text-sm text-gray-500 py-4 text-center">加载切片中...</div>
                              ) : !chunks[asset.asset_id] || chunks[asset.asset_id].length === 0 ? (
                                <div className="text-sm text-gray-400 py-4 text-center">暂无切片数据</div>
                              ) : (
                                <div className="space-y-2">
                                  {chunks[asset.asset_id].map((chunk) => (
                                    <div
                                      key={chunk.chunk_id}
                                      className="bg-white border rounded-lg p-3 text-sm"
                                    >
                                      <div className="flex items-center gap-2 mb-1">
                                        <span className="font-mono text-xs text-gray-500">
                                          {chunk.chunk_id}
                                        </span>
                                        <Badge variant="outline" className="text-xs">
                                          {chunk.section}
                                        </Badge>
                                      </div>
                                      <p className="text-gray-600 text-xs line-clamp-2">
                                        {chunk.content || '(无内容)'}
                                      </p>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create / Edit Asset Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editing ? '编辑知识资产' : '添加知识资产'}</DialogTitle>
            <DialogDescription>
              {editing ? '修改知识资产信息' : '创建新的知识资产'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium text-gray-700">资产ID *</label>
                <Input
                  placeholder="ASSET-001"
                  value={form.asset_id}
                  onChange={(e) => setForm((prev) => ({ ...prev, asset_id: e.target.value }))}
                  disabled={!!editing}
                />
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700">标题 *</label>
                <Input
                  placeholder="北京市基本医疗保险药品目录（2025版）"
                  value={form.title}
                  onChange={(e) => setForm((prev) => ({ ...prev, title: e.target.value }))}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium text-gray-700">来源</label>
                <Input
                  placeholder="北京市医保局"
                  value={form.source}
                  onChange={(e) => setForm((prev) => ({ ...prev, source: e.target.value }))}
                />
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700">类型</label>
                <Select
                  value={form.asset_type}
                  onValueChange={(v) => {
                    if (v) setForm((prev) => ({ ...prev, asset_type: v }))
                  }}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="policy_doc">政策文档</SelectItem>
                    <SelectItem value="regulation">法规</SelectItem>
                    <SelectItem value="guideline">指南</SelectItem>
                    <SelectItem value="template">模板</SelectItem>
                    <SelectItem value="other">其他</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium text-gray-700">版本</label>
                <Input
                  placeholder="2025.1"
                  value={form.version}
                  onChange={(e) => setForm((prev) => ({ ...prev, version: e.target.value }))}
                />
              </div>
              <div />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">摘要</label>
              <Textarea
                placeholder="知识资产的摘要描述"
                value={form.summary}
                onChange={(e) => setForm((prev) => ({ ...prev, summary: e.target.value }))}
                className="min-h-[80px]"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">可见性配置 (JSON)</label>
              <Textarea
                placeholder='{"roles": ["insurance_officer", "doctor"]}'
                value={form.visibility}
                onChange={(e) => setForm((prev) => ({ ...prev, visibility: e.target.value }))}
                className="min-h-[100px] font-mono text-xs"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              取消
            </Button>
            <Button onClick={submit} disabled={submitting}>
              {submitting ? '提交中...' : editing ? '保存' : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
            <DialogDescription>
              确定要删除资产 &ldquo;{deleteTarget}&rdquo; 吗？
              这将同时删除所有关联的切片，此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              取消
            </Button>
            <Button variant="destructive" onClick={confirmDelete}>
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create Chunk Dialog */}
      <Dialog open={chunkDialogOpen} onOpenChange={setChunkDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>添加知识切片</DialogTitle>
            <DialogDescription>为资产添加新的知识切片，提交后将触发向量化。</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium text-gray-700">切片ID *</label>
                <Input
                  placeholder="chunk-001"
                  value={chunkForm.chunk_id}
                  onChange={(e) => setChunkForm((prev) => ({ ...prev, chunk_id: e.target.value }))}
                />
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700">章节 *</label>
                <Input
                  placeholder="第一章 总则"
                  value={chunkForm.section}
                  onChange={(e) => setChunkForm((prev) => ({ ...prev, section: e.target.value }))}
                />
              </div>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">内容</label>
              <Textarea
                placeholder="切片文本内容"
                value={chunkForm.content}
                onChange={(e) => setChunkForm((prev) => ({ ...prev, content: e.target.value }))}
                className="min-h-[150px]"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setChunkDialogOpen(false)}>
              取消
            </Button>
            <Button onClick={submitChunk} disabled={chunkSubmitting}>
              {chunkSubmitting ? '提交中...' : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
