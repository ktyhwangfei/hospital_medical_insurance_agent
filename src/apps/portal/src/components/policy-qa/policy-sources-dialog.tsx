'use client'

import { useState } from 'react'
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

export default function PolicySourcesDialog({ citations }: PolicySourcesDialogProps) {
  const [open, setOpen] = useState(false)
  if (citations.length === 0) return null

  return (
    <>
      <Button type="button" variant="outline" onClick={() => setOpen(true)}>
        <BookOpenText aria-hidden />
        查看 {citations.length} 条政策来源
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>政策来源</DialogTitle>
            <DialogDescription>以下仅展示可公开核验的政策标题与相关摘录。</DialogDescription>
          </DialogHeader>
          <ol className="space-y-3">
            {citations.map((citation, index) => (
              <li
                key={`${citation.title}-${index}`}
                className="rounded-xl border border-slate-200 bg-slate-50 p-4"
              >
                <p className="font-medium text-slate-900">{citation.title}</p>
                <p className="mt-2 text-sm leading-6 text-slate-600">{citation.excerpt}</p>
              </li>
            ))}
          </ol>
        </DialogContent>
      </Dialog>
    </>
  )
}
