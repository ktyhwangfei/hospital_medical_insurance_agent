'use client'

import EvalCasePoolTable from '@/components/skills/eval-case-pool-table'

// /skills/eval-case-pool 错误案例池页：评测者浏览用户反馈挖掘出的回归案例
export default function EvalCasePoolPage() {
  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-8">
      <header>
        <h1 className="text-2xl font-bold text-slate-900">错误案例池</h1>
        <p className="mt-1 text-sm text-slate-500">
          汇总政策问答中用户标注的「回答有误」案例，用于 Skill 回归测试与评测。
        </p>
      </header>
      <EvalCasePoolTable />
    </div>
  )
}
