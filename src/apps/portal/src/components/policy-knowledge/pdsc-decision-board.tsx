'use client'

import { useCallback, useEffect, useState } from 'react'

import {
  activatePdscCluster,
  adjustPdscCluster,
  decidePdscCluster,
  getPdscDecisionPackage,
  listPdscClusters,
  mergePdscClusters,
  refreshPdscCluster,
  scanPdscSignals,
  splitPdscCluster,
  type PdscActivation,
  type PdscCluster,
  type PdscDecisionPackage,
} from '@/lib/policy-knowledge-api'

const STATUS_LABEL: Record<string, string> = {
  pending: '待验证',
  accepted: '已接受',
  policy_only_accepted: '政策专用',
  not_issue: '已归档',
}

const CROSS_KIND_LABEL: Record<string, string> = {
  supporting: '支持',
  extending: '扩展',
  temporal_variant: '时间变体',
  conflicting: '冲突',
  irrelevant: '无关',
}

const DB_VALUE_LABEL: Record<string, string> = {
  aligned: '已对齐',
  value_extension: '值域扩展',
  db_only: '数据库专用',
  undecidable: '不可判断',
}

function DecisionCard({
  cluster,
  onChanged,
}: {
  cluster: PdscCluster
  onChanged: () => Promise<void>
}) {
  const c = cluster
  const [open, setOpen] = useState(false)
  const [pkg, setPkg] = useState<PdscDecisionPackage | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [businessMetric, setBusinessMetric] = useState(c.business_metric_code ?? '')
  const [selectedCandidate, setSelectedCandidate] = useState(
    c.business_metric_code ?? pkg?.business_metric_candidates?.[0]?.metric_code ?? '',
  )
  const [selectedEvidence, setSelectedEvidence] = useState<string[]>([])
  const [activation, setActivation] = useState<PdscActivation | null>(null)

  const counts = c.cross_validation?.counts ?? {}
  const alignment = c.value_alignment
  // 区分摘要：同名字段的多条簇靠 政策值/证据/文档 数量区分
  const docCount = new Set(c.evidence.map((e) => e.doc_id).filter(Boolean)).size

  // 详情展开时按需加载完整决策包；簇更新后详情随之刷新；首选项随候选列表初始化
  useEffect(() => {
    if (!open) return
    if (pkg && pkg.cluster.updated_at === c.updated_at) return
    let cancelled = false
    getPdscDecisionPackage(c.cluster_id)
      .then((data) => {
        if (cancelled) return
        setPkg(data)
        setSelectedCandidate((prev) =>
          prev || c.business_metric_code
          || data.business_metric_candidates?.[0]?.metric_code || '',
        )
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : '加载决策包失败')
      })
    return () => { cancelled = true }
  }, [open, pkg, c.cluster_id, c.updated_at, c.business_metric_code])

  const handleAction = async (
    action: string,
    actionReason?: string,
    extra?: Record<string, unknown>,
  ) => {
    setBusy(true)
    setError(null)
    try {
      if (action === 'refresh') {
        await refreshPdscCluster(c.cluster_id)
      } else if (action === 'adjust') {
        await adjustPdscCluster(c.cluster_id, {
          reason: actionReason ?? '',
          business_metric_code: (extra?.business_metric_code as string) ?? undefined,
        })
      } else if (action === 'merge') {
        await mergePdscClusters(
          c.cluster_id, extra?.into_cluster_id as string, actionReason ?? '',
        )
      } else if (action === 'split') {
        await splitPdscCluster(c.cluster_id, extra?.source_refs as string[], actionReason ?? '')
      } else if (action === 'activate') {
        setActivation(null)
        setActivation(await activatePdscCluster(c.cluster_id))
      } else {
        await decidePdscCluster(
          c.cluster_id,
          action as Parameters<typeof decidePdscCluster>[1],
          actionReason,
        )
      }
      setSelectedEvidence([])
      await onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" aria-label={`决策卡 ${c.concept}`}>
      {/* 首屏：系统假设 + 治理价值分 */}
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold text-slate-900">
            {c.concept}
            <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs font-normal text-slate-600">
              {STATUS_LABEL[c.status] ?? c.status}
            </span>
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            语义角色 {c.semantic_role} · 类型 {c.semantic_type}
            {c.policy_value_signature.length > 0 &&
              ` · 政策值：${c.policy_value_signature.slice(0, 4).join('、')}${c.policy_value_signature.length > 4 ? ' 等' : ''}`}
            {` · ${c.evidence.length} 条证据 · ${docCount} 个文档`}
            {' · 机器观察，未经人工确认'}
          </p>
          {c.diagnosis && (
            <p className="mt-0.5 text-xs text-slate-600" aria-label="机器诊断">
              机器诊断：{c.diagnosis}
            </p>
          )}
        </div>
        {c.score && (
          <div className="shrink-0 text-right" aria-label="治理价值分">
            <div className="flex items-baseline gap-2">
              <span className="text-xs text-slate-500">治理价值分</span>
              <span className="text-lg font-semibold tabular-nums text-slate-900">{c.score.total.toFixed(2)}</span>
            </div>
            <p className="text-xs text-slate-500 tabular-nums">
              发现可信度 {c.score.credibility.toFixed(2)} · 落地支持 {c.score.landing_support.toFixed(2)} ·
              全政策影响 {c.score.policy_impact.toFixed(2)}
            </p>
          </div>
        )}
      </header>

      {/* 首屏：交叉验证摘要（只展示非零类；支持数恒可见——0 也是关键信号） */}
      {c.cross_validation && (
        <div aria-label="全政策交叉验证" className="flex flex-wrap items-center gap-1.5 text-xs">
          {Object.entries(counts)
            .filter(([kind, count]) => kind !== 'irrelevant' && (count > 0 || kind === 'supporting'))
            .map(([kind, count]) => (
            <span
              key={kind}
              className={`rounded px-1.5 py-0.5 ${
                kind === 'conflicting' && count > 0
                  ? 'bg-red-50 text-red-700'
                  : 'bg-slate-100 text-slate-600'
              }`}
            >
              {CROSS_KIND_LABEL[kind] ?? kind} {count}
            </span>
          ))}
          {c.cross_validation.blocked && (
            <span className="text-red-600">存在未解决冲突，不能一键批准</span>
          )}
          {c.cross_validation.error && (
            <span className="text-amber-600">{c.cross_validation.error}</span>
          )}
        </div>
      )}

      {/* 首屏：裁决动作（始终可见） */}
      {c.status === 'pending' ? (
        <div className="space-y-2 border-t border-slate-100 pt-3" aria-label="建模方案与裁决">
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="rounded bg-sky-600 px-3 py-1.5 text-sm text-white hover:bg-sky-700 disabled:opacity-50"
              disabled={busy}
              onClick={() => handleAction('accept_full_plan')}
            >
              接受完整方案
            </button>
            <button
              type="button"
              className="rounded border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              disabled={busy}
              onClick={() => handleAction('policy_only', '政策证据充分，无可靠业务字段')}
            >
              政策专用指标
            </button>
            <button
              type="button"
              className="rounded border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              disabled={busy}
              onClick={() => handleAction('insufficient_evidence', '保留待补证据')}
            >
              证据不足
            </button>
            <button
              type="button"
              className="rounded border border-red-200 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50"
              disabled={busy || !reason.trim()}
              onClick={() => handleAction('not_issue', reason)}
              title="驳回需填写理由"
            >
              不是问题（需理由）
            </button>
            <button
              type="button"
              className="rounded border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              disabled={busy}
              onClick={() => handleAction('refresh')}
            >
              重新验证
            </button>
          </div>
          <input
            aria-label="裁决理由"
            className="w-full rounded border border-slate-200 px-2 py-1 text-xs"
            placeholder="驳回/调整时必填理由；正常接受无需填写"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </div>
      ) : (
        <div className="space-y-2 border-t border-slate-100 pt-3" aria-label="激活流水线">
          <p className="text-xs text-slate-500">
            人工结论：{STATUS_LABEL[c.status]}
            {c.review_note && ` · ${c.review_note}`}
          </p>
          {(c.status === 'accepted' || c.status === 'policy_only_accepted') && (
            <div className="space-y-1">
              <button
                type="button"
                className="rounded bg-emerald-600 px-3 py-1.5 text-sm text-white hover:bg-emerald-700 disabled:opacity-50"
                disabled={busy}
                onClick={() => handleAction('activate')}
              >
                激活候选方案（重提取→编译→验证→发布）
              </button>
              {activation && (
                <div className="rounded border border-slate-100 bg-slate-50 p-2" aria-label="激活结果">
                  <p className={activation.status === 'succeeded'
                    ? 'text-xs text-emerald-700'
                    : activation.status === 'failed' ? 'text-xs text-red-600' : 'text-xs text-slate-500'}>
                    激活{activation.status === 'succeeded' ? '成功' : activation.status === 'failed' ? `失败（${activation.failed_step}）：${activation.error}` : '中'}
                  </p>
                  <ul className="mt-1 space-y-0.5">
                    {activation.steps.map((s) => (
                      <li key={s.step} className="text-[11px] text-slate-600">
                        {s.passed ? '✓' : '✗'} {s.step}：{s.detail || '—'}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}
      {error && <p className="text-xs text-red-600" role="alert">{error}</p>}

      {/* 详情：原文证据、指标建议、值域对齐、影响范围（默认收起） */}
      <details
        className="rounded-lg border border-slate-100 bg-slate-50/50 px-3 py-2"
        onToggle={(event) => setOpen(event.currentTarget.open)}
      >
        <summary className="cursor-pointer text-xs font-medium text-slate-600">
          详情（发现线索原文、指标建议、值域对齐、影响范围）
        </summary>
        <div className="space-y-4 pt-3">
          {!pkg && !error && <p className="text-xs text-slate-400">加载详情中…</p>}
          {pkg && (
            <>
              {/* 发现线索（客观异常原文） */}
              <div>
                <h3 className="text-sm font-medium text-slate-900">发现线索（为什么出现）</h3>
                <ul className="mt-1 space-y-1" aria-label="发现线索列表">
                  {c.evidence.map((e, i) => (
                    <li key={`${e.source_ref}-${i}`} className="flex items-start gap-2 rounded border border-slate-100 bg-slate-50 px-2 py-1.5 text-xs text-slate-700">
                      {c.status === 'pending' && c.evidence.length > 1 && (
                        <input
                          type="checkbox"
                          aria-label={`选择证据 ${e.source_ref}`}
                          className="mt-0.5"
                          checked={selectedEvidence.includes(e.source_ref)}
                          onChange={(event) =>
                            setSelectedEvidence((prev) =>
                              event.target.checked
                                ? [...prev, e.source_ref]
                                : prev.filter((ref) => ref !== e.source_ref),
                            )
                          }
                        />
                      )}
                      <span className="flex-1">
                        <span className="mr-1.5 rounded bg-white px-1 py-0.5 text-[10px] text-slate-500">
                          {e.evidence_kind === 'policy' ? '政策' : '数据库'}
                        </span>
                        {e.excerpt || `${e.table_name ?? ''}.${e.field_name ?? ''}`}
                        <span className="ml-2 text-slate-400">
                          {e.doc_id && `${e.doc_id}`}
                          {e.unit_id && ` / ${e.unit_id}`}
                        </span>
                        {/* 原文命中值 vs 提取落值：压缩/漏检主张可在卡片上直接核实 */}
                        {(e.sample_values.length > 0 || (e.extracted_values?.length ?? 0) > 0) && (
                          <span className="mt-1 block">
                            {e.sample_values.length > 0 && (
                              <span className="mr-2 rounded bg-sky-50 px-1 py-0.5 text-[10px] text-sky-700">
                                原文命中：{e.sample_values.slice(0, 6).join('、')}
                              </span>
                            )}
                            {(e.extracted_values?.length ?? 0) > 0 ? (
                              <span className="rounded bg-emerald-50 px-1 py-0.5 text-[10px] text-emerald-700">
                                提取落值：{e.extracted_values!.slice(0, 6).join('、')}
                              </span>
                            ) : (
                              <span className="rounded bg-red-50 px-1 py-0.5 text-[10px] text-red-600">
                                提取落值：空
                              </span>
                            )}
                          </span>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
                {selectedEvidence.length > 0 && selectedEvidence.length < c.evidence.length && (
                  <p className="mt-1 text-xs text-slate-500">
                    已选 {selectedEvidence.length} 条证据：
                    <button
                      type="button"
                      className="mx-1 rounded border border-slate-200 bg-white px-1.5 py-0.5 text-[10px] hover:bg-slate-50 disabled:opacity-50"
                      disabled={busy || !reason.trim()}
                      title="拆分需理由"
                      onClick={() => handleAction('split', reason, { source_refs: selectedEvidence })}
                    >
                      移出到新簇（拆分）
                    </button>
                  </p>
                )}
              </div>

              {/* 交叉验证扩展值 + 预计影响 */}
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div>
                  <h3 className="text-sm font-medium text-slate-900">全政策交叉验证明细</h3>
                  {pkg.value_domain_extension_values.length > 0 && (
                    <p className="mt-1 text-xs text-slate-500">
                      扩展值：{pkg.value_domain_extension_values.join('、')}
                    </p>
                  )}
                  {/* 支持证据出处：计数有源可查，而非无出处的数字 */}
                  {(() => {
                    const items = (c.cross_validation?.items ?? [])
                      .filter((it) => it.kind && it.kind !== 'irrelevant')
                      .slice(0, 6)
                    if (items.length === 0) {
                      return (
                        <p className="mt-1 text-xs text-slate-400">
                          无支持/扩展/冲突单元（无关项已折叠）
                        </p>
                      )
                    }
                    return (
                      <ul className="mt-1 space-y-1" aria-label="交叉验证证据出处">
                        {items.map((it, i) => {
                          const kind = it.kind ?? ''
                          return (
                          <li key={`${it.unit_id}-${i}`} className="rounded border border-slate-100 bg-white px-2 py-1 text-xs">
                            <span className={`mr-1.5 rounded px-1 py-0.5 text-[10px] ${
                              kind === 'conflicting' ? 'bg-red-50 text-red-700' : 'bg-sky-50 text-sky-700'
                            }`}>
                              {CROSS_KIND_LABEL[kind] ?? kind}
                            </span>
                            <span className="text-slate-600">
                              {it.doc_title || it.doc_id}
                              {it.unit_id && ` · ${it.unit_id}`}
                            </span>
                            {(it.found_values?.length ?? 0) > 0 && (
                              <span className="ml-1 text-slate-500">（命中：{(it.found_values ?? []).slice(0, 4).join('、')}）</span>
                            )}
                            {it.excerpt && (
                              <p className="mt-0.5 truncate text-slate-500" title={it.excerpt}>
                                {it.excerpt.slice(0, 80)}
                              </p>
                            )}
                          </li>
                          )
                        })}
                      </ul>
                    )
                  })()}
                  {c.suggested_merge_cluster_ids.length > 0 && (
                    <p className="mt-1 text-xs text-slate-500">
                      建议合并的近似发现：
                      {c.suggested_merge_cluster_ids.map((id) => (
                        <button
                          key={id}
                          type="button"
                          className="mx-1 rounded border border-slate-200 bg-white px-1.5 py-0.5 font-mono text-[10px] hover:bg-slate-50 disabled:opacity-50"
                          disabled={busy || !reason.trim()}
                          onClick={() => handleAction('merge', reason, { into_cluster_id: id })}
                        >
                          合并 {id}
                        </button>
                      ))}
                    </p>
                  )}
                </div>
                <div aria-label="影响范围">
                  <h3 className="text-sm font-medium text-slate-900">预计影响</h3>
                  <p className="mt-1 text-xs text-slate-600">
                    政策单元 {pkg.affected_unit_ids.length} · 规范规则 {pkg.affected_rule_ids.length} ·
                    Skill 依赖 {pkg.affected_skill_usage}
                  </p>
                </div>
              </div>

              {/* 政策指标建议 + 业务对象指标 */}
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div aria-label="政策指标建议">
                  <h3 className="text-sm font-medium text-slate-900">政策指标（Milvus 字段）</h3>
                  <p className="mt-1 font-mono text-xs text-slate-700">
                    {pkg.recommended_policy_metric_code ?? '待系统建议（调整方案后生成）'}
                  </p>
                </div>
                <div aria-label="业务对象指标">
                  <h3 className="text-sm font-medium text-slate-900">业务对象指标（领域对象取数）</h3>
                  {c.status === 'pending' ? (
                    pkg.business_metric_candidates?.length ? (
                      <div className="mt-1 space-y-1" role="radiogroup" aria-label="候选业务指标">
                        {pkg.business_metric_candidates.map((cand) => (
                          <label
                            key={cand.metric_code}
                            className="flex cursor-pointer items-start gap-1.5 rounded border border-slate-200 bg-white px-2 py-1"
                          >
                            <input
                              type="radio"
                              name={`cand-${c.cluster_id}`}
                              className="mt-0.5"
                              checked={selectedCandidate === cand.metric_code}
                              onChange={() => setSelectedCandidate(cand.metric_code)}
                            />
                            <span className="min-w-0">
                              <span className="font-mono text-xs text-slate-700">{cand.metric_code}</span>
                              <span className="ml-1 text-xs text-slate-600">{cand.name}</span>
                              {cand.status !== 'published' && (
                                <span className="ml-1 rounded bg-slate-100 px-1 text-[10px] text-slate-500">{cand.status}</span>
                              )}
                              {cand.match_reasons.length > 0 && (
                                <span className="ml-1 text-[10px] text-emerald-700">
                                  {cand.match_reasons.join(' · ')}
                                </span>
                              )}
                            </span>
                          </label>
                        ))}
                        <button
                          type="button"
                          className="mt-1 rounded border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                          disabled={busy || !selectedCandidate}
                          onClick={() =>
                            handleAction('adjust', '绑定业务指标', {
                              business_metric_code: selectedCandidate,
                            })
                          }
                        >
                          绑定
                        </button>
                      </div>
                    ) : (
                      <div className="mt-1 flex gap-1.5">
                        <input
                          aria-label="业务指标编码"
                          className="w-full rounded border border-slate-200 bg-white px-2 py-1 font-mono text-xs"
                          placeholder="如 djxx.hosp_type"
                          value={businessMetric}
                          onChange={(event) => setBusinessMetric(event.target.value)}
                        />
                        <button
                          type="button"
                          className="shrink-0 rounded border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                          disabled={busy || !businessMetric.trim()}
                          onClick={() =>
                            handleAction('adjust', '绑定业务指标', {
                              business_metric_code: businessMetric.trim(),
                            })
                          }
                        >
                          绑定
                        </button>
                      </div>
                    )
                  ) : (
                    <p className="mt-1 font-mono text-xs text-slate-700">
                      {pkg.recommended_business_metric_code ?? '未绑定（政策专用）'}
                    </p>
                  )}
                </div>
              </div>

              {/* 业务字段库画像：摆事实（单值/无释义直接影响落地与对齐判断） */}
              {pkg.business_field_profile && (() => {
                const p = pkg.business_field_profile
                return (
                  <div aria-label="业务字段画像" className="rounded border border-slate-100 bg-white px-2 py-1.5 text-xs text-slate-600">
                    <span className="font-medium text-slate-700">业务字段画像</span>
                    <span className="ml-2">{p.table_name}.{p.field_name}</span>
                    <span className="ml-2 tabular-nums">
                      非空率 {p.non_null_rate !== null ? `${Math.round(p.non_null_rate)}%` : '—'}
                      · distinct {p.distinct_count ?? '—'}
                      · 样本值 {p.sample_values.slice(0, 5).join('、') || '—'}
                    </span>
                    {!p.has_description && (
                      <p className="mt-0.5 text-amber-600">库值无中文释义，值域对齐不可计算（不伪造分数）</p>
                    )}
                    {p.distinct_count !== null && p.distinct_count <= 1 && (
                      <p className="mt-0.5 text-red-600">业务字段单一取值，绑定暂不计落地支持</p>
                    )}
                  </div>
                )
              })()}

              {/* 值域对齐 */}
              {alignment && (
                <div aria-label="值域对齐">
                  <h3 className="text-sm font-medium text-slate-900">
                    值域对齐
                    {alignment.alignment_score !== null ? (
                      <span className="ml-2 text-xs font-normal text-slate-500 tabular-nums">
                        对齐度 {alignment.alignment_score.toFixed(2)}（全政策覆盖{' '}
                        {alignment.policy_coverage_rate !== null
                          ? `${Math.round(alignment.policy_coverage_rate * 100)}%`
                          : '—'}
                        ，库值释义{' '}
                        {alignment.db_definition_rate !== null
                          ? `${Math.round(alignment.db_definition_rate * 100)}%`
                          : '—'}
                        ）
                      </span>
                    ) : (
                      <span className="ml-2 text-xs font-normal text-amber-600">对齐度不可计算</span>
                    )}
                  </h3>
                  <div className="mt-1 flex flex-wrap gap-1 text-xs">
                    {alignment.full_policy_values.map((v) => (
                      <span key={`p-${v}`} className="rounded bg-sky-50 px-1.5 py-0.5 text-sky-700">{v}</span>
                    ))}
                    {alignment.database_values.map((d) => (
                      <span
                        key={`d-${d.value}`}
                        className={`rounded px-1.5 py-0.5 ${
                          d.classification === 'undecidable' || d.classification === 'db_only'
                            ? 'bg-amber-50 text-amber-700'
                            : 'bg-slate-100 text-slate-600'
                        }`}
                        title={d.definition ?? '无释义'}
                      >
                        {d.value}
                        {d.classification && `（${DB_VALUE_LABEL[d.classification] ?? d.classification}）`}
                      </span>
                    ))}
                  </div>
                  {alignment.notes.map((note) => (
                    <p key={note} className="mt-1 text-xs text-amber-600">{note}</p>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </details>
    </section>
  )
}

type StatusTab = 'pending' | 'decided' | 'archived'

const TAB_LABEL: Record<StatusTab, string> = {
  pending: '待验证',
  decided: '已裁决',
  archived: '已归档',
}

function statusGroup(status: PdscCluster['status']): StatusTab {
  if (status === 'pending') return 'pending'
  if (status === 'not_issue') return 'archived'
  return 'decided'
}

export function PdscDecisionBoard() {
  const [clusters, setClusters] = useState<PdscCluster[]>([])
  const [statusTab, setStatusTab] = useState<StatusTab>('pending')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [scanReport, setScanReport] = useState<string | null>(null)

  const loadClusters = useCallback(async () => {
    try {
      setClusters(await listPdscClusters())
      setLoadError(null)
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : '加载发现列表失败')
    }
  }, [])

  useEffect(() => {
    void loadClusters()
  }, [loadClusters])

  const handleScan = async () => {
    setBusy(true)
    setError(null)
    try {
      const report = await scanPdscSignals()
      setScanReport(
        `扫描 ${report.scanned_extractions} 条提取，新增 ${report.intaked_clusters} 簇；` +
        report.detectors.map((d) => `${d.detector} ${d.signals}`).join('、'),
      )
      await loadClusters()
    } catch (err) {
      setError(err instanceof Error ? err.message : '扫描失败')
    } finally {
      setBusy(false)
    }
  }

  if (loadError) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-red-600">
        {loadError}
      </div>
    )
  }

  // 一发现一卡片，治理价值分倒序（设计 §9.1：同分时冲突更多者优先）
  const sorted = [...clusters].sort((a, b) => {
    const diff = (b.score?.total ?? 0) - (a.score?.total ?? 0)
    if (diff !== 0) return diff
    return (b.cross_validation?.counts.conflicting ?? 0)
      - (a.cross_validation?.counts.conflicting ?? 0)
  })
  // 状态分组：默认只看待验证，已归档不再堆积在首屏
  const visible = sorted.filter((c) => statusGroup(c.status) === statusTab)
  const counts: Record<StatusTab, number> = { pending: 0, decided: 0, archived: 0 }
  for (const c of clusters) counts[statusGroup(c.status)] += 1

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="rounded border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          disabled={busy}
          onClick={handleScan}
        >
          扫描发现信号
        </button>
        {scanReport && <p className="text-xs text-slate-500">{scanReport}</p>}
        {error && <p className="text-xs text-red-600" role="alert">{error}</p>}
      </div>
      <div className="flex gap-1" role="tablist" aria-label="发现状态筛选">
        {(Object.keys(TAB_LABEL) as StatusTab[]).map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={statusTab === tab}
            className={`rounded px-2.5 py-1 text-xs ${
              statusTab === tab
                ? 'bg-sky-600 text-white'
                : 'border border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
            }`}
            onClick={() => setStatusTab(tab)}
          >
            {TAB_LABEL[tab]}（{counts[tab]}）
          </button>
        ))}
      </div>
      {visible.length === 0 && (
        <p className="text-sm text-slate-500">暂无{TAB_LABEL[statusTab]}的语义发现。</p>
      )}
      {visible.length > 0 && (
        <p className="text-xs text-slate-400">
          共 {visible.length} 条{TAB_LABEL[statusTab]}发现，按治理价值分降序排列。
        </p>
      )}
      <div className="space-y-3" aria-label="语义发现列表">
        {visible.map((c) => (
          <DecisionCard key={c.cluster_id} cluster={c} onChanged={loadClusters} />
        ))}
      </div>
    </div>
  )
}
