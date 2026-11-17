'use client'

// 筛查规则管理 /rule-management 页 — issue #86 规则管理（管理入口）。
// 与运营问数入口分离：上传 → 逐条分类 → 候选规则（带原条款）→ 人批准 → 跑数 →
// 执行批次与两本名单（明显对不上 / 材料不足）。未批准规则不得跑数。
import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, ListChecks, Play, ShieldCheck, Upload, XCircle } from 'lucide-react'
import {
  approveRule,
  createRule,
  disableRule,
  hasRuleManagementPermission,
  listFindings,
  listRules,
  listRuns,
  startRun,
  updateRule,
  uploadChecklist,
  verifyFinding,
  type ChecklistItemDto,
  type FindingTypeDto,
  type RuleClassDto,
  type RuleStatusDto,
  type ScreeningFindingDto,
  type ScreeningRuleDto,
  type ScreeningRunDto,
  type VerifyStatusDto,
} from '@/lib/rule-management-api'
import { ApiClientError } from '@/lib/types'

const selectCls =
  'rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-slate-400 focus:outline-none'
const inputCls =
  'w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-slate-400 focus:outline-none'
const btnCls =
  'inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50'
const btnGhostCls =
  'inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-700 hover:border-slate-400 disabled:opacity-50'

const CLASS_LABELS: Record<RuleClassDto, string> = {
  executable: '可执行',
  needs_mapping: '差一层映射',
  not_executable: '目前执行不了',
}

const CLASS_BADGES: Record<RuleClassDto, string> = {
  executable: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  needs_mapping: 'border-amber-200 bg-amber-50 text-amber-700',
  not_executable: 'border-slate-200 bg-slate-100 text-slate-500',
}

const STATUS_LABELS: Record<RuleStatusDto, string> = {
  candidate: '候选',
  approved: '已批准',
  disabled: '已关闭',
}

const STATUS_BADGES: Record<RuleStatusDto, string> = {
  candidate: 'border-amber-200 bg-amber-50 text-amber-700',
  approved: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  disabled: 'border-slate-200 bg-slate-100 text-slate-500',
}

const RUN_STATUS_LABELS: Record<ScreeningRunDto['status'], string> = {
  running: '执行中',
  succeeded: '成功',
  failed: '失败',
}

const FINDING_TYPE_LABELS: Record<FindingTypeDto, string> = {
  mismatch: '明显对不上',
  insufficient_material: '材料不足',
}

const VERIFY_LABELS: Record<VerifyStatusDto, string> = {
  pending: '待核实',
  follow: '跟',
  not_follow: '不跟',
  insufficient: '材料不足',
}

type Tab = 'upload' | 'rules' | 'runs' | 'findings'

export default function RuleManagementPage() {
  const [tab, setTab] = useState<Tab>('rules')
  const [rules, setRules] = useState<ScreeningRuleDto[]>([])
  const [runs, setRuns] = useState<ScreeningRunDto[]>([])
  const [findings, setFindings] = useState<ScreeningFindingDto[]>([])
  const [findingType, setFindingType] = useState<FindingTypeDto>('mismatch')
  const [findingRunId, setFindingRunId] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // 上传面板
  const [sourceDoc, setSourceDoc] = useState('国家定点医疗机构违法违规使用医疗保障基金典型问题清单（2025版）')
  const [content, setContent] = useState('')
  const [classifiedItems, setClassifiedItems] = useState<ChecklistItemDto[]>([])

  // 规则编辑
  const [editingRuleId, setEditingRuleId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editCondition, setEditCondition] = useState('')

  // 手工录入（两库知识点等非「重复收取」句式条款）
  const [showManualCreate, setShowManualCreate] = useState(false)
  const [mcTitle, setMcTitle] = useState('')
  const [mcClause, setMcClause] = useState('')
  const [mcConditionText, setMcConditionText] = useState('')
  const [mcSourceDoc, setMcSourceDoc] = useState('国家医保智能监管“两库”规则和知识点')
  const [mcItemRef, setMcItemRef] = useState('')
  const [mcClass, setMcClass] = useState<RuleClassDto>('executable')
  const [mcSpec, setMcSpec] = useState('')
  const [mcGap, setMcGap] = useState('')

  // 跑数面板
  const [rangeStart, setRangeStart] = useState('')
  const [rangeEnd, setRangeEnd] = useState('')

  const canWrite = hasRuleManagementPermission('write')

  const showError = useCallback((exc: unknown) => {
    setNotice(null)
    setError(exc instanceof ApiClientError ? exc.message : String(exc))
  }, [])

  const refreshRules = useCallback(async () => {
    try {
      setRules(await listRules())
      setError(null)
    } catch (exc) {
      showError(exc)
    }
  }, [showError])

  const refreshRuns = useCallback(async () => {
    try {
      setRuns(await listRuns())
      setError(null)
    } catch (exc) {
      showError(exc)
    }
  }, [showError])

  const refreshFindings = useCallback(async () => {
    try {
      setFindings(
        await listFindings({
          finding_type: findingType,
          run_id: findingRunId || undefined,
        }),
      )
      setError(null)
    } catch (exc) {
      showError(exc)
    }
  }, [findingType, findingRunId, showError])

  useEffect(() => {
    refreshRules()
    refreshRuns()
  }, [refreshRules, refreshRuns])

  useEffect(() => {
    refreshFindings()
  }, [refreshFindings])

  const handleUpload = async () => {
    setLoading(true)
    try {
      const result = await uploadChecklist(sourceDoc, content)
      setClassifiedItems(result.items)
      setNotice(`已分类 ${result.items.length} 条，生成候选规则 ${result.candidate_rule_ids.length} 条`)
      setError(null)
      await refreshRules()
    } catch (exc) {
      showError(exc)
    } finally {
      setLoading(false)
    }
  }

  const handleApprove = async (ruleId: string) => {
    try {
      await approveRule(ruleId)
      setNotice('规则已批准，可以跑数')
      setError(null)
      await refreshRules()
    } catch (exc) {
      showError(exc)
    }
  }

  const handleDisable = async (ruleId: string) => {
    try {
      await disableRule(ruleId)
      setNotice('规则已关闭，不再进入后续执行批次')
      setError(null)
      await refreshRules()
    } catch (exc) {
      showError(exc)
    }
  }

  const handleSaveEdit = async () => {
    if (!editingRuleId) return
    try {
      await updateRule(editingRuleId, { title: editTitle, condition_text: editCondition })
      setNotice('规则已保存（已批准规则修改后需重新批准）')
      setEditingRuleId(null)
      setError(null)
      await refreshRules()
    } catch (exc) {
      showError(exc)
    }
  }

  const handleRun = async () => {
    if (!rangeStart || !rangeEnd) {
      setError('请选择时间范围')
      return
    }
    setLoading(true)
    try {
      const run = await startRun({
        time_range_start: `${rangeStart}T00:00:00`,
        time_range_end: `${rangeEnd}T23:59:59`,
      })
      setNotice(
        `批次 ${run.run_id} ${RUN_STATUS_LABELS[run.status]}：` +
          `明显对不上 ${run.finding_counts['mismatch'] ?? 0} 条，材料不足 ${run.finding_counts['insufficient_material'] ?? 0} 条`,
      )
      setError(null)
      await refreshRuns()
      await refreshFindings()
    } catch (exc) {
      showError(exc)
    } finally {
      setLoading(false)
    }
  }

  const handleVerify = async (findingId: string, status: VerifyStatusDto) => {
    try {
      await verifyFinding(findingId, status)
      await refreshFindings()
    } catch (exc) {
      showError(exc)
    }
  }

  const handleManualCreate = async () => {
    setLoading(true)
    try {
      let spec: Record<string, unknown> | null = null
      if (mcSpec.trim()) {
        spec = JSON.parse(mcSpec) as Record<string, unknown>
      }
      await createRule({
        source_doc: mcSourceDoc,
        source_clause: mcClause,
        title: mcTitle,
        condition_text: mcConditionText,
        rule_class: mcClass,
        condition_spec: spec,
        mapping_gap: mcGap.trim() || null,
        source_item_ref: mcItemRef.trim() || null,
      })
      setNotice('已录入候选规则（待批准后跑数）')
      setError(null)
      setShowManualCreate(false)
      setMcTitle(''); setMcClause(''); setMcConditionText(''); setMcSpec(''); setMcGap(''); setMcItemRef('')
      await refreshRules()
    } catch (exc) {
      showError(exc instanceof SyntaxError ? '条件 JSON 格式错误' : exc)
    } finally {
      setLoading(false)
    }
  }

  const tabs: Array<{ key: Tab; label: string }> = [
    { key: 'upload', label: '上传清单' },
    { key: 'rules', label: `规则（${rules.length}）` },
    { key: 'runs', label: `执行批次（${runs.length}）` },
    { key: 'findings', label: '疑点名单' },
  ]

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6">
      <header>
        <h1 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
          <ShieldCheck className="size-5" /> 筛查规则管理
        </h1>
        <p className="mt-1 text-xs text-slate-500">
          上传政策/问题清单 → 逐条分类 → 候选规则（带原条款）→ 人批准后跑数 → 查看执行批次与两本名单。
          命中只作为疑点，判定与整改留在医保办。
        </p>
      </header>

      <nav className="flex gap-1 border-b border-slate-200">
        {tabs.map((item) => (
          <button
            key={item.key}
            onClick={() => setTab(item.key)}
            className={`px-3 py-2 text-xs font-medium ${
              tab === item.key
                ? 'border-b-2 border-slate-900 text-slate-900'
                : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {error && (
        <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div>
      )}
      {notice && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">{notice}</div>
      )}

      {tab === 'upload' && (
        <section className="space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">清单名称</label>
            <input className={inputCls} value={sourceDoc} onChange={(e) => setSourceDoc(e.target.value)} />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">清单内容（每行一条）</label>
            <textarea
              className={`${inputCls} h-40 font-mono`}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="粘贴问题清单条目，每行一条，例如：开展甲状腺癌扩大根治术，重复收取甲状腺癌根治术和（或）淋巴结清扫术费用"
            />
          </div>
          <button className={btnCls} disabled={loading || !canWrite || !content.trim()} onClick={handleUpload}>
            <Upload className="size-3.5" /> 上传并分类
          </button>

          {classifiedItems.length > 0 && (
            <ul className="space-y-2">
              {classifiedItems.map((item) => (
                <li key={item.item_ref} className="rounded-md border border-slate-200 bg-white p-3">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-sm text-slate-800">
                      <span className="mr-2 font-mono text-xs text-slate-400">#{item.item_ref}</span>
                      {item.clause}
                    </p>
                    <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] ${CLASS_BADGES[item.rule_class]}`}>
                      {CLASS_LABELS[item.rule_class]}
                    </span>
                  </div>
                  {item.mapping_gap && (
                    <p className="mt-1 text-xs text-amber-700">缺口：{item.mapping_gap}</p>
                  )}
                  {item.candidate_rule_id && (
                    <p className="mt-1 text-xs text-emerald-700">
                      已生成候选规则 {item.candidate_rule_id}（带原条款），待批准后跑数
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {tab === 'rules' && (
        <section className="space-y-2">
          {canWrite && (
            <div className="rounded-md border border-slate-200 bg-white p-3">
              <button className={btnGhostCls} onClick={() => setShowManualCreate((v) => !v)}>
                {showManualCreate ? '收起' : '手工录入规则（两库知识点等）'}
              </button>
              {showManualCreate && (
                <div className="mt-3 space-y-2">
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="mb-1 block text-xs font-medium text-slate-600">规则标题</label>
                      <input className={inputCls} value={mcTitle} onChange={(e) => setMcTitle(e.target.value)} placeholder="注射用重组人凝血因子Ⅷ限儿童甲(A)型血友病；成人限出血时使用" />
                    </div>
                    <div>
                      <label className="mb-1 block text-xs font-medium text-slate-600">来源文件</label>
                      <input className={inputCls} value={mcSourceDoc} onChange={(e) => setMcSourceDoc(e.target.value)} />
                    </div>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-slate-600">原条款（必填，逐字引用）</label>
                    <textarea className={`${inputCls} h-16`} value={mcClause} onChange={(e) => setMcClause(e.target.value)} />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-slate-600">条件描述（人读）</label>
                    <input className={inputCls} value={mcConditionText} onChange={(e) => setMcConditionText(e.target.value)} placeholder="门诊使用该药时：儿童不受限；成人需诊断中同时出现甲型血友病与出血" />
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    <div>
                      <label className="mb-1 block text-xs font-medium text-slate-600">分类</label>
                      <select className={selectCls} value={mcClass} onChange={(e) => setMcClass(e.target.value as RuleClassDto)}>
                        <option value="executable">可执行</option>
                        <option value="needs_mapping">差一层映射</option>
                        <option value="not_executable">目前执行不了</option>
                      </select>
                    </div>
                    <div>
                      <label className="mb-1 block text-xs font-medium text-slate-600">清单条目号（可选）</label>
                      <input className={inputCls} value={mcItemRef} onChange={(e) => setMcItemRef(e.target.value)} placeholder="第十三批-序号64" />
                    </div>
                    <div>
                      <label className="mb-1 block text-xs font-medium text-slate-600">映射缺口（差一层映射时必填）</label>
                      <input className={inputCls} value={mcGap} onChange={(e) => setMcGap(e.target.value)} />
                    </div>
                  </div>
                  {mcClass === 'executable' && (
                    <div>
                      <label className="mb-1 block text-xs font-medium text-slate-600">结构化条件 condition_spec（JSON，可执行时必填）</label>
                      <textarea
                        className={`${inputCls} h-24 font-mono text-xs`}
                        value={mcSpec}
                        onChange={(e) => setMcSpec(e.target.value)}
                        placeholder='{"kind":"drug_age_indication","drug_name_contains":"凝血因子Ⅷ","diagnosis_contains":["血友病A","甲型血友病"],"child_max_age":18,"adult_requires_diagnosis_contains":["出血"]}'
                      />
                    </div>
                  )}
                  <button
                    className={btnCls}
                    disabled={loading || !mcTitle.trim() || !mcClause.trim() || !mcConditionText.trim() || (mcClass === 'executable' && !mcSpec.trim()) || (mcClass === 'needs_mapping' && !mcGap.trim())}
                    onClick={handleManualCreate}
                  >
                    录入候选规则
                  </button>
                </div>
              )}
            </div>
          )}
          {rules.length === 0 && <p className="text-sm text-slate-500">暂无规则，请先在「上传清单」页上传并分类。</p>}
          {rules.map((rule) => (
            <div key={rule.rule_id} className="rounded-md border border-slate-200 bg-white p-3">
              {editingRuleId === rule.rule_id ? (
                <div className="space-y-2">
                  <input className={inputCls} value={editTitle} onChange={(e) => setEditTitle(e.target.value)} />
                  <textarea
                    className={`${inputCls} h-20`}
                    value={editCondition}
                    onChange={(e) => setEditCondition(e.target.value)}
                  />
                  <div className="flex gap-2">
                    <button className={btnCls} onClick={handleSaveEdit}>保存</button>
                    <button className={btnGhostCls} onClick={() => setEditingRuleId(null)}>取消</button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-slate-900">{rule.title}</p>
                      <p className="mt-0.5 text-xs text-slate-500">{rule.condition_text}</p>
                    </div>
                    <div className="flex shrink-0 gap-1">
                      <span className={`rounded-full border px-2 py-0.5 text-[11px] ${CLASS_BADGES[rule.rule_class]}`}>
                        {CLASS_LABELS[rule.rule_class]}
                      </span>
                      <span className={`rounded-full border px-2 py-0.5 text-[11px] ${STATUS_BADGES[rule.status]}`}>
                        {STATUS_LABELS[rule.status]}
                      </span>
                    </div>
                  </div>
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs text-slate-500">原条款与来源</summary>
                    <p className="mt-1 rounded bg-slate-50 p-2 text-xs text-slate-700">{rule.source_clause}</p>
                    <p className="mt-1 text-[11px] text-slate-400">
                      来源：{rule.source_doc}
                      {rule.source_item_ref ? ` · 条目 #${rule.source_item_ref}` : ''}
                      {rule.approved_by ? ` · 批准人 ${rule.approved_by}` : ''}
                    </p>
                  </details>
                  {rule.mapping_gap && <p className="mt-1 text-xs text-amber-700">缺口：{rule.mapping_gap}</p>}
                  {canWrite && (
                    <div className="mt-2 flex gap-2">
                      {rule.status === 'candidate' && rule.rule_class === 'executable' && (
                        <button className={btnCls} onClick={() => handleApprove(rule.rule_id)}>
                          <CheckCircle2 className="size-3.5" /> 批准
                        </button>
                      )}
                      {rule.status !== 'disabled' && (
                        <button
                          className={btnGhostCls}
                          onClick={() => {
                            setEditingRuleId(rule.rule_id)
                            setEditTitle(rule.title)
                            setEditCondition(rule.condition_text)
                          }}
                        >
                          修改
                        </button>
                      )}
                      {rule.status !== 'disabled' && (
                        <button className={btnGhostCls} onClick={() => handleDisable(rule.rule_id)}>
                          <XCircle className="size-3.5" /> 关闭
                        </button>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          ))}
        </section>
      )}

      {tab === 'runs' && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-end gap-2 rounded-md border border-slate-200 bg-white p-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">开始</label>
              <input type="date" className={selectCls} value={rangeStart} onChange={(e) => setRangeStart(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">结束</label>
              <input type="date" className={selectCls} value={rangeEnd} onChange={(e) => setRangeEnd(e.target.value)} />
            </div>
            <button className={btnCls} disabled={loading || !canWrite} onClick={handleRun}>
              <Play className="size-3.5" /> 执行已批准规则
            </button>
            <p className="text-[11px] text-slate-400">仅执行已批准的可执行规则；未批准的规则会被拒绝。一次请选不超过 92 天的诊次。</p>
          </div>
          {runs.map((run) => (
            <div key={run.run_id} className="rounded-md border border-slate-200 bg-white p-3">
              <div className="flex items-center justify-between">
                <p className="font-mono text-xs text-slate-700">{run.run_id}</p>
                <span className="text-xs font-medium text-slate-700">{RUN_STATUS_LABELS[run.status]}</span>
              </div>
              <p className="mt-1 text-xs text-slate-500">
                {run.time_range_start.slice(0, 10)} ~ {run.time_range_end.slice(0, 10)} · 规则 {run.rule_ids.length} 条 ·
                明显对不上 {run.finding_counts['mismatch'] ?? 0} 条 · 材料不足 {run.finding_counts['insufficient_material'] ?? 0} 条 ·
                发起人 {run.created_by}
              </p>
              {run.error_message && <p className="mt-1 text-xs text-rose-600">{run.error_message}</p>}
              <button
                className={`${btnGhostCls} mt-2`}
                onClick={() => {
                  setFindingRunId(run.run_id)
                  setTab('findings')
                }}
              >
                <ListChecks className="size-3.5" /> 查看名单
              </button>
            </div>
          ))}
        </section>
      )}

      {tab === 'findings' && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <select className={selectCls} value={findingType} onChange={(e) => setFindingType(e.target.value as FindingTypeDto)}>
              <option value="mismatch">明显对不上</option>
              <option value="insufficient_material">材料不足</option>
            </select>
            {findingRunId && (
              <button className={btnGhostCls} onClick={() => setFindingRunId('')}>
                清除批次过滤（{findingRunId}）
              </button>
            )}
          </div>
          {findings.length === 0 && <p className="text-sm text-slate-500">该名单暂无疑点。</p>}
          {findings.map((finding) => (
            <div key={finding.finding_id} className="rounded-md border border-slate-200 bg-white p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-slate-900">
                    {finding.item_name ?? '（无项目名）'}
                    {finding.amount != null && <span className="ml-2 text-rose-600">¥{finding.amount.toFixed(2)}</span>}
                  </p>
                  <p className="mt-0.5 font-mono text-[11px] text-slate-400">
                    结算键 {finding.settlement_key} · 费用行 {finding.fee_line_id ?? '-'} ·{' '}
                    {finding.primary_finding_id === finding.finding_id ? '主疑点' : `关联主疑点 ${finding.primary_finding_id}`}
                  </p>
                </div>
                <span className="shrink-0 rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600">
                  {VERIFY_LABELS[finding.verify_status]}
                </span>
              </div>
              <details className="mt-2">
                <summary className="cursor-pointer text-xs text-slate-500">依据（原条款 + 对照事实）</summary>
                <p className="mt-1 rounded bg-slate-50 p-2 text-xs text-slate-700">{finding.evidence_clause}</p>
                <pre className="mt-1 overflow-x-auto rounded bg-slate-50 p-2 text-[11px] text-slate-600">
                  {JSON.stringify(finding.evidence_facts, null, 2)}
                </pre>
              </details>
              {canWrite && finding.verify_status === 'pending' && (
                <div className="mt-2 flex gap-2">
                  <button className={btnGhostCls} onClick={() => handleVerify(finding.finding_id, 'follow')}>跟</button>
                  <button className={btnGhostCls} onClick={() => handleVerify(finding.finding_id, 'not_follow')}>不跟</button>
                  <button className={btnGhostCls} onClick={() => handleVerify(finding.finding_id, 'insufficient')}>材料不足</button>
                </div>
              )}
            </div>
          ))}
        </section>
      )}
    </div>
  )
}
