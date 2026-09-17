'use client'

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Boxes, ChevronDown, ChevronRight, Database, Network, Plus, RotateCcw, X } from 'lucide-react'

import {
  getKnowledgeMap,
  type KnowledgeMapData,
  type KnowledgeMapRule,
} from '@/lib/policy-knowledge-api'

type BlockState<T> =
  | { kind: 'loading' }
  | { kind: 'ready'; data: T }
  | { kind: 'failed' }

/* ---------------------------------- 维度路线 ---------------------------------- */

const DIMENSIONS = [
  { key: 'insu_type', label: '参保体系' },
  { key: 'med_type', label: '医疗类别' },
  { key: 'hosp_lv', label: '医院等级' },
  { key: 'psn_type', label: '人群' },
  { key: 'setl_type', label: '结算方式' },
  { key: 'rule_type', label: '规则类型' },
  { key: 'region', label: '适用地区' },
  { key: 'amount_band', label: '金额分段' },
  { key: 'admission_order', label: '住院次序' },
] as const

type DimKey = (typeof DIMENSIONS)[number]['key']

const DIM_LABEL: Record<DimKey, string> = Object.fromEntries(
  DIMENSIONS.map((d) => [d.key, d.label]),
) as Record<DimKey, string>

const DEFAULT_ROUTE: DimKey[] = ['insu_type', 'med_type', 'hosp_lv', 'psn_type', 'rule_type']
const ROUTE_STORAGE_KEY = 'policy-knowledge-map-route-v1'
const UNLABELED = '未标注'
const KEY_SEPARATOR = '\u001f'

/* ---------------------------------- 树构建 ---------------------------------- */

interface MapNode {
  key: string
  value: string
  count: number
  children: MapNode[]
  rules: KnowledgeMapRule[]
}

function buildTree(rules: KnowledgeMapRule[], route: DimKey[], depth = 0, parentKey = ''): MapNode[] {
  if (depth >= route.length) return []
  const dim = route[depth]
  const groups = new Map<string, KnowledgeMapRule[]>()
  for (const rule of rules) {
    const value = (rule[dim] ?? '').trim() || UNLABELED
    const bucket = groups.get(value)
    if (bucket) bucket.push(rule)
    else groups.set(value, [rule])
  }
  const nodes: MapNode[] = [...groups.entries()].map(([value, bucket]) => ({
    key: `${parentKey}${KEY_SEPARATOR}${value}`,
    value,
    count: bucket.length,
    children: buildTree(bucket, route, depth + 1, `${parentKey}${KEY_SEPARATOR}${value}`),
    rules: bucket,
  }))
  // 数量降序，「未标注」固定沉底
  nodes.sort((a, b) => {
    if (a.value === UNLABELED && b.value !== UNLABELED) return 1
    if (b.value === UNLABELED && a.value !== UNLABELED) return -1
    return b.count - a.count || a.value.localeCompare(b.value, 'zh')
  })
  return nodes
}

function collectNodeKeys(nodes: MapNode[]): string[] {
  return nodes.flatMap((node) => [node.key, ...collectNodeKeys(node.children)])
}

/* ---------------------------------- 格式化 ---------------------------------- */

function formatNumber(value: number): string {
  return value.toLocaleString('zh-CN')
}

function formatRatio(value: string | undefined | null): string | null {
  const text = (value ?? '').trim()
  if (!text) return null
  return /^[\d.]+$/.test(text) ? `${text}%` : text
}

function formatAmountRange(min: string | undefined, max: string | undefined): string | null {
  const lo = Number(min)
  const hi = Number(max)
  if (lo > 0 && hi > 0) return `${formatNumber(lo)}–${formatNumber(hi)}元`
  if (lo > 0 && hi === -1) return `${formatNumber(lo)}元以上`
  return null
}

function formatValidity(rule: KnowledgeMapRule): string | null {
  const eff = rule.effective_date && rule.effective_date !== '1900-01-01' ? rule.effective_date : ''
  const exp = rule.expiry_date && rule.expiry_date !== '9999-12-31' ? rule.expiry_date : ''
  if (eff && exp) return `${eff} 至 ${exp}`
  if (eff) return `生效 ${eff}`
  if (exp) return `至 ${exp}`
  return null
}

/* ---------------------------------- 页面 ---------------------------------- */

export default function KnowledgeMapPage() {
  const [state, setState] = useState<BlockState<KnowledgeMapData>>({ kind: 'loading' })
  const [route, setRoute] = useState<DimKey[]>(DEFAULT_ROUTE)
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())

  // 路线持久化：启动时恢复，非法值回退默认
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(ROUTE_STORAGE_KEY)
      if (!raw) return
      const parsed: unknown = JSON.parse(raw)
      const validKeys = new Set<string>(DIMENSIONS.map((d) => d.key))
      if (
        Array.isArray(parsed) && parsed.length > 0
        && parsed.every((k) => typeof k === 'string' && validKeys.has(k))
      ) {
        setRoute(parsed as DimKey[])
      }
    } catch {
      // 忽略损坏的本地存储
    }
  }, [])

  const load = useCallback(() => {
    setState({ kind: 'loading' })
    getKnowledgeMap()
      .then((data) => setState({ kind: 'ready', data }))
      .catch(() => setState({ kind: 'failed' }))
  }, [])

  useEffect(() => { load() }, [load])

  const updateRoute = (next: DimKey[]) => {
    setRoute(next)
    setExpanded(new Set())
    try {
      window.localStorage.setItem(ROUTE_STORAGE_KEY, JSON.stringify(next))
    } catch {
      // 本地存储不可用时仅丢失记忆，不影响功能
    }
  }

  const removeDimension = (dim: DimKey) => {
    if (route.length <= 1) return
    updateRoute(route.filter((d) => d !== dim))
  }
  const appendDimension = (dim: DimKey) => {
    if (!route.includes(dim)) updateRoute([...route, dim])
  }

  const toggleNode = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const rules = state.kind === 'ready' ? state.data.rules : []
  const tree = useMemo(() => buildTree(rules, route), [rules, route])

  const allNodeKeys = useMemo(() => collectNodeKeys(tree), [tree])
  const allExpanded = allNodeKeys.length > 0 && allNodeKeys.every((key) => expanded.has(key))

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end gap-4">
        <div>
          <h2 className="text-2xl font-semibold tracking-[-0.025em] text-slate-900">知识体系</h2>
          <p className="mt-1 text-sm text-slate-500">按维度路线展开当前读路径中的全部结构化知识与向量化集合</p>
        </div>
        {state.kind === 'ready' && (
          <div className="ml-auto flex flex-wrap items-center gap-2 text-xs">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1.5 font-medium text-emerald-700">
              <Network className="size-3.5" />
              读路径 <span className="font-mono">{state.data.rules_collection}</span>
            </span>
            {state.data.active_release_id && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-3 py-1.5 font-medium text-blue-700">
                生效版本 <span className="font-mono">{state.data.active_release_id}</span>
              </span>
            )}
          </div>
        )}
      </header>

      {state.kind === 'loading' && <MapSkeleton />}
      {state.kind === 'failed' && (
        <section className="rounded-2xl border border-slate-200 bg-white px-6 py-16 text-center">
          <p className="text-sm text-slate-500">知识体系暂不可用（Milvus 连接失败或服务未就绪）</p>
          <button
            type="button"
            onClick={load}
            className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white transition-colors hover:bg-blue-700"
          >
            <RotateCcw className="size-3.5" />重试
          </button>
        </section>
      )}
      {state.kind === 'ready' && (
        <>
          <SummaryStrip data={state.data} />
          <CollectionInventory data={state.data} />
          <KnowledgeTreeSection
            data={state.data}
            route={route}
            tree={tree}
            expanded={expanded}
            allNodeKeys={allNodeKeys}
            allExpanded={allExpanded}
            onToggleNode={toggleNode}
            onRemoveDimension={removeDimension}
            onAppendDimension={appendDimension}
            onResetRoute={() => updateRoute(DEFAULT_ROUTE)}
            onToggleAll={() => setExpanded(allExpanded ? new Set() : new Set(allNodeKeys))}
          />
        </>
      )}
    </div>
  )
}

/* ---------------------------------- 汇总条 ---------------------------------- */

function SummaryStrip({ data }: { data: KnowledgeMapData }) {
  const factsTotal = data.facts_by_doc.reduce((sum, item) => sum + item.count, 0)
  const docCount = new Set(data.rules.map((r) => r.doc_id).filter(Boolean)).size
  const stats: Array<[string, number, string]> = [
    ['结构化规则', data.rules.length, '当前读路径集合'],
    ['向量化事实', factsTotal, `${data.facts_by_doc.length} 篇文档`],
    ['政策集合', data.collections.length, '含历史版本'],
    ['覆盖文档', docCount, '规则来源'],
  ]
  return (
    <section aria-label="知识体系汇总" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {stats.map(([label, value, sub]) => (
        <div key={label} className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex items-center gap-2.5">
            <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-blue-50 text-blue-600">
              <Database className="size-4" />
            </span>
            <span className="text-xs text-slate-500">{label}</span>
          </div>
          <div className="mt-3 font-mono text-2xl font-bold tabular-nums text-slate-900">{formatNumber(value)}</div>
          <div className="mt-1 text-[11px] text-slate-500">{sub}</div>
        </div>
      ))}
    </section>
  )
}

/* ---------------------------------- 集合盘点 ---------------------------------- */

function CollectionInventory({ data }: { data: KnowledgeMapData }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white px-5 py-5 sm:px-6">
      <div className="mb-3 flex items-baseline gap-3">
        <h3 className="text-base font-semibold text-slate-900">Milvus 集合盘点</h3>
        <p className="text-xs text-slate-500">结构化规则与向量化事实的全部集合，「当前读路径」即问答检索实际消费的集合</p>
      </div>

      <table aria-label="Milvus 政策集合" className="w-full text-left text-sm text-slate-700">
        <thead>
          <tr className="border-b border-slate-200 text-[11px] font-medium text-slate-500">
            <th className="px-3 py-2.5">集合</th>
            <th className="px-3 py-2.5">类型</th>
            <th className="px-3 py-2.5 text-right">条数</th>
            <th className="px-3 py-2.5">状态</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {data.collections.map((col) => (
            <tr key={col.name} className={col.active ? 'bg-emerald-50/40' : 'transition-colors hover:bg-slate-50/70'}>
              <td className="px-3 py-2.5 font-mono text-xs text-slate-800">{col.name}</td>
              <td className="px-3 py-2.5">
                <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${col.kind === 'rules' ? 'bg-blue-50 text-blue-700' : 'bg-violet-50 text-violet-700'}`}>
                  {col.kind === 'rules' ? '结构化规则' : '向量化事实'}
                </span>
              </td>
              <td className="px-3 py-2.5 text-right font-mono tabular-nums">{formatNumber(col.row_count)}</td>
              <td className="px-3 py-2.5">
                {col.active ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">
                    <span aria-hidden className="size-1.5 rounded-full bg-emerald-500" />当前读路径
                  </span>
                ) : (
                  <span className="text-xs text-slate-400">历史 / 备用</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {data.facts_by_doc.length > 0 && (
        <div className="mt-4 border-t border-dashed border-slate-200 pt-3">
          <h4 className="mb-2 text-xs font-semibold text-slate-700">
            向量化事实按文档分布 <span className="ml-1 font-normal text-slate-400">语义检索单元 · 共 {formatNumber(data.facts_by_doc.reduce((s, i) => s + i.count, 0))} 条</span>
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {data.facts_by_doc.map((item) => (
              <span key={item.doc_id || UNLABELED} className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600">
                <span className="font-mono">{item.doc_id || UNLABELED}</span>
                <strong className="font-mono tabular-nums text-slate-800">{formatNumber(item.count)}</strong>
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

/* ---------------------------------- 知识体系树 ---------------------------------- */

function KnowledgeTreeSection({
  data,
  route,
  tree,
  expanded,
  allNodeKeys,
  allExpanded,
  onToggleNode,
  onRemoveDimension,
  onAppendDimension,
  onResetRoute,
  onToggleAll,
}: {
  data: KnowledgeMapData
  route: DimKey[]
  tree: MapNode[]
  expanded: Set<string>
  allNodeKeys: string[]
  allExpanded: boolean
  onToggleNode: (key: string) => void
  onRemoveDimension: (dim: DimKey) => void
  onAppendDimension: (dim: DimKey) => void
  onResetRoute: () => void
  onToggleAll: () => void
}) {
  const appendable = DIMENSIONS.filter((d) => !route.includes(d.key))

  return (
    <section className="rounded-2xl border border-slate-200 bg-white px-5 py-5 sm:px-6">
      <div className="mb-3 flex flex-wrap items-baseline gap-3">
        <h3 className="text-base font-semibold text-slate-900">知识体系树</h3>
        <p className="text-xs text-slate-500">逐级展开查看框架，叶子为具体规则</p>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={onToggleAll}
            disabled={tree.length === 0}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 transition-colors hover:border-slate-300 hover:text-slate-800 disabled:opacity-40"
          >
            {allExpanded ? '全部收起' : '全部展开'}
          </button>
          <button
            type="button"
            onClick={onResetRoute}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 transition-colors hover:border-slate-300 hover:text-slate-800"
          >
            <RotateCcw className="size-3" />默认路线
          </button>
        </div>
      </div>

      {/* 维度路线编辑：删除用 ×，追加用下拉；至少保留一个维度 */}
      <div className="mb-4 flex flex-wrap items-center gap-1.5 rounded-xl bg-slate-50 px-3 py-2.5 ring-1 ring-slate-200/70">
        <span className="mr-1 inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500">
          <Boxes className="size-3.5" />展开路线
        </span>
        {route.map((dim, index) => (
          <span key={dim} className="inline-flex items-center">
            {index > 0 && <ChevronRight aria-hidden className="mx-0.5 size-3 text-slate-300" />}
            <span className="inline-flex items-center gap-1 rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 ring-1 ring-slate-200">
              {DIM_LABEL[dim]}
              {route.length > 1 && (
                <button
                  type="button"
                  aria-label={`移除维度 ${DIM_LABEL[dim]}`}
                  onClick={() => onRemoveDimension(dim)}
                  className="rounded-full p-0.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
                >
                  <X className="size-3" />
                </button>
              )}
            </span>
          </span>
        ))}
        {appendable.length > 0 && (
          <label className="ml-1 inline-flex items-center gap-1 text-xs text-slate-500">
            <Plus aria-hidden className="size-3" />
            <select
              aria-label="添加展开维度"
              value=""
              onChange={(event) => {
                const dim = event.target.value as DimKey
                if (dim) onAppendDimension(dim)
              }}
              className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs text-slate-600"
            >
              <option value="" disabled>添加维度</option>
              {appendable.map((d) => (
                <option key={d.key} value={d.key}>{d.label}</option>
              ))}
            </select>
          </label>
        )}
      </div>

      {tree.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-200 px-6 py-12 text-center">
          <p className="text-sm font-medium text-slate-600">当前读路径集合中没有规则</p>
          <p className="mt-1 text-xs text-slate-400">
            集合 <span className="font-mono">{data.rules_collection}</span> 为空，请先在发布管理创建并发布知识版本
          </p>
        </div>
      ) : (
        <ul aria-label="知识体系树" className="space-y-1.5">
          {tree.map((node) => (
            <MapTreeNode
              key={node.key}
              node={node}
              depth={0}
              routeLength={route.length}
              expanded={expanded}
              onToggleNode={onToggleNode}
            />
          ))}
        </ul>
      )}
    </section>
  )
}

function MapTreeNode({
  node,
  depth,
  routeLength,
  expanded,
  onToggleNode,
}: {
  node: MapNode
  depth: number
  routeLength: number
  expanded: Set<string>
  onToggleNode: (key: string) => void
}) {
  const isOpen = expanded.has(node.key)
  const isLeafLevel = depth === routeLength - 1

  return (
    <li>
      <button
        type="button"
        aria-expanded={isOpen}
        onClick={() => onToggleNode(node.key)}
        className="flex w-full min-w-0 items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors hover:bg-slate-50"
      >
        {isOpen ? <ChevronDown aria-hidden className="size-3.5 shrink-0 text-slate-400" /> : <ChevronRight aria-hidden className="size-3.5 shrink-0 text-slate-400" />}
        <span className={`truncate text-sm font-semibold ${node.value === UNLABELED ? 'text-slate-400' : 'text-slate-800'}`}>
          {node.value}
        </span>
        <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[10px] font-semibold tabular-nums text-slate-500">
          {formatNumber(node.count)}
        </span>
      </button>

      {isOpen && (
        <div className="ml-4 border-l border-slate-200 pl-3">
          {isLeafLevel ? (
            <ul className="space-y-2 py-2">
              {node.rules.map((rule) => (
                <RuleCard key={rule.rule_id} rule={rule} />
              ))}
            </ul>
          ) : (
            <ul className="space-y-1.5 py-1.5">
              {node.children.map((child) => (
                <MapTreeNode
                  key={child.key}
                  node={child}
                  depth={depth + 1}
                  routeLength={routeLength}
                  expanded={expanded}
                  onToggleNode={onToggleNode}
                />
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  )
}

/* ---------------------------------- 规则卡片 ---------------------------------- */

function MetaChip({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-slate-50 px-2 py-1 text-[11px] text-slate-600 ring-1 ring-slate-200/70">
      <span className="text-slate-400">{label}</span>
      <span className="font-mono font-semibold tabular-nums text-slate-700">{value}</span>
    </span>
  )
}

function RuleCard({ rule }: { rule: KnowledgeMapRule }) {
  const validity = formatValidity(rule)
  const ratio = formatRatio(rule.payment_ratio)
  const personalRatio = formatRatio(rule.personal_payment_ratio)
  const amountRange = formatAmountRange(rule.amount_band_min, rule.amount_band_max)

  const metas: Array<[string, string]> = []
  if (ratio) metas.push(['支付比例', ratio])
  if (personalRatio) metas.push(['个人比例', personalRatio])
  if (rule.deductible_amount) metas.push(['起付', `${rule.deductible_amount}元`])
  if (rule.cap_amount) metas.push(['封顶', `${rule.cap_amount}元`])
  if (rule.amount_band && !amountRange) metas.push(['金额分段', rule.amount_band])
  if (rule.admission_order) metas.push(['住院次序', rule.admission_order])
  if (rule.priority) metas.push(['优先级', rule.priority])

  return (
    <li className="rounded-xl border border-slate-200 bg-white p-3.5">
      <div className="flex flex-wrap items-center gap-2">
        {rule.rule_type && (
          <span className="inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-semibold text-blue-700">
            {rule.rule_type}
          </span>
        )}
        {rule.publish_status && rule.publish_status !== 'published' && (
          <span className="inline-flex items-center rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700">
            {rule.publish_status}
          </span>
        )}
        <span className="font-mono text-[10px] text-slate-400">{rule.rule_id}</span>
        {validity && (
          <span className="ml-auto font-mono text-[10px] text-slate-500">{validity}</span>
        )}
      </div>

      <p className="mt-2 text-sm leading-relaxed text-slate-800">
        {rule.rule_value || rule.source_text || '（无规则值）'}
      </p>

      {rule.source_text && rule.source_text !== rule.rule_value && (
        <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-slate-500" title={rule.source_text}>
          原文：{rule.source_text}
        </p>
      )}

      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        {metas.map(([label, value]) => (
          <MetaChip key={label} label={label} value={value} />
        ))}
        {amountRange && <MetaChip label="金额区间" value={amountRange} />}
        <span className="ml-auto font-mono text-[10px] text-slate-400">
          {[rule.region, rule.doc_id].filter(Boolean).join(' · ')}
        </span>
      </div>
    </li>
  )
}

/* ---------------------------------- 骨架屏 ---------------------------------- */

function MapSkeleton(): ReactNode {
  return (
    <div className="space-y-5" aria-busy="true" aria-label="知识体系加载中">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="rounded-xl border border-slate-200 bg-white p-4">
            <span className="block h-4 w-16 animate-pulse rounded bg-slate-200/80" />
            <span className="mt-3 block h-7 w-14 animate-pulse rounded bg-slate-200/80" />
          </div>
        ))}
      </div>
      <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5">
        <span className="block h-4 w-32 animate-pulse rounded bg-slate-200/80" />
        <span className="mt-4 block h-8 w-full animate-pulse rounded bg-slate-200/80" />
        <span className="mt-2 block h-8 w-2/3 animate-pulse rounded bg-slate-200/80" />
        <span className="mt-2 block h-8 w-1/2 animate-pulse rounded bg-slate-200/80" />
      </div>
    </div>
  )
}
