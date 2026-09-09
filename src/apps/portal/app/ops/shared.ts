// /ops 页公共标签与格式化 — 列表页与详情抽屉共享（#45 建立，#50 扩充状态/证据标签）。
import type { OpsFindingStatus, OpsSeverity } from '@/lib/ops-api'

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
}
export const STATUS_LABELS: Record<OpsFindingStatus, string> = {
  open: '开放',
  ignored: '已忽略',
  resolved: '已解决',
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
