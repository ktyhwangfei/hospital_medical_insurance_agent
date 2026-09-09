// 数据目录页共享标签/格式化 — issue #38。
import type { CatalogAssetType } from '@/lib/catalog-api'

export const ASSET_TYPE_LABELS: Record<CatalogAssetType, string> = {
  dataset: '数据集',
  field: '字段',
  object: '业务对象',
  metric: '指标',
  consumer: '消费方',
}

export const ASSET_TYPE_BADGES: Record<CatalogAssetType, string> = {
  dataset: 'bg-sky-50 text-sky-700 border-sky-200',
  field: 'bg-violet-50 text-violet-700 border-violet-200',
  object: 'bg-indigo-50 text-indigo-700 border-indigo-200',
  metric: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  consumer: 'bg-amber-50 text-amber-700 border-amber-200',
}

export const FIELD_ROLE_LABELS: Record<string, string> = {
  identifier: '标识',
  dimension: '维度',
  fact: '事实',
}

export function formatDateTime(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  )
}

export function formatSeconds(value: number | null): string {
  if (value === null || value === undefined) return '—'
  if (value < 60) return `${value.toFixed(1)} 秒`
  const minutes = Math.floor(value / 60)
  const seconds = Math.round(value % 60)
  return seconds ? `${minutes} 分 ${seconds} 秒` : `${minutes} 分`
}
