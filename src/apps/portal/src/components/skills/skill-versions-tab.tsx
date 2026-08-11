import { useState } from 'react'
import { GitCommit, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { syncInfraSkillVersion } from '@/lib/api-client'
import type { SkillVersionResponse, SkillWorkbenchItem } from '@/lib/types'

interface SkillVersionsTabProps {
  item: SkillWorkbenchItem
  versions: SkillVersionResponse[]
  error: string | null
  readOnly: boolean
  onChanged: () => void
}

export default function SkillVersionsTab({ item, versions, error, readOnly, onChanged }: SkillVersionsTabProps) {
  const [syncing, setSyncing] = useState(false)
  const [mutationError, setMutationError] = useState<string | null>(null)

  async function syncVersion(): Promise<void> {
    setSyncing(true)
    setMutationError(null)
    try {
      await syncInfraSkillVersion(item.skill_id, { created_by: 'portal-user' })
      onChanged()
    } catch (syncError) {
      setMutationError(syncError instanceof Error ? syncError.message : '版本登记失败')
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 p-4">
        <div>
          <h3 className="font-medium text-slate-900">当前工作区制品</h3>
          <p className="mt-1 text-sm text-slate-500">{item.artifact_status === 'registered' ? '当前内容与登记版本一致' : '检测到未登记的制品变化'}</p>
        </div>
        {item.artifact_status !== 'registered' && (
          <Button data-testid="register-skill-version" disabled={readOnly || syncing} onClick={() => void syncVersion()}>
            <RefreshCw className="h-4 w-4" /> {syncing ? '登记中…' : '登记当前制品'}
          </Button>
        )}
      </div>
      {(error || mutationError) && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error ?? mutationError}</p>}
      <ol className="relative ml-2 border-l border-slate-200 pl-5">
        {versions.length === 0 ? <li className="py-4 text-sm text-slate-500">暂无登记版本</li> : versions.map((version) => (
          <li key={version.version_id} className="relative pb-5 last:pb-0">
            <span className="absolute -left-[1.6rem] top-1 flex h-5 w-5 items-center justify-center rounded-full border border-slate-200 bg-white"><GitCommit className="h-3 w-3" /></span>
            <div className="flex flex-wrap items-center gap-2">
              <strong className="text-sm text-slate-900">v{version.semantic_version}</strong>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{version.validation_status}</span>
            </div>
            <p className="mt-1 font-mono text-xs text-slate-500">{version.artifact_hash.slice(0, 12)} · {version.source_commit?.slice(0, 12) || '无提交信息'}</p>
            <time className="mt-1 block text-xs text-slate-400">{new Date(version.created_at).toLocaleString('zh-CN')}</time>
          </li>
        ))}
      </ol>
    </div>
  )
}
