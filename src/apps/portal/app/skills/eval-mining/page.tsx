'use client'

import EvalCasePoolList from '@/components/skills/eval-case-pool-list'

// /skills/eval-mining 案例挖掘页：AI 转换 + 人工分型编辑确认
export default function EvalMiningPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <header>
        <h1 className="text-2xl font-bold text-slate-900">案例挖掘</h1>
        <p className="mt-1 text-sm text-slate-500">
          汇总政策问答中的「回答有误」反馈：AI 类型化转换 → 人工编辑确认 → 投影到评测回归资产。
        </p>
      </header>
      <EvalCasePoolList />
    </div>
  )
}
