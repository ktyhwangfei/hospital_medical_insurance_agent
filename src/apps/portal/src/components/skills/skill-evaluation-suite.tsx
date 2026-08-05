'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Play, Plus, RefreshCw, XCircle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  createSkillEvalCase,
  createSkillEvalRun,
  listSkillEvalCases,
  listSkillEvalRuns,
} from '@/lib/api-client'
import type {
  SkillEvalCaseResponse,
  SkillEvalRunResponse,
  SkillVersionResponse,
} from '@/lib/types'


interface SkillEvaluationSuiteProps {
  skillId: string
  versions: SkillVersionResponse[]
}


function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '批量评测请求失败'
}


export default function SkillEvaluationSuite({
  skillId,
  versions,
}: SkillEvaluationSuiteProps) {
  const [cases, setCases] = useState<SkillEvalCaseResponse[]>([])
  const [runs, setRuns] = useState<SkillEvalRunResponse[]>([])
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(true)
  const [mutating, setMutating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [casePage, runPage] = await Promise.all([
        listSkillEvalCases(),
        listSkillEvalRuns(skillId),
      ])
      setCases(casePage.items)
      setRuns(runPage.items)
    } catch (loadError) {
      setError(errorMessage(loadError))
    } finally {
      setLoading(false)
    }
  }, [skillId])

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(timer)
  }, [load])

  const latestRun = runs[0]
  const currentVersion = versions.find((version) => version.validation_status === 'passed')
  const relevantCases = useMemo(
    () => cases.filter((item) => item.expected_skill_id === skillId || item.expected_skill_id == null),
    [cases, skillId],
  )

  const addCase = async () => {
    if (!question.trim()) return
    setMutating(true)
    setError(null)
    try {
      await createSkillEvalCase({
        question_template: question.trim(),
        expected_skill_id: skillId,
        required: true,
        risk_tags: [],
        business_tags: [],
        source_type: 'manual',
        source_ref: 'portal-skill-workbench',
        contains_sensitive_data: false,
      })
      setQuestion('')
      await load()
    } catch (mutationError) {
      setError(errorMessage(mutationError))
    } finally {
      setMutating(false)
    }
  }

  const runEvaluation = async () => {
    if (!currentVersion) return
    setMutating(true)
    setError(null)
    try {
      await createSkillEvalRun(skillId, {
        version_id: currentVersion.version_id,
      })
      await load()
    } catch (mutationError) {
      setError(errorMessage(mutationError))
    } finally {
      setMutating(false)
    }
  }

  if (loading) {
    return <div className="py-10 text-center text-sm text-gray-500">正在加载固定评测集...</div>
  }

  return (
    <div className="space-y-4" data-testid="skill-evaluation-suite">
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="输入脱敏后的固定路由问题"
          className="min-w-64 flex-1"
        />
        <Button variant="outline" onClick={addCase} disabled={mutating || !question.trim()}>
          <Plus className="mr-1 h-4 w-4" />新增必测用例
        </Button>
        <Button onClick={runEvaluation} disabled={mutating || !currentVersion || cases.length === 0}>
          <Play className="mr-1 h-4 w-4" />运行候选评测
        </Button>
        <Button variant="ghost" size="icon" onClick={() => void load()} aria-label="刷新评测">
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>
      <p className="text-xs text-gray-500">
        仅保存脱敏问题模板；候选版按不可变 Manifest 快照评测，不读取患者上下文。
      </p>

      {latestRun ? (
        <Card className={latestRun.metrics.gate_passed ? 'border-emerald-200' : 'border-red-200'}>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center justify-between text-sm">
              <span>最近一次候选版 / 基线对比</span>
              <Badge variant="outline" className={latestRun.metrics.gate_passed ? 'text-emerald-700' : 'text-red-700'}>
                {latestRun.metrics.gate_passed ? '门禁通过' : '门禁未通过'}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              <div>必测通过 <strong>{latestRun.metrics.required_passed}/{latestRun.metrics.required_total}</strong></div>
              <div>Top-1 <strong>{Math.round(latestRun.metrics.top1_accuracy * 100)}%</strong></div>
              <div>新增失败 <strong>{latestRun.metrics.regression_count}</strong></div>
              <div>新增误接管 <strong>{latestRun.metrics.new_false_takeover_count}</strong></div>
            </div>
            {latestRun.results.map((result) => (
              <div key={result.case_id} className="flex items-center justify-between rounded border px-3 py-2 text-xs">
                <span className="font-mono">{result.case_id.slice(0, 12)}</span>
                <span>{result.candidate_skill_id ?? 'no-match'} / {result.baseline_skill_id ?? 'no-match'}</span>
                {result.candidate_passed ? (
                  <span className="flex items-center gap-1 text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" />通过</span>
                ) : (
                  <span className="flex items-center gap-1 text-red-700"><XCircle className="h-3.5 w-3.5" />{result.diff}</span>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      ) : (
        <div className="rounded-lg border border-dashed py-8 text-center text-sm text-gray-500">
          尚无批量评测运行
        </div>
      )}

      <div className="space-y-2">
        <div className="text-xs font-medium text-gray-600">固定用例（当前 Skill 与 no-match）· {relevantCases.length}</div>
        {relevantCases.map((item) => (
          <div key={item.case_id} className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm">
            <span>{item.question_template}</span>
            <div className="flex items-center gap-2 text-xs text-gray-500">
              {item.required && <Badge variant="secondary">必测</Badge>}
              <span>suite v{item.suite_version}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
