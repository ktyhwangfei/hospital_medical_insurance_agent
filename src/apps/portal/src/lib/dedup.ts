/**
 * dedup.ts — 前端数据去重与规范化工具
 *
 * 用于在渲染前对 SettlementExplanationData 进行去重处理，
 * 确保同一内容只在一个位置展示。
 */

import type { SettlementExplanationData, PolicyEvidenceItem, CalculationStep } from './settlement-explanation-types'

/** 规范化文本：去除空白、中文标点后比较 */
export function normalizeText(text: string): string {
  return text
    .replace(/\s+/g, '')
    .replace(/[，。；：、,.;:]/g, '')
    .trim()
}

/** 基于文本内容去重（保留首次出现） */
export function dedupeByText<T>(items: T[], keyFn: (item: T) => string): T[] {
  const seen = new Set<string>()
  return items.filter((item) => {
    const key = normalizeText(keyFn(item))
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

/** 去重并过滤空字符串 */
export function dedupeStrings(items: string[]): string[] {
  const seen = new Set<string>()
  return items.filter((item) => {
    const trimmed = item.trim()
    if (!trimmed) return false
    const key = normalizeText(trimmed)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

/** 基于 policy_title 和 clause_text 去除重复政策依据 */
export function dedupePolicyEvidence(items: PolicyEvidenceItem[]): PolicyEvidenceItem[] {
  const seen = new Set<string>()
  return items.filter((item) => {
    const key = normalizeText(`${item.policy_title}|||${item.clause_text}`)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

/** 基于 step_name 和 description 去除重复计算步骤 */
function dedupeCalcSteps(steps: CalculationStep[]): CalculationStep[] {
  return dedupeByText(steps, (s) => `${s.step_name}|||${s.description}`)
}

/**
 * 规范化 SettlementExplanationData：
 * 1. warnings 去重，最多保留 3 条
 * 2. policy_evidence 去重
 * 3. calculation_trace.steps 去重
 * 4. 空字段过滤
 * 5. 重复段落过滤
 */
export function normalizeExplanationResult(
  data: SettlementExplanationData
): SettlementExplanationData {
  return {
    ...data,
    warnings: dedupeStrings(data.warnings || []).slice(0, 3),
    policy_evidence: dedupePolicyEvidence(data.policy_evidence),
    calculation_trace: {
      method: data.calculation_trace?.method ?? '',
      steps: dedupeCalcSteps(data.calculation_trace?.steps ?? []),
    },
    // 清理患者/院端回答中的重复段落
    patient_answer: dedupeParagraphs(data.patient_answer),
    office_answer: dedupeParagraphs(data.office_answer),
  }
}

/** 去除大段文本中重复的段落（基于段落文本相似度） */
function dedupeParagraphs(text: string): string {
  if (!text) return text
  const paragraphs = text.split('\n').filter((p) => p.trim())
  const deduped = dedupeByText(paragraphs, (p) => p)
  return deduped.join('\n')
}
