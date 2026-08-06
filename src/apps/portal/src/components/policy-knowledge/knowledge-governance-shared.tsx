import Link from 'next/link'

type KnowledgeFlowStage = 'build' | 'review' | 'release'

const FLOW_STAGES = [
  { id: 'document', label: '文档接入' },
  { id: 'unit', label: '单元拆分与审核' },
  { id: 'build', label: '知识构建' },
  { id: 'review', label: '知识审核' },
  { id: 'release', label: '发布正式版本' },
] as const

const CURRENT_STAGE_INDEX: Record<KnowledgeFlowStage, number> = {
  build: 2,
  review: 3,
  release: 4,
}

export function KnowledgeFlow({ current }: { current: KnowledgeFlowStage }) {
  const currentIndex = CURRENT_STAGE_INDEX[current]

  return (
    <ol
      aria-label="知识治理流程"
      className="flex items-center gap-2 overflow-x-auto py-2 text-xs"
    >
      {FLOW_STAGES.map((stage, index) => {
        const status = index < currentIndex ? '已完成' : index === currentIndex ? '当前' : '后续'
        const isDone = index < currentIndex
        const isCurrent = index === currentIndex

        return (
          <li
            key={stage.id}
            aria-label={`${stage.label}：${status}`}
            aria-current={isCurrent ? 'step' : undefined}
            className={`flex shrink-0 items-center rounded-full ${
              isCurrent
                ? 'bg-emerald-50 px-2.5 py-1 font-semibold text-emerald-800 ring-1 ring-emerald-600/20'
                : isDone
                  ? 'px-2 py-1 font-medium text-emerald-700'
                  : 'px-2 py-1 text-slate-400'
            }`}
          >
            <span>{stage.label}</span>
            {index < FLOW_STAGES.length - 1 && (
              <span aria-hidden="true" className={`ml-2 ${isCurrent || isDone ? 'text-emerald-300' : 'text-slate-300'}`}>{' → '}</span>
            )}
          </li>
        )
      })}
    </ol>
  )
}

type BuildContextBarProps = {
  availableUnitCount: number | null
  semanticContractVersion: string | null
}

export function BuildContextBar({
  availableUnitCount,
  semanticContractVersion,
}: BuildContextBarProps) {
  return (
    <aside
      aria-label="知识构建上下文"
      className="flex items-center gap-3 overflow-x-auto whitespace-nowrap border-y border-slate-200 py-2.5 text-xs tracking-wide text-slate-600"
    >
      <span>可用单元：{availableUnitCount ?? '暂无统计'}</span>
      <span aria-hidden="true" className="text-slate-300">·</span>
      <span>语义契约版本：{semanticContractVersion ?? '暂无版本'}</span>
      <span aria-hidden="true" className="text-slate-300">·</span>
      <span className="inline-flex items-center rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">本页只读</span>
      <Link
        href="/semantic-layer/metrics"
        className="ml-auto font-medium text-emerald-700 hover:text-emerald-800 hover:underline"
      >
        查看语义层
      </Link>
    </aside>
  )
}
