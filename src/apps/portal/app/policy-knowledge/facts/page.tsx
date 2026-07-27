'use client'

// P9.4 事实 tab（占位）——原文→最小事实拆分 + 向量化管理。
// 完整实现见后续 P9.4 任务；当前为路由骨架，保证 5 tab 可切换。

export default function FactsPage() {
  return (
    <div className="rounded-xl border border-slate-200 bg-white/80 p-8 backdrop-blur">
      <h1 className="text-lg font-semibold text-slate-800">事实</h1>
      <p className="mt-2 text-sm text-slate-500">
        原文 → 最小事实拆分 + 向量化管理（P9.4 实现中）。
      </p>
      <div className="mt-6 flex items-center gap-2 rounded-lg bg-slate-50 p-4 text-xs text-slate-500">
        <span className="rounded bg-amber-100 px-2 py-0.5 text-amber-700">待实现</span>
        数据来源：<code className="rounded bg-slate-100 px-1">GET /policy-pipeline/extractions</code>
        （拆出原文→事实拆分与向量化管理视图）
      </div>
    </div>
  )
}