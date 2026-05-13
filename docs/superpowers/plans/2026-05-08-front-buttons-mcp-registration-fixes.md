# Front Buttons and MCP Registration Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复前端按钮交互不可用/构建不可用问题，并让 MCP 管理页面直接支持 Roo/Cline 标准 `mcpServers` JSON 配置导入与 `drawio` stdio MCP 注册。

**Architecture:** 先用失败测试锁定两个根因：前端生产构建因质控状态索引类型错误失败，MCP PostgreSQL 结构化读取路径丢失 stdio `connection_config`；再补齐前端配置导入 UI 和 API 客户端。后端继续保留现有 `McpServer`/`import_mcp_servers_config()` 契约，前端新增标准配置导入入口，不绕过注册中心和存储层。

**Tech Stack:** Python 3.13、FastAPI、Pydantic、pytest、Next.js 16、React 19、TypeScript、Tailwind CSS、Base UI。

---

## 排查结论与边界

- `npm run build` 当前失败，错误在 `prototype/src/components/discharge-qc.tsx:220`：`risk.status` 被推断为 `string`，无法索引只包含 `待处理 | 处理中 | 已完成` 的对象。生产构建失败会直接影响页面可部署版本和按钮交互验证。
- 后端已有 `POST /api/v1/medical-insurance-ai-agent/mcp/servers/import-config`，并且内存存储测试能注册 `{ "mcpServers": { "drawio": { "command": "npx", "args": ["@next-ai-drawio/mcp-server@latest"] } } }`。
- 当前前端 MCP 管理页只调用 `POST /mcp/servers` 的手工表单，要求 `endpoint`，没有暴露 `mcpServers` JSON 导入入口，所以用户无法通过页面注册 `drawio` stdio MCP。
- 默认 MCP 存储是 PostgreSQL；`PostgresMcpStorage._server_from_row()` 在结构化列存在时只恢复 `server_id/name/endpoint/transport/status/protocol_version/auth_headers/metadata`，会丢弃保存在 `payload_json` 中的 `connection_config.command/args/env/cwd`，导致 stdio MCP 即使保存成功，读取后也无法用于后续发现/调用。

---

## 文件结构与职责

- Modify: `prototype/src/components/discharge-qc.tsx` — 修复状态/风险等级类型，保证构建通过和交互页面可加载。
- Modify: `src/tests/data_platform/test_mcp_postgres_storage.py` — 增加 PostgreSQL 读取 stdio MCP 时保留 `connection_config` 的失败测试。
- Modify: `src/data_platform/storage/mcp/postgres.py` — 从 `payload_json` 恢复完整 `McpServer`，再用结构化列覆盖查询字段，避免丢失 stdio 配置。
- Modify: `src/tests/integration/test_mcp_management_api.py` — 增加 API 导入后可从列表读取 `command/args` 的回归测试。
- Modify: `prototype/src/lib/types.ts` — 扩展前端 `McpServer` 和 `mcpServers` 配置导入类型。
- Modify: `prototype/src/lib/api-client.ts` — 新增 `importMcpServersConfig()`，调用后端 `/mcp/servers/import-config`。
- Modify: `prototype/src/components/mcp-management.tsx` — 新增 Roo/Cline JSON 导入文本框与按钮，展示 stdio `command/args`。
- Verify: `python -m pytest ...` 与 `npm run build`。

---

### Task 1: 修复前端构建失败导致的按钮交互风险

**Files:**
- Modify: `prototype/src/components/discharge-qc.tsx:20-112`
- Test: `prototype/src/components/discharge-qc.tsx`

- [ ] **Step 1: 复现当前前端构建失败**

Run:

```bash
npm run build
```

Working directory:

```bash
prototype
```

Expected: FAIL，错误包含：

```text
./src/components/discharge-qc.tsx:220:41
Type error: Element implicitly has an 'any' type because expression of type 'string' can't be used to index type '{ 待处理: string; 处理中: string; 已完成: string; }'.
```

- [ ] **Step 2: 为质控风险数据补充显式类型**

在 `prototype/src/components/discharge-qc.tsx` 的 `const qcCases = [` 之前加入：

```tsx
type QcRiskLevel = '高' | '中' | '低'
type QcRiskStatus = '待处理' | '处理中' | '已完成'

interface QcRisk {
  id: number
  type: string
  level: QcRiskLevel
  description: string
  source: string
  status: QcRiskStatus
  assignee: string
}

interface QcCase {
  id: string
  patientName: string
  patientId: string
  department: string
  doctor: string
  expectedDischarge: string
  completionRate: number
  risks: QcRisk[]
}

const riskLevels: QcRiskLevel[] = ['高', '中', '低']
```

将原来的：

```tsx
const qcCases = [
```

改为：

```tsx
const qcCases: QcCase[] = [
```

将组件内颜色映射改为：

```tsx
const levelColors: Record<QcRiskLevel, string> = {
  高: 'bg-red-100 text-red-800 border-red-300',
  中: 'bg-yellow-100 text-yellow-800 border-yellow-300',
  低: 'bg-green-100 text-green-800 border-green-300',
}

const statusColors: Record<QcRiskStatus, string> = {
  待处理: 'bg-gray-100 text-gray-800',
  处理中: 'bg-blue-100 text-blue-800',
  已完成: 'bg-green-100 text-green-800',
}
```

将风险统计循环从：

```tsx
{['高', '中', '低'].map((level) => {
  const count = qc.risks.filter((r) => r.level === level).length
  if (count === 0) return null
  return (
    <Badge key={level} className={levelColors[level as keyof typeof levelColors]}>
      {level}风险 {count}项
    </Badge>
  )
})}
```

改为：

```tsx
{riskLevels.map((level) => {
  const count = qc.risks.filter((risk) => risk.level === level).length
  if (count === 0) return null
  return (
    <Badge key={level} className={levelColors[level]}>
      {level}风险 {count}项
    </Badge>
  )
})}
```

- [ ] **Step 3: 验证前端构建进入下一阶段**

Run:

```bash
npm run build
```

Working directory:

```bash
prototype
```

Expected: 不再出现 `discharge-qc.tsx:220` 类型错误；如果出现新的类型错误，按同样方式先记录再修复，不把多个根因混在一个提交里。

- [ ] **Step 4: Commit**

```bash
git add prototype/src/components/discharge-qc.tsx
git commit -m "fix: restore front prototype build readiness"
```

---

### Task 2: 用失败测试锁定 PostgreSQL 读取 stdio MCP 时丢失 command/args 的根因

**Files:**
- Modify: `src/tests/data_platform/test_mcp_postgres_storage.py:1-221`
- Test: `src/tests/data_platform/test_mcp_postgres_storage.py`

- [ ] **Step 1: 增加导入函数引用**

在 `src/tests/data_platform/test_mcp_postgres_storage.py` 顶部导入区加入：

```python
from src.knowledge_extension.mcp_registry.config_import import import_mcp_servers_config
```

- [ ] **Step 2: 写 PostgreSQL stdio 配置保留失败测试**

在 `test_postgres_mcp_storage_loads_server_from_structured_columns()` 后追加：

```python
def test_postgres_mcp_storage_loads_stdio_server_with_connection_config_from_payload_json():
    executor = FakeExecutor()
    dialect = PostgresDialect()
    storage = PostgresMcpStorage(executor=executor, dialect=dialect)
    server = import_mcp_servers_config(
        {
            "mcpServers": {
                "drawio": {
                    "command": "npx",
                    "args": ["@next-ai-drawio/mcp-server@latest"],
                    "env": {"DRAWIO_MODE": "stdio"},
                    "cwd": "d:/project/hospital_medical_insurance_agent",
                }
            }
        }
    ).servers[0]

    storage.save_server(server)
    statement = executor.statements[0]
    executor.rows["drawio"] = {
        "server_id": statement.params[0],
        "name": statement.params[1],
        "endpoint": statement.params[2],
        "transport": statement.params[3],
        "status": statement.params[4],
        "protocol_version": statement.params[5],
        "auth_headers_json": statement.params[6],
        "metadata_json": statement.params[7],
        "payload_json": statement.params[8],
    }

    loaded = storage.get_server("drawio")

    assert loaded is not None
    assert loaded.transport is McpTransportType.STDIO
    assert loaded.connection_config["command"] == "npx"
    assert loaded.connection_config["args"] == ["@next-ai-drawio/mcp-server@latest"]
    assert loaded.connection_config["env"] == {"DRAWIO_MODE": "stdio"}
    assert loaded.connection_config["cwd"] == "d:/project/hospital_medical_insurance_agent"
```

- [ ] **Step 3: 运行失败测试确认根因**

Run:

```bash
python -m pytest src/tests/data_platform/test_mcp_postgres_storage.py::test_postgres_mcp_storage_loads_stdio_server_with_connection_config_from_payload_json -v
```

Expected: FAIL，失败点为 `loaded.connection_config["command"]` 缺失或 `connection_config` 为空。

---

### Task 3: 修复 PostgreSQL MCP 存储完整恢复 McpServer payload

**Files:**
- Modify: `src/data_platform/storage/mcp/postgres.py:26-38`
- Test: `src/tests/data_platform/test_mcp_postgres_storage.py`

- [ ] **Step 1: 修改 `_server_from_row()` 保留 payload_json 中的扩展字段**

将 `src/data_platform/storage/mcp/postgres.py` 中现有 `_server_from_row()` 替换为：

```python
def _server_from_row(self, row: dict) -> McpServer:
    payload: dict = {}
    payload_json = row.get("payload_json")
    if payload_json:
        payload = self._dialect.json_load(payload_json)
    if row.get("name") is not None and row.get("endpoint") is not None and row.get("transport") is not None and row.get("status") is not None:
        payload.update(
            {
                "server_id": row["server_id"],
                "name": row["name"],
                "endpoint": row["endpoint"],
                "transport": row["transport"],
                "status": row["status"],
                "protocol_version": row.get("protocol_version"),
            }
        )
        if row.get("auth_headers_json") is not None:
            payload["auth_headers"] = self._dialect.json_load(row.get("auth_headers_json"))
        if row.get("metadata_json") is not None:
            payload["metadata"] = self._dialect.json_load(row.get("metadata_json"))
    return McpServer(**payload)
```

- [ ] **Step 2: 运行新增失败测试确认通过**

Run:

```bash
python -m pytest src/tests/data_platform/test_mcp_postgres_storage.py::test_postgres_mcp_storage_loads_stdio_server_with_connection_config_from_payload_json -v
```

Expected: PASS。

- [ ] **Step 3: 运行 MCP PostgreSQL 存储全量测试**

Run:

```bash
python -m pytest src/tests/data_platform/test_mcp_postgres_storage.py -v
```

Expected: 全部 PASS。

- [ ] **Step 4: Commit**

```bash
git add src/tests/data_platform/test_mcp_postgres_storage.py src/data_platform/storage/mcp/postgres.py
git commit -m "fix: preserve stdio mcp connection config in postgres storage"
```

---

### Task 4: 增强 MCP 配置导入 API 回归覆盖

**Files:**
- Modify: `src/tests/integration/test_mcp_management_api.py:78-92`
- Test: `src/tests/integration/test_mcp_management_api.py`

- [ ] **Step 1: 扩展现有导入端点测试**

将 `test_mcp_import_config_endpoint_registers_stdio_server()` 改为：

```python
def test_mcp_import_config_endpoint_registers_stdio_server(monkeypatch):
    use_in_memory_mcp_registry(monkeypatch)
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/medical-insurance-ai-agent/mcp/servers/import-config",
        json={
            "mcpServers": {
                "drawio": {
                    "command": "npx",
                    "args": ["@next-ai-drawio/mcp-server@latest"],
                    "env": {"DRAWIO_MODE": "stdio"},
                }
            }
        },
    )
    listed = client.get("/api/v1/medical-insurance-ai-agent/mcp/servers")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["server_id"] == "drawio"
    assert payload[0]["transport"] == "stdio"
    assert payload[0]["connection_config"]["command"] == "npx"
    assert payload[0]["connection_config"]["args"] == ["@next-ai-drawio/mcp-server@latest"]
    assert payload[0]["connection_config"]["env"] == {"DRAWIO_MODE": "stdio"}
    assert listed.status_code == 200
    assert any(server["server_id"] == "drawio" and server["connection_config"]["command"] == "npx" for server in listed.json())
```

- [ ] **Step 2: 运行 MCP 管理 API 测试**

Run:

```bash
python -m pytest src/tests/integration/test_mcp_management_api.py -v
```

Expected: 全部 PASS。

- [ ] **Step 3: Commit**

```bash
git add src/tests/integration/test_mcp_management_api.py
git commit -m "test: cover mcp config import list contract"
```

---

### Task 5: 扩展前端 MCP 类型与配置导入 API 客户端

**Files:**
- Modify: `prototype/src/lib/types.ts:93-108`
- Modify: `prototype/src/lib/api-client.ts:7-23,449-462`
- Test: `prototype/src/lib/api-client.ts`

- [ ] **Step 1: 扩展前端类型**

在 `prototype/src/lib/types.ts` 的 MCP 类型区域替换/追加为：

```ts
export type McpTransport = 'stdio' | 'sse' | 'streamable_http'
export type McpServerStatus = 'enabled' | 'disabled' | 'degraded' | 'unhealthy'
export type McpCapabilityType = 'tool' | 'resource' | 'prompt' | 'service'
export type McpRiskLevel = 'low' | 'medium' | 'high'
export type McpAuthType = 'none' | 'bearer' | 'api_key' | 'custom_headers'
export type McpDiscoveryStatus = 'not_discovered' | 'success' | 'failed'

export interface McpServerConfigEntry {
  command?: string
  args?: string[]
  env?: Record<string, string>
  cwd?: string
  name?: string
  description?: string
  url?: string
  endpoint?: string
  transport?: McpTransport
  headers?: Record<string, string>
  metadata?: Record<string, unknown>
  protocol_version?: string
}

export interface McpServersConfig {
  mcpServers: Record<string, McpServerConfigEntry>
}

export interface McpServer {
  server_id: string
  name: string
  endpoint: string
  transport: McpTransport
  status: McpServerStatus
  description?: string | null
  protocol_version?: string | null
  auth_type?: McpAuthType
  auth_headers: Record<string, string>
  connection_config?: Record<string, unknown>
  capabilities_summary?: Record<string, unknown>
  discovery_status?: McpDiscoveryStatus
  last_discovered_at?: string | null
  last_error?: string | null
  metadata: Record<string, unknown>
  fallback?: boolean
}
```

- [ ] **Step 2: 在 API 客户端导入新类型**

在 `prototype/src/lib/api-client.ts` 的类型导入列表加入：

```ts
McpServersConfig,
McpServerConfigEntry,
```

- [ ] **Step 3: 新增前端标准配置导入函数**

在 `registerMcpServer()` 后追加：

```ts
function fallbackServerFromConfigEntry(serverId: string, entry: McpServerConfigEntry): McpServer {
  const command = typeof entry.command === 'string' ? entry.command : ''
  const args = Array.isArray(entry.args) ? entry.args : []
  const endpoint = command ? `stdio://${serverId}` : (entry.endpoint ?? entry.url ?? `memory://${serverId}`)

  return {
    server_id: serverId,
    name: entry.name ?? serverId,
    description: entry.description,
    endpoint,
    transport: command ? 'stdio' : (entry.transport ?? 'streamable_http'),
    status: 'enabled',
    protocol_version: entry.protocol_version ?? '2025-03-26',
    auth_type: 'none',
    auth_headers: {},
    connection_config: command ? { command, args, env: entry.env ?? {}, cwd: entry.cwd } : {},
    discovery_status: 'not_discovered',
    metadata: entry.metadata ?? {},
    fallback: true,
  }
}

export async function importMcpServersConfig(config: McpServersConfig): Promise<McpServer[]> {
  try {
    return await requestJson<McpServer[]>('/mcp/servers/import-config', {
      method: 'POST',
      body: JSON.stringify(config),
    })
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error
    }

    return Object.entries(config.mcpServers).map(([serverId, entry]) => fallbackServerFromConfigEntry(serverId, entry))
  }
}
```

- [ ] **Step 4: 运行前端类型检查**

Run:

```bash
npm run build
```

Working directory:

```bash
prototype
```

Expected: 此任务相关类型无错误。

- [ ] **Step 5: Commit**

```bash
git add prototype/src/lib/types.ts prototype/src/lib/api-client.ts
git commit -m "feat: add mcp config import client"
```

---

### Task 6: 在 MCP 管理页面增加 Roo/Cline JSON 导入与 stdio 配置展示

**Files:**
- Modify: `prototype/src/components/mcp-management.tsx:1-350`
- Test: `prototype/src/components/mcp-management.tsx`

- [ ] **Step 1: 扩展导入**

将 `prototype/src/components/mcp-management.tsx` 顶部导入改为包含 `Textarea`、`importMcpServersConfig` 和 `McpServersConfig`：

```tsx
import { Textarea } from '@/components/ui/textarea'
import { fetchMcpCapabilities, fetchMcpServers, fetchMcpStorageHealth, importMcpServersConfig, initialMcpCapabilities, initialMcpServers, registerMcpServer } from '@/lib/api-client'
import type { McpCapability, McpRiskLevel, McpServer, McpServersConfig, McpServerStatus, McpStorageHealth, McpTransport } from '@/lib/types'
```

- [ ] **Step 2: 新增默认 drawio 配置和解析辅助函数**

在 `emptyForm` 后加入：

```tsx
const defaultConfigText = JSON.stringify(
  {
    mcpServers: {
      drawio: {
        command: 'npx',
        args: ['@next-ai-drawio/mcp-server@latest'],
      },
    },
  },
  null,
  2
)

function parseMcpServersConfig(value: string): McpServersConfig {
  const parsed = JSON.parse(value) as unknown
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error('MCP 配置必须是 JSON 对象')
  }
  const config = parsed as Record<string, unknown>
  if (typeof config.mcpServers !== 'object' || config.mcpServers === null || Array.isArray(config.mcpServers)) {
    throw new Error('mcpServers 必须是对象')
  }
  return parsed as McpServersConfig
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

function stringArrayValue(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function commandLine(server: McpServer): string | null {
  const command = stringValue(server.connection_config?.command)
  if (!command) {
    return null
  }
  const args = stringArrayValue(server.connection_config?.args)
  return [command, ...args].join(' ')
}
```

- [ ] **Step 3: 新增配置导入状态与提交函数**

在 `McpManagement()` 的 state 区域加入：

```tsx
const [configText, setConfigText] = useState(defaultConfigText)
const [isImporting, setIsImporting] = useState(false)
```

在 `submit()` 函数后加入：

```tsx
const submitConfigImport = async () => {
  setError(null)

  let config: McpServersConfig
  try {
    config = parseMcpServersConfig(configText)
  } catch (err) {
    setError(err instanceof Error ? err.message : 'MCP 配置 JSON 格式错误')
    return
  }

  setIsImporting(true)

  try {
    const registered = await importMcpServersConfig(config)
    await loadServers()
    setServers((current) => [
      ...registered,
      ...current.filter((server) => !registered.some((item) => item.server_id === server.server_id)),
    ])

    if (registered.some((server) => server.fallback)) {
      setFallback()
    } else {
      setConnected()
    }
  } catch (err) {
    setError(err instanceof Error ? err.message : 'MCP 配置导入失败')
  } finally {
    setIsImporting(false)
  }
}
```

- [ ] **Step 4: 增加 Roo/Cline 配置导入卡片**

将注册区域外层从：

```tsx
<div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
```

改为：

```tsx
<div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
```

在手工 `服务注册` Card 后插入：

```tsx
<Card>
  <CardHeader>
    <CardTitle className="flex items-center gap-2">
      <Server className="w-5 h-5" />
      Roo/Cline 配置导入
    </CardTitle>
  </CardHeader>
  <CardContent className="space-y-3">
    <Textarea
      value={configText}
      onChange={(event) => setConfigText(event.target.value)}
      className="min-h-[180px] font-mono text-xs"
      placeholder='{"mcpServers":{"drawio":{"command":"npx","args":["@next-ai-drawio/mcp-server@latest"]}}}'
    />
    <Button onClick={submitConfigImport} disabled={isImporting} className="w-full">
      {isImporting ? '导入中...' : '导入标准配置'}
    </Button>
    <p className="text-xs text-gray-500">
      支持 command/args/env/cwd 形式的 stdio MCP，例如 drawio。
    </p>
  </CardContent>
</Card>
```

将健康检查 Card className 从：

```tsx
<Card className="lg:col-span-2">
```

改为：

```tsx
<Card className="lg:col-span-2">
```

该行保持不变即可；四列布局下它仍占两列。

- [ ] **Step 5: 在服务卡片展示 stdio command/args**

在服务卡片的 endpoint 显示后加入：

```tsx
{commandLine(server) && (
  <p className="text-sm text-gray-800 break-all">
    <span className="font-medium">command:</span> {commandLine(server)}
  </p>
)}
```

- [ ] **Step 6: 运行前端构建**

Run:

```bash
npm run build
```

Working directory:

```bash
prototype
```

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add prototype/src/components/mcp-management.tsx
git commit -m "feat: support mcp servers json import in frontend"
```

---

### Task 7: 联合验证与回归检查

**Files:**
- Verify: `src/tests/data_platform/test_mcp_postgres_storage.py`
- Verify: `src/tests/integration/test_mcp_management_api.py`
- Verify: `src/tests/knowledge_extension/test_mcp_config_import.py`
- Verify: `prototype/src/components/discharge-qc.tsx`
- Verify: `prototype/src/components/mcp-management.tsx`

- [ ] **Step 1: 运行后端 MCP 相关测试**

Run:

```bash
python -m pytest src/tests/knowledge_extension/test_mcp_config_import.py src/tests/data_platform/test_mcp_postgres_storage.py src/tests/integration/test_mcp_management_api.py -v
```

Expected: 全部 PASS。

- [ ] **Step 2: 运行前端生产构建**

Run:

```bash
npm run build
```

Working directory:

```bash
prototype
```

Expected: PASS。

- [ ] **Step 3: 手工联调 MCP 导入接口**

确保后端已启动：

```bash
uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory --reload
```

执行：

```bash
python -c "from fastapi.testclient import TestClient; from src.runtime.api.app import create_app; client=TestClient(create_app()); body={'mcpServers': {'drawio': {'command': 'npx', 'args': ['@next-ai-drawio/mcp-server@latest']}}}; r=client.post('/api/v1/medical-insurance-ai-agent/mcp/servers/import-config', json=body); print(r.status_code); print(r.json()[0]['server_id']); print(r.json()[0]['connection_config'])"
```

Expected:

```text
200
drawio
{'command': 'npx', 'args': ['@next-ai-drawio/mcp-server@latest'], 'env': {}, 'cwd': None}
```

- [ ] **Step 4: 浏览器手工验收**

启动前后端：

```bash
start-dev.bat
```

在浏览器打开：

```text
http://127.0.0.1:3000
```

验收步骤：

1. 点击顶部 `MCP管理` Tab，页面应切换。
2. 点击 `查看存储状态`，面板应显示 JSON 健康状态。
3. 在 `Roo/Cline 配置导入` 中保留默认 drawio JSON，点击 `导入标准配置`。
4. 服务列表应出现 `drawio`，传输类型为 `stdio`，并显示 `command: npx @next-ai-drawio/mcp-server@latest`。
5. 点击 `出院前联合质控` Tab，再点击任意 `查看详细清单`，详情卡片应展开。

- [ ] **Step 5: 最终提交**

```bash
git status --short
git log --oneline -5
```

Expected: 只包含本计划相关文件变更；若前面已按任务提交，此步骤不再新增提交。

---

## 自审清单

- OpenSpec 覆盖：现有 `front-prototype` 只要求手工 MCP 注册；本计划在不破坏手工注册的基础上新增 `mcpServers` JSON 导入，覆盖用户新增需求。
- 高风险安全边界：本次只注册 MCP Server，不执行工具调用，不绕过 `McpRegistryService` 和后续能力选择的风险控制。
- 来源可追溯：无业务 AI 输出变更，不影响 `citations` 约束。
- 类型一致性：前端 `McpServersConfig` 与后端 `import_mcp_servers_config()` 的 `mcpServers` 顶层字段一致；`McpServer.connection_config` 与后端 `McpServer` 模型字段一致。
- 回归风险：PostgreSQL 结构化列仍覆盖列表常用字段，`payload_json` 仅用于保留扩展字段；现有结构化列测试应继续通过。
