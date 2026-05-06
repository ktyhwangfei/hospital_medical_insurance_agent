'use client'

import { useState } from 'react'
import { Activity, Database, MessageSquare, Server, ShieldCheck, Wrench } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { fetchMcpStorageHealth, initialMcpServers, registerMcpServer } from '@/lib/api-client'
import { useApiContext } from '@/lib/api-context'
import { mockMcpCapabilities } from '@/lib/mock-data'
import type { McpServer, McpServerStatus, McpStorageHealth, McpTransport } from '@/lib/types'

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
  const [health, setHealth] = useState<McpStorageHealth | null>(null)
  const [form, setForm] = useState<McpServerForm>(emptyForm)
  const [error, setError] = useState<string | null>(null)
  const [isCheckingHealth, setIsCheckingHealth] = useState(false)
  const [isRegistering, setIsRegistering] = useState(false)

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
    </div>
  )
}
