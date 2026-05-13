'use client'

import { useState, useEffect } from 'react'
import { Activity, Database, MessageSquare, Server, ShieldCheck, Trash2, Plus, Wrench } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogTrigger,
  DialogClose,
} from '@/components/ui/dialog'
import {
  fetchMcpStorageHealth,
  initialMcpServers,
  registerMcpServer,
  listCapabilities,
  createCapability,
  deleteCapability,
} from '@/lib/api-client'
import { useApiContext } from '@/lib/api-context'
import { mockMcpCapabilities } from '@/lib/mock-data'
import type { McpCapability, McpCapabilityCreate, McpServer, McpServerStatus, McpStorageHealth, McpTransport } from '@/lib/types'

const statusColors: Record<McpServerStatus, string> = {
  enabled: 'bg-green-100 text-green-800',
  disabled: 'bg-gray-100 text-gray-800',
  degraded: 'bg-yellow-100 text-yellow-800',
  unhealthy: 'bg-red-100 text-red-800',
}

const statusLabels: Record<McpServerStatus, string> = {
  enabled: '已启用',
  disabled: '已禁用',
  degraded: '降级',
  unhealthy: '异常',
}

const capabilityIcons = [Wrench, Database, MessageSquare, ShieldCheck] as const

interface McpServerForm {
  server_id: string
  name: string
  endpoint: string
  transport: McpTransport
}

const emptyForm: McpServerForm = {
  server_id: '',
  name: '',
  endpoint: '',
  transport: 'sse',
}

const emptyCapabilityForm = {
  capability_id: '',
  server_id: '',
  capability_type: 'Tool',
  risk_level: 'LOW',
  payload_json: '',
}

function createServerPayload(form: McpServerForm): McpServer {
  return {
    server_id: form.server_id.trim(),
    name: form.name.trim(),
    endpoint: form.endpoint.trim(),
    transport: form.transport,
    status: 'enabled',
    protocol_version: '2025-03-26',
    auth_headers: {},
    metadata: {},
  }
}

export default function McpManagement() {
  const { setConnected, setFallback } = useApiContext()
  const [servers, setServers] = useState<McpServer[]>(() => initialMcpServers())
  const [capabilities, setCapabilities] = useState<McpCapability[]>([])
  const [health, setHealth] = useState<McpStorageHealth | null>(null)
  const [form, setForm] = useState<McpServerForm>(emptyForm)
  const [error, setError] = useState<string | null>(null)
  const [isCheckingHealth, setIsCheckingHealth] = useState(false)
  const [isRegistering, setIsRegistering] = useState(false)
  const [capDialogOpen, setCapDialogOpen] = useState(false)
  const [capForm, setCapForm] = useState(emptyCapabilityForm)
  const [capFormError, setCapFormError] = useState<string | null>(null)
  const [isCreatingCap, setIsCreatingCap] = useState(false)
  const [deleteCapId, setDeleteCapId] = useState<string | null>(null)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [isDeletingCap, setIsDeletingCap] = useState(false)
  const [capFilterServer, setCapFilterServer] = useState<string>('all')

  // Load capabilities on mount
  useEffect(() => {
    loadCapabilities()
  }, [])

  const loadCapabilities = async () => {
    try {
      const data = await listCapabilities()
      setCapabilities(data)
      if (Array.isArray(data)) {
        setConnected()
      }
    } catch {
      // Silently handle - capabilities may not be available
    }
  }

  const updateForm = (field: keyof McpServerForm, value: string | null) => {
    if (value === null) {
      return
    }

    setForm((current) => ({
      ...current,
      [field]: field === 'transport' ? (value as McpTransport) : value,
    }))
  }

  const loadHealth = async () => {
    setError(null)
    setIsCheckingHealth(true)

    try {
      const result = await fetchMcpStorageHealth()
      setHealth(result)

      if (result.fallback) {
        setFallback()
      } else {
        setConnected()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '健康检查失败')
    } finally {
      setIsCheckingHealth(false)
    }
  }

  const submit = async () => {
    setError(null)

    if (!form.server_id.trim() || !form.name.trim() || !form.endpoint.trim()) {
      setError('服务ID、名称和端点不能为空')
      return
    }

    setIsRegistering(true)

    try {
      const registered = await registerMcpServer(createServerPayload(form))
      setServers((current) => [
        registered,
        ...current.filter((server) => server.server_id !== registered.server_id),
      ])

      if (registered.fallback) {
        setFallback()
      } else {
        setConnected()
      }

      setForm(emptyForm)
    } catch (err) {
      setError(err instanceof Error ? err.message : '服务注册失败')
    } finally {
      setIsRegistering(false)
    }
  }

  const handleCreateCapability = async () => {
    setCapFormError(null)

    if (!capForm.capability_id.trim() || !capForm.server_id.trim()) {
      setCapFormError('能力ID和服务ID不能为空')
      return
    }

    setIsCreatingCap(true)

    try {
      const payload: McpCapabilityCreate = {
        capability_id: capForm.capability_id.trim(),
        server_id: capForm.server_id.trim(),
        capability_type: capForm.capability_type,
        risk_level: capForm.risk_level,
      }

      if (capForm.payload_json.trim()) {
        try {
          payload.payload_json = JSON.parse(capForm.payload_json.trim())
        } catch {
          setCapFormError('payload_json 格式无效，请输入合法 JSON')
          setIsCreatingCap(false)
          return
        }
      }

      const result = await createCapability(payload)
      setCapabilities((current) => [result, ...current])
      setCapDialogOpen(false)
      setCapForm(emptyCapabilityForm)
      setConnected()
    } catch (err) {
      setCapFormError(err instanceof Error ? err.message : '能力注册失败')
    } finally {
      setIsCreatingCap(false)
    }
  }

  const handleDeleteCapability = async () => {
    if (!deleteCapId) return

    setIsDeletingCap(true)

    try {
      await deleteCapability(deleteCapId)
      setCapabilities((current) => current.filter((c: any) => c.capability_id !== deleteCapId))
      setDeleteDialogOpen(false)
      setDeleteCapId(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除能力失败')
    } finally {
      setIsDeletingCap(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">MCP 服务管理</h2>
          <p className="text-sm text-gray-500 mt-1">注册、检查和浏览院端 MCP 能力</p>
        </div>
        <Badge className="bg-blue-100 text-blue-800">{servers.length}个服务</Badge>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {mockMcpCapabilities.map((capability, index) => {
          const Icon = capabilityIcons[index % capabilityIcons.length]

          return (
            <Card key={capability.id}>
              <CardContent className="p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-gray-500">{capability.type}</p>
                    <p className={`text-2xl font-bold mt-1 ${capability.color}`}>{capability.count}</p>
                  </div>
                  <div className="p-3 rounded-lg bg-gray-50">
                    <Icon className={`w-6 h-6 ${capability.color}`} />
                  </div>
                </div>
                <p className="text-sm text-gray-700 mt-3">{capability.name}</p>
                <Badge variant="outline" className="mt-2">
                  演示数据
                </Badge>
              </CardContent>
            </Card>
          )
        })}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Server className="w-5 h-5" />
              服务注册
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input
              placeholder="server_id"
              value={form.server_id}
              onChange={(event) => updateForm('server_id', event.target.value)}
            />
            <Input
              placeholder="服务名称"
              value={form.name}
              onChange={(event) => updateForm('name', event.target.value)}
            />
            <Input
              placeholder="endpoint"
              value={form.endpoint}
              onChange={(event) => updateForm('endpoint', event.target.value)}
            />
            <Select value={form.transport} onValueChange={(value) => updateForm('transport', value)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="sse">sse</SelectItem>
                <SelectItem value="streamable_http">streamable_http</SelectItem>
                <SelectItem value="stdio">stdio</SelectItem>
              </SelectContent>
            </Select>
            <Button onClick={submit} disabled={isRegistering} className="w-full">
              {isRegistering ? '注册中...' : '注册服务'}
            </Button>
            {error && <p className="text-sm text-red-600">{error}</p>}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center justify-between gap-4">
              <span className="flex items-center gap-2">
                <Activity className="w-5 h-5" />
                存储健康检查
              </span>
              <Button variant="outline" size="sm" onClick={loadHealth} disabled={isCheckingHealth}>
                {isCheckingHealth ? '检查中...' : '查看存储状态'}
              </Button>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="bg-slate-900 text-blue-100 rounded-lg p-4 overflow-auto text-sm min-h-[160px]">
              {health ? JSON.stringify(health, null, 2) : '等待操作'}
            </pre>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="w-5 h-5" />
            MCP 服务列表
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          {servers.map((server) => (
            <Card key={server.server_id} className="p-6 hover:shadow-lg transition-shadow">
              <div className="flex items-start justify-between gap-4">
                <div className="space-y-2 min-w-0">
                  <div className="flex flex-wrap items-center gap-3">
                    <h3 className="text-lg font-semibold">{server.name}</h3>
                    <Badge className={statusColors[server.status]}>{statusLabels[server.status]}</Badge>
                    {server.fallback && <Badge variant="outline">离线模式</Badge>}
                  </div>
                  <p className="text-sm text-gray-600">
                    <span className="font-medium">服务ID:</span> {server.server_id}
                  </p>
                  <p className="text-sm text-gray-800 break-all">
                    <span className="font-medium">endpoint:</span> {server.endpoint}
                  </p>
                </div>
                <Badge variant="outline">{server.transport}</Badge>
              </div>
            </Card>
          ))}
        </CardContent>
      </Card>

      {/* Capabilities CRUD Section */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="w-5 h-5" />
              MCP 能力管理
            </CardTitle>
            <div className="flex items-center gap-2">
              <Select value={capFilterServer} onValueChange={(v) => { if (v !== null) setCapFilterServer(v) }}>
                <SelectTrigger className="w-[180px]">
                  <SelectValue placeholder="按服务筛选" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部服务</SelectItem>
                  {servers.map((s) => (
                    <SelectItem key={s.server_id} value={s.server_id}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Dialog open={capDialogOpen} onOpenChange={setCapDialogOpen}>
                <DialogTrigger render={<Button size="sm" />}>
                  <Plus className="w-4 h-4" />
                  注册能力
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>注册 MCP 能力</DialogTitle>
                    <DialogDescription>
                      填写能力信息，注册新的 MCP 能力到系统中。
                    </DialogDescription>
                  </DialogHeader>
                  <div className="space-y-3">
                    <Input
                      placeholder="能力ID (capability_id)"
                      value={capForm.capability_id}
                      onChange={(e) => setCapForm((f) => ({ ...f, capability_id: e.target.value }))}
                    />
                    <Select
                      value={capForm.server_id}
                      onValueChange={(val) => { if (val !== null) setCapForm((f) => ({ ...f, server_id: val })) }}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="选择所属服务" />
                      </SelectTrigger>
                      <SelectContent>
                        {servers.map((s) => (
                          <SelectItem key={s.server_id} value={s.server_id}>
                            {s.name} ({s.server_id})
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Select
                      value={capForm.capability_type}
                      onValueChange={(val) => { if (val !== null) setCapForm((f) => ({ ...f, capability_type: val })) }}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="能力类型" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="Tool">Tool</SelectItem>
                        <SelectItem value="Resource">Resource</SelectItem>
                        <SelectItem value="Prompt">Prompt</SelectItem>
                      </SelectContent>
                    </Select>
                    <Select
                      value={capForm.risk_level}
                      onValueChange={(val) => { if (val !== null) setCapForm((f) => ({ ...f, risk_level: val })) }}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="风险等级" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="LOW">低</SelectItem>
                        <SelectItem value="MEDIUM">中</SelectItem>
                        <SelectItem value="HIGH">高</SelectItem>
                      </SelectContent>
                    </Select>
                    <Textarea
                      placeholder="payload_json (可选，JSON 格式)"
                      value={capForm.payload_json}
                      onChange={(e) => setCapForm((f) => ({ ...f, payload_json: e.target.value }))}
                      rows={3}
                    />
                    {capFormError && <p className="text-sm text-red-600">{capFormError}</p>}
                  </div>
                  <DialogFooter>
                    <DialogClose render={<Button variant="outline" />}>
                      取消
                    </DialogClose>
                    <Button onClick={handleCreateCapability} disabled={isCreatingCap}>
                      {isCreatingCap ? '注册中...' : '确认注册'}
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {(() => {
            const filtered = capFilterServer === 'all'
              ? capabilities
              : capabilities.filter((c) => c.server_id === capFilterServer)
            return filtered.length === 0 ? (
              <div className="text-center py-8 text-gray-400">
                <ShieldCheck className="w-12 h-12 mx-auto mb-3 opacity-40" />
                <p className="text-sm">暂无能力数据</p>
                <p className="text-xs mt-1">点击右上角「注册能力」添加新的 MCP 能力</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200">
                      <th className="text-left py-3 px-3 font-medium text-gray-500">能力ID</th>
                      <th className="text-left py-3 px-3 font-medium text-gray-500">所属服务</th>
                      <th className="text-left py-3 px-3 font-medium text-gray-500">能力类型</th>
                      <th className="text-left py-3 px-3 font-medium text-gray-500">风险等级</th>
                      <th className="text-right py-3 px-3 font-medium text-gray-500">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((cap: McpCapability) => (
                      <tr key={cap.capability_id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                        <td className="py-3 px-3 font-mono text-xs">{cap.capability_id}</td>
                        <td className="py-3 px-3">{cap.server_id}</td>
                        <td className="py-3 px-3">
                          <Badge variant="outline">{cap.capability_type}</Badge>
                        </td>
                        <td className="py-3 px-3">
                          <Badge
                            className={
                              cap.risk_level === 'HIGH'
                                ? 'bg-red-100 text-red-800'
                                : cap.risk_level === 'MEDIUM'
                                  ? 'bg-yellow-100 text-yellow-800'
                                  : 'bg-green-100 text-green-800'
                            }
                          >
                            {cap.risk_level === 'HIGH' ? '高' : cap.risk_level === 'MEDIUM' ? '中' : '低'}
                          </Badge>
                        </td>
                        <td className="py-3 px-3 text-right">
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            className="text-red-500 hover:text-red-700 hover:bg-red-50"
                            onClick={() => {
                              setDeleteCapId(cap.capability_id)
                              setDeleteDialogOpen(true)
                            }}
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          })()}
        </CardContent>
      </Card>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认删除能力</DialogTitle>
            <DialogDescription>
              确定要删除能力 <span className="font-mono font-medium">{deleteCapId}</span> 吗？此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              取消
            </DialogClose>
            <Button
              variant="destructive"
              onClick={handleDeleteCapability}
              disabled={isDeletingCap}
            >
              {isDeletingCap ? '删除中...' : '确认删除'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
