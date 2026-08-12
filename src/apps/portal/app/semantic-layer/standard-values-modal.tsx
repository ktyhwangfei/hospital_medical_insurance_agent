'use client'

import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Loader2, X, Plus, Trash2,
} from 'lucide-react'
import { semanticReviewJson } from '@/lib/policy-knowledge-api'

const SEMANTIC_API = '/api/v1/medical-insurance-ai-agent/semantic'

interface Props {
  valueDomainCode: string
  onClose: () => void
  onSaved: () => void
}

export default function StandardValuesModal({ valueDomainCode, onClose, onSaved }: Props) {
  const [values, setValues] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [newValue, setNewValue] = useState('')
  const [notFound, setNotFound] = useState(false)
  const [creating, setCreating] = useState(false)

  const loadValues = useCallback(async () => {
    setLoading(true); setNotFound(false)
    try {
      const res = await fetch(`${SEMANTIC_API}/value-domains/${encodeURIComponent(valueDomainCode)}/standard-values`)
      if (res.status === 404) { setNotFound(true); setValues([]) }
      else if (res.ok) { const data = await res.json() as { standard_values: string[] }; setValues(data.standard_values || []) }
    } catch { setValues([]) }
    setLoading(false)
  }, [valueDomainCode])

  useEffect(() => { loadValues() }, [loadValues])

  const addValue = useCallback(() => {
    const v = newValue.trim()
    if (!v || values.includes(v)) return
    setValues((prev) => [...prev, v])
    setNewValue('')
  }, [newValue, values])

  const removeValue = useCallback((idx: number) => {
    setValues((prev) => prev.filter((_, i) => i !== idx))
  }, [])

  const handleSave = useCallback(async () => {
    setSaving(true)
    try {
      await semanticReviewJson(`${SEMANTIC_API}/value-domains/${encodeURIComponent(valueDomainCode)}/standard-values`, 'PUT', { standard_values: values })
      onSaved()
      onClose()
    } catch (err: any) { alert(err.message) }
    setSaving(false)
  }, [values, valueDomainCode, onSaved, onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm" onClick={onClose}>
      <div className="max-h-[85vh] w-full max-w-md overflow-y-auto rounded-2xl border border-slate-200 bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-800">标准值域</h3>
            <p className="font-mono text-[11px] text-slate-400">{valueDomainCode}</p>
          </div>
          <button onClick={onClose} className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"><X className="h-4 w-4" /></button>
        </div>

        <div className="space-y-4 px-6 py-4">
          {loading ? (
            <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>
          ) : notFound ? (
            <div className="py-6 text-center">
              <p className="text-sm text-slate-600 mb-1">值域 "{valueDomainCode}" 尚未创建</p>
              <p className="text-[11px] text-slate-400 mb-4">可在映射页"值域管理"中创建，或点击下方按钮直接创建</p>
              <button
                onClick={async () => {
                  setCreating(true)
                  try {
                    await semanticReviewJson(`${SEMANTIC_API}/value-domains`, 'POST', { domain_code: valueDomainCode, name: valueDomainCode })
                    setNotFound(false)
                    loadValues()
                  } catch (err: any) { alert(err.message || '创建失败') }
                  finally { setCreating(false) }
                }}
                disabled={creating}
                className="rounded-md bg-purple-500 px-4 py-1.5 text-xs font-medium text-white hover:bg-purple-600 disabled:opacity-40"
              >
                {creating ? '创建中...' : `创建 "${valueDomainCode}" 值域`}
              </button>
            </div>
          ) : (
            <>
              {/* Standard values list */}
              <div>
                <h4 className="mb-2 text-xs font-medium text-slate-500">
                  标准值列表 <span className="font-mono text-slate-400">({values.length})</span>
                </h4>
                {values.length === 0 ? (
                  <p className="py-4 text-center text-[11px] text-slate-400">暂无标准值，请在下方添加</p>
                ) : (
                  <div className="max-h-48 overflow-y-auto rounded-lg border border-slate-200">
                    <table className="w-full text-left text-xs">
                      <thead>
                        <tr className="border-b border-slate-100 bg-slate-50 text-[11px] text-slate-500">
                          <th className="px-3 py-2 font-medium w-10">#</th>
                          <th className="px-3 py-2 font-medium">标准值</th>
                          <th className="w-10 px-2 py-2"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {values.map((v, i) => (
                          <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                            <td className="px-3 py-1.5 text-slate-400">{i + 1}</td>
                            <td className="px-3 py-1.5 font-medium text-slate-700">{v}</td>
                            <td className="px-2 py-1.5">
                              <button onClick={() => removeValue(i)} className="rounded p-0.5 text-slate-400 hover:text-red-500"><Trash2 className="h-3 w-3" /></button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Add new */}
              <div className="flex items-center gap-2">
                <Input
                  value={newValue}
                  onChange={(e) => setNewValue(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') addValue() }}
                  placeholder="输入标准值，如：三级"
                  className="h-8 flex-1 text-xs"
                />
                <Button size="sm" onClick={addValue} disabled={!newValue.trim()} className="h-8 gap-1 bg-purple-50 text-purple-600 text-xs hover:bg-purple-100">
                  <Plus className="h-3 w-3" />添加
                </Button>
              </div>

              {/* Actions */}
              <div className="flex justify-end gap-2 pt-2 border-t border-slate-100">
                <button onClick={onClose} className="rounded-md border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50">取消</button>
                <button onClick={handleSave} disabled={saving} className="rounded-md bg-purple-500 px-4 py-1.5 text-xs font-medium text-white hover:bg-purple-600 disabled:opacity-40">
                  {saving ? '保存中...' : `保存 (${values.length})`}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
