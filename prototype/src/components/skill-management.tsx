'use client'

import { useEffect, useState } from 'react'
import { Layers, Pencil, Plus, Trash2, Wrench } from 'lucide-react'
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
import { requestJson } from '@/lib/api-client'
import { useApiContext } from '@/lib/api-context'
import type { RoleId } from '@/lib/types'
import { roles } from '@/components/role-switcher'

const ROLE_COLORS: Record<string, string> = {
  cashier: 'bg-green-100 text-green-800',
  medical_office: 'bg-blue-100 text-blue-800',
  information_department: 'bg-purple-100 text-purple-800',
  medical_record_staff: 'bg-orange-100 text-orange-800',
}

const ROLE_LABELS: Record<string, string> = {
  cashier: '收费员',
  medical_office: '医保办',
  information_department: '信息科',
  medical_record_staff: '病案室',
}

const TOOL_TYPE_LABELS: Record<string, string> = {
  adapter_call: '适配器调用',
  knowledge_retrieval: '知识检索',
  mcp_tool_call: 'MCP工具调用',
  result_building: '结果构建',
}

const RISK_LABELS: Record<string, string> = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
}

const RISK_COLORS: Record<string, string> = {
  low: 'bg-green-100 text-green-800',
  medium: 'bg-yellow-100 text-yellow-800',
  high: 'bg-red-100 text-red-800',
}

const STRATEGY_LABELS: Record<string, string> = {
  sequential: '顺序执行',
  parallel: '并行执行',
  conditional: '条件执行',
}

const STRATEGY_ICONS: Record<string, string> = {
  sequential: '→',
  parallel: '⇉',
  conditional: '◇',
}

interface ToolItem {
  tool_id: string
  name: string
  description: string
  owner: string
  tool_type: string
  capability_ref: string
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  risk_level: string
  enabled: boolean
  required_roles: string[]
  metadata: Record<string, unknown>
  fallback?: boolean
}

interface SkillStepItem {
  step_id: string
  tool_id: string
  input_mapping?: Record<string, unknown>
  output_mapping?: Record<string, unknown>
  condition?: string | null
  depends_on?: string[]
}

interface SkillItem {
  skill_id: string
  name: string
  description: string
  owner: string
  steps: SkillStepItem[]
  execution_strategy: string
  intent_keywords: string[]
  required_roles: string[]
  enabled: boolean
  risk_level: string
  license?: string | null
  compatibility?: string | null
  allowed_tools: string[]
  skill_metadata: {
    author: string
    version: string
    mcp_server?: string | null
    category?: string | null
    tags: string[]
  }
  fallback?: boolean
}

interface ToolForm {
  tool_id: string
  name: string
  description: string
  owner: string
  tool_type: string
  capability_ref: string
  risk_level: string
  required_roles: string
}

interface SkillForm {
  skill_id: string
  name: string
  description: string
  owner: string
  execution_strategy: string
  intent_keywords: string
  required_roles: string[]
  steps: SkillStepFormItem[]
  license: string
  compatibility: string
  allowed_tools: string
  author: string
  version: string
  category: string
  tags: string
}

interface SkillStepFormItem {
  step_id: string
  tool_id: string
}

const emptyToolForm: ToolForm = {
  tool_id: '',
  name: '',
  description: '',
  owner: 'cashier',
  tool_type: 'adapter_call',
  capability_ref: '',
  risk_level: 'low',
  required_roles: '',
}

const emptySkillForm: SkillForm = {
  skill_id: '',
  name: '',
  description: '',
  owner: 'cashier',
  execution_strategy: 'sequential',
  intent_keywords: '',
  required_roles: [],
  steps: [{ step_id: 'step_1', tool_id: '' }],
  license: '',
  compatibility: '',
  allowed_tools: '',
  author: 'hospital-medical-insurance-team',
  version: '1.0.0',
  category: '',
  tags: '',
}

const fallbackTools: ToolItem[] = [
  {
    tool_id: 'tool-query-policy',
    name: '政策查询工具',
    description: '按医保错误码查询政策解释和处置提示',
    owner: 'medical_office',
    tool_type: 'knowledge_retrieval',
    capability_ref: 'cap-query-policy-by-error-code',
    input_schema: {},
    output_schema: {},
    risk_level: 'low',
    enabled: true,
    required_roles: ['medical_office', 'cashier'],
    metadata: {},
    fallback: true,
  },
  {
    tool_id: 'tool-check-eligibility',
    name: '资格校验工具',
    description: '校验患者医保待遇资格',
    owner: 'cashier',
    tool_type: 'adapter_call',
    capability_ref: 'cap-check-eligibility',
    input_schema: {},
    output_schema: {},
    risk_level: 'medium',
    enabled: true,
    required_roles: ['cashier'],
    metadata: {},
    fallback: true,
  },
  {
    tool_id: 'tool-drg-grouping',
    name: 'DRG分组工具',
    description: '对病案数据进行DRG分组计算',
    owner: 'medical_record_staff',
    tool_type: 'mcp_tool_call',
    capability_ref: 'cap-drg-grouping',
    input_schema: {},
    output_schema: {},
    risk_level: 'high',
    enabled: false,
    required_roles: ['medical_record_staff', 'medical_office'],
    metadata: {},
    fallback: true,
  },
]

const fallbackSkills: SkillItem[] = [
  {
    skill_id: 'skill-settlement-guide',
    name: '结算异常导办',
    description: '引导收费员处理医保结算异常',
    owner: 'cashier',
    steps: [
      { step_id: 'step_1', tool_id: 'tool-query-policy' },
      { step_id: 'step_2', tool_id: 'tool-check-eligibility' },
    ],
    execution_strategy: 'sequential',
    intent_keywords: ['结算失败', '结算异常', 'ERR'],
    required_roles: ['cashier', 'medical_office'],
    enabled: true,
    risk_level: 'low',
    license: 'MIT',
    compatibility: null,
    allowed_tools: [],
    skill_metadata: { author: 'hospital-medical-insurance-team', version: '1.0.0', category: 'workflow-automation', tags: ['insurance', 'settlement'] },
    fallback: true,
  },
  {
    skill_id: 'skill-discharge-qc',
    name: '出院前质控',
    description: '出院前联合质控检查流程',
    owner: 'medical_office',
    steps: [
      { step_id: 'step_1', tool_id: 'tool-query-policy' },
      { step_id: 'step_2', tool_id: 'tool-drg-grouping' },
    ],
    execution_strategy: 'parallel',
    intent_keywords: ['出院', '质控', 'DRG'],
    required_roles: ['medical_office', 'medical_record_staff'],
    enabled: true,
    risk_level: 'medium',
    license: 'MIT',
    compatibility: null,
    allowed_tools: [],
    skill_metadata: { author: 'hospital-medical-insurance-team', version: '1.0.0', category: 'workflow-automation', tags: ['discharge', 'qc'] },
    fallback: true,
  },
]

function ownerBadge(owner: string) {
  const color = ROLE_COLORS[owner] ?? 'bg-gray-100 text-gray-800'
  const label = ROLE_LABELS[owner] ?? owner
  return <Badge className={color}>{label}</Badge>
}

interface SkillManagementProps {
  currentRole: RoleId
}

export default function SkillManagement({ currentRole }: SkillManagementProps) {
  const { setConnected, setFallback } = useApiContext()
  const [activeTab, setActiveTab] = useState('tools')
  const [tools, setTools] = useState<ToolItem[]>([])
  const [skills, setSkills] = useState<SkillItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toolDialogOpen, setToolDialogOpen] = useState(false)
  const [skillDialogOpen, setSkillDialogOpen] = useState(false)
  const [editingTool, setEditingTool] = useState<ToolItem | null>(null)
  const [editingSkill, setEditingSkill] = useState<SkillItem | null>(null)
  const [toolForm, setToolForm] = useState<ToolForm>(emptyToolForm)
  const [skillForm, setSkillForm] = useState<SkillForm>(emptySkillForm)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    loadData()
  }, [currentRole])

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [toolResult, skillResult] = await Promise.all([
        fetchTools(currentRole),
        fetchSkills(currentRole),
      ])
      setTools(toolResult)
      setSkills(skillResult)
      const hasFallback = toolResult.some((t) => t.fallback) || skillResult.some((s) => s.fallback)
      if (hasFallback) {
        setFallback()
      } else {
        setConnected()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '数据加载失败')
    } finally {
      setLoading(false)
    }
  }

  const openCreateTool = () => {
    setEditingTool(null)
    setToolForm(emptyToolForm)
    setToolDialogOpen(true)
  }

  const openEditTool = (tool: ToolItem) => {
    setEditingTool(tool)
    setToolForm({
      tool_id: tool.tool_id,
      name: tool.name,
      description: tool.description,
      owner: tool.owner,
      tool_type: tool.tool_type,
      capability_ref: tool.capability_ref,
      risk_level: tool.risk_level,
      required_roles: tool.required_roles.join(', '),
    })
    setToolDialogOpen(true)
  }

  const openCreateSkill = () => {
    setEditingSkill(null)
    setSkillForm(emptySkillForm)
    setSkillDialogOpen(true)
  }

  const openEditSkill = (skill: SkillItem) => {
    setEditingSkill(skill)
    setSkillForm({
      skill_id: skill.skill_id,
      name: skill.name,
      description: skill.description,
      owner: skill.owner,
      execution_strategy: skill.execution_strategy,
      intent_keywords: skill.intent_keywords.join(', '),
      required_roles: [...skill.required_roles],
      steps: skill.steps.map((s, i) => ({ step_id: s.step_id || `step_${i + 1}`, tool_id: s.tool_id })),
      license: skill.license ?? '',
      compatibility: skill.compatibility ?? '',
      allowed_tools: skill.allowed_tools?.join(', ') ?? '',
      author: skill.skill_metadata?.author ?? 'hospital-medical-insurance-team',
      version: skill.skill_metadata?.version ?? '1.0.0',
      category: skill.skill_metadata?.category ?? '',
      tags: skill.skill_metadata?.tags?.join(', ') ?? '',
    })
    setSkillDialogOpen(true)
  }

  const submitTool = async () => {
    setError(null)
    if (!toolForm.tool_id.trim() || !toolForm.name.trim() || !toolForm.description.trim()) {
      setError('工具ID、名称和描述不能为空')
      return
    }
    setSubmitting(true)
    try {
      const payload = {
        tool_id: toolForm.tool_id.trim(),
        name: toolForm.name.trim(),
        description: toolForm.description.trim(),
        owner: toolForm.owner,
        tool_type: toolForm.tool_type,
        capability_ref: toolForm.capability_ref.trim(),
        risk_level: toolForm.risk_level,
        required_roles: toolForm.required_roles.split(',').map((s) => s.trim()).filter(Boolean),
        input_schema: {},
        output_schema: {},
        metadata: {},
      }
      if (editingTool) {
        await requestJson(`/tools/${encodeURIComponent(editingTool.tool_id)}`, {
          method: 'PUT',
          body: JSON.stringify(payload),
        })
      } else {
        await requestJson('/tools', {
          method: 'POST',
          body: JSON.stringify(payload),
        })
      }
      setToolDialogOpen(false)
      await loadData()
    } catch (err) {
      setError(err instanceof Error ? err.message : '工具操作失败')
    } finally {
      setSubmitting(false)
    }
  }

  const deleteTool = async (toolId: string) => {
    setError(null)
    try {
      await requestJson(`/tools/${encodeURIComponent(toolId)}`, { method: 'DELETE' })
      await loadData()
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除工具失败')
    }
  }

  const toggleToolEnabled = async (tool: ToolItem) => {
    setError(null)
    try {
      await requestJson(`/tools/${encodeURIComponent(tool.tool_id)}`, {
        method: 'PUT',
        body: JSON.stringify({ enabled: !tool.enabled }),
      })
      await loadData()
    } catch (err) {
      setError(err instanceof Error ? err.message : '切换状态失败')
    }
  }

  const submitSkill = async () => {
    setError(null)
    if (!skillForm.skill_id.trim() || !skillForm.name.trim() || !skillForm.description.trim()) {
      setError('技能ID、名称和描述不能为空')
      return
    }
    setSubmitting(true)
    try {
      const payload = {
        skill_id: skillForm.skill_id.trim(),
        name: skillForm.name.trim(),
        description: skillForm.description.trim(),
        owner: skillForm.owner,
        execution_strategy: skillForm.execution_strategy,
        intent_keywords: skillForm.intent_keywords.split(',').map((s) => s.trim()).filter(Boolean),
        required_roles: skillForm.required_roles,
        steps: skillForm.steps.map((s) => ({
          step_id: s.step_id,
          tool_id: s.tool_id,
          input_mapping: {},
          output_mapping: {},
        })),
        risk_level: 'low',
        license: skillForm.license.trim() || null,
        compatibility: skillForm.compatibility.trim() || null,
        allowed_tools: skillForm.allowed_tools.split(',').map((s) => s.trim()).filter(Boolean),
        skill_metadata: {
          author: skillForm.author.trim() || 'hospital-medical-insurance-team',
          version: skillForm.version.trim() || '1.0.0',
          category: skillForm.category.trim() || null,
          tags: skillForm.tags.split(',').map((s) => s.trim()).filter(Boolean),
        },
      }
      if (editingSkill) {
        await requestJson(`/skills/${encodeURIComponent(editingSkill.skill_id)}`, {
          method: 'PUT',
          body: JSON.stringify(payload),
        })
      } else {
        await requestJson('/skills', {
          method: 'POST',
          body: JSON.stringify(payload),
        })
      }
      setSkillDialogOpen(false)
      await loadData()
    } catch (err) {
      setError(err instanceof Error ? err.message : '技能操作失败')
    } finally {
      setSubmitting(false)
    }
  }

  const deleteSkill = async (skillId: string) => {
    setError(null)
    try {
      await requestJson(`/skills/${encodeURIComponent(skillId)}`, { method: 'DELETE' })
      await loadData()
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除技能失败')
    }
  }

  const toggleSkillEnabled = async (skill: SkillItem) => {
    setError(null)
    try {
      await requestJson(`/skills/${encodeURIComponent(skill.skill_id)}`, {
        method: 'PUT',
        body: JSON.stringify({ enabled: !skill.enabled }),
      })
      await loadData()
    } catch (err) {
      setError(err instanceof Error ? err.message : '切换状态失败')
    }
  }

  const addStep = () => {
    setSkillForm((prev) => ({
      ...prev,
      steps: [...prev.steps, { step_id: `step_${prev.steps.length + 1}`, tool_id: '' }],
    }))
  }

  const removeStep = (index: number) => {
    setSkillForm((prev) => ({
      ...prev,
      steps: prev.steps.filter((_, i) => i !== index),
    }))
  }

  const updateStep = (index: number, field: 'step_id' | 'tool_id', value: string) => {
    setSkillForm((prev) => ({
      ...prev,
      steps: prev.steps.map((s, i) => (i === index ? { ...s, [field]: value } : s)),
    }))
  }

  const toggleRequiredRole = (roleId: string) => {
    setSkillForm((prev) => ({
      ...prev,
      required_roles: prev.required_roles.includes(roleId)
        ? prev.required_roles.filter((r) => r !== roleId)
        : [...prev.required_roles, roleId],
    }))
  }

  const filteredTools = tools.filter((t) => t.owner === currentRole || t.required_roles.includes(currentRole))
  const filteredSkills = skills.filter((s) => s.owner === currentRole || s.required_roles.includes(currentRole))

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">工具与技能管理</h2>
          <p className="text-sm text-gray-500 mt-1">管理 Agent 可调用的工具和编排技能</p>
        </div>
        <div className="flex gap-2">
          <Badge className="bg-blue-100 text-blue-800">{tools.length}个工具</Badge>
          <Badge className="bg-purple-100 text-purple-800">{skills.length}个技能</Badge>
            </div>
            <div className="border-t pt-3 mt-4">
              <label className="text-sm font-semibold text-gray-700 mb-2 block">元数据信息 (Anthropic Skills 规范)</label>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-sm font-medium text-gray-700">许可证</label>
                  <Select value={skillForm.license} onValueChange={(v) => { if (v) setSkillForm((prev) => ({ ...prev, license: v })) }}>
                    <SelectTrigger>
                      <SelectValue placeholder="选择许可证" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="MIT">MIT</SelectItem>
                      <SelectItem value="Apache-2.0">Apache-2.0</SelectItem>
                      <SelectItem value="GPL-3.0">GPL-3.0</SelectItem>
                      <SelectItem value="">无</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="text-sm font-medium text-gray-700">兼容性说明</label>
                  <Input
                    placeholder="环境要求"
                    value={skillForm.compatibility}
                    onChange={(e) => setSkillForm((prev) => ({ ...prev, compatibility: e.target.value }))}
                    maxLength={500}
                  />
                </div>
              </div>
              <div className="mt-2">
                <label className="text-sm font-medium text-gray-700">允许的工具（逗号分隔模式）</label>
                <Input
                  placeholder="Bash(python:*) Bash(npm:*)"
                  value={skillForm.allowed_tools}
                  onChange={(e) => setSkillForm((prev) => ({ ...prev, allowed_tools: e.target.value }))}
                />
              </div>
              <div className="grid grid-cols-2 gap-3 mt-2">
                <div>
                  <label className="text-sm font-medium text-gray-700">作者</label>
                  <Input
                    placeholder="作者名称"
                    value={skillForm.author}
                    onChange={(e) => setSkillForm((prev) => ({ ...prev, author: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="text-sm font-medium text-gray-700">版本</label>
                  <Input
                    placeholder="1.0.0"
                    value={skillForm.version}
                    onChange={(e) => setSkillForm((prev) => ({ ...prev, version: e.target.value }))}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3 mt-2">
                <div>
                  <label className="text-sm font-medium text-gray-700">分类</label>
                  <Input
                    placeholder="workflow-automation"
                    value={skillForm.category}
                    onChange={(e) => setSkillForm((prev) => ({ ...prev, category: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="text-sm font-medium text-gray-700">标签（逗号分隔）</label>
                  <Input
                    placeholder="insurance, settlement, guidance"
                    value={skillForm.tags}
                    onChange={(e) => setSkillForm((prev) => ({ ...prev, tags: e.target.value }))}
                  />
                </div>
              </div>
            </div>
          </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">{error}</div>
      )}

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="tools" className="flex items-center gap-1.5">
            <Wrench className="w-4 h-4" />
            工具管理
          </TabsTrigger>
          <TabsTrigger value="skills" className="flex items-center gap-1.5">
            <Layers className="w-4 h-4" />
            技能管理
          </TabsTrigger>
        </TabsList>

        <TabsContent value="tools">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span className="flex items-center gap-2">
                  <Wrench className="w-5 h-5" />
                  工具列表
                </span>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={loadData} disabled={loading}>
                    {loading ? '加载中...' : '刷新'}
                  </Button>
                  <Button size="sm" onClick={openCreateTool}>
                    <Plus className="w-4 h-4 mr-1" />
                    添加工具
                  </Button>
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="text-center py-8 text-gray-500">加载中...</div>
              ) : filteredTools.length === 0 ? (
                <div className="text-center py-8 text-gray-500">暂无工具数据</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left">
                        <th className="pb-3 pr-4 font-medium text-gray-600">名称</th>
                        <th className="pb-3 pr-4 font-medium text-gray-600">归属</th>
                        <th className="pb-3 pr-4 font-medium text-gray-600">类型</th>
                        <th className="pb-3 pr-4 font-medium text-gray-600">风险等级</th>
                        <th className="pb-3 pr-4 font-medium text-gray-600">状态</th>
                        <th className="pb-3 font-medium text-gray-600">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredTools.map((tool) => (
                        <tr key={tool.tool_id} className="border-b last:border-0 hover:bg-gray-50">
                          <td className="py-3 pr-4">
                            <div>
                              <div className="font-medium">{tool.name}</div>
                              <div className="text-xs text-gray-500 mt-0.5">{tool.description}</div>
                            </div>
                          </td>
                          <td className="py-3 pr-4">{ownerBadge(tool.owner)}</td>
                          <td className="py-3 pr-4">
                            <Badge variant="outline">{TOOL_TYPE_LABELS[tool.tool_type] ?? tool.tool_type}</Badge>
                          </td>
                          <td className="py-3 pr-4">
                            <Badge className={RISK_COLORS[tool.risk_level] ?? 'bg-gray-100 text-gray-800'}>
                              {RISK_LABELS[tool.risk_level] ?? tool.risk_level}
                            </Badge>
                          </td>
                          <td className="py-3 pr-4">
                            <button
                              onClick={() => toggleToolEnabled(tool)}
                              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors cursor-pointer ${
                                tool.enabled
                                  ? 'bg-green-100 text-green-800 hover:bg-green-200'
                                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                              }`}
                            >
                              {tool.enabled ? '已启用' : '已禁用'}
                            </button>
                          </td>
                          <td className="py-3">
                            <div className="flex gap-1">
                              <Button variant="ghost" size="icon-sm" onClick={() => openEditTool(tool)} title="编辑">
                                <Pencil className="w-4 h-4" />
                              </Button>
                              <Button variant="ghost" size="icon-sm" onClick={() => deleteTool(tool.tool_id)} title="删除">
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
        </TabsContent>

        <TabsContent value="skills">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span className="flex items-center gap-2">
                  <Layers className="w-5 h-5" />
                  技能列表
                </span>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={loadData} disabled={loading}>
                    {loading ? '加载中...' : '刷新'}
                  </Button>
                  <Button size="sm" onClick={openCreateSkill}>
                    <Plus className="w-4 h-4 mr-1" />
                    添加技能
                  </Button>
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="text-center py-8 text-gray-500">加载中...</div>
              ) : filteredSkills.length === 0 ? (
                <div className="text-center py-8 text-gray-500">暂无技能数据</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left">
                        <th className="pb-3 pr-4 font-medium text-gray-600">名称</th>
                        <th className="pb-3 pr-4 font-medium text-gray-600">归属</th>
                        <th className="pb-3 pr-4 font-medium text-gray-600">策略</th>
                        <th className="pb-3 pr-4 font-medium text-gray-600">步骤数</th>
                        <th className="pb-3 pr-4 font-medium text-gray-600">状态</th>
                        <th className="pb-3 font-medium text-gray-600">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredSkills.map((skill) => (
                        <tr key={skill.skill_id} className="border-b last:border-0 hover:bg-gray-50">
                          <td className="py-3 pr-4">
                            <div>
                              <div className="font-medium">{skill.name}</div>
                              <div className="text-xs text-gray-500 mt-0.5">{skill.description}</div>
                            </div>
                          </td>
                          <td className="py-3 pr-4">{ownerBadge(skill.owner)}</td>
                          <td className="py-3 pr-4">
                            <Badge variant="outline">
                              {STRATEGY_ICONS[skill.execution_strategy]} {STRATEGY_LABELS[skill.execution_strategy] ?? skill.execution_strategy}
                            </Badge>
                          </td>
                          <td className="py-3 pr-4">
                            <Badge variant="outline">{skill.steps.length}步</Badge>
                          </td>
                          <td className="py-3 pr-4">
                            <button
                              onClick={() => toggleSkillEnabled(skill)}
                              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors cursor-pointer ${
                                skill.enabled
                                  ? 'bg-green-100 text-green-800 hover:bg-green-200'
                                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                              }`}
                            >
                              {skill.enabled ? '已启用' : '已禁用'}
                            </button>
                          </td>
                          <td className="py-3">
                            <div className="flex gap-1">
                              <Button variant="ghost" size="icon-sm" onClick={() => openEditSkill(skill)} title="编辑">
                                <Pencil className="w-4 h-4" />
                              </Button>
                              <Button variant="ghost" size="icon-sm" onClick={() => deleteSkill(skill.skill_id)} title="删除">
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
        </TabsContent>
      </Tabs>

      <Dialog open={toolDialogOpen} onOpenChange={setToolDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{editingTool ? '编辑工具' : '添加工具'}</DialogTitle>
            <DialogDescription>
              {editingTool ? '修改工具配置信息' : '创建新的 Agent 工具'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium text-gray-700">工具ID</label>
              <Input
                placeholder="tool-id"
                value={toolForm.tool_id}
                onChange={(e) => setToolForm((prev) => ({ ...prev, tool_id: e.target.value }))}
                disabled={!!editingTool}
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">名称</label>
              <Input
                placeholder="工具名称"
                value={toolForm.name}
                onChange={(e) => setToolForm((prev) => ({ ...prev, name: e.target.value }))}
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">描述</label>
              <Textarea
                placeholder="工具描述"
                value={toolForm.description}
                onChange={(e) => setToolForm((prev) => ({ ...prev, description: e.target.value }))}
                className="min-h-[60px]"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium text-gray-700">归属角色</label>
                <Select value={toolForm.owner} onValueChange={(v) => { if (v) setToolForm((prev) => ({ ...prev, owner: v })) }}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {roles.map((r) => (
                      <SelectItem key={r.id} value={r.id}>{r.icon} {r.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700">类型</label>
                <Select value={toolForm.tool_type} onValueChange={(v) => { if (v) setToolForm((prev) => ({ ...prev, tool_type: v })) }}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="adapter_call">适配器调用</SelectItem>
                    <SelectItem value="knowledge_retrieval">知识检索</SelectItem>
                    <SelectItem value="mcp_tool_call">MCP工具调用</SelectItem>
                    <SelectItem value="result_building">结果构建</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium text-gray-700">风险等级</label>
                <Select value={toolForm.risk_level} onValueChange={(v) => { if (v) setToolForm((prev) => ({ ...prev, risk_level: v })) }}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="low">低风险</SelectItem>
                    <SelectItem value="medium">中风险</SelectItem>
                    <SelectItem value="high">高风险</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700">能力引用</label>
                <Input
                  placeholder="capability_ref"
                  value={toolForm.capability_ref}
                  onChange={(e) => setToolForm((prev) => ({ ...prev, capability_ref: e.target.value }))}
                />
              </div>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">所需角色（逗号分隔）</label>
              <Input
                placeholder="cashier, medical_office"
                value={toolForm.required_roles}
                onChange={(e) => setToolForm((prev) => ({ ...prev, required_roles: e.target.value }))}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setToolDialogOpen(false)}>取消</Button>
            <Button onClick={submitTool} disabled={submitting}>
              {submitting ? '提交中...' : editingTool ? '保存' : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={skillDialogOpen} onOpenChange={setSkillDialogOpen}>
        <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingSkill ? '编辑技能' : '添加技能'}</DialogTitle>
            <DialogDescription>
              {editingSkill ? '修改技能配置信息' : '创建新的编排技能'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium text-gray-700">技能ID</label>
              <Input
                placeholder="skill-id"
                value={skillForm.skill_id}
                onChange={(e) => setSkillForm((prev) => ({ ...prev, skill_id: e.target.value }))}
                disabled={!!editingSkill}
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">名称</label>
              <Input
                placeholder="技能名称"
                value={skillForm.name}
                onChange={(e) => setSkillForm((prev) => ({ ...prev, name: e.target.value }))}
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">描述</label>
              <Textarea
                placeholder="技能描述"
                value={skillForm.description}
                onChange={(e) => setSkillForm((prev) => ({ ...prev, description: e.target.value }))}
                className="min-h-[60px]"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium text-gray-700">归属角色</label>
                <Select value={skillForm.owner} onValueChange={(v) => { if (v) setSkillForm((prev) => ({ ...prev, owner: v })) }}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {roles.map((r) => (
                      <SelectItem key={r.id} value={r.id}>{r.icon} {r.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700">执行策略</label>
                <Select value={skillForm.execution_strategy} onValueChange={(v) => { if (v) setSkillForm((prev) => ({ ...prev, execution_strategy: v })) }}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="sequential">→ 顺序执行</SelectItem>
                    <SelectItem value="parallel">⇉ 并行执行</SelectItem>
                    <SelectItem value="conditional">◇ 条件执行</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">意图关键词（逗号分隔）</label>
              <Input
                placeholder="结算失败, 结算异常, ERR"
                value={skillForm.intent_keywords}
                onChange={(e) => setSkillForm((prev) => ({ ...prev, intent_keywords: e.target.value }))}
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700 mb-2 block">所需角色</label>
              <div className="flex flex-wrap gap-2">
                {roles.map((r) => (
                  <button
                    key={r.id}
                    type="button"
                    onClick={() => toggleRequiredRole(r.id)}
                    className={`px-3 py-1.5 rounded-md text-sm cursor-pointer transition-colors ${
                      skillForm.required_roles.includes(r.id)
                        ? 'bg-blue-600 text-white hover:bg-blue-700'
                        : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                    }`}
                  >
                    {r.icon} {r.name}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-sm font-medium text-gray-700">执行步骤</label>
                <Button variant="outline" size="sm" onClick={addStep}>
                  <Plus className="w-3 h-3 mr-1" />
                  添加步骤
                </Button>
              </div>
              <div className="space-y-2">
                {skillForm.steps.map((step, index) => (
                  <div key={index} className="flex items-center gap-2">
                    <span className="text-xs text-gray-500 w-6 shrink-0">{index + 1}.</span>
                    <Input
                      placeholder="步骤ID"
                      value={step.step_id}
                      onChange={(e) => updateStep(index, 'step_id', e.target.value)}
                      className="w-32"
                    />
                    <Select value={step.tool_id} onValueChange={(v) => { if (v) updateStep(index, 'tool_id', v) }}>
                      <SelectTrigger className="flex-1">
                        <SelectValue placeholder="选择工具" />
                      </SelectTrigger>
                      <SelectContent>
                        {tools.map((t) => (
                          <SelectItem key={t.tool_id} value={t.tool_id}>{t.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {skillForm.steps.length > 1 && (
                      <Button variant="ghost" size="icon-sm" onClick={() => removeStep(index)}>
                        <Trash2 className="w-4 h-4 text-red-500" />
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSkillDialogOpen(false)}>取消</Button>
            <Button onClick={submitSkill} disabled={submitting}>
              {submitting ? '提交中...' : editingSkill ? '保存' : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

async function fetchTools(role: RoleId): Promise<ToolItem[]> {
  try {
    return await requestJson<ToolItem[]>(`/tools/by-role/${encodeURIComponent(role)}`)
  } catch {
    try {
      return await requestJson<ToolItem[]>('/tools')
    } catch {
      return fallbackTools
    }
  }
}

async function fetchSkills(role: RoleId): Promise<SkillItem[]> {
  try {
    return await requestJson<SkillItem[]>(`/skills/by-role/${encodeURIComponent(role)}`)
  } catch {
    try {
      return await requestJson<SkillItem[]>('/skills')
    } catch {
      return fallbackSkills
    }
  }
}