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
import { Textarea } from '@/components/ui/textarea'
import { testInfraSkillRouting } from '@/lib/api-client'
import type { SkillRouteTestResponse } from '@/lib/types'

interface SkillRouteTestDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelectSkill: (skillId: string) => void
}

export default function SkillRouteTestDrawer({ open, onOpenChange, onSelectSkill }: SkillRouteTestDrawerProps) {
  const [question, setQuestion] = useState('')
  const [result, setResult] = useState<SkillRouteTestResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run(): Promise<void> {
    if (!question.trim()) return
    setLoading(true)
    setError(null)
    try {
      setResult(await testInfraSkillRouting({ question: question.trim() }))
    } catch (routeError) {
      setError(routeError instanceof Error ? routeError.message : '路由分析失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="inset-y-0 left-auto right-0 top-0 h-dvh w-full max-w-xl translate-x-0 translate-y-0 content-start overflow-y-auto rounded-none p-6 sm:max-w-xl"
      >
        <DialogHeader>
          <DialogTitle>路由调试</DialogTitle>
          <DialogDescription>仅分析路由命中与候选，不会执行 Skill。</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <label htmlFor="route-question" className="text-sm font-medium text-slate-900">路由问题</label>
          <Textarea
            id="route-question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="输入已脱敏的医保业务问题"
            className="min-h-28"
          />
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={() => void run()} disabled={!question.trim() || loading}>{loading ? '分析中…' : '分析路由'}</Button>
          <DialogClose render={<Button variant="outline" aria-label="关闭路由调试" />}>关闭</DialogClose>
        </div>
        {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        {result && (
          <section className="space-y-4 border-t border-slate-200 pt-5">
            <div className="rounded-lg border border-slate-200 p-4">
              <p className="text-xs text-slate-500">命中 Skill</p>
              <p className="mt-1 font-mono text-sm font-medium text-slate-900">{result.matched_skill_id ?? '未命中'}</p>
              <p className="mt-2 text-sm text-slate-600">置信度 {Math.round(result.confidence * 100)}% · {result.match_method}</p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div><h3 className="text-sm font-medium">命中关键词</h3><p className="mt-1 text-sm text-slate-500">{result.matched_keywords.join('、') || '无'}</p></div>
              <div><h3 className="text-sm font-medium">排除关键词</h3><p className="mt-1 text-sm text-slate-500">{result.excluded_keywords.join('、') || '无'}</p></div>
            </div>
            <div className="space-y-2">
              <h3 className="text-sm font-medium">候选列表</h3>
              {result.candidates.map((candidate) => (
                <button
                  key={candidate.skill_id}
                  type="button"
                  onClick={() => onSelectSkill(candidate.skill_id)}
                  className="flex w-full items-center justify-between rounded-lg border border-slate-200 p-3 text-left hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                >
                  <span><strong className="block text-sm">{candidate.skill_name}</strong><span className="font-mono text-xs text-slate-500">{candidate.skill_id}</span></span>
                  <span className="text-sm font-medium text-blue-700">{Math.round(candidate.confidence * 100)}%</span>
                </button>
              ))}
            </div>
          </section>
        )}
      </DialogContent>
    </Dialog>
  )
}
