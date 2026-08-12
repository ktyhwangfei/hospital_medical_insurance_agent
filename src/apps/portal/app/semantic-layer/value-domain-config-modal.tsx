'use client'

import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Loader2, X, Plus, Trash2,
} from 'lucide-react'
import { semanticReviewJson } from '@/lib/policy-knowledge-api'

const SEMANTIC_API = '/api/v1/medical-insurance-ai-agent/semantic'

interface ValueMapping {
  source_value: string
  standard_value: string
  status: string
}

interface Props {
  valueDomainCode: string
  sourceValues?: string[]
  onClose: () => void
  onSaved: () => void
}

export default function ValueDomainConfigModal({ valueDomainCode, sourceValues, onClose, onSaved }: Props) {
  const [mappings, setMappings] = useState<ValueMapping[]>([])
  const [standardValues, setStandardValues] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [newSource, setNewSource] = useState('')
  const [newStandard, setNewStandard] = useState('')
  const [saving, setSaving] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [mRes, sRes] = await Promise.all([
        fetch(`${SEMANTIC_API}/value-domains/${encodeURIComponent(valueDomainCode)}/mappings`),
        fetch(`${SEMANTIC_API}/value-domains/${encodeURIComponent(valueDomainCode)}/standard-values`),
      ])
      if (mRes.ok) {
        const data = await mRes.json() as { mappings: ValueMapping[] }
        setMappings(data.mappings || [])
      }
      if (sRes.ok) {
        const data = await sRes.json() as { standard_values: string[] }
        setStandardValues(data.standard_values || [])
      }
    } catch { setMappings([]); setStandardValues([]) }
    setLoading(false)
  }, [valueDomainCode])

  useEffect(() => { loadData() }, [loadData])

  const handleAdd = useCallback(async () => {
    if (!newSource.trim() || !newStandard.trim()) return
    setSaving(true)
    try {
      await semanticReviewJson(`${SEMANTIC_API}/value-domain/mapping`, 'POST', {
        domain_code: valueDomainCode,
        source_value: newSource.trim(),
        standard_value: newStandard.trim(),
      })
      setNewSource(''); setNewStandard('')
      loadData(); onSaved()
    } catch (err: any) { alert(err.message) }
    setSaving(false)
  }, [newSource, newStandard, valueDomainCode, loadData, onSaved])

  const handleDelete = useCallback(async (sourceValue: string) => {
    try {
      await semanticReviewJson(`${SEMANTIC_API}/value-domains/${encodeURIComponent(valueDomainCode)}/mappings/${encodeURIComponent(sourceValue)}`, 'DELETE')
      loadData(); onSaved()
    } catch (err: any) { alert(err.message) }
  }, [valueDomainCode, loadData, onSaved])

  const mappedValues = new Set(mappings.map(m => m.source_value))
  const unmappedSourceValues = (sourceValues || []).filter(v => !mappedValues.has(v))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm" onClick={onClose}>
      <div className="max-h-[85vh] w-full max-w-xl overflow-y-auto rounded-2xl border border-slate-200 bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-800">值域映射</h3>
            <p className="font-mono text-[11px] text-slate-400">{valueDomainCode}</p>
          </div>
          <button onClick={onClose} className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"><X className="h-4 w-4" /></button>
        </div>

        <div className="space-y-4 px-6 py-4">
          {loading ? (
            <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>
          ) : (
            <>
              {/* Existing mappings table */}
              <div>
                <h4 className="mb-2 text-xs font-medium text-slate-500">
                  已有映射 <span className="font-mono text-slate-400">({mappings.length})</span>
                </h4>
                {mappings.length === 0 ? (
                  <p className="py-2 text-center text-[11px] text-slate-400">暂无映射</p>
                ) : (
                  <div className="max-h-40 overflow-y-auto rounded-lg border border-slate-200">
                    <table className="w-full text-left text-[11px]">
                      <thead>
                        <tr className="border-b border-slate-100 bg-slate-50 text-slate-500 sticky top-0">
                          <th className="px-3 py-1.5 font-medium">源值（原始）</th>
                          <th className="px-1 py-1.5"></th>
                          <th className="px-3 py-1.5 font-medium">标准值</th>
                          <th className="w-10 px-1 py-1.5"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {mappings.map(m => (
                          <tr key={m.source_value} className="border-b border-slate-50">
                            <td className="px-3 py-1.5 font-mono text-slate-700">{m.source_value}</td>
                            <td className="px-1 py-1.5 text-center text-slate-400">→</td>
                            <td className="px-3 py-1.5 text-slate-700">{m.standard_value}</td>
                            <td className="px-1 py-1.5">
                              <button onClick={() => handleDelete(m.source_value)} className="rounded p-0.5 text-slate-400 hover:text-red-500"><Trash2 className="h-3 w-3" /></button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Unmapped source values from discovery */}
              {unmappedSourceValues.length > 0 && (
                <div>
                  <h4 className="mb-2 text-xs font-medium text-amber-600">
                    发现源值 <span className="font-mono">({unmappedSourceValues.length})</span>
                    <span className="ml-1 font-normal text-amber-400">点击填入下方</span>
                  </h4>
                  <div className="flex flex-wrap gap-1.5">
                    {unmappedSourceValues.map((sv, i) => (
                      <button
                        key={i}
                        onClick={() => setNewSource(sv)}
                        className="rounded border border-amber-200 bg-amber-50 px-2 py-0.5 font-mono text-[10px] text-amber-700 hover:bg-amber-100"
                      >
                        {sv}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Add new mapping */}
              <div className="rounded-lg border border-dashed border-slate-300 p-3">
                <h4 className="mb-2 text-xs font-medium text-slate-500">添加映射</h4>
                <div className="flex items-start gap-2">
                  <div className="flex-1 space-y-2">
                    <div className="flex items-center gap-2">
                      <span className="w-10 text-[10px] text-slate-400 shrink-0">源值</span>
                      <Input value={newSource} onChange={(e) => setNewSource(e.target.value)} placeholder="原始值，如 LEVEL_3" className="h-8 flex-1 text-xs font-mono" />
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="w-10 text-[10px] text-slate-400 shrink-0">标准值</span>
                      <div className="flex-1 flex items-center gap-1">
                        <Input value={newStandard} onChange={(e) => setNewStandard(e.target.value)} placeholder="选择或输入标准值" className="h-8 flex-1 text-xs" />
                        {standardValues.length > 0 && (
                          <select
                            className="h-8 w-28 rounded border border-slate-300 text-xs text-slate-600"
                            value=""
                            onChange={(e) => { if (e.target.value) setNewStandard(e.target.value) }}
                          >
                            <option value="">下拉选择</option>
                            {standardValues.map(sv => (
                              <option key={sv} value={sv}>{sv}</option>
                            ))}
                          </select>
                        )}
                      </div>
                    </div>
                  </div>
                  <Button size="sm" onClick={handleAdd} disabled={saving || !newSource.trim() || !newStandard.trim()} className="h-8 gap-1 bg-purple-50 text-purple-600 text-xs hover:bg-purple-100 shrink-0">
                    {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
                    添加
                  </Button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
