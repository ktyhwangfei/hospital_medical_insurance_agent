'use client'

import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'

import { ModelGovernanceWorkspace } from '@/components/model-governance-workspace'
import { getModelGovernanceSnapshot } from '@/lib/model-governance-api'

export default function ModelGovernancePage() {
  const [ready, setReady] = useState(false)
  const [loadFailed, setLoadFailed] = useState(false)

  useEffect(() => {
    let active = true
    const timer = window.setTimeout(() => {
      setReady(false)
      setLoadFailed(false)
      void getModelGovernanceSnapshot()
        .then(() => { if (active) setReady(true) })
        .catch(() => { if (active) setLoadFailed(true) })
    }, 0)
    return () => { active = false; window.clearTimeout(timer) }
  }, [])

  if (loadFailed) {
    return <section role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-800">
      <div className="flex items-center gap-2 font-medium"><AlertTriangle className="size-4" />治理快照暂不可用</div>
      <p className="mt-1 text-xs text-amber-700">请稍后重试。页面不会以空数据替代当前治理状态。</p>
    </section>
  }

  if (!ready) {
    return <p role="status" aria-live="polite" className="text-sm text-slate-500">正在加载治理快照</p>
  }

  return <main className="mx-auto flex min-w-0 max-w-6xl flex-col gap-6">
    <header>
      <h2 className="text-xl font-semibold tracking-tight text-slate-800">后台管理</h2>
      <p className="mt-1 max-w-2xl text-sm text-slate-500">管理真实提示词、模型、路由规则与发布版本。</p>
    </header>
    <ModelGovernanceWorkspace />
  </main>
}
