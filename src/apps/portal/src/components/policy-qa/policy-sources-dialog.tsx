'use client'

import Link from 'next/link'
import { useMemo, useState } from 'react'
import { BookOpenText } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { PolicyQAResult } from '@/lib/policy-qa-stream'

interface PolicySourcesDialogProps {
  citations: PolicyQAResult['citations']
}

interface SourceGroup {
  title: string
  docId?: string
  excerpts: Array<{ text: string; sourceExcerpt?: string }>
}

/** 同一篇文档命中的多个语义单元合并展示，避免同一标题重复出现。 */
function groupByDocument(citations: PolicyQAResult['citations']): SourceGroup[] {
  const map = new Map<string, SourceGroup>()
  for (const citation of citations) {
    const key = citation.docId || citation.title
    const group = map.get(key) ?? {
      title: citation.title,
      docId: citation.docId,
      excerpts: [],
    }
    if (!group.excerpts.some((item) => item.text === citation.excerpt)) {
      group.excerpts.push({ text: citation.excerpt, sourceExcerpt: citation.sourceExcerpt })
    }
    map.set(key, group)
  }
  return [...map.values()]
}

export default function PolicySourcesDialog({ citations }: PolicySourcesDialogProps) {
  const [open, setOpen] = useState(false)
  const groups = useMemo(() => groupByDocument(citations), [citations])
  if (citations.length === 0) return null

  return (
    <>
      <Button type="button" variant="outline" onClick={() => setOpen(true)}>
        <BookOpenText aria-hidden />
        查看 {groups.length} 篇政策来源（{citations.length} 条命中单元）
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          data-testid="policy-qa-sources"
          className="max-h-[80vh] overflow-y-auto sm:max-w-xl"
        >
          <DialogHeader>
            <DialogTitle>政策来源</DialogTitle>
            <DialogDescription>
              向量检索命中的是语义单元，同一篇文档可能命中多条，已按文档合并。
            </DialogDescription>
          </DialogHeader>
          <ol className="space-y-3">
            {groups.map((group) => (
              <li
                key={group.docId || group.title}
                className="rounded-xl border border-slate-200 bg-slate-50 p-4"
              >
                <p className="font-medium text-slate-900">{group.title}</p>
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
                {group.docId && (
                  <Link
                    href={`/policy-document/${encodeURIComponent(group.docId)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-3 inline-block text-sm text-blue-600 hover:underline"
                  >
                    查看原文 →
                  </Link>
                )}
              </li>
            ))}
          </ol>
        </DialogContent>
      </Dialog>
    </>
  )
}
