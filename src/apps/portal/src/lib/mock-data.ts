import type { McpServer, McpStorageHealth, ModelTestResponse } from './types'

export const mockMcpServers: McpServer[] = [
  {
    server_id: 'mcp-knowledge-search',
    name: '知识检索 MCP 服务',
    endpoint: 'http://127.0.0.1:9101/sse',
    transport: 'sse',
    status: 'enabled',
    protocol_version: '2025-03-26',
    auth_headers: {},
    metadata: { owner: '医保办', scene: 'knowledge_search' },
  },
  {
    server_id: 'mcp-policy-rules',
    name: '政策规则 MCP 服务',
    endpoint: 'http://127.0.0.1:9102/mcp',
    transport: 'streamable_http',
    status: 'degraded',
    protocol_version: '2025-03-26',
    auth_headers: {},
    metadata: { owner: '信息科', scene: 'policy_rule' },
  },
]

export const mockMcpStorageHealth: McpStorageHealth = {
  status: 'ok',
  backend: 'memory',
  details: { server_count: 2, capability_count: 8 },
}

export const mockModelTestResult: ModelTestResponse = {
  content: '后端模型服务当前不可用。',
  model_name: 'unavailable',
  latency_ms: 0,
  prompt_tokens: 0,
  completion_tokens: 0,
}
