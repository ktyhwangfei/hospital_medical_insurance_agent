'use client'

import { AlertTriangle, CheckCircle2, Loader2, ShieldCheck } from 'lucide-react'

import type { SkillAIGenerationProposal } from '@/lib/types'

interface SkillDraftPreviewProps {
  proposal: SkillAIGenerationProposal
  accepting: boolean
  onAccept: () => void
  onBack: () => void
}

const CODE_FILES = ['assembler.py', 'prompt_template.yaml'] as const

export default function SkillDraftPreview({
  proposal,
  accepting,
  onAccept,
  onBack,
}: SkillDraftPreviewProps) {
  const { structured_config: config, provenance, validation_preview: validation } = proposal

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-amber-900">
            <span>AI 生成候选 · </span><span>尚未进入运行时</span>
          </p>
          <p className="mt-1 text-xs text-amber-700">接受后只会创建可编辑草稿，仍需校验、评测和人工发布。</p>
        </div>
        <span className="rounded-full bg-white px-2.5 py-1 font-mono text-[11px] text-amber-800">
          {provenance.model_type}
        </span>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-slate-900">派生配置</h3>
        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
          <ConfigItem label="Skill" value={`${config.basic.skill_name} (${config.basic.skill_id})`} />
          <ConfigItem label="业务挂载" value={`${config.business_mounting.business_action} / ${config.business_mounting.business_object}`} />
          <ConfigItem label="负责人" value={config.basic.owner || '—'} />
          <ConfigItem label="Prompt 版本" value={provenance.prompt_version} />
        </dl>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        {CODE_FILES.map((name) => (
          <CodePanel key={name} title={name} content={proposal.raw_files[name] ?? '（未生成）'} />
        ))}
        <CodePanel title="输入 Schema" content={JSON.stringify(config.schemas.input, null, 2)} />
        <CodePanel title="输出 Schema" content={JSON.stringify(config.schemas.output, null, 2)} />
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-slate-900">冻结指标版本</h3>
        <div className="mt-3 flex flex-wrap gap-2">
          {provenance.metric_versions.map((metric) => (
            <span key={`${metric.metric_code}-${metric.object_version}`} className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700">
              {metric.metric_code}@v{metric.object_version} · {metric.status}
            </span>
          ))}
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            {validation.blocking_ok ? <CheckCircle2 className="h-4 w-4 text-green-600" /> : <AlertTriangle className="h-4 w-4 text-amber-600" />}
            校验预览
          </h3>
          <p className="mt-2 text-xs text-slate-600">
            {validation.blocking_ok ? '未发现阻塞项' : `发现 ${validation.issues.length} 个问题`}
          </p>
          {validation.issues.map((issue) => (
            <p key={`${issue.code}-${issue.path ?? ''}`} className="mt-2 text-xs text-slate-700">{issue.code}: {issue.message}</p>
          ))}
        </section>
        <section className="rounded-xl border border-green-200 bg-green-50 p-4">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-green-900">
            <ShieldCheck className="h-4 w-4" />安全扫描通过
          </h3>
          <p className="mt-2 break-all font-mono text-[11px] text-green-800">content hash: {provenance.content_hash}</p>
        </section>
      </div>

      <section className="grid gap-4 md:grid-cols-2">
        <EvidenceList title="来源" items={proposal.citations.map((item) => `${item.source_id} · ${item.summary}`)} empty="无引用" />
        <EvidenceList title="不确定性" items={proposal.uncertainties} empty="未声明不确定性" />
      </section>

      <div className="flex items-center justify-end gap-3">
        <button type="button" onClick={onBack} disabled={accepting} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
          返回修改
        </button>
        <button type="button" onClick={onAccept} disabled={accepting} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
          {accepting ? <><Loader2 className="h-4 w-4 animate-spin" />正在接受</> : '接受为草稿'}
        </button>
      </div>
    </div>
  )
}

function ConfigItem({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 text-slate-800">{value}</dd></div>
}

function CodePanel({ title, content }: { title: string; content: string }) {
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-slate-950">
      <h3 className="border-b border-slate-800 px-4 py-2 font-mono text-xs font-semibold text-slate-300">{title}</h3>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap p-4 font-mono text-xs text-slate-100">{content}</pre>
    </section>
  )
}

function EvidenceList({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      <ul className="mt-2 space-y-1 text-xs text-slate-600">
        {(items.length ? items : [empty]).map((item) => <li key={item}>• {item}</li>)}
      </ul>
    </div>
  )
}
