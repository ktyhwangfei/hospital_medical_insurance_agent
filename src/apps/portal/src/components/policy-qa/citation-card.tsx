'use client'

import Link from 'next/link'
import { BookOpenText, FileText } from 'lucide-react'

import { groupCitationsByDocument } from '@/lib/policy-qa-citations'
import type { PolicyQAResult } from '@/lib/policy-qa-stream'

/**
 * V4.0 政策问答智能体：内联政策来源卡片（常显，不折叠）。
 *
 * 设计 §4.1：来源可追溯是政策问答智能体的核心价值——
 * 文档标题 + 命中条款 + 原文链接直接展开在答案内，不做折叠引用角标。
 */

interface CitationCardsProps {
  citations: PolicyQAResult['citations']
}

export default function CitationCards({ citations }: CitationCardsProps) {
  const groups = groupCitationsByDocument(citations)
  if (groups.length === 0) return null

  return (
    <section
      aria-label="政策来源"
      data-testid="policy-qa-citation-cards"
      className="space-y-3 rounded-xl bg-slate-50 p-4"
    >
      <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
        <BookOpenText className="size-4" aria-hidden />
        政策来源（{groups.length} 篇）
      </div>
      <ol className="space-y-3">
        {groups.map((group) => (
          <li
            key={group.docId || group.title}
            className="rounded-xl border border-slate-200 bg-white p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <p className="flex items-center gap-1.5 font-medium text-slate-900">
                <FileText className="size-3.5 shrink-0 text-slate-400" aria-hidden />
                {group.title}
              </p>
              {group.docId ? (
                <Link
                  href={`/policy-document/${encodeURIComponent(group.docId)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="shrink-0 text-sm text-blue-600 hover:underline"
                >
                  查看原文 →
                </Link>
              ) : null}
            </div>
            <ul className="mt-2 space-y-1.5">
              {group.excerpts.map((item, index) => {
                const highlight = item.sourceExcerpt?.trim()
                const body = <span>{item.text}</span>
                return (
                  <li
                    key={index}
                    className="border-l-2 border-slate-300 pl-3 text-sm leading-6 text-slate-600"
                  >
                    {group.docId && highlight ? (
                      <Link
                        href={`/policy-document/${encodeURIComponent(group.docId)}?q=${encodeURIComponent(highlight)}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="hover:text-blue-600 hover:underline"
                        title="在原文中定位该段落"
                      >
                        {body}
                      </Link>
                    ) : (
                      body
                    )}
                  </li>
                )
              })}
            </ul>
          </li>
        ))}
      </ol>
    </section>
  )
}
