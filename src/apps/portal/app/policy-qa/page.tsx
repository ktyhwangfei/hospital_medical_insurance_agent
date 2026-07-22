'use client'

import PolicyQAChat from '@/components/policy-qa-chat'

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
              政策·QA
            </span>
            <span className="text-xs text-slate-500">结算解释 / 政策依据 / 双视角输出</span>
          </div>
          <h2 className="text-xl font-semibold tracking-tight text-slate-900">政策问答</h2>
          <p className="text-sm text-slate-600">
            输入结算单号与问题，获取可追溯的政策依据、计算过程与患者/院端解释。
          </p>
        </header>

        <PolicyQAChat />
      </div>
    </div>
  )
}
