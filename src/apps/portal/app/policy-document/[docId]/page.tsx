'use client'

import Link from 'next/link'
import { useParams, useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useState } from 'react'

import {
  getPolicyDocumentContent,
  PolicyDocumentContent,
} from '@/lib/policy-document-api'

/** 把命中单元的原文段落在全文中高亮（?q= 参数，多命中全部标出）。 */
function HighlightedText({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>
  const parts = text.split(query)
  if (parts.length === 1) return <>{text}</>
  return (
    <>
      {parts.map((part, index) => (
        <span key={index}>
          {part}
          {index < parts.length - 1 && (
            <mark className="rounded bg-yellow-200 px-0.5">{query}</mark>
          )}
        </span>
      ))}
    </>
  )
}

export default function PolicyDocumentPage() {
  return (
    <Suspense
      fallback={
        <main className="min-h-screen bg-gray-50 p-6">
          <div className="mx-auto max-w-4xl rounded-lg bg-white p-6 shadow text-gray-500">
            加载中…
          </div>
        </main>
      }
    >
      <PolicyDocumentContentView />
    </Suspense>
  )
}

function PolicyDocumentContentView() {
  const params = useParams<{ docId: string }>()
  const searchParams = useSearchParams()
  const highlight = searchParams?.get('q')?.trim() ?? ''
  const docId = params?.docId
  const [doc, setDoc] = useState<PolicyDocumentContent | null>(null)
  const [error, setError] = useState<string>('')

  useEffect(() => {
    if (!docId) return
    getPolicyDocumentContent(docId)
      .then(setDoc)
      .catch((err: Error) => setError(err.message || '加载失败'))
  }, [docId])

  if (error) {
    return (
      <main className="min-h-screen bg-gray-50 p-6">
        <div className="mx-auto max-w-4xl rounded-lg bg-white p-6 shadow text-red-600">
          {error}
        </div>
      </main>
    )
  }

  if (!doc) {
    return (
      <main className="min-h-screen bg-gray-50 p-6">
        <div className="mx-auto max-w-4xl rounded-lg bg-white p-6 shadow text-gray-500">
          加载中…
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-gray-50 p-6">
      <div className="mx-auto max-w-4xl rounded-lg bg-white p-6 shadow">
        <Link
          href="/policy-qa"
          className="text-sm text-blue-600 hover:underline"
        >
          ← 返回问答
        </Link>
        <h1 className="mt-4 text-2xl font-bold text-gray-900">{doc.title}</h1>
        <div className="mt-2 flex flex-wrap gap-4 text-sm text-gray-500">
          {doc.issuing_agency && <span>发布机构：{doc.issuing_agency}</span>}
          {doc.publish_date && <span>发布日期：{doc.publish_date}</span>}
          <span>状态：{doc.validity}</span>
        </div>
        {doc.source_url && (
          <a
            href={doc.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 inline-block text-sm text-blue-600 hover:underline"
          >
            访问原始链接
          </a>
        )}
        <pre className="mt-6 max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-lg bg-gray-50 p-4 text-sm leading-relaxed text-gray-800">
          <HighlightedText text={doc.content_text} query={highlight} />
        </pre>
      </div>
    </main>
  )
}
