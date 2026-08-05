import { ArrowRight, Copy } from 'lucide-react'

import { Button } from '@/components/ui/button'
import type {
  SkillEvalRunResponse,
  SkillReleaseResponse,
  SkillVersionResponse,
  SkillWorkbenchItem,
  SkillWorkbenchTab,
} from '@/lib/types'
import { lifecycleSteps } from './skill-lifecycle-stepper'

interface SkillOverviewTabProps {
  item: SkillWorkbenchItem
  versions: SkillVersionResponse[]
  evalRuns: SkillEvalRunResponse[]
  releases: SkillReleaseResponse[]
  onNavigate: (tab: SkillWorkbenchTab) => void
}

function shortHash(hash: string | undefined): string {
  return hash ? hash.slice(0, 12) : '—'
}

export default function SkillOverviewTab({
  item,
  versions,
  evalRuns,
  releases,
  onNavigate,
}: SkillOverviewTabProps) {
  const nextStep = lifecycleSteps(item).find((step) => step.state !== 'completed')
  const currentVersion = versions[0]
  const latestRun = evalRuns[0]
  const latestRelease = releases[0]

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <section className="rounded-lg border border-blue-200 bg-blue-50 p-4 xl:col-span-2">
        <p className="text-xs font-medium uppercase tracking-wide text-blue-700">下一步</p>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="font-medium text-slate-950">{nextStep ? `当前建议：${nextStep.label}` : '治理流程已完成'}</p>
            <p className="mt-1 text-sm text-slate-600">{nextStep?.description ?? '当前版本已在 Test Shadow 激活'}</p>
          </div>
          {nextStep && (
            <Button onClick={() => onNavigate(nextStep.tab)}>
              查看证据 <ArrowRight className="h-4 w-4" />
            </Button>
          )}
        </div>
      </section>
      <section className="rounded-lg border border-slate-200 p-4">
        <h3 className="font-medium text-slate-900">当前制品</h3>
        <dl className="mt-3 space-y-2 text-sm">
          <div className="flex justify-between gap-4"><dt className="text-slate-500">语义版本</dt><dd>v{item.semantic_version}</dd></div>
          <div className="flex justify-between gap-4"><dt className="text-slate-500">校验</dt><dd>{item.validation_status}</dd></div>
          <div className="flex items-center justify-between gap-4">
            <dt className="text-slate-500">制品指纹</dt>
            <dd className="flex items-center gap-1 font-mono text-xs">
              {shortHash(currentVersion?.artifact_hash)}
              {currentVersion?.artifact_hash && (
                <button type="button" aria-label="复制制品指纹" onClick={() => void navigator.clipboard?.writeText(currentVersion.artifact_hash)}>
                  <Copy className="h-3.5 w-3.5" />
                </button>
              )}
            </dd>
          </div>
        </dl>
      </section>
      <section className="rounded-lg border border-slate-200 p-4">
        <h3 className="font-medium text-slate-900">最近评测</h3>
        <p className="mt-3 text-2xl font-semibold text-slate-950">{latestRun?.status ?? item.latest_eval_status ?? '未运行'}</p>
        <p className="mt-1 text-sm text-slate-500">Top-1 {latestRun ? `${Math.round(latestRun.metrics.top1_accuracy * 100)}%` : '—'}</p>
      </section>
      <section className="rounded-lg border border-slate-200 p-4 xl:col-span-2">
        <h3 className="font-medium text-slate-900">Test 发布摘要</h3>
        <div className="mt-3 flex flex-wrap gap-x-8 gap-y-2 text-sm">
          <span className="text-slate-500">状态 <strong className="ml-2 text-slate-900">{latestRelease?.status ?? item.test_release_status ?? '无发布'}</strong></span>
          <span className="text-slate-500">Active 版本 <strong className="ml-2 text-slate-900">{item.test_active_version ?? '—'}</strong></span>
          <button type="button" onClick={() => onNavigate('development')} className="font-medium text-blue-700 hover:underline">打开调试与开发详情</button>
        </div>
      </section>
    </div>
  )
}
