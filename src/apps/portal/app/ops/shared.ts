// /ops 页公共标签与格式化 — 列表页与详情抽屉共享（#45 建立，#50 扩充状态/证据标签，#53 扩充修复标签，#51 扩充诊断标签，#52 扩充巡检调度标签，#54 扩充人工交接标签）。
import type {
  DiagnosisActionLevel,
  OpsFindingStatus,
  OpsInspectionStatus,
  OpsInspectionTrigger,
  OpsManualTarget,
  OpsSeverity,
  RemediationRunStatus,
  VerificationResult,
} from '@/lib/ops-api'

export const SEVERITY_BADGES: Record<OpsSeverity, string> = {
  critical: 'bg-red-50 text-red-700 ring-red-200',
  warning: 'bg-amber-50 text-amber-700 ring-amber-200',
  info: 'bg-sky-50 text-sky-700 ring-sky-200',
}
export const SEVERITY_LABELS: Record<OpsSeverity, string> = {
  critical: '严重',
  warning: '警告',
  info: '提示',
}
export const ASSET_LABELS: Record<string, string> = {
  data: '数据',
  skill: '技能',
  knowledge: '知识',
  runtime: '运行时',
}
export const CHECK_LABELS: Record<string, string> = {
  data_sync_failed: '门诊同步异常',
  data_source_down: '数据源连接失败',
}
export const STATUS_BADGES: Record<OpsFindingStatus, string> = {
  open: 'bg-sky-50 text-sky-700 ring-sky-200',
  ignored: 'bg-slate-100 text-slate-600 ring-slate-200',
  resolved: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  waiting_human: 'bg-amber-50 text-amber-700 ring-amber-200',
}
export const STATUS_LABELS: Record<OpsFindingStatus, string> = {
  open: '开放',
  ignored: '已忽略',
  resolved: '已解决',
  waiting_human: '转人工处理中',
}

// ── #53 L1 自动修复标签 ──

/** 修复动作 → 中文短语 */
export const ACTION_LABELS: Record<string, string> = {
  retry_data_sync: '重试门诊同步',
}

export const RUN_STATUS_LABELS: Record<RemediationRunStatus, string> = {
  succeeded: '已执行',
  failed: '未发起',
}

export const VERIFICATION_LABELS: Record<VerificationResult, string> = {
  passed: '验证通过',
  failed: '验证未通过',
}

// ── #51 LLM 智能诊断标签 ──

/** 建议动作分级 → 标签与配色（L3 红色醒目：禁止自动执行） */
export const DIAGNOSIS_LEVEL_BADGES: Record<DiagnosisActionLevel, string> = {
  L1: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  L2: 'bg-amber-50 text-amber-700 ring-amber-200',
  L3: 'bg-red-50 text-red-700 ring-red-200',
}
export const DIAGNOSIS_LEVEL_LABELS: Record<DiagnosisActionLevel, string> = {
  L1: 'L1 可自动',
  L2: 'L2 需人工确认',
  L3: 'L3 禁止自动执行',
}

// ── #52 定时巡检调度标签 ──

export const INSPECTION_STATUS_BADGES: Record<OpsInspectionStatus, string> = {
  running: 'bg-amber-50 text-amber-700 ring-amber-200',
  succeeded: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  failed: 'bg-red-50 text-red-700 ring-red-200',
}
export const INSPECTION_STATUS_LABELS: Record<OpsInspectionStatus, string> = {
  running: '进行中',
  succeeded: '完成',
  failed: '失败',
}
export const INSPECTION_TRIGGER_LABELS: Record<OpsInspectionTrigger, string> = {
  manual: '手动',
  scheduled: '定时',
}

// ── #54 L2 人工确认修复流标签 ──

/** 人工处理跳转目标 → 治理页面入口文案 */
export const MANUAL_TARGET_LABELS: Record<OpsManualTarget, string> = {
  policy_knowledge: '政策知识治理',
  skill_draft: '技能草稿',
  external: '外部系统',
}

/** 跳转目标 → 门户治理页路由（external 无门户页面，返回 null 由组件降级为文案） */
export const MANUAL_TARGET_PATHS: Partial<Record<OpsManualTarget, string>> = {
  policy_knowledge: '/policy-knowledge',
  skill_draft: '/skills',
}

/** 巡检周期展示：1440=每天、整小时=每小时，其余按分钟 */
export function inspectionIntervalLabel(minutes: number): string {
  if (minutes % 1440 === 0) return minutes === 1440 ? '每天' : `每 ${minutes / 1440} 天`
  if (minutes % 60 === 0) return minutes === 60 ? '每小时' : `每 ${minutes / 60} 小时`
  return `每 ${minutes} 分钟`
}

/** 证据快照字段的展示名（未知键原样展示） */
export const PAYLOAD_KEY_LABELS: Record<string, string> = {
  problem: '问题码',
  last_error_code: '错误码',
  due_at: '应执行时间',
  next_run_at: '下次执行',
  grace_minutes: '超宽限（分钟）',
  safe_probe_message: '连接探测',
  last_probed_at: '最近探测',
}

/** 问题码 → 中文短语 */
export const PROBLEM_LABELS: Record<string, string> = {
  sync_job_failed: '同步任务失败',
  sync_job_degraded: '同步任务降级',
  sync_job_lagging: '同步任务滞后',
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return iso.replace('T', ' ').replace(/([+-]\d{2}:\d{2}|Z)$/, '')
}

/** 证据字段值展示：时间戳格式化、问题码翻译、其余字符串/数字直出 */
export function formatPayloadValue(key: string, value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') {
    if (key === 'problem' && PROBLEM_LABELS[value]) return `${PROBLEM_LABELS[value]}（${value}）`
    return value
  }
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}
