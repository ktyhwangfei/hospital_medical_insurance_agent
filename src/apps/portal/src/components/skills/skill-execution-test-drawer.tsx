'use client'

import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { testInfraSkillExecution } from '@/lib/api-client'
import type { SkillExecuteTestResponse } from '@/lib/types'

interface SkillExecutionTestDrawerProps {
  open: boolean
  skillId: string | null
  onOpenChange: (open: boolean) => void
}

export default function SkillExecutionTestDrawer({ open, skillId, onOpenChange }: SkillExecutionTestDrawerProps) {
  const [question, setQuestion] = useState('')
  const [targetFeeItem, setTargetFeeItem] = useState('')
  const [context, setContext] = useState('{\n  "patient_id": "DEMO_PATIENT",\n  "encounter_id": "DEMO_ENCOUNTER"\n}')
  const [result, setResult] = useState<SkillExecuteTestResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run(): Promise<void> {
    if (!skillId || !question.trim()) return
    setLoading(true)
    setError(null)
    try {
      const parsedContext = JSON.parse(context) as Record<string, unknown>
      setResult(await testInfraSkillExecution(skillId, {
        question: question.trim(),
        target_fee_item: targetFeeItem.trim() || null,
        context: parsedContext,
      }))
    } catch (executionError) {
      setError(executionError instanceof Error ? executionError.message : '执行调试失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="inset-y-0 left-auto right-0 top-0 h-dvh w-full max-w-2xl translate-x-0 translate-y-0 content-start overflow-y-auto rounded-none p-6 sm:max-w-2xl"
      >
        <DialogHeader>
          <DialogTitle>执行调试</DialogTitle>
          <DialogDescription>仅使用脱敏示例上下文执行当前 Skill，结果不会持久化。</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <label htmlFor="execution-question" className="text-sm font-medium">调试问题</label>
          <Textarea id="execution-question" value={question} onChange={(event) => setQuestion(event.target.value)} className="min-h-24" />
        </div>
        <div className="space-y-2">
          <label htmlFor="target-fee-item" className="text-sm font-medium">目标费用项（可选）</label>
          <Input id="target-fee-item" value={targetFeeItem} onChange={(event) => setTargetFeeItem(event.target.value)} />
        </div>
        <div className="space-y-2">
          <label htmlFor="execution-context" className="text-sm font-medium">脱敏上下文 JSON</label>
          <Textarea id="execution-context" value={context} onChange={(event) => setContext(event.target.value)} className="min-h-36 font-mono text-xs" />
        </div>
        <div className="flex gap-2">
          <Button onClick={() => void run()} disabled={!skillId || !question.trim() || loading}>{loading ? '执行中…' : '执行 Skill'}</Button>
          <DialogClose render={<Button variant="outline" aria-label="关闭执行调试" />}>关闭</DialogClose>
        </div>
        {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        {result && (
          <section className="space-y-4 border-t border-slate-200 pt-5">
            <div><h3 className="text-sm font-medium">结构化摘要</h3><pre className="mt-2 overflow-auto rounded-lg bg-slate-950 p-4 text-xs text-slate-100">{JSON.stringify(result.result, null, 2)}</pre></div>
            <div><h3 className="text-sm font-medium">引用来源</h3><pre className="mt-2 overflow-auto rounded-lg bg-slate-50 p-3 text-xs">{JSON.stringify(result.citations, null, 2)}</pre></div>
            <div><h3 className="text-sm font-medium">不确定性</h3><p className="mt-1 text-sm text-slate-600">{result.uncertainties.join('；') || '无'}</p></div>
            <div><h3 className="text-sm font-medium">警告</h3><p className="mt-1 text-sm text-slate-600">{result.warnings.join('；') || '无'}</p></div>
            <details><summary className="cursor-pointer text-sm font-medium">执行 trace / JSON</summary><pre className="mt-2 overflow-auto rounded-lg bg-slate-950 p-4 text-xs text-slate-100">{JSON.stringify(result.trace, null, 2)}</pre></details>
          </section>
        )}
      </DialogContent>
    </Dialog>
  )
}
