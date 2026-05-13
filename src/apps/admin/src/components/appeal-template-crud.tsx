'use client'

import { useEffect, useState } from 'react'
import { FileText, Pencil, Plus, Trash2 } from 'lucide-react'
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
  listAppealTemplates,
  createAppealTemplate,
  updateAppealTemplate,
  deleteAppealTemplate,
} from '@/lib/api-client'
import type { AppealTemplateCreate, AppealTemplateItem } from '@/lib/types'

const TEMPLATE_TYPE_OPTIONS = [
  { value: 'appeal', label: '拒付申诉' },
  { value: 'dispute', label: '争议申诉' },
  { value: 'explanation', label: '情况说明' },
  { value: 'appeal_letter', label: '申诉函' },
]

const SCENARIO_OPTIONS = [
  { value: 'settlement_exception', label: '结算异常' },
  { value: 'pre_discharge_qc', label: '出院前质控' },
  { value: 'drg_dip_operation', label: 'DRG/DIP运营' },
  { value: 'appeal_assistant', label: '申诉助手' },
  { value: 'policy_explanation', label: '政策解释' },
]

interface AppealTemplateForm {
  template_id: string
  template_name: string
  template_type: string
  denial_reason_pattern: string
  content: string
  required_evidence: string
  applicable_scenarios: string[]
}

const emptyForm: AppealTemplateForm = {
  template_id: '',
  template_name: '',
  template_type: 'appeal',
  denial_reason_pattern: '',
  content: '',
  required_evidence: '',
  applicable_scenarios: [],
}

export default function AppealTemplateCrud() {
  const [items, setItems] = useState<AppealTemplateItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<AppealTemplateItem | null>(null)
  const [form, setForm] = useState<AppealTemplateForm>(emptyForm)
  const [submitting, setSubmitting] = useState(false)
  const [filterType, setFilterType] = useState<string>('')

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listAppealTemplates()
      setItems(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载申诉模板失败')
    } finally {
      setLoading(false)
    }
  }

  const filteredItems = filterType
    ? items.filter((item) => item.template_type === filterType)
    : items

  const parseEvidence = (text: string): string[] => {
    try {
      const parsed = JSON.parse(text)
      if (Array.isArray(parsed)) return parsed
      return [text]
    } catch {
      return text.split(',').map((s) => s.trim()).filter(Boolean)
    }
  }

  const openCreate = () => {
    setEditing(null)
    setForm(emptyForm)
    setDialogOpen(true)
  }

  const openEdit = (item: AppealTemplateItem) => {
    setEditing(item)
    setForm({
      template_id: item.template_id,
      template_name: item.template_name,
      template_type: item.template_type,
      denial_reason_pattern: item.denial_reason_pattern,
      content: item.content,
      required_evidence: JSON.stringify(item.required_evidence, null, 2),
      applicable_scenarios: [...item.applicable_scenarios],
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
      const payload: AppealTemplateCreate = {
        template_id: form.template_id.trim(),
        template_name: form.template_name.trim(),
        template_type: form.template_type,
        denial_reason_pattern: form.denial_reason_pattern.trim(),
        content: form.content.trim(),
        required_evidence: parseEvidence(form.required_evidence),
        applicable_scenarios: form.applicable_scenarios,
      }
      if (editing) {
        await updateAppealTemplate(editing.template_id, payload)
      } else {
        await createAppealTemplate(payload)
      }
      setDialogOpen(false)
      await loadData()
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交申诉模板失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (templateId: string) => {
    setError(null)
    if (!window.confirm('确定要删除此申诉模板吗？')) return
    try {
      await deleteAppealTemplate(templateId)
      await loadData()
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除申诉模板失败')
    }
  }

  const toggleScenario = (scenario: string) => {
    setForm((prev) => ({
      ...prev,
      applicable_scenarios: prev.applicable_scenarios.includes(scenario)
        ? prev.applicable_scenarios.filter((s) => s !== scenario)
        : [...prev.applicable_scenarios, scenario],
    }))
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span className="flex items-center gap-2">
            <FileText className="w-5 h-5" />
            申诉模板管理
          </span>
          <div className="flex gap-2">
            <Select value={filterType} onValueChange={(v: string | null) => setFilterType(v ?? '')}>
              <SelectTrigger className="w-36">
                <SelectValue placeholder="全部类型" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">全部类型</SelectItem>
                {TEMPLATE_TYPE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" size="sm" onClick={loadData} disabled={loading}>
              {loading ? '加载中...' : '刷新'}
            </Button>
            <Button size="sm" onClick={openCreate}>
              <Plus className="w-4 h-4 mr-1" />
              添加申诉模板
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
          <div className="text-center py-8 text-gray-500">{filterType ? '没有匹配的申诉模板' : '暂无申诉模板数据'}</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left">
                  <th className="pb-3 pr-4 font-medium text-gray-600">模板ID</th>
                  <th className="pb-3 pr-4 font-medium text-gray-600">名称</th>
                  <th className="pb-3 pr-4 font-medium text-gray-600">类型</th>
                  <th className="pb-3 pr-4 font-medium text-gray-600">拒付原因模式</th>
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
                      <Badge variant="outline">{TEMPLATE_TYPE_OPTIONS.find((o) => o.value === item.template_type)?.label ?? item.template_type}</Badge>
                    </td>
                    <td className="py-3 pr-4 text-xs text-gray-500 max-w-[200px] truncate">{item.denial_reason_pattern}</td>
                    <td className="py-3 pr-4">
                      <span className={`px-3 py-1 rounded-full text-xs font-medium ${
                        item.enabled ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'
                      }`}>
                        {item.enabled ? '已启用' : '已禁用'}
                      </span>
                    </td>
                    <td className="py-3">
                      <div className="flex gap-1">
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
            <DialogTitle>{editing ? '编辑申诉模板' : '添加申诉模板'}</DialogTitle>
            <DialogDescription>
              {editing ? '修改申诉模板信息' : '创建新的申诉模板'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium text-gray-700">模板ID</label>
              <Input
                placeholder="at-001"
                value={form.template_id}
                onChange={(e) => setForm((prev) => ({ ...prev, template_id: e.target.value }))}
                disabled={!!editing}
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">模板名称</label>
              <Input
                placeholder="DRG分组争议申诉模板"
                value={form.template_name}
                onChange={(e) => setForm((prev) => ({ ...prev, template_name: e.target.value }))}
              />
            </div>
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
              <label className="text-sm font-medium text-gray-700">拒付原因模式</label>
              <Input
                placeholder="DRG分组"
                value={form.denial_reason_pattern}
                onChange={(e) => setForm((prev) => ({ ...prev, denial_reason_pattern: e.target.value }))}
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">模板内容</label>
              <Textarea
                placeholder="申诉事由：..."
                value={form.content}
                onChange={(e) => setForm((prev) => ({ ...prev, content: e.target.value }))}
                className="min-h-[120px]"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">所需证据（JSON 数组或逗号分隔）</label>
              <Textarea
                placeholder='["病案首页", "诊断证明", "手术记录"]'
                value={form.required_evidence}
                onChange={(e) => setForm((prev) => ({ ...prev, required_evidence: e.target.value }))}
                className="min-h-[60px] font-mono text-xs"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700 mb-2 block">适用场景</label>
              <div className="flex flex-wrap gap-2">
                {SCENARIO_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => toggleScenario(opt.value)}
                    className={`px-3 py-1.5 rounded-md text-sm cursor-pointer transition-colors ${
                      form.applicable_scenarios.includes(opt.value)
                        ? 'bg-blue-600 text-white hover:bg-blue-700'
                        : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
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
    </Card>
  )
}
