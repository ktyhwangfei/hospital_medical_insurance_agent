'use client'

import { useRouter } from 'next/navigation'
import { Plus, Upload } from 'lucide-react'
import SkillGovernanceWorkbench from '@/components/skills/skill-governance-workbench'

// /skills 管理列表页：正式 Skill 治理工作台（设计 §3.2）
// 顶部提供新建/导入入口，主体复用现有治理工作台
export default function SkillsManagementPage() {
  const router = useRouter()

  return (
    <div className="mt-4 space-y-4">
      <header className="flex items-center justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">
              Skill 管理工作台
            </span>
          </div>
          <h2 className="text-xl font-semibold tracking-tight text-slate-900">
            正式 Skill 管理列表
          </h2>
          <p className="text-sm text-slate-600">
            管理 Skill 生命周期：草稿编辑、校验、物化、发布、停用与归档。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => router.push('/skills/import')}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50"
          >
            <Upload className="h-4 w-4" />
            导入 Skill
          </button>
          <button
            type="button"
            onClick={() => router.push('/skills/new')}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-blue-700"
          >
            <Plus className="h-4 w-4" />
            新建 Skill
          </button>
        </div>
      </header>

      <SkillGovernanceWorkbench />
    </div>
  )
}
