'use client'

import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Database, Download, KeyRound, Pencil, PlugZap, RefreshCw, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  SourceExploreModal,
  SourceMappingModal,
} from '@/components/data-governance-source-tools'
import {
  checkDataSourceCdc,
  createDataSource,
  downloadCdcScript,
  getPostgresTargetStatus,
  hasDataGovernancePermission,
  listDataSources,
  rotateDataSourceCredential,
  testDataSourceConnection,
  updateDataSource,
  type CreateDataSourceInput,
  type DataSource,
  type PostgresTarget,
} from '@/lib/data-governance-api'

const emptyForm: CreateDataSourceInput = {
  sourceId: '', hospitalCode: '', hospitalName: '', name: '', host: '', port: 1433,
  database: '', username: '', credentialId: '', password: '',
}
const connectionLabel = { unknown: '未检测', healthy: '连接正常', error: '连接异常' }
const cdcLabel = { not_applicable: '不适用', not_checked: '未检测', waiting_dba: '等待 DBA', ready: 'CDC 已就绪', invalid: '配置异常' }

function safeMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请稍后重试'
}

function maskedEndpoint(source: DataSource): string {
  const parts = source.host.split('.')
  const host = parts.length === 4 ? `${parts[0]}.${parts[1]}.*.*` : source.host.replace(/^(.{2}).*(.{2})$/, '$1***$2')
  return `${host}:${source.port} / ${source.database}`
}

function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4" role="presentation">
    <section role="dialog" aria-modal="true" aria-label={title} className="max-h-[90dvh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white shadow-xl">
      <header className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
        <h2 className="font-semibold text-slate-900">{title}</h2>
        <button type="button" aria-label="关闭" onClick={onClose} className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100"><X className="size-4" /></button>
      </header>
      {children}
    </section>
  </div>
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="grid gap-1.5 text-sm font-medium text-slate-700"><span>{label}</span>{children}</label>
}

const inputClass = 'h-9 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100'

export default function DataSourcesPage() {
  const [sources, setSources] = useState<DataSource[]>([])
  const [postgres, setPostgres] = useState<PostgresTarget | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [editing, setEditing] = useState<DataSource | 'new' | null>(null)
  const [form, setForm] = useState<CreateDataSourceInput>(emptyForm)
  const [rotating, setRotating] = useState<DataSource | null>(null)
  const [newPassword, setNewPassword] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [canWrite, setCanWrite] = useState(false)
  const [exploring, setExploring] = useState<DataSource | null>(null)
  const [mappingSource, setMappingSource] = useState<DataSource | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [items, target] = await Promise.all([listDataSources(), getPostgresTargetStatus()])
      setSources(items)
      setPostgres(target)
      setError(null)
    } catch (reason) {
      setError(safeMessage(reason))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => { void load() }, 0)
    return () => window.clearTimeout(timer)
  }, [load])

  useEffect(() => {
    const timer = window.setTimeout(() => setCanWrite(hasDataGovernancePermission('write')), 0)
    return () => window.clearTimeout(timer)
  }, [])

  const openCreate = () => {
    setForm(emptyForm)
    setEditing('new')
  }

  const openEdit = (source: DataSource) => {
    setForm({
      sourceId: source.sourceId, hospitalCode: source.hospitalCode, hospitalName: source.hospitalName,
      name: source.name, host: source.host, port: source.port, database: source.database,
      username: source.username, credentialId: source.credentialId, password: '',
    })
    setEditing(source)
  }

  const save = async (event: FormEvent) => {
    event.preventDefault()
    setBusy('save')
    setError(null)
    try {
      let saved: DataSource
      if (editing === 'new') {
        saved = await createDataSource(form)
      } else if (editing) {
        const endpointChanged = form.host !== editing.host || form.port !== editing.port
          || form.database !== editing.database || form.username !== editing.username
        if (endpointChanged && !form.password) throw new Error('端点发生变化，请同时重新输入密码')
        saved = await updateDataSource(editing.sourceId, form)
        if (endpointChanged) {
          saved = await rotateDataSourceCredential(
            editing.sourceId, editing.credentialId, form.password, editing.credentialRevision ?? 1,
          )
        }
      } else {
        return
      }
      setSources((items) => [saved, ...items.filter((item) => item.sourceId !== saved.sourceId)])
      setForm(emptyForm)
      setEditing(null)
      setMessage('数据源已保存')
    } catch (reason) {
      setError(safeMessage(reason))
    } finally {
      setBusy(null)
    }
  }

  const act = async (sourceId: string, action: 'test' | 'download' | 'check') => {
    setBusy(`${sourceId}:${action}`)
    setError(null)
    try {
      if (action === 'test') {
        const result = await testDataSourceConnection(sourceId)
        setMessage(result.safeMessage)
        setSources((items) => items.map((item) => item.sourceId === sourceId ? { ...item, connectionStatus: result.status, safeProbeMessage: result.safeMessage } : item))
      } else if (action === 'download') {
        await downloadCdcScript(sourceId)
        setMessage('等待 DBA 执行脚本')
        setSources((items) => items.map((item) => item.sourceId === sourceId ? { ...item, cdcStatus: 'waiting_dba' } : item))
      } else {
        const result = await checkDataSourceCdc(sourceId)
        setMessage(result.safeMessage)
        setSources((items) => items.map((item) => item.sourceId === sourceId ? { ...item, cdcStatus: result.status as DataSource['cdcStatus'] } : item))
      }
    } catch (reason) {
      setError(safeMessage(reason))
    } finally {
      setBusy(null)
    }
  }

  const rotate = async (event: FormEvent) => {
    event.preventDefault()
    if (!rotating) return
    setBusy('rotate')
    try {
      const saved = await rotateDataSourceCredential(rotating.sourceId, rotating.credentialId, newPassword, rotating.credentialRevision ?? 1)
      setSources((items) => items.map((item) => item.sourceId === saved.sourceId ? saved : item))
      setNewPassword('')
      setRotating(null)
      setMessage('凭据已更新')
    } catch (reason) {
      setError(safeMessage(reason))
    } finally {
      setBusy(null)
    }
  }

  return <div className="space-y-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="font-semibold text-slate-900">SQL Server 数据源</h2><p className="mt-1 text-sm text-slate-600">密码只在提交时传输，页面和接口响应均不回显。</p></div>
      {canWrite && <Button onClick={openCreate}>新增数据源</Button>}
    </div>

    {(message || error) && <div role={error ? 'alert' : 'status'} className={`rounded-lg border px-4 py-3 text-sm ${error ? 'border-red-200 bg-red-50 text-red-800' : 'border-emerald-200 bg-emerald-50 text-emerald-800'}`}>{error ?? message}</div>}

    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-3">
        <Database className="size-5 text-blue-600" />
        <div className="flex-1"><h2 className="font-semibold text-slate-900">PostgreSQL 目标库</h2><p className="mt-0.5 text-xs text-slate-500">门诊标准化数据、批次和检查点的落库目标</p></div>
        <span className={`rounded-md px-2 py-1 text-xs font-medium ${postgres?.connectionStatus === 'healthy' && postgres.schemaReady ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>{postgres?.safeMessage ?? '检测中'}</span>
      </div>
    </section>

    {loading ? <p className="py-10 text-center text-sm text-slate-500">正在读取数据源...</p> : sources.length === 0 ? <section className="rounded-xl border border-dashed border-slate-300 bg-white py-12 text-center"><p className="font-medium text-slate-800">暂无数据源</p><p className="mt-1 text-sm text-slate-500">点击“新增数据源”登记第一家医院。</p></section> : <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="overflow-x-auto"><table className="w-full min-w-[980px] text-left text-sm">
        <thead className="bg-slate-50 text-xs text-slate-600"><tr><th className="px-4 py-3 font-medium">医院</th><th className="px-4 py-3 font-medium">端点</th><th className="px-4 py-3 font-medium">凭据</th><th className="px-4 py-3 font-medium">门诊源表</th><th className="px-4 py-3 font-medium">CDC</th><th className="px-4 py-3 font-medium">操作</th></tr></thead>
        <tbody className="divide-y divide-slate-100">{sources.map((source) => <tr key={source.sourceId}>
          <td className="px-4 py-3"><p className="font-medium text-slate-900">{source.hospitalName}</p><p className="text-xs text-slate-500">{source.name} ({source.sourceId})</p></td>
          <td className="px-4 py-3 font-mono text-xs text-slate-700">{maskedEndpoint(source)}</td>
          <td className="px-4 py-3"><span className={source.credentialConfigured ? 'text-emerald-700' : 'text-red-700'}>{source.credentialConfigured ? '凭据已配置' : '需重新提交凭据'}</span></td>
          <td className="px-4 py-3"><p>{connectionLabel[source.connectionStatus]}</p>{source.safeProbeMessage && <p className="mt-0.5 max-w-64 text-xs text-slate-500">{source.safeProbeMessage}</p>}</td><td className="px-4 py-3">{cdcLabel[source.cdcStatus]}</td>
          <td className="px-4 py-3">{canWrite && <div className="flex flex-wrap gap-1.5">
            <Button size="sm" variant="outline" aria-label="编辑数据源" onClick={() => openEdit(source)}><Pencil /></Button>
            <Button size="sm" variant="outline" aria-label="轮换凭据" onClick={() => setRotating(source)}><KeyRound /></Button>
            <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => setExploring(source)}>表探查</Button>
            <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => setMappingSource(source)}>字段映射</Button>
            <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => void act(source.sourceId, 'test')}><PlugZap />测试连接</Button>
            <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => void act(source.sourceId, 'download')}><Download />下载 CDC 脚本</Button>
            <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => void act(source.sourceId, 'check')}><RefreshCw />重新检测 CDC</Button>
          </div>}</td>
        </tr>)}</tbody>
      </table></div>
    </section>}

    {editing && <Modal title={editing === 'new' ? '新增数据源' : '编辑数据源'} onClose={() => setEditing(null)}>
      <form onSubmit={save} className="grid gap-4 p-5 sm:grid-cols-2">
        <Field label="数据源 ID"><input className={inputClass} required disabled={editing !== 'new'} value={form.sourceId} onChange={(e) => setForm({ ...form, sourceId: e.target.value })} /></Field>
        <Field label="医院编码"><input className={inputClass} required value={form.hospitalCode} onChange={(e) => setForm({ ...form, hospitalCode: e.target.value })} /></Field>
        <Field label="医院名称"><input className={inputClass} required value={form.hospitalName} onChange={(e) => setForm({ ...form, hospitalName: e.target.value })} /></Field>
        <Field label="数据源名称"><input className={inputClass} required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="主机"><input className={inputClass} required value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} /></Field>
        <Field label="端口"><input className={inputClass} required type="number" min={1} max={65535} value={form.port} onChange={(e) => setForm({ ...form, port: Number(e.target.value) })} /></Field>
        <Field label="数据库"><input className={inputClass} required value={form.database} onChange={(e) => setForm({ ...form, database: e.target.value })} /></Field>
        <Field label="用户名"><input className={inputClass} required value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></Field>
        <Field label="凭据 ID"><input className={inputClass} required disabled={editing !== 'new'} value={form.credentialId} onChange={(e) => setForm({ ...form, credentialId: e.target.value })} /></Field>
        <Field label="密码"><input aria-label="密码" className={inputClass} required={editing === 'new'} type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /><span className="text-xs font-normal text-slate-500">编辑端点时必须重新输入，其他修改请留空。</span></Field>
        <div className="flex justify-end gap-2 sm:col-span-2"><Button type="button" variant="outline" onClick={() => setEditing(null)}>取消</Button><Button type="submit" disabled={busy !== null}>保存数据源</Button></div>
      </form>
    </Modal>}

    {rotating && <Modal title="轮换数据源凭据" onClose={() => setRotating(null)}><form onSubmit={rotate} className="space-y-4 p-5"><Field label="新密码"><input className={inputClass} required type="password" autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} /></Field><div className="flex justify-end gap-2"><Button type="button" variant="outline" onClick={() => setRotating(null)}>取消</Button><Button type="submit" disabled={busy !== null}>更新凭据</Button></div></form></Modal>}

    {exploring && <SourceExploreModal sourceId={exploring.sourceId} onClose={() => setExploring(null)} />}
    {mappingSource && <SourceMappingModal
      sourceId={mappingSource.sourceId}
      onClose={() => setMappingSource(null)}
      onSaved={(text) => { setMappingSource(null); setMessage(text); void load() }}
    />}
  </div>
}
