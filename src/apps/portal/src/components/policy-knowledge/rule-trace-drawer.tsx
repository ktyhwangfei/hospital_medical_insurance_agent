'use client'

import { useEffect, useMemo, useState, type KeyboardEvent, type ReactNode } from 'react'
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
  type CompileStage,
  type CompileStep,
  type RuleCompilationTrace,
  type ValidationIssue,
} from '@/lib/policy-knowledge-api'

interface RuleTraceDrawerProps {
  open: boolean
  ruleId: string | null
  runId?: string | null
  fieldLabels?: Record<string, string>
  onOpenChange: (open: boolean) => void
}

type StageMode = 'baseline' | 'diff' | 'transform' | 'derive' | 'validate' | 'publish' | 'legacy' | 'generic'
type ChangeKind = 'added' | 'changed' | 'removed' | 'derived' | 'blocked' | 'unchanged'
type DecisionState = 'complete' | 'review' | 'blocked' | 'pending' | 'published'

interface FlatField {
  path: string
  value: unknown
}

interface FieldChange extends FlatField {
  kind: ChangeKind
  before?: unknown
  label?: string
}

interface StageView {
  key: CompileStage
  label: string
  mode: StageMode
  step: CompileStep | null
  input: FlatField[]
  changes: FieldChange[]
  issues: ValidationIssue[]
  state: DecisionState
  summary: string
  description: string
}

const DEFAULT_FIELD_LABELS: Record<string, string> = {
  insu_type: '险种类别',
  med_type: '医疗类别',
  hosp_lv: '医疗机构等级',
  psn_type: '人群标签',
  setl_type: '结算方式',
  payment_ratio: '支付比例',
  personal_payment_ratio: '个人支付比例',
  deductible_amount: '起付金额',
  cap_amount: '封顶金额',
  amount_band: '金额分段',
  time_period: '时间周期',
  admission_order: '住院次数',
  priority: '规则优先级',
  rule_type: '规则类型',
  rule_value: '规则值',
  business_sentence: '业务描述',
  referenced_clause: '引用条款',
  personal_payment_coefficient: '个人支付比例系数',
  subject: '规则主题',
  confidence: '综合置信度',
  population: '适用人群',
  amount: '规则金额',
  ratio: '规则比例',
  operator: '计算方式',
  factor: '计算系数',
  total: '计算总额',
  dependencies: '规则依赖',
  source_type: '规则来源',
  formula: '计算公式',
  publish_eligibility: '发布资格',
  expression: '计算表达式',
  status: '状态',
}

export default function RuleTraceDrawer({ open, ruleId, runId, fieldLabels = {}, onOpenChange }: RuleTraceDrawerProps) {
  const targetRunId = runId ?? null
  const [loadedTrace, setLoadedTrace] = useState<{
    ruleId: string
    runId: string | null
    trace: RuleCompilationTrace
  } | null>(null)
  const trace = loadedTrace?.ruleId === ruleId && loadedTrace.runId === targetRunId
    ? loadedTrace.trace
    : null
  const [loadError, setLoadError] = useState<{
    ruleId: string
    runId: string | null
    message: string
  } | null>(null)
  const [retry, setRetry] = useState(0)
  const [stageSelection, setStageSelection] = useState<{ traceKey: string; stage: CompileStage } | null>(null)
  const [viewOptions, setViewOptions] = useState<{ traceKey: string; showAll: boolean; jsonView: boolean } | null>(null)
  const stages = useMemo(() => trace ? buildStages(trace) : [], [trace])
  const traceKey = trace ? `${trace.rule_id}:${trace.run.run_id}` : ''
  const error = loadError?.ruleId === ruleId && loadError.runId === targetRunId ? loadError.message : ''
  const loading = open && Boolean(ruleId) && !trace && !error
  const activeStage = stages.find((stage) => stageSelection?.traceKey === traceKey && stage.key === stageSelection.stage)
    ?? (stages.length > 0 ? defaultStage(stages) : undefined)
  const showAll = viewOptions?.traceKey === traceKey ? viewOptions.showAll : false
  const jsonView = viewOptions?.traceKey === traceKey ? viewOptions.jsonView : false
  const visibleIssues = activeStage && trace
    ? uniqueIssues([
      ...activeStage.issues,
      ...trace.issues.filter((issue) => issue.stage === activeStage.key),
    ])
    : []
  const hasStepError = trace?.steps.some((step) => step.error) ?? false
  const visibleError = activeStage?.step?.error ?? (!hasStepError && trace?.run.status === 'FAIL' ? trace.run.error : null)
  const releaseDecision = stages.find((stage) => stage.key === 'VALIDATE')

  useEffect(() => {
    if (!open || !ruleId) return
    let active = true
    void getRuleCompilationTrace(ruleId, targetRunId)
      .then((result) => {
        if (!active) return
        setLoadError(null)
        setLoadedTrace({ ruleId, runId: targetRunId, trace: result })
      })
      .catch((reason) => {
        if (active) setLoadError({
          ruleId,
          runId: targetRunId,
          message: reason instanceof Error ? reason.message : '轨迹加载失败',
        })
      })
    return () => {
      active = false
    }
  }, [open, ruleId, targetRunId, retry])

  const close = () => {
    setLoadedTrace(null)
    setLoadError(null)
    onOpenChange(false)
  }

  const moveStage = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    const offset = event.key === 'ArrowRight' ? 1 : -1
    const next = (index + offset + stages.length) % stages.length
    setStageSelection({ traceKey, stage: stages[next].key })
    document.getElementById(`trace-stage-${stages[next].key}`)?.focus()
  }

  const updateView = (next: Partial<{ showAll: boolean; jsonView: boolean }>) => {
    setViewOptions((current) => ({
      traceKey,
      showAll: current?.traceKey === traceKey ? current.showAll : false,
      jsonView: current?.traceKey === traceKey ? current.jsonView : false,
      ...next,
    }))
  }

  return (
    <>
      <Dialog open={open} onOpenChange={(next) => next ? onOpenChange(true) : close()}>
        <DialogContent
          showCloseButton={false}
          className="inset-y-0 left-auto right-0 top-0 flex h-dvh w-[96vw] max-w-none translate-x-0 translate-y-0 flex-col gap-0 overflow-hidden rounded-none p-0 sm:max-w-[96vw]"
        >
          <DialogHeader className="border-b border-slate-200 px-6 py-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <DialogTitle>规则审核决策</DialogTitle>
                <DialogDescription>确认模型识别结果、规范化与冲突，以及当前能否发布。</DialogDescription>
              </div>
              <button type="button" aria-label="关闭溯源" onClick={close} className="rounded-md p-1 text-slate-500 hover:bg-slate-100">
                <X className="size-4" />
              </button>
            </div>
            {trace && (
              <div className="flex flex-wrap gap-2 pt-2 text-xs">
                <Badge>规则 {trace.rule_id}</Badge>
                {trace.rule ? <Badge>{trace.rule.source_type}</Badge> : <Badge>未生成规范规则</Badge>}
                <Badge>{trace.run.status}</Badge>
                {trace.rule && <Badge>规则版本 {trace.rule.rule_version}</Badge>}
                <Badge>编译器 {trace.rule?.compiler_version ?? trace.run.compiler_version}</Badge>
                {trace.publication && <Badge>发布 {trace.publication.release_id}{trace.publication.published_at ? ` · ${trace.publication.published_at}` : ''}</Badge>}
              </div>
            )}
          </DialogHeader>

          {loading && (
            <p className="flex items-center gap-2 px-6 py-8 text-sm text-slate-500">
              <Loader2 className="size-4 animate-spin" />正在加载编译轨迹…
            </p>
          )}
          {error && (
            <div role="alert" className="m-6 space-y-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              <p>{error}</p>
              <button type="button" onClick={() => { setLoadError(null); setRetry((value) => value + 1) }} className="inline-flex items-center gap-1 rounded border border-red-200 bg-white px-2 py-1 font-medium">
                <RefreshCw className="size-3" />重试
              </button>
            </div>
          )}
          {trace && releaseDecision && (
            <DecisionBanner stage={releaseDecision} />
          )}
          {trace && activeStage && (
            <div className="flex min-h-0 flex-1 flex-col">
              <div role="tablist" aria-label="审核决策流程" className="grid shrink-0 gap-2 border-b border-slate-200 bg-slate-50 px-5 py-3 md:grid-cols-3">
                {stages.map((stage, index) => {
                  const selected = stage.key === activeStage.key
                  return (
                    <button
                      key={stage.key}
                      id={`trace-stage-${stage.key}`}
                      type="button"
                      role="tab"
                      aria-selected={selected}
                      aria-controls="trace-stage-panel"
                      tabIndex={selected ? 0 : -1}
                      onClick={() => setStageSelection({ traceKey, stage: stage.key })}
                      onKeyDown={(event) => moveStage(event, index)}
                      className={`rounded-lg border px-4 py-3 text-left transition active:translate-y-px ${selected ? 'border-blue-500 bg-white shadow-sm ring-1 ring-blue-100' : 'border-slate-200 bg-slate-100 hover:bg-white'}`}
                    >
                      <span className="block text-xs font-semibold text-slate-900">
                        <span className="mr-1">{index + 1}.</span><span>{stage.label}</span>
                      </span>
                      <span className={`mt-1 block text-[11px] ${decisionStateClass(stage.state)}`}>
                        {stage.summary}
                      </span>
                    </button>
                  )
                })}
              </div>

              <div id="trace-stage-panel" role="tabpanel" aria-labelledby={`trace-stage-${activeStage.key}`} className="min-h-0 flex-1 overflow-y-auto bg-slate-100/70 p-5">
                <div className="mx-auto max-w-[1500px] space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-900">{activeStage.label}</h3>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {activeStage.description}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button type="button" aria-pressed={!jsonView} onClick={() => updateView({ jsonView: false })} className={viewButtonClass(!jsonView)}>语义视图</button>
                      <button type="button" aria-pressed={jsonView} onClick={() => updateView({ jsonView: true })} className={viewButtonClass(jsonView)}>JSON 对照</button>
                      {!jsonView && !['LLM_EXTRACTION', 'CANONICALIZE'].includes(activeStage.key) && (
                        <button type="button" onClick={() => updateView({ showAll: !showAll })} className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50">
                          {showAll ? '只看变化' : '查看全部字段'}
                        </button>
                      )}
                    </div>
                  </div>

                  {activeStage.mode === 'legacy' && (
                    <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                      中间编译历史缺失，当前仅展示可恢复的历史快照。
                    </p>
                  )}

                  {activeStage.mode === 'generic' && (
                    <p className="rounded-lg border border-slate-300 bg-white p-3 text-sm text-slate-700">
                      通用视图：未识别阶段，按接口返回的输入与输出计算字段变化。
                    </p>
                  )}

                  <PhaseNotice stage={activeStage} />

                  {jsonView ? (
                    <div className="grid gap-4 lg:grid-cols-2">
                      <JsonPanel label="阶段输入 JSON" value={activeStage.step?.input_payload ?? {}} />
                      <JsonPanel label="阶段输出 JSON" value={activeStage.step?.output_payload ?? {}} />
                    </div>
                  ) : (
                    <StageComparison stage={activeStage} showAll={showAll} fieldLabels={fieldLabels} />
                  )}

                  <IssueList issues={visibleIssues} error={visibleError} />

                  <FullPayloadDialog key={traceKey} payload={trace} />
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

    </>
  )
}

function FullPayloadDialog({ payload }: { payload: RuleCompilationTrace }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50">
        查看完整 JSON
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="h-[92vh] max-w-6xl overflow-auto">
          <DialogHeader>
            <DialogTitle>完整编译轨迹 JSON</DialogTitle>
            <DialogDescription>完整只读响应，便于审计和故障定位。</DialogDescription>
          </DialogHeader>
          <JsonBlock value={payload} />
          <button type="button" aria-label="关闭完整 JSON" onClick={() => setOpen(false)} className="w-fit rounded-md border border-slate-300 px-3 py-2 text-xs font-medium">
            关闭
          </button>
        </DialogContent>
      </Dialog>
    </>
  )
}

function DecisionBanner({ stage }: { stage: StageView }) {
  return (
    <section aria-label="当前发布结论" className={`mx-5 mt-4 rounded-lg border px-4 py-3 ${decisionBannerClass(stage.state)}`}>
      <p className="text-sm font-semibold">{stage.summary}</p>
      <p className="mt-1 text-xs leading-5">{stage.description}</p>
    </section>
  )
}

function PhaseNotice({ stage }: { stage: StageView }) {
  return (
    <section className={`rounded-lg border px-4 py-3 ${decisionBannerClass(stage.state)}`}>
      <p className="text-sm font-semibold">{stage.summary}</p>
      <p className="mt-1 text-xs leading-5">{stage.description}</p>
    </section>
  )
}

function StageComparison({ stage, showAll, fieldLabels }: { stage: StageView; showAll: boolean; fieldLabels: Record<string, string> }) {
  if (stage.key === 'LLM_EXTRACTION' && stage.step) return <RecognitionComparison stage={stage} fieldLabels={fieldLabels} />

  const alwaysShow = stage.key === 'CANONICALIZE'
  const input = inputFields(stage, showAll || alwaysShow).filter(isGovernanceField)
  const output = outputFields(stage, showAll || alwaysShow).filter(isGovernanceField)
  const unchanged = !alwaysShow && !showAll && stage.input.length > 0 && input.length === 0

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_12rem_minmax(0,1fr)]">
      <FieldPanel
        title={alwaysShow ? '规范化输入' : '阶段输入'}
        fields={input}
        empty={unchanged ? '该阶段已执行，但未产生字段变化；点击“查看全部字段”核对当前值。' : '无输入数据'}
        fieldLabels={fieldLabels}
      />
      <ChangeSummary stage={stage} />
      <FieldPanel title={alwaysShow ? '规范化输出' : '阶段输出'} fields={output} empty={stage.step ? '此阶段没有产生字段变化' : '阶段未执行'} fieldLabels={fieldLabels} />
    </div>
  )
}

function RecognitionComparison({ stage, fieldLabels }: { stage: StageView; fieldLabels: Record<string, string> }) {
  const sourceText = sourceTextOf(stage.step?.input_payload)
  const extracted = recognitionFields(stage, 'extracted')
  const inferred = recognitionFields(stage, 'inferred')
  const matches = sourceMatchTokens(sourceText, extracted)

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_12rem_minmax(0,1fr)]">
      <section className="min-w-0 rounded-xl border border-slate-200 bg-white">
        <h4 className="border-b border-slate-200 px-4 py-3 text-sm font-semibold text-slate-900">单元原文</h4>
        <p className="max-h-[55vh] overflow-auto whitespace-pre-wrap p-4 text-sm leading-7 text-slate-700">
          {sourceText ? highlightedText(sourceText, matches) : '未找到单元原文'}
        </p>
      </section>
      <ChangeSummary stage={stage} />
      <div className="min-w-0 space-y-4">
        <FieldPanel title="原文提取" fields={extracted} empty="未找到当前候选" sourceText={sourceText} fieldLabels={fieldLabels} />
        <FieldPanel title="辅助推断" fields={inferred} empty="没有辅助推断字段" fieldLabels={fieldLabels} />
      </div>
    </div>
  )
}

function ChangeSummary({ stage }: { stage: StageView }) {
  const changed = stage.changes.filter((field) => field.kind !== 'unchanged')
  const counts = changed.reduce<Record<ChangeKind, number>>((result, field) => {
    result[field.kind] += 1
    return result
  }, { added: 0, changed: 0, removed: 0, derived: 0, blocked: 0, unchanged: 0 })

  return (
    <div className="flex min-h-28 flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white p-4 text-center">
      <span className="text-2xl text-slate-300">→</span>
      <p className="mt-1 text-xs font-semibold text-slate-700">变化摘要</p>
      {changed.length === 0 ? (
        <p className="mt-2 text-xs text-slate-500">{stage.step ? '无字段变化' : '未执行'}</p>
      ) : (
        <div className="mt-2 flex flex-wrap justify-center gap-1.5 text-[11px]">
          {counts.added > 0 && <ChangePill kind="added">{counts.added}</ChangePill>}
          {counts.changed > 0 && <ChangePill kind="changed">{counts.changed}</ChangePill>}
          {counts.removed > 0 && <ChangePill kind="removed">{counts.removed}</ChangePill>}
          {counts.derived > 0 && <ChangePill kind="derived">{counts.derived}</ChangePill>}
          {counts.blocked > 0 && <ChangePill kind="blocked">{counts.blocked}</ChangePill>}
        </div>
      )}
    </div>
  )
}

function FieldPanel({ title, fields, empty, sourceText = '', fieldLabels }: { title: string; fields: FieldChange[]; empty: string; sourceText?: string; fieldLabels: Record<string, string> }) {
  return (
    <section className="min-w-0 rounded-xl border border-slate-200 bg-white">
      <h4 className="border-b border-slate-200 px-4 py-3 text-sm font-semibold text-slate-900">{title}</h4>
      <div className="max-h-[55vh] space-y-1 overflow-auto p-3">
        {fields.length === 0 ? (
          <p className="px-1 py-8 text-center text-xs text-slate-400">{empty}</p>
        ) : fields.map((field, index) => {
          const matched = fieldMatchesSource(field, sourceText)
          return (
          <div key={`${field.path}-${index}`} data-source-match={matched || undefined} className={`grid grid-cols-[minmax(8rem,0.9fr)_minmax(0,1.1fr)] gap-3 rounded-md border-l-2 px-2.5 py-2 text-xs ${matched ? 'border-l-emerald-500 bg-emerald-50 text-emerald-900 ring-1 ring-emerald-200' : changeRowClass(sourceText ? 'unchanged' : field.kind)}`}>
            <span className="font-medium text-slate-600">{fieldLabel(field.path, fieldLabels)}</span>
            <span className="min-w-0">
              {field.kind !== 'unchanged' && <span className="mr-2 font-sans font-semibold">{field.label ?? changeLabel(field.kind)}</span>}
              <span data-change={field.kind} className={`break-all font-mono ${field.kind === 'removed' ? 'line-through' : ''} ${matched ? 'rounded bg-emerald-200 px-1 font-semibold text-emerald-950' : ''}`}>{formatValue(field.value)}</span>
            </span>
          </div>
        )})}
      </div>
    </section>
  )
}

function IssueList({ issues, error }: { issues: ValidationIssue[]; error: Record<string, unknown> | null }) {
  if (issues.length === 0 && !error) return null
  return (
    <section aria-label="阶段问题" className="space-y-2">
      {issues.map((issue) => (
        <div key={issue.issue_id} className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          <p className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">{issue.severity}</span>
            <code className="font-semibold text-red-700">{issue.code}</code>
          </p>
          <p className="mt-1">{issue.message}</p>
          <p className="mt-1 text-amber-700">{issue.recommended_action}</p>
        </div>
      ))}
      {error && <JsonBlock value={error} />}
    </section>
  )
}

function JsonPanel({ label, value }: { label: string; value: unknown }) {
  return (
    <section className="min-w-0 rounded-xl border border-slate-200 bg-white p-3">
      <h4 className="mb-2 text-sm font-semibold text-slate-900">{label}</h4>
      <JsonBlock value={value} />
    </section>
  )
}

function buildStages(trace: RuleCompilationTrace): StageView[] {
  const sorted = [...trace.steps].sort((left, right) => left.sequence_no - right.sequence_no)
  const legacy = sorted.find((step) => step.stage === 'LEGACY_IMPORT')
  if (legacy) return [{
    ...buildStage('LEGACY_IMPORT', '历史导入', 'legacy', legacy),
    state: 'review',
    summary: '历史轨迹不完整',
    description: '该规则来自历史导入，只能展示已保存的快照，不能还原中间编译过程。',
  }]
  return [
    buildRecognitionStage(trace, sorted),
    buildGovernanceStage(trace, sorted),
    buildReleaseDecisionStage(trace, sorted),
  ]
}

function buildRecognitionStage(trace: RuleCompilationTrace, steps: CompileStep[]): StageView {
  const snapshot = findStep(steps, 'INPUT_SNAPSHOT')
  const extraction = findStep(steps, 'LLM_EXTRACTION')
  const canonicalize = findStep(steps, 'CANONICALIZE')
  const extracted = findCandidate(extraction?.output_payload, trace.rule_id)
  const compilerCandidate = findCandidate(canonicalize?.input_payload, trace.rule_id)
  const candidate = extracted ?? compilerCandidate
  const inferred = compilerCandidate
    ? Object.fromEntries(['subject', 'confidence'].flatMap((key) => compilerCandidate[key] == null ? [] : [[key, compilerCandidate[key]]]))
    : null
  const source = extraction ?? snapshot
  const sourceText = sourceTextOf(extraction?.input_payload)
    || sourceTextOf(snapshot?.input_payload)
    || sourceTextOf(trace.raw_input)
  const focused = source && candidate
    ? { ...source, input_payload: sourceText ? { source_text: sourceText } : source.input_payload, output_payload: { extracted: candidate, inferred } }
    : source
  const stage = buildStage('LLM_EXTRACTION', '模型识别', 'transform', focused ?? null)
  const issues = uniqueIssues([
    ...(snapshot?.issues ?? []),
    ...(extraction?.issues ?? []),
    ...focusIssues(
      trace.issues.filter((issue) => issue.stage === 'INPUT_SNAPSHOT' || issue.stage === 'LLM_EXTRACTION'),
      trace.rule_id,
    ),
  ])
  const failed = trace.run.status === 'FAIL' || [snapshot, extraction].some((step) => step?.status === 'FAIL')
  return {
    ...stage,
    issues,
    state: failed ? 'blocked' : source ? 'complete' : 'pending',
    summary: failed ? '模型识别失败' : candidate ? '已定位当前候选' : source ? '模型识别已完成' : '模型识别未执行',
    description: candidate
      ? '原文提取与编译器辅助推断分开显示；同色高亮表示可在原文中精确定位。'
      : '当前轨迹没有可定位的候选结构，技术原始数据仍可在完整 JSON 中查看。',
  }
}

function buildGovernanceStage(trace: RuleCompilationTrace, steps: CompileStep[]): StageView {
  const views = [
    buildStage('CANONICALIZE', '字段规范化', 'diff', scopeStep(findStep(steps, 'CANONICALIZE'), trace.rule_id)),
    buildStage('COMPOSE', '规则组合', 'transform', scopeStep(findStep(steps, 'COMPOSE'), trace.rule_id)),
    buildStage('RESOLVE', '关系解析', 'transform', scopeStep(findStep(steps, 'RESOLVE'), trace.rule_id)),
    buildStage('DERIVE', '规则推导', 'derive', scopeStep(findStep(steps, 'DERIVE'), trace.rule_id)),
  ]
  const issues = uniqueIssues([
    ...views.flatMap((view) => view.issues),
    ...focusIssues(
      trace.issues.filter((issue) => ['CANONICALIZE', 'COMPOSE', 'RESOLVE', 'DERIVE'].includes(issue.stage)),
      trace.rule_id,
    ),
  ])
  const blocking = views.find((view) => view.step?.status === 'FAIL')
  const review = views.find((view) => ['WARN', 'REVIEW'].includes(view.step?.status ?? ''))
  const executed = views.filter((view) => view.step)
  const state: DecisionState = blocking ? 'blocked' : review || issues.length > 0 ? 'review' : executed.length > 0 ? 'complete' : 'pending'
  return {
    key: 'CANONICALIZE',
    label: '规范化与冲突',
    mode: 'diff',
    step: blocking?.step ?? review?.step ?? executed.at(-1)?.step ?? null,
    input: views[0].input,
    changes: views.flatMap((view) => view.changes),
    issues,
    state,
    summary: state === 'blocked'
      ? '规范化或规则组合失败'
      : state === 'review'
        ? `${issues.length || 1} 项冲突需处理`
        : state === 'complete'
          ? '规范化与冲突检查已完成'
          : '规范化与冲突检查未执行',
    description: state === 'review'
      ? '系统已执行规范化和规则组合，但发现会阻止生成规范规则的冲突。关系解析和规则推导只有存在有效关系时才产生结果。'
      : '系统统一字段格式并检查规则能否组合；没有关系表达式时，关系解析和规则推导不作为必经步骤。',
  }
}

function buildReleaseDecisionStage(trace: RuleCompilationTrace, steps: CompileStep[]): StageView {
  const validate = buildStage('VALIDATE', '确定性校验', 'validate', scopeStep(findStep(steps, 'VALIDATE'), trace.rule_id))
  const publish = buildStage('PUBLISH', '发布入库', 'publish', scopeStep(findStep(steps, 'PUBLISH'), trace.rule_id))
  const published = Boolean(trace.publication)
  const hasRule = Boolean(trace.rule)
  const validationFailed = validate.step?.status === 'FAIL'
  const needsReview = validate.issues.length > 0 || ['WARN', 'REVIEW'].includes(validate.step?.status ?? '')
  const state: DecisionState = published
    ? 'published'
    : !hasRule || validationFailed
      ? 'blocked'
      : needsReview
        ? 'review'
        : validate.step
          ? 'complete'
          : 'pending'
  const issues = uniqueIssues(validate.issues)
  const changes = published
    ? publish.changes
    : state === 'blocked'
      ? [{ path: 'publish_eligibility', value: hasRule ? '确定性校验失败' : '未生成规范规则', kind: 'blocked' as const, label: '! 不可发布' }]
      : needsReview
        ? validate.changes
        : [{ path: 'publish_eligibility', value: '规则校验完成，等待整批发布流程', kind: 'added' as const, label: '+ 可进入发布流程' }]
  return {
    key: 'VALIDATE',
    label: '发布判定',
    mode: 'validate',
    step: publish.step ?? validate.step,
    input: validate.input,
    changes,
    issues,
    state,
    summary: state === 'published'
      ? `已发布${trace.publication?.release_id ? ` · ${trace.publication.release_id}` : ''}`
      : state === 'blocked'
        ? '当前不可发布'
        : state === 'review'
          ? '校验结果需要人工处理'
          : state === 'complete'
            ? '可进入发布流程'
            : '尚未形成发布结论',
    description: state === 'published'
      ? '该规则已进入正式发布版本，入库集合与血缘可在下方结果和完整 JSON 中查看。'
      : state === 'blocked'
        ? '尚未生成可校验的规范规则，不能把空集合校验视为通过。请先处理上一阶段的冲突。'
        : '此处不执行发布。完成整批审核后，请到发布管理依次完成候选构建、质量测试和生效。',
  }
}

function buildStage(key: CompileStage, label: string, mode: StageMode, step: CompileStep | null): StageView {
  if (!step) return {
    key,
    label,
    mode,
    step: null,
    input: [],
    changes: [],
    issues: [],
    state: 'pending',
    summary: '未执行',
    description: '当前运行未执行此阶段。',
  }
  const inputValue = mode === 'diff' && isRecord(step.input_payload) && 'facts' in step.input_payload
    ? step.input_payload.facts
    : step.input_payload
  const outputValue = unwrapResult(step.output_payload)
  const input = flatten(inputValue)
  let changes: FieldChange[]

  if (mode === 'diff') {
    changes = diff(input, flatten(outputValue))
  } else if (mode === 'generic') {
    changes = diff(input, flatten(outputValue))
  } else if (mode === 'derive') {
    changes = prioritizeDerived(flatten(outputValue).map((field) => {
      const calculated = field.path.includes('.result.') || field.path.includes('.formula.')
      return calculated
        ? { ...field, kind: 'derived' as const, label: 'ƒ 计算推导' }
        : { ...field, kind: 'added' as const, label: field.path.includes('.dependencies') ? '+ 新增依赖' : '+ 生成属性' }
    }))
  } else if (mode === 'validate') {
    changes = step.issues.map((issue) => ({ path: `issues.${issue.code}`, value: issue.message, kind: 'blocked' as const, label: '! 校验问题' }))
  } else if (mode === 'baseline' || mode === 'legacy') {
    changes = flatten(outputValue).map((field) => ({ ...field, kind: 'unchanged' as const }))
  } else {
    changes = flatten(outputValue).map((field) => ({ ...field, kind: 'added' as const, label: productLabel(key, mode) }))
  }

  return {
    key,
    label,
    mode,
    step,
    input,
    changes,
    issues: step.issues,
    state: decisionState(step.status),
    summary: step.status,
    description: `步骤 ${step.sequence_no} · ${step.duration_ms} ms`,
  }
}

function defaultStage(stages: StageView[]) {
  return stages.find((stage) => ['review', 'blocked'].includes(stage.state))
    ?? [...stages].reverse().find((stage) => stage.step && stage.changes.some((field) => field.kind !== 'unchanged'))
    ?? [...stages].reverse().find((stage) => stage.step)
    ?? stages[0]
}

function findStep(steps: CompileStep[], stage: CompileStage) {
  return steps.find((step) => step.stage === stage)
}

function scopeStep(step: CompileStep | undefined, targetId: string): CompileStep | null {
  if (!step) return null
  return {
    ...step,
    input_payload: scopeValue(step.input_payload, targetId) as Record<string, unknown>,
    output_payload: scopeValue(step.output_payload, targetId) as Record<string, unknown>,
    issues: focusIssues(step.issues, targetId),
  }
}

function focusIssues(issues: ValidationIssue[], targetId: string) {
  const matching = issues.filter((issue) => issue.fact_id === targetId || issue.rule_id === targetId)
  return matching.length > 0 ? matching : issues
}

function scopeValue(value: unknown, targetId: string): unknown {
  if (Array.isArray(value)) {
    const matches = value.filter((item) => matchesCandidate(item, targetId))
    return (matches.length > 0 ? matches : value).map((item) => scopeValue(item, targetId))
  }
  if (!isRecord(value)) return value
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, scopeValue(item, targetId)]))
}

function findCandidate(value: unknown, targetId: string): Record<string, unknown> | null {
  if (matchesCandidate(value, targetId)) return value
  if (Array.isArray(value)) {
    for (const item of value) {
      const match = findCandidate(item, targetId)
      if (match) return match
    }
  } else if (isRecord(value)) {
    for (const item of Object.values(value)) {
      const match = findCandidate(item, targetId)
      if (match) return match
    }
  }
  return null
}

function matchesCandidate(value: unknown, targetId: string): value is Record<string, unknown> {
  if (!isRecord(value)) return false
  return ['fact_id', 'rule_id', 'knowledge_id', 'id'].some((key) => value[key] === targetId)
}

function inputFields(stage: StageView, showAll: boolean): FieldChange[] {
  if (stage.mode !== 'diff' && stage.mode !== 'generic') return stage.input.map((field) => ({ ...field, kind: 'unchanged' }))
  const changes = showAll ? stage.changes : stage.changes.filter((field) => field.kind !== 'unchanged')
  return changes
    .filter((field) => field.kind === 'changed' || field.kind === 'removed' || field.kind === 'unchanged')
    .map((field) => ({ path: field.path, value: field.before, kind: field.kind }))
}

function outputFields(stage: StageView, showAll: boolean): FieldChange[] {
  if (stage.mode === 'baseline' || stage.mode === 'legacy') return stage.changes
  const fields = showAll ? stage.changes : stage.changes.filter((field) => field.kind !== 'unchanged')
  return fields.map((field) => field.kind === 'removed' ? { ...field, value: '已移除' } : field)
}

function recognitionFields(stage: StageView, group: 'extracted' | 'inferred') {
  const fields = outputFields(stage, true).filter((field) => field.path.startsWith(`${group}.`) && isSemanticField(field, group === 'inferred'))
  return fields.filter((field) => {
    if (field.path.endsWith('.conditions.rule_value')) {
      return !fields.some((candidate) => candidate.path.includes('.value.') && sameValue(candidate.value, field.value))
    }
    if (field.path.endsWith('.population')) {
      return !fields.some((candidate) => candidate.path.endsWith('.conditions.psn_type') && sameValue(candidate.value, field.value))
    }
    return true
  }).map((field) => group === 'inferred' ? { ...field, kind: 'derived' as const, label: 'ƒ 编译推断' } : field)
}

function isGovernanceField(field: FlatField) {
  return isSemanticField(field) && fieldCode(field.path) !== 'subject'
}

function isSemanticField(field: FlatField, allowInference = false) {
  if (field.value === null || field.value === '') return false
  return !field.path.split('.').some((part) => {
    const code = part.replace(/\[.*$/, '')
    return code === 'id' || code.endsWith('_id') || ['evidence', 'source_text', 'raw_text'].includes(code) || (!allowInference && code === 'confidence')
  })
}

function fieldCode(path: string) {
  return (path.split('.').at(-1) ?? path).replace(/\[.*$/, '')
}

function fieldLabel(path: string, labels: Record<string, string>) {
  const code = fieldCode(path)
  return labels[code] ?? DEFAULT_FIELD_LABELS[code] ?? '其他业务字段'
}

function sourceTextOf(value: unknown): string {
  if (Array.isArray(value)) {
    for (const item of value) {
      const text = sourceTextOf(item)
      if (text) return text
    }
    return ''
  }
  if (!isRecord(value)) return ''
  for (const key of ['source_text', 'raw_text', 'text', 'content']) {
    if (typeof value[key] === 'string' && value[key].trim()) return value[key]
  }
  for (const item of Object.values(value)) {
    if (typeof item !== 'object' || item === null) continue
    const text = sourceTextOf(item)
    if (text) return text
  }
  return ''
}

function sourceAliases(value: unknown): string[] {
  if (typeof value !== 'string' && typeof value !== 'number') return []
  const text = String(value)
  const aliases = [text]
  const numeric = typeof value === 'number' ? value : /^\d+(?:\.\d+)?$/.test(text) ? Number(text) : null
  if (numeric !== null && Number.isInteger(numeric) && numeric >= 10000 && numeric % 10000 === 0) {
    aliases.push(`${numeric / 10000}万元`)
  }
  if (numeric !== null && numeric > 0 && numeric <= 1 && Number.isInteger(numeric * 100)) {
    aliases.push(`${numeric * 100}%`)
  }
  return aliases
}

function sourceMatchTokens(sourceText: string, fields: FieldChange[]) {
  return [...new Set(fields.flatMap((field) => sourceAliases(field.value)))]
    .filter((token) => token.length >= 2 && sourceText.includes(token))
    .sort((left, right) => right.length - left.length)
}

function fieldMatchesSource(field: FieldChange, sourceText: string) {
  return sourceText.length > 0 && sourceAliases(field.value).some((alias) => alias.length >= 2 && sourceText.includes(alias))
}

function highlightedText(sourceText: string, tokens: string[]) {
  if (tokens.length === 0) return sourceText
  const pattern = new RegExp(`(${tokens.map(escapeRegex).join('|')})`, 'g')
  const matches = new Set(tokens)
  return sourceText.split(pattern).map((part, index) => matches.has(part)
    ? <mark key={`${part}-${index}`} className="rounded bg-emerald-200 px-0.5 text-emerald-950">{part}</mark>
    : part)
}

function escapeRegex(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function diff(before: FlatField[], after: FlatField[]): FieldChange[] {
  const beforeMap = new Map(before.map((field) => [field.path, field.value]))
  const changes = after.map<FieldChange>((field) => {
    if (!beforeMap.has(field.path)) return { ...field, kind: 'added' }
    const previous = beforeMap.get(field.path)
    beforeMap.delete(field.path)
    return sameValue(previous, field.value)
      ? { ...field, before: previous, kind: 'unchanged' }
      : { ...field, before: previous, kind: 'changed' }
  })
  beforeMap.forEach((value, path) => changes.push({ path, value, before: value, kind: 'removed' }))
  return changes
}

function flatten(value: unknown, path = ''): FlatField[] {
  if (Array.isArray(value)) {
    if (value.length === 0) return []
    return value.flatMap((item, index) => flatten(item, `${path}[${itemKey(item, index)}]`))
  }
  if (isRecord(value)) {
    const entries = Object.entries(value)
    if (entries.length === 0) return []
    return entries.flatMap(([key, item]) => flatten(item, path ? `${path}.${key}` : key))
  }
  return [{ path: path || 'value', value }]
}

function itemKey(value: unknown, index: number) {
  if (!isRecord(value)) return String(index)
  for (const key of ['fact_id', 'rule_id', 'issue_id']) {
    if (typeof value[key] === 'string') return `${key}=${value[key]}`
  }
  return String(index)
}

function unwrapResult(value: Record<string, unknown>) {
  return Object.keys(value).length === 1 && 'result' in value ? value.result : value
}

function prioritizeDerived(fields: FieldChange[]) {
  return fields.sort((left, right) => Number(left.kind !== 'derived') - Number(right.kind !== 'derived'))
}

function productLabel(stage: CompileStage, mode: StageMode) {
  if (stage === 'LLM_EXTRACTION') return '+ 提取产物'
  if (stage === 'COMPOSE') return '+ 生成规则/关系'
  if (stage === 'RESOLVE') return '+ 绑定结果'
  if (mode === 'publish') return '+ 发布产物'
  return '+ 通用产物'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function sameValue(left: unknown, right: unknown) {
  return JSON.stringify(left) === JSON.stringify(right)
}

function uniqueIssues(issues: ValidationIssue[]) {
  const seen = new Set<string>()
  return issues.filter((issue) => {
    if (seen.has(issue.issue_id)) return false
    seen.add(issue.issue_id)
    return true
  })
}

function decisionState(status: CompileStep['status']): DecisionState {
  if (status === 'FAIL') return 'blocked'
  if (status === 'REVIEW' || status === 'WARN') return 'review'
  if (status === 'PASS') return 'complete'
  return 'pending'
}

function decisionStateClass(state: DecisionState) {
  if (state === 'blocked') return 'text-red-700'
  if (state === 'review') return 'text-amber-700'
  if (state === 'pending') return 'text-slate-500'
  return 'text-emerald-700'
}

function decisionBannerClass(state: DecisionState) {
  if (state === 'blocked') return 'border-red-200 bg-red-50 text-red-900'
  if (state === 'review') return 'border-amber-200 bg-amber-50 text-amber-900'
  if (state === 'pending') return 'border-slate-200 bg-slate-50 text-slate-700'
  return 'border-emerald-200 bg-emerald-50 text-emerald-900'
}

function viewButtonClass(active: boolean) {
  return `rounded-md px-3 py-1.5 text-xs font-medium ${active ? 'bg-slate-900 text-white' : 'border border-slate-300 text-slate-700 hover:bg-slate-50'}`
}

function changeRowClass(kind: ChangeKind) {
  if (kind === 'added') return 'border-l-emerald-500 bg-emerald-50 text-emerald-800'
  if (kind === 'changed') return 'border-l-amber-500 bg-amber-50 text-amber-900'
  if (kind === 'removed') return 'border-l-red-500 bg-red-50 text-red-800'
  if (kind === 'blocked') return 'border-l-red-500 bg-red-50 text-red-800'
  if (kind === 'derived') return 'border-l-violet-500 bg-violet-50 text-violet-800'
  return 'border-l-slate-200 bg-slate-50 text-slate-700'
}

function ChangePill({ kind, children }: { kind: ChangeKind; children: ReactNode }) {
  return <span className={`rounded-full px-2 py-1 ${changeRowClass(kind)}`}>{changeLabel(kind)} {children}</span>
}

function changeLabel(kind: ChangeKind) {
  if (kind === 'added') return '+ 新增'
  if (kind === 'changed') return '~ 修改'
  if (kind === 'removed') return '− 删除'
  if (kind === 'derived') return 'ƒ 推导'
  if (kind === 'blocked') return '! 阻断'
  return '未变化'
}

function formatValue(value: unknown) {
  if (typeof value === 'string') return value
  if (value === undefined) return '—'
  return JSON.stringify(value)
}

function Badge({ children }: { children: ReactNode }) {
  return <span className="rounded-full bg-slate-100 px-2.5 py-1 font-medium text-slate-700">{children}</span>
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="max-h-[60vh] overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">{JSON.stringify(value, null, 2)}</pre>
}
