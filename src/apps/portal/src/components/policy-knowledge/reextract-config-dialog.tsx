'use client'

import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FlaskConical,
  Loader2,
  RefreshCw,
  X,
} from 'lucide-react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog'
import { useApiContext } from '@/lib/api-context'
import {
  getExtractionConfig,
  getPromptPreview,
  listExtractionModels,
  reextractChangeSet,
  testExtractChangeSetItem,
  PolicyKnowledgeApiError,
  type ExtractionConfig,
  type ExtractionOverride,
  type ModelOption,
  type PromptMode,
  type PromptPreview,
  type ReextractReport,
  type TestExtractResult,
} from '@/lib/policy-knowledge-api'

export type ReextractScope =
  | { kind: 'single'; itemId: string; extractedFields?: string[] }
  | { kind: 'batch'; itemIds: string[] }

function scopeCount(scope: ReextractScope): number {
  return scope.kind === 'single' ? 1 : scope.itemIds.length
}

function scopeItemIds(scope: ReextractScope): string[] {
  return scope.kind === 'single' ? [scope.itemId] : scope.itemIds
}

/** 修改1 诊断：四类审核不通过原因 + 对应补救路径。 */
const DIAGNOSTIC_PATHS = [
  {
    key: 'missing_metric',
    title: '缺少指标',
    description: '语义层没有对应指标，去语义层新增并发布指标',
    target: '语义层指标管理',
  },
  {
    key: 'prompt',
    title: '有指标未提取出来',
    description: '契约有指标但候选没提取，修改提示词增强提取约束',
    target: '自定义提示词',
  },
  {
    key: 'model',
    title: '怎么修改提示词都不行',
    description: '提示词已尽力，切换更大/更合适的大模型重试',
    target: '切换大模型',
  },
  {
    key: 'extraction_method',
    title: '大模型质量差',
    description: '当前模型对实体/关系提取能力不足，需更换实体提取方法',
    target: '更换提取方法（需后端支持）',
  },
] as const

type DiagnosticKey = (typeof DIAGNOSTIC_PATHS)[number]['key']

/** 修改1 诊断：当前候选缺失字段 vs 契约指标。 */
function diagnoseMissingFields(
  extractedFields: string[] | undefined,
  metrics: ExtractionConfig['metrics'],
): { missing: ExtractionConfig['metrics'] } {
  if (!extractedFields || extractedFields.length === 0) {
    return { missing: [] }
  }
  const extracted = new Set(extractedFields)
  const missing = metrics.filter((metric) => !extracted.has(metric.code))
  return { missing }
}

/**
 * 重新提取配置向导（迭代 19：修改1 诊断 + 修改2 测试 + 修改3 UI 对齐新建构建任务）。
 *
 * 3 步抽屉：①问题诊断（自动缺失字段 + 四类补救路径）②配置与测试（提示词/模型/动态指标
 * + 不落库测试预览）③提交确认。schema 模式实时读语义层 published 指标。
 */
export function ReextractConfigDialog({
  changeSetId,
  scope,
  onClose,
  onComplete,
}: {
  changeSetId: string
  scope: ReextractScope
  onClose: () => void
  onComplete: (report: ReextractReport) => void
}) {
  const { userId } = useApiContext()
  const [step, setStep] = useState<1 | 2 | 3>(1)

  const [config, setConfig] = useState<ExtractionConfig | null>(null)
  const [models, setModels] = useState<ModelOption[]>([])
  const [promptMode, setPromptMode] = useState<PromptMode>('schema')
  const [customPrompt, setCustomPrompt] = useState('')
  const [modelName, setModelName] = useState<string>('')
  const [maxTokens, setMaxTokens] = useState<number>(8192)
  const [useCustomMaxTokens, setUseCustomMaxTokens] = useState(false)
  const [preview, setPreview] = useState<PromptPreview | null>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [diagnosticKey, setDiagnosticKey] = useState<DiagnosticKey | null>(null)
  const [testResult, setTestResult] = useState<TestExtractResult | null>(null)
  const [testing, setTesting] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<ReextractReport | null>(null)
  const [error, setError] = useState('')

  // 打开（挂载）时加载提取配置 + 可选模型（每次打开重新挂载，状态即初始值）
  useEffect(() => {
    let active = true
    void Promise.all([getExtractionConfig(), listExtractionModels()])
      .then(([nextConfig, nextModels]) => {
        if (!active) return
        setError('')
        setResult(null)
        setConfig(nextConfig)
        setModels(nextModels)
        setPromptMode(nextConfig.default_prompt_mode)
        setMaxTokens(nextConfig.default_max_tokens)
      })
      .catch((reasonValue) => {
        if (!active) return
        setError(reasonValue instanceof Error ? reasonValue.message : '提取配置加载失败')
      })
    return () => {
      active = false
    }
  }, [])

  // 提示词预览（schema / custom）；首次预览时 preview 为空 → 展示「加载中…」
  useEffect(() => {
    if (!previewOpen) return
    let active = true
    const params: { prompt_mode: PromptMode; custom_prompt?: string } = { prompt_mode: promptMode }
    if (promptMode === 'custom' && customPrompt.trim()) params.custom_prompt = customPrompt
    void getPromptPreview(params)
      .then((nextPreview) => {
        if (active) setPreview(nextPreview)
      })
      .catch((reasonValue) => {
        if (active) setPreview(null)
        if (reasonValue instanceof PolicyKnowledgeApiError && reasonValue.status === 400) {
          setError('custom 模式需填写提示词后才能预览')
        }
      })
    return () => {
      active = false
    }
  }, [previewOpen, promptMode, customPrompt])

  const extractedFields = scope.kind === 'single' ? scope.extractedFields : undefined
  const missingMetrics = useMemo(
    () => diagnoseMissingFields(extractedFields, config?.metrics ?? []).missing,
    [extractedFields, config],
  )

  function buildOverride(): ExtractionOverride {
    const override: ExtractionOverride = {
      prompt_mode: promptMode,
      operator: userId,
    }
    if (promptMode === 'custom') override.custom_prompt = customPrompt
    if (modelName) override.model_name = modelName
    if (useCustomMaxTokens) override.max_tokens = maxTokens
    return override
  }

  // 修改2：不落库测试提取（单条场景）
  async function handleTest() {
    if (scope.kind !== 'single' || testing) return
    if (promptMode === 'custom' && !customPrompt.trim()) {
      setError('自定义提示词不能为空')
      return
    }
    setTesting(true)
    setError('')
    setTestResult(null)
    try {
      const nextResult = await testExtractChangeSetItem(changeSetId, {
        item_id: scope.itemId,
        override: buildOverride(),
      })
      setTestResult(nextResult)
    } catch (reasonValue) {
      setError(reasonValue instanceof Error ? reasonValue.message : '测试提取失败')
    } finally {
      setTesting(false)
    }
  }

  async function handleSubmit(targetItemIds?: string[]) {
    if (submitting) return
    if (promptMode === 'custom' && !customPrompt.trim()) {
      setError('自定义提示词不能为空')
      return
    }
    setSubmitting(true)
    setError('')
    setResult(null)
    try {
      const itemIds = targetItemIds ?? scopeItemIds(scope)
      const report = await reextractChangeSet(changeSetId, {
        item_ids: itemIds,
        override: buildOverride(),
      })
      setResult(report)
      if (report.failed === 0) {
        onComplete(report)
      }
    } catch (reasonValue) {
      setError(reasonValue instanceof Error ? reasonValue.message : '重新提取失败')
    } finally {
      setSubmitting(false)
    }
  }

  const count = scopeCount(scope)
  const allSuccess = result !== null && result.failed === 0
  const failedItemIds = result
    ? result.items.filter((item) => !item.success).flatMap((item) => item.item_ids)
    : []
  const stepLabels = ['问题诊断', '配置与测试', '提交确认'] as const

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !submitting) onClose()
      }}
    >
      <DialogContent
        aria-label="重新提取配置"
        showCloseButton={false}
        className="w-full flex-col gap-0 overflow-hidden bg-white p-0 shadow-2xl ring-0"
        style={{
          top: 0,
          right: 0,
          bottom: 0,
          left: 'auto',
          display: 'flex',
          height: '100dvh',
          maxWidth: '42rem',
          transform: 'none',
          translate: 'none',
          borderRadius: 0,
        }}
      >
        <header className="border-b border-slate-200 px-5 py-4">
          <div className="flex items-start gap-3">
            <div>
              <p className="text-xs font-semibold text-emerald-700">重新提取 · 第 {step}/3 步</p>
              <DialogTitle className="mt-1 text-lg font-semibold tracking-tight text-slate-900">
                重新提取{count > 1 ? ` ${count} 条` : '该条'}候选知识
              </DialogTitle>
              <DialogDescription className="sr-only">
                诊断候选问题，配置提示词/大模型并测试后重新提取
              </DialogDescription>
            </div>
            <button
              type="button"
              aria-label="关闭重提取抽屉"
              disabled={submitting}
              onClick={onClose}
              className="ml-auto rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <X className="size-4" />
            </button>
          </div>
          <ol aria-label="重新提取步骤" className="mt-4 grid grid-cols-3 gap-1.5 text-xs">
            {stepLabels.map((label, index) => (
              <li
                key={label}
                aria-current={step === index + 1 ? 'step' : undefined}
                className={`rounded-md px-2 py-1.5 text-center ring-1 ring-inset ${
                  step === index + 1
                    ? 'bg-emerald-50 font-semibold text-emerald-800 ring-emerald-600/20'
                    : index + 1 < step
                      ? 'bg-emerald-50/60 text-emerald-700 ring-emerald-600/10'
                      : 'bg-slate-50 text-slate-400 ring-slate-200/60'
                }`}
              >
                {index + 1}. {label}
              </li>
            ))}
          </ol>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {error && (
            <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {error}
            </div>
          )}

          {/* ── 第 1 步：问题诊断（修改1）────────────────────────── */}
          {step === 1 && (
            <div className="space-y-4">
              <div>
                <h3 className="font-semibold text-slate-900">问题诊断</h3>
                <p className="mt-1 text-xs text-slate-500">
                  从结构化结果出发，判断候选缺失的原因，选择对应补救路径。
                </p>
              </div>

              {/* 自动缺失字段清单 */}
              {scope.kind === 'single' && (
                <div className="rounded-lg border border-amber-100 bg-amber-50/40 px-3 py-2">
                  <p className="flex items-center gap-1.5 text-xs font-medium text-amber-800">
                    <AlertTriangle className="size-3.5" />
                    当前候选已提取 {extractedFields?.length ?? 0} 个字段
                    {missingMetrics.length > 0 && `，以下契约指标未提取到（共 ${missingMetrics.length} 个）：`}
                  </p>
                  {missingMetrics.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {missingMetrics.slice(0, 12).map((metric) => (
                        <span
                          key={`${metric.kind}:${metric.code}`}
                          className="rounded bg-white px-1.5 py-0.5 font-mono text-[10px] text-amber-700"
                          title={metric.extraction_hint ?? metric.name}
                        >
                          {metric.code}
                        </span>
                      ))}
                      {missingMetrics.length > 12 && (
                        <span className="px-1.5 py-0.5 text-[10px] text-amber-600">
                          …等 {missingMetrics.length - 12} 个
                        </span>
                      )}
                    </div>
                  )}
                  {missingMetrics.length === 0 && extractedFields && extractedFields.length > 0 && (
                    <p className="mt-1 text-[11px] text-amber-700">
                      已覆盖当前契约全部指标；若仍缺字段，可能是指标未覆盖该维度（见下方补救路径）。
                    </p>
                  )}
                </div>
              )}

              {/* 四类补救路径 */}
              <fieldset className="space-y-2">
                <legend className="text-xs font-semibold text-slate-700">审核结果归类（选择补救路径）</legend>
                {DIAGNOSTIC_PATHS.map((path) => (
                  <label
                    key={path.key}
                    className="flex cursor-pointer items-start gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs hover:border-emerald-300"
                  >
                    <input
                      type="radio"
                      name="diagnostic-path"
                      value={path.key}
                      checked={diagnosticKey === path.key}
                      onChange={() => setDiagnosticKey(path.key)}
                      className="mt-0.5 size-3.5 accent-emerald-600"
                    />
                    <span>
                      <span className="font-medium text-slate-800">{path.title}</span>
                      <span className="mt-0.5 block text-[11px] text-slate-500">{path.description}</span>
                    </span>
                  </label>
                ))}
              </fieldset>

              {diagnosticKey === 'missing_metric' && (
                <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] text-slate-600">
                  去{DIAGNOSTIC_PATHS[0].target}新增指标并发布；schema 模式下一次重提取将自动注入新指标。
                </p>
              )}
            </div>
          )}

          {/* ── 第 2 步：配置与测试（修改2）──────────────────────── */}
          {step === 2 && (
            <div className="space-y-4">
              <div>
                <h3 className="font-semibold text-slate-900">配置与测试</h3>
                <p className="mt-1 text-xs text-slate-500">
                  选择提示词与大模型；可先用「测试提取」预览结果，满意后再提交。
                </p>
              </div>

              {/* 提示词模式 */}
              <fieldset className="space-y-2">
                <legend className="text-xs font-semibold text-slate-700">提示词</legend>
                <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs">
                  <input
                    type="radio"
                    name="prompt-mode"
                    value="schema"
                    checked={promptMode === 'schema'}
                    onChange={() => setPromptMode('schema')}
                    disabled={submitting || testing}
                    className="mt-0.5 size-3.5 accent-emerald-600"
                  />
                  <span>
                    <span className="font-medium text-slate-800">schema（默认）</span>
                    <span className="mt-0.5 block text-[11px] text-slate-500">
                      实时读取语义层已发布指标，自动注入提示词。
                      {config && (
                        <>当前契约版本 v{config.schema_version} · 共 {config.metrics.length} 个指标（动态加载，发布后立即生效）</>
                      )}
                    </span>
                  </span>
                </label>
                <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs">
                  <input
                    type="radio"
                    name="prompt-mode"
                    value="custom"
                    checked={promptMode === 'custom'}
                    onChange={() => setPromptMode('custom')}
                    disabled={submitting || testing}
                    className="mt-0.5 size-3.5 accent-emerald-600"
                  />
                  <span className="flex-1">
                    <span className="font-medium text-slate-800">自定义</span>
                    <span className="block text-[11px] text-slate-500">
                      手动编写提示词（指标不会自动注入，需自行包含）。可用占位符：{'{title}'} {'{text}'}
                    </span>
                    {promptMode === 'custom' && (
                      <textarea
                        aria-label="自定义提示词"
                        value={customPrompt}
                        onChange={(event) => setCustomPrompt(event.target.value)}
                        disabled={submitting || testing}
                        rows={4}
                        placeholder="例如：请从以下医保政策中提取起付线与支付比例规则，注意相对比例（如为职工支付比例的60%）。&#10;标题：{title}&#10;原文：{text}"
                        className="mt-2 w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-[11px] outline-none transition-colors focus:border-emerald-500 disabled:opacity-60"
                      />
                    )}
                  </span>
                </label>
              </fieldset>

              {/* 提示词预览 */}
              <div className="rounded-lg border border-slate-100 bg-slate-50/60">
                <button
                  type="button"
                  onClick={() => setPreviewOpen((current) => !current)}
                  className="flex w-full items-center gap-1 px-3 py-2 text-[11px] font-medium text-slate-600 hover:text-slate-800"
                >
                  {previewOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                  查看完整提示词预览
                </button>
                {previewOpen && (
                  <pre className="max-h-56 overflow-auto whitespace-pre-wrap border-t border-slate-100 px-3 py-2 font-mono text-[10px] leading-4 text-slate-600">
                    {preview ? preview.prompt : '加载中…'}
                  </pre>
                )}
              </div>

              {/* 大模型 */}
              <div className="grid grid-cols-2 gap-3">
                <label className="space-y-1 text-xs font-medium text-slate-700">
                  <span>大模型</span>
                  <select
                    aria-label="选择大模型"
                    value={modelName}
                    onChange={(event) => setModelName(event.target.value)}
                    disabled={submitting || testing}
                    className="h-8 w-full rounded-lg border border-slate-200 bg-white px-2.5 text-xs outline-none transition-colors focus:border-emerald-500 disabled:opacity-60"
                  >
                    <option value="">{config ? `${config.default_model}（默认路由）` : '默认路由'}</option>
                    {models.map((model) => (
                      <option key={model.model_name} value={model.model_name}>
                        {model.display_name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="space-y-1 text-xs font-medium text-slate-700">
                  <span className="flex items-center gap-1.5">
                    最大输出 tokens
                    <input
                      type="checkbox"
                      checked={useCustomMaxTokens}
                      onChange={(event) => setUseCustomMaxTokens(event.target.checked)}
                      disabled={submitting || testing}
                      className="size-3 accent-emerald-600"
                      aria-label="自定义最大输出 tokens"
                    />
                  </span>
                  <input
                    type="number"
                    aria-label="最大输出 tokens"
                    value={maxTokens}
                    min={256}
                    onChange={(event) => setMaxTokens(Number(event.target.value) || 0)}
                    disabled={submitting || testing || !useCustomMaxTokens}
                    className="h-8 w-full rounded-lg border border-slate-200 bg-white px-2.5 text-xs outline-none transition-colors focus:border-emerald-500 disabled:bg-slate-50 disabled:opacity-60"
                  />
                </label>
              </div>

              {/* 生效指标（schema 模式） */}
              {promptMode === 'schema' && config && config.metrics.length > 0 && (
                <div className="rounded-lg border border-emerald-100 bg-emerald-50/40 px-3 py-2">
                  <p className="text-[11px] font-medium text-emerald-800">
                    本次重提取将注入 {config.metrics.length} 个已发布指标（{config.note}）
                  </p>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {config.metrics.slice(0, 12).map((metric) => (
                      <span
                        key={`${metric.kind}:${metric.code}`}
                        className="rounded bg-white px-1.5 py-0.5 font-mono text-[10px] text-emerald-700"
                        title={metric.extraction_hint ?? metric.name}
                      >
                        {metric.code}
                      </span>
                    ))}
                    {config.metrics.length > 12 && (
                      <span className="px-1.5 py-0.5 text-[10px] text-emerald-600">
                        …等 {config.metrics.length - 12} 个
                      </span>
                    )}
                  </div>
                </div>
              )}

              {/* 修改2：测试提取（单条） */}
              {scope.kind === 'single' && (
                <div className="rounded-lg border border-slate-200 px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-[11px] font-medium text-slate-700">
                      测试提取：用当前单元 + 动态指标 + 所选提示词/模型预览结果（不落库）
                    </p>
                    <button
                      type="button"
                      onClick={() => void handleTest()}
                      disabled={testing || submitting || (promptMode === 'custom' && !customPrompt.trim())}
                      className="inline-flex items-center gap-1 rounded-lg border border-emerald-600 px-2.5 py-1.5 text-[11px] font-semibold text-emerald-700 hover:bg-emerald-50 disabled:opacity-40"
                    >
                      {testing ? <Loader2 className="size-3 animate-spin" /> : <FlaskConical className="size-3" />}
                      {testing ? '测试中…' : '测试提取'}
                    </button>
                  </div>
                  {testResult && (
                    <div className="mt-2 space-y-1.5">
                      <p className="flex items-center gap-1 text-[11px] font-medium text-emerald-800">
                        <CheckCircle2 className="size-3.5" />
                        提取 {testResult.fact_count} 条事实 · {testResult.rule_count} 条规则 · 覆盖 {testResult.fields_extracted.length} 个字段
                      </p>
                      {testResult.fields_extracted.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {testResult.fields_extracted.slice(0, 12).map((code) => (
                            <span key={code} className="rounded bg-emerald-50 px-1.5 py-0.5 font-mono text-[10px] text-emerald-700">
                              {code}
                            </span>
                          ))}
                        </div>
                      )}
                      <details className="rounded-lg border border-slate-100 bg-slate-50/60 px-2 py-1.5">
                        <summary className="cursor-pointer text-[11px] font-medium text-slate-600">
                          查看测试提取结果 JSON
                        </summary>
                        <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap font-mono text-[10px] leading-4 text-slate-600">
                          {JSON.stringify(testResult.facts, null, 2)}
                        </pre>
                      </details>
                    </div>
                  )}
                </div>
              )}
              {scope.kind === 'batch' && (
                <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] text-slate-600">
                  批量重提取暂不支持单条测试；可先对单条测试满意后，再回到批量选择提交。
                </p>
              )}
            </div>
          )}

          {/* ── 第 3 步：提交确认 ─────────────────────────────── */}
          {step === 3 && (
            <div className="space-y-4">
              <div>
                <h3 className="font-semibold text-slate-900">提交确认</h3>
                <p className="mt-1 text-xs text-slate-500">核对配置后提交重提取；重提后原地刷新候选，状态回到「等待审核」。</p>
              </div>
              <dl className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-slate-200 p-3">
                  <dt className="text-[11px] font-medium text-slate-500">提示词模式</dt>
                  <dd className="mt-1 text-sm font-medium text-slate-900">
                    {promptMode === 'schema' ? `schema（契约 v${config?.schema_version ?? '?'}，${config?.metrics.length ?? 0} 指标）` : promptMode === 'custom' ? '自定义' : 'legacy'}
                  </dd>
                </div>
                <div className="rounded-lg border border-slate-200 p-3">
                  <dt className="text-[11px] font-medium text-slate-500">大模型</dt>
                  <dd className="mt-1 text-sm font-medium text-slate-900">
                    {modelName || (config ? `${config.default_model}（默认路由）` : '默认路由')}
                  </dd>
                </div>
                <div className="rounded-lg border border-slate-200 p-3">
                  <dt className="text-[11px] font-medium text-slate-500">重提取范围</dt>
                  <dd className="mt-1 text-sm font-medium text-slate-900">{count} 条候选</dd>
                </div>
                <div className="rounded-lg border border-slate-200 p-3">
                  <dt className="text-[11px] font-medium text-slate-500">诊断归类</dt>
                  <dd className="mt-1 text-sm font-medium text-slate-900">
                    {DIAGNOSTIC_PATHS.find((path) => path.key === diagnosticKey)?.title ?? '未选择'}
                  </dd>
                </div>
              </dl>

              {/* 逐条结果（部分失败时展示） */}
              {result && result.failed > 0 && (
                <div className="rounded-lg border border-amber-200 bg-amber-50/50 px-3 py-2">
                  <p className="text-[11px] font-medium text-amber-800">
                    成功 {result.succeeded} / {result.total} 条；以下失败项可单独重试：
                  </p>
                  <ul className="mt-1.5 space-y-1">
                    {result.items.filter((item) => !item.success).map((item) => (
                      <li key={item.extraction_id} className="text-[11px] text-amber-700">
                        <span className="font-mono">{item.extraction_id}</span>
                        ：{item.error ?? '未知错误'}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>

        <footer className="flex items-center justify-end gap-2 border-t border-slate-200 px-5 py-3">
          {allSuccess ? (
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-700"
            >
              完成
            </button>
          ) : (
            <>
              {step > 1 && (
                <button
                  type="button"
                  onClick={() => { setError(''); setStep((current) => (current - 1) as 1 | 2 | 3) }}
                  disabled={submitting}
                  className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-40"
                >
                  上一步
                </button>
              )}
              {step < 3 ? (
                <button
                  type="button"
                  onClick={() => { setError(''); setStep((current) => (current + 1) as 1 | 2 | 3) }}
                  className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-700"
                >
                  下一步：{step === 1 ? stepLabels[1] : stepLabels[2]}
                </button>
              ) : (
                <>
                  {failedItemIds.length > 0 ? (
                    <button
                      type="button"
                      onClick={() => void handleSubmit(failedItemIds)}
                      disabled={submitting}
                      className="inline-flex items-center gap-1 rounded-lg bg-amber-600 px-3 py-2 text-xs font-semibold text-white hover:bg-amber-700 disabled:opacity-40"
                    >
                      {submitting ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
                      {submitting ? '重试中…' : `仅重试失败 ${failedItemIds.length} 条`}
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => void handleSubmit()}
                    disabled={submitting || (promptMode === 'custom' && !customPrompt.trim())}
                    className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-40"
                  >
                    {submitting ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
                    {submitting ? '提取中…' : '开始重新提取'}
                  </button>
                </>
              )}
            </>
          )}
        </footer>
      </DialogContent>
    </Dialog>
  )
}
