'use client'

import { useEffect, useState } from 'react'
import {
  FlaskConical,
  Loader2,
  Network,
  Pencil,
  Plus,
  Server,
  Settings2,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import {
  getModelConfig,
  updateModelConfig,
  listModelRoutes,
  createModelRoute,
  updateModelRoute,
  deleteModelRoute,
  getModelFallbacks,
  updateModelFallbacks,
  getModelParams,
  updateModelParams,
  listModelProviders,
  createModelProvider,
  updateModelProvider,
  deleteModelProvider,
  testModelProvider,
} from '@/lib/api-client'
import { useApiContext } from '@/lib/api-context'
import ModelTest from './model-test'
import type {
  ModelConfig,
  ModelParams,
  ModelProviderCreate,
  ModelProviderResponse,
  ModelProviderTestResult,
  ModelRouteCreate,
  ModelRouteResponse,
} from '@/lib/types'

// --- Scenes & Labels ---

const SCENE_OPTIONS = [
  { value: 'default', label: '默认场景' },
  { value: 'settlement_exception', label: '结算异常' },
  { value: 'pre_discharge_qc', label: '出院前质控' },
  { value: 'drg_analysis', label: 'DRG 分析' },
] as const

const MODEL_TYPE_OPTIONS = [
  { value: 'llm', label: 'LLM' },
  { value: 'embedding', label: 'Embedding' },
  { value: 'rerank', label: 'Rerank' },
  { value: 'ocr', label: 'OCR' },
] as const

const PROVIDER_TYPE_OPTIONS = [
  { value: 'openai_compatible', label: 'OpenAI Compatible' },
] as const

// --- ModelConfigPanel ---

function ModelConfigPanel() {
  const { setConnected, setFallback } = useApiContext()
  const [config, setConfig] = useState<ModelConfig>({
    base_url: '',
    timeout: 30,
    max_retries: 3,
    default_model: '',
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  useEffect(() => {
    loadConfig()
  }, [])

  const loadConfig = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await getModelConfig()
      setConfig(result)
      if (result.fallback !== undefined) {
        // Use fallback marker pattern from existing APIs
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载配置失败')
    } finally {
      setLoading(false)
    }
  }

  const updateField = <K extends keyof ModelConfig>(field: K, value: ModelConfig[K]) => {
    setConfig((prev) => ({ ...prev, [field]: value }))
  }

  const save = async () => {
    setError(null)
    setSuccess(null)
    setSaving(true)
    try {
      const result = await updateModelConfig(config)
      setConfig(result)
      setSuccess('配置保存成功')
      if (result.fallback) {
        setFallback()
      } else {
        setConnected()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存配置失败')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
          <span className="ml-2 text-sm text-gray-500">加载配置中...</span>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Settings2 className="w-5 h-5" />
          模型服务配置
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">{error}</div>
        )}
        {success && (
          <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-lg text-sm">{success}</div>
        )}

        <div>
          <label className="text-sm font-medium text-gray-700 mb-1 block">Base URL</label>
          <Input
            value={config.base_url}
            onChange={(e) => updateField('base_url', e.target.value)}
            placeholder="https://api.example.com/v1"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-sm font-medium text-gray-700 mb-1 block">超时时间 (秒)</label>
            <Input
              type="number"
              min={1}
              value={config.timeout}
              onChange={(e) => updateField('timeout', Math.max(1, Number(e.target.value) || 1))}
            />
          </div>
          <div>
            <label className="text-sm font-medium text-gray-700 mb-1 block">最大重试次数</label>
            <Input
              type="number"
              min={0}
              value={config.max_retries}
              onChange={(e) => updateField('max_retries', Math.max(0, Number(e.target.value) || 0))}
            />
          </div>
        </div>

        <div>
          <label className="text-sm font-medium text-gray-700 mb-1 block">默认模型</label>
          <Input
            value={config.default_model}
            onChange={(e) => updateField('default_model', e.target.value)}
            placeholder="gpt-4o"
          />
        </div>

        <Button onClick={save} disabled={saving} className="w-full">
          {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
          {saving ? '保存中...' : '保存配置'}
        </Button>
      </CardContent>
    </Card>
  )
}

// --- ModelRouteCrud ---

interface RouteFormState {
  route_id: string
  scene: string
  model_type: string
  model_name: string
  priority: number
  enabled: boolean
}

const emptyRouteForm: RouteFormState = {
  route_id: '',
  scene: 'default',
  model_type: 'llm',
  model_name: '',
  priority: 10,
  enabled: true,
}

function ModelRouteCrud() {
  const { setConnected, setFallback } = useApiContext()
  const [routes, setRoutes] = useState<ModelRouteResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingRoute, setEditingRoute] = useState<ModelRouteResponse | null>(null)
  const [form, setForm] = useState<RouteFormState>(emptyRouteForm)
  const [submitting, setSubmitting] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)

  // Fallback chain state
  const [fallbackList, setFallbackList] = useState<string[]>([])
  const [fallbackDirty, setFallbackDirty] = useState(false)
  const [fallbackInput, setFallbackInput] = useState('')

  // Params state
  const [paramsJson, setParamsJson] = useState('')
  const [paramsDirty, setParamsDirty] = useState(false)

  useEffect(() => {
    loadRoutes()
  }, [])

  const loadRoutes = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await listModelRoutes()
      setRoutes(result.items)
      const hasFallback = result.items.some((r) => r.fallback)
      if (hasFallback) {
        setFallback()
      } else {
        setConnected()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载路由列表失败')
    } finally {
      setLoading(false)
    }
  }

  const openCreate = () => {
    setEditingRoute(null)
    setForm(emptyRouteForm)
    setFallbackList([])
    setFallbackDirty(false)
    setParamsJson('{}')
    setParamsDirty(false)
    setDialogOpen(true)
  }

  const openEdit = async (route: ModelRouteResponse) => {
    setEditingRoute(route)
    setForm({
      route_id: route.route_id,
      scene: route.scene,
      model_type: route.model_type,
      model_name: route.model_name,
      priority: route.priority,
      enabled: route.enabled,
    })

    // Load fallbacks for this model
    try {
      const result = await getModelFallbacks(route.model_name)
      setFallbackList(result.fallbacks)
    } catch {
      setFallbackList([])
    }
    setFallbackDirty(false)

    // Load params for this model
    try {
      const result = await getModelParams(route.model_name)
      setParamsJson(JSON.stringify(result, null, 2))
    } catch {
      setParamsJson('{}')
    }
    setParamsDirty(false)

    setDialogOpen(true)
  }

  const updateForm = <K extends keyof RouteFormState>(field: K, value: RouteFormState[K]) => {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  const addFallback = () => {
    const name = fallbackInput.trim()
    if (!name) return
    setFallbackList((prev) => [...prev, name])
    setFallbackInput('')
    setFallbackDirty(true)
  }

  const removeFallback = (index: number) => {
    setFallbackList((prev) => prev.filter((_, i) => i !== index))
    setFallbackDirty(true)
  }

  const submit = async () => {
    setError(null)

    if (!form.model_name.trim()) {
      setError('模型名称不能为空')
      return
    }

    setSubmitting(true)
    try {
      const payload: ModelRouteCreate = {
        scene: form.scene,
        model_type: form.model_type,
        model_name: form.model_name.trim(),
        priority: form.priority,
        enabled: form.enabled,
      }

      if (editingRoute) {
        await updateModelRoute(editingRoute.route_id, payload)
      } else {
        await createModelRoute(payload)
      }

      // Save fallbacks if changed
      if (fallbackDirty) {
        await updateModelFallbacks(form.model_name.trim(), fallbackList)
      }

      // Save params if changed
      if (paramsDirty) {
        try {
          const parsed = JSON.parse(paramsJson)
          await updateModelParams(form.model_name.trim(), parsed as ModelParams)
        } catch {
          setError('参数 JSON 格式错误，路由已保存但参数未更新')
          setDialogOpen(false)
          await loadRoutes()
          setSubmitting(false)
          return
        }
      }

      setDialogOpen(false)
      await loadRoutes()
    } catch (err) {
      setError(err instanceof Error ? err.message : (editingRoute ? '更新路由失败' : '创建路由失败'))
    } finally {
      setSubmitting(false)
    }
  }

  const remove = async (routeId: string) => {
    setError(null)
    try {
      await deleteModelRoute(routeId)
      await loadRoutes()
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除路由失败')
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span className="flex items-center gap-2">
              <Network className="w-5 h-5" />
              模型路由列表
            </span>
            <Button size="sm" onClick={openCreate}>
              <Plus className="w-4 h-4 mr-1" />
              添加路由
            </Button>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm mb-4">
              {error}
            </div>
          )}
          {loading ? (
            <div className="text-center py-8 text-gray-500">加载中...</div>
          ) : routes.length === 0 ? (
            <div className="text-center py-8 text-gray-500">暂无路由数据</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left">
                    <th className="pb-3 pr-4 font-medium text-gray-600">场景</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">模型类型</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">模型名称</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">优先级</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">状态</th>
                    <th className="pb-3 font-medium text-gray-600">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {routes.map((route) => (
                    <tr key={route.route_id} className="border-b last:border-0 hover:bg-gray-50">
                      <td className="py-3 pr-4">
                        <Badge variant="outline">
                          {SCENE_OPTIONS.find((s) => s.value === route.scene)?.label ?? route.scene}
                        </Badge>
                      </td>
                      <td className="py-3 pr-4">
                        {MODEL_TYPE_OPTIONS.find((t) => t.value === route.model_type)?.label ?? route.model_type}
                      </td>
                      <td className="py-3 pr-4 font-medium">{route.model_name}</td>
                      <td className="py-3 pr-4">{route.priority}</td>
                      <td className="py-3 pr-4">
                        <span
                          className={`px-3 py-1 rounded-full text-xs font-medium ${
                            route.enabled
                              ? 'bg-green-100 text-green-800'
                              : 'bg-gray-100 text-gray-600'
                          }`}
                        >
                          {route.enabled ? '已启用' : '已禁用'}
                        </span>
                      </td>
                      <td className="py-3">
                        <div className="flex gap-1">
                          <Button variant="ghost" size="icon-sm" onClick={() => openEdit(route)} title="编辑">
                            <Pencil className="w-4 h-4" />
                          </Button>
                          <Button variant="ghost" size="icon-sm" onClick={() => setDeleteConfirm(route.route_id)} title="删除">
                            <Trash2 className="w-4 h-4 text-red-500" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingRoute ? '编辑路由' : '添加路由'}</DialogTitle>
            <DialogDescription>
              {editingRoute ? '修改模型路由配置' : '创建新的模型路由规则'}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {/* Route basic fields */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block">场景</label>
                <Select
                  value={form.scene}
                  onValueChange={(v) => { if (v) updateForm('scene', v) }}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SCENE_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block">模型类型</label>
                <Select
                  value={form.model_type}
                  onValueChange={(v) => { if (v) updateForm('model_type', v) }}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {MODEL_TYPE_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">模型名称</label>
              <Input
                value={form.model_name}
                onChange={(e) => updateForm('model_name', e.target.value)}
                placeholder="gpt-4o"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block">优先级</label>
                <Input
                  type="number"
                  min={0}
                  value={form.priority}
                  onChange={(e) => updateForm('priority', Math.max(0, Number(e.target.value) || 0))}
                />
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block">启用状态</label>
                <Select
                  value={form.enabled ? 'true' : 'false'}
                  onValueChange={(v) => { if (v) updateForm('enabled', v === 'true') }}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="true">已启用</SelectItem>
                    <SelectItem value="false">已禁用</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Fallback chain */}
            <div className="border-t pt-4">
              <label className="text-sm font-semibold text-gray-700 mb-2 block">退避链 (Fallback)</label>
              <p className="text-xs text-gray-500 mb-2">
                当主模型不可用时，按顺序尝试退避模型
              </p>
              <div className="space-y-2">
                {fallbackList.map((name, index) => (
                  <div key={index} className="flex items-center gap-2">
                    <span className="text-xs text-gray-400 w-5 shrink-0">{index + 1}.</span>
                    <Input
                      value={name}
                      onChange={(e) => {
                        const updated = [...fallbackList]
                        updated[index] = e.target.value
                        setFallbackList(updated)
                        setFallbackDirty(true)
                      }}
                      placeholder="模型名称"
                    />
                    <Button variant="ghost" size="icon-sm" onClick={() => removeFallback(index)}>
                      <Trash2 className="w-4 h-4 text-red-500" />
                    </Button>
                  </div>
                ))}
              </div>
              <div className="flex items-center gap-2 mt-2">
                <Input
                  value={fallbackInput}
                  onChange={(e) => setFallbackInput(e.target.value)}
                  placeholder="输入退避模型名称"
                  className="flex-1"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      addFallback()
                    }
                  }}
                />
                <Button variant="outline" size="sm" onClick={addFallback} disabled={!fallbackInput.trim()}>
                  <Plus className="w-3 h-3 mr-1" />
                  添加
                </Button>
              </div>
            </div>

            {/* Parameters */}
            <div className="border-t pt-4">
              <label className="text-sm font-semibold text-gray-700 mb-2 block">模型参数</label>
              <p className="text-xs text-gray-500 mb-2">
                JSON 格式: temperature, max_tokens, top_p 等
              </p>
              <Textarea
                value={paramsJson}
                onChange={(e) => {
                  setParamsJson(e.target.value)
                  setParamsDirty(true)
                }}
                className="min-h-[120px] font-mono text-xs"
                placeholder='{\n  "temperature": 0.7,\n  "max_tokens": 4096,\n  "top_p": 0.9\n}'
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>取消</Button>
            <Button onClick={submit} disabled={submitting}>
              {submitting ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              {submitting ? '提交中...' : editingRoute ? '保存' : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation dialog */}
      <Dialog open={!!deleteConfirm} onOpenChange={(open) => { if (!open) setDeleteConfirm(null) }}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
            <DialogDescription>
              确定要删除此路由规则吗？此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteConfirm(null)}>取消</Button>
            <Button variant="destructive" onClick={async () => {
              if (deleteConfirm) {
                try {
                  await deleteModelRoute(deleteConfirm)
                  setDeleteConfirm(null)
                  await loadRoutes()
                } catch (err) {
                  setError(err instanceof Error ? err.message : '删除路由失败')
                }
              }
            }}>
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// --- ProviderCrud ---

interface ProviderFormState {
  provider_id: string
  provider_type: string
  base_url: string
  api_key: string
  default_headers: string
  enabled: boolean
}

const emptyProviderForm: ProviderFormState = {
  provider_id: '',
  provider_type: 'openai_compatible',
  base_url: '',
  api_key: '',
  default_headers: '{}',
  enabled: true,
}

function ProviderCrud() {
  const { setConnected, setFallback } = useApiContext()
  const [providers, setProviders] = useState<ModelProviderResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingProvider, setEditingProvider] = useState<ModelProviderResponse | null>(null)
  const [form, setForm] = useState<ProviderFormState>(emptyProviderForm)
  const [submitting, setSubmitting] = useState(false)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, ModelProviderTestResult>>({})
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)

  useEffect(() => {
    loadProviders()
  }, [])

  const loadProviders = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await listModelProviders()
      setProviders(result.items)
      const hasFallback = result.items.some((p) => p.fallback)
      if (hasFallback) {
        setFallback()
      } else {
        setConnected()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载 Provider 列表失败')
    } finally {
      setLoading(false)
    }
  }

  const openCreate = () => {
    setEditingProvider(null)
    setForm(emptyProviderForm)
    setDialogOpen(true)
  }

  const openEdit = (provider: ModelProviderResponse) => {
    setEditingProvider(provider)
    setForm({
      provider_id: provider.provider_id,
      provider_type: provider.provider_type,
      base_url: provider.base_url,
      api_key: provider.api_key ?? '',
      default_headers: JSON.stringify(provider.default_headers ?? {}, null, 2),
      enabled: provider.enabled,
    })
    setDialogOpen(true)
  }

  const updateForm = <K extends keyof ProviderFormState>(field: K, value: ProviderFormState[K]) => {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  const submit = async () => {
    setError(null)

    if (!form.provider_id.trim() && !editingProvider) {
      setError('Provider ID 不能为空')
      return
    }
    if (!form.base_url.trim()) {
      setError('Base URL 不能为空')
      return
    }

    let parsedHeaders: Record<string, string> = {}
    try {
      parsedHeaders = JSON.parse(form.default_headers || '{}')
    } catch {
      setError('请求头 JSON 格式错误')
      return
    }

    setSubmitting(true)
    try {
      const payload: ModelProviderCreate = {
        provider_id: editingProvider ? undefined : form.provider_id.trim(),
        provider_type: form.provider_type,
        base_url: form.base_url.trim(),
        api_key: form.api_key.trim() || undefined,
        default_headers: parsedHeaders,
        enabled: form.enabled,
      }

      if (editingProvider) {
        await updateModelProvider(editingProvider.provider_id, payload)
      } else {
        await createModelProvider(payload)
      }

      setDialogOpen(false)
      await loadProviders()
    } catch (err) {
      setError(err instanceof Error ? err.message : (editingProvider ? '更新 Provider 失败' : '创建 Provider 失败'))
    } finally {
      setSubmitting(false)
    }
  }

  const remove = async (providerId: string) => {
    setError(null)
    try {
      await deleteModelProvider(providerId)
      setDeleteConfirm(null)
      await loadProviders()
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除 Provider 失败')
    }
  }

  const runTest = async (providerId: string) => {
    setTestingId(providerId)
    setError(null)
    try {
      const result = await testModelProvider(providerId)
      setTestResults((prev) => ({ ...prev, [providerId]: result }))
    } catch (err) {
      setTestResults((prev) => ({
        ...prev,
        [providerId]: { success: false, latency_ms: 0, error: err instanceof Error ? err.message : '连接测试失败' },
      }))
    } finally {
      setTestingId(null)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span className="flex items-center gap-2">
              <Server className="w-5 h-5" />
              Provider 列表
            </span>
            <Button size="sm" onClick={openCreate}>
              <Plus className="w-4 h-4 mr-1" />
              添加 Provider
            </Button>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm mb-4">
              {error}
            </div>
          )}
          {loading ? (
            <div className="text-center py-8 text-gray-500">加载中...</div>
          ) : providers.length === 0 ? (
            <div className="text-center py-8 text-gray-500">暂无 Provider 数据</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left">
                    <th className="pb-3 pr-4 font-medium text-gray-600">ID</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">类型</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">Base URL</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">状态</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">连通性</th>
                    <th className="pb-3 font-medium text-gray-600">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {providers.map((provider) => {
                    const testResult = testResults[provider.provider_id]
                    const isTesting = testingId === provider.provider_id

                    return (
                      <tr key={provider.provider_id} className="border-b last:border-0 hover:bg-gray-50">
                        <td className="py-3 pr-4 font-medium">{provider.provider_id}</td>
                        <td className="py-3 pr-4">
                          <Badge variant="outline">
                            {PROVIDER_TYPE_OPTIONS.find((t) => t.value === provider.provider_type)?.label ?? provider.provider_type}
                          </Badge>
                        </td>
                        <td className="py-3 pr-4 max-w-[200px] truncate" title={provider.base_url}>
                          {provider.base_url}
                        </td>
                        <td className="py-3 pr-4">
                          <span
                            className={`px-3 py-1 rounded-full text-xs font-medium ${
                              provider.enabled
                                ? 'bg-green-100 text-green-800'
                                : 'bg-gray-100 text-gray-600'
                            }`}
                          >
                            {provider.enabled ? '已启用' : '已禁用'}
                          </span>
                        </td>
                        <td className="py-3 pr-4">
                          <div className="flex items-center gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => runTest(provider.provider_id)}
                              disabled={isTesting}
                            >
                              {isTesting ? (
                                <Loader2 className="w-3 h-3 animate-spin" />
                              ) : (
                                <ShieldCheck className="w-3 h-3" />
                              )}
                              {isTesting ? '测试中' : '测试'}
                            </Button>
                            {testResult && (
                              <span className={`text-xs flex items-center gap-1 ${
                                testResult.success ? 'text-green-600' : 'text-red-600'
                              }`}>
                                {testResult.success ? (
                                  <>✅ {testResult.latency_ms}ms</>
                                ) : (
                                  <>❌ {testResult.error ?? '失败'}</>
                                )}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="py-3">
                          <div className="flex gap-1">
                            <Button variant="ghost" size="icon-sm" onClick={() => openEdit(provider)} title="编辑">
                              <Pencil className="w-4 h-4" />
                            </Button>
                            <Button variant="ghost" size="icon-sm" onClick={() => setDeleteConfirm(provider.provider_id)} title="删除">
                              <Trash2 className="w-4 h-4 text-red-500" />
                            </Button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{editingProvider ? '编辑 Provider' : '添加 Provider'}</DialogTitle>
            <DialogDescription>
              {editingProvider ? '修改 Provider 配置' : '注册新的模型服务 Provider'}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">Provider ID</label>
              <Input
                value={form.provider_id}
                onChange={(e) => updateForm('provider_id', e.target.value)}
                placeholder="my-provider"
                disabled={!!editingProvider}
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">类型</label>
              <Select
                value={form.provider_type}
                onValueChange={(v) => { if (v) updateForm('provider_type', v) }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PROVIDER_TYPE_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">Base URL</label>
              <Input
                type="url"
                value={form.base_url}
                onChange={(e) => updateForm('base_url', e.target.value)}
                placeholder="https://api.openai.com/v1"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">API Key</label>
              <Input
                type="password"
                value={form.api_key}
                onChange={(e) => updateForm('api_key', e.target.value)}
                placeholder="sk-..."
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">请求头 (JSON)</label>
              <Textarea
                value={form.default_headers}
                onChange={(e) => updateForm('default_headers', e.target.value)}
                className="min-h-[80px] font-mono text-xs"
                placeholder='{"Authorization": "Bearer ..."}'
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">启用状态</label>
              <Select
                value={form.enabled ? 'true' : 'false'}
                onValueChange={(v) => { if (v) updateForm('enabled', v === 'true') }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="true">已启用</SelectItem>
                  <SelectItem value="false">已禁用</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>取消</Button>
            <Button onClick={submit} disabled={submitting}>
              {submitting ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              {submitting ? '提交中...' : editingProvider ? '保存' : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation dialog */}
      <Dialog open={!!deleteConfirm} onOpenChange={(open) => { if (!open) setDeleteConfirm(null) }}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
            <DialogDescription>
              确定要删除 Provider <strong>{deleteConfirm}</strong> 吗？此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteConfirm(null)}>取消</Button>
            <Button variant="destructive" onClick={() => deleteConfirm && remove(deleteConfirm)}>
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// --- ModelManagement (Main) ---

export default function ModelManagement() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">模型服务管理</h2>
          <p className="text-sm text-gray-500 mt-1">测试模型、配置服务参数、管理路由和 Provider</p>
        </div>
      </div>

      <Tabs defaultValue="test">
        <TabsList>
          <TabsTrigger value="test" className="flex items-center gap-1.5">
            <FlaskConical className="w-4 h-4" />
            模型测试
          </TabsTrigger>
          <TabsTrigger value="config" className="flex items-center gap-1.5">
            <Settings2 className="w-4 h-4" />
            模型配置
          </TabsTrigger>
          <TabsTrigger value="routes" className="flex items-center gap-1.5">
            <Network className="w-4 h-4" />
            路由管理
          </TabsTrigger>
          <TabsTrigger value="providers" className="flex items-center gap-1.5">
            <Server className="w-4 h-4" />
            Provider 管理
          </TabsTrigger>
        </TabsList>

        <TabsContent value="test">
          <ModelTest />
        </TabsContent>

        <TabsContent value="config">
          <ModelConfigPanel />
        </TabsContent>

        <TabsContent value="routes">
          <ModelRouteCrud />
        </TabsContent>

        <TabsContent value="providers">
          <ProviderCrud />
        </TabsContent>
      </Tabs>
    </div>
  )
}
