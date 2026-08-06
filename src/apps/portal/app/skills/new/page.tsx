'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, ArrowRight, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react'
import { createSkillDraft, ApiClientError } from '@/lib/skill-draft-api'
import type { SkillDraftResponse } from '@/lib/types'

type Step = 0 | 1 | 2 | 3

const BUSINESS_ACTIONS = [
  'explain', 'query', 'guide', 'verify', 'compare', 'evaluate', 'analyze',
]
const BUSINESS_OBJECTS = [
  'settlement', 'insurance', 'order_fee', 'drg_dip', 'medical_record', 'audit_risk', 'appeal', 'patient',
]

const STEP_LABELS = ['基本信息', '业务挂载', '输入输出契约', '生成预览']

// /skills/new 模板向导四步（设计 §4.1）
export default function NewSkillWizardPage() {
  const router = useRouter()
  const [step, setStep] = useState<Step>(0)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [created, setCreated] = useState<SkillDraftResponse | null>(null)

  // Step 0: 基本信息
  const [skillId, setSkillId] = useState('')
  const [skillName, setSkillName] = useState('')
  const [description, setDescription] = useState('')
  const [owner, setOwner] = useState('')

  // Step 1: 业务挂载
  const [businessAction, setBusinessAction] = useState('explain')
  const [businessObject, setBusinessObject] = useState('settlement')
  const [keywords, setKeywords] = useState('')

  // Step 2: 输入输出契约
  const [inputMetrics, setInputMetrics] = useState('')
  const [inputSchema, setInputSchema] = useState('{\n  "type": "object",\n  "properties": {}\n}')
  const [outputSchema, setOutputSchema] = useState('{\n  "type": "object",\n  "properties": {}\n}')

  const canNext = (): boolean => {
    if (step === 0) return skillId.trim() !== '' && skillName.trim() !== ''
    return true
  }

  function next() {
    setError(null)
    if (step < 3) setStep((step + 1) as Step)
  }
  function prev() {
    setError(null)
    if (step > 0) setStep((step - 1) as Step)
  }

  async function submit() {
    setSubmitting(true)
    setError(null)
    try {
      const key = `create-skill-${Date.now()}`
      const draft = await createSkillDraft(
        {
          skill_id: skillId.trim(),
          skill_name: skillName.trim(),
          description: description.trim() || undefined,
          owner: owner.trim() || undefined,
          business_action: businessAction,
          business_object: businessObject,
        },
        key,
      )
      setCreated(draft)
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '创建草稿失败')
    } finally {
      setSubmitting(false)
    }
  }

  function buildPreview(): string {
    const kw = keywords.split(/[,，\s]+/).filter(Boolean)
    return [
      `# ${skillName || '(未命名)'}`,
      '',
      `**skill_id**: \`${skillId || '(待填)'}\``,
      `**负责人**: ${owner || '—'}`,
      '',
      '## 说明',
      description || '（暂无）',
      '',
      '## 业务挂载',
      `- BusinessAction: \`${businessAction}\``,
      `- BusinessObject: \`${businessObject}\``,
      `- 关键词: ${kw.length ? kw.join(', ') : '—'}`,
      '',
      '## 输入指标',
      inputMetrics.trim() || '（暂无）',
      '',
      '## skill_manifest.yaml',
      '```yaml',
      `skill_id: ${skillId || '...'}`,
      `skill_name: ${skillName || '...'}`,
      `business_action: ${businessAction}`,
      `business_object: ${businessObject}`,
      '```',
    ].join('\n')
  }

  if (created) {
    return (
      <div className="mt-10 mx-auto max-w-lg rounded-xl border border-green-200 bg-white p-8 text-center shadow-sm">
        <CheckCircle2 className="mx-auto h-12 w-12 text-green-600" />
        <h2 className="mt-4 text-xl font-semibold text-slate-900">草稿已创建</h2>
        <p className="mt-2 text-sm text-slate-600">
          草稿「{created.skill_name}」已创建，可进入编辑器继续完善输入指标契约与校验。
        </p>
        <div className="mt-6 flex justify-center gap-2">
          <button
            type="button"
            onClick={() => router.push('/skills/drafts')}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            返回草稿列表
          </button>
          <button
            type="button"
            onClick={() => router.push(`/skills/${encodeURIComponent(created.skill_id)}/edit?draft=${created.draft_id}`)}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            进入编辑器
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="mt-4 mx-auto max-w-3xl space-y-6">
      <header className="space-y-1">
        <h2 className="text-xl font-semibold tracking-tight text-slate-900">新建 Skill 向导</h2>
        <p className="text-sm text-slate-600">通过模板创建 Skill 草稿，完成后进入编辑器完善细节。</p>
      </header>

      {/* 步骤指示器 */}
      <div className="flex items-center gap-2">
        {STEP_LABELS.map((label, i) => (
          <div key={label} className="flex items-center gap-2">
            <div
              className={
                'flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold ' +
                (i === step ? 'bg-blue-600 text-white' : i < step ? 'bg-green-600 text-white' : 'bg-slate-200 text-slate-500')
              }
            >
              {i < step ? '✓' : i + 1}
            </div>
            <span className={i === step ? 'text-sm font-medium text-slate-900' : 'text-sm text-slate-500'}>{label}</span>
            {i < STEP_LABELS.length - 1 && <div className="h-px w-8 bg-slate-200" />}
          </div>
        ))}
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {/* 步骤内容 */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        {step === 0 && (
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-slate-800">第一步 · 基本信息</h3>
            <div>
              <label className="block text-sm font-medium text-slate-700">skill_id <span className="text-red-500">*</span></label>
              <input
                value={skillId}
                onChange={(e) => setSkillId(e.target.value)}
                placeholder="如 settlement_explain_skill"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
              <p className="mt-1 text-xs text-slate-500">全局唯一标识，创建后不可修改</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">名称 <span className="text-red-500">*</span></label>
              <input
                value={skillName}
                onChange={(e) => setSkillName(e.target.value)}
                placeholder="如 结算费用解释 Skill"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">说明</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                placeholder="简要描述该 Skill 的业务目标"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">负责人</label>
              <input
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
                placeholder="如 信息科-张三"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-slate-800">第二步 · 业务挂载</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-slate-700">BusinessAction</label>
                <select
                  value={businessAction}
                  onChange={(e) => setBusinessAction(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                >
                  {BUSINESS_ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700">BusinessObject</label>
                <select
                  value={businessObject}
                  onChange={(e) => setBusinessObject(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                >
                  {BUSINESS_OBJECTS.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">触发关键词（逗号分隔）</label>
              <input
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
                placeholder="如 结算,费用,自付"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-slate-800">第三步 · 输入输出契约</h3>
            <div>
              <label className="block text-sm font-medium text-slate-700">输入指标（metric_code，逗号分隔）</label>
              <input
                value={inputMetrics}
                onChange={(e) => setInputMetrics(e.target.value)}
                placeholder="如 zydyxx.bcqfje, policy.settlement_rule"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
              <p className="mt-1 text-xs text-slate-500">完整契约在编辑器中通过输入选择器配置</p>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-slate-700">输入 Schema (JSON)</label>
                <textarea
                  value={inputSchema}
                  onChange={(e) => setInputSchema(e.target.value)}
                  rows={5}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-xs focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700">输出 Schema (JSON)</label>
                <textarea
                  value={outputSchema}
                  onChange={(e) => setOutputSchema(e.target.value)}
                  rows={5}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-xs focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                />
              </div>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-slate-800">第四步 · 生成预览</h3>
            <pre className="max-h-96 overflow-auto rounded-lg bg-slate-900 p-4 text-xs text-slate-100">
              {buildPreview()}
            </pre>
            <p className="text-xs text-slate-500">
              创建草稿后，可在编辑器中完善输入指标契约、运行校验并物化发布。
            </p>
          </div>
        )}
      </div>

      {/* 导航按钮 */}
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={prev}
          disabled={step === 0 || submitting}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          <ArrowLeft className="h-4 w-4" />
          上一步
        </button>
        {step < 3 ? (
          <button
            type="button"
            onClick={next}
            disabled={!canNext()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            下一步
            <ArrowRight className="h-4 w-4" />
          </button>
        ) : (
          <button
            type="button"
            onClick={() => void submit()}
            disabled={submitting}
            className="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
            创建草稿
          </button>
        )}
      </div>
    </div>
  )
}
