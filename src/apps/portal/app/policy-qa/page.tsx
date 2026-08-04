'use client'

import PolicyQAWorkspace from '@/components/policy-qa/policy-qa-workspace'

export default function PolicyQAPage() {
  return (
    <div className="relative">
      {/* 背景氛围：柔和渐变 + 细网格（保持“医疗控制台”气质） */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(37,99,235,0.12),transparent_55%),radial-gradient(ellipse_at_bottom,rgba(14,165,233,0.08),transparent_50%)]" />
        <div className="absolute inset-0 opacity-[0.35] [background-image:linear-gradient(to_right,rgba(15,23,42,0.05)_1px,transparent_1px),linear-gradient(to_bottom,rgba(15,23,42,0.05)_1px,transparent_1px)] [background-size:44px_44px]" />
        <div className="absolute -left-24 -top-24 size-[340px] rounded-full bg-blue-500/10 blur-3xl" />
        <div className="absolute -bottom-32 -right-24 size-[420px] rounded-full bg-sky-400/10 blur-3xl" />
      </div>

      <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-6">
        <header className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">
              医保费用 · 智能解答
            </span>
          </div>
          <h2 className="text-xl font-semibold tracking-tight text-slate-900">政策问答</h2>
          <p className="text-sm text-slate-600">
            输入患者结算单号，快速查清费用构成与自付原因，向患者做出准确解释。
          </p>
        </header>

        {/* 持续对话工作区（旧一次性表单组件 policy-qa-chat.tsx 保留作回退） */}
        <PolicyQAWorkspace />
      </div>
    </div>
  )
}
