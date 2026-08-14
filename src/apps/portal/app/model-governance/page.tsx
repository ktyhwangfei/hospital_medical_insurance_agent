'use client'

import { useEffect, useState } from 'react'
import { AlertTriangle, BookOpenCheck, Cpu, Route, Server } from 'lucide-react'
import {
  getModelGovernanceSnapshot,
  type CredentialStatus,
  type GatewayStatus,
  type ManagementStatus,
  type ModelGovernanceSnapshot,
  type PromptSourceKind,
} from '@/lib/model-governance-api'

const sourceKindLabel: Record<PromptSourceKind, string> = {
  code: '代码文件',
  yaml: 'YAML 配置',
  dynamic: '动态生成',
}

const gatewayStatusLabel: Record<GatewayStatus, string> = {
  routed: '统一网关',
  direct: '直连调用',
  unknown: '调用待核验',
}

const managementStatusLabel: Record<ManagementStatus, string> = {
  source_managed: '源文件管理',
  needs_migration: '需迁移',
  needs_verification: '待核验',
}

const credentialStatusLabel: Record<CredentialStatus, string> = {
  configured: '凭据已配置',
  missing: '未配置凭据',
}

function promptStatus(gatewayStatus: GatewayStatus, managementStatus: ManagementStatus): string {
  if (gatewayStatus === 'direct' && managementStatus === 'needs_migration') {
    return '直连待迁移'
  }
  return `${gatewayStatusLabel[gatewayStatus]} / ${managementStatusLabel[managementStatus]}`
}

function redactedEndpoint(endpoint: string): string {
  if (endpoint === 'dummy') return endpoint
  try {
    const url = new URL(endpoint)
    return url.origin
  } catch {
    return '无效端点'
  }
}

export default function ModelGovernancePage() {
  const [snapshot, setSnapshot] = useState<ModelGovernanceSnapshot | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)

  useEffect(() => {
    let active = true

    void getModelGovernanceSnapshot()
      .then((data) => {
        if (active) setSnapshot(data)
      })
      .catch(() => {
        if (active) setLoadFailed(true)
      })

    return () => { active = false }
  }, [])

  if (loadFailed) {
    return (
      <section className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-800">
        <div className="flex items-center gap-2 font-medium">
          <AlertTriangle className="size-4" />
          治理快照暂不可用
        </div>
        <p className="mt-1 text-xs text-amber-700">请稍后重试。页面不会以空数据替代当前治理状态。</p>
      </section>
    )
  }

  if (!snapshot) {
    return <p className="text-sm text-slate-500">正在加载治理快照</p>
  }

  const summary = [
    { label: '提示词', value: snapshot.prompts.length, icon: BookOpenCheck },
    { label: '模型', value: snapshot.models.length, icon: Cpu },
    { label: '路由', value: snapshot.routes.length, icon: Route },
    { label: 'Provider', value: snapshot.providers.length, icon: Server },
  ]

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <header className="flex flex-wrap items-start gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-slate-800">模型与提示词治理</h2>
          <p className="mt-1 text-sm text-slate-500">统一网关、路由和提示词来源的只读台账</p>
        </div>
        <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">只读台账</span>
      </header>

      <section aria-label="治理摘要" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {summary.map(({ label, value, icon: Icon }) => (
          <div key={label} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-xs text-slate-500"><Icon className="size-4 text-blue-600" />{label}</div>
            <p className="mt-2 text-2xl font-semibold text-slate-800">{value}</p>
          </div>
        ))}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 px-5 py-4">
          <h3 className="text-sm font-semibold text-slate-700">提示词台账</h3>
          <p className="mt-1 text-xs text-slate-500">提示词来源、调用入口与治理状态</p>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <caption className="sr-only">提示词台账</caption>
            <thead className="bg-slate-50 text-xs text-slate-500">
              <tr><th className="px-5 py-3 font-medium">提示词</th><th className="px-5 py-3 font-medium">来源</th><th className="px-5 py-3 font-medium">场景</th><th className="px-5 py-3 font-medium">状态</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-700">
              {snapshot.prompts.map((prompt) => (
                <tr key={prompt.prompt_id}>
                  <td className="px-5 py-3"><p className="font-medium">{prompt.name}</p><p className="mt-0.5 font-mono text-xs text-slate-400">{prompt.prompt_id}</p></td>
                  <td className="max-w-72 px-5 py-3"><p className="break-all font-mono text-xs text-slate-600">{prompt.source_path}</p><p className="mt-1 text-xs text-slate-400">{sourceKindLabel[prompt.source_kind]}</p></td>
                  <td className="px-5 py-3 text-xs text-slate-600">{prompt.scene ?? '未登记场景'}</td>
                  <td className="px-5 py-3"><span className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-700">{promptStatus(prompt.gateway_status, prompt.management_status)}</span>{prompt.warnings.map((warning) => <p key={warning} className="mt-1 text-xs text-amber-700">{warning}</p>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-700">模型概览</h3>
          <div className="mt-4 space-y-3">
            {snapshot.models.map((model) => <div key={model.model_name} className="flex items-center justify-between border-b border-slate-100 pb-3 text-sm last:border-0 last:pb-0"><span className="font-mono text-slate-700">{model.model_name}</span><span className="text-xs text-slate-500">温度 {model.temperature}，最大 {model.max_tokens} tokens</span></div>)}
          </div>
        </section>
        <section aria-label="Provider 概览" className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-700">Provider 概览</h3>
          <div className="mt-4 space-y-3">
            {snapshot.providers.map((provider) => <div key={provider.provider_id} className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3 text-sm last:border-0 last:pb-0"><span className="break-all font-mono text-slate-700">{redactedEndpoint(provider.endpoint)}</span><span className={`rounded px-2 py-1 text-xs ${provider.credential_status === 'configured' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>{credentialStatusLabel[provider.credential_status]}</span></div>)}
          </div>
        </section>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 px-5 py-4"><h3 className="text-sm font-semibold text-slate-700">路由台账</h3></div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <caption className="sr-only">模型路由台账</caption>
            <thead className="bg-slate-50 text-xs text-slate-500"><tr><th className="px-5 py-3 font-medium">场景</th><th className="px-5 py-3 font-medium">模型类型</th><th className="px-5 py-3 font-medium">生效模型</th><th className="px-5 py-3 font-medium">路由状态</th><th className="px-5 py-3 font-medium">备用模型</th></tr></thead>
            <tbody className="divide-y divide-slate-100 text-slate-700">
              {snapshot.routes.map((route) => <tr key={`${route.scene}:${route.model_type}`}><td className="px-5 py-3 font-mono text-xs">{route.scene}</td><td className="px-5 py-3">{route.model_type}</td><td className="px-5 py-3 font-mono text-xs">{route.effective_model ?? '未解析'}</td><td className="px-5 py-3"><span className="rounded bg-blue-50 px-2 py-1 text-xs text-blue-700">{route.explicit ? '显式路由' : '默认路由'}</span>{route.warnings.map((warning) => <p key={warning} className="mt-1 text-xs text-amber-700">{warning}</p>)}</td><td className="px-5 py-3 font-mono text-xs text-slate-500">{route.fallbacks.length ? route.fallbacks.join('，') : '无'}</td></tr>)}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-700">来源与待核验说明</h3>
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          <div><p className="text-xs font-medium text-slate-500">来源</p><ul className="mt-2 space-y-1 text-xs text-slate-600">{snapshot.citations.map((citation) => <li key={citation} className="break-all font-mono">{citation}</li>)}</ul></div>
          <div><p className="text-xs font-medium text-slate-500">待核验</p><ul className="mt-2 space-y-1 text-xs text-amber-700">{snapshot.uncertainties.map((uncertainty) => <li key={uncertainty}>{uncertainty}</li>)}</ul></div>
        </div>
      </section>
    </div>
  )
}
