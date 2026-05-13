'use client'

import { useEffect, useState } from 'react'
import { Brain, Eye, Pencil, Plus, Trash2 } from 'lucide-react'
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
import { Textarea } from '@/components/ui/textarea'
import {
  listPromptTemplates,
  createPromptTemplate,
  updatePromptTemplate,
  deletePromptTemplate,
  renderPromptTemplate,
} from '@/lib/api-client'
import type { PromptTemplateCreate, PromptTemplateItem } from '@/lib/types'

const TEMPLATE_TYPE_OPTIONS = [
  { value: 'scenario', label: '场景模板' },
  { value: 'role', label: '角色模板' },
  { value: 'system', label: '系统模板' },
  { value: 'user', label: '用户模板' },
]

const SCENARIO_OPTIONS = [
  { value: 'settlement_exception', label: '结算异常' },
  { value: 'pre_discharge_qc', label: '出院前质控' },
  { value: 'drg_dip_operation', label: 'DRG/DIP运营' },
  { value: 'appeal_assistant', label: '申诉助手' },
  { value: 'policy_explanation', label: '政策解释' },
]

const ROLE_OPTIONS = [
  { value: 'system', label: '系统' },
  { value: 'user', label: '用户' },
  { value: 'assistant', label: '助手' },
]

interface PromptTemplateForm {
  template_id: string
  template_name: string
  template_type: string
  scenario: string
  role: string
  system_prompt: string
  user_prompt_template: string
  variables: string
  output_format: string
}

const emptyForm: PromptTemplateForm = {
  template_id: '',
  template_name: '',
  template_type: 'scenario',
  scenario: 'settlement_exception',
  role: 'system',
  system_prompt: '',
  user_prompt_template: '',
  variables: '',
  output_format: '{}',
}

export default function PromptTemplateCrud() {
  const [items, setItems] = useState<PromptTemplateItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<PromptTemplateItem | null>(null)
  const [form, setForm] = useState<PromptTemplateForm>(emptyForm)
  const [submitting, setSubmitting] = useState(false)
  const [filterScenario, setFilterScenario] = useState<string>('')
  const [filterRole, setFilterRole] = useState<string>('')

  // Render preview state
  const [renderDialogOpen, setRenderDialogOpen] = useState(false)
  const [renderTemplate, setRenderTemplate] = useState<PromptTemplateItem | null>(null)
  const [renderVariables, setRenderVariables] = useState<Record<string, string>>({})
  const [renderResult, setRenderResult] = useState<string>('')
  const [renderLoading, setRenderLoading] = useState(false)
  const [renderError, setRenderError] = useState<string | null>(null)

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listPromptTemplates()
      setItems(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载提示词模板失败')
    } finally {
      setLoading(false)
    }
  }

  const filteredItems = items.filter((item) => {
    if (filterScenario && item.scenario !== filterScenario) return false
    if (filterRole && item.role !== filterRole) return false
    return true
  })

  const parseOutputFormat = (text: string): Record<string, unknown> => {
    try {
      return JSON.parse(text) as Record<string, unknown>
    } catch {
      return {}
    }
  }

  const openCreate = () => {
    setEditing(null)
    setForm(emptyForm)
    setDialogOpen(true)
  }

  const openEdit = (item: PromptTemplateItem) => {
    setEditing(item)
    setForm({
      template_id: item.template_id,
      template_name: item.template_name,
      template_type: item.template_type,
      scenario: item.scenario,
      role: item.role,
      system_prompt: item.system_prompt,
      user_prompt_template: item.user_prompt_template ?? '',
      variables: item.variables.join(', '),
      output_format: JSON.stringify(item.output_format, null, 2),
    })
    setDialogOpen(true)
  }

  const submit = async () => {
    setError(null)
    if (!form.template_id.trim() || !form.template_name.trim()) {
      setError('模板ID和名称不能为空')
      return
    }
    setSubmitting(true)
    try {
      const payload: PromptTemplateCreate = {
        template_id: form.template_id.trim(),
        template_name: form.template_name.trim(),
        template_type: form.template_type,
        scenario: form.scenario,
        role: form.role,
        system_prompt: form.system_prompt.trim(),
        user_prompt_template: form.user_prompt_template.trim() || undefined,
        variables: form.variables.split(',').map((s) => s.trim()).filter(Boolean),
        output_format: parseOutputFormat(form.output_format),
      }
      if (editing) {
        await updatePromptTemplate(editing.template_id, payload)
      } else {
        await createPromptTemplate(payload)
      }
      setDialogOpen(false)
      await loadData()
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交提示词模板失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (templateId: string) => {
    setError(null)
    if (!window.confirm('确定要删除此提示词模板吗？')) return
    try {
      await deletePromptTemplate(templateId)
      await loadData()
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除提示词模板失败')
    }
  }

  const openRender = (item: PromptTemplateItem) => {
    setRenderTemplate(item)
    setRenderVariables({})
    setRenderResult('')
    setRenderError(null)
    setRenderDialogOpen(true)
  }

  const handleRender = async () => {
    if (!renderTemplate) return
    setRenderLoading(true)
    setRenderError(null)
    try {
      const result = await renderPromptTemplate({
        template_id: renderTemplate.template_id,
        variables: renderVariables,
      })
      setRenderResult(result.rendered)
    } catch (err) {
      setRenderError(err instanceof Error ? err.message : '渲染失败')
    } finally {
      setRenderLoading(false)
    }
  }

  const scenarioLabel = (value: string) => SCENARIO_OPTIONS.find((o) => o.value === value)?.label ?? value
  const typeLabel = (value: string) => TEMPLATE_TYPE_OPTIONS.find((o) => o.value === value)?.label ?? value
  const roleLabel = (value: string) => ROLE_OPTIONS.find((o) => o.value === value)?.label ?? value

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Brain className="w-5 h-5" />
            提示词模板管理
          </span>
          <div className="flex gap-2">
            <Select value={filterScenario} onValueChange={(v: string | null) => setFilterScenario(v ?? '')}>
              <SelectTrigger className="w-32">
                <SelectValue placeholder="全部场景" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">全部场景</SelectItem>
                {SCENARIO_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={filterRole} onValueChange={(v: string | null) => setFilterRole(v ?? '')}>
              <SelectTrigger className="w-28">
                <SelectValue placeholder="全部角色" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">全部角色</SelectItem>
                {ROLE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" size="sm" onClick={loadData} disabled={loading}>
              {loading ? '加载中...' : '刷新'}
            </Button>
            <Button size="sm" onClick={openCreate}>
              <Plus className="w-4 h-4 mr-1" />
              添加模板
            </Button>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm mb-4">{error}</div>
        )}
        {loading ? (
          <div className="text-center py-8 text-gray-500">加载中...</div>
        ) : filteredItems.length === 0 ? (
          <div className="text-center py-8 text-gray-500">{filterScenario || filterRole ? '没有匹配的提示词模板' : '暂无提示词模板数据'}</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left">
                  <th className="pb-3 pr-4 font-medium text-gray-600">模板ID</th>
                  <th className="pb-3 pr-4 font-medium text-gray-600">名称</th>
                  <th className="pb-3 pr-4 font-medium text-gray-600">类型</th>
                  <th className="pb-3 pr-4 font-medium text-gray-600">场景</th>
                  <th className="pb-3 pr-4 font-medium text-gray-600">角色</th>
                  <th className="pb-3 pr-4 font-medium text-gray-600">状态</th>
                  <th className="pb-3 font-medium text-gray-600">操作</th>
                </tr>
              </thead>
              <tbody>
                {filteredItems.map((item) => (
                  <tr key={item.template_id} className="border-b last:border-0 hover:bg-gray-50">
                    <td className="py-3 pr-4">
                      <span className="font-mono text-xs">{item.template_id}</span>
                    </td>
                    <td className="py-3 pr-4 font-medium">{item.template_name}</td>
                    <td className="py-3 pr-4">
                      <Badge variant="outline">{typeLabel(item.template_type)}</Badge>
                    </td>
                    <td className="py-3 pr-4">
                      <Badge variant="secondary" className="bg-blue-50 text-blue-700">{scenarioLabel(item.scenario)}</Badge>
                    </td>
                    <td className="py-3 pr-4">
                      <Badge variant="secondary" className="bg-purple-50 text-purple-700">{roleLabel(item.role)}</Badge>
                    </td>
                    <td className="py-3 pr-4">
                      <span className={`px-3 py-1 rounded-full text-xs font-medium ${
                        item.enabled ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'
                      }`}>
                        {item.enabled ? '已启用' : '已禁用'}
                      </span>
                    </td>
                    <td className="py-3">
                      <div className="flex gap-1">
                        <Button variant="ghost" size="icon-sm" onClick={() => openRender(item)} title="渲染预览">
                          <Eye className="w-4 h-4" />
                        </Button>
                        <Button variant="ghost" size="icon-sm" onClick={() => openEdit(item)} title="编辑">
                          <Pencil className="w-4 h-4" />
                        </Button>
                        <Button variant="ghost" size="icon-sm" onClick={() => handleDelete(item.template_id)} title="删除">
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

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editing ? '编辑提示词模板' : '添加提示词模板'}</DialogTitle>
            <DialogDescription>
              {editing ? '修改提示词模板信息' : '创建新的提示词模板'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium text-gray-700">模板ID</label>
              <Input
                placeholder="pt-001"
                value={form.template_id}
                onChange={(e) => setForm((prev) => ({ ...prev, template_id: e.target.value }))}
                disabled={!!editing}
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">模板名称</label>
              <Input
                placeholder="出院前质控提示词"
                value={form.template_name}
                onChange={(e) => setForm((prev) => ({ ...prev, template_name: e.target.value }))}
              />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="text-sm font-medium text-gray-700">模板类型</label>
                <Select value={form.template_type} onValueChange={(v) => { if (v) setForm((prev) => ({ ...prev, template_type: v })) }}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TEMPLATE_TYPE_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700">场景</label>
                <Select value={form.scenario} onValueChange={(v) => { if (v) setForm((prev) => ({ ...prev, scenario: v })) }}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SCENARIO_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700">角色</label>
                <Select value={form.role} onValueChange={(v) => { if (v) setForm((prev) => ({ ...prev, role: v })) }}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ROLE_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">系统提示词</label>
              <Textarea
                placeholder="你是医院医保出院前质控专家。请根据患者{{patient_info}}和审核结果{{audit_results}}..."
                value={form.system_prompt}
                onChange={(e) => setForm((prev) => ({ ...prev, system_prompt: e.target.value }))}
                className="min-h-[100px]"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">用户提示词模板（可选）</label>
              <Textarea
                placeholder="请分析以下患者信息：{{patient_info}}"
                value={form.user_prompt_template}
                onChange={(e) => setForm((prev) => ({ ...prev, user_prompt_template: e.target.value }))}
                className="min-h-[60px]"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">变量（逗号分隔）</label>
              <Input
                placeholder="patient_info, audit_results"
                value={form.variables}
                onChange={(e) => setForm((prev) => ({ ...prev, variables: e.target.value }))}
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">输出格式（JSON）</label>
              <Textarea
                placeholder='{"risks": "list", "recommendations": "string"}'
                value={form.output_format}
                onChange={(e) => setForm((prev) => ({ ...prev, output_format: e.target.value }))}
                className="min-h-[60px] font-mono text-xs"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>取消</Button>
            <Button onClick={submit} disabled={submitting}>
              {submitting ? '提交中...' : editing ? '保存' : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Render Preview Dialog */}
      <Dialog open={renderDialogOpen} onOpenChange={setRenderDialogOpen}>
        <DialogContent className="sm:max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>渲染预览</DialogTitle>
            <DialogDescription>
              填写变量值以预览模板渲染结果
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {renderTemplate && renderTemplate.variables.length > 0 ? (
              renderTemplate.variables.map((varName) => (
                <div key={varName}>
                  <label className="text-sm font-medium text-gray-700">{varName}</label>
                  <Input
                    placeholder={`输入 ${varName} 的值`}
                    value={renderVariables[varName] ?? ''}
                    onChange={(e) =>
                      setRenderVariables((prev) => ({ ...prev, [varName]: e.target.value }))
                    }
                  />
                </div>
              ))
            ) : (
              <p className="text-sm text-gray-500">该模板没有定义变量，可直接渲染。</p>
            )}
            {renderError && (
              <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">{renderError}</div>
            )}
            {renderResult && (
              <div>
                <label className="text-sm font-medium text-gray-700">渲染结果</label>
                <Textarea
                  readOnly
                  value={renderResult}
                  className="min-h-[120px] font-mono text-xs bg-gray-50"
                />
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenderDialogOpen(false)}>关闭</Button>
            <Button onClick={handleRender} disabled={renderLoading}>
              {renderLoading ? '渲染中...' : '渲染预览'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
