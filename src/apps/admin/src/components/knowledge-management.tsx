'use client'

import { useEffect, useState } from 'react'
import {
  AlertCircle,
  BookOpen,
  FileText,
  MessageSquareText,
  Pencil,
  Plus,
  RefreshCw,
  ScrollText,
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
  listErrorCodes,
  createErrorCode,
  updateErrorCode,
  deleteErrorCode,
} from '@/lib/api-client'
import { useApiContext } from '@/lib/api-context'
import type { ErrorCode, ErrorCodeCreate, RoleId } from '@/lib/types'

// ─── Constants ───────────────────────────────────────────────────────────────

const RESPONSIBLE_ROLES = [
  { id: 'cashier', label: '收费员' },
  { id: 'medical_office', label: '医保办' },
  { id: 'information_department', label: '信息科' },
  { id: 'medical_record_staff', label: '病案室' },
  { id: 'clinician', label: '临床医生' },
]

const ROLE_BADGE_COLORS: Record<string, string> = {
  cashier: 'bg-green-100 text-green-800',
  medical_office: 'bg-blue-100 text-blue-800',
  information_department: 'bg-purple-100 text-purple-800',
  medical_record_staff: 'bg-orange-100 text-orange-800',
  clinician: 'bg-teal-100 text-teal-800',
}

// ─── Types ───────────────────────────────────────────────────────────────────

interface ErrorCodeForm {
  error_code: string
  description: string
  exception_type: string
  responsible_role: string
  recommendation: string
}

const EMPTY_ERROR_CODE_FORM: ErrorCodeForm = {
  error_code: '',
  description: '',
  exception_type: '',
  responsible_role: 'cashier',
  recommendation: '',
}

// ─── Skeleton Row ────────────────────────────────────────────────────────────

function TableSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <tbody>
      {Array.from({ length: rows }).map((_, i) => (
        <tr key={i} className="border-b last:border-0">
          <td className="py-3 pr-4">
            <div className="h-4 w-32 animate-pulse rounded bg-gray-200" />
            <div className="mt-1.5 h-3 w-48 animate-pulse rounded bg-gray-100" />
          </td>
          <td className="py-3 pr-4">
            <div className="h-5 w-14 animate-pulse rounded-full bg-gray-200" />
          </td>
          <td className="py-3 pr-4">
            <div className="h-4 w-20 animate-pulse rounded bg-gray-200" />
          </td>
          <td className="py-3">
            <div className="flex gap-1">
              <div className="h-8 w-8 animate-pulse rounded bg-gray-200" />
              <div className="h-8 w-8 animate-pulse rounded bg-gray-200" />
            </div>
          </td>
        </tr>
      ))}
    </tbody>
  )
}

// ─── ErrorCodeCrud ───────────────────────────────────────────────────────────

function ErrorCodeCrud({ currentRole }: { currentRole: RoleId }) {
  const { setConnected, setFallback } = useApiContext()
  const [errorCodes, setErrorCodes] = useState<ErrorCode[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchCode, setSearchCode] = useState('')
  const [searchDesc, setSearchDesc] = useState('')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deletingCode, setDeletingCode] = useState<string | null>(null)
  const [editing, setEditing] = useState<ErrorCode | null>(null)
  const [form, setForm] = useState<ErrorCodeForm>(EMPTY_ERROR_CODE_FORM)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    loadData()
  }, [currentRole])

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listErrorCodes()
      setErrorCodes(data)
      setConnected()
    } catch {
      setErrorCodes([])
      setFallback()
    } finally {
      setLoading(false)
    }
  }

  const openCreate = () => {
    setEditing(null)
    setForm(EMPTY_ERROR_CODE_FORM)
    setDialogOpen(true)
  }

  const openEdit = (code: ErrorCode) => {
    setEditing(code)
    setForm({
      error_code: code.error_code,
      description: code.description,
      exception_type: code.exception_type,
      responsible_role: code.responsible_role,
      recommendation: code.recommendation,
    })
    setDialogOpen(true)
  }

  const openDelete = (errorCode: string) => {
    setDeletingCode(errorCode)
    setDeleteDialogOpen(true)
  }

  const handleSubmit = async () => {
    setError(null)
    if (!form.error_code.trim() || !form.description.trim()) {
      setError('错误码和描述不能为空')
      return
    }
    setSubmitting(true)
    try {
      if (editing) {
        const payload: Partial<ErrorCodeCreate> = {
          description: form.description.trim(),
          exception_type: form.exception_type.trim(),
          responsible_role: form.responsible_role,
          recommendation: form.recommendation.trim(),
        }
        await updateErrorCode(editing.error_code, payload)
      } else {
        const payload: ErrorCodeCreate = {
          error_code: form.error_code.trim(),
          description: form.description.trim(),
          exception_type: form.exception_type.trim(),
          responsible_role: form.responsible_role,
          recommendation: form.recommendation.trim(),
        }
        await createErrorCode(payload)
      }
      setDialogOpen(false)
      await loadData()
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async () => {
    if (!deletingCode) return
    setError(null)
    try {
      await deleteErrorCode(deletingCode)
      setDeleteDialogOpen(false)
      setDeletingCode(null)
      await loadData()
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败')
    }
  }

  const filtered = errorCodes.filter((c) => {
    if (searchCode && !c.error_code.toLowerCase().includes(searchCode.toLowerCase())) return false
    if (searchDesc && !c.description.toLowerCase().includes(searchDesc.toLowerCase())) return false
    return true
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span className="flex items-center gap-2">
            <AlertCircle className="w-5 h-5" />
            错误码列表
          </span>
          <div className="flex items-center gap-2">
            <div className="flex gap-2">
              <Input
                placeholder="按错误码搜索"
                value={searchCode}
                onChange={(e) => setSearchCode(e.target.value)}
                className="w-44"
              />
              <Input
                placeholder="按描述搜索"
                value={searchDesc}
                onChange={(e) => setSearchDesc(e.target.value)}
                className="w-44"
              />
            </div>
            <Button variant="outline" size="sm" onClick={loadData} disabled={loading}>
              <RefreshCw className={`w-4 h-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
              刷新
            </Button>
            <Button size="sm" onClick={openCreate}>
              <Plus className="w-4 h-4 mr-1" />
              添加错误码
            </Button>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {error && (
          <div className="mb-4 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">{error}</div>
        )}

        {loading ? (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left">
                <th className="pb-3 pr-4 font-medium text-gray-600">错误码</th>
                <th className="pb-3 pr-4 font-medium text-gray-600">描述</th>
                <th className="pb-3 pr-4 font-medium text-gray-600">异常类型</th>
                <th className="pb-3 pr-4 font-medium text-gray-600">负责角色</th>
                <th className="pb-3 font-medium text-gray-600">操作</th>
              </tr>
            </thead>
            <TableSkeleton rows={4} />
          </table>
        ) : filtered.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            <AlertCircle className="w-10 h-10 mx-auto mb-3 text-gray-300" />
            <p className="text-base font-medium">暂无错误码</p>
            <p className="text-sm mt-1 mb-4">错误码知识库当前为空，点击下方按钮创建第一个</p>
            <Button size="sm" onClick={openCreate}>
              <Plus className="w-4 h-4 mr-1" />
              创建第一个
            </Button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left">
                  <th className="pb-3 pr-4 font-medium text-gray-600">错误码</th>
                  <th className="pb-3 pr-4 font-medium text-gray-600">描述</th>
                  <th className="pb-3 pr-4 font-medium text-gray-600">异常类型</th>
                  <th className="pb-3 pr-4 font-medium text-gray-600">负责角色</th>
                  <th className="pb-3 font-medium text-gray-600">操作</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((code) => (
                  <tr key={code.error_code} className="border-b last:border-0 hover:bg-gray-50">
                    <td className="py-3 pr-4">
                      <code className="px-2 py-0.5 bg-gray-100 rounded text-sm font-mono">{code.error_code}</code>
                    </td>
                    <td className="py-3 pr-4 max-w-[260px]">
                      <div className="truncate" title={code.description}>{code.description}</div>
                    </td>
                    <td className="py-3 pr-4">{code.exception_type || '-'}</td>
                    <td className="py-3 pr-4">
                      <Badge className={ROLE_BADGE_COLORS[code.responsible_role] ?? 'bg-gray-100 text-gray-800'}>
                        {RESPONSIBLE_ROLES.find((r) => r.id === code.responsible_role)?.label ?? code.responsible_role}
                      </Badge>
                    </td>
                    <td className="py-3">
                      <div className="flex gap-1">
                        <Button variant="ghost" size="icon-sm" onClick={() => openEdit(code)} title="编辑">
                          <Pencil className="w-4 h-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => openDelete(code.error_code)}
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

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{editing ? '编辑错误码' : '添加错误码'}</DialogTitle>
            <DialogDescription>
              {editing ? '修改错误码配置信息' : '创建新的错误码知识条目'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium text-gray-700">错误码</label>
              <Input
                placeholder="如 ERR001"
                value={form.error_code}
                onChange={(e) => setForm((prev) => ({ ...prev, error_code: e.target.value }))}
                disabled={!!editing}
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">描述</label>
              <Textarea
                placeholder="错误码的详细描述信息"
                value={form.description}
                onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
                className="min-h-[60px]"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">异常类型</label>
              <Input
                placeholder="如 待遇资格校验失败"
                value={form.exception_type}
                onChange={(e) => setForm((prev) => ({ ...prev, exception_type: e.target.value }))}
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">负责角色</label>
              <Select
                value={form.responsible_role}
                onValueChange={(v) => { if (v) setForm((prev) => ({ ...prev, responsible_role: v })) }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {RESPONSIBLE_ROLES.map((role) => (
                    <SelectItem key={role.id} value={role.id}>{role.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700">处置建议</label>
              <Textarea
                placeholder="针对该错误码的处理建议"
                value={form.recommendation}
                onChange={(e) => setForm((prev) => ({ ...prev, recommendation: e.target.value }))}
                className="min-h-[60px]"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>取消</Button>
            <Button onClick={handleSubmit} disabled={submitting}>
              {submitting ? '提交中...' : editing ? '保存' : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
            <DialogDescription>
              确定要删除错误码 <strong>{deletingCode}</strong> 吗？此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>取消</Button>
            <Button variant="destructive" onClick={handleDelete}>确认删除</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}

// ─── KnowledgeManagement ─────────────────────────────────────────────────────

interface KnowledgeManagementProps {
  currentRole: RoleId
}

export default function KnowledgeManagement({ currentRole }: KnowledgeManagementProps) {
  const [activeTab, setActiveTab] = useState('error-codes')

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">知识管理</h2>
          <p className="text-sm text-gray-500 mt-1">管理错误码、规则、知识资产、申诉模板和提示词模板</p>
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="error-codes" className="flex items-center gap-1.5">
            <AlertCircle className="w-4 h-4" />
            错误码管理
          </TabsTrigger>
          <TabsTrigger value="rules" className="flex items-center gap-1.5">
            <ScrollText className="w-4 h-4" />
            规则解释
          </TabsTrigger>
          <TabsTrigger value="assets" className="flex items-center gap-1.5">
            <BookOpen className="w-4 h-4" />
            知识资产
          </TabsTrigger>
          <TabsTrigger value="appeal-templates" className="flex items-center gap-1.5">
            <FileText className="w-4 h-4" />
            申诉模板
          </TabsTrigger>
          <TabsTrigger value="prompt-templates" className="flex items-center gap-1.5">
            <MessageSquareText className="w-4 h-4" />
            提示词模板
          </TabsTrigger>
        </TabsList>

        <TabsContent value="error-codes">
          <ErrorCodeCrud currentRole={currentRole} />
        </TabsContent>

        <TabsContent value="rules">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ScrollText className="w-5 h-5" />
                规则解释
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-gray-500">规则解释管理功能即将上线。</p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="assets">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <BookOpen className="w-5 h-5" />
                知识资产
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-gray-500">知识资产管理功能即将上线。</p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="appeal-templates">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FileText className="w-5 h-5" />
                申诉模板
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-gray-500">申诉模板管理功能即将上线。</p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="prompt-templates">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <MessageSquareText className="w-5 h-5" />
                提示词模板
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-gray-500">提示词模板管理功能即将上线。</p>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
