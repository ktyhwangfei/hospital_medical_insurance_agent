'use client'

import { useEffect, useState } from 'react'
import { BookText, Pencil, Plus, Trash2 } from 'lucide-react'
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
import { listRules, createRule, updateRule, deleteRule } from '@/lib/api-client'

const SCENARIO_LABELS: Record<string, string> = {
  settlement_exception: '结算异常',
  pre_discharge_qc: '出院前质控',
  mcp_tool_invocation: 'MCP工具调用',
}

const RISK_LABELS: Record<string, string> = {
  LOW: '低风险',
  MEDIUM: '中风险',
  HIGH: '高风险',
}

const RISK_COLORS: Record<string, string> = {
  LOW: 'bg-green-100 text-green-800',
  MEDIUM: 'bg-yellow-100 text-yellow-800',
  HIGH: 'bg-red-100 text-red-800',
}

const ROLE_OPTIONS = [
  { id: 'cashier', name: '收费员' },
  { id: 'medical_office', name: '医保办' },
  { id: 'information_department', name: '信息科' },
  { id: 'medical_record_staff', name: '病案室' },
  { id: 'clinician', name: '临床医生' },
]

interface RuleItem {
  rule_id: string
  rule_name: string
  category: string
  scenario: string
  rule_content: string
  explanation: string
  applicable_roles: string[]
  risk_level: string
  effective_date: string
  enabled: boolean
  fallback?: boolean
}

interface RuleFormState {
  rule_id: string
  rule_name: string
  category: string
  scenario: string
  rule_content: string
  explanation: string
  applicable_roles: string[]
  risk_level: string
  effective_date: string
  enabled: boolean
}

const emptyForm: RuleFormState = {
  rule_id: '',
  rule_name: '',
  category: '',
  scenario: 'settlement_exception',
  rule_content: '',
  explanation: '',
  applicable_roles: [],
  risk_level: 'LOW',
  effective_date: '',
  enabled: true,
}

export default function RuleExplanationCrud() {
  const [rules, setRules] = useState<RuleItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [scenarioFilter, setScenarioFilter] = useState<string>('')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const [editing, setEditing] = useState<RuleItem | null>(null)
  const [form, setForm] = useState<RuleFormState>(emptyForm)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    loadRules()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioFilter])

  const loadRules = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await listRules(scenarioFilter ? { scenario: scenarioFilter } : undefined)
      setRules(result as unknown as RuleItem[])
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载规则失败')
    } finally {
      setLoading(false)
    }
  }

  const openCreate = () => {
    setEditing(null)
    setForm({ ...emptyForm })
    setDialogOpen(true)
  }

  const openEdit = (rule: RuleItem) => {
    setEditing(rule)
    setForm({
      rule_id: rule.rule_id,
      rule_name: rule.rule_name,
      category: rule.category,
      scenario: rule.scenario,
      rule_content: rule.rule_content,
      explanation: rule.explanation,
      applicable_roles: [...(rule.applicable_roles || [])],
      risk_level: rule.risk_level,
      effective_date: rule.effective_date,
      enabled: rule.enabled,
    })
    setDialogOpen(true)
  }

  const submit = async () => {
    setError(null)
    if (!form.rule_id.trim() || !form.rule_name.trim()) {
      setError('规则ID和名称不能为空')
      return
    }
    setSubmitting(true)
    try {
      if (editing) {
        await updateRule(editing.rule_id, form)
      } else {
        await createRule(form)
      }
      setDialogOpen(false)
      await loadRules()
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败')
    } finally {
      setSubmitting(false)
    }
  }

  const openDelete = (ruleId: string) => {
    setDeleteTarget(ruleId)
    setDeleteDialogOpen(true)
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setError(null)
    try {
      await deleteRule(deleteTarget)
      setDeleteDialogOpen(false)
      setDeleteTarget(null)
      await loadRules()
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败')
    }
  }

  const toggleRole = (roleId: string) => {
    setForm((prev) => ({
      ...prev,
      applicable_roles: prev.applicable_roles.includes(roleId)
        ? prev.applicable_roles.filter((r) => r !== roleId)
        : [...prev.applicable_roles, roleId],
    }))
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span className="flex items-center gap-2">
              <BookText className="w-5 h-5" />
              规则解释管理
            </span>
            <div className="flex items-center gap-2">
              <Select value={scenarioFilter} onValueChange={(v) => { setScenarioFilter(v ?? '') }}>
                <SelectTrigger className="w-[160px]">
                  <SelectValue placeholder="全部场景" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">全部场景</SelectItem>
                  <SelectItem value="settlement_exception">结算异常</SelectItem>
                  <SelectItem value="pre_discharge_qc">出院前质控</SelectItem>
                  <SelectItem value="mcp_tool_invocation">MCP工具调用</SelectItem>
                </SelectContent>
              </Select>
              <Button variant="outline" size="sm" onClick={loadRules} disabled={loading}>
                {loading ? '加载中...' : '刷新'}
              </Button>
              <Button size="sm" onClick={openCreate}>
                <Plus className="w-4 h-4 mr-1" />
                添加规则
              </Button>
            </div>
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
          ) : rules.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              <p>暂无规则</p>
              <Button variant="outline" size="sm" className="mt-2" onClick={openCreate}>
                <Plus className="w-4 h-4 mr-1" />
                创建第一条规则
              </Button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left">
                    <th className="pb-3 pr-4 font-medium text-gray-600">规则ID</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">规则名称</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">分类</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">场景</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">风险等级</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">状态</th>
                    <th className="pb-3 font-medium text-gray-600">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {rules.map((rule) => (
                    <tr key={rule.rule_id} className="border-b last:border-0 hover:bg-gray-50">
                      <td className="py-3 pr-4 font-mono text-xs">{rule.rule_id}</td>
                      <td className="py-3 pr-4">
                        <div className="font-medium">{rule.rule_name}</div>
                      </td>
                      <td className="py-3 pr-4">{rule.category}</td>
                      <td className="py-3 pr-4">
                        <Badge variant="outline">
                          {SCENARIO_LABELS[rule.scenario] ?? rule.scenario}
                        </Badge>
                      </td>
                      <td className="py-3 pr-4">
                        <Badge className={RISK_COLORS[rule.risk_level] ?? 'bg-gray-100 text-gray-800'}>
                          {RISK_LABELS[rule.risk_level] ?? rule.risk_level}
                        </Badge>
                      </td>
                      <td className="py-3 pr-4">
                        <span
                          className={`px-3 py-1 rounded-full text-xs font-medium ${
                            rule.enabled ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'
                          }`}
                        >
                          {rule.enabled ? '已启用' : '已禁用'}
                        </span>
                      </td>
                      <td className="py-3">
                        <div className="flex gap-1">
                          <Button variant="ghost" size="icon-sm" onClick={() => openEdit(rule)} title="编辑">
                            <Pencil className="w-4 h-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => openDelete(rule.rule_id)}
                            title="删除"
                          >
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

      {/* Create / Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editing ? '编辑规则' : '添加规则'}</DialogTitle>
            <DialogDescription>
              {editing ? '修改规则解释信息' : '创建新的规则解释'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium text-gray-700">规则ID *</label>
                <Input
                  placeholder="RULE-001"
                  value={form.rule_id}
                  onChange={(e) => setForm((prev) => ({ ...prev, rule_id: e.target.value }))}
                  disabled={!!editing}
                />
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700">规则名称 *</label>
                <Input
                  placeholder="医保目录匹配规则"
                  value={form.rule_name}
                  onChange={(e) => setForm((prev) => ({ ...prev, rule_name: e.target.value }))}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium text-gray-700">分类</label>
                <Input
                  placeholder="结算"
                  value={form.category}
                  onChange={(e) => setForm((prev) => ({ ...prev, category: e.target.value }))}
                />
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700">场景</label>
                <Select
                  value={form.scenario}
                  onValueChange={(v) => {
                    if (v) setForm((prev) => ({ ...prev, scenario: v }))
                  }}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="settlement_exception">结算异常</SelectItem>
                    <SelectItem value="pre_discharge_qc">出院前质控</SelectItem>
                    <SelectItem value="mcp_tool_invocation">MCP工具调用</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">规则内容</label>
              <Textarea
                placeholder="规则详细内容"
                value={form.rule_content}
                onChange={(e) => setForm((prev) => ({ ...prev, rule_content: e.target.value }))}
                className="min-h-[80px]"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">解释说明</label>
              <Textarea
                placeholder="规则的详细解释说明"
                value={form.explanation}
                onChange={(e) => setForm((prev) => ({ ...prev, explanation: e.target.value }))}
                className="min-h-[80px]"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700 mb-2 block">适用角色</label>
              <div className="flex flex-wrap gap-2">
                {ROLE_OPTIONS.map((role) => (
                  <button
                    key={role.id}
                    type="button"
                    onClick={() => toggleRole(role.id)}
                    className={`px-3 py-1.5 rounded-md text-sm cursor-pointer transition-colors ${
                      form.applicable_roles.includes(role.id)
                        ? 'bg-blue-600 text-white hover:bg-blue-700'
                        : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                    }`}
                  >
                    {role.name}
                  </button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium text-gray-700">风险等级</label>
                <Select
                  value={form.risk_level}
                  onValueChange={(v) => {
                    if (v) setForm((prev) => ({ ...prev, risk_level: v }))
                  }}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="LOW">低风险</SelectItem>
                    <SelectItem value="MEDIUM">中风险</SelectItem>
                    <SelectItem value="HIGH">高风险</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700">生效日期</label>
                <Input
                  type="date"
                  value={form.effective_date}
                  onChange={(e) => setForm((prev) => ({ ...prev, effective_date: e.target.value }))}
                />
              </div>
            </div>
            <div className="flex items-center gap-2">
              <label className="text-sm font-medium text-gray-700">启用状态</label>
              <button
                type="button"
                onClick={() => setForm((prev) => ({ ...prev, enabled: !prev.enabled }))}
                className={`px-3 py-1.5 rounded-md text-sm cursor-pointer transition-colors ${
                  form.enabled
                    ? 'bg-green-100 text-green-800 hover:bg-green-200'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {form.enabled ? '已启用' : '已禁用'}
              </button>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              取消
            </Button>
            <Button onClick={submit} disabled={submitting}>
              {submitting ? '提交中...' : editing ? '保存' : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
            <DialogDescription>
              确定要删除规则 &ldquo;{deleteTarget}&rdquo; 吗？此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              取消
            </Button>
            <Button variant="destructive" onClick={confirmDelete}>
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
