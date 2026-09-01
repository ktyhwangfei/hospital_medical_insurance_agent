'use client'

import { useState } from 'react'
import { Loader2, ShieldCheck } from 'lucide-react'

import AnswerVerificationResult from '@/components/policy-qa/answer-verification-result'
import { Button } from '@/components/ui/button'
import { verifyPolicyQAAnswer, type VerifyAnswerResponse } from '@/lib/policy-qa-feedback'
import { ApiClientError } from '@/lib/types'

/** 针对一次问答轮次（qa_turn_id）的「验证」按钮：点击后内联展示五维验证结果。 */
export default function AnswerVerificationButton({ qaTurnId }: { qaTurnId: string }) {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<VerifyAnswerResponse | null>(null)
  const [error, setError] = useState('')

  async function run() {
    if (loading) return
    setLoading(true); setError(''); setResult(null)
    try {
      setResult(await verifyPolicyQAAnswer(qaTurnId))
    } catch (reason) {
      if (reason instanceof ApiClientError && reason.status === 404) {
        setError('该回答的验证轨迹已失效（可能服务已重启），仅保留公开信息可降级验证')
      } else {
        setError(reason instanceof Error ? reason.message : '答案验证失败')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col items-start gap-2">
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => void run()}
        disabled={loading}
        className="flex items-center gap-1.5"
      >
        {loading ? (
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
        ) : (
          <ShieldCheck className="size-3.5" aria-hidden />
        )}
        答案验证
      </Button>
      {error && <p className="text-xs text-red-600">{error}</p>}
      {result && <AnswerVerificationResult result={result} className="w-full" />}
    </div>
  )
}
