'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Plus, Trash2, CheckCircle2, FileCode, AlertCircle, Copy } from 'lucide-react'
import {
  listSkillDrafts,
  deleteSkillDraft,
  ApiClientError,
} from '@/lib/skill-draft-api'
import type { SkillDraftResponse } from '@/lib/types'

const STATUS_LABELS: Record<string, { label: string; className: string }> = {
  editing: { label: '编辑中', className: 'bg-amber-100 text-amber-800' },
  validated: { label: '已校验', className: 'bg-green-100 text-green-800' },
  materialized: { label: '已物化', className: 'bg-blue-100 text-blue-800' },
  deleted: { label: '已删除', className: 'bg-slate-200 text-slate-600' },
}

export default function SkillDraftsPage() {
  const router = useRouter()
  const [drafts, setDrafts] = useState<SkillDraftResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<SkillDraftResponse | null>(null)
  const [deleting, setDeleting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listSkillDrafts()
      setDrafts(data.items ?? [])
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '加载草稿失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function confirmDelete() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteSkillDraft(deleteTarget.draft_id)
      setDeleteTarget(null)
      await load()
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '删除失败')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="mt-4 space-y-4">
      <header className="flex items-center justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">
              Skill 管理工作台
            </span>
            <span className="text-xs text-slate-500">草稿列表</span>
          </div>
          <h2 className="text-xl font-semibold tracking-tight text-slate-900">草稿管理</h2>
          <p className="text-sm text-slate-600">
            管理所有草稿：模板创建、复制、导入。草稿校验通过后可物化为正式版本。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => router.push('/skills/import')}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50"
          >
            <Copy className="h-4 w-4" />
            导入 Skill
          </button>
          <button
            type="button"
            onClick={() => router.push('/skills/new')}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-blue-700"
          >
            <Plus className="h-4 w-4" />
            新建草稿
          </button>
        </div>
      </header>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3 font-medium">Skill 名称 / ID</th>
              <th className="px-4 py-3 font-medium">来源</th>
              <th className="px-4 py-3 font-medium">状态</th>
              <th className="px-4 py-3 font-medium">业务挂载</th>
              <th className="px-4 py-3 font-medium">最近修改</th>
              <th className="px-4 py-3 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-slate-400">
                  加载中…
                </td>
              </tr>
            )}
            {!loading && drafts.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-slate-400">
                  暂无草稿，点击右上角「新建草稿」开始
                </td>
              </tr>
            )}
            {drafts.map((draft) => {
              const status = STATUS_LABELS[draft.status] ?? STATUS_LABELS.editing
              const bm = draft.structured_config?.business_mounting
              return (
                <tr key={draft.draft_id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900">{draft.skill_name}</div>
                    <div className="font-mono text-xs text-slate-500">{draft.skill_id}</div>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{draft.source_type}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${status.className}`}>
                      {draft.status === 'validated' && <CheckCircle2 className="h-3 w-3" />}
                      {status.label}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {bm ? `${bm.business_action} / ${bm.business_object}` : '—'}
                  </td>
                  <td className="px-4 py-3 text-slate-500">
                    {new Date(draft.updated_at).toLocaleString('zh-CN')}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => router.push(`/skills/${encodeURIComponent(draft.skill_id)}/edit?draft=${draft.draft_id}`)}
                        className="inline-flex items-center gap-1 rounded-md border border-slate-300 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
                      >
                        <FileCode className="h-3.5 w-3.5" />
                        编辑
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeleteTarget(draft)}
                        className="inline-flex items-center gap-1 rounded-md border border-red-200 px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* 删除二次确认（设计 §6 二次确认） */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" role="dialog" aria-modal>
          <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-900">删除草稿确认</h3>
            <p className="mt-2 text-sm text-slate-600">
              确定要删除草稿「{deleteTarget.skill_name}」(<code className="rounded bg-slate-100 px-1 text-xs">{deleteTarget.skill_id}</code>) 吗？
              此操作为软删除，草稿将不再出现在列表中。
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setDeleteTarget(null)}
                disabled={deleting}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void confirmDelete()}
                disabled={deleting}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {deleting ? '删除中…' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
