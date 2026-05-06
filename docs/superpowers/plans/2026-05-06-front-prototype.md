# Front Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `prototype/` 的 Next.js 高保真原型接入后端真实 API，并新增 MCP 管理、知识浏览、模型测试三个页面，同时保留 mock 降级演示能力。

**Architecture:** 前端通过 `next.config.ts` rewrites 代理到 FastAPI 后端；所有 HTTP/SSE 调用集中在 `prototype/src/lib/api-client.ts`；全局连接状态由 `ApiProvider` 管理；新增页面沿用现有 Tab + Card + Badge + Grid 交互设计。

**Tech Stack:** Next.js 16、React 19、TypeScript 5、shadcn/ui、lucide-react、FastAPI backend API、SSE via `fetch` + `ReadableStream`。

---

## Scope Check

该规格包含多个页面，但它们共享同一个 Next.js 原型、同一套 API 客户端、同一套 mock 降级和同一套 UI 设计语言，因此作为一个前端原型模块计划执行。实施顺序采用“基础层 → API 层 → 页面层 → 验证文档”的垂直分解，每个任务可独立提交。

---

## File Structure

### Create

- `prototype/.env.example` — 前端 API 目标地址说明。
- `prototype/src/lib/types.ts` — 后端 API schema 的 TypeScript 镜像类型。
- `prototype/src/lib/api-context.tsx` — 全局 API 连接状态、fallback 状态和 demo user 上下文。
- `prototype/src/lib/api-client.ts` — 所有后端 API、SSE 解析和 mock 降级函数。
- `prototype/src/components/mcp-management.tsx` — MCP 管理 Tab 页面。
- `prototype/src/components/knowledge-explorer.tsx` — 知识浏览 Tab 页面。
- `prototype/src/components/model-test.tsx` — 模型测试 Tab 页面。

### Modify

- `prototype/next.config.ts` — 添加 rewrites 代理。
- `prototype/src/app/layout.tsx` — 包裹 `ApiProvider`。
- `prototype/src/app/page.tsx` — 扩展 7 个 Tab、连接状态指示器、新页面挂载。
- `prototype/src/components/settlement-chat.tsx` — 将 mock 对话切换为 API/SSE 调用，并处理澄清和人工确认。
- `prototype/src/lib/mock-data.ts` — 扩展 MCP、知识浏览、模型测试 mock 数据。
- `prototype/README.md` — 增加前后端联调说明。
- `prototype/原型交付文档.md` — 增加 API 集成、MCP、知识、模型测试说明。

### Verification Commands

- Frontend lint: `cd prototype && npm run lint`
- Frontend build: `cd prototype && npm run build`
- Backend API smoke: `python -m pytest src/tests/integration/test_mcp_management_api.py -v`
- Full backend regression: `python -m pytest src/tests -v`

---

## Task 1: Frontend Environment, Proxy, and Types

**Files:**
- Create: `prototype/.env.example`
- Create: `prototype/src/lib/types.ts`
- Modify: `prototype/next.config.ts`

- [ ] **Step 1: Add frontend env example**

Create `prototype/.env.example` with this content:

```env
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

- [ ] **Step 2: Add API proxy config**

Replace `prototype/next.config.ts` with:

```typescript
import type { NextConfig } from 'next'

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8000'

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/v1/medical-insurance-ai-agent/:path*',
        destination: `${apiBaseUrl}/api/v1/medical-insurance-ai-agent/:path*`,
      },
    ]
  },
}

export default nextConfig
```

- [ ] **Step 3: Add TypeScript API types**

Create `prototype/src/lib/types.ts` with:

```typescript
export type RoleId = 'cashier' | 'insurance_office' | 'it_department' | 'medical_record'

export type ApiConnectionStatus = 'unknown' | 'connected' | 'fallback'

export interface Citation {
  source_type: string
  source_id: string
  summary: string
}

export interface AgentTask {
  task_id?: string
  task_type?: string
  status?: string
  description?: string
  action?: string
  [key: string]: unknown
}

export interface ChatRequest {
  user_id: string
  role: string
  message: string
  patient_id?: string
  encounter_id?: string
}

export interface AgentResponse {
  scenario?: string | null
  status: string
  result: Record<string, unknown>
  citations: Citation[]
  tasks: AgentTask[]
  missing_fields: string[]
  uncertainties: string[]
  blocked_actions: string[]
  audit: Record<string, unknown>
  fallback?: boolean
}

export interface PatientContextResponse {
  patient: Record<string, unknown>
  visible_fields: string[]
  encounter_id?: string | null
  settlement_status?: string | null
  audit_risks?: unknown[] | null
  fallback?: boolean
}

export interface TaskConfirmRequest {
  task_id: string
  action: 'confirm' | 'reject'
  user_id: string
  reason?: string
}

export interface TaskConfirmResponse {
  task_id: string
  status: string
  confirmed_by: string
  confirmed_at: string
  reason?: string | null
  result: Record<string, unknown>
  fallback?: boolean
}

export interface WorkflowStatusResponse {
  workflow_id: string
  status: string
  fallback?: boolean
}

export interface TaskStatusResponse {
  task_id: string
  status: string
  fallback?: boolean
}

export interface ModelTestRequest {
  message: string
  scene: string
}

export interface ModelTestResponse {
  content: string
  model_name: string
  latency_ms: number
  prompt_tokens: number
  completion_tokens: number
  fallback?: boolean
}

export type McpTransport = 'stdio' | 'sse' | 'streamable_http'
export type McpServerStatus = 'enabled' | 'disabled' | 'degraded' | 'unhealthy'

export interface McpServer {
  server_id: string
  name: string
  endpoint: string
  transport: McpTransport
  status: McpServerStatus
  protocol_version?: string | null
  auth_headers: Record<string, string>
  metadata: Record<string, unknown>
  fallback?: boolean
}

export interface McpStorageHealth {
  status: string
  backend?: string
  details?: Record<string, unknown>
  fallback?: boolean
  [key: string]: unknown
}

export type SseEventType = 'step' | 'final' | 'error' | 'done' | 'token'

export interface SseEvent<T = unknown> {
  event: SseEventType
  data: T
}

export interface ApiErrorDetail {
  error_code: string
  message: string
  audit_event?: Record<string, unknown>
}

export class ApiClientError extends Error {
  readonly status: number
  readonly detail: ApiErrorDetail

  constructor(status: number, detail: ApiErrorDetail) {
    super(detail.message)
    this.name = 'ApiClientError'
    this.status = status
    this.detail = detail
  }
}
```

- [ ] **Step 4: Verify TypeScript compiles**

Run:

```cmd
cd prototype && npm run lint
```

Expected: command exits with code 0. If lint reports existing unrelated warnings, record them before changing behavior.

- [ ] **Step 5: Commit Task 1**

Run:

```cmd
git add prototype/.env.example prototype/next.config.ts prototype/src/lib/types.ts
git commit -m "feat: add prototype api proxy and types"
```

---

## Task 2: Mock Data Extensions

**Files:**
- Modify: `prototype/src/lib/mock-data.ts`

- [ ] **Step 1: Append MCP, knowledge, and model mock exports**

Append this code to `prototype/src/lib/mock-data.ts` after the existing exports:

```typescript
export const mockMcpServers = [
  {
    server_id: 'mcp-knowledge-search',
    name: '知识检索 MCP 服务',
    endpoint: 'http://127.0.0.1:9101/sse',
    transport: 'sse' as const,
    status: 'enabled' as const,
    protocol_version: '2025-03-26',
    auth_headers: {},
    metadata: { owner: '医保办', scene: 'knowledge_search' },
  },
  {
    server_id: 'mcp-policy-rules',
    name: '政策规则 MCP 服务',
    endpoint: 'http://127.0.0.1:9102/mcp',
    transport: 'streamable_http' as const,
    status: 'degraded' as const,
    protocol_version: '2025-03-26',
    auth_headers: {},
    metadata: { owner: '信息科', scene: 'policy_rule' },
  },
]

export const mockMcpStorageHealth = {
  status: 'ok',
  backend: 'memory',
  details: {
    server_count: 2,
    capability_count: 8,
    checked_at: '2026-05-06T13:00:00+08:00',
  },
}

export const mockMcpCapabilities = [
  { id: 'tool-search-policy', type: 'Tool', name: '政策检索工具', count: 3, color: 'text-blue-600' },
  { id: 'resource-error-codes', type: 'Resource', name: '错误码资源', count: 2, color: 'text-green-600' },
  { id: 'prompt-qc-guide', type: 'Prompt', name: '质控导办提示', count: 2, color: 'text-purple-600' },
  { id: 'service-risk-score', type: 'Service', name: '风险评分服务', count: 1, color: 'text-orange-600' },
]

export const mockKnowledgeAssets = [
  { title: '错误码知识库', value: '128条', coverage: 92, color: 'text-blue-600' },
  { title: '政策规则库', value: '56条', coverage: 81, color: 'text-green-600' },
  { title: 'DRG/DIP知识库', value: '34条', coverage: 74, color: 'text-purple-600' },
  { title: '提示模板库', value: '18个', coverage: 88, color: 'text-orange-600' },
]

export const mockRagResults = [
  { source: '医保政策规则库', score: 0.91, summary: '待遇资格校验失败时，应先核验参保状态、待遇享受期和账户状态。' },
  { source: '错误码知识库 ERR_001', score: 0.86, summary: 'ERR_001 表示患者待遇资格校验不通过，常见原因为医保卡未激活或待遇过期。' },
  { source: '结算异常处置流程', score: 0.78, summary: '收费员确认患者信息后，由医保办协助恢复待遇资格或指导患者补缴。' },
]

export const mockDrgRules = [
  { code: 'DRG-BM21', title: '髋膝关节置换病组', summary: '关注主要诊断、手术操作编码和高值耗材说明完整性。' },
  { code: 'DIP-CV1', title: '心血管介入病种', summary: '关注检查费用占比、耗材适应症和住院天数合理性。' },
]

export const mockPromptTemplates = [
  { name: '结算异常导办模板', scenario: 'settlement_exception_guidance', role: '收费员' },
  { name: '出院前质控模板', scenario: 'pre_discharge_quality_control', role: '病案室' },
  { name: '政策解释模板', scenario: 'policy_explanation', role: '医保办' },
]

export const mockModelTestResult = {
  content: '这是离线模式下的模型测试结果。后端模型服务不可用时，前端会保留演示体验。',
  model_name: 'mock-model',
  latency_ms: 120,
  prompt_tokens: 32,
  completion_tokens: 48,
}
```

- [ ] **Step 2: Verify lint**

Run:

```cmd
cd prototype && npm run lint
```

Expected: command exits with code 0.

- [ ] **Step 3: Commit Task 2**

Run:

```cmd
git add prototype/src/lib/mock-data.ts
git commit -m "feat: add prototype mock data for integration pages"
```

---

## Task 3: API Context

**Files:**
- Create: `prototype/src/lib/api-context.tsx`
- Modify: `prototype/src/app/layout.tsx`

- [ ] **Step 1: Create API context**

Create `prototype/src/lib/api-context.tsx` with:

```typescript
'use client'

import { createContext, useContext, useMemo, useState } from 'react'
import type { ApiConnectionStatus } from './types'

interface ApiContextValue {
  userId: string
  connectionStatus: ApiConnectionStatus
  setConnected: () => void
  setFallback: () => void
  resetConnection: () => void
}

const ApiContext = createContext<ApiContextValue | null>(null)

export function ApiProvider({ children }: { children: React.ReactNode }) {
  const [connectionStatus, setConnectionStatus] = useState<ApiConnectionStatus>('unknown')

  const value = useMemo<ApiContextValue>(
    () => ({
      userId: 'demo',
      connectionStatus,
      setConnected: () => setConnectionStatus('connected'),
      setFallback: () => setConnectionStatus('fallback'),
      resetConnection: () => setConnectionStatus('unknown'),
    }),
    [connectionStatus]
  )

  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>
}

export function useApiContext() {
  const context = useContext(ApiContext)
  if (!context) {
    throw new Error('useApiContext must be used within ApiProvider')
  }
  return context
}
```

- [ ] **Step 2: Wrap layout with ApiProvider**

Replace `prototype/src/app/layout.tsx` with:

```typescript
import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import { ApiProvider } from '@/lib/api-context'
import './globals.css'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: '医保AI导办与运营协同平台 - 原型演示',
  description: '医院医保智能工作台原型演示系统',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-CN">
      <body className={inter.className}>
        <ApiProvider>{children}</ApiProvider>
      </body>
    </html>
  )
}
```

- [ ] **Step 3: Verify lint**

Run:

```cmd
cd prototype && npm run lint
```

Expected: command exits with code 0.

- [ ] **Step 4: Commit Task 3**

Run:

```cmd
git add prototype/src/lib/api-context.tsx prototype/src/app/layout.tsx
git commit -m "feat: add prototype api context"
```

---

## Task 4: API Client Core and Endpoint Functions

**Files:**
- Create: `prototype/src/lib/api-client.ts`

- [ ] **Step 1: Create API client with helpers and endpoints**

Create `prototype/src/lib/api-client.ts` with:

```typescript
import {
  mockAIChatResponses,
  mockMcpServers,
  mockMcpStorageHealth,
  mockModelTestResult,
} from './mock-data'
import type {
  AgentResponse,
  ChatRequest,
  McpServer,
  McpStorageHealth,
  ModelTestRequest,
  ModelTestResponse,
  PatientContextResponse,
  SseEvent,
  TaskConfirmRequest,
  TaskConfirmResponse,
  TaskStatusResponse,
  WorkflowStatusResponse,
} from './types'
import { ApiClientError } from './types'

const API_PREFIX = '/api/v1/medical-insurance-ai-agent'

async function parseError(response: Response): Promise<ApiClientError> {
  const body = await response.json().catch(() => null)
  const detail = body?.detail
  if (detail?.error_code && detail?.message) {
    return new ApiClientError(response.status, detail)
  }
  return new ApiClientError(response.status, {
    error_code: `HTTP_${response.status}`,
    message: response.statusText || '请求失败',
  })
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  })
  if (!response.ok) {
    throw await parseError(response)
  }
  return (await response.json()) as T
}

function fallbackAgentResponse(message: string): AgentResponse {
  const lines = mockAIChatResponses[message] || [
    `我理解您的问题：${message}`,
    '',
    '后端服务当前不可用，已切换到离线演示模式。',
    '请启动 FastAPI 服务后重新尝试真实联调。',
  ]
  return {
    scenario: 'offline_demo',
    status: 'success',
    result: { content: lines.join('\n') },
    citations: [{ source_type: 'mock', source_id: 'prototype-mock', summary: '前端离线演示数据' }],
    tasks: [],
    missing_fields: [],
    uncertainties: ['后端不可达，当前展示 mock 降级结果'],
    blocked_actions: [],
    audit: { fallback: true },
    fallback: true,
  }
}

export async function sendChat(request: ChatRequest): Promise<AgentResponse> {
  try {
    return await requestJson<AgentResponse>('/chat', {
      method: 'POST',
      body: JSON.stringify(request),
    })
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error
    }
    return fallbackAgentResponse(request.message)
  }
}

export async function sendChatStream(
  request: ChatRequest,
  onEvent: (event: SseEvent) => void
): Promise<void> {
  const response = await fetch(`${API_PREFIX}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!response.ok) {
    throw await parseError(response)
  }
  if (!response.body) {
    throw new Error('浏览器不支持流式响应')
  }
  await readSseStream(response.body, onEvent)
}

export async function testModel(request: ModelTestRequest): Promise<ModelTestResponse> {
  try {
    return await requestJson<ModelTestResponse>('/model-test', {
      method: 'POST',
      body: JSON.stringify(request),
    })
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error
    }
    return { ...mockModelTestResult, fallback: true }
  }
}

export async function testModelStream(
  request: ModelTestRequest,
  onEvent: (event: SseEvent) => void
): Promise<void> {
  const response = await fetch(`${API_PREFIX}/model-test/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!response.ok) {
    throw await parseError(response)
  }
  if (!response.body) {
    throw new Error('浏览器不支持流式响应')
  }
  await readSseStream(response.body, onEvent)
}

export async function fetchPatientContext(
  patientId: string,
  encounterId: string,
  userId: string,
  role: string
): Promise<PatientContextResponse> {
  try {
    const query = new URLSearchParams({ user_id: userId, role })
    return await requestJson<PatientContextResponse>(`/patient-context/${patientId}/${encounterId}?${query}`)
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error
    }
    return {
      patient: { patient_id: patientId, name: '张*' },
      visible_fields: ['encounter_id', 'settlement_status'],
      encounter_id: encounterId,
      settlement_status: 'failed',
      audit_risks: [],
      fallback: true,
    }
  }
}

export async function confirmTask(request: TaskConfirmRequest): Promise<TaskConfirmResponse> {
  try {
    return await requestJson<TaskConfirmResponse>('/tasks/confirm', {
      method: 'POST',
      body: JSON.stringify(request),
    })
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error
    }
    return {
      task_id: request.task_id,
      status: request.action === 'confirm' ? 'confirmed' : 'rejected',
      confirmed_by: request.user_id,
      confirmed_at: new Date().toISOString(),
      reason: request.reason,
      result: request.action === 'confirm' ? {} : { blocked: true, message: '用户拒绝执行该操作' },
      fallback: true,
    }
  }
}

export async function fetchWorkflowStatus(workflowId: string): Promise<WorkflowStatusResponse> {
  try {
    return await requestJson<WorkflowStatusResponse>(`/workflows/${workflowId}`)
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error
    }
    return { workflow_id: workflowId, status: 'pending', fallback: true }
  }
}

export async function fetchTaskStatus(taskId: string): Promise<TaskStatusResponse> {
  try {
    return await requestJson<TaskStatusResponse>(`/tasks/${taskId}`)
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error
    }
    return { task_id: taskId, status: 'pending', fallback: true }
  }
}

export async function fetchMcpStorageHealth(): Promise<McpStorageHealth> {
  try {
    return await requestJson<McpStorageHealth>('/mcp/storage/health')
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error
    }
    return { ...mockMcpStorageHealth, fallback: true }
  }
}

export async function registerMcpServer(server: McpServer): Promise<McpServer> {
  try {
    return await requestJson<McpServer>('/mcp/servers', {
      method: 'POST',
      body: JSON.stringify(server),
    })
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error
    }
    return { ...server, fallback: true }
  }
}

export function initialMcpServers(): McpServer[] {
  return mockMcpServers.map((server) => ({ ...server }))
}

async function readSseStream(body: ReadableStream<Uint8Array>, onEvent: (event: SseEvent) => void) {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() || ''
    for (const chunk of chunks) {
      const event = parseSseChunk(chunk)
      if (event) onEvent(event)
    }
  }
}

function parseSseChunk(chunk: string): SseEvent | null {
  const lines = chunk.split('\n')
  const eventLine = lines.find((line) => line.startsWith('event:'))
  const dataLine = lines.find((line) => line.startsWith('data:'))
  if (!eventLine || !dataLine) return null
  const event = eventLine.replace('event:', '').trim() as SseEvent['event']
  const rawData = dataLine.replace('data:', '').trim()
  return { event, data: rawData ? JSON.parse(rawData) : {} }
}
```

- [ ] **Step 2: Verify lint**

Run:

```cmd
cd prototype && npm run lint
```

Expected: command exits with code 0.

- [ ] **Step 3: Commit Task 4**

Run:

```cmd
git add prototype/src/lib/api-client.ts
git commit -m "feat: add prototype api client"
```

---

## Task 5: Top-Level Navigation and Connection Indicator

**Files:**
- Modify: `prototype/src/app/page.tsx`

- [ ] **Step 1: Update page imports**

Modify the import block in `prototype/src/app/page.tsx` to include new icons, context, and components:

```typescript
import { useState } from 'react'
import { Card } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { MessageCircle, AlertTriangle, ClipboardCheck, BarChart3, Server, BookOpen, FlaskConical, Wifi, WifiOff } from 'lucide-react'
import SettlementChat from '@/components/settlement-chat'
import DischargeQC from '@/components/discharge-qc'
import Dashboard from '@/components/dashboard'
import RoleSwitcher from '@/components/role-switcher'
import McpManagement from '@/components/mcp-management'
import KnowledgeExplorer from '@/components/knowledge-explorer'
import ModelTest from '@/components/model-test'
import { useApiContext } from '@/lib/api-context'
```

- [ ] **Step 2: Add connection status in Home component**

Inside `Home`, after `currentRole`, add:

```typescript
  const { connectionStatus } = useApiContext()
```

In the header action area, before `RoleSwitcher`, add:

```tsx
            <Badge
              variant="outline"
              className={connectionStatus === 'connected' ? 'bg-green-50 text-green-700' : connectionStatus === 'fallback' ? 'bg-orange-50 text-orange-700' : 'bg-gray-50 text-gray-600'}
            >
              {connectionStatus === 'connected' ? <Wifi className="w-3 h-3 mr-1" /> : <WifiOff className="w-3 h-3 mr-1" />}
              {connectionStatus === 'connected' ? '已连接' : connectionStatus === 'fallback' ? '离线模式' : '未检测'}
            </Badge>
```

- [ ] **Step 3: Expand TabsList to seven tabs**

Replace the existing `TabsList` block with:

```tsx
          <TabsList className="grid w-full grid-cols-2 md:grid-cols-4 lg:grid-cols-7">
            <TabsTrigger value="chat" className="flex items-center gap-2">
              <MessageCircle className="w-4 h-4" />
              AI导办对话
            </TabsTrigger>
            <TabsTrigger value="settlement" className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4" />
              结算异常导办
            </TabsTrigger>
            <TabsTrigger value="qc" className="flex items-center gap-2">
              <ClipboardCheck className="w-4 h-4" />
              出院前联合质控
            </TabsTrigger>
            <TabsTrigger value="dashboard" className="flex items-center gap-2">
              <BarChart3 className="w-4 h-4" />
              运营驾驶舱
            </TabsTrigger>
            <TabsTrigger value="mcp" className="flex items-center gap-2">
              <Server className="w-4 h-4" />
              MCP管理
            </TabsTrigger>
            <TabsTrigger value="knowledge" className="flex items-center gap-2">
              <BookOpen className="w-4 h-4" />
              知识浏览
            </TabsTrigger>
            <TabsTrigger value="model" className="flex items-center gap-2">
              <FlaskConical className="w-4 h-4" />
              模型测试
            </TabsTrigger>
          </TabsList>
```

- [ ] **Step 4: Add new tab contents**

After the dashboard `TabsContent`, add:

```tsx
          <TabsContent value="mcp">
            <McpManagement />
          </TabsContent>

          <TabsContent value="knowledge">
            <KnowledgeExplorer />
          </TabsContent>

          <TabsContent value="model">
            <ModelTest />
          </TabsContent>
```

- [ ] **Step 5: Verify current missing components fail clearly**

Run:

```cmd
cd prototype && npm run lint
```

Expected: FAIL because `mcp-management`, `knowledge-explorer`, and `model-test` components do not exist yet. This confirms Task 5 imports are wired before page creation.

- [ ] **Step 6: Commit Task 5 after Tasks 6-8 are implemented**

Do not commit Task 5 alone while imports are unresolved. Commit it together with Tasks 6-8 or after those files exist.

---

## Task 6: MCP Management Page

**Files:**
- Create: `prototype/src/components/mcp-management.tsx`

- [ ] **Step 1: Create MCP management component**

Create `prototype/src/components/mcp-management.tsx` with:

```typescript
'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Server, Activity, Wrench, Database, MessageSquare, ShieldCheck } from 'lucide-react'
import { fetchMcpStorageHealth, initialMcpServers, registerMcpServer } from '@/lib/api-client'
import { useApiContext } from '@/lib/api-context'
import { mockMcpCapabilities } from '@/lib/mock-data'
import type { McpServer, McpStorageHealth, McpTransport } from '@/lib/types'

const statusColors: Record<string, string> = {
  enabled: 'bg-green-100 text-green-800',
  disabled: 'bg-gray-100 text-gray-800',
  degraded: 'bg-yellow-100 text-yellow-800',
  unhealthy: 'bg-red-100 text-red-800',
}

const capabilityIcons = [Wrench, Database, MessageSquare, ShieldCheck]

export default function McpManagement() {
  const { setConnected, setFallback } = useApiContext()
  const [servers, setServers] = useState<McpServer[]>(initialMcpServers())
  const [health, setHealth] = useState<McpStorageHealth | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({ server_id: '', name: '', endpoint: '', transport: 'sse' as McpTransport })

  const loadHealth = async () => {
    setError(null)
    try {
      const result = await fetchMcpStorageHealth()
      setHealth(result)
      result.fallback ? setFallback() : setConnected()
    } catch (err) {
      setError(err instanceof Error ? err.message : '健康检查失败')
    }
  }

  const submit = async () => {
    setError(null)
    if (!form.server_id.trim() || !form.name.trim() || !form.endpoint.trim()) {
      setError('服务ID、名称和端点不能为空')
      return
    }
    try {
      const registered = await registerMcpServer({
        ...form,
        status: 'enabled',
        protocol_version: '2025-03-26',
        auth_headers: {},
        metadata: {},
      })
      setServers((prev) => [registered, ...prev.filter((item) => item.server_id !== registered.server_id)])
      registered.fallback ? setFallback() : setConnected()
      setForm({ server_id: '', name: '', endpoint: '', transport: 'sse' })
    } catch (err) {
      setError(err instanceof Error ? err.message : '服务注册失败')
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
          const Icon = capabilityIcons[index]
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
                <Badge variant="outline" className="mt-2">演示数据</Badge>
              </CardContent>
            </Card>
          )
        })}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><Server className="w-5 h-5" />服务注册</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <Input placeholder="server_id" value={form.server_id} onChange={(e) => setForm({ ...form, server_id: e.target.value })} />
            <Input placeholder="服务名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <Input placeholder="endpoint" value={form.endpoint} onChange={(e) => setForm({ ...form, endpoint: e.target.value })} />
            <Select value={form.transport} onValueChange={(value) => setForm({ ...form, transport: value as McpTransport })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="sse">sse</SelectItem>
                <SelectItem value="streamable_http">streamable_http</SelectItem>
                <SelectItem value="stdio">stdio</SelectItem>
              </SelectContent>
            </Select>
            <Button onClick={submit} className="w-full">注册服务</Button>
            {error && <p className="text-sm text-red-600">{error}</p>}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span className="flex items-center gap-2"><Activity className="w-5 h-5" />存储健康检查</span>
              <Button variant="outline" size="sm" onClick={loadHealth}>查看存储状态</Button>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="bg-slate-900 text-blue-100 rounded-lg p-4 overflow-auto text-sm min-h-[160px]">
              {health ? JSON.stringify(health, null, 2) : '等待操作'}
            </pre>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4">
        {servers.map((server) => (
          <Card key={server.server_id} className="p-6 hover:shadow-lg transition-shadow">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-2">
                <div className="flex items-center gap-3">
                  <h3 className="text-lg font-semibold">{server.name}</h3>
                  <Badge className={statusColors[server.status]}>{server.status}</Badge>
                  {server.fallback && <Badge variant="outline">离线模式</Badge>}
                </div>
                <p className="text-sm text-gray-600"><span className="font-medium">服务ID:</span> {server.server_id}</p>
                <p className="text-sm text-gray-800 break-all">{server.endpoint}</p>
              </div>
              <Badge variant="outline">{server.transport}</Badge>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify lint still fails only for remaining missing pages**

Run:

```cmd
cd prototype && npm run lint
```

Expected: FAIL because `knowledge-explorer` and `model-test` are still missing; no error should mention `mcp-management`.

---

## Task 7: Knowledge Explorer Page

**Files:**
- Create: `prototype/src/components/knowledge-explorer.tsx`

- [ ] **Step 1: Create knowledge explorer component**

Create `prototype/src/components/knowledge-explorer.tsx` with:

```typescript
'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { BookOpen, Search, FileText, Brain, ScrollText } from 'lucide-react'
import { errorCodeKnowledge, mockDrgRules, mockKnowledgeAssets, mockPromptTemplates, mockRagResults } from '@/lib/mock-data'

export default function KnowledgeExplorer() {
  const [query, setQuery] = useState('待遇资格校验失败')
  const [searched, setSearched] = useState(false)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">知识扩展浏览</h2>
          <p className="text-sm text-gray-500 mt-1">浏览知识资产、规则解释、RAG 检索和提示模板</p>
        </div>
        <Badge className="bg-purple-100 text-purple-800">演示数据</Badge>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {mockKnowledgeAssets.map((asset) => (
          <Card key={asset.title}>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-500">{asset.title}</p>
                  <p className={`text-2xl font-bold mt-1 ${asset.color}`}>{asset.value}</p>
                </div>
                <div className="p-3 rounded-lg bg-gray-50"><BookOpen className={`w-6 h-6 ${asset.color}`} /></div>
              </div>
              <div className="mt-3">
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-gray-600">覆盖度</span>
                  <span className="font-medium">{asset.coverage}%</span>
                </div>
                <Progress value={asset.coverage} className="h-2" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Search className="w-5 h-5" />RAG 检索测试</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-2">
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="输入知识检索问题" />
            <Button onClick={() => setSearched(true)}>检索</Button>
          </div>
          <div className="space-y-3">
            {(searched ? mockRagResults : mockRagResults.slice(0, 1)).map((result) => (
              <Alert key={result.source}>
                <Search className="h-4 w-4" />
                <AlertTitle className="flex items-center justify-between">
                  <span>{result.source}</span>
                  <Badge variant="outline">相关度 {(result.score * 100).toFixed(0)}%</Badge>
                </AlertTitle>
                <AlertDescription className="mt-2">{result.summary}</AlertDescription>
              </Alert>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><FileText className="w-5 h-5" />错误码规则解释</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {Object.values(errorCodeKnowledge).map((item) => (
              <Alert key={item.code}>
                <ScrollText className="h-4 w-4" />
                <AlertTitle>{item.code} - {item.description}</AlertTitle>
                <AlertDescription>
                  <p className="mt-2 text-sm">可能原因：{item.possibleCauses.slice(0, 2).join('、')}</p>
                  <p className="mt-1 text-sm">处理步骤：{item.handlingSteps.slice(0, 2).join('、')}</p>
                </AlertDescription>
              </Alert>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><Brain className="w-5 h-5" />DRG/DIP 与提示模板</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {mockDrgRules.map((rule) => (
              <div key={rule.code} className="p-4 bg-gray-50 rounded-lg">
                <div className="flex items-center gap-2"><Badge variant="outline">{rule.code}</Badge><span className="font-medium">{rule.title}</span></div>
                <p className="text-sm text-gray-600 mt-2">{rule.summary}</p>
              </div>
            ))}
            <div className="border-t pt-4 space-y-2">
              {mockPromptTemplates.map((template) => (
                <div key={template.name} className="flex items-center justify-between text-sm">
                  <span>{template.name}</span>
                  <div className="flex gap-2"><Badge variant="outline">{template.scenario}</Badge><Badge>{template.role}</Badge></div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify lint still fails only for model page**

Run:

```cmd
cd prototype && npm run lint
```

Expected: FAIL because `model-test` is still missing; no error should mention `knowledge-explorer`.

---

## Task 8: Model Test Page

**Files:**
- Create: `prototype/src/components/model-test.tsx`

- [ ] **Step 1: Create model test component**

Create `prototype/src/components/model-test.tsx` with:

```typescript
'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Progress } from '@/components/ui/progress'
import { FlaskConical, Zap, Clock, History } from 'lucide-react'
import { testModel, testModelStream } from '@/lib/api-client'
import { useApiContext } from '@/lib/api-context'
import type { ModelTestResponse, SseEvent } from '@/lib/types'

interface HistoryItem {
  id: string
  scene: string
  message: string
  result: ModelTestResponse
  createdAt: string
}

const scenes = ['default', 'settlement_exception', 'pre_discharge_qc', 'drg_analysis']

export default function ModelTest() {
  const { setConnected, setFallback } = useApiContext()
  const [message, setMessage] = useState('请解释医保结算失败 ERR_001 的原因')
  const [scene, setScene] = useState('default')
  const [mode, setMode] = useState<'sync' | 'stream'>('sync')
  const [result, setResult] = useState<ModelTestResponse | null>(null)
  const [streamText, setStreamText] = useState('')
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const runSync = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await testModel({ message, scene })
      setResult(response)
      response.fallback ? setFallback() : setConnected()
      setHistory((prev) => [{ id: crypto.randomUUID(), scene, message, result: response, createdAt: new Date().toLocaleString() }, ...prev])
    } catch (err) {
      setError(err instanceof Error ? err.message : '模型测试失败')
    } finally {
      setLoading(false)
    }
  }

  const runStream = async () => {
    setLoading(true)
    setError(null)
    setStreamText('')
    try {
      await testModelStream({ message, scene }, (event: SseEvent) => {
        if (event.event === 'token' || event.event === 'final') {
          setStreamText((prev) => `${prev}${JSON.stringify(event.data, null, 2)}\n`)
        }
        if (event.event === 'error') {
          setError(JSON.stringify(event.data))
        }
      })
      setConnected()
    } catch (err) {
      setError(err instanceof Error ? err.message : '流式测试失败')
    } finally {
      setLoading(false)
    }
  }

  const run = () => {
    if (mode === 'sync') void runSync()
    if (mode === 'stream') void runStream()
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 min-h-[calc(100vh-220px)]">
      <Card className="lg:col-span-1">
        <CardHeader><CardTitle className="text-base flex items-center gap-2"><FlaskConical className="w-5 h-5" />模型测试参数</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div>
            <p className="text-xs text-gray-500 mb-2">场景</p>
            <Select value={scene} onValueChange={setScene}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{scenes.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-2">模式</p>
            <Select value={mode} onValueChange={(value) => setMode(value as 'sync' | 'stream')}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="sync">同步</SelectItem><SelectItem value="stream">流式</SelectItem></SelectContent>
            </Select>
          </div>
          <Textarea value={message} onChange={(e) => setMessage(e.target.value)} className="min-h-[160px]" />
          <Button onClick={run} disabled={loading || !message.trim()} className="w-full"><Zap className="w-4 h-4 mr-2" />发送测试</Button>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </CardContent>
      </Card>

      <Card className="lg:col-span-3">
        <CardHeader><CardTitle className="flex items-center gap-2"><Zap className="w-5 h-5" />测试结果</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          {mode === 'sync' && result && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <Metric label="模型" value={result.model_name} />
                <Metric label="延迟" value={`${result.latency_ms}ms`} />
                <Metric label="Prompt Tokens" value={String(result.prompt_tokens)} />
                <Metric label="Completion Tokens" value={String(result.completion_tokens)} />
              </div>
              <pre className="bg-gray-50 rounded-lg p-4 whitespace-pre-wrap text-sm">{result.content}</pre>
              <Progress value={Math.min(result.prompt_tokens + result.completion_tokens, 100)} className="h-2" />
              {result.fallback && <Badge variant="outline">离线模式 - 演示数据</Badge>}
            </div>
          )}
          {mode === 'stream' && <pre className="bg-slate-900 text-blue-100 rounded-lg p-4 min-h-[300px] whitespace-pre-wrap text-sm">{streamText || '等待流式输出'}</pre>}
        </CardContent>
      </Card>

      <Card className="lg:col-span-4">
        <CardHeader><CardTitle className="flex items-center justify-between"><span className="flex items-center gap-2"><History className="w-5 h-5" />测试历史</span><Button variant="outline" size="sm" onClick={() => setHistory([])}>清除历史</Button></CardTitle></CardHeader>
        <CardContent className="grid gap-4">
          {history.length === 0 && <p className="text-sm text-gray-500">暂无测试历史</p>}
          {history.map((item) => (
            <Card key={item.id} className="p-4 hover:shadow-lg transition-shadow">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2"><Badge variant="outline">{item.scene}</Badge><span className="text-sm text-gray-500">{item.createdAt}</span></div>
                  <p className="text-sm text-gray-700 mt-2">{item.message}</p>
                  <p className="text-sm text-gray-900 mt-1">{item.result.content.slice(0, 120)}</p>
                </div>
                <Badge className="bg-blue-100 text-blue-800"><Clock className="w-3 h-3 mr-1" />{item.result.latency_ms}ms</Badge>
              </div>
            </Card>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="p-4 bg-gray-50 rounded-lg text-center"><p className="text-xl font-bold">{value}</p><p className="text-xs text-gray-500 mt-1">{label}</p></div>
}
```

- [ ] **Step 2: Verify lint after new pages**

Run:

```cmd
cd prototype && npm run lint
```

Expected: command exits with code 0.

- [ ] **Step 3: Commit Tasks 5-8 together**

Run:

```cmd
git add prototype/src/app/page.tsx prototype/src/components/mcp-management.tsx prototype/src/components/knowledge-explorer.tsx prototype/src/components/model-test.tsx
git commit -m "feat: add prototype mcp knowledge and model pages"
```

---

## Task 9: Chat API Integration and Task Confirmation

**Files:**
- Modify: `prototype/src/components/settlement-chat.tsx`

- [ ] **Step 1: Add imports**

Add these imports to `prototype/src/components/settlement-chat.tsx`:

```typescript
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { confirmTask, sendChat, sendChatStream } from '@/lib/api-client'
import { useApiContext } from '@/lib/api-context'
import type { AgentResponse, AgentTask, SseEvent } from '@/lib/types'
```

- [ ] **Step 2: Expand message shape**

Replace the message state type with:

```typescript
  const [messages, setMessages] = useState<
    Array<{ role: 'user' | 'assistant'; content: string; response?: AgentResponse }>
  >([
```

- [ ] **Step 3: Add API context and helpers**

Inside the component after loading state, add:

```typescript
  const { userId, setConnected, setFallback } = useApiContext()
  const [taskMessage, setTaskMessage] = useState<string | null>(null)

  const formatResponse = (response: AgentResponse) => {
    if (response.status === 'needs_clarification') {
      return `需要补充信息：${response.missing_fields.join('、')}`
    }
    if (response.status === 'waiting_human_confirmation') {
      return `检测到高风险动作：${response.blocked_actions.join('、')}\n请由人工确认后在既有业务系统执行。`
    }
    const content = response.result.content
    if (typeof content === 'string') return content
    return JSON.stringify(response.result, null, 2)
  }

  const resolveTaskId = (response: AgentResponse) => {
    const firstTask = response.tasks[0] as AgentTask | undefined
    if (firstTask?.task_id) return firstTask.task_id
    if (typeof response.audit.task_id === 'string') return response.audit.task_id
    return 'task-001'
  }
```

- [ ] **Step 4: Replace handleSend implementation**

Replace `handleSend` with:

```typescript
  const handleSend = async (text?: string) => {
    const messageText = text || input
    if (!messageText.trim()) return

    setMessages((prev) => [...prev, { role: 'user', content: messageText }])
    setInput('')
    setIsLoading(true)
    setTaskMessage(null)

    try {
      const request = { user_id: userId, role: currentRole, message: messageText, patient_id: 'P001', encounter_id: 'E001' }
      let finalResponse: AgentResponse | null = null
      await sendChatStream(request, (event: SseEvent) => {
        if (event.event === 'step') {
          const stepData = event.data as { message?: string }
          if (stepData.message) {
            setMessages((prev) => [...prev, { role: 'assistant', content: stepData.message }])
          }
        }
        if (event.event === 'final') {
          finalResponse = event.data as AgentResponse
        }
      })
      const response = finalResponse || (await sendChat(request))
      response.fallback ? setFallback() : setConnected()
      setMessages((prev) => [...prev, { role: 'assistant', content: formatResponse(response), response }])
    } catch {
      const response = await sendChat({ user_id: userId, role: currentRole, message: messageText, patient_id: 'P001', encounter_id: 'E001' })
      response.fallback ? setFallback() : setConnected()
      setMessages((prev) => [...prev, { role: 'assistant', content: formatResponse(response), response }])
    } finally {
      setIsLoading(false)
    }
  }
```

- [ ] **Step 5: Add task confirmation handler**

Add this function after `handleSend`:

```typescript
  const handleConfirmTask = async (response: AgentResponse, action: 'confirm' | 'reject') => {
    const taskId = resolveTaskId(response)
    const result = await confirmTask({ task_id: taskId, action, user_id: userId, reason: action === 'confirm' ? '前端原型人工确认' : '前端原型人工拒绝' })
    result.fallback ? setFallback() : setConnected()
    setTaskMessage(`任务 ${result.task_id} 已${action === 'confirm' ? '确认' : '拒绝'}，当前状态：${result.status}`)
  }
```

- [ ] **Step 6: Render high-risk confirmation card**

Inside the assistant message bubble, after `<p className="text-sm whitespace-pre-wrap">{msg.content}</p>`, add:

```tsx
                    {msg.response?.status === 'waiting_human_confirmation' && (
                      <Alert className="mt-3 bg-orange-50 border-orange-200">
                        <AlertTriangle className="h-4 w-4" />
                        <AlertTitle>需要人工确认</AlertTitle>
                        <AlertDescription className="space-y-3">
                          <p>高风险动作不会由 AI 自动执行，请人工确认。</p>
                          <div className="flex gap-2">
                            <Button size="sm" onClick={() => handleConfirmTask(msg.response!, 'confirm')}>确认</Button>
                            <Button size="sm" variant="outline" onClick={() => handleConfirmTask(msg.response!, 'reject')}>拒绝</Button>
                          </div>
                        </AlertDescription>
                      </Alert>
                    )}
```

- [ ] **Step 7: Render task result message**

Before the input area, add:

```tsx
            {taskMessage && <p className="px-4 pb-2 text-sm text-green-700">{taskMessage}</p>}
```

- [ ] **Step 8: Verify lint**

Run:

```cmd
cd prototype && npm run lint
```

Expected: command exits with code 0.

- [ ] **Step 9: Commit Task 9**

Run:

```cmd
git add prototype/src/components/settlement-chat.tsx
git commit -m "feat: connect prototype chat to backend api"
```

---

## Task 10: Documentation and Verification

**Files:**
- Modify: `prototype/README.md`
- Modify: `prototype/原型交付文档.md`

- [ ] **Step 1: Update prototype README**

Add this section to `prototype/README.md`:

```markdown
## 前后端联调

### 启动后端

在项目根目录运行：

```bash
uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory --reload
```

### 启动前端原型

在 `prototype/` 目录运行：

```bash
npm run dev
```

访问 `http://localhost:3000`。

### 环境变量

复制 `.env.example` 为 `.env.local`，可修改后端地址：

```env
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

### 联调验证

- AI导办对话：输入“为什么这个患者结算失败”
- MCP管理：点击“查看存储状态”并注册一个测试服务
- 模型测试：选择 `default` 场景并发送测试消息
- 后端未启动时，页面会显示“离线模式”并使用 mock 数据
```

- [ ] **Step 2: Update delivery document**

Add this section near the feature overview in `prototype/原型交付文档.md`:

```markdown
## v1.1 前后端联调增强

本版本将原型从纯 mock 演示升级为真实 API 联调原型：

1. **真实对话联调**：AI 导办对话调用后端 `/chat` 和 `/chat/stream`
2. **高风险确认闭环**：支持任务确认/拒绝交互，调用 `/tasks/confirm`
3. **MCP 管理页面**：支持 MCP 服务注册和存储健康检查
4. **知识浏览页面**：展示知识资产、RAG 检索、规则解释和提示模板
5. **模型测试页面**：支持同步和流式模型调用测试
6. **离线演示模式**：后端不可用时自动使用 mock 数据
```

- [ ] **Step 3: Run frontend lint**

Run:

```cmd
cd prototype && npm run lint
```

Expected: command exits with code 0.

- [ ] **Step 4: Run frontend build**

Run:

```cmd
cd prototype && npm run build
```

Expected: build completes successfully and prints Next.js route output.

- [ ] **Step 5: Run backend MCP API tests**

Run:

```cmd
python -m pytest src/tests/integration/test_mcp_management_api.py -v
```

Expected: tests pass.

- [ ] **Step 6: Run OpenSpec status**

Run:

```cmd
npx openspec status --change "front-prototype"
```

Expected: all artifacts complete.

- [ ] **Step 7: Commit documentation and verification updates**

Run:

```cmd
git add prototype/README.md prototype/原型交付文档.md
git commit -m "docs: add prototype frontend integration guide"
```

---

## Task 11: OpenSpec Task Checklist Update

**Files:**
- Modify: `openspec/changes/front-prototype/tasks.md`

- [ ] **Step 1: Mark completed OpenSpec tasks**

After implementation and verification, update `openspec/changes/front-prototype/tasks.md` by changing every completed checkbox from `- [ ]` to `- [x]`.

- [ ] **Step 2: Verify OpenSpec status**

Run:

```cmd
npx openspec status --change "front-prototype"
```

Expected: tasks progress reflects completed implementation.

- [ ] **Step 3: Commit checklist update**

Run:

```cmd
git add openspec/changes/front-prototype/tasks.md
git commit -m "docs: mark front prototype tasks complete"
```

---

## Task 12: Final End-to-End Verification

**Files:**
- No source file changes expected.

- [ ] **Step 1: Start backend server**

Run in one terminal:

```cmd
uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory --reload
```

Expected: server starts and logs FastAPI startup.

- [ ] **Step 2: Start frontend dev server**

Run in a second terminal:

```cmd
cd prototype && npm run dev
```

Expected: Next.js starts on `http://localhost:3000`.

- [ ] **Step 3: Manual smoke checklist**

In the browser, verify:

```text
1. Header shows current role and API connection indicator.
2. AI导办对话 responds to “为什么这个患者结算失败”.
3. High-risk text such as “请帮我退费冲正” shows human confirmation UI.
4. MCP管理 page can fetch storage health.
5. MCP管理 page can register a demo service.
6. 知识浏览 page shows asset cards and RAG results.
7. 模型测试 page sync mode returns model result or structured model config error.
8. Stopping backend switches UI to 离线模式 after the next request.
```

- [ ] **Step 4: Run final regression commands**

Run:

```cmd
cd prototype && npm run lint
```

Expected: command exits with code 0.

Run:

```cmd
cd prototype && npm run build
```

Expected: build succeeds.

Run:

```cmd
python -m pytest src/tests -v
```

Expected: backend regression tests pass.

- [ ] **Step 5: Final commit if any verification fixes were needed**

If files changed during verification, run:

```cmd
git add prototype openspec/changes/front-prototype docs/superpowers/plans/2026-05-06-front-prototype.md
git commit -m "fix: stabilize front prototype verification"
```

If no files changed, do not create an empty commit.

---

## Self-Review

### Spec Coverage

- `frontend-api-integration`: covered by Tasks 1, 3, 4, 5, 9, 10, 12.
- `frontend-mcp-management`: covered by Tasks 2, 4, 5, 6, 10, 12.
- `frontend-knowledge-explorer`: covered by Tasks 2, 5, 7, 10, 12.
- `frontend-model-test`: covered by Tasks 2, 4, 5, 8, 10, 12.
- OpenSpec task tracking: covered by Task 11.

### Placeholder Scan

The plan contains no placeholder sections, no incomplete code blocks, and no deferred implementation steps.

### Type Consistency

- `ApiClientError`, `AgentResponse`, `McpServer`, `ModelTestResponse`, and `SseEvent` are defined in Task 1 and used consistently in Tasks 4, 6, 8, and 9.
- API function names in Tasks 4, 6, 8, and 9 match exactly: `sendChat`, `sendChatStream`, `testModel`, `testModelStream`, `fetchMcpStorageHealth`, `registerMcpServer`, `confirmTask`.

---

## Execution Notes

- Implement tasks in order.
- Prefer one commit per task unless a task intentionally depends on missing files from the next task.
- For Task 5, commit only after Tasks 6-8 create imported components.
- If `npm run lint` reports issues caused by existing code outside touched files, record the exact output and fix only issues introduced by this plan.
