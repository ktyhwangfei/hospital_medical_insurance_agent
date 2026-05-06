'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { Send, Bot, User, Sparkles, AlertTriangle } from 'lucide-react'
import { sendChat, confirmTask } from '@/lib/api-client'
import { useApiContext } from '@/lib/api-context'
import { ApiClientError } from '@/lib/types'
import type { AgentResponse, ChatRequest } from '@/lib/types'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  fallback?: boolean
}

interface PendingConfirmation {
  taskId: string
  description: string
}

function extractContent(result: Record<string, unknown>): string {
  const content = result.content
  if (typeof content === 'string') return content
  if (content === null || content === undefined) return JSON.stringify(result, null, 2)
  return JSON.stringify(content, null, 2)
}

export default function SettlementChat({ currentRole }: { currentRole: string }) {
  const { connectionStatus, setConnected, setFallback } = useApiContext()
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'assistant',
      content:
        '您好！我是医保AI导办助手 🤖\n\n我可以帮您：\n• 查询医保结算异常原因\n• 解释医保错误码\n• 生成出院前质控清单\n• 分析DRG/DIP盈亏情况\n• 提供处理步骤导办\n\n请告诉我您需要什么帮助？',
    },
  ])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null)
  const [confirmReason, setConfirmReason] = useState('')
  const [isConfirming, setIsConfirming] = useState(false)

  const handleSend = async (text?: string) => {
    const messageText = text || input
    if (!messageText.trim()) return

    setMessages((prev) => [...prev, { role: 'user', content: messageText }])
    setInput('')
    setIsLoading(true)

    const request: ChatRequest = {
      message: messageText,
      user_id: 'demo',
      role: currentRole,
      patient_id: 'P001',
      encounter_id: 'E001',
    }

    try {
      const response: AgentResponse = await sendChat(request)

      if (response.fallback) {
        setFallback()
      } else {
        setConnected()
      }

      const content = extractContent(response.result)
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content, fallback: response.fallback },
      ])

      if (
        response.status === 'waiting_human_confirmation' &&
        response.tasks.length > 0
      ) {
        const task = response.tasks[0]
        const taskId = task.task_id
        if (taskId) {
          setPendingConfirmation({
            taskId,
            description: task.description || task.action || '高风险操作',
          })
        }
      }
    } catch (error) {
      if (error instanceof ApiClientError) {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: `❌ 请求失败\n错误码: ${error.detail.error_code}\n${error.detail.message}`,
          },
        ])
      }
    } finally {
      setIsLoading(false)
    }
  }

  const handleTaskConfirm = async (action: 'confirm' | 'reject') => {
    if (!pendingConfirmation) return

    setIsConfirming(true)
    try {
      const result = await confirmTask({
        task_id: pendingConfirmation.taskId,
        action,
        user_id: 'demo',
        reason: confirmReason || undefined,
      })

      const label = action === 'confirm' ? '✅ 已确认执行' : '❌ 已拒绝执行'
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `${label}\n任务: ${pendingConfirmation.description}\n任务ID: ${result.task_id}\n状态: ${result.status}`,
        },
      ])
    } catch (error) {
      if (error instanceof ApiClientError) {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: `❌ 确认操作失败\n错误码: ${error.detail.error_code}\n${error.detail.message}`,
          },
        ])
      }
    } finally {
      setIsConfirming(false)
      setPendingConfirmation(null)
      setConfirmReason('')
    }
  }

  const quickQuestions = [
    '为什么这个患者结算失败',
    '这个患者出院前还有哪些风险',
    '本月哪个科室DRG亏损最多',
  ]

  const statusLabel =
    connectionStatus === 'connected'
      ? '已连接'
      : connectionStatus === 'fallback'
        ? '离线模式'
        : '未检测'

  const statusColor =
    connectionStatus === 'connected'
      ? 'bg-green-50 text-green-700'
      : connectionStatus === 'fallback'
        ? 'bg-yellow-50 text-yellow-700'
        : 'bg-gray-50 text-gray-500'

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 h-[calc(100vh-200px)]">
      {/* 左侧：快捷问题 */}
      <Card className="lg:col-span-1">
        <CardHeader>
          <CardTitle className="text-base">💡 快捷提问</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {quickQuestions.map((q) => (
            <Button
              key={q}
              variant="ghost"
              className="w-full justify-start text-left h-auto py-3 px-4 whitespace-normal"
              onClick={() => handleSend(q)}
            >
              {q}
            </Button>
          ))}

          <div className="pt-4 border-t">
            <p className="text-xs text-gray-500 mb-2">当前角色视图</p>
            <Badge variant="outline" className="w-full justify-center py-1">
              {currentRole === 'cashier' && '💰 收费员视图'}
              {currentRole === 'insurance_office' && '🏥 医保办视图'}
              {currentRole === 'it_department' && '💻 信息科视图'}
              {currentRole === 'medical_record' && '📋 病案室视图'}
            </Badge>
          </div>
        </CardContent>
      </Card>

      {/* 右侧：对话界面 */}
      <Card className="lg:col-span-3 flex flex-col">
        <CardHeader className="border-b">
          <div className="flex items-center gap-3">
            <Avatar className="bg-blue-600">
              <AvatarFallback>
                <Bot className="w-5 h-5 text-white" />
              </AvatarFallback>
            </Avatar>
            <div>
              <CardTitle className="text-base">医保AI导办助手</CardTitle>
              <p className="text-xs text-gray-500">在线 • 响应时间 {"<"}1秒</p>
            </div>
            <Badge variant="outline" className={`ml-auto ${statusColor}`}>
              <Sparkles className="w-3 h-3 mr-1" />
              {statusLabel}
            </Badge>
          </div>
        </CardHeader>

        <CardContent className="flex-1 flex flex-col p-0">
          <ScrollArea className="flex-1 p-6">
            <div className="space-y-4">
              {messages.map((msg, idx) => (
                <div
                  key={idx}
                  className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  {msg.role === 'assistant' && (
                    <Avatar className="w-8 h-8 bg-blue-600">
                      <AvatarFallback>
                        <Bot className="w-4 h-4 text-white" />
                      </AvatarFallback>
                    </Avatar>
                  )}
                  <div
                    className={`max-w-[80%] rounded-lg p-4 ${
                      msg.role === 'user'
                        ? 'bg-blue-600 text-white'
                        : msg.fallback
                          ? 'bg-yellow-50 text-gray-900 border border-yellow-200'
                          : 'bg-gray-100 text-gray-900'
                    }`}
                  >
                    <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                    {msg.fallback && (
                      <p className="text-xs text-yellow-600 mt-2">⚠️ 离线演示模式</p>
                    )}
                  </div>
                  {msg.role === 'user' && (
                    <Avatar className="w-8 h-8 bg-gray-600">
                      <AvatarFallback>
                        <User className="w-4 h-4 text-white" />
                      </AvatarFallback>
                    </Avatar>
                  )}
                </div>
              ))}
              {isLoading && (
                <div className="flex gap-3">
                  <Avatar className="w-8 h-8 bg-blue-600">
                    <AvatarFallback>
                      <Bot className="w-4 h-4 text-white" />
                    </AvatarFallback>
                  </Avatar>
                  <div className="bg-gray-100 rounded-lg p-4">
                    <div className="flex gap-1">
                      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></span>
                      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-100"></span>
                      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-200"></span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </ScrollArea>

          <div className="p-4 border-t">
            <div className="flex gap-2">
              <Input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && handleSend()}
                placeholder="输入您的问题..."
                className="flex-1"
              />
              <Button onClick={() => handleSend()} disabled={isLoading}>
                <Send className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 人工确认 Dialog */}
      <Dialog
        open={!!pendingConfirmation}
        onOpenChange={(open) => {
          if (!open) {
            setPendingConfirmation(null)
            setConfirmReason('')
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-yellow-600" />
              高风险操作确认
            </DialogTitle>
            <DialogDescription>
              此操作需要人工确认后才能在业务系统中执行。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div className="rounded-lg bg-yellow-50 border border-yellow-200 p-3">
              <p className="text-sm font-medium text-yellow-800">
                {pendingConfirmation?.description}
              </p>
              <p className="text-xs text-yellow-600 mt-1">
                任务ID: {pendingConfirmation?.taskId}
              </p>
            </div>

            <Textarea
              value={confirmReason}
              onChange={(e) => setConfirmReason(e.target.value)}
              placeholder="请输入确认/拒绝原因（可选）"
              className="min-h-[80px]"
            />
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => handleTaskConfirm('reject')}
              disabled={isConfirming}
            >
              拒绝执行
            </Button>
            <Button
              onClick={() => handleTaskConfirm('confirm')}
              disabled={isConfirming}
            >
              {isConfirming ? '处理中...' : '确认执行'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
