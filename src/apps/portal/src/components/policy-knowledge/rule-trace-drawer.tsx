'use client'

import { useEffect, useState, type ReactNode } from 'react'
import { Loader2, RefreshCw, X } from 'lucide-react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  getRuleCompilationTrace,
  type RuleCompilationTrace,
} from '@/lib/policy-knowledge-api'

interface RuleTraceDrawerProps {
  open: boolean
  ruleId: string | null
  runId?: string | null
  onOpenChange: (open: boolean) => void
}

export default function RuleTraceDrawer({ open, ruleId, runId, onOpenChange }: RuleTraceDrawerProps) {
  const targetRunId = runId ?? null
  const [loadedTrace, setLoadedTrace] = useState<{
    ruleId: string
    runId: string | null
    trace: RuleCompilationTrace
  } | null>(null)
  const trace = loadedTrace?.ruleId === ruleId && loadedTrace.runId === targetRunId
    ? loadedTrace.trace
    : null
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [fullPayload, setFullPayload] = useState<RuleCompilationTrace | null>(null)

  useEffect(() => {
    if (!open || !ruleId) return
    let active = true
    setLoading(true)
    setError('')
    setLoadedTrace(null)
    void getRuleCompilationTrace(ruleId, targetRunId)
      .then((result) => {
        if (active) setLoadedTrace({ ruleId, runId: targetRunId, trace: result })
      })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : '轨迹加载失败')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [open, ruleId, targetRunId, retry])

  const close = () => {
    setFullPayload(null)
    onOpenChange(false)
  }

  return (
    <>
      <Dialog open={open} onOpenChange={(next) => next ? onOpenChange(true) : close()}>
        <DialogContent
          showCloseButton={false}
          className="inset-y-0 left-auto right-0 top-0 h-dvh w-full max-w-3xl translate-x-0 translate-y-0 content-start overflow-y-auto rounded-none p-6 sm:max-w-3xl"
        >
          <DialogHeader>
            <div className="flex items-start justify-between gap-4">
              <div>
                <DialogTitle>规则编译溯源</DialogTitle>
                <DialogDescription>查看原始输入、模型提取、确定性编译步骤与发布血缘。</DialogDescription>
              </div>
              <button type="button" aria-label="关闭溯源" onClick={close} className="rounded-md p-1 text-slate-500 hover:bg-slate-100">
                <X className="size-4" />
              </button>
            </div>
          </DialogHeader>

          {loading && (
            <p className="flex items-center gap-2 py-8 text-sm text-slate-500">
              <Loader2 className="size-4 animate-spin" />正在加载编译轨迹…
            </p>
          )}
          {error && (
            <div role="alert" className="space-y-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              <p>{error}</p>
              <button type="button" onClick={() => setRetry((value) => value + 1)} className="inline-flex items-center gap-1 rounded border border-red-200 bg-white px-2 py-1 font-medium">
                <RefreshCw className="size-3" />重试
              </button>
            </div>
          )}
          {trace && (
            <div className="space-y-5">
              <div className="flex flex-wrap gap-2 text-xs">
                {trace.rule ? <Badge>{trace.rule.source_type}</Badge> : <Badge>未生成规范规则</Badge>}
                <Badge>{trace.run.status}</Badge>
                {trace.rule && <Badge>规则版本 {trace.rule.rule_version}</Badge>}
                <Badge>编译器 {trace.rule?.compiler_version ?? trace.run.compiler_version}</Badge>
                {trace.publication && <Badge>发布 {trace.publication.release_id}</Badge>}
              </div>

              <JsonDetails label="原始输入" value={trace.raw_input} />
              <JsonDetails label="LLM 提取" value={trace.llm_output} />

              <section aria-label="编译步骤" className="space-y-2">
                {[...trace.steps]
                  .sort((left, right) => left.sequence_no - right.sequence_no)
                  .map((step) => (
                    <details key={step.step_id} data-testid="trace-stage" className="rounded-lg border border-slate-200 bg-white p-3">
                      <summary className="cursor-pointer text-sm font-semibold text-slate-800">
                        {step.sequence_no}. {step.stage} · {step.status}
                      </summary>
                      <div className="mt-3 space-y-3">
                        <JsonDetails label="输入" value={step.input_payload} />
                        <JsonDetails label="输出" value={step.output_payload} />
                        {step.issues.map((issue) => (
                          <div key={issue.issue_id} className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
                            <code className="font-semibold text-red-700">{issue.code}</code>
                            <p className="mt-1">{issue.message}</p>
                            <p className="mt-1 text-amber-700">{issue.recommended_action}</p>
                          </div>
                        ))}
                        {step.error && <JsonBlock value={step.error} />}
                      </div>
                    </details>
                  ))}
              </section>

              <button type="button" onClick={() => setFullPayload(trace)} className="rounded-md border border-slate-300 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50">
                查看完整 JSON
              </button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={fullPayload !== null} onOpenChange={(next) => { if (!next) setFullPayload(null) }}>
        <DialogContent className="h-[92vh] max-w-6xl overflow-auto">
          <DialogHeader>
            <DialogTitle>完整编译轨迹 JSON</DialogTitle>
            <DialogDescription>完整只读响应，便于审计和故障定位。</DialogDescription>
          </DialogHeader>
          {fullPayload && <JsonBlock value={fullPayload} />}
          <button type="button" aria-label="关闭完整 JSON" onClick={() => setFullPayload(null)} className="w-fit rounded-md border border-slate-300 px-3 py-2 text-xs font-medium">
            关闭
          </button>
        </DialogContent>
      </Dialog>
    </>
  )
}

function Badge({ children }: { children: ReactNode }) {
  return <span className="rounded-full bg-slate-100 px-2.5 py-1 font-medium text-slate-700">{children}</span>
}

function JsonDetails({ label, value }: { label: string; value: unknown }) {
  return (
    <details className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <summary className="cursor-pointer text-sm font-medium text-slate-800">{label}</summary>
      <div className="mt-2"><JsonBlock value={value} /></div>
    </details>
  )
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="max-h-96 overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">{JSON.stringify(value, null, 2)}</pre>
}
