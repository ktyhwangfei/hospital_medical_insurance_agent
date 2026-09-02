'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  createRuleGovernanceDraft,
  diagnoseRuleGovernance,
  type RuleGovernanceDecision,
  type RuleGovernanceDiagnosis,
  type RuleGovernanceIssue,
} from '@/lib/policy-knowledge-api'


const DECISION_LABELS: Record<RuleGovernanceDecision, string> = {
  repair_extraction: '修复抽取，不新增字段',
  add_and_bind: '新增政策指标并绑定数据库字段',
  add_policy_field: '新增政策专用字段',
  supplement_value_mapping: '补充值域或来源映射',
  needs_review: '证据不足，转人工判断',
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : '请求失败，请稍后重试'
}

function parseRuleIds(value: string): string[] {
  return [...new Set(value.split(/[，,；;\n]+/).map((item) => item.trim()).filter(Boolean))]
}

export function RuleGovernanceWizard() {
  const [releaseId, setReleaseId] = useState('')
  const [ruleInput, setRuleInput] = useState('')
  const [diagnosis, setDiagnosis] = useState<RuleGovernanceDiagnosis | null>(null)
  const [issueIndex, setIssueIndex] = useState(0)
  const [step, setStep] = useState<1 | 2 | 3>(1)
  const [decision, setDecision] = useState<RuleGovernanceDecision>('needs_review')
  const [reviewNote, setReviewNote] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [draftId, setDraftId] = useState('')
  const [showTechnical, setShowTechnical] = useState(false)

  const runDiagnosis = async (sourceRelease: string, ruleIds: string[]) => {
    if (!sourceRelease.trim() || ruleIds.length === 0) return
    setLoading(true)
    setError('')
    setDraftId('')
    try {
      const result = await diagnoseRuleGovernance(sourceRelease.trim(), ruleIds)
      setDiagnosis(result)
      setIssueIndex(0)
      setStep(1)
      setDecision(result.items[0]?.recommended_decision ?? 'needs_review')
      const params = new URLSearchParams(window.location.search)
      params.set('release_id', sourceRelease.trim())
      params.set('rule_ids', ruleIds.join(','))
      params.set('diagnosis_id', result.diagnosis_id)
      window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`)
      window.sessionStorage.setItem('rule-governance-input', JSON.stringify({
        releaseId: sourceRelease.trim(),
        ruleIds,
      }))
    } catch (reason) {
      setError(message(reason))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const sourceRelease = params.get('release_id') ?? ''
    const ruleIds = parseRuleIds(params.get('rule_ids') ?? params.get('rule_id') ?? '')
    if (sourceRelease && ruleIds.length) {
      setReleaseId(sourceRelease)
      setRuleInput(ruleIds.join('\n'))
      void runDiagnosis(sourceRelease, ruleIds)
      return
    }
    const saved = window.sessionStorage.getItem('rule-governance-input')
    if (!saved) return
    try {
      const input = JSON.parse(saved) as { releaseId?: string; ruleIds?: string[] }
      setReleaseId(input.releaseId ?? '')
      setRuleInput(input.ruleIds?.join('\n') ?? '')
    } catch {
      window.sessionStorage.removeItem('rule-governance-input')
    }
    // 深链只在首次挂载时解析，后续由页面操作更新 URL。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const issue: RuleGovernanceIssue | undefined = diagnosis?.items[issueIndex]

  const selectIssue = (index: number) => {
    setIssueIndex(index)
    setStep(1)
    setReviewNote('')
    setShowTechnical(false)
    setDecision(diagnosis?.items[index]?.recommended_decision ?? 'needs_review')
  }

  const createDraft = async () => {
    if (!diagnosis || !issue) return
    setLoading(true)
    setError('')
    try {
      const draft = await createRuleGovernanceDraft({
        release_id: diagnosis.release_id,
        rule_ids: issue.rule_ids,
        issue_id: issue.issue_id,
        decision,
        review_note: reviewNote.trim() || undefined,
      })
      setDraftId(draft.proposal_id)
    } catch (reason) {
      setError(message(reason))
    } finally {
      setLoading(false)
    }
  }

  if (!diagnosis && !loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>从异常规则开始结构治理</CardTitle>
          <p className="text-sm text-slate-600">请从规则追溯中的“发起结构治理”进入。也可以使用下面的高级方式定位规则。</p>
        </CardHeader>
        <CardContent>
          <details className="space-y-3 rounded-lg border border-slate-200 p-4">
            <summary className="cursor-pointer text-sm font-medium">高级方式：输入来源版本和规则 ID</summary>
            <div className="grid gap-3 pt-3 md:grid-cols-2">
              <label className="grid gap-1 text-xs text-slate-600">问题发生版本<Input aria-label="问题发生版本" value={releaseId} onChange={(event) => setReleaseId(event.target.value)} placeholder="REL_202608182" /></label>
              <label className="grid gap-1 text-xs text-slate-600">规则 ID<Input aria-label="规则 ID" value={ruleInput} onChange={(event) => setRuleInput(event.target.value)} placeholder="支持逗号、分号或换行" /></label>
            </div>
            <Button className="mt-3" type="button" disabled={!releaseId.trim() || parseRuleIds(ruleInput).length === 0} onClick={() => void runDiagnosis(releaseId, parseRuleIds(ruleInput))}>开始诊断</Button>
          </details>
          {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
        </CardContent>
      </Card>
    )
  }

  if (loading && !diagnosis) {
    return <p aria-live="polite" className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-600">正在还原政策规则与数据库证据…</p>
  }

  if (!diagnosis || !issue) return null

  if (draftId) {
    return (
      <Card className="border-emerald-200 bg-emerald-50/40">
        <CardHeader><CardTitle>治理草稿已生成</CardTitle></CardHeader>
        <CardContent className="space-y-4 text-sm">
          <div className="flex items-center gap-2"><Badge>未执行</Badge><span>历史版本和 Milvus collection 均未修改。</span></div>
          <p>{issue.proposed_changes}</p>
          <div className="flex flex-wrap gap-3">
            <Link className="text-blue-700 underline" href="/semantic-layer/proposals">查看治理草稿</Link>
            <Button type="button" variant="outline" onClick={() => { setDraftId(''); setStep(1) }}>查看下一条问题</Button>
          </div>
          <p className="text-xs text-slate-500">草稿 {draftId}</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-xl font-semibold text-slate-950">{issue.title}</h2>
            <p className="text-sm text-slate-600">问题发生版本：{diagnosis.release_id} · 历史版本保持不变</p>
          </div>
          <Badge variant="outline">{issueIndex + 1} / {diagnosis.items.length} 个问题</Badge>
        </div>
        {diagnosis.items.length > 1 && <div className="flex flex-wrap gap-2" aria-label="结构问题列表">{diagnosis.items.map((item, index) => (
          <Button key={item.issue_id} type="button" size="sm" variant={index === issueIndex ? 'default' : 'outline'} onClick={() => selectIssue(index)}>{item.title}</Button>
        ))}</div>}
        <ol className="grid grid-cols-3 gap-2 text-xs" aria-label="治理步骤">
          {['规则诊断', '数据库证据', '建模决策'].map((label, index) => <li key={label} className={`rounded-md px-3 py-2 text-center ${step === index + 1 ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-600'}`}>{index + 1}. {label}</li>)}
        </ol>
      </header>

      {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      {step === 1 && <Card>
        <CardHeader><CardTitle className="text-base">诊断结果</CardTitle></CardHeader>
        <CardContent className="space-y-4 text-sm">
          <p>{issue.problem}</p>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-lg bg-red-50 p-3"><p className="text-xs text-red-700">当前结构</p><p className="mt-1 font-medium">{issue.current_structure_summary}</p></div>
            <div className="rounded-lg bg-blue-50 p-3"><p className="text-xs text-blue-700">缺失业务概念</p><p className="mt-1 font-medium">{issue.missing_concept ?? '无需新增业务概念'}</p></div>
          </div>
          {diagnosis.rules.filter((rule) => issue.rule_ids.includes(rule.rule_id)).map((rule) => <blockquote key={rule.rule_id} className="border-l-2 border-slate-300 pl-3 text-slate-700">{rule.excerpt}</blockquote>)}
          <Button type="button" variant="ghost" onClick={() => setShowTechnical((value) => !value)}>{showTechnical ? '收起技术详情' : '查看技术详情'}</Button>
          {showTechnical && <p className="break-all rounded bg-slate-50 p-3 font-mono text-xs">{issue.rule_ids.join('、')}</p>}
          <div className="flex justify-end"><Button type="button" onClick={() => setStep(2)}>查看数据库证据</Button></div>
        </CardContent>
      </Card>}

      {step === 2 && <Card>
        <CardHeader><CardTitle className="text-base">bjyb 数据库证据</CardTitle><p className="text-xs text-slate-600">数据库证据只辅助结构建模，不覆盖政策原文。</p></CardHeader>
        <CardContent className="space-y-3">
          {issue.database_evidence.length === 0 && <p className="text-sm text-amber-700">当前没有可用数据库证据，仍可按政策原文修复抽取。</p>}
          {issue.database_evidence.map((item) => <div key={item.source_ref} className="space-y-2 rounded-lg border border-slate-200 p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2"><strong>{item.excerpt || '数据库字段'}</strong><Badge variant={item.evidence_grade === 'rejected' ? 'destructive' : 'outline'}>{item.evidence_grade === 'strong' ? '推荐' : item.evidence_grade === 'rejected' ? '排除' : '佐证'}</Badge></div>
            <code className="text-xs text-blue-700">{item.table_name}.{item.field_name}</code>
            {item.match_reasons?.map((reason) => <p key={reason} className="text-emerald-700">{reason}</p>)}
            {item.rejection_reasons?.map((reason) => <p key={reason} className="text-red-700">{reason}</p>)}
            {item.sample_values?.length ? <p className="text-xs text-amber-700">观测码值：{item.sample_values.join('、')}（业务释义需确认）</p> : null}
          </div>)}
          <div className="flex justify-between"><Button type="button" variant="outline" onClick={() => setStep(1)}>返回诊断</Button><Button type="button" onClick={() => setStep(3)}>查看建模建议</Button></div>
        </CardContent>
      </Card>}

      {step === 3 && <Card>
        <CardHeader><CardTitle className="text-base">建模建议</CardTitle></CardHeader>
        <CardContent className="space-y-4 text-sm">
          <div className="rounded-lg border border-blue-200 bg-blue-50 p-4"><p className="text-xs text-blue-700">系统推荐</p><p className="mt-1 font-medium">{DECISION_LABELS[issue.recommended_decision]}</p><p className="mt-2 text-slate-700">{issue.recommended_reason}</p></div>
          <div className="grid gap-3 md:grid-cols-2"><div className="rounded bg-slate-50 p-3"><p className="text-xs text-slate-500">当前结构</p><p>{issue.current_structure_summary}</p></div><div className="rounded bg-emerald-50 p-3"><p className="text-xs text-emerald-700">拟变更结构</p><p>{issue.proposed_changes}</p></div></div>
          <p className="font-medium text-amber-800">历史版本保持不变，本次只生成下一候选版本的治理草稿。</p>
          <label className="grid gap-1 text-xs text-slate-600">建模结论<select aria-label="建模结论" className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm" value={decision} onChange={(event) => setDecision(event.target.value as RuleGovernanceDecision)}>{Object.entries(DECISION_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          {decision !== issue.recommended_decision && <label className="grid gap-1 text-xs text-slate-600">改选原因<textarea aria-label="改选原因" className="min-h-20 rounded-md border border-slate-300 p-3 text-sm" value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} /></label>}
          <div className="flex justify-between"><Button type="button" variant="outline" onClick={() => setStep(2)}>返回证据</Button><Button type="button" disabled={loading || (decision !== issue.recommended_decision && !reviewNote.trim())} onClick={() => void createDraft()}>{loading ? '生成中…' : '确认并生成治理草稿'}</Button></div>
        </CardContent>
      </Card>}
    </div>
  )
}
