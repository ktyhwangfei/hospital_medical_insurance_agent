'use client'

// 政策知识对齐工作台 · 三栏共享基础组件与工具函数
// 供 units-column / knowledge-column / standardization-column 复用，避免各栏重复实现。
// [来源: docs/steering/政策知识治理平台设计-V2.1.md §5.5]

import type {
  KnowledgeField,
  KnowledgeItem,
  MetricDraftSource,
  StandardizedField,
  WorkbenchDocument,
} from '@/lib/policy-knowledge-api'

// ── 结构化价值判断（意见3）─────────────────────────────────────────────
// 判断一条知识/一个单元是否具备「值得结构化」的价值：以金额/数值类字段为高价值信号，
// 人群/类别/实体描述类字段不构成结构化价值（如「人群=城乡居民」本身无量化意义）。

/** 事实型字段：涉及金额/比例/限额/数值区间，有明确量化意义（高结构化价值） */
const FACT_FIELDS = new Set([
  'payment_ratio',      // 支付比例
  'deductible_amount',  // 起付额
  'cap_amount',         // 封顶额
  'amount_band',        // 金额区间
  'admission_order',    // 住院序次（数值）
])

/** 维度型字段：过滤维度/索引标签（值域标准化，中等价值） */
const DIMENSION_FIELDS = new Set([
  'rule_type',    // 知识类型
  'insu_type',    // 险种
  'med_type',     // 医疗类别
  'hosp_lv',      // 医疗机构等级
  'psn_type',     // 人员类别
  'setl_type',    // 结算方式
  'time_period',  // 时间周期（含数值但偏索引）
])

/** 描述型字段：AI 辅助/非结构化（低结构化价值，折叠展示） */
const DESCRIPTIVE_FIELDS = new Set([
  'entities',   // 实体抽取
  'relations',  // 关系抽取
  'priority',   // 优先级
  'rule_value', // 规则值（自然语言；含金额模式时另有 high-value 判定）
])

/** 金额/比例模式：数字 + 元/万元/% 等 */
const MONEY_PATTERN = /\d+(?:\.\d+)?\s*(元|万元|万|块|%|％|分之)/

/** 通用数值模式：数字 + 常见单位（元/天/次/人/年/月/岁/% 等），用于识别量化规则 */
const NUMERIC_PATTERN = /\d+(?:\.\d+)?\s*(元|万元|万|块|%|％|分之|天|日|次|人|年|月|岁|周|小时)/

function hasMoneyPattern(value: unknown): boolean {
  return typeof value === 'string' && MONEY_PATTERN.test(value)
}

/** 文本是否含量化数值（金额/天数/次数/年龄等），可作为事实型信号 */
export function hasNumericPattern(value: unknown): boolean {
  return typeof value === 'string' && NUMERIC_PATTERN.test(value)
}

/** 字段是否有实质内容（非空、非占位） */
function hasSubstance(value: unknown): boolean {
  if (value === null || value === undefined) return false
  if (typeof value === 'string') return value.trim().length > 0 && value.trim() !== 'None'
  if (typeof value === 'number') return !Number.isNaN(value)
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'object') return Object.keys(value as object).length > 0
  return true
}

/** 字段分层：'fact' | 'dimension' | 'descriptive' */
export function fieldTier(field: KnowledgeField): 'fact' | 'dimension' | 'descriptive' {
  if (FACT_FIELDS.has(field.field_code)) {
    // 事实型字段必须含量化数值，"不限"/"低"/"高" 等非数字值不算
    if (hasNumericPattern(field.raw_value)) return 'fact'
    return 'dimension' // 退化为维度型展示
  }
  if (DIMENSION_FIELDS.has(field.field_code)) return 'dimension'
  if (DESCRIPTIVE_FIELDS.has(field.field_code)) return 'descriptive'
  // 未归类字段：含量化数值视为事实型，否则描述型
  return hasNumericPattern(field.raw_value) ? 'fact' : 'descriptive'
}

/** 单个结构化字段是否具有高结构化价值 */
export function fieldHasStructuredValue(field: KnowledgeField): boolean {
  if (!hasSubstance(field.raw_value)) return false
  if (FACT_FIELDS.has(field.field_code)) return true
  // 未归类文本字段内含金额/量化数值时视为有价值
  if (hasMoneyPattern(field.raw_value) || hasNumericPattern(field.raw_value)) return true
  return false
}

/** 一条知识是否具备结构化价值（任一字段高价值即算） */
export function knowledgeHasStructuredValue(knowledge: KnowledgeItem): boolean {
  return knowledge.fields.some(fieldHasStructuredValue)
}

/** 一个单元是否具备结构化价值（任一条知识有价值即算） */
export function unitHasStructuredValue(knowledgeList: KnowledgeItem[]): boolean {
  return knowledgeList.some(knowledgeHasStructuredValue)
}

/** 列容器：统一样式（圆角卡片 + 标题 + 滚动区），min-w-0 防止 grid 子项被长内容撑破 */
export function Column({ id, className = '', title, subtitle, children }: {
  id?: string
  className?: string
  title: string
  subtitle: string
  children: React.ReactNode
}) {
  return (
    <section id={id} className={`flex min-h-0 min-w-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-slate-50/70 p-3 ${className}`}>
      <div className="mb-3 shrink-0">
        <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
        <p className="mt-0.5 text-[11px] text-slate-400">{subtitle}</p>
      </div>
      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto pr-1">{children}</div>
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

/**
 * 结构化字段值渲染：标量直接显示；对象/数组展开为可读子项，
 * 避免整段 JSON 字符串堆叠（中栏结构化知识用）。
 */
export function FieldValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-slate-400">—</span>
  if (typeof value !== 'object') return <span className="text-slate-700">{String(value)}</span>

  // 对象/数组：递归展开为「键: 值」行，单键对象可直接拼值
  const entries = Array.isArray(value)
    ? value.map((item, index) => [String(index + 1), item] as const)
    : Object.entries(value as Record<string, unknown>)

  if (entries.length === 0) return <span className="text-slate-400">∅</span>

  return (
    <ul className="space-y-0.5">
      {entries.map(([key, item]) => (
        <li key={key} className="flex items-start gap-1.5">
          <span className="shrink-0 font-mono text-[10px] text-slate-400">{key}</span>
          <span className="min-w-0 break-all text-slate-700">
            {typeof item === 'object' && item !== null
              ? <FieldValue value={item} />
              : String(item ?? '—')}
          </span>
        </li>
      ))}
    </ul>
  )
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
