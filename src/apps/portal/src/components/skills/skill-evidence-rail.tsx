import type {
  SkillEvalRunResponse,
  SkillReleaseResponse,
  SkillVersionResponse,
  SkillWorkbenchItem,
} from '@/lib/types'

interface SkillEvidenceRailProps {
  item: SkillWorkbenchItem
  latestRun: SkillEvalRunResponse | null
  latestRelease: SkillReleaseResponse | null
  latestVersion: SkillVersionResponse | null
  historicalRuns?: SkillEvalRunResponse[]
  state?: 'loading' | 'ready' | 'unavailable'
  variant?: 'rail' | 'drawer'
}

export function shortHash(value?: string | null): string {
  if (value == null) return '—'
  return value.length > 12 ? `${value.slice(0, 6)}…${value.slice(-6)}` : value
}

function EvidenceContent({
  item,
  latestRun,
  latestRelease,
  latestVersion,
  historicalRuns = latestRun ? [latestRun] : [],
  state = 'ready',
}: Omit<SkillEvidenceRailProps, 'variant'>) {
  const currentGateEvidence = Boolean(
    state === 'ready'
    && latestRun
    && latestVersion
    && item.latest_eval_run_id === latestRun.run_id
    && item.latest_eval_status === latestRun.status
    && item.artifact_status === 'registered'
    && item.validation_status === 'passed'
    && latestRun.version_id === latestVersion.version_id
    && (!item.candidate_version || item.candidate_version === latestVersion.semantic_version),
  )
  const emptyEvaluation = state === 'ready' && !item.latest_eval_run_id && historicalRuns.length === 0
  const gatePassed = Boolean(currentGateEvidence && latestRun?.metrics.gate_passed && latestRun.status === 'passed')
  const records = [
    latestVersion && ['版本登记', latestVersion.created_by, latestVersion.created_at],
    ...historicalRuns.map((run) => [
      `固定评测 · ${shortHash(run.run_id)}`,
      run.created_by,
      run.completed_at ?? run.created_at,
    ]),
    latestRelease && ['发布候选', latestRelease.created_by, latestRelease.created_at],
    latestRelease?.approval && ['人工复审', latestRelease.approval.approved_by, latestRelease.approval.approved_at],
    latestRelease?.activated_at && ['Test 激活', '执行人不可用', latestRelease.activated_at],
  ].filter(Boolean) as string[][]

  return (
    <div className="divide-y divide-slate-200">
      <section className="p-4">
        <h3 className="text-sm font-semibold text-slate-950">门禁结论</h3>
        <p className={`mt-2 text-sm font-medium ${gatePassed ? 'text-emerald-700' : 'text-amber-700'}`}>
          {state === 'loading'
            ? '正在加载当前门禁证据'
            : emptyEvaluation
              ? '尚无评测结论'
              : gatePassed
                ? '固定评测门禁通过'
                : currentGateEvidence
                  ? '暂不可进入下一阶段'
                  : '当前门禁证据不可用'}
        </p>
        <p className="mt-1 break-words text-xs leading-5 text-slate-600">
          {!currentGateEvidence
            ? item.next_action_reason ?? '当前队列事实与已加载评测不一致，请刷新。'
            : gatePassed
            ? '评测运行与冻结证据完整。'
            : latestRun
              ? `新增回归 ${latestRun.metrics.regression_count}，必测通过 ${latestRun.metrics.required_passed}/${latestRun.metrics.required_total}。`
              : '需要先加载并完成固定评测。'}
        </p>
      </section>
      <section className="p-4">
        <h3 className="text-sm font-semibold text-slate-950">冻结证据</h3>
        <dl className="mt-3 space-y-2 text-xs">
          <div className="flex justify-between gap-3"><dt className="text-slate-500">候选版本</dt><dd>{latestVersion?.semantic_version ?? '—'}</dd></div>
          <div className="flex justify-between gap-3"><dt className="text-slate-500">评测运行</dt><dd className="font-mono">{shortHash(latestRun?.run_id)}</dd></div>
          <div className="flex justify-between gap-3"><dt className="text-slate-500">Suite revision</dt><dd>{latestRun?.suite_version ?? '—'}</dd></div>
          <div className="flex justify-between gap-3"><dt className="text-slate-500">Artifact</dt><dd className="font-mono">{shortHash(latestVersion?.artifact_hash ?? latestRelease?.artifact_hash)}</dd></div>
          <div className="flex justify-between gap-3"><dt className="text-slate-500">Config</dt><dd className="font-mono">{shortHash(latestRun?.config_hash ?? latestRelease?.config_hash)}</dd></div>
          <div className="flex justify-between gap-3"><dt className="text-slate-500">Routing manifest</dt><dd className="font-mono">{shortHash(latestRun?.routing_manifest_hash)}</dd></div>
          <div className="flex justify-between gap-3"><dt className="text-slate-500">Source commit</dt><dd className="font-mono">{shortHash(latestVersion?.source_commit)}</dd></div>
        </dl>
      </section>
      <section className="p-4">
        <h3 className="text-sm font-semibold text-slate-950">最近记录</h3>
        {records.length ? (
          <ol className="mt-3 space-y-3">
            {records.map(([label, actor, at]) => (
              <li key={`${label}-${at}`} className="text-xs leading-5">
                <p className="font-medium text-slate-800">{label}</p>
                <p className="break-words text-slate-500">{actor} · {new Date(at).toLocaleString('zh-CN')}</p>
              </li>
            ))}
          </ol>
        ) : <p className="mt-2 text-xs text-slate-500">暂无记录</p>}
      </section>
    </div>
  )
}

export default function SkillEvidenceRail(props: SkillEvidenceRailProps) {
  const { variant = 'rail', ...contentProps } = props
  return variant === 'rail' ? (
    <aside aria-label="治理证据" className="hidden min-h-0 overflow-y-auto border-l border-slate-200 bg-slate-50/60 2xl:block">
      <EvidenceContent {...contentProps} />
    </aside>
  ) : <EvidenceContent {...contentProps} />
}
