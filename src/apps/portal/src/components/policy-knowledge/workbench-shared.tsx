'use client'

// 政策知识对齐工作台 · 三栏共享基础组件与工具函数
// 供 units-column / knowledge-column / standardization-column 复用，避免各栏重复实现。
// [来源: docs/steering/政策知识治理平台设计-V2.1.md §5.5]

import type {
  KnowledgeItem,
  MetricDraftSource,
  StandardizedField,
  WorkbenchDocument,
} from '@/lib/policy-knowledge-api'

/** 列容器：统一样式（圆角卡片 + 标题 + 滚动区） */
export function Column({ id, className = '', title, subtitle, children }: {
  id?: string
  className?: string
  title: string
  subtitle: string
  children: React.ReactNode
}) {
  return (
    <section id={id} className={`flex min-h-0 flex-col rounded-2xl border border-slate-200 bg-slate-50/70 p-3 ${className}`}>
      <div className="mb-3 shrink-0">
        <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
        <p className="mt-0.5 text-[11px] text-slate-400">{subtitle}</p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto pr-1">{children}</div>
    </section>
  )
}

/** 空态占位 */
export function Empty({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-200 bg-white px-3 py-10 text-center text-xs text-slate-400">
      {text}
    </div>
  )
}

/** 置信度指标小卡（中栏知识卡片用） */
export function Score({ label, value, pending = false }: {
  label: string
  value: string
  pending?: boolean
}) {
  return (
    <div className={`rounded-md px-2 py-1.5 ${pending ? 'bg-amber-50' : 'bg-white'}`}>
      <p className="text-[9px] text-slate-400">{label}</p>
      <p className={`text-[11px] font-semibold ${pending ? 'text-amber-700' : 'text-slate-700'}`}>{value}</p>
    </div>
  )
}

/** 标化状态徽标（右栏用） */
export function Status({ status }: { status: StandardizedField['status'] }) {
  const styles = {
    mapped: 'bg-emerald-50 text-emerald-700',
    unmapped: 'bg-blue-50 text-blue-700',
    invalid: 'bg-amber-50 text-amber-700',
    not_applicable: 'bg-slate-100 text-slate-500',
  }
  const labels = {
    mapped: '已映射',
    unmapped: '未映射',
    invalid: '值域未映射',
    not_applicable: '不适用',
  }
  return (
    <span className={`ml-auto rounded px-1.5 py-0.5 text-[10px] font-semibold ${styles[status]}`}>
      {labels[status]}
    </span>
  )
}

/** 值展示（右栏来源/标准值），对象以稳定排序的 JSON 呈现 */
export function Value({ label, value, empty = false }: {
  label: string
  value: unknown
  empty?: boolean
}) {
  return (
    <div className="rounded-lg bg-slate-50 p-2">
      <p className="text-[9px] text-slate-400">{label}</p>
      <p className="mt-0.5 break-all font-mono text-[11px] text-slate-700">{empty ? '—' : readableValue(value)}</p>
    </div>
  )
}

/** 百分比格式化：null 显示「待验证」，否则取整百分比 */
export function pct(value: number | null): string {
  return value === null ? '待验证' : `${Math.round(value * 100)}%`
}

/** 任意值 → 可读字符串；对象键排序保证 JSON 输出稳定 */
export function readableValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value !== 'object') return String(value)
  const stable = (_key: string, item: unknown) => item && typeof item === 'object' && !Array.isArray(item)
    ? Object.fromEntries(Object.entries(item).sort(([left], [right]) => left.localeCompare(right)))
    : item
  return JSON.stringify(value, stable)
}

/** 构建指标草稿源（右栏 → MetricDraftDialog 的输入） */
export function toDraftSource(
  document: WorkbenchDocument,
  unitId: string,
  knowledge: KnowledgeItem,
  field: StandardizedField,
): MetricDraftSource {
  return {
    doc_id: document.doc_id,
    unit_id: unitId,
    knowledge_id: knowledge.knowledge_id,
    source_field: field.source_field,
    field_name: knowledge.fields.find((item) => item.field_code === field.source_field)?.field_name || field.source_field,
    source_value: field.source_value,
    source_text: knowledge.source_text,
    contract_version: document.contract_version || 'unknown',
  }
}
