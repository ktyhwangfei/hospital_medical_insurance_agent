'use client'

import { BadgeCheck, FileWarning, ShieldCheck } from 'lucide-react'

import type {
  PolicyTestCase,
  QualityCaseResult,
  WorkbenchDocumentSummary,
} from '@/lib/policy-knowledge-api'

interface GoldenCaseCoverageProps {
  cases: PolicyTestCase[]
  documents: WorkbenchDocumentSummary[]
  caseResults: QualityCaseResult[]
}

interface GoldenGroup {
  docId: string
  title: string
  cases: PolicyTestCase[]
}

const DIM_LABELS: Record<string, string> = {
  psn_type: '人群',
  med_type: '医疗类别',
  hosp_lv: '医院等级',
  amount_band: '金额区间',
  rule_type: '规则类型',
  insu_type: '险种',
}

function isGolden(item: PolicyTestCase): boolean {
  return item.case_id.startsWith('golden')
}

function groupByDocument(cases: PolicyTestCase[]): GoldenGroup[] {
  const map = new Map<string, GoldenGroup>()
  for (const item of cases) {
    if (!isGolden(item) || !item.active) continue
    const docId = String(item.filters?.doc_id ?? '')
    const group = map.get(docId) ?? { docId, title: '', cases: [] }
    group.cases.push(item)
    map.set(docId, group)
  }
  return [...map.values()]
}

function dimSummary(item: PolicyTestCase): string {
  return Object.entries(item.filters ?? {})
    .filter(([key]) => key !== 'doc_id')
    .map(([key, value]) => `${DIM_LABELS[key] ?? key}=${String(value)}`)
    .join(' · ')
}

/** 黄金问答覆盖面板：按政策文档分组展示黄金用例，并标注未覆盖文档与最近运行结果。 */
export function GoldenCaseCoverage({
  cases,
  documents,
  caseResults,
}: GoldenCaseCoverageProps) {
  const groups = groupByDocument(cases)
  const coveredDocIds = new Set(groups.map((group) => group.docId))
  const uncovered = documents.filter((doc) => !coveredDocIds.has(doc.doc_id))
  for (const group of groups) {
    group.title =
      documents.find((doc) => doc.doc_id === group.docId)?.doc_title ?? group.docId
  }
  const latestByCaseId = new Map<string, QualityCaseResult>()
  for (const result of caseResults) {
    if (!latestByCaseId.has(result.case_id)) latestByCaseId.set(result.case_id, result)
  }
  const goldenTotal = groups.reduce((sum, group) => sum + group.cases.length, 0)

  return (
    <section
      data-testid="golden-case-coverage"
      className="rounded-2xl border border-amber-200 bg-amber-50/40 p-5 shadow-sm"
    >
      <div className="flex flex-wrap items-center gap-2">
        <ShieldCheck className="size-4 text-amber-600" />
        <h3 className="text-sm font-semibold text-slate-900">黄金问答覆盖</h3>
        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
          {goldenTotal} 条用例 · 覆盖 {groups.length}/{documents.length} 篇文档
        </span>
        <span className="ml-auto text-[11px] text-slate-400">
          发布门禁的回归护栏：候选版本运行质量时逐条断言
        </span>
      </div>

      {groups.length === 0 && (
        <p className="mt-3 text-xs text-slate-500">
          尚无黄金用例。运行 scripts/seed_golden_test_cases.py 按文档生成。
        </p>
      )}

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        {groups.map((group) => (
          <div
            key={group.docId}
            className="rounded-xl border border-amber-100 bg-white p-4"
          >
            <p className="text-xs font-semibold text-slate-800">{group.title}</p>
            <ul className="mt-2 space-y-2">
              {group.cases.map((item) => {
                const result = latestByCaseId.get(item.case_id)
                return (
                  <li
                    key={item.case_id}
                    className="rounded-lg border border-slate-100 bg-slate-50/60 p-2.5"
                  >
                    <div className="flex items-center gap-2">
                      {result ? (
                        result.passed ? (
                          <BadgeCheck className="size-3.5 shrink-0 text-emerald-600" />
                        ) : (
                          <FileWarning className="size-3.5 shrink-0 text-red-600" />
                        )
                      ) : (
                        <span className="size-3.5 shrink-0 rounded-full border border-slate-300" />
                      )}
                      <p className="text-[11px] font-medium text-slate-700">
                        {item.query}
                      </p>
                      <span
                        className={`ml-auto shrink-0 rounded px-1 text-[9px] ${
                          result
                            ? result.passed
                              ? 'bg-emerald-50 text-emerald-700'
                              : 'bg-red-50 text-red-700'
                            : 'bg-slate-100 text-slate-500'
                        }`}
                      >
                        {result ? (result.passed ? '通过' : '未通过') : '未运行'}
                      </span>
                    </div>
                    <p className="mt-1 font-mono text-[9px] text-slate-400">
                      {dimSummary(item)} · 期望 {item.expected_knowledge_ids.length} 条规则
                    </p>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </div>

      {uncovered.length > 0 && (
        <div className="mt-3 rounded-xl border border-red-100 bg-red-50/60 p-3">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold text-red-700">
            <FileWarning className="size-3.5" />
            未覆盖文档（{uncovered.length} 篇）
          </p>
          <p className="mt-1 text-[11px] leading-5 text-red-600">
            {uncovered.map((doc) => doc.doc_title).join('；')}
          </p>
          <p className="mt-1 text-[10px] text-red-400">
            无比例类规则的文档不产生黄金问答，由提取覆盖率校验与发布键冲突门禁兜底。
          </p>
        </div>
      )}
    </section>
  )
}
