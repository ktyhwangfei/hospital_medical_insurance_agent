'use client'

// P9.5 结构化 tab（占位）——提取规则库 + 三模式混合搜索（精准/语义/混合，target=policy/database/both）。
// 合并现 rules（已入库规则）+ search（知识检索）两个页面。
// 完整实现见后续 P9.5 任务；当前为路由骨架。

export default function StructuredPage() {
  return (
    <div className="rounded-xl border border-slate-200 bg-white/80 p-8 backdrop-blur">
      <h1 className="text-lg font-semibold text-slate-800">结构化</h1>
      <p className="mt-2 text-sm text-slate-500">
        规则库列表 + 三模式混合检索（精准/语义/混合，跨世界联查）。
      </p>
      <div className="mt-6 flex flex-col gap-2 rounded-lg bg-slate-50 p-4 text-xs text-slate-500">
        <span><span className="rounded bg-amber-100 px-2 py-0.5 text-amber-700">待实现</span> 合并来源：</span>
        <code className="rounded bg-slate-100 px-1">GET /policy-knowledge/rules · POST /policy-pipeline/rules/search</code>
      </div>
    </div>
  )
}