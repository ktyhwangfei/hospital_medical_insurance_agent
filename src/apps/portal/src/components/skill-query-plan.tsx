'use client'

import Link from 'next/link'
import { ArrowRight, Database, ShieldCheck } from 'lucide-react'

export interface SkillQueryPlanProps {
  skillId: string
}

export default function SkillQueryPlan({ skillId }: SkillQueryPlanProps) {
  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50/40 p-5">
      <div className="flex items-start gap-3">
        <div className="rounded-lg bg-blue-100 p-2 text-blue-700"><Database className="h-4 w-4" /></div>
        <div className="flex-1">
          <h4 className="text-sm font-semibold text-slate-800">受治理语义查询</h4>
          <p className="mt-1 text-xs text-slate-600">
            Skill <span className="font-mono">{skillId}</span> 的运行时取数由已发布语义模型和 Query Planner 编译；不再使用固定 SQL 或单行读取。
          </p>
          <p className="mt-2 flex items-center gap-1 text-xs text-emerald-700"><ShieldCheck className="h-3.5 w-3.5" />多事实先聚合后关联，分段覆盖不足时失败关闭。</p>
        </div>
      </div>
      <Link href="/semantic-layer/query" className="mt-4 inline-flex items-center gap-1 rounded-md bg-blue-600 px-3 py-2 text-xs font-medium text-white hover:bg-blue-700">
        打开查询验证 <ArrowRight className="h-3.5 w-3.5" />
      </Link>
    </div>
  )
}
