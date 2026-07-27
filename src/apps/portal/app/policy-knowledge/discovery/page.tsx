'use client'

// P9.6 发现 tab（占位）——扫描候选指标 → 人工确认 → 回写语义层。
// 完整实现见后续 P9.6 任务；当前为路由骨架。

export default function DiscoveryPage() {
  return (
    <div className="rounded-xl border border-slate-200 bg-white/80 p-8 backdrop-blur">
      <h1 className="text-lg font-semibold text-slate-800">发现</h1>
      <p className="mt-2 text-sm text-slate-500">
        多源扫描候选指标 → 确认 → 回写语义层。
      </p>
      <div className="mt-6 flex flex-col gap-2 rounded-lg bg-slate-50 p-4 text-xs text-slate-500">
        <span><span className="rounded bg-amber-100 px-2 py-0.5 text-amber-700">待实现</span> 数据来源：</span>
        <code className="rounded bg-slate-100 px-1">POST /semantic/discovery/scan · GET /semantic/discovery/results</code>
      </div>
    </div>
  )
}