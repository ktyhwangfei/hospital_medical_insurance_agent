'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  exploreSourceTable,
  exploreSourceTables,
  getMappingSqlPreview,
  getSourceMapping,
  saveSourceMapping,
  type CaptureMapping,
  type MappingSqlPreview,
  type SourceColumn,
  type SourceTable,
} from '@/lib/data-governance-api'

const CAPTURE_LABELS: Record<string, string> = {
  dbo_o_Trade: '交易表',
  dbo_o_FeeItem: '费用明细表',
  dbo_o_Diagnose: '诊断表',
}
const CAPTURE_ORDER = ['dbo_o_Trade', 'dbo_o_FeeItem', 'dbo_o_Diagnose'] as const
// 契约锚点：交易表必填（增量时间窗口 / 父子关联）
const ANCHOR_FIELDS: Record<string, string[]> = {
  dbo_o_Trade: ['T_TradeNo', 'T_TradeDate'],
}

function safeMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请稍后重试'
}

function Shell({ title, children, onClose, wide }: {
  title: string
  children: React.ReactNode
  onClose: () => void
  wide?: boolean
}) {
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4" role="presentation">
    <section role="dialog" aria-modal="true" aria-label={title}
      className={`max-h-[90dvh] w-full ${wide ? 'max-w-4xl' : 'max-w-2xl'} overflow-y-auto rounded-xl bg-white shadow-xl`}>
      <header className="sticky top-0 flex items-center justify-between border-b border-slate-200 bg-white px-5 py-4">
        <h2 className="font-semibold text-slate-900">{title}</h2>
        <button type="button" aria-label="关闭" onClick={onClose}
          className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100">✕</button>
      </header>
      {children}
    </section>
  </div>
}

/** 表探查弹窗：源库表清单（元数据 + 行数）→ 列详情（类型/可空/主键）。不回显样本值。 */
export function SourceExploreModal({ sourceId, onClose }: { sourceId: string; onClose: () => void }) {
  const [tables, setTables] = useState<SourceTable[]>([])
  const [selected, setSelected] = useState<SourceTable | null>(null)
  const [columns, setColumns] = useState<SourceColumn[]>([])
  const [loading, setLoading] = useState(true)
  const [columnsLoading, setColumnsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [keyword, setKeyword] = useState('')

  useEffect(() => {
    let cancelled = false
    exploreSourceTables(sourceId)
      .then((items) => { if (!cancelled) setTables(items) })
      .catch((reason) => { if (!cancelled) setError(safeMessage(reason)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [sourceId])

  const openTable = async (table: SourceTable) => {
    setSelected(table)
    setColumns([])
    setColumnsLoading(true)
    setError(null)
    try {
      setColumns(await exploreSourceTable(sourceId, table.table_schema, table.table_name))
    } catch (reason) {
      setError(safeMessage(reason))
    } finally {
      setColumnsLoading(false)
    }
  }

  const filtered = useMemo(
    () => tables.filter((item) => `${item.table_schema}.${item.table_name}`.toLowerCase().includes(keyword.toLowerCase())),
    [tables, keyword],
  )

  return <Shell title={`表探查 · ${sourceId}`} onClose={onClose} wide>
    <div className="space-y-4 p-5">
      {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</p>}
      <input
        aria-label="按表名筛选"
        className="h-9 w-full rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-blue-500"
        placeholder="按表名筛选…"
        value={keyword}
        onChange={(event) => setKeyword(event.target.value)}
      />
      {loading ? <p className="py-8 text-center text-sm text-slate-500">正在读取表清单…</p> : (
        <div className="max-h-56 overflow-y-auto rounded-lg border border-slate-200">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-slate-50 text-xs text-slate-600">
              <tr><th className="px-3 py-2 font-medium">Schema</th><th className="px-3 py-2 font-medium">表名</th><th className="px-3 py-2 text-right font-medium">行数</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((table) => <tr key={`${table.table_schema}.${table.table_name}`}
                className={`cursor-pointer hover:bg-blue-50 ${selected === table ? 'bg-blue-50' : ''}`}
                onClick={() => void openTable(table)}>
                <td className="px-3 py-2 font-mono text-xs text-slate-600">{table.table_schema}</td>
                <td className="px-3 py-2 font-mono text-slate-900">{table.table_name}</td>
                <td className="px-3 py-2 text-right tabular-nums text-slate-600">{table.row_count.toLocaleString()}</td>
              </tr>)}
            </tbody>
          </table>
        </div>
      )}
      {selected && <div>
        <h3 className="mb-2 text-sm font-semibold text-slate-900">{selected.table_schema}.{selected.table_name} 的列</h3>
        {columnsLoading ? <p className="py-4 text-center text-sm text-slate-500">读取列元数据…</p> : (
          <div className="max-h-60 overflow-y-auto rounded-lg border border-slate-200">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-slate-50 text-xs text-slate-600">
                <tr><th className="px-3 py-2 font-medium">列名</th><th className="px-3 py-2 font-medium">类型</th><th className="px-3 py-2 font-medium">可空</th><th className="px-3 py-2 font-medium">主键</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {columns.map((column) => <tr key={column.name}>
                  <td className="px-3 py-1.5 font-mono text-xs text-slate-900">{column.name}</td>
                  <td className="px-3 py-1.5 font-mono text-xs text-slate-600">{column.data_type}</td>
                  <td className="px-3 py-1.5 text-slate-600">{column.is_nullable ? '是' : '否'}</td>
                  <td className="px-3 py-1.5">{column.is_primary_key && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800">主键</span>}</td>
                </tr>)}
              </tbody>
            </table>
          </div>
        )}
      </div>}
    </div>
  </Shell>
}

/** 字段映射弹窗：选表 → 契约字段 ↔ 源列映射（自动同名匹配）→ 主键 → SQL 预览 → 保存。 */
export function SourceMappingModal({ sourceId, onClose, onSaved }: {
  sourceId: string
  onClose: () => void
  onSaved: (message: string) => void
}) {
  const [captured, setCaptured] = useState<Record<string, CaptureMapping> | null>(null)
  // 契约字段全集（默认映射加载时固定），未映射项以空值展示，避免字段从列表消失无法重新映射
  const [contractFields, setContractFields] = useState<Record<string, string[]>>({})
  const [revision, setRevision] = useState(1)
  const [tables, setTables] = useState<SourceTable[]>([])
  const [columnsCache, setColumnsCache] = useState<Record<string, SourceColumn[]>>({})
  const [activeCapture, setActiveCapture] = useState<string>('dbo_o_Trade')
  const [preview, setPreview] = useState<MappingSqlPreview | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const [mapping, tableList] = await Promise.all([
          getSourceMapping(sourceId),
          exploreSourceTables(sourceId),
        ])
        if (cancelled) return
        setCaptured(mapping.captures)
        setRevision(mapping.revision)
        setTables(tableList)
        setContractFields(Object.fromEntries(
          Object.entries(mapping.captures).map(([capture, item]) => [
            capture, Object.keys(item.column_map),
          ]),
        ))
        // 鄂取各 capture 当前表的列，供映射下拉与主键展示
        for (const item of Object.values(mapping.captures)) {
          try {
            const columns = await exploreSourceTable(
              sourceId, item.table_schema, item.table_name,
            )
            if (!cancelled) {
              setColumnsCache((cache) => ({
                ...cache,
                [`${item.table_schema}.${item.table_name}`]: columns,
              }))
            }
          } catch {
            // 单表列加载失败不阻塞弹窗，换表时再试
          }
        }
      } catch (reason) {
        if (!cancelled) setError(safeMessage(reason))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [sourceId])

  const ensureColumns = useCallback(async (schema: string, table: string): Promise<SourceColumn[]> => {
    const key = `${schema}.${table}`
    if (columnsCache[key]) return columnsCache[key]
    const columns = await exploreSourceTable(sourceId, schema, table)
    setColumnsCache((cache) => ({ ...cache, [key]: columns }))
    return columns
  }, [columnsCache, sourceId])

  if (loading || !captured) return <Shell title={`字段映射 · ${sourceId}`} onClose={onClose}>
    <p className="p-8 text-center text-sm text-slate-500">{error ?? '正在读取映射配置…'}</p>
  </Shell>

  const current = captured[activeCapture]
  const currentColumns = columnsCache[`${current.table_schema}.${current.table_name}`] ?? []
  const currentKey = `${current.table_schema}.${current.table_name}`

  const updateCapture = (patch: Partial<CaptureMapping>) => {
    setCaptured((items) => ({ ...items, [activeCapture]: { ...current, ...patch } }))
    setPreview(null)
  }

  const selectTable = async (option: string) => {
    const [schema, ...rest] = option.split('.')
    const tableName = rest.join('.')
    updateCapture({ table_schema: schema, table_name: tableName })
    try {
      const columns = await ensureColumns(schema, tableName)
      // 自动同名匹配（大小写不敏感）
      const byLower = new Map(columns.map((column) => [column.name.toLowerCase(), column.name]))
      const columnMap: Record<string, string> = {}
      for (const field of Object.keys(current.column_map)) {
        const hit = byLower.get(field.toLowerCase())
        if (hit) columnMap[field] = hit
      }
      const anchors = ANCHOR_FIELDS[activeCapture] ?? ['T_TradeNo']
      for (const anchor of anchors) {
        if (!columnMap[anchor]) {
          const hit = byLower.get(anchor.toLowerCase())
          if (hit) columnMap[anchor] = hit
        }
      }
      updateCapture({
        table_schema: schema, table_name: tableName,
        column_map: columnMap,
        key_fields: current.key_fields.filter((field) => columnMap[field]),
      })
    } catch (reason) {
      setError(safeMessage(reason))
    }
  }

  const setFieldMapping = (field: string, column: string) => {
    const columnMap = { ...current.column_map }
    if (column) columnMap[field] = column
    else delete columnMap[field]
    updateCapture({
      column_map: columnMap,
      key_fields: current.key_fields.filter((item) => columnMap[item]),
    })
  }

  const toggleKeyField = (field: string) => {
    const keys = current.key_fields.includes(field)
      ? current.key_fields.filter((item) => item !== field)
      : [...current.key_fields, field]
    updateCapture({ key_fields: keys })
  }

  const draftCaptures = (): CaptureMapping[] => CAPTURE_ORDER.map(
    (capture) => captured[capture],
  )

  const runPreview = async () => {
    setBusy('preview')
    setError(null)
    try {
      setPreview(await getMappingSqlPreview(sourceId, draftCaptures()))
    } catch (reason) {
      setError(safeMessage(reason))
    } finally {
      setBusy(null)
    }
  }

  const save = async () => {
    setBusy('save')
    setError(null)
    try {
      const saved = await saveSourceMapping(sourceId, draftCaptures(), revision)
      setRevision(saved.revision)
      onSaved('字段映射已保存，SQL 预览与定时同步将按新映射执行')
    } catch (reason) {
      setError(safeMessage(reason))
    } finally {
      setBusy(null)
    }
  }

  const anchors = ANCHOR_FIELDS[activeCapture] ?? ['T_TradeNo']
  const mappedFields = Object.keys(current.column_map)

  return <Shell title={`字段映射 · ${sourceId}`} onClose={onClose} wide>
    <div className="space-y-4 p-5">
      {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</p>}

      <div className="flex gap-1 rounded-lg bg-slate-100 p-1">
        {CAPTURE_ORDER.map((capture) => (
          <button key={capture} type="button"
            onClick={() => { setActiveCapture(capture); setPreview(null) }}
            className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${activeCapture === capture ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'}`}>
            {CAPTURE_LABELS[capture]}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="grid flex-1 gap-1.5 text-sm font-medium text-slate-700">
          <span>源表（{current.table_schema}）</span>
          <select className="h-9 rounded-lg border border-slate-300 bg-white px-3 text-sm"
            value={currentKey}
            onChange={(event) => void selectTable(event.target.value)}>
            <option value={currentKey}>{currentKey}</option>
            {tables.map((table) => {
              const key = `${table.table_schema}.${table.table_name}`
              return key === currentKey ? null : <option key={key} value={key}>{key}（{table.row_count.toLocaleString()} 行）</option>
            })}
          </select>
        </label>
        <Button type="button" variant="outline" disabled={busy !== null}
          onClick={() => void selectTable(currentKey)}>自动同名匹配</Button>
      </div>

      <div>
        <p className="mb-1.5 text-sm font-medium text-slate-700">主键（决定排序与快照对比键）</p>
        <div className="flex flex-wrap gap-2">
          {mappedFields.length === 0 && <span className="text-xs text-slate-500">先映射字段</span>}
          {mappedFields.map((field) => (
            <label key={field} className={`inline-flex cursor-pointer items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium ${current.key_fields.includes(field) ? 'border-amber-300 bg-amber-50 text-amber-800' : 'border-slate-200 bg-white text-slate-600'}`}>
              <input type="checkbox" className="accent-amber-600"
                checked={current.key_fields.includes(field)}
                onChange={() => toggleKeyField(field)} />
              <span className="font-mono">{field}</span>
            </label>
          ))}
        </div>
      </div>

      <div>
        <p className="mb-1.5 text-sm font-medium text-slate-700">
          字段映射（契约字段 → 源列；{anchors.map((anchor) => <span key={anchor} className="mx-0.5 rounded bg-red-50 px-1 font-mono text-xs text-red-700">{anchor}</span>)} 为必填锚点）
        </p>
        <div className="max-h-64 overflow-y-auto rounded-lg border border-slate-200">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-slate-50 text-xs text-slate-600">
              <tr><th className="px-3 py-2 font-medium">契约字段</th><th className="px-3 py-2 font-medium">源列</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {contractFields[activeCapture]?.map((field) => {
                const required = anchors.includes(field)
                return <tr key={field}>
                  <td className="px-3 py-1.5 font-mono text-xs text-slate-900">
                    {field}{required && <span className="ml-1.5 rounded bg-red-50 px-1 text-[10px] font-medium text-red-700">必填</span>}
                  </td>
                  <td className="px-3 py-1.5">
                    <select className="h-7 w-full min-w-40 rounded-md border border-slate-300 bg-white px-2 text-xs font-mono"
                      value={current.column_map[field] ?? ''}
                      onChange={(event) => setFieldMapping(field, event.target.value)}>
                      <option value="">（未映射）</option>
                      {currentColumns.map((column) => (
                        <option key={column.name} value={column.name}>{column.name} · {column.data_type}</option>
                      ))}
                    </select>
                  </td>
                </tr>
              })}
            </tbody>
          </table>
        </div>
        {currentColumns.length === 0 && <p className="mt-1 text-xs text-slate-500">选择源表后加载列清单（当前表尚未加载）。</p>}
      </div>

      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" disabled={busy !== null} onClick={() => void runPreview()}>SQL 预览</Button>
        <Button type="button" disabled={busy !== null || current.key_fields.length === 0} onClick={() => void save()}>保存映射</Button>
      </div>

      {preview && <div className="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
        <p className="text-xs font-medium text-slate-600">基线快照 SQL（{preview.is_default ? '默认契约' : `映射 v${preview.mapping_revision}`}）</p>
        {preview.baseline_sql.map((sql) => <pre key={sql.slice(0, 60)} className="overflow-x-auto rounded bg-white p-2 text-[11px] leading-relaxed text-slate-800">{sql}</pre>)}
        <p className="text-xs font-medium text-slate-600">增量时间窗口 SQL（按任务配置周期执行）</p>
        <pre className="overflow-x-auto rounded bg-white p-2 text-[11px] leading-relaxed text-slate-800">{preview.incremental_window_sql}</pre>
        <p className="text-xs font-medium text-slate-600">子表关联 SQL（按交易号 IN，示例 3 个占位）</p>
        {preview.incremental_children_sql.map((sql) => <pre key={sql.slice(0, 60)} className="overflow-x-auto rounded bg-white p-2 text-[11px] leading-relaxed text-slate-800">{sql}</pre>)}
      </div>}
    </div>
  </Shell>
}
