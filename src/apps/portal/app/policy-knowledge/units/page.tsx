'use client'

// 页面顶层使用 useSearchParams → 关闭静态预渲染（Next.js 要求 Suspense 或动态渲染）
export const dynamic = 'force-dynamic'

// 政策知识治理 · 单元模块（三栏 v5，Python 结构拆分 + 审核）。
// [来源: docs/steering/政策知识治理平台设计-V2.1.md §5.4/§5.5；按用户迭代要求]
//
// 核心模型：单元 = 文档结构树的叶子节点（Python structure_parser 拆分，确定性、与中栏树一致）。
// ① 左框：选文档 + 覆盖率（有提取记录的叶子 / 全部叶子）
// ② 中框：文档全文 → 文档树（章/条/段/项/目），可收展；叶子按是否被提取标记覆盖/待提取
// ③ 右栏：单元（叶子），按文档顺序(order_no)排列；
//         · 每个叶子生成全路径 content_hash（含祖先章/条/段/项/目），完全一致的直接排除（req2）
//         · 关联该叶子的 LLM 提取记录（状态），审核作用于提取记录
//         · 仅展示原文 + 状态 + 置信度；不展示结构化字段（类型/支付比例/分段等属于知识提取阶段）
//         · 审核通过(reviewed)后流转至「知识」页进行结构化提取/发布
//
// 数据：GET /documents/{id}/structure（Python 结构树，含页脚噪声过滤）+ GET /extractions?doc_id=
// 审核：POST /extractions/batch/audit（approve/reject+reason）
// 重提取：POST /extractions/{id}/reextract（LLM）

import { useState, useEffect, useCallback, useMemo, useRef, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import {
  FileText, Loader2, Lightbulb, ChevronRight, ChevronDown,
  Target,
  Plus, Minus, CornerDownRight, CopyX, RefreshCw, Check, X,
  ListTree, AlignLeft, Sparkles,
} from 'lucide-react'

const API = '/api/v1/medical-insurance-ai-agent/policy-pipeline'

// 叶子（单元）状态：聚合其关联提取记录的状态
const UNIT_STATUS: Record<string, { label: string; cls: string }> = {
  pending: { label: '无提取记录', cls: 'bg-slate-100 text-slate-500' },
  draft: { label: '待审', cls: 'bg-slate-100 text-slate-600' },
  reviewed: { label: '待发布', cls: 'bg-amber-100 text-amber-700' },
  published: { label: '已发布', cls: 'bg-emerald-100 text-emerald-700' },
  rejected: { label: '已驳回', cls: 'bg-red-100 text-red-700' },
}

const LEVEL_LABEL: Record<string, string> = {
  document: '文件', chapter: '章', article: '条', paragraph: '段',
  subparagraph: '项', item: '目', subitem: '子目', plain: '正文',
}

interface ClauseNode {
  node_id: string
  level: string
  marker: string
  title: string
  text: string
  parent_id: string | null
  path: string[]
  order_no: number
  has_children: boolean
  children: ClauseNode[]
}
interface StructureResp {
  doc_id: string; title: string; content_text: string; root: ClauseNode
}
interface DocItem { doc_id: string; title: string; pending_count?: number; created_at?: string; [k: string]: any }
interface PolicyRule { [k: string]: any }
interface ExtractedFields { fact_text?: string; rules?: PolicyRule[]; audit_reason?: string; [k: string]: any }
interface Extraction {
  extraction_id: string
  doc_id: string
  source_text: string
  extracted_fields: ExtractedFields
  confidence: number
  status: string
  [k: string]: any
}

interface UnitLeaf {
  leaf: ClauseNode
  hash: string
  exts: Extraction[]
  status: string
  isDup: boolean
}

interface Derived {
  root: ClauseNode
  byId: Map<string, ClauseNode>
  units: UnitLeaf[]
  unitByNodeId: Map<string, UnitLeaf>   // 叶子 node_id → 单元（含去重重定向）
  coverage: { total: number; covered: number }
  dupCount: number   // 疑似重复总数（含已处理，用于文档列表待处理数）
}

/** FNV-1a 同步哈希（内容指纹，用于去重展示）*/
function fnv1a(s: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) }
  return (h >>> 0).toString(16).padStart(8, '0')
}
function normText(s: string): string {
  return (s || '').replace(/[\s，。、；：“”‘’（）()【】\[\]「」.,;:％%]/g, '')
}

/** 剥除叶子文本的结构标记前缀（marker 不属于正文内容，匹配时不应参与）*/
function leafBody(node: ClauseNode): string {
  let body = node.text || ''
  const mk = node.marker || ''
  if (mk && body.startsWith(mk)) body = body.slice(mk.length)
  return body.trimStart()
}

/**
 * 全路径 hash：拼接 根→叶 所有祖先正文 + 叶子正文（含章/条/段/项/目各层）。
 * 确保不同位置的相同文本（如 #15 在「二、第三十六条修改为」下、#19 在另一处）hash 不同，避免误去重。
 */
function pathTextParts(leaf: ClauseNode, byId: Map<string, ClauseNode>): string[] {
  const parts: string[] = []
  let cur = leaf.parent_id ? byId.get(leaf.parent_id) : null
  while (cur) {
    if (cur.level !== 'document') parts.unshift(normText(cur.text))
    cur = cur.parent_id ? byId.get(cur.parent_id) : null
  }
  parts.push(normText(leaf.text))
  return parts
}
function pathHash(leaf: ClauseNode, byId: Map<string, ClauseNode>): string {
  return fnv1a(pathTextParts(leaf, byId).join('|'))
}
/** 叶子正文与祖先路径分离——用于加权相似度（需求2）*/
function leafAndPath(leaf: ClauseNode, byId: Map<string, ClauseNode>): { leaf: string; path: string } {
  const parts = pathTextParts(leaf, byId)
  return { leaf: parts[parts.length - 1] || '', path: parts.slice(0, -1).join('') }
}

/** 提取数字集合（含小数）——需求2：数字占比提高 */
function extractNumbers(s: string): Set<string> {
  const nums = new Set<string>()
  const m = s.match(/\d+(?:\.\d+)?/g)
  if (m) m.forEach((n) => nums.add(n))
  return nums
}

/** 集合交集大小 */
function setIntersect<T>(a: Set<T>, b: Set<T>): number {
  let n = 0
  a.forEach((x) => { if (b.has(x)) n++ })
  return n
}

/**
 * 加权相似度（需求2）：
 * - 叶子内容占 80%，路径占 20%
 * - 数字完全不同（无交集）直接判 0
 * - 叶子相似度 = 60%文本 + 40%数字（提高数字权重）
 */
function dupSimilarity(leafA: string, pathA: string, leafB: string, pathB: string): number {
  const leafSim = jaccard(bigrams(leafA), bigrams(leafB))
  const pathSim = jaccard(bigrams(pathA), bigrams(pathB))
  const numsA = extractNumbers(leafA)
  const numsB = extractNumbers(leafB)
  if (numsA.size > 0 && numsB.size > 0) {
    const common = setIntersect(numsA, numsB)
    if (common === 0) return 0  // 数字完全不同 → 不相似
    const numberSim = common / (numsA.size + numsB.size - common)
    const blendedLeaf = 0.6 * leafSim + 0.4 * numberSim
    return 0.8 * blendedLeaf + 0.2 * pathSim
  }
  return 0.8 * leafSim + 0.2 * pathSim
}

/** 最长公共子串长度（DP，回退匹配用）*/
function longestCommonSubstring(a: string, b: string): number {
  const m = a.length, n = b.length
  if (!m || !n) return 0
  let prev = new Array<number>(n + 1).fill(0)
  let best = 0
  for (let i = 1; i <= m; i++) {
    const cur = new Array<number>(n + 1).fill(0)
    const ai = a.charCodeAt(i - 1)
    for (let j = 1; j <= n; j++) {
      if (ai === b.charCodeAt(j - 1)) { cur[j] = prev[j - 1] + 1; if (cur[j] > best) best = cur[j] }
    }
    prev = cur
  }
  return best
}

/**
 * 提取记录 → 叶子定位（可多个）：
 * ① 优先「双向全包含」——源含叶子正文(提取覆盖整条子规则) 或 叶子含源(提取是多规则长条款的一部分)，取重叠最长者；并列最长都返回（处理重复文本叶子）。
 * ② 回退「最长公共子串」——重叠≥较短文本的 50% 且≥10字 才算命中；并列最高分都返回。
 * 注：旧版「叶子含提取前缀」方向反了——提取源常含父节点引言+子规则，导致父叶子抢匹配或完全失配。
 */
function matchLeaves(src: string, leaves: ClauseNode[]): string[] {
  const S = normText(src)
  if (!S || S.length < 6) return []
  type Cand = { id: string; len: number }
  // ① 双向全包含
  const contained: Cand[] = []
  for (const lf of leaves) {
    const lt = normText(leafBody(lf))
    if (lt.length < 6) continue
    if (S.includes(lt)) contained.push({ id: lf.node_id, len: lt.length })   // 源含叶子(整条)
    else if (lt.includes(S)) contained.push({ id: lf.node_id, len: S.length }) // 叶子含源(部分)
  }
  if (contained.length) {
    const mx = Math.max(...contained.map((c) => c.len))
    return contained.filter((c) => c.len === mx).map((c) => c.id)
  }
  // ② 回退：最长公共子串
  const scored: Cand[] = []
  for (const lf of leaves) {
    const lt = normText(leafBody(lf))
    if (lt.length < 6) continue
    const lcs = longestCommonSubstring(lt, S)
    if (lcs >= 10 && lcs >= Math.min(lt.length, S.length) * 0.5) scored.push({ id: lf.node_id, len: lcs })
  }
  if (scored.length) {
    const mx = Math.max(...scored.map((c) => c.len))
    return scored.filter((c) => c.len === mx).map((c) => c.id)
  }
  return []
}

function collectLeaves(node: ClauseNode, out: ClauseNode[] = []): ClauseNode[] {
  if (!node.has_children || node.children.length === 0) {
    if (node.level !== 'document') out.push(node)
    return out
  }
  for (const c of node.children) collectLeaves(c, out)
  return out
}
function flattenById(node: ClauseNode, map: Map<string, ClauseNode> = new Map()): Map<string, ClauseNode> {
  map.set(node.node_id, node)
  for (const c of node.children) flattenById(c, map)
  return map
}
function ancestorTexts(leaf: ClauseNode, byId: Map<string, ClauseNode>): ClauseNode[] {
  const out: ClauseNode[] = []
  let cur = leaf.parent_id ? byId.get(leaf.parent_id) : null
  while (cur) {
    if (cur.level !== 'document') out.unshift(cur)
    cur = cur.parent_id ? byId.get(cur.parent_id) : null
  }
  return out
}
function subtreeLeafCount(node: ClauseNode): number {
  return collectLeaves(node).length
}

// 叶子状态聚合
function leafStatus(exts: Extraction[]): string {
  if (!exts.length) return 'pending'
  const ss = exts.map((e) => e.status)
  if (ss.some((s) => s === 'rejected')) return 'rejected'
  if (ss.every((s) => s === 'published')) return 'published'
  if (ss.every((s) => s === 'reviewed' || s === 'published')) return 'reviewed'
  return 'draft'
}

// 近似叶子检测（加权相似度 ≥ 0.8）——需求1+2
function bigrams(s: string): Set<string> {
  const set = new Set<string>()
  for (let i = 0; i < s.length - 1; i++) set.add(s.slice(i, i + 2))
  return set
}
function jaccard(a: Set<string>, b: Set<string>): number {
  if (!a.size && !b.size) return 0
  let n = 0
  a.forEach((x) => { if (b.has(x)) n++ })
  return n / (a.size + b.size - n)
}
function detectDupLeaves(leaves: ClauseNode[], byId: Map<string, ClauseNode>): { dupSet: Set<string>; partnerMap: Map<string, string[]> } {
  const items = leaves.map((l) => leafAndPath(l, byId))
  const dup = new Set<string>()
  const partnerMap = new Map<string, string[]>()
  for (let i = 0; i < items.length; i++) {
    if (!items[i].leaf) continue
    for (let j = i + 1; j < items.length; j++) {
      if (!items[j].leaf) continue
      if (dupSimilarity(items[i].leaf, items[i].path, items[j].leaf, items[j].path) >= 0.8) {
        dup.add(leaves[i].node_id); dup.add(leaves[j].node_id)
        // 双向记录伙伴关系
        if (!partnerMap.has(leaves[i].node_id)) partnerMap.set(leaves[i].node_id, [])
        if (!partnerMap.has(leaves[j].node_id)) partnerMap.set(leaves[j].node_id, [])
        partnerMap.get(leaves[i].node_id)!.push(leaves[j].node_id)
        partnerMap.get(leaves[j].node_id)!.push(leaves[i].node_id)
      }
    }
  }
  return { dupSet: dup, partnerMap }
}

/** 查找指定单元的疑似重复候选（加权相似度 ≥ 0.8），按相似度降序——需求1+2 */
function findDupCandidates(leaf: ClauseNode, units: UnitLeaf[], byId: Map<string, ClauseNode>): { unit: UnitLeaf; score: number }[] {
  const a = leafAndPath(leaf, byId)
  if (!a.leaf && !a.path) return []
  return units
    .filter((u) => u.leaf.node_id !== leaf.node_id)
    .map((u) => { const b = leafAndPath(u.leaf, byId); return { unit: u, score: dupSimilarity(a.leaf, a.path, b.leaf, b.path) } })
    .filter((x) => x.score >= 0.8)
    .sort((a, b) => b.score - a.score)
}

type ColFilter = 'all' | 'dup' | 'merged' | 'unique' | 'draft' | 'reviewed' | 'rejected'

/** 双向成对添加：A-B 确认「不是重复」，两个方向都记录 */
function addPair(map: Map<string, Set<string>>, a: string, b: string) {
  if (!map.has(a)) map.set(a, new Set())
  if (!map.has(b)) map.set(b, new Set())
  map.get(a)!.add(b)
  map.get(b)!.add(a)
}

/**
 * 成对关系（需求11.3）：相对当前单元判断两单元的关系，返回 'dup' | 'not_dup' | 'undecided'。
 * - dup：任一方向标记过重复（merged[a]===b 或 merged[b]===a）——「重复」与「留下相似单元」都属于此
 * - not_dup：双向 not_dup 集合含此对
 * - undecided：未判定过（即使某方被别处标记为重复，也不影响本对）
 */
function pairRel(
  a: string, b: string,
  dupMerged: Map<string, string>, dupNotDup: Map<string, Set<string>>,
): 'dup' | 'not_dup' | 'undecided' {
  if (dupMerged.get(a) === b || dupMerged.get(b) === a) return 'dup'
  if (dupNotDup.get(a)?.has(b) || dupNotDup.get(b)?.has(a)) return 'not_dup'
  return 'undecided'
}

/** 单元审核决定（无提取记录的单元用，需求11.1）*/
interface UnitAudit { action: 'approve' | 'reject'; reason: string }

export default function UnitsPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center py-16"><Loader2 className="size-5 animate-spin text-slate-400" /></div>}>
      <UnitsContent />
    </Suspense>
  )
}

function UnitsContent() {
  const params = useSearchParams()
  const initialDocId = params.get('doc_id') || ''

  const [docs, setDocs] = useState<DocItem[]>([])
  const [selectedDocId, setSelectedDocId] = useState(initialDocId)
  const [docTitle, setDocTitle] = useState('')
  const [structure, setStructure] = useState<StructureResp | null>(null)
  const [units, setUnits] = useState<Extraction[]>([])
  const [loadingDocs, setLoadingDocs] = useState(true)
  const [loadingDoc, setLoadingDoc] = useState(false)
  const [error, setError] = useState('')
  const [selectedUnitKey, setSelectedUnitKey] = useState('')   // 高亮的单元(叶子 node_id)
  const [highlightedLeafId, setHighlightedLeafId] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [colFilter, setColFilter] = useState<ColFilter>('all')
  const [rejectKey, setRejectKey] = useState<string | null>(null)
  const [singleReason, setSingleReason] = useState('')
  const [batchReason, setBatchReason] = useState('')
  const [batchRejecting, setBatchRejecting] = useState(false)
  const [busy, setBusy] = useState<string>('') // 单元 key=单个在跑 / 'batch'=批量在跑
  const [toast, setToast] = useState('')
  // 需求1：中栏视图切换（树/原文）
  const [viewMode, setViewMode] = useState<'tree' | 'raw'>('tree')
  // 需求1：重复处理——双向成对模型（不是全局标签）
  const [dupNotDup, setDupNotDup] = useState<Map<string, Set<string>>>(new Map())  // A → {B,C}：A 与 B/C 确认「不是重复」（双向存储）
  const [dupMerged, setDupMerged] = useState<Map<string, string>>(new Map())  // A → K：A 标记为 K 的重复副本
  const [dupModalKey, setDupModalKey] = useState<string | null>(null)       // 当前弹框处理的单元
  // 需求11.1：单元级审核（无提取记录的单元也能通过/驳回）
  const [unitAudit, setUnitAudit] = useState<Map<string, UnitAudit>>(new Map())  // node_id → {action, reason}

  const leafRefs = useRef<Map<string, HTMLDivElement>>(new Map())
  const unitRefs = useRef<Map<string, HTMLDivElement>>(new Map())

  const fetchDocs = useCallback(async () => {
    setLoadingDocs(true)
    try {
      const r = await fetch(`${API}/documents?page=1&page_size=100`)
      const d = await r.json()
      setDocs(d.items || [])
    } catch { setError('加载文档失败') }
    finally { setLoadingDocs(false) }
  }, [])
  useEffect(() => { fetchDocs() }, [fetchDocs])

  useEffect(() => {
    if (!selectedDocId && docs.length > 0) setSelectedDocId(docs[0].doc_id)
  }, [docs, selectedDocId])

  /** 全量拉取文档提取记录（分页循环，绕过后端 page_size 上限）。
   *  doc_1d44 有 122 条提取记录，单次 page_size=100 只拿 100 会漏 22 条，
   *  导致批量通过无法覆盖全部、pending 残留（问题1/3 根因）。 */
  const fetchAllExtractions = useCallback(async (docId: string): Promise<Extraction[]> => {
    const out: Extraction[] = []
    for (let page = 1; page < 50; page++) {
      try {
        const r = await fetch(`${API}/extractions?doc_id=${docId}&page=${page}&page_size=100`)
        if (!r.ok) break
        const d = await r.json()
        const items = (d.items || []) as Extraction[]
        if (!items.length) break
        out.push(...items)
        if (out.length >= (d.total || 0)) break
      } catch { break }
    }
    return out
  }, [])

  const refreshUnits = useCallback(async (docId: string) => {
    try { setUnits(await fetchAllExtractions(docId)) } catch { /* ignore */ }
  }, [fetchAllExtractions])

  useEffect(() => {
    if (!selectedDocId) { setStructure(null); setUnits([]); setDocTitle(''); return }
    let cancel = false
    setSelected(new Set()); setRejectKey(null); setBatchRejecting(false)
    setDupModalKey(null)
    ;(async () => {
      setLoadingDoc(true); setError(''); setStructure(null); setUnits([])
      try {
        const [stRes, allExts, dupRes] = await Promise.all([
          fetch(`${API}/documents/${selectedDocId}/structure`),
          fetchAllExtractions(selectedDocId),
          fetch(`${API}/documents/${selectedDocId}/dup-state`),
        ])
        if (cancel) return
        if (stRes.ok) { const s = await stRes.json(); setStructure(s); setDocTitle(s.title || '') }
        setUnits(allExts)
        // 需求1：恢复重复处理状态（双向成对格式）
        if (dupRes.ok) {
          const ds = await dupRes.json().catch(() => ({}))
          // 兼容旧格式 resolved[]：旧的全局 resolved 转为空 notDup（旧数据重新审核）
          const nd = new Map<string, Set<string>>()
          if (ds.not_dup) {
            for (const [k, vals] of Object.entries(ds.not_dup)) {
              nd.set(k, new Set(vals as string[]))
            }
          }
          setDupNotDup(nd)
          setDupMerged(new Map(Object.entries(ds.merged || {})))
          // 需求11.1：恢复单元级审核
          const ua = new Map<string, UnitAudit>()
          if (ds.unit_audit) {
            for (const [k, v] of Object.entries(ds.unit_audit)) {
              const rec = v as UnitAudit
              if (rec && (rec.action === 'approve' || rec.action === 'reject')) ua.set(k, { action: rec.action, reason: rec.reason || '' })
            }
          }
          setUnitAudit(ua)
        } else {
          setDupNotDup(new Map()); setDupMerged(new Map()); setUnitAudit(new Map())
        }
      } catch { if (!cancel) setError('加载文档/单元失败') }
      finally { if (!cancel) setLoadingDoc(false) }
    })()
    return () => { cancel = true }
  }, [selectedDocId])

  // ── 结构派生（仅依赖 structure，含 O(n²) 相似度检测）──
  // 性能关键：相似度计算与 dup 判定状态无关，提前 memo。
  // 否则每点一次标记按钮（dupMerged/dupNotDup/unitAudit 变）都会重算 149 叶子的 O(n²) 相似度，导致卡顿。
  const structInfo = useMemo(() => {
    if (!structure) return null
    let root = structure.root
    const realChildren = root.children || []
    if (realChildren.length === 0 && structure.content_text.trim()) {
      const fallback: ClauseNode = {
        node_id: '__fallback__', level: 'plain', marker: '', title: '全文',
        text: structure.content_text, parent_id: root.node_id, path: ['全文'],
        has_children: false, children: [], order_no: 1,
      }
      root = { ...root, children: [fallback] }
    }
    const byId = flattenById(root)
    const allLeaves = collectLeaves(root)
    const sorted = allLeaves.slice().sort((a, b) => (a.order_no || 0) - (b.order_no || 0))
    // 先去重（hash 完全一致），得到保留叶子——与下方 unitsOut 去重逻辑一致
    const seenHash = new Map<string, string>()
    const keptLeaves: ClauseNode[] = []
    for (const lf of sorted) {
      const h = pathHash(lf, byId)
      if (seenHash.has(h)) continue
      seenHash.set(h, lf.node_id)
      keptLeaves.push(lf)
    }
    // 近义检测（O(n²) 相似度，仅 structure 变时算一次）——partnerMap 用 kept node_id
    const { dupSet, partnerMap } = detectDupLeaves(keptLeaves, byId)
    return { root, byId, allLeaves, sorted, dupSet, partnerMap }
  }, [structure])

  // ── 派生：叶子为单元（去重 + 关联提取 + 顺序）──
  const derived = useMemo<Derived | null>(() => {
    if (!structInfo) return null
    const { root, byId, allLeaves, sorted, dupSet, partnerMap } = structInfo
    // 需求11.1：单元有效状态——有提取则用提取状态，无提取则回退 unit_audit，再无则 pending
    const effStatus = (nodeId: string, exts: Extraction[]): string => {
      if (exts.length > 0) return leafStatus(exts)
      const ua = unitAudit.get(nodeId)
      if (ua) return ua.action === 'approve' ? 'reviewed' : 'rejected'
      return 'pending'
    }
    // 提取记录 → 叶子（全量叶子）
    const leafExts = new Map<string, Extraction[]>()
    allLeaves.forEach((l) => { leafExts.set(l.node_id, []) })
    for (const u of units) {
      const src = (u.extracted_fields?.fact_text || u.source_text || '').trim()
      const lids = matchLeaves(src, allLeaves)
      for (const lid of lids) {
        leafExts.get(lid)!.push(u)
      }
    }
    // ① 先去重（hash 完全一致 → 合并），得到保留单元
    const seenHash = new Map<string, string>()  // hash → kept node_id
    const unitsOut: UnitLeaf[] = []
    const unitByNodeId = new Map<string, UnitLeaf>()  // 含重定向：deduped leaf → kept unit
    for (const lf of sorted) {
      const h = pathHash(lf, byId)
      const keptId = seenHash.get(h)
      if (keptId) {
        const kept = unitsOut.find((x) => x.leaf.node_id === keptId)!
        kept.exts.push(...(leafExts.get(lf.node_id) || []))
        kept.exts.sort((a, b) => (a.extraction_id > b.extraction_id ? 1 : -1))
        kept.status = effStatus(kept.leaf.node_id, kept.exts)
        unitByNodeId.set(lf.node_id, kept)
        continue
      }
      seenHash.set(h, lf.node_id)
      const exts = (leafExts.get(lf.node_id) || []).slice()
      unitsOut.push({ leaf: lf, hash: h, exts, status: effStatus(lf.node_id, exts), isDup: false })
      unitByNodeId.set(lf.node_id, unitsOut[unitsOut.length - 1])
    }
    // ② 近义检测结果来自 structInfo（不再每次重算 O(n²) 相似度）
    // 需求11.3：成对相对判定——某单元「已处理」= 自身被标记为重复 OR 所有伙伴与本单元的关系均已判定
    const nodeResolved = (id: string) => {
      if (dupMerged.has(id)) return true
      const partners = partnerMap.get(id) || []
      return partners.length > 0 && partners.every((p) => pairRel(id, p, dupMerged, dupNotDup) !== 'undecided')
    }
    // ③ 设置 isDup
    for (const u of unitsOut) {
      u.isDup = dupSet.has(u.leaf.node_id) && !nodeResolved(u.leaf.node_id)
    }
    const covered = unitsOut.filter((u) => u.exts.length > 0).length
    const coverage = { total: unitsOut.length, covered }
    return { root, byId, units: unitsOut, unitByNodeId, coverage, dupCount: dupSet.size }
  }, [structInfo, units, dupNotDup, dupMerged, unitAudit])

  // 需求1：持久化重复处理状态到后端（双向成对格式）
  const persistDupState = useCallback((notDup: Map<string, Set<string>>, merged: Map<string, string>, audit: Map<string, UnitAudit>) => {
    if (!selectedDocId) return
    const notDupObj: Record<string, string[]> = {}
    notDup.forEach((vals, key) => { notDupObj[key] = [...vals] })
    const auditObj: Record<string, UnitAudit> = {}
    audit.forEach((v, k) => { auditObj[k] = v })
    fetch(`${API}/documents/${selectedDocId}/dup-state`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ not_dup: notDupObj, merged: Object.fromEntries(merged), unit_audit: auditObj, total_dup: derived?.dupCount || 0 }),
    }).catch(() => {})
  }, [selectedDocId, derived])

  useEffect(() => {
    if (!derived) return
    const all = new Set<string>()
    derived.byId.forEach((n) => { if (n.has_children) all.add(n.node_id) })
    setExpanded(all)
  }, [derived?.root])

  const toggleNode = (id: string) =>
    setExpanded((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  const expandAll = () => { if (!derived) return; const all = new Set<string>(); derived.byId.forEach((n) => { if (n.has_children) all.add(n.node_id) }); setExpanded(all) }
  const collapseAll = () => setExpanded(new Set())

  const expandAncestors = (leafId: string) => {
    if (!derived) return
    const chain: string[] = []
    let cur = derived.byId.get(leafId)
    while (cur && cur.parent_id) { chain.push(cur.parent_id); cur = derived.byId.get(cur.parent_id) }
    setExpanded((prev) => { const n = new Set(prev); chain.forEach((c) => n.add(c)); return n })
  }

  // 中栏叶子点击 → 定位右栏单元
  const clickLeaf = (nodeId: string) => {
    const ul = derived?.unitByNodeId.get(nodeId)
    if (!ul) return
    setSelectedUnitKey(ul.leaf.node_id)
    setHighlightedLeafId(nodeId)
    unitRefs.current.get(ul.leaf.node_id)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }
  // 右栏单元点击 → 定位中栏叶子
  const clickUnit = (nodeId: string) => {
    setSelectedUnitKey(nodeId)
    setHighlightedLeafId(nodeId)
    expandAncestors(nodeId)
    setTimeout(() => leafRefs.current.get(nodeId)?.scrollIntoView({ block: 'center', behavior: 'smooth' }), 60)
  }

  const flash = (msg: string) => { setToast(msg); setTimeout(() => setToast(''), 2600) }

  // 审核：作用于单元关联的全部提取记录 id；无提取记录的单元走单元级审核（需求11.1）
  async function batchAudit(unitKeys: string[], action: 'approve' | 'reject', reason = '') {
    if (!derived) return
    // 分流：有提取记录→审提取；无提取记录→写 unit_audit
    const withExt: string[] = []
    const withoutExt: string[] = []
    for (const k of unitKeys) {
      const ul = derived.unitByNodeId.get(k)
      if (!ul) continue
      ;(ul.exts.length > 0 ? withExt : withoutExt).push(k)
    }
    let extUpdated = 0
    if (withExt.length) {
      const ids = collectExtIds(withExt)
      if (!ids.length) { flash('所选单元无提取记录，无可审核项'); return }
      setBusy('batch')
      try {
        const r = await fetch(`${API}/extractions/batch/audit`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ extraction_ids: ids, action, reason }),
        })
        const d = await r.json().catch(() => ({}))
        if (!r.ok) { setError(d.detail?.message || d.detail || '审核失败'); setBusy(''); return }
        extUpdated = d.updated || 0
      } catch { setError('审核失败'); setBusy(''); return }
    }
    let unitAudited = 0
    if (withoutExt.length) {
      const newAudit = new Map(unitAudit)
      for (const k of withoutExt) {
        newAudit.set(k, { action, reason: action === 'reject' ? reason : '' })
        unitAudited++
      }
      setUnitAudit(newAudit)
      persistDupState(dupNotDup, dupMerged, newAudit)
      if (!withExt.length) setBusy('batch')
    }
    const parts: string[] = []
    if (extUpdated) parts.push(`${action === 'approve' ? '通过' : '驳回'} ${extUpdated} 条提取`)
    if (unitAudited) parts.push(`${action === 'approve' ? '通过' : '驳回'} ${unitAudited} 个单元`)
    flash(parts.length ? parts.join('·') : '无可审核单元')
    setSelected(new Set()); setRejectKey(null); setSingleReason(''); setBatchRejecting(false); setBatchReason('')
    if (withExt.length) { await refreshUnits(selectedDocId); fetchDocs() }  // 仅提取审核需刷新后端
    setBusy('')
  }
  async function batchReextract(unitKeys: string[]) {
    const ids = collectExtIds(unitKeys)
    if (!ids.length) { flash('所选单元无提取记录，无可重提取项'); return }
    setBusy('batch')
    let ok = 0, fail = 0
    for (const id of ids) {
      try { const r = await fetch(`${API}/extractions/${id}/reextract`, { method: 'POST' }); if (r.ok) ok++; else fail++ }
      catch { fail++ }
    }
    flash(`重提取完成：成功 ${ok}${fail ? `，失败 ${fail}` : ''}`)
    setSelected(new Set())
    await refreshUnits(selectedDocId)
    fetchDocs()  // 需求4：实时更新文档列表待处理数
    setBusy('')
  }
  // 需求2：为无提取记录的单元触发单条 LLM 提取
  async function triggerLeafExtract(leafText: string) {
    if (!selectedDocId || !leafText.trim()) return
    setBusy(selectedDocId)
    try {
      const r = await fetch(`${API}/documents/${selectedDocId}/extract-leaf`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_text: leafText }),
      })
      if (r.ok) { const d = await r.json(); flash(`提取完成：新建 ${d.extractions_created || 0} 条记录`); await refreshUnits(selectedDocId); fetchDocs() }
      else { const d = await r.json().catch(() => ({})); flash(`提取失败：${d.detail?.message || '未知错误'}`) }
    } catch { flash('提取失败：网络错误') }
    finally { setBusy('') }
  }
  function collectExtIds(unitKeys: string[]): string[] {
    if (!derived) return []
    const ids: string[] = []
    for (const k of unitKeys) { const ul = derived.unitByNodeId.get(k); if (ul) ul.exts.forEach((e) => ids.push(e.extraction_id)) }
    return [...new Set(ids)]
  }

  const toggleSelect = (key: string) =>
    setSelected((prev) => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n })

  // 需求1：重复处理——双向成对模型（不是全局标签）
  // 保留本单元：本单元与所有候选都不是重复
  const resolveDupKeep = (key: string) => {
    if (!derived) return
    const unit = derived.unitByNodeId.get(key)
    if (!unit) return
    const newNotDup = new Map(dupNotDup)
    const partners = findDupCandidates(unit.leaf, derived.units, derived.byId).map((c) => c.unit.leaf.node_id)
    // 需求11.5：仅判定未决伙伴为 not_dup，不动已判定的对（避免 dup 与 not_dup 冲突）
    for (const pid of partners) {
      if (pairRel(key, pid, dupMerged, dupNotDup) === 'undecided') addPair(newNotDup, key, pid)
    }
    setDupNotDup(newNotDup)
    persistDupState(newNotDup, dupMerged, unitAudit)
    setDupModalKey(null); fetchDocs()
  }

  // 保留此候选：本单元是候选的重复副本（需求11.4：也是重复关系，仅方向相反）
  const resolveDupMerge = (key: string, targetKey: string) => {
    const newMerged = new Map(dupMerged).set(key, targetKey)
    setDupMerged(newMerged)
    persistDupState(dupNotDup, newMerged, unitAudit)
    setDupModalKey(null); fetchDocs()
  }

  // 候选是重复：候选是当前单元的副本（merge candidate → current）
  const markCandidateDup = (candidateKey: string) => {
    if (!dupModalKey) return
    const newMerged = new Map(dupMerged).set(candidateKey, dupModalKey)
    setDupMerged(newMerged)
    persistDupState(dupNotDup, newMerged, unitAudit)
  }

  // 候选不是重复：仅解除当前这对关系（不影响候选与其他单元的关系）
  const markCandidateNotDup = (candidateKey: string) => {
    if (!dupModalKey) return
    const newNotDup = new Map(dupNotDup)
    addPair(newNotDup, dupModalKey, candidateKey)  // 双向
    setDupNotDup(newNotDup)
    persistDupState(newNotDup, dupMerged, unitAudit)
  }
  const dupModalUnit = dupModalKey && derived ? derived.unitByNodeId.get(dupModalKey) : null
  const dupCandidates = dupModalUnit && derived ? findDupCandidates(dupModalUnit.leaf, derived.units, derived.byId) : []

  // 需求3：实时统计（全状态）
  // unique = 未被 merge 且所有伙伴与本单元的关系均已判定（需求11.3：成对相对）
  const isUnique = useCallback((nodeId: string) => {
    if (!derived || dupMerged.has(nodeId)) return false
    const unit = derived.unitByNodeId.get(nodeId)
    if (!unit) return false
    const partners = findDupCandidates(unit.leaf, derived.units, derived.byId).map((c) => c.unit.leaf.node_id)
    if (partners.length === 0) return false
    return partners.every((pid) => pairRel(nodeId, pid, dupMerged, dupNotDup) !== 'undecided')
  }, [derived, dupMerged, dupNotDup])

  const stats = useMemo(() => {
    if (!derived) return { dup: 0, merged: 0, draft: 0, reviewed: 0, rejected: 0, total: 0 }
    // 互斥分类：被标记为重复副本（merged）的单元单独统计，不计入通过/驳回/待审。
    // 保证 总数 = 重复 + 通过 + 已驳回 + 待审核（+ 疑似重复未处理）。
    const mergedSet = new Set(derived.units.filter((u) => dupMerged.has(u.leaf.node_id)).map((u) => u.leaf.node_id))
    const active = derived.units.filter((u) => !mergedSet.has(u.leaf.node_id))
    return {
      dup: derived.units.filter((u) => u.isDup).length,
      merged: mergedSet.size,
      // 待审核/通过/已驳回 仅统计非重复单元（需求：总数-重复 = 通过+已驳回+待审核）
      draft: active.filter((u) => u.status === 'draft' || u.status === 'pending').length,
      reviewed: active.filter((u) => u.status === 'reviewed' || u.status === 'published').length,
      rejected: active.filter((u) => u.status === 'rejected').length,
      total: derived.units.length,
    }
  }, [derived, dupMerged, dupNotDup])

  const visibleUnits = useMemo(() => {
    if (!derived) return []
    let list = derived.units.slice()
    if (colFilter === 'dup') list = list.filter((u) => u.isDup)
    else if (colFilter === 'merged') list = list.filter((u) => dupMerged.has(u.leaf.node_id))
    else if (colFilter === 'unique') list = list.filter((u) => isUnique(u.leaf.node_id))
    else if (colFilter === 'draft') list = list.filter((u) => u.status === 'draft' || u.status === 'pending')
    else if (colFilter === 'reviewed') list = list.filter((u) => u.status === 'reviewed' || u.status === 'published')
    else if (colFilter === 'rejected') list = list.filter((u) => u.status === 'rejected')
    return list
  }, [derived, colFilter, dupMerged, dupNotDup, isUnique])

  const allVisibleChecked = visibleUnits.length > 0 && visibleUnits.every((u) => selected.has(u.leaf.node_id))
  const toggleSelectAll = () => {
    if (allVisibleChecked) setSelected(new Set())
    else setSelected(new Set(visibleUnits.map((u) => u.leaf.node_id)))
  }

  const coverage = derived?.coverage

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">
            政策单元 · Python 结构拆分
          </span>
        </div>
        <h2 className="text-xl font-semibold tracking-tight text-slate-900 mt-1">单元</h2>
        <p className="text-xs text-slate-500 mt-0.5">
          单元 = 文档结构叶子（Python 拆分，确定性）。按文档顺序排列；hash 去重完全一致；正文字噪声已过滤。
        </p>
      </div>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">{error}</div>}
      {toast && <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-700">{toast}</div>}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12 lg:h-[78vh]">
        {/* ① 左框 */}
        <div className="lg:col-span-3 flex flex-col rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          <div className="border-b border-slate-100 px-3 py-2 text-xs font-semibold text-slate-600">文档</div>
          <div className="flex-1 overflow-y-auto p-2">
            {loadingDocs ? (
              <div className="flex justify-center py-8"><Loader2 className="size-4 animate-spin text-slate-400" /></div>
            ) : docs.length === 0 ? (
              <div className="px-2 py-8 text-center text-xs text-slate-400">
                无文档。<Link href="/policy-knowledge/documents" className="text-blue-500 hover:underline">去上传 →</Link>
              </div>
            ) : (
              docs.map((doc) => {
                const isSel = doc.doc_id === selectedDocId
                // 待处理 = 待审核单元数（draft/pending），与后端 pending_count 口径一致。
                // 疑似重复是另一类工作，在右栏单独统计，不计入文档列表待处理数（避免前后端口径不一致）。
                const totalPending = isSel ? stats.draft : (doc.pending_count || 0)
                return (
                  <button key={doc.doc_id} onClick={() => setSelectedDocId(doc.doc_id)}
                    className={`mb-0.5 flex w-full items-start gap-1.5 rounded-lg px-2.5 py-2 text-left text-xs transition ${isSel ? 'bg-blue-50 text-blue-700 ring-1 ring-blue-200' : 'text-slate-600 hover:bg-slate-50'}`}>
                    <FileText className={`mt-0.5 size-3.5 shrink-0 ${isSel ? 'text-blue-500' : 'text-slate-400'}`} />
                    <div className="flex-1 min-w-0">
                      <span className="line-clamp-2 block">{doc.title || doc.doc_id}</span>
                      {/* 需求4：待处理工作数徽章（排序已由后端 pending_count DESC + created_at DESC）*/}
                      {totalPending > 0 ? (
                        <span className="mt-1 inline-flex items-center gap-0.5 rounded bg-amber-50 px-1.5 py-0.5 text-[9px] font-medium text-amber-700 ring-1 ring-amber-200">
                          待处理 {totalPending}
                        </span>
                      ) : (
                        <span className="mt-1 inline-flex items-center gap-0.5 rounded bg-emerald-50 px-1.5 py-0.5 text-[9px] font-medium text-emerald-600 ring-1 ring-emerald-200">
                          已完成
                        </span>
                      )}
                    </div>
                  </button>
                )
              })
            )}
          </div>
          {coverage && (
            <div className="border-t border-slate-100 p-3">
              <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold text-slate-600">
                <Target className="size-3.5 text-blue-500" />单元统计
              </div>
              <div className="text-[11px] text-slate-600">
                共 <span className="font-semibold text-slate-800">{coverage.total}</span> 个单元
              </div>
              <div className="mt-1 text-[10px] text-slate-400">
                其中 <span className="text-emerald-600 font-medium">{coverage.covered}</span> 个已有提取记录
                {coverage.total - coverage.covered > 0 && <span>（{coverage.total - coverage.covered} 个尚无）</span>}
              </div>
            </div>
          )}
        </div>

        {/* ② 中框：文档树 */}
        <div className="lg:col-span-5 flex flex-col rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          <div className="border-b border-slate-100 px-3 py-2 flex items-center gap-2">
            <FileText className="size-3.5 text-slate-400" />
            <span className="text-xs font-semibold text-slate-600">文档全文</span>
            {/* 树/原文切换：固定在左侧（文档全文右边），位置不随模式变化 */}
            <div className="flex gap-0.5 rounded-md bg-slate-100 p-0.5">
              <button onClick={() => setViewMode('tree')}
                className={`flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-medium transition ${viewMode === 'tree' ? 'bg-white text-slate-700 shadow-sm ring-1 ring-slate-300' : 'text-slate-400 hover:text-slate-600'}`} title="树形结构视图">
                <ListTree className="size-3" />树
              </button>
              <button onClick={() => setViewMode('raw')}
                className={`flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-medium transition ${viewMode === 'raw' ? 'bg-white text-slate-700 shadow-sm ring-1 ring-slate-300' : 'text-slate-400 hover:text-slate-600'}`} title="原始全文视图">
                <AlignLeft className="size-3" />原文
              </button>
            </div>
            {/* 全展/全收：固定在右侧（仅树模式显示），不影响左侧切换组位置 */}
            <div className="ml-auto flex items-center gap-1">
              {viewMode === 'tree' && (<>
                <button onClick={expandAll} className="flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] text-slate-500 hover:bg-slate-100"><Plus className="size-3" />全展</button>
                <button onClick={collapseAll} className="flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] text-slate-500 hover:bg-slate-100"><Minus className="size-3" />全收</button>
              </>)}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {loadingDoc ? (
              <div className="flex justify-center py-12"><Loader2 className="size-5 animate-spin text-slate-400" /></div>
            ) : !derived ? (
              <div className="py-12 text-center text-xs text-slate-400">无全文</div>
            ) : viewMode === 'raw' ? (
              // 需求1：原文模式——展示文档全貌，不支持双向定位
              <pre className="whitespace-pre-wrap text-xs leading-relaxed text-slate-700">{structure?.content_text}</pre>
            ) : (
              <div className="flex flex-col gap-0.5">
                {(derived.root.children || []).map((node) => (
                  <TreeNode key={node.node_id} node={node} depth={0}
                    expanded={expanded} onToggle={toggleNode}
                    highlightedLeafId={highlightedLeafId} onSelectLeaf={clickLeaf}
                    leafRefs={leafRefs} />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ③ 右框：单元（叶子，文档顺序）+ 审核 */}
        <div className="lg:col-span-4 flex flex-col rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          <div className="border-b border-slate-100 px-3 py-2 flex items-center gap-2">
            <Lightbulb className="size-3.5 text-slate-400" />
            <span className="text-xs font-semibold text-slate-600">单元（{derived?.units.length ?? 0}）</span>
            {docTitle && <span className="truncate text-[10px] text-slate-400 min-w-0 shrink" title={docTitle}>· {docTitle}</span>}
            <Link href={`/policy-knowledge/knowledge?doc_id=${selectedDocId}&sub=audit`}
              className="ml-auto flex shrink-0 items-center gap-0.5 text-[10px] text-amber-600 hover:text-amber-700">
              知识库审核 <ChevronRight className="size-3" />
            </Link>
          </div>

          {!loadingDoc && derived && derived.units.length > 0 && (
            <div className="border-b border-slate-100 bg-slate-50/60 px-2.5 py-2 flex flex-col gap-1.5">
              <div className="flex items-center gap-2 text-[11px]">
                <label className="flex items-center gap-1 text-slate-600 cursor-pointer">
                  <input type="checkbox" checked={allVisibleChecked} onChange={toggleSelectAll} className="size-3" />全选
                </label>
                <span className="text-slate-400">已选 {selected.size}</span>
                {/* 需求11.2：两阶段统计——有待处理时显示「疑似重复+待审核+通过+已驳回」，全部处理后显示重复结果 */}
                <div className="flex items-center gap-1">
                  {stats.dup > 0 || stats.draft > 0 ? (
                    <>
                      <button onClick={() => setColFilter(colFilter === 'dup' ? 'all' : 'dup')} title="点击筛选疑似重复"
                        className={`rounded px-1.5 py-0.5 text-[10px] font-medium transition ${colFilter === 'dup' ? 'bg-orange-200 text-orange-800 ring-1 ring-orange-400' : 'bg-orange-50 text-orange-600 hover:bg-orange-100'}`}>
                        疑似重复 {stats.dup}
                      </button>
                      <button onClick={() => setColFilter(colFilter === 'draft' ? 'all' : 'draft')} title="点击筛选待审核（含无提取记录单元）"
                        className={`rounded px-1.5 py-0.5 text-[10px] font-medium transition ${colFilter === 'draft' ? 'bg-amber-200 text-amber-800 ring-1 ring-amber-400' : 'bg-amber-50 text-amber-600 hover:bg-amber-100'}`}>
                        待审核 {stats.draft}
                      </button>
                      {stats.merged > 0 && (
                        <button onClick={() => setColFilter(colFilter === 'merged' ? 'all' : 'merged')} title="点击筛选确认重复"
                          className={`rounded px-1.5 py-0.5 text-[10px] font-medium transition ${colFilter === 'merged' ? 'bg-slate-200 text-slate-800 ring-1 ring-slate-400' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>
                          重复 {stats.merged}
                        </button>
                      )}
                      {stats.reviewed > 0 && (
                        <button onClick={() => setColFilter(colFilter === 'reviewed' ? 'all' : 'reviewed')} title="点击筛选已通过"
                          className={`rounded px-1.5 py-0.5 text-[10px] font-medium transition ${colFilter === 'reviewed' ? 'bg-emerald-200 text-emerald-800 ring-1 ring-emerald-400' : 'bg-emerald-50 text-emerald-600 hover:bg-emerald-100'}`}>
                          通过 {stats.reviewed}
                        </button>
                      )}
                      {stats.rejected > 0 && (
                        <button onClick={() => setColFilter(colFilter === 'rejected' ? 'all' : 'rejected')} title="点击筛选已驳回"
                          className={`rounded px-1.5 py-0.5 text-[10px] font-medium transition ${colFilter === 'rejected' ? 'bg-red-200 text-red-800 ring-1 ring-red-400' : 'bg-red-50 text-red-600 hover:bg-red-100'}`}>
                          已驳回 {stats.rejected}
                        </button>
                      )}
                    </>
                  ) : (
                    <>
                      <button onClick={() => setColFilter(colFilter === 'merged' ? 'all' : 'merged')} title="点击筛选确认重复"
                        className={`rounded px-1.5 py-0.5 text-[10px] font-medium transition ${colFilter === 'merged' ? 'bg-slate-200 text-slate-800 ring-1 ring-slate-400' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>
                        重复 {stats.merged}
                      </button>
                      <button onClick={() => setColFilter(colFilter === 'reviewed' ? 'all' : 'reviewed')} title="点击筛选已通过"
                        className={`rounded px-1.5 py-0.5 text-[10px] font-medium transition ${colFilter === 'reviewed' ? 'bg-emerald-200 text-emerald-800 ring-1 ring-emerald-400' : 'bg-emerald-50 text-emerald-600 hover:bg-emerald-100'}`}>
                        通过 {stats.reviewed}
                      </button>
                      <button onClick={() => setColFilter(colFilter === 'rejected' ? 'all' : 'rejected')} title="点击筛选已驳回"
                        className={`rounded px-1.5 py-0.5 text-[10px] font-medium transition ${colFilter === 'rejected' ? 'bg-red-200 text-red-800 ring-1 ring-red-400' : 'bg-red-50 text-red-600 hover:bg-red-100'}`}>
                        已驳回 {stats.rejected}
                      </button>
                    </>
                  )}
                </div>
                <select value={colFilter} onChange={(e) => setColFilter(e.target.value as ColFilter)}
                  className="ml-auto rounded border border-slate-200 bg-white px-1.5 py-0.5 text-[10px] text-slate-600">
                  <option value="all">全部</option>
                  <option value="dup">疑似重复</option>
                  <option value="merged">确认重复</option>
                  <option value="unique">确认不重复</option>
                  <option value="draft">待审核</option>
                  <option value="reviewed">通过</option>
                  <option value="rejected">已驳回</option>
                </select>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <button onClick={() => batchAudit([...selected], 'approve')} disabled={!selected.size || !!busy}
                  className="flex items-center gap-1 rounded bg-amber-600 px-2 py-1 text-[10px] font-medium text-white hover:bg-amber-700 disabled:opacity-40">
                  {busy === 'batch' ? <Loader2 className="size-3 animate-spin" /> : <Check className="size-3" />}批量通过
                </button>
                <button onClick={() => selected.size && setBatchRejecting(true)} disabled={!selected.size || !!busy}
                  className="flex items-center gap-1 rounded border border-red-200 bg-white px-2 py-1 text-[10px] text-red-600 hover:bg-red-50 disabled:opacity-40">
                  <X className="size-3" />批量驳回
                </button>
                <button onClick={() => batchReextract([...selected])} disabled={!selected.size || !!busy}
                  className="flex items-center gap-1 rounded border border-slate-200 bg-white px-2 py-1 text-[10px] text-slate-600 hover:bg-slate-50 disabled:opacity-40">
                  <RefreshCw className="size-3" />批量重提取
                </button>
              </div>
              {batchRejecting && (
                <div className="flex items-center gap-1.5">
                  <input value={batchReason} onChange={(e) => setBatchReason(e.target.value)} placeholder="驳回原因（必填）"
                    className="flex-1 rounded border border-red-200 px-2 py-1 text-[11px] focus:border-red-400 focus:outline-none" />
                  <button onClick={() => batchReason.trim() ? batchAudit([...selected], 'reject', batchReason.trim()) : flash('请填驳回原因')}
                    className="rounded bg-red-600 px-2 py-1 text-[10px] font-medium text-white hover:bg-red-700">确认驳回</button>
                  <button onClick={() => { setBatchRejecting(false); setBatchReason('') }}
                    className="rounded border border-slate-200 px-2 py-1 text-[10px] text-slate-500">取消</button>
                </div>
              )}
            </div>
          )}

          <div className="flex-1 overflow-y-auto p-2">
            {loadingDoc ? (
              <div className="flex justify-center py-12"><Loader2 className="size-5 animate-spin text-slate-400" /></div>
            ) : visibleUnits.length === 0 ? (
              <div className="py-12 text-center text-xs text-slate-400">{!derived?.units.length ? '该文档暂无单元' : '当前筛选无单元'}</div>
            ) : (
              <div className="flex flex-col gap-1.5">
                {visibleUnits.map((u) => (
                  <UnitCard key={u.leaf.node_id}
                    unit={u}
                    ancestors={ancestorTexts(u.leaf, derived!.byId)}
                    dupTargetOrder={(() => { const tid = dupMerged.get(u.leaf.node_id); return tid ? derived!.unitByNodeId.get(tid)?.leaf.order_no : undefined })()}
                    unitAuditReason={unitAudit.get(u.leaf.node_id)?.reason}
                    checked={selected.has(u.leaf.node_id)}
                    isSel={selectedUnitKey === u.leaf.node_id}
                    orderNo={u.leaf.order_no}
                    busy={busy}
                    rejecting={rejectKey === u.leaf.node_id}
                    singleReason={singleReason}
                    onToggleSelect={() => toggleSelect(u.leaf.node_id)}
                    onClickBody={() => clickUnit(u.leaf.node_id)}
                    onApprove={() => batchAudit([u.leaf.node_id], 'approve')}
                    onStartReject={() => { setRejectKey(u.leaf.node_id); setSingleReason(u.exts.find((e) => e.extracted_fields?.audit_reason)?.extracted_fields?.audit_reason || '') }}
                    onCancelReject={() => { setRejectKey(null); setSingleReason('') }}
                    onConfirmReject={() => singleReason.trim() ? batchAudit([u.leaf.node_id], 'reject', singleReason.trim()) : flash('请填驳回原因')}
                    onSetSingleReason={setSingleReason}
                    onReextract={() => batchReextract([u.leaf.node_id])}
                    onExtractLeaf={() => triggerLeafExtract(u.leaf.text)}
                    onResolveDup={() => setDupModalKey(u.leaf.node_id)}
                    unitRef={(el) => { if (el) unitRefs.current.set(u.leaf.node_id, el); else unitRefs.current.delete(u.leaf.node_id) }} />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 需求3：疑似重复处理弹框 */}
      {dupModalUnit && (
        <DupResolveModal
          unit={dupModalUnit}
          ancestors={ancestorTexts(dupModalUnit.leaf, derived!.byId)}
          candidates={dupCandidates}
          byId={derived!.byId}
          dupNotDup={dupNotDup}
          dupMerged={dupMerged}
          onMarkDup={markCandidateDup}
          onMarkNotDup={markCandidateNotDup}
          onMergeToCandidate={(targetKey) => resolveDupMerge(dupModalUnit.leaf.node_id, targetKey)}
          onKeepCurrent={() => resolveDupKeep(dupModalUnit.leaf.node_id)}
          onClose={() => { setDupModalKey(null); fetchDocs() }}
        />
      )}
    </div>
  )
}
interface UnitCardProps {
  unit: UnitLeaf
  ancestors: ClauseNode[]
  dupTargetOrder?: number
  unitAuditReason?: string          // 需求11.1：无提取单元的驳回原因
  checked: boolean
  isSel: boolean
  orderNo: number
  busy: string
  rejecting: boolean
  singleReason: string
  onToggleSelect: () => void
  onClickBody: () => void
  onApprove: () => void
  onStartReject: () => void
  onCancelReject: () => void
  onConfirmReject: () => void
  onSetSingleReason: (v: string) => void
  onReextract: () => void
  onExtractLeaf: () => void
  onResolveDup: () => void
  unitRef: (el: HTMLDivElement | null) => void
}
function UnitCard(p: UnitCardProps) {
  const { unit, ancestors, dupTargetOrder } = p
  const leaf = unit.leaf
  const exts = unit.exts
  const hasExts = exts.length > 0
  // 需求11.1：无提取单元的状态标签区分——通过为「已通过」（无知识可发布），驳回为「已驳回」
  const lc = hasExts
    ? (UNIT_STATUS[unit.status] || { label: unit.status, cls: 'bg-slate-100 text-slate-600' })
    : (unit.status === 'reviewed' ? { label: '已通过', cls: 'bg-emerald-100 text-emerald-700' }
       : unit.status === 'rejected' ? { label: '已驳回', cls: 'bg-red-100 text-red-700' }
       : { label: '无提取记录', cls: 'bg-slate-100 text-slate-500' })
  const isBusy = p.busy === leaf.node_id
  const disabled = !!p.busy
  // 驳回原因：有提取从提取字段取，无提取用 unit_audit.reason
  const reasons = [
    ...exts.map((e) => e.extracted_fields?.audit_reason).filter(Boolean),
    ...(!hasExts && p.unitAuditReason ? [p.unitAuditReason] : []),
  ]

  return (
    <div ref={p.unitRef}
      className={`rounded-lg border p-2.5 transition-all ${p.isSel ? 'border-blue-300 bg-blue-50 ring-1 ring-blue-200' : 'border-slate-200 bg-white hover:border-slate-300'}`}>
      {/* 头部：勾选 + 顺序 + hash + 状态 + 标记 */}
      <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
        <input type="checkbox" checked={p.checked} onChange={p.onToggleSelect} className="size-3 shrink-0" onClick={(e) => e.stopPropagation()} />
        <span className="rounded bg-slate-700 px-1 py-0.5 text-[9px] font-bold text-white" title="文档顺序">#{p.orderNo}</span>
        <code className="rounded bg-slate-100 px-1 py-0.5 text-[9px] text-slate-400" title="内容指纹 hash">{unit.hash.slice(0, 6)}</code>
        <span className={`rounded px-1 py-0.5 text-[9px] font-medium ${lc.cls}`}>{lc.label}</span>
        {unit.isDup && (
          <button onClick={(e) => { e.stopPropagation(); p.onResolveDup() }}
            className="flex items-center gap-0.5 rounded bg-orange-50 px-1 py-0.5 text-[9px] font-medium text-orange-700 ring-1 ring-orange-200 hover:bg-orange-100" title="点击处理疑似重复">
            <CopyX className="size-2.5" />疑似重复·处理
          </button>
        )}
        {/* 需求3：标记为重复的单元不隐藏，仅显示重复标签 */}
        {dupTargetOrder !== undefined && (
          <span className="flex items-center gap-0.5 rounded bg-slate-100 px-1 py-0.5 text-[9px] font-medium text-slate-500" title="已标记为重复，保留显示">
            <CopyX className="size-2.5" />重复·#{dupTargetOrder}
          </span>
        )}
      </div>

      {/* 正文（点击联动定位中栏叶子）*/}
      <div onClick={p.onClickBody} className="cursor-pointer">
        {ancestors.length > 0 && (
          <div className="mb-1.5 rounded-md bg-slate-50/80 p-1.5">
            {ancestors.map((a, i) => (
              <p key={i} className="flex items-start gap-1 text-[10px] leading-relaxed text-slate-500">
                <span className="mt-0.5 shrink-0 rounded bg-white px-0.5 text-[8px] font-semibold text-slate-400 ring-1 ring-slate-200">{LEVEL_LABEL[a.level] || '节'}</span>
                <span className="whitespace-pre-wrap">{a.text}</span>
              </p>
            ))}
          </div>
        )}
        <p className="mb-1 whitespace-pre-wrap rounded-md bg-emerald-50/40 px-2 py-1 text-[11px] leading-relaxed text-slate-700">{leaf.text}</p>
        {reasons.length > 0 && (
          <p className="mb-1 rounded bg-red-50 px-2 py-1 text-[10px] text-red-600">驳回原因：{reasons[0]}{reasons.length > 1 ? ` 等${reasons.length}条` : ''}</p>
        )}
      </div>

      {/* 审核动作（需求11.1：所有单元均可通过/驳回；有提取另可重提取，无提取另可触发提取）*/}
      <div className="flex flex-wrap items-center gap-1.5 border-t border-slate-100 pt-1.5">
        {p.rejecting ? (
          <div className="flex w-full items-center gap-1.5">
            <input value={p.singleReason} onChange={(e) => p.onSetSingleReason(e.target.value)} placeholder="驳回原因（必填）"
              className="flex-1 rounded border border-red-200 px-2 py-1 text-[11px] focus:border-red-400 focus:outline-none" autoFocus />
            <button onClick={p.onConfirmReject} disabled={disabled}
              className="rounded bg-red-600 px-2 py-1 text-[10px] font-medium text-white hover:bg-red-700 disabled:opacity-40">确认</button>
            <button onClick={p.onCancelReject} className="rounded border border-slate-200 px-2 py-1 text-[10px] text-slate-500">取消</button>
          </div>
        ) : (
          <>
            {unit.status !== 'reviewed' && unit.status !== 'published' && (
              <button onClick={p.onApprove} disabled={disabled}
                className="flex items-center gap-1 rounded bg-amber-600 px-2 py-1 text-[10px] font-medium text-white hover:bg-amber-700 disabled:opacity-40">
                {isBusy ? <Loader2 className="size-3 animate-spin" /> : <Check className="size-3" />}通过
              </button>
            )}
            {unit.status !== 'published' && (
              <button onClick={p.onStartReject} disabled={disabled}
                className="flex items-center gap-1 rounded border border-red-200 px-2 py-1 text-[10px] text-red-600 hover:bg-red-50 disabled:opacity-40">
                <X className="size-3" />不通过
              </button>
            )}
            {hasExts ? (
              <button onClick={p.onReextract} disabled={disabled}
                className="ml-auto flex items-center gap-1 rounded border border-slate-200 bg-white px-2 py-1 text-[10px] text-slate-600 hover:bg-slate-50 disabled:opacity-40" title="调用 LLM 重新提取（需 MODEL_API_KEY）">
                {isBusy ? <Loader2 className="size-3 animate-spin" /> : <RefreshCw className="size-3" />}重提取
              </button>
            ) : (
              <button onClick={p.onExtractLeaf} disabled={disabled}
                className="ml-auto flex items-center gap-1 rounded border border-blue-200 bg-white px-2 py-1 text-[10px] text-blue-600 hover:bg-blue-50 disabled:opacity-40" title="调用 LLM 为此单元生成提取记录">
                {isBusy ? <Loader2 className="size-3 animate-spin" /> : <Sparkles className="size-3" />}触发提取
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ── 树节点（递归）──
interface TreeNodeProps {
  node: ClauseNode
  depth: number
  expanded: Set<string>
  onToggle: (id: string) => void
  highlightedLeafId: string | null
  onSelectLeaf: (id: string) => void
  leafRefs: React.MutableRefObject<Map<string, HTMLDivElement>>
}
function TreeNode(props: TreeNodeProps) {
  const { node, depth, expanded, onToggle, highlightedLeafId, onSelectLeaf, leafRefs } = props
  const isLeaf = !node.has_children || node.children.length === 0

  if (isLeaf) {
    const isHi = highlightedLeafId === node.node_id
    return (
      <div
        ref={(el) => { if (el) leafRefs.current.set(node.node_id, el); else leafRefs.current.delete(node.node_id) }}
        onClick={() => onSelectLeaf(node.node_id)}
        className={`rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs leading-relaxed text-slate-700 transition-all cursor-pointer hover:border-blue-300 hover:bg-blue-50/30 ${isHi ? 'ring-2 ring-blue-400' : ''}`}
        style={{ marginLeft: depth * 14 }}
        title="点击定位右侧单元">
        <div className="mb-0.5 flex items-center gap-1.5">
          <span className="rounded bg-slate-700 px-1 text-[9px] font-bold text-white">#{node.order_no}</span>
          <span className="rounded bg-slate-100 px-1 text-[9px] font-semibold text-slate-500">{LEVEL_LABEL[node.level] || '正文'}</span>
        </div>
        <p className="whitespace-pre-wrap">{node.text}</p>
      </div>
    )
  }

  const isOpen = expanded.has(node.node_id)
  const leafCount = subtreeLeafCount(node)
  return (
    <div style={{ marginLeft: depth * 14 }}>
      <button onClick={() => onToggle(node.node_id)}
        className="flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-left text-xs transition hover:bg-slate-50">
        {isOpen ? <ChevronDown className="size-3.5 shrink-0 text-slate-400" /> : <ChevronRight className="size-3.5 shrink-0 text-slate-400" />}
        <span className="rounded bg-slate-200/70 px-1 text-[9px] font-semibold text-slate-500">{LEVEL_LABEL[node.level] || '节'}</span>
        <span className="truncate font-medium text-slate-700">{node.title}</span>
        <span className="ml-auto shrink-0 text-[9px] text-slate-400">{leafCount} 叶</span>
      </button>
      {isOpen && (
        <div className="mt-0.5 flex flex-col gap-0.5">
          {node.children.map((c) => (
            <TreeNode key={c.node_id} node={c} depth={depth + 1}
              expanded={expanded} onToggle={onToggle}
              highlightedLeafId={highlightedLeafId} onSelectLeaf={onSelectLeaf}
              leafRefs={leafRefs} />
          ))}
        </div>
      )}
    </div>
  )
}

// ── 疑似重复处理弹框（需求1）──
// 批量处理所有候选：每个候选可选「是重复」/「不是重复」/「保留此候选」。
// 全部候选处理完后，本单元自动确认。不重复的仅保留结果，不显示标签。
interface DupResolveModalProps {
  unit: UnitLeaf
  ancestors: ClauseNode[]
  candidates: { unit: UnitLeaf; score: number }[]
  byId: Map<string, ClauseNode>
  dupNotDup: Map<string, Set<string>>
  dupMerged: Map<string, string>
  onMarkDup: (candidateKey: string) => void
  onMarkNotDup: (candidateKey: string) => void
  onMergeToCandidate: (candidateKey: string) => void
  onKeepCurrent: () => void
  onClose: () => void
}
function DupResolveModal(p: DupResolveModalProps) {
  const { unit, ancestors, candidates, byId, dupNotDup, dupMerged } = p
  const leaf = unit.leaf
  // 需求11.3：成对相对判定——当前单元与某候选的关系
  const relOf = (cid: string) => pairRel(leaf.node_id, cid, dupMerged, dupNotDup)
  // 当前单元是否已完全处理（被 merge 或所有候选均已判定）
  const currentResolved = dupMerged.has(leaf.node_id) || candidates.every((c) => relOf(c.unit.leaf.node_id) !== 'undecided')
  const candAncestors = (c: ClauseNode): ClauseNode[] => {
    const out: ClauseNode[] = []
    let cur = c.parent_id ? byId.get(c.parent_id) : null
    while (cur) { if (cur.level !== 'document') out.unshift(cur); cur = cur.parent_id ? byId.get(cur.parent_id) : null }
    return out
  }
  const unresolvedCount = candidates.filter((c) => relOf(c.unit.leaf.node_id) === 'undecided').length
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm p-4" onClick={p.onClose}>
      <div className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-slate-100 px-5 py-3">
          <CopyX className="size-4 text-orange-500" />
          <h3 className="text-sm font-semibold text-slate-800">疑似重复处理</h3>
          <span className="rounded bg-slate-700 px-1 py-0.5 text-[9px] font-bold text-white">#{leaf.order_no}</span>
          {currentResolved && <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[9px] font-medium text-emerald-700 ring-1 ring-emerald-200">已确认</span>}
          <button onClick={p.onClose} className="ml-auto text-slate-400 hover:text-slate-600 text-xl leading-none">×</button>
        </div>
        <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-4">
          <section>
            <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-slate-600">
              <span className="rounded bg-blue-50 px-1.5 py-0.5 text-blue-700 ring-1 ring-blue-200">当前单元</span>
              {currentResolved ? <span className="text-[10px] text-emerald-600">已确认（全部候选已处理）</span>
                : unresolvedCount > 0 ? <span className="text-[10px] text-slate-400">还有 {unresolvedCount} 个候选待处理</span>
                : <span className="text-[10px] text-emerald-600">候选全部处理完，本单元已自动确认</span>}
            </div>
            {ancestors.length > 0 && (
              <div className="mb-1 flex flex-wrap items-center gap-0.5 text-[10px] text-slate-400">
                {ancestors.map((a, i) => (<span key={i} className="flex items-center gap-0.5">{i > 0 && <ChevronRight className="size-2.5" />}<span className="truncate max-w-[200px]">{a.text}</span></span>))}
              </div>
            )}
            <p className="rounded-lg bg-emerald-50/40 px-3 py-2 text-xs leading-relaxed text-slate-700">{leaf.text}</p>
          </section>
          <section>
            <div className="mb-2 flex items-center gap-1.5 text-[11px] font-medium text-slate-600">
              <span className="rounded bg-orange-50 px-1.5 py-0.5 text-orange-700 ring-1 ring-orange-200">疑似重复候选</span>
              <span className="text-[10px] text-slate-400">{candidates.length} 条 · 是重复(留当前)/不是重复/留下相似单元(也是重复)</span>
            </div>
            {candidates.length === 0 ? (<p className="text-xs text-slate-400 py-4 text-center">无候选</p>) : (
              <div className="flex flex-col gap-2">
                {candidates.map(({ unit: cu, score }) => {
                  const cId = cu.leaf.node_id
                  // 需求11.3：成对相对判定——当前单元与此候选的关系
                  const rel = relOf(cId)              // 'dup' | 'not_dup' | 'undecided'
                  const pairDone = rel !== 'undecided'
                  // 需求11.4：候选已被别处标记为重复（指向非当前单元）→ 禁用「是重复」防覆盖
                  const candDupElsewhere = !!dupMerged.get(cId) && dupMerged.get(cId) !== leaf.node_id
                  const elsewhereOrder = candDupElsewhere ? byId.get(dupMerged.get(cId)!)?.order_no : undefined
                  const cas = candAncestors(cu.leaf)
                  return (
                    <div key={cId} className={"rounded-lg border p-2.5 " + (rel === 'dup' ? "border-slate-300 bg-slate-50" : rel === 'not_dup' ? "border-emerald-200 bg-emerald-50/30" : "border-slate-200")}>
                      <div className="mb-1 flex items-center gap-1.5">
                        <span className="rounded bg-slate-700 px-1 py-0.5 text-[9px] font-bold text-white">#{cu.leaf.order_no}</span>
                        <span className="rounded bg-orange-50 px-1.5 py-0.5 text-[9px] font-medium text-orange-700">相似度 {Math.round(score * 100)}%</span>
                        {rel === 'dup' && <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[9px] font-medium text-slate-600">✓ 重复</span>}
                        {rel === 'not_dup' && <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[9px] font-medium text-emerald-700">✓ 不重复</span>}
                      </div>
                      {cas.length > 0 && (
                        <div className="mb-1 flex flex-wrap items-center gap-0.5 text-[10px] text-slate-400">
                          {cas.map((a, i) => (<span key={i} className="flex items-center gap-0.5">{i > 0 && <ChevronRight className="size-2.5" />}<span className="truncate max-w-[180px]">{a.text}</span></span>))}
                        </div>
                      )}
                      <p className="mb-1.5 text-xs leading-relaxed text-slate-600">{cu.leaf.text}</p>
                      {!pairDone && (
                        <div className="flex flex-wrap items-center gap-1.5">
                          <button onClick={() => p.onMarkDup(cId)} disabled={candDupElsewhere} title={candDupElsewhere ? `候选已是 #${elsewhereOrder} 的重复，不能重复标记` : '候选是本单元的重复副本（保留当前）'} className="rounded bg-slate-700 px-2 py-1 text-[10px] font-medium text-white hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed">是重复</button>
                          <button onClick={() => p.onMarkNotDup(cId)} className="rounded border border-emerald-300 px-2 py-1 text-[10px] font-medium text-emerald-700 hover:bg-emerald-50" title="候选实为独立内容，不是重复">不是重复</button>
                          <button onClick={() => p.onMergeToCandidate(cId)} className="ml-auto rounded border border-blue-300 px-2 py-1 text-[10px] text-blue-600 hover:bg-blue-50" title="本单元是此候选的重复（留下相似单元，也属于重复关系）">留下相似单元</button>
                          {candDupElsewhere && <span className="text-[9px] text-slate-400">已是 #{elsewhereOrder} 的重复</span>}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </section>
        </div>
        <div className="flex items-center gap-2 border-t border-slate-100 px-5 py-3">
          <button onClick={p.onKeepCurrent} disabled={currentResolved} className="rounded bg-emerald-600 px-3 py-1.5 text-[11px] font-medium text-white hover:bg-emerald-700 disabled:opacity-40" title="本单元为独立内容">保留本单元</button>
          <button onClick={p.onClose} className="ml-auto rounded border border-slate-200 px-3 py-1.5 text-[11px] text-slate-500">关闭</button>
        </div>
      </div>
    </div>
  )
}
