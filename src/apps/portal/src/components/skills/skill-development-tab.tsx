import type { InfraSkillDetailResponse } from '@/lib/types'

interface SkillDevelopmentTabProps {
  detail: InfraSkillDetailResponse | null
  error: string | null
  onOpenExecution: () => void
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="mt-3 max-h-96 overflow-auto rounded-lg bg-slate-950 p-4 text-xs leading-5 text-slate-100">{JSON.stringify(value, null, 2)}</pre>
}

export default function SkillDevelopmentTab({ detail, error, onOpenExecution }: SkillDevelopmentTabProps) {
  if (error) return <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>
  if (!detail) return <p className="text-sm text-slate-500">正在加载开发详情…</p>

  const groups = [
    { label: '费用项解析', content: detail.manifest.target_fee_item ?? '未配置费用项解析规则' },
    { label: '查询计划', content: detail.manifest.query_plan ?? '未配置查询计划' },
    { label: '字段映射', content: detail.field_mapping ?? '未配置字段映射' },
    { label: 'Manifest', content: detail.manifest },
    { label: '目录结构', content: detail.files_structure },
  ]

  return (
    <div className="space-y-3">
      <button type="button" onClick={onOpenExecution} className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100">执行调试</button>
      <div className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
      {groups.map((group) => (
        <details key={group.label} className="group p-4">
          <summary className="cursor-pointer font-medium text-slate-900">{group.label}</summary>
          <JsonBlock value={group.content} />
        </details>
      ))}
      <details className="group p-4">
        <summary className="cursor-pointer font-medium text-slate-900">SKILL.md</summary>
        <pre className="mt-3 max-h-[36rem] overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-4 text-sm leading-6 text-slate-700">{detail.readme || '暂无 SKILL.md 内容'}</pre>
      </details>
      </div>
    </div>
  )
}
