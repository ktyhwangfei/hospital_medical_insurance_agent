'use client'

import { useMemo, useState } from 'react'
import {
  Plus,
  Trash2,
  Copy,
  Search,
  AlertCircle,
  Eye,
  EyeOff,
} from 'lucide-react'
import type {
  SkillExecutionContract,
  ExecutionProfileSpec,
  ContextInputSpec,
  MetricInputSpec,
  RuntimeContextCode,
  SkillInputSelectorResponse,
} from '@/lib/types'

// 执行契约编辑器（设计 §44/§46-§49）：
// 左栏 执行场景导航 / 中栏 当前场景契约 / 右栏 语义指标选择器。
// 用户不是在「填 JSON」，而是在定义 Skill 为完成某场景需要哪些数据（§77）。

const CONTEXT_OPTIONS: { value: RuntimeContextCode; label: string }[] = [
  { value: 'question', label: '用户问题' },
  { value: 'settlement_id', label: '结算标识' },
  { value: 'person_id', label: '人员标识' },
  { value: 'visit_id', label: '就诊标识' },
  { value: 'hospital_id', label: '医院标识' },
]

const UNAVAILABLE_REASON_LABELS: Record<string, string> = {
  NOT_PUBLISHED: '指标未发布',
  OBJECT_NOT_PUBLISHED: '所属对象未发布',
  NO_RUNTIME_RESOLVER: '未配置运行时解析器',
  INVALID_MAPPING: '字段映射无效',
  RESOLVER_DISABLED: '解析器已禁用',
  VERSION_UNAVAILABLE: '版本不可用',
}

// 「公共输入」虚拟场景标识（不写入 profiles，仅用于左侧导航选中）
const COMMON_KEY = '__common__'

function emptyProfile(): ExecutionProfileSpec {
  return {
    profile_id: '',
    name: '',
    purpose: '',
    routing_hints: [],
    context_inputs: [],
    metric_inputs: [],
  }
}

function ensureContract(contract?: SkillExecutionContract | null): SkillExecutionContract {
  if (contract) return contract
  return { version: 2, common: { context_inputs: [], metric_inputs: [] }, profiles: [] }
}

interface ExecutionContractEditorProps {
  contract: SkillExecutionContract | undefined
  selector: SkillInputSelectorResponse | null
  onChange: (contract: SkillExecutionContract) => void
}

export default function ExecutionContractEditor({
  contract: contractProp,
  selector,
  onChange,
}: ExecutionContractEditorProps) {
  const contract = ensureContract(contractProp)
  const [activeKey, setActiveKey] = useState<string>(COMMON_KEY)
  const [showUnavailable, setShowUnavailable] = useState(false)
  const [search, setSearch] = useState('')

  // ── 扁平化所有可选指标，供右栏渲染 ─────────────────────────────
  const flatMetrics = useMemo(() => {
    if (!selector?.tree) return []
    const rows: {
      metric_code: string
      name: string
      definition: string
      object_name: string
      domain_name: string
      runtime_resolvable: boolean
      resolution_type: string | null
      unavailable_reason: string | null
    }[] = []
    for (const domain of selector.tree) {
      for (const obj of domain.objects) {
        for (const m of obj.metrics) {
          rows.push({
            metric_code: m.metric_code,
            name: m.name,
            definition: m.definition ?? '',
            object_name: obj.name,
            domain_name: domain.name,
            runtime_resolvable: m.runtime_resolvable ?? false,
            resolution_type: m.resolution_type ?? null,
            unavailable_reason: m.unavailable_reason ?? null,
          })
        }
      }
    }
    return rows
  }, [selector])

  const filteredMetrics = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return flatMetrics
    return flatMetrics.filter(
      (m) =>
        m.metric_code.toLowerCase().includes(q) ||
        m.name.toLowerCase().includes(q),
    )
  }, [flatMetrics, search])

  // ── 当前选中场景的输入集合 ─────────────────────────────────────
  const isCommon = activeKey === COMMON_KEY
  const activeProfile = contract.profiles.find((p) => p.profile_id === activeKey)
  const activeMetricInputs: MetricInputSpec[] = isCommon
    ? contract.common.metric_inputs
    : activeProfile?.metric_inputs ?? []
  const activeContextInputs: ContextInputSpec[] = isCommon
    ? contract.common.context_inputs
    : activeProfile?.context_inputs ?? []

  // 已在「当前选中场景」声明的 metric_code 集合（避免重复添加）
  const declaredMetricCodes = new Set(activeMetricInputs.map((m) => m.metric_code))
  // common 中已声明的 metric_code（profile 视图里禁用，避免重复声明，§54.5）
  const commonMetricCodes = new Set(contract.common.metric_inputs.map((m) => m.metric_code))

  function emit(next: SkillExecutionContract) {
    onChange(next)
  }

  // ── 场景导航操作 ───────────────────────────────────────────────
  function addProfile() {
    const next = emptyProfile()
    const idx = contract.profiles.length + 1
    next.profile_id = `scene-${idx}`
    next.name = `执行场景 ${idx}`
    const profiles = [...contract.profiles, next]
    emit({ ...contract, profiles })
    setActiveKey(next.profile_id)
  }

  function duplicateProfile(profile: ExecutionProfileSpec) {
    const copy: ExecutionProfileSpec = {
      ...profile,
      profile_id: `${profile.profile_id}-copy`,
      name: `${profile.name}（副本）`,
      context_inputs: [...(profile.context_inputs ?? [])],
      metric_inputs: [...(profile.metric_inputs ?? [])],
      routing_hints: [...(profile.routing_hints ?? [])],
    }
    const profiles = [...contract.profiles, copy]
    emit({ ...contract, profiles })
    setActiveKey(copy.profile_id)
  }

  function removeProfile(profileId: string) {
    emit({
      ...contract,
      profiles: contract.profiles.filter((p) => p.profile_id !== profileId),
    })
    setActiveKey(COMMON_KEY)
  }

  // ── 场景字段编辑 ───────────────────────────────────────────────
  function patchActiveProfile(patch: Partial<ExecutionProfileSpec>) {
    if (isCommon || !activeProfile) return
    const profiles = contract.profiles.map((p) =>
      p.profile_id === activeProfile.profile_id ? { ...p, ...patch } : p,
    )
    emit({ ...contract, profiles })
  }

  // ── metric input 操作 ──────────────────────────────────────────
  function addMetric(metricCode: string) {
    const spec: MetricInputSpec = { metric_code: metricCode, required: true }
    if (isCommon) {
      emit({
        ...contract,
        common: { ...contract.common, metric_inputs: [...contract.common.metric_inputs, spec] },
      })
    } else {
      patchActiveProfile({
        metric_inputs: [...activeMetricInputs, spec],
      })
    }
  }

  function patchMetric(idx: number, patch: Partial<MetricInputSpec>) {
    const updated = activeMetricInputs.map((m, i) => (i === idx ? { ...m, ...patch } : m))
    if (isCommon) {
      emit({ ...contract, common: { ...contract.common, metric_inputs: updated } })
    } else {
      patchActiveProfile({ metric_inputs: updated })
    }
  }

  function removeMetric(idx: number) {
    const updated = activeMetricInputs.filter((_, i) => i !== idx)
    if (isCommon) {
      emit({ ...contract, common: { ...contract.common, metric_inputs: updated } })
    } else {
      patchActiveProfile({ metric_inputs: updated })
    }
  }

  // ── context input 操作 ─────────────────────────────────────────
  function toggleContext(code: RuntimeContextCode) {
    const exists = activeContextInputs.some((c) => c.code === code)
    if (exists) {
      const updated = activeContextInputs.filter((c) => c.code !== code)
      commitContexts(updated)
    } else {
      const spec: ContextInputSpec = { code, required: true }
      commitContexts([...activeContextInputs, spec])
    }
  }

  function commitContexts(updated: ContextInputSpec[]) {
    if (isCommon) {
      emit({ ...contract, common: { ...contract.common, context_inputs: updated } })
    } else {
      patchActiveProfile({ context_inputs: updated })
    }
  }

  function patchContext(code: RuntimeContextCode, patch: Partial<ContextInputSpec>) {
    const updated = activeContextInputs.map((c) =>
      c.code === code ? { ...c, ...patch } : c,
    )
    commitContexts(updated)
  }

  const selectedContextCodes = new Set(activeContextInputs.map((c) => c.code))

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-4 py-3">
        <h3 className="text-sm font-semibold text-slate-800">输入输出契约</h3>
        <p className="mt-0.5 text-xs text-slate-500">
          定义这个 Skill 有哪些执行场景、每个场景需要哪些上下文与语义指标。
        </p>
      </div>

      <div className="grid grid-cols-1 gap-0 md:grid-cols-12">
        {/* 左栏：执行场景导航（§46） */}
        <div className="border-b border-slate-200 p-3 md:col-span-3 md:border-b-0 md:border-r">
          <div className="space-y-1">
            <button
              type="button"
              onClick={() => setActiveKey(COMMON_KEY)}
              className={
                'flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm ' +
                (isCommon ? 'bg-blue-50 text-blue-700' : 'text-slate-600 hover:bg-slate-50')
              }
            >
              <span className="font-medium">公共输入</span>
              <span className="text-xs text-slate-400">
                {contract.common.metric_inputs.length}
              </span>
            </button>
            <div className="my-1 border-t border-slate-100" />
            {contract.profiles.map((p) => (
              <button
                key={p.profile_id}
                type="button"
                onClick={() => setActiveKey(p.profile_id)}
                className={
                  'flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm ' +
                  (activeKey === p.profile_id
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-slate-600 hover:bg-slate-50')
                }
              >
                <span className="truncate">{p.name || p.profile_id}</span>
                <span className="text-xs text-slate-400">
                  {(p.metric_inputs ?? []).length}
                </span>
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={addProfile}
            className="mt-2 flex w-full items-center justify-center gap-1 rounded-md border border-dashed border-slate-300 px-2 py-1.5 text-xs font-medium text-slate-500 hover:bg-slate-50"
          >
            <Plus className="h-3.5 w-3.5" />
            新建执行场景
          </button>
        </div>

        {/* 中栏：当前场景契约（§47-§48） */}
        <div className="space-y-4 border-b border-slate-200 p-4 md:col-span-5 md:border-b-0 md:border-r">
          {!isCommon && activeProfile && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-xs font-medium text-slate-600">场景标识 (kebab-case)</label>
                  <input
                    value={activeProfile.profile_id}
                    onChange={(e) => {
                      // 仅允许小写字母/数字/连字符
                      const v = e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '')
                      patchActiveProfile({ profile_id: v })
                      setActiveKey(v)
                    }}
                    className="mt-1 w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-600">显示名称</label>
                  <input
                    value={activeProfile.name}
                    onChange={(e) => patchActiveProfile({ name: e.target.value })}
                    className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-xs"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600">用途</label>
                <input
                  value={activeProfile.purpose ?? ''}
                  onChange={(e) => patchActiveProfile({ purpose: e.target.value })}
                  placeholder="该场景的业务目的"
                  className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-xs"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600">路由线索（逗号分隔）</label>
                <input
                  value={(activeProfile.routing_hints ?? []).join(', ')}
                  onChange={(e) =>
                    patchActiveProfile({
                      routing_hints: e.target.value
                        .split(/[,，\s]+/)
                        .filter(Boolean),
                    })
                  }
                  placeholder="如 起付线, 门槛费"
                  className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-xs"
                />
                <p className="mt-1 text-[11px] text-slate-400">路由辅助线索，非决定性规则（§23）</p>
              </div>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => duplicateProfile(activeProfile)}
                  className="inline-flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
                >
                  <Copy className="h-3 w-3" /> 复制
                </button>
                <button
                  type="button"
                  onClick={() => removeProfile(activeProfile.profile_id)}
                  className="inline-flex items-center gap-1 rounded border border-red-200 px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                >
                  <Trash2 className="h-3 w-3" /> 删除场景
                </button>
              </div>
            </div>
          )}

          {isCommon && (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
              <p className="text-xs text-amber-800">
                公共输入 = 几乎每个执行场景都需要的数据。必须克制使用——
                只有「绝大多数场景都需要 AND 获取成本合理」才放这里（§25/§26）。
              </p>
            </div>
          )}

          {/* Context Inputs（§49） */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-slate-700">运行时上下文</h4>
            <div className="flex flex-wrap gap-2">
              {CONTEXT_OPTIONS.map((opt) => {
                const checked = selectedContextCodes.has(opt.value)
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => toggleContext(opt.value)}
                    className={
                      'rounded-full border px-2.5 py-1 text-xs ' +
                      (checked
                        ? 'border-blue-400 bg-blue-50 text-blue-700'
                        : 'border-slate-200 text-slate-500 hover:bg-slate-50')
                    }
                  >
                    {checked ? '✓ ' : ''}{opt.label}
                  </button>
                )
              })}
            </div>
            {activeContextInputs.length > 0 && (
              <div className="space-y-1.5">
                {activeContextInputs.map((c) => (
                  <div key={c.code} className="flex flex-wrap items-center gap-2 rounded border border-slate-100 p-1.5">
                    <code className="min-w-0 flex-1 font-mono text-[11px] text-slate-600">{c.code}</code>
                    <input
                      value={c.alias ?? ''}
                      onChange={(e) => patchContext(c.code, { alias: e.target.value })}
                      placeholder="别名"
                      className="w-20 shrink-0 rounded border border-slate-200 px-1.5 py-0.5 text-[11px]"
                    />
                    <label className="flex shrink-0 items-center gap-1 text-[11px] text-slate-500">
                      <input
                        type="checkbox"
                        checked={c.required}
                        onChange={(e) => patchContext(c.code, { required: e.target.checked })}
                      />
                      必填
                    </label>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Metric Inputs（§48） */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-slate-700">指标依赖</h4>
            {activeMetricInputs.length === 0 ? (
              <p className="rounded border border-dashed border-slate-200 px-3 py-2 text-xs text-slate-400">
                暂无指标。从右侧选择器添加 runtime_resolvable 的指标（§9）。
              </p>
            ) : (
              <div className="space-y-1.5">
                {activeMetricInputs.map((m, idx) => (
                  <div key={`${m.metric_code}-${idx}`} className="min-w-0 rounded border border-slate-100 p-2">
                    <div className="flex items-center gap-2">
                      <code className="min-w-0 flex-1 truncate font-mono text-[11px] text-blue-700">{m.metric_code}</code>
                      <button
                        type="button"
                        onClick={() => removeMetric(idx)}
                        className="shrink-0 text-red-400 hover:text-red-600"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      <input
                        value={m.alias ?? ''}
                        onChange={(e) => patchMetric(idx, { alias: e.target.value })}
                        placeholder="别名"
                        className="w-20 shrink-0 rounded border border-slate-200 px-1.5 py-0.5 text-[11px]"
                      />
                      <input
                        value={m.purpose ?? ''}
                        onChange={(e) => patchMetric(idx, { purpose: e.target.value })}
                        placeholder="用途说明"
                        className="min-w-0 flex-1 rounded border border-slate-200 px-1.5 py-0.5 text-[11px]"
                      />
                      <label className="flex shrink-0 items-center gap-1 text-[11px] text-slate-500">
                        <input
                          type="checkbox"
                          checked={m.required}
                          onChange={(e) => patchMetric(idx, { required: e.target.checked })}
                        />
                        必填
                      </label>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* 右栏：语义指标选择器（§33-§36） */}
        <div className="space-y-2 p-4 md:col-span-4">
          <div className="relative">
            <Search className="absolute left-2 top-2 h-3.5 w-3.5 text-slate-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索指标"
              className="w-full rounded-md border border-slate-300 py-1.5 pl-7 pr-2 text-xs"
            />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-slate-400">
              仅 runtime_resolvable 可选（§35）
            </span>
            <label className="flex cursor-pointer items-center gap-1 text-[11px] text-slate-500">
              <button
                type="button"
                onClick={() => setShowUnavailable((v) => !v)}
                className="inline-flex items-center gap-1 hover:text-slate-700"
              >
                {showUnavailable ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                {showUnavailable ? '隐藏不可用' : '显示不可用'}
              </button>
            </label>
          </div>

          <div className="max-h-[28rem] space-y-1 overflow-y-auto">
            {filteredMetrics.length === 0 ? (
              <p className="px-2 py-4 text-center text-xs text-slate-400">
                {flatMetrics.length === 0 ? '语义层暂无指标' : '无匹配指标'}
              </p>
            ) : (
              filteredMetrics.map((m) => {
                const resolvable = m.runtime_resolvable
                const declared = declaredMetricCodes.has(m.metric_code)
                const inCommon = commonMetricCodes.has(m.metric_code)
                // 公共输入已在 common 声明的指标，在场景视图直接隐藏（不重复选择，§54.5）
                if (inCommon && !isCommon) return null
                const disabled = !resolvable || declared
                const reason = m.unavailable_reason
                  ? UNAVAILABLE_REASON_LABELS[m.unavailable_reason] ?? m.unavailable_reason
                  : '不可用'
                return (
                  <button
                    key={m.metric_code}
                    type="button"
                    disabled={disabled}
                    onClick={() => addMetric(m.metric_code)}
                    className={
                      'block w-full rounded-md border px-2 py-1.5 text-left text-xs ' +
                      (resolvable
                        ? declared
                          ? 'border-slate-100 bg-slate-50 text-slate-400'
                          : 'border-slate-200 hover:border-blue-300 hover:bg-blue-50'
                        : showUnavailable
                          ? 'border-slate-100 bg-slate-50 text-slate-400'
                          : 'hidden')
                    }
                    title={
                      !resolvable
                        ? `${reason}：暂不可作为 Skill 指标输入`
                        : declared
                          ? '已在当前场景声明'
                          : undefined
                    }
                  >
                    <div className="flex items-center justify-between">
                      <span className="truncate font-medium">{m.name}</span>
                      {!resolvable && (
                        <span className="inline-flex items-center gap-0.5 text-[10px] text-amber-600">
                          <AlertCircle className="h-3 w-3" />
                          {reason}
                        </span>
                      )}
                      {resolvable && declared && <span className="text-[10px] text-emerald-600">已选</span>}
                    </div>
                    <div className="truncate font-mono text-[10px] text-slate-400">{m.metric_code}</div>
                    <div className="text-[10px] text-slate-400">来源：{m.object_name}</div>
                  </button>
                )
              })
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
