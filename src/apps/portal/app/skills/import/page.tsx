'use client'

import { useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Upload, AlertCircle, Loader2, CheckCircle2, FileArchive } from 'lucide-react'
import { importSkillZip, ApiClientError } from '@/lib/skill-draft-api'
import type { SkillDraftResponse } from '@/lib/types'

// /skills/import 导入入口（设计 §4.2）：支持 ZIP 上传，导入后生成独立草稿
export default function SkillImportPage() {
  const router = useRouter()
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [importing, setImporting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<SkillDraftResponse | null>(null)

  async function handleImport() {
    if (!file) return
    setImporting(true)
    setError(null)
    try {
      const key = `import-skill-${Date.now()}`
      const draft = await importSkillZip(file, key)
      setResult(draft)
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '导入失败')
    } finally {
      setImporting(false)
    }
  }

  if (result) {
    return (
      <div className="mt-10 mx-auto max-w-lg rounded-xl border border-green-200 bg-white p-8 text-center shadow-sm">
        <CheckCircle2 className="mx-auto h-12 w-12 text-green-600" />
        <h2 className="mt-4 text-xl font-semibold text-slate-900">导入成功</h2>
        <p className="mt-2 text-sm text-slate-600">
          已从 ZIP 创建草稿「{result.skill_name}」，可在编辑器中校验后物化。
        </p>
        <div className="mt-6 flex justify-center gap-2">
          <button
            type="button"
            onClick={() => router.push('/skills/drafts')}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            返回草稿列表
          </button>
          <button
            type="button"
            onClick={() => router.push(`/skills/${encodeURIComponent(result.skill_id)}/edit?draft=${result.draft_id}`)}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            进入编辑器
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="mt-4 mx-auto max-w-2xl space-y-6">
      <header className="space-y-1">
        <h2 className="text-xl font-semibold tracking-tight text-slate-900">导入 Skill</h2>
        <p className="text-sm text-slate-600">
          上传 ZIP 包导入已有 Skill。导入后生成独立草稿，不自动写入正式 skills/ 目录，也不自动执行其中脚本。
        </p>
      </header>

      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div
          className="rounded-xl border-2 border-dashed border-slate-300 p-8 text-center transition hover:border-blue-400 hover:bg-blue-50/30"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            const f = e.dataTransfer.files[0]
            if (f) setFile(f)
          }}
        >
          <FileArchive className="mx-auto h-10 w-10 text-slate-400" />
          <p className="mt-3 text-sm text-slate-600">拖拽 ZIP 文件到此处，或</p>
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            <Upload className="h-4 w-4" />
            选择文件
          </button>
          <input
            ref={inputRef}
            type="file"
            accept=".zip"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) setFile(f)
            }}
          />
          {file && (
            <p className="mt-3 text-sm font-medium text-blue-700">{file.name} ({(file.size / 1024).toFixed(1)} KB)</p>
          )}
        </div>

        <div className="mt-4 rounded-lg bg-amber-50 px-4 py-3 text-xs text-amber-700">
          <p className="font-medium">安全检查</p>
          <p className="mt-1">导入包将经过路径遍历、符号链接、文件大小和扩展名检查，以及脚本安全性（AST）与敏感内容扫描。包含风险的包将被拒绝。</p>
        </div>

        {error && (
          <div className="mt-4 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {error}
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => router.back()}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void handleImport()}
            disabled={!file || importing}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            导入
          </button>
        </div>
      </div>
    </div>
  )
}
