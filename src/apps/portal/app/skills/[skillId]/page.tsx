'use client'

import { use, useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, AlertCircle, Loader2, Pencil, PowerOff, Power, Archive } from 'lucide-react'
import {
  getInfraSkillDetail,
  listInfraSkillVersions,
  listSkillEvalRuns,
  listSkillReleases,
} from '@/lib/api-client'
import { ApiClientError } from '@/lib/types'
import {
  getSkillDefinition,
  disableSkill,
  restoreSkill,
  archiveSkill,
  copySkill,
} from '@/lib/skill-draft-api'
import type {
  InfraSkillDetailResponse,
  SkillDefinitionResponse,
  SkillVersionResponse,
  SkillEvalRunListResponse,
  SkillReleaseListResponse,
} from '@/lib/types'

// /skills/[skillId] 独立详情页（设计 §3.3）：生命周期、版本、输入契约
export default function SkillDetailPage({ params }: { params: Promise<{ skillId: string }> }) {
  const { skillId } = use(params)
  const router = useRouter()
  const [detail, setDetail] = useState<InfraSkillDetailResponse | null>(null)
  const [definition, setDefinition] = useState<SkillDefinitionResponse | null>(null)
  const [versions, setVersions] = useState<SkillVersionResponse[] | null>(null)
  const [evalRuns, setEvalRuns] = useState<SkillEvalRunListResponse | null>(null)
  const [releases, setReleases] = useState<SkillReleaseListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [acting, setActing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      // 版本/评测/发布按需容错：未物化的 skill 这些接口可能 404，不阻塞详情主体
      const [d, def, vers, runs, rels] = await Promise.all([
        getInfraSkillDetail(skillId),
        getSkillDefinition(skillId).catch(() => null),
        listInfraSkillVersions(skillId).catch(() => null),
        listSkillEvalRuns(skillId).catch(() => null),
        listSkillReleases(skillId).catch(() => null),
      ])
      setDetail(d)
      setDefinition(def)
      setVersions(vers)
      setEvalRuns(runs)
      setReleases(rels)
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '加载详情失败')
    } finally {
      setLoading(false)
    }
  }, [skillId])

  useEffect(() => {
    void load()
  }, [load])

  // 复制当前 Skill 为新草稿：需用户输入新 skill_id（不可与源相同），成功后直达草稿编辑器
  async function copyToDraft() {
    const newSkillId = window.prompt('请输入新 Skill ID（复制当前 Skill 的配置为新草稿）', `${skillId}_v2`)
    if (!newSkillId || newSkillId.trim() === skillId) {
      if (newSkillId !== null) window.alert('新 Skill ID 不能与源 Skill 相同')
      return
    }
    setActing(true)
    setActionError(null)
    try {
      const draft = await copySkill(
        { source_skill_id: skillId, new_skill_id: newSkillId.trim() },
        `${skillId}:copy:${Date.now()}`,
      )
      router.push(`/skills/${encodeURIComponent(newSkillId.trim())}/edit?draft=${draft.draft_id}`)
    } catch (err) {
      setActionError(err instanceof ApiClientError ? err.detail.message : '复制失败')
    } finally {
      setActing(false)
    }
  }

  async function lifecycleAction(
    action: 'disable' | 'restore' | 'archive',
  ) {
    if (!definition) return
    const reason = window.prompt(`请输入${action === 'disable' ? '停用' : action === 'restore' ? '恢复' : '归档'}原因`)
    if (!reason) return
    setActing(true)
    setActionError(null)
    try {
      const req = { expected_revision: definition.revision, reason }
      const updated =
        action === 'disable'
          ? await disableSkill(skillId, req)
          : action === 'restore'
            ? await restoreSkill(skillId, req)
            : await archiveSkill(skillId, req)
      setDefinition(updated)
    } catch (err) {
      setActionError(err instanceof ApiClientError ? err.detail.message : '操作失败')
    } finally {
      setActing(false)
    }
  }

  if (loading) {
    return <div className="mt-10 text-center text-slate-400"><Loader2 className="mx-auto h-8 w-8 animate-spin" /></div>
  }

  if (error) {
    return (
      <div className="mt-4 space-y-3">
        <button onClick={() => router.push('/skills')} className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900">
          <ArrowLeft className="h-4 w-4" /> 返回列表
        </button>
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" /> {error}
        </div>
      </div>
    )
  }

  const skill = detail
  const skillName = skill?.skill_name ?? skillId
  const lifecycle = definition?.lifecycle_status

  const LIFECYCLE_BADGE: Record<string, string> = {
    enabled: 'bg-emerald-100 text-emerald-800',
    disabled: 'bg-amber-100 text-amber-800',
    archived: 'bg-slate-200 text-slate-600',
  }

  return (
    <div className="mt-4 space-y-4">
      <button onClick={() => router.push('/skills')} className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900">
        <ArrowLeft className="h-4 w-4" /> 返回列表
      </button>

      <header className="flex items-start justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-semibold tracking-tight text-slate-900">{skillName}</h2>
            <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">{skillId}</code>
            {lifecycle && (
              <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${LIFECYCLE_BADGE[lifecycle] ?? 'bg-slate-100 text-slate-600'}`}>
                {lifecycle}
              </span>
            )}
          </div>
          {definition && (
            <p className="text-sm text-slate-500">
              {definition.business_action} / {definition.business_object}
              {definition.current_version_id && ` · 当前版本: ${definition.current_version_id}`}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void copyToDraft()}
            disabled={acting}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            <Pencil className="h-4 w-4" /> 创建新草稿
          </button>
          {lifecycle === 'enabled' && (
            <button
              type="button"
              onClick={() => void lifecycleAction('disable')}
              disabled={acting}
              className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 px-3 py-2 text-sm font-medium text-amber-700 hover:bg-amber-50 disabled:opacity-50"
            >
              <PowerOff className="h-4 w-4" /> 停用
            </button>
          )}
          {lifecycle === 'disabled' && (
            <>
              <button
                type="button"
                onClick={() => void lifecycleAction('restore')}
                disabled={acting}
                className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-300 px-3 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
              >
                <Power className="h-4 w-4" /> 恢复
              </button>
              <button
                type="button"
                onClick={() => void lifecycleAction('archive')}
                disabled={acting}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                <Archive className="h-4 w-4" /> 归档
              </button>
            </>
          )}
        </div>
      </header>

      {actionError && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" /> {actionError}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="mb-2 text-sm font-semibold text-slate-800">生命周期信息</h3>
          {definition ? (
            <dl className="space-y-1 text-sm">
              <div className="flex justify-between"><dt className="text-slate-500">状态</dt><dd className="font-medium">{definition.lifecycle_status}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">当前版本</dt><dd>{definition.current_version_id ?? '—'}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">语义依赖变更</dt><dd>{definition.semantic_dependency_changed ? '是' : '否'}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">revision</dt><dd>{definition.revision}</dd></div>
              {definition.disabled_at && <div className="flex justify-between"><dt className="text-slate-500">停用时间</dt><dd>{new Date(definition.disabled_at).toLocaleString('zh-CN')}</dd></div>}
              {definition.archived_at && <div className="flex justify-between"><dt className="text-slate-500">归档时间</dt><dd>{new Date(definition.archived_at).toLocaleString('zh-CN')}</dd></div>}
            </dl>
          ) : (
            <p className="text-sm text-slate-400">该 Skill 尚未物化，无生命周期记录</p>
          )}
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="mb-2 text-sm font-semibold text-slate-800">版本与发布</h3>
          <div className="space-y-3">
            <div>
              <p className="mb-1 text-xs font-medium text-slate-500">版本记录</p>
              {versions && versions.length > 0 ? (
                <ul className="space-y-1 text-sm">
                  {versions.slice(0, 5).map((v) => (
                    <li key={v.version_id} className="flex items-center justify-between gap-2">
                      <span className="font-mono text-xs text-slate-700">
                        v{v.semantic_version}
                        <span className="ml-1.5 text-slate-400">{v.version_id.slice(0, 8)}</span>
                      </span>
                      <span className="flex items-center gap-2 text-xs text-slate-500">
                        <span className={
                          v.validation_status === 'passed'
                            ? 'rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700'
                            : 'rounded bg-amber-50 px-1.5 py-0.5 text-amber-700'
                        }>
                          {v.validation_status === 'passed' ? '校验通过' : '待校验'}
                        </span>
                        {v.created_at && new Date(v.created_at).toLocaleDateString('zh-CN')}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-slate-400">暂无版本记录</p>
              )}
            </div>
            <div>
              <p className="mb-1 text-xs font-medium text-slate-500">最近评测</p>
              {evalRuns && evalRuns.items.length > 0 ? (
                <ul className="space-y-1 text-sm">
                  {evalRuns.items.slice(0, 3).map((r) => (
                    <li key={r.run_id} className="flex items-center justify-between gap-2">
                      <span className="font-mono text-xs text-slate-700">{r.run_id.slice(0, 8)}</span>
                      <span className="flex items-center gap-2 text-xs text-slate-500">
                        <span className={
                          r.status === 'passed'
                            ? 'rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700'
                            : 'rounded bg-red-50 px-1.5 py-0.5 text-red-700'
                        }>
                          {r.status === 'passed' ? '通过' : '未通过'}
                        </span>
                        {r.created_at && new Date(r.created_at).toLocaleDateString('zh-CN')}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-slate-400">暂无评测记录</p>
              )}
            </div>
            <div>
              <p className="mb-1 text-xs font-medium text-slate-500">发布记录</p>
              {releases && releases.items.length > 0 ? (
                <ul className="space-y-1 text-sm">
                  {releases.items.slice(0, 3).map((r) => (
                    <li key={r.release_id} className="flex items-center justify-between gap-2">
                      <span className="font-mono text-xs text-slate-700">{r.release_id.slice(0, 8)}</span>
                      <span className="flex items-center gap-2 text-xs text-slate-500">
                        <span className="rounded bg-blue-50 px-1.5 py-0.5 text-blue-700">{r.status}</span>
                        {r.activated_at && new Date(r.activated_at).toLocaleDateString('zh-CN')}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-slate-400">暂无发布记录</p>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
