import { ModelGovernanceWorkspace } from '@/components/model-governance-workspace'

export default function ModelGovernancePage() {
  return <main className="mx-auto flex min-w-0 max-w-6xl flex-col gap-6">
    <header>
      <h2 className="text-xl font-semibold tracking-tight text-slate-800">后台管理</h2>
      <p className="mt-1 max-w-2xl text-sm text-slate-500">管理真实提示词、模型、路由规则与发布版本。</p>
    </header>
    <ModelGovernanceWorkspace />
  </main>
}
