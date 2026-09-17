'use client'

// 「下一步」引导卡片：数据资产生命周期各阶段页底部，引导用户走完闭环。
import Link from 'next/link'
import { ArrowRight } from 'lucide-react'

export function NextStepCard({ href, title, description }: {
  href: string
  title: string
  description: string
}) {
  return (
    <Link href={href} data-testid="next-step-card"
      className="group flex items-center gap-3 rounded-xl border border-dashed border-slate-300 bg-white px-4 py-3 transition-colors hover:border-blue-300 hover:bg-blue-50/40">
      <div className="min-w-0 flex-1">
        <p className="text-xs text-slate-400">下一步</p>
        <p className="truncate text-sm font-medium text-slate-800 group-hover:text-blue-800">{title}</p>
        <p className="mt-0.5 truncate text-xs text-slate-500">{description}</p>
      </div>
      <ArrowRight className="size-4 shrink-0 text-slate-300 transition-colors group-hover:text-blue-500" />
    </Link>
  )
}
