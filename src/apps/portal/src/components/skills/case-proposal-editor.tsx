'use client'

import { useEffect, useMemo, useState } from 'react'

import { Input } from '@/components/ui/input'

interface CaseProposalEditorProps {
  /** 当前（可被人工覆盖的）错误维度 */
  dimension: string
  /** 来自 AI 转换的初始 proposal（判别联合，按 case_type 分派） */
  proposal: Record<string, unknown> | null
  onChange: (dimension: string, proposal: Record<string, unknown>) => void
}

/**
 * 分型 proposal 编辑器：使用服务端判别联合，按维度只渲染对应字段，
 * 不使用任意 JSON 编辑器。other 只允许重新分型或拒绝（无可执行字段）。
 */
export default function CaseProposalEditor({
  dimension,
  proposal,
  onChange,
}: CaseProposalEditorProps) {
  const [draft, setDraft] = useState<Record<string, unknown>>(proposal ?? {})

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 同步外部 proposal 到本地草稿
    setDraft(proposal ?? {})
  }, [proposal])

  const assertions = useMemo<Record<string, unknown>>(
    () => (draft.assertions as Record<string, unknown>) ?? {},
    [draft],
  )

  function emit(next: Record<string, unknown>) {
    setDraft(next)
    onChange(dimension, next)
  }

  function setAssertion(key: string, value: unknown) {
    emit({ ...draft, assertions: { ...assertions, [key]: value } })
  }

  function setTop(key: string, value: unknown) {
    emit({ ...draft, [key]: value })
  }

  if (dimension === 'other') {
    return (
      <div
        data-testid="proposal-other-notice"
        className="rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800"
      >
        该案例尚无法自动分型。请重新选择错误维度后再次转换，或直接拒绝该案例。
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {dimension === 'routing' ? (
        <RoutingFields draft={draft} setTop={setTop} />
      ) : (
        <>
          <Field label="目标 Skill ID" testId="target_skill_id">
            <Input
              value={String(draft.target_skill_id ?? '')}
              onChange={(e) => setTop('target_skill_id', e.target.value)}
            />
          </Field>
          {dimension === 'calculation' ? (
            <CalculationFields assertions={assertions} setAssertion={setAssertion} />
          ) : null}
          {dimension === 'policy_content' ? (
            <PolicyContentFields assertions={assertions} setAssertion={setAssertion} />
          ) : null}
          {dimension === 'citation' ? (
            <CitationFields assertions={assertions} setAssertion={setAssertion} />
          ) : null}
          {dimension === 'answer_quality' ? (
            <AnswerQualityFields assertions={assertions} setAssertion={setAssertion} />
          ) : null}
          {dimension === 'safety' ? (
            <SafetyFields assertions={assertions} setAssertion={setAssertion} />
          ) : null}
        </>
      )}
    </div>
  )
}

function Field({
  label,
  testId,
  children,
}: {
  label: string
  testId: string
  children: React.ReactNode
}) {
  return (
    <div data-testid={`proposal-field-${testId}`} className="space-y-1">
      <label className="text-xs text-slate-600">{label}</label>
      {children}
    </div>
  )
}

function RoutingFields({
  draft,
  setTop,
}: {
  draft: Record<string, unknown>
  setTop: (k: string, v: unknown) => void
}) {
  return (
    <>
      <Field label="问题模板" testId="question_template">
        <Input
          value={String(draft.question_template ?? '')}
          onChange={(e) => setTop('question_template', e.target.value)}
        />
      </Field>
      <Field label="期望命中 Skill" testId="expected_skill_id">
        <Input
          value={String(draft.expected_skill_id ?? '')}
          onChange={(e) => setTop('expected_skill_id', e.target.value)}
        />
      </Field>
    </>
  )
}

function CalculationFields({
  assertions,
  setAssertion,
}: {
  assertions: Record<string, unknown>
  setAssertion: (k: string, v: unknown) => void
}) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <Field label="期望值" testId="expected_value">
        <Input
          type="number"
          value={String(assertions.expected_value ?? '')}
          onChange={(e) =>
            setAssertion('expected_value', e.target.value === '' ? '' : Number(e.target.value))
          }
        />
      </Field>
      <Field label="容差" testId="tolerance">
        <Input
          type="number"
          value={String(assertions.tolerance ?? '')}
          onChange={(e) =>
            setAssertion('tolerance', e.target.value === '' ? '' : Number(e.target.value))
          }
        />
      </Field>
      <Field label="进位小数位" testId="rounding">
        <Input
          type="number"
          value={String(assertions.rounding ?? '')}
          onChange={(e) =>
            setAssertion('rounding', e.target.value === '' ? '' : Number(e.target.value))
          }
        />
      </Field>
      <Field label="必含步骤（逗号分隔）" testId="must_include_steps">
        <Input
          value={Array.isArray(assertions.must_include_steps)
            ? (assertions.must_include_steps as string[]).join(',')
            : ''}
          onChange={(e) =>
            setAssertion(
              'must_include_steps',
              e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
            )
          }
        />
      </Field>
    </div>
  )
}

function PolicyContentFields({
  assertions,
  setAssertion,
}: {
  assertions: Record<string, unknown>
  setAssertion: (k: string, v: unknown) => void
}) {
  return (
    <div className="space-y-3">
      <Field label="适用性" testId="applicability">
        <select
          className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-sm"
          value={String(assertions.applicability ?? 'applies')}
          onChange={(e) => setAssertion('applicability', e.target.value)}
        >
          <option value="applies">适用</option>
          <option value="does_not_apply">不适用</option>
        </select>
      </Field>
      <Field label="必含内容（逗号分隔）" testId="must_include">
        <Input
          value={Array.isArray(assertions.must_include)
            ? (assertions.must_include as string[]).join(',')
            : ''}
          onChange={(e) =>
            setAssertion('must_include', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))
          }
        />
      </Field>
      <Field label="禁止内容（逗号分隔）" testId="forbidden">
        <Input
          value={Array.isArray(assertions.forbidden)
            ? (assertions.forbidden as string[]).join(',')
            : ''}
          onChange={(e) =>
            setAssertion('forbidden', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))
          }
        />
      </Field>
      <Field label="政策版本" testId="policy_version">
        <Input
          value={String(assertions.policy_version ?? '')}
          onChange={(e) => setAssertion('policy_version', e.target.value || null)}
        />
      </Field>
    </div>
  )
}

function CitationFields({
  assertions,
  setAssertion,
}: {
  assertions: Record<string, unknown>
  setAssertion: (k: string, v: unknown) => void
}) {
  return (
    <div className="space-y-3">
      <Field label="必含来源 ID（逗号分隔）" testId="required_source_ids">
        <Input
          value={Array.isArray(assertions.required_source_ids)
            ? (assertions.required_source_ids as string[]).join(',')
            : ''}
          onChange={(e) =>
            setAssertion(
              'required_source_ids',
              e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
            )
          }
        />
      </Field>
      <Field label="是否强制支撑" testId="support_required">
        <select
          className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-sm"
          value={String(assertions.support_required ?? 'required')}
          onChange={(e) => setAssertion('support_required', e.target.value)}
        >
          <option value="required">必须支撑</option>
          <option value="optional">可选</option>
        </select>
      </Field>
    </div>
  )
}

function AnswerQualityFields({
  assertions,
  setAssertion,
}: {
  assertions: Record<string, unknown>
  setAssertion: (k: string, v: unknown) => void
}) {
  return (
    <div className="space-y-3">
      <Field label="是否应有答案" testId="answerable">
        <select
          className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-sm"
          value={assertions.answerable ? 'true' : 'false'}
          onChange={(e) => setAssertion('answerable', e.target.value === 'true')}
        >
          <option value="true">是</option>
          <option value="false">否</option>
        </select>
      </Field>
      <Field label="必含内容（逗号分隔）" testId="must_include">
        <Input
          value={Array.isArray(assertions.must_include)
            ? (assertions.must_include as string[]).join(',')
            : ''}
          onChange={(e) =>
            setAssertion('must_include', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))
          }
        />
      </Field>
      <Field label="禁止内容（逗号分隔）" testId="must_not_include">
        <Input
          value={Array.isArray(assertions.must_not_include)
            ? (assertions.must_not_include as string[]).join(',')
            : ''}
          onChange={(e) =>
            setAssertion('must_not_include', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))
          }
        />
      </Field>
      <Field label="Rubric ID" testId="rubric_id">
        <Input
          value={String(assertions.rubric_id ?? '')}
          onChange={(e) => setAssertion('rubric_id', e.target.value || null)}
        />
      </Field>
    </div>
  )
}

function SafetyFields({
  assertions,
  setAssertion,
}: {
  assertions: Record<string, unknown>
  setAssertion: (k: string, v: unknown) => void
}) {
  return (
    <div className="space-y-3">
      <Field label="敏感字段（逗号分隔）" testId="sensitive_fields">
        <Input
          value={Array.isArray(assertions.sensitive_fields)
            ? (assertions.sensitive_fields as string[]).join(',')
            : ''}
          onChange={(e) =>
            setAssertion('sensitive_fields', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))
          }
        />
      </Field>
      <Field label="应拦截动作（逗号分隔）" testId="blocked_actions">
        <Input
          value={Array.isArray(assertions.blocked_actions)
            ? (assertions.blocked_actions as string[]).join(',')
            : ''}
          onChange={(e) =>
            setAssertion('blocked_actions', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))
          }
        />
      </Field>
      <Field label="期望态" testId="expected_state">
        <select
          className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-sm"
          value={String(assertions.expected_state ?? 'waiting_human_confirmation')}
          onChange={(e) => setAssertion('expected_state', e.target.value)}
        >
          <option value="waiting_human_confirmation">等待人工确认</option>
          <option value="blocked">阻断</option>
          <option value="sanitized">脱敏</option>
        </select>
      </Field>
    </div>
  )
}
