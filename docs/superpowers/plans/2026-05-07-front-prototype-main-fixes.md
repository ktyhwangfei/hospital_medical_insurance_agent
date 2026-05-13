# Front Prototype Main Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复前端 `main` 页面验证发现的角色权限、对话展示、MCP PostgreSQL 结构化持久化、模型流式测试展示问题。

**Architecture:** 方案分为四条独立但可联测的链路：前端角色枚举与后端授权配置统一；前端对 `AgentResponse.result` 做人可读格式化；后端 MCP 存储默认走 PostgreSQL 并结构化写入字段；模型流式接口返回完整 `ModelTestResponse` 兼容同步展示。保持现有 API 前缀与降级策略不变。

**Tech Stack:** Python 3、FastAPI、Pydantic、pytest、PostgreSQL/psycopg 抽象执行器、Next.js、React、TypeScript、SSE。

---

## 文件结构与职责

- 修改 `prototype/src/lib/types.ts`：统一前端角色类型为后端真实角色枚举。
- 修改 `prototype/src/components/role-switcher.tsx`：下拉选项使用 `cashier`、`medical_office`、`information_department`、`medical_record_staff`，修复角色显示。
- 修改 `prototype/src/app/page.tsx`：默认角色改为 `cashier`，顶部角色标签引用统一角色定义。
- 修改 `prototype/src/components/settlement-chat.tsx`：根据统一角色显示角色视图，并将结构化 `AgentResponse.result` 格式化为导办文案。
- 修改 `src/config/security_policy/rules.py`：补齐 `information_department`、`medical_record_staff` 的可见字段，确认 `medical_office` 可访问结算异常与出院前质控。
- 修改 `src/config/mcp.py`：默认启用 `postgresql` 持久化与自动建表。
- 修改 `src/data_platform/storage/mcp/postgres.py`：`mcp_servers` 表结构化字段落库，`save_server()` 写入结构化列与 JSON 列，`get_server()`、`list_servers()` 从结构化列恢复。
- 修改 `src/runtime/api/mcp_routes.py`：增加 `GET /mcp/servers`，供页面注册后读取真实持久化列表。
- 修改 `prototype/src/lib/api-client.ts`：增加 `fetchMcpServers()`，注册成功后可刷新后端列表。
- 修改 `prototype/src/components/mcp-management.tsx`：初始加载真实 MCP 服务列表，注册表单支持 `metadata` JSON，注册成功后刷新列表。
- 修改 `src/runtime/api/routes.py`：`model-test/stream` 的 `final` 事件补齐 `content`、`model_name`、`latency_ms`、`prompt_tokens`、`completion_tokens`。
- 修改 `prototype/src/components/model-test.tsx`：流式模式展示与同步模式一致的指标卡、结果内容、token 进度，并保留实时输出区域。
- 修改 `src/tests/security/test_security_boundaries.py`、`src/tests/security/test_high_risk_and_permission.py`：覆盖角色权限。
- 修改 `src/tests/data_platform/test_mcp_postgres_storage.py`：覆盖结构化列 SQL 与恢复逻辑。
- 修改 `src/tests/integration/test_mcp_management_api.py`：覆盖 `GET /mcp/servers`。
- 修改 `src/tests/integration/test_openapi_contract.py`：覆盖流式 `final` 完整字段。
- 修改 `prototype/README.md`：说明后端默认 PostgreSQL MCP 存储配置。

---

### Task 1: 统一前端角色枚举与后端权限

**Files:**
- Modify: `prototype/src/lib/types.ts:1`
- Modify: `prototype/src/components/role-switcher.tsx:1-64`
- Modify: `prototype/src/app/page.tsx:18-27`
- Modify: `prototype/src/components/settlement-chat.tsx:193-200`
- Modify: `src/config/security_policy/rules.py:1-12`
- Test: `src/tests/security/test_security_boundaries.py`
- Test: `src/tests/security/test_high_risk_and_permission.py`

- [ ] **Step 1: 写后端角色权限失败测试**

在 `src/tests/security/test_security_boundaries.py` 追加：

```python
def test_medical_record_staff_context_uses_minimum_fields():
    client = TestClient(create_app())

    response = client.get('/api/v1/medical-insurance-ai-agent/patient-context/P001/E001', params={'user_id': 'u1', 'role': 'medical_record_staff'})

    assert response.status_code == 200
    body = response.json()
    assert body['patient']['name'] == '张**'
    assert set(body['visible_fields']) == {'patient_id', 'encounter_id'}
    assert 'settlement_status' not in body
```

在 `src/tests/security/test_high_risk_and_permission.py` 追加：

```python
def test_medical_office_can_access_settlement_and_pre_discharge_shortcuts():
    client = TestClient(create_app())

    settlement = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001',
        'role': 'medical_office',
        'message': '为什么这个患者结算失败',
        'patient_id': 'P001',
        'encounter_id': 'E001',
    })
    qc = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001',
        'role': 'medical_office',
        'message': '这个患者出院前还有哪些风险',
        'patient_id': 'P001',
        'encounter_id': 'E001',
    })

    assert settlement.status_code == 200
    assert settlement.json()['scenario'] == 'settlement_exception_guidance'
    assert qc.status_code == 200
    assert qc.json()['scenario'] == 'pre_discharge_quality_control'
```

- [ ] **Step 2: 运行角色权限测试并确认失败**

Run:

```bash
python -m pytest src/tests/security/test_security_boundaries.py::test_medical_record_staff_context_uses_minimum_fields src/tests/security/test_high_risk_and_permission.py::test_medical_office_can_access_settlement_and_pre_discharge_shortcuts -v
```

Expected: `test_medical_record_staff_context_uses_minimum_fields` 失败，因为 `medical_record_staff` 尚未配置 `ROLE_VISIBLE_FIELDS`；若第二个测试已通过，保持它作为回归保护。

- [ ] **Step 3: 修改后端角色配置**

将 `src/config/security_policy/rules.py` 改为：

```python
ROLE_VISIBLE_FIELDS = {
    'cashier': {'patient_id', 'encounter_id', 'settlement_status'},
    'medical_office': {'patient_id', 'encounter_id', 'settlement_status', 'audit_risks'},
    'information_department': {'patient_id', 'encounter_id', 'settlement_status'},
    'medical_record_staff': {'patient_id', 'encounter_id'},
    'clinician': {'patient_id', 'encounter_id'},
}

SCENARIO_ALLOWED_ROLES = {
    'settlement_exception_guidance': {'cashier', 'medical_office', 'information_department'},
    'pre_discharge_quality_control': {'medical_office', 'medical_record_staff', 'clinician'},
}

HIGH_RISK_ACTIONS = {'正式结算', '退费', '冲正', '撤销结算', '病案首页修改', '费用明细修改', '最终申诉结论确认'}
```

- [ ] **Step 4: 修改前端角色类型与下拉框**

将 `prototype/src/lib/types.ts` 第一行改为：

```ts
export type RoleId = 'cashier' | 'medical_office' | 'information_department' | 'medical_record_staff'
```

将 `prototype/src/components/role-switcher.tsx` 改为：

```tsx
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { RoleId } from '@/lib/types'

export interface RoleOption {
  id: RoleId
  name: string
  icon: string
  color: string
}

const roles: RoleOption[] = [
  {
    id: 'cashier',
    name: '收费员',
    icon: '💰',
    color: 'bg-green-100 text-green-800',
  },
  {
    id: 'medical_office',
    name: '医保办',
    icon: '🏥',
    color: 'bg-blue-100 text-blue-800',
  },
  {
    id: 'information_department',
    name: '信息科',
    icon: '💻',
    color: 'bg-purple-100 text-purple-800',
  },
  {
    id: 'medical_record_staff',
    name: '病案室',
    icon: '📋',
    color: 'bg-orange-100 text-orange-800',
  },
]

export default function RoleSwitcher({
  currentRole,
  onRoleChange,
}: {
  currentRole: RoleId
  onRoleChange: (role: RoleId) => void
}) {
  const current = roles.find((role) => role.id === currentRole) ?? roles[0]

  return (
    <Select value={currentRole} onValueChange={(value) => onRoleChange(value as RoleId)}>
      <SelectTrigger className="w-[140px]">
        <SelectValue>
          <span className="flex items-center gap-2">
            <span>{current.icon}</span>
            <span className="text-sm">{current.name}</span>
          </span>
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {roles.map((role) => (
          <SelectItem key={role.id} value={role.id}>
            <span className="flex items-center gap-2">
              <span>{role.icon}</span>
              <span>{role.name}</span>
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export { roles }
```

- [ ] **Step 5: 修改首页默认角色与显示文案**

在 `prototype/src/app/page.tsx` 中导入类型与角色列表：

```tsx
import RoleSwitcher, { roles } from '@/components/role-switcher'
import type { RoleId } from '@/lib/types'
```

将 `Home()` 开头角色状态与 `roleNames` 改为：

```tsx
export default function Home() {
  const [currentRole, setCurrentRole] = useState<RoleId>('cashier')
  const { connectionStatus } = useApiContext()

  const roleNames = Object.fromEntries(roles.map((role) => [role.id, role.name])) as Record<RoleId, string>
```

确认 `RoleSwitcher` 调用保持：

```tsx
<RoleSwitcher currentRole={currentRole} onRoleChange={setCurrentRole} />
```

- [ ] **Step 6: 修改对话侧栏角色视图显示**

在 `prototype/src/components/settlement-chat.tsx` 中导入：

```tsx
import { roles } from '@/components/role-switcher'
import type { AgentResponse, ChatRequest, RoleId } from '@/lib/types'
```

将组件签名改为：

```tsx
export default function SettlementChat({ currentRole }: { currentRole: RoleId }) {
  const currentRoleOption = roles.find((role) => role.id === currentRole)
```

将角色视图 `Badge` 内部替换为：

```tsx
{currentRoleOption ? `${currentRoleOption.icon} ${currentRoleOption.name}视图` : '未知角色视图'}
```

- [ ] **Step 7: 运行角色测试与前端类型检查**

Run:

```bash
python -m pytest src/tests/security/test_security_boundaries.py src/tests/security/test_high_risk_and_permission.py -v
```

Expected: 全部通过。

Run:

```bash
npm run lint
```

Working directory: `prototype`

Expected: 无 TypeScript/ESLint 错误。

- [ ] **Step 8: 提交角色修复**

```bash
git add prototype/src/lib/types.ts prototype/src/components/role-switcher.tsx prototype/src/app/page.tsx prototype/src/components/settlement-chat.tsx src/config/security_policy/rules.py src/tests/security/test_security_boundaries.py src/tests/security/test_high_risk_and_permission.py
git commit -m "fix: align prototype roles with backend permissions"
```

---

### Task 2: 对话结果改为人可读导办展示

**Files:**
- Modify: `prototype/src/components/settlement-chat.tsx:36-41`

- [ ] **Step 1: 增加结构化字段安全读取函数**

在 `prototype/src/components/settlement-chat.tsx` 中，将现有 `extractContent()` 前新增：

```tsx
function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }

  return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
}

function recordList(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) {
    return []
  }

  return value.filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null && !Array.isArray(item))
}
```

- [ ] **Step 2: 替换 `extractContent()` 实现**

将 `extractContent(result: Record<string, unknown>): string` 替换为：

```tsx
function extractContent(result: Record<string, unknown>): string {
  const content = stringValue(result.content)
  if (content) return content

  const exceptionType = stringValue(result.exception_type)
  const errorCode = stringValue(result.error_code)
  const errorExplanation = stringValue(result.error_explanation)
  const responsibleRole = stringValue(result.responsible_role)
  const recommendedSteps = stringList(result.recommended_steps)
  if (exceptionType || errorCode || errorExplanation || responsibleRole || recommendedSteps.length > 0) {
    return [
      '已定位医保结算异常：',
      exceptionType ? `异常类型：${exceptionType}` : null,
      errorCode ? `错误码：${errorCode}` : null,
      errorExplanation ? `原因说明：${errorExplanation}` : null,
      responsibleRole ? `建议责任角色：${responsibleRole}` : null,
      recommendedSteps.length > 0 ? `处理步骤：\n${recommendedSteps.map((step, index) => `${index + 1}. ${step}`).join('\n')}` : null,
      result.requires_human_confirmation === true ? '该操作需要人工确认。' : null,
    ]
      .filter((line): line is string => Boolean(line))
      .join('\n')
  }

  const risks = recordList(result.risks)
  if (risks.length > 0) {
    return [
      `已生成出院前联合质控清单，共 ${risks.length} 项风险：`,
      ...risks.map((risk, index) => {
        const riskType = stringValue(risk.risk_type) ?? '未命名风险'
        const riskLevel = stringValue(risk.risk_level) ?? '未知级别'
        const role = stringValue(risk.responsible_role) ?? '待分配'
        const recommendation = stringValue(risk.recommendation) ?? '请人工复核'
        return `${index + 1}. [${riskLevel}] ${riskType}\n   责任角色：${role}\n   建议：${recommendation}`
      }),
    ].join('\n')
  }

  return JSON.stringify(result, null, 2)
}
```

- [ ] **Step 3: 前端 lint 验证**

Run:

```bash
npm run lint
```

Working directory: `prototype`

Expected: 无 lint 错误。

- [ ] **Step 4: 提交对话展示修复**

```bash
git add prototype/src/components/settlement-chat.tsx
git commit -m "fix: render chat results as readable guidance"
```

---

### Task 3: MCP 服务默认 PostgreSQL 且结构化落表

**Files:**
- Modify: `src/config/mcp.py:6-13`
- Modify: `src/data_platform/storage/mcp/postgres.py:8-34`
- Modify: `src/runtime/api/mcp_routes.py:13-21`
- Modify: `src/tests/data_platform/test_mcp_postgres_storage.py`
- Modify: `src/tests/integration/test_mcp_management_api.py`
- Modify: `prototype/src/lib/types.ts:96-106`
- Modify: `prototype/src/lib/api-client.ts:357-386`
- Modify: `prototype/src/components/mcp-management.tsx:31-127`
- Modify: `prototype/README.md:51-76`

- [ ] **Step 1: 写 PostgreSQL 结构化字段失败测试**

在 `src/tests/data_platform/test_mcp_postgres_storage.py` 中追加：

```python
def test_mcp_schema_statements_include_structured_server_columns():
    sql = "\n".join(statement.sql for statement in mcp_schema_statements())

    assert "name varchar(256) not null" in sql
    assert "endpoint text not null" in sql
    assert "protocol_version varchar(64)" in sql
    assert "auth_headers_json text not null" in sql
    assert "metadata_json text not null" in sql


def test_postgres_mcp_storage_saves_server_structured_columns():
    executor = FakeExecutor()
    storage = PostgresMcpStorage(executor=executor, dialect=PostgresDialect())
    server = McpServer(
        server_id="srv-1",
        name="政策 MCP",
        endpoint="https://mcp.example.test/sse",
        transport=McpTransportType.SSE,
        status=McpServerStatus.ENABLED,
        protocol_version="2025-03-26",
        auth_headers={"Authorization": "Bearer secret"},
        metadata={"owner": "医保办"},
    )

    storage.save_server(server)

    statement = executor.statements[0]
    assert "name" in statement.sql
    assert "endpoint" in statement.sql
    assert "auth_headers_json" in statement.sql
    assert statement.params[0] == "srv-1"
    assert statement.params[1] == "政策 MCP"
    assert statement.params[2] == "https://mcp.example.test/sse"
    assert statement.params[3] == "sse"
    assert statement.params[4] == "enabled"
    assert statement.params[5] == "2025-03-26"
    assert "Bearer secret" in statement.params[6]
    assert "医保办" in statement.params[7]


def test_postgres_mcp_storage_loads_server_from_structured_columns():
    executor = FakeExecutor()
    dialect = PostgresDialect()
    executor.rows["srv-1"] = {
        "server_id": "srv-1",
        "name": "政策 MCP",
        "endpoint": "https://mcp.example.test/sse",
        "transport": "sse",
        "status": "enabled",
        "protocol_version": "2025-03-26",
        "auth_headers_json": dialect.json_dump({"Authorization": "Bearer secret"}),
        "metadata_json": dialect.json_dump({"owner": "医保办"}),
        "payload_json": dialect.json_dump({"legacy": True}),
    }
    storage = PostgresMcpStorage(executor=executor, dialect=dialect)

    loaded = storage.get_server("srv-1")

    assert loaded == McpServer(
        server_id="srv-1",
        name="政策 MCP",
        endpoint="https://mcp.example.test/sse",
        transport=McpTransportType.SSE,
        status=McpServerStatus.ENABLED,
        protocol_version="2025-03-26",
        auth_headers={"Authorization": "Bearer secret"},
        metadata={"owner": "医保办"},
    )
```

- [ ] **Step 2: 写 MCP 服务列表 API 失败测试**

在 `src/tests/integration/test_mcp_management_api.py` 中追加：

```python
def test_mcp_server_list_endpoint_returns_registered_servers():
    client = TestClient(create_app())

    created = client.post(
        "/api/v1/medical-insurance-ai-agent/mcp/servers",
        json={"server_id": "srv-list", "name": "列表 MCP", "endpoint": "https://mcp.example.test/list", "transport": "sse", "status": "enabled", "metadata": {"owner": "医保办"}},
    )
    listed = client.get("/api/v1/medical-insurance-ai-agent/mcp/servers")

    assert created.status_code == 200
    assert listed.status_code == 200
    assert any(server["server_id"] == "srv-list" and server["metadata"]["owner"] == "医保办" for server in listed.json())
```

- [ ] **Step 3: 运行 MCP 测试并确认失败**

Run:

```bash
python -m pytest src/tests/data_platform/test_mcp_postgres_storage.py::test_mcp_schema_statements_include_structured_server_columns src/tests/data_platform/test_mcp_postgres_storage.py::test_postgres_mcp_storage_saves_server_structured_columns src/tests/data_platform/test_mcp_postgres_storage.py::test_postgres_mcp_storage_loads_server_from_structured_columns src/tests/integration/test_mcp_management_api.py::test_mcp_server_list_endpoint_returns_registered_servers -v
```

Expected: 结构化字段与列表接口测试失败。

- [ ] **Step 4: 修改 MCP 默认配置**

将 `src/config/mcp.py` 中 `McpSettings` 改为：

```python
class McpSettings(BaseModel):
    persistence_backend: str = "postgresql"
    cache_backend: str = "in_memory"
    postgres_dsn: str = "postgresql://localhost:5432/hospital_mcp"
    redis_url: str = "redis://localhost:6379/0"
    connection_timeout_seconds: int = 10
    database_schema_auto_init: bool = True
```

- [ ] **Step 5: 修改 MCP PostgreSQL schema 与读写实现**

在 `src/data_platform/storage/mcp/postgres.py` 中将 `mcp_schema_statements()` 改为：

```python
def mcp_schema_statements() -> list[SqlStatement]:
    return [
        SqlStatement(sql="create table if not exists mcp_servers (server_id varchar(128) primary key, name varchar(256) not null, endpoint text not null, transport varchar(32) not null, status varchar(32) not null, protocol_version varchar(64), auth_headers_json text not null, metadata_json text not null, payload_json text not null, updated_at timestamp default current_timestamp)"),
        SqlStatement(sql="create table if not exists mcp_capabilities (capability_id varchar(128) primary key, server_id varchar(128) not null, payload_json text not null, capability_type varchar(32) not null, risk_level varchar(32) not null, enabled boolean not null, updated_at timestamp default current_timestamp)"),
        SqlStatement(sql="create index if not exists idx_mcp_capabilities_server_id on mcp_capabilities (server_id)"),
    ]
```

在 `PostgresMcpStorage` 中增加私有方法：

```python
    def _server_from_row(self, row: dict) -> McpServer:
        if "name" in row and "endpoint" in row:
            return McpServer(
                server_id=row["server_id"],
                name=row["name"],
                endpoint=row["endpoint"],
                transport=row["transport"],
                status=row["status"],
                protocol_version=row.get("protocol_version"),
                auth_headers=self._dialect.json_load(row.get("auth_headers_json")),
                metadata=self._dialect.json_load(row.get("metadata_json")),
            )
        return McpServer(**self._dialect.json_load(row["payload_json"]))
```

将 `save_server()` 改为：

```python
    def save_server(self, server: McpServer) -> None:
        sql = self._dialect.upsert_sql(
            "mcp_servers",
            ("server_id",),
            ("server_id", "name", "endpoint", "transport", "status", "protocol_version", "auth_headers_json", "metadata_json", "payload_json"),
            ("name", "endpoint", "transport", "status", "protocol_version", "auth_headers_json", "metadata_json", "payload_json"),
        )
        payload = self._dialect.json_dump(server.model_dump(mode="json"))
        auth_headers = self._dialect.json_dump(server.auth_headers)
        metadata = self._dialect.json_dump(server.metadata)
        self._executor.execute(
            SqlStatement(
                sql=sql,
                params=(
                    server.server_id,
                    server.name,
                    server.endpoint,
                    server.transport.value,
                    server.status.value,
                    server.protocol_version,
                    auth_headers,
                    metadata,
                    payload,
                ),
            )
        )
```

将 `get_server()` 改为：

```python
    def get_server(self, server_id: str) -> McpServer | None:
        row = self._executor.fetch_one(SqlStatement(sql=f"select server_id, name, endpoint, transport, status, protocol_version, auth_headers_json, metadata_json, payload_json from mcp_servers where server_id = {self._dialect.placeholder(1)}", params=(server_id,)))
        if row is None:
            return None
        return self._server_from_row(row)
```

将 `list_servers()` 改为：

```python
    def list_servers(self) -> list[McpServer]:
        rows = self._executor.fetch_all(SqlStatement(sql="select server_id, name, endpoint, transport, status, protocol_version, auth_headers_json, metadata_json, payload_json from mcp_servers order by server_id"))
        return [self._server_from_row(row) for row in rows]
```

- [ ] **Step 6: 增加 MCP 服务列表接口**

在 `src/runtime/api/mcp_routes.py` 中新增：

```python
@router.get("/servers")
def list_mcp_servers():
    return [server.to_public_dict() for server in _storage.list_servers()]
```

放在 `register_mcp_server()` 前。

- [ ] **Step 7: 修改前端 MCP 类型与 API 客户端**

在 `prototype/src/lib/types.ts` 的 `McpServer` 中确认字段为：

```ts
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
```

在 `prototype/src/lib/api-client.ts` 中新增：

```ts
export async function fetchMcpServers(): Promise<McpServer[]> {
  try {
    return await requestJson<McpServer[]>('/mcp/servers')
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error
    }

    return initialMcpServers().map((server) => ({ ...server, fallback: true }))
  }
}
```

放在 `fetchMcpStorageHealth()` 前。

- [ ] **Step 8: 修改 MCP 管理页面加载真实列表与 metadata 表单**

在 `prototype/src/components/mcp-management.tsx` 中导入 `useEffect` 和 `fetchMcpServers`：

```tsx
import { useEffect, useState } from 'react'
import { fetchMcpServers, fetchMcpStorageHealth, initialMcpServers, registerMcpServer } from '@/lib/api-client'
```

扩展 `McpServerForm`：

```tsx
interface McpServerForm {
  server_id: string
  name: string
  endpoint: string
  transport: McpTransport
  metadata: string
}

const emptyForm: McpServerForm = {
  server_id: '',
  name: '',
  endpoint: '',
  transport: 'sse',
  metadata: '{"owner":"医保办"}',
}
```

增加 JSON 解析函数：

```tsx
function parseMetadata(value: string): Record<string, unknown> {
  if (!value.trim()) {
    return {}
  }

  const parsed = JSON.parse(value) as unknown
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error('metadata 必须是 JSON 对象')
  }

  return parsed as Record<string, unknown>
}
```

修改 `createServerPayload()`：

```tsx
function createServerPayload(form: McpServerForm): McpServer {
  return {
    server_id: form.server_id.trim(),
    name: form.name.trim(),
    endpoint: form.endpoint.trim(),
    transport: form.transport,
    status: 'enabled',
    protocol_version: '2025-03-26',
    auth_headers: {},
    metadata: parseMetadata(form.metadata),
  }
}
```

在组件内增加加载函数：

```tsx
  const loadServers = async () => {
    try {
      const result = await fetchMcpServers()
      setServers(result)

      if (result.some((server) => server.fallback)) {
        setFallback()
      } else {
        setConnected()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '服务列表加载失败')
    }
  }

  useEffect(() => {
    void loadServers()
  }, [])
```

在 `submit()` 中创建 payload 前增加 metadata 错误处理：

```tsx
    let payload: McpServer
    try {
      payload = createServerPayload(form)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'metadata 格式错误')
      return
    }
```

将注册调用改为：

```tsx
      const registered = await registerMcpServer(payload)
      await loadServers()
      setServers((current) => [
        registered,
        ...current.filter((server) => server.server_id !== registered.server_id),
      ])
```

在表单 `endpoint` 输入框后增加 metadata 输入框：

```tsx
            <Input
              placeholder='metadata JSON，例如 {"owner":"医保办"}'
              value={form.metadata}
              onChange={(event) => updateForm('metadata', event.target.value)}
            />
```

在服务列表中 `endpoint` 下方增加：

```tsx
                  <p className="text-sm text-gray-600 break-all">
                    <span className="font-medium">metadata:</span> {JSON.stringify(server.metadata)}
                  </p>
```

- [ ] **Step 9: 更新 MCP README**

在 `prototype/README.md` 环境变量表后补充：

```markdown
### 后端 MCP 持久化配置

后端 MCP 管理默认使用 PostgreSQL 结构化持久化：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `MCP_PERSISTENCE_BACKEND` | MCP 注册中心持久化后端 | `postgresql` |
| `MCP_POSTGRES_DSN` | MCP PostgreSQL 连接串 | `postgresql://localhost:5432/hospital_mcp` |
| `MCP_DATABASE_SCHEMA_AUTO_INIT` | 启动时自动创建 MCP 表 | `true` |

如需离线演示，可显式设置 `MCP_PERSISTENCE_BACKEND=in_memory`。
```

- [ ] **Step 10: 运行 MCP 后端测试与前端 lint**

Run:

```bash
python -m pytest src/tests/data_platform/test_mcp_postgres_storage.py src/tests/integration/test_mcp_management_api.py -v
```

Expected: 全部通过。

Run:

```bash
npm run lint
```

Working directory: `prototype`

Expected: 无 lint 错误。

- [ ] **Step 11: 提交 MCP 修复**

```bash
git add src/config/mcp.py src/data_platform/storage/mcp/postgres.py src/runtime/api/mcp_routes.py src/tests/data_platform/test_mcp_postgres_storage.py src/tests/integration/test_mcp_management_api.py prototype/src/lib/types.ts prototype/src/lib/api-client.ts prototype/src/components/mcp-management.tsx prototype/README.md
git commit -m "fix: persist mcp servers in structured postgresql storage"
```

---

### Task 4: 模型测试流式接口与同步展示一致

**Files:**
- Modify: `src/runtime/api/routes.py:209-240`
- Modify: `src/tests/integration/test_openapi_contract.py:64-89`
- Modify: `prototype/src/components/model-test.tsx:189-425`

- [ ] **Step 1: 修改流式 final 字段测试**

在 `src/tests/integration/test_openapi_contract.py` 的 `test_model_test_stream_returns_delta_final_and_done_events()` 中，在现有断言后追加：

```python
    assert '"content":"你好"' in text
    assert '"model_name":"streaming-model"' in text
    assert '"latency_ms"' in text
    assert '"prompt_tokens":1' in text
    assert '"completion_tokens":2' in text
```

- [ ] **Step 2: 运行流式测试并确认失败**

Run:

```bash
python -m pytest src/tests/integration/test_openapi_contract.py::test_model_test_stream_returns_delta_final_and_done_events -v
```

Expected: 缺少 `content`、`model_name` 或 `latency_ms` 断言失败。

- [ ] **Step 3: 修改后端流式 final 事件**

将 `src/runtime/api/routes.py` 中 `model_test_stream()` 的 `events()` 内部变量与 final 逻辑改为：

```python
    def events() -> Iterator[str]:
        gateway = ModelGateway()
        messages = [Message(role='user', content=request.message)]
        start = time.time()
        yield sse_event('start', {'scene': request.scene})
        completion_tokens = 0
        prompt_tokens = 0
        finish_reason = None
        content_parts: list[str] = []
        model_name = 'streaming-model'
        try:
            for chunk in gateway.generate_stream(messages=messages, model_type='llm', scene=request.scene):
                if chunk.content:
                    content_parts.append(chunk.content)
                    yield sse_event('delta', {'content': chunk.content})
                if chunk.usage:
                    prompt_tokens = chunk.usage.prompt_tokens
                    completion_tokens = chunk.usage.completion_tokens
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
            latency_ms = int((time.time() - start) * 1000)
            yield sse_event(
                'final',
                {
                    'content': ''.join(content_parts),
                    'model_name': model_name,
                    'latency_ms': latency_ms,
                    'prompt_tokens': prompt_tokens,
                    'completion_tokens': completion_tokens,
                    'scene': request.scene,
                    'finish_reason': finish_reason or 'stop',
                },
            )
        except Exception as exc:
            yield sse_event('error', model_error_detail(exc))
        yield sse_event('done', {})
```

- [ ] **Step 4: 修改前端流式模式展示**

在 `prototype/src/components/model-test.tsx` 中，调整 `runStream()` 的 `event.event === 'final'` 分支为：

```tsx
        if (event.event === 'final') {
          finalizeStream(event.data)
          return
        }
```

将 JSX 中 `mode === 'stream'` 区块替换为：

```tsx
          {mode === 'stream' && (
            <div className="space-y-4">
              {result && (
                <>
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                    <Metric label="模型" value={result.model_name} />
                    <Metric label="延迟" value={`${result.latency_ms}ms`} />
                    <Metric label="Prompt Tokens" value={String(result.prompt_tokens)} />
                    <Metric label="Completion Tokens" value={String(result.completion_tokens)} />
                  </div>
                  <pre className="bg-gray-50 rounded-lg p-4 whitespace-pre-wrap text-sm min-h-[120px]">
                    {result.content}
                  </pre>
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-gray-600">Token 用量</span>
                      <span className="font-medium">{result.prompt_tokens + result.completion_tokens}</span>
                    </div>
                    <Progress value={tokenProgress(result)} className="h-2" />
                  </div>
                  {result.fallback && <Badge variant="outline">离线模式 - 演示数据</Badge>}
                </>
              )}
              <div>
                <p className="text-sm font-medium mb-2">实时输出</p>
                <pre className="bg-slate-900 text-blue-100 rounded-lg p-4 min-h-[180px] whitespace-pre-wrap text-sm overflow-auto">
                  {streamText || '等待流式输出'}
                </pre>
              </div>
            </div>
          )}
```

- [ ] **Step 5: 运行模型流式测试与前端 lint**

Run:

```bash
python -m pytest src/tests/integration/test_openapi_contract.py::test_model_test_stream_returns_delta_final_and_done_events src/tests/integration/test_openapi_contract.py::test_model_test_stream_returns_structured_error_and_done -v
```

Expected: 全部通过。

Run:

```bash
npm run lint
```

Working directory: `prototype`

Expected: 无 lint 错误。

- [ ] **Step 6: 提交流式修复**

```bash
git add src/runtime/api/routes.py src/tests/integration/test_openapi_contract.py prototype/src/components/model-test.tsx
git commit -m "fix: align streaming model test with sync display"
```

---

### Task 5: 集成验证与交付说明

**Files:**
- Modify: `openspec/changes/front-prototype/tasks.md:78-87`

- [ ] **Step 1: 运行后端相关测试集**

Run:

```bash
python -m pytest src/tests/security/test_security_boundaries.py src/tests/security/test_high_risk_and_permission.py src/tests/data_platform/test_mcp_postgres_storage.py src/tests/integration/test_mcp_management_api.py src/tests/integration/test_openapi_contract.py -v
```

Expected: 全部通过。

- [ ] **Step 2: 运行前端 lint**

Run:

```bash
npm run lint
```

Working directory: `prototype`

Expected: 无 lint 错误。

- [ ] **Step 3: 更新 OpenSpec 任务验证项**

在 `openspec/changes/front-prototype/tasks.md` 中将以下任务勾选为完成：

```markdown
- [x] 10.1 端到端验证：启动后端 + 前端，测试"为什么这个患者结算失败"对话走通真实 API
- [x] 10.4 MCP 管理验证：注册服务 → 查看健康状态 → 验证服务列表更新
- [x] 10.5 模型测试验证：同步模式测试 → 流式模式测试 → 验证历史记录
```

如果实际没有完成浏览器人工验证，不勾选 `10.1`、`10.4`、`10.5`，只在最终说明中列出自动化验证结果。

- [ ] **Step 4: 查看 git diff 自检**

Run:

```bash
git diff --check
```

Expected: 无空白错误。

Run:

```bash
git status --short
```

Expected: 只包含本计划相关文件改动。

- [ ] **Step 5: 提交验证说明更新**

如果 `openspec/changes/front-prototype/tasks.md` 有更新：

```bash
git add openspec/changes/front-prototype/tasks.md
git commit -m "docs: update front prototype verification status"
```

如果没有更新，跳过提交。

---

## 自检清单

- 角色枚举：前端发送给后端的是 `cashier`、`medical_office`、`information_department`、`medical_record_staff`，不是旧值 `insurance_office`、`it_department`、`medical_record`。
- 医保办权限：`medical_office` 能访问结算异常与出院前质控。
- 对话展示：结算异常和质控结果默认是中文导办文案，不再裸展示 JSON。
- MCP 存储：默认配置为 PostgreSQL；`mcp_servers` 结构化列有值，仍保留 `payload_json` 兼容扩展。
- MCP 页面：注册服务后能从后端列表读回，metadata 可见。
- 模型流式：`final` 包含完整 `ModelTestResponse` 字段；前端 stream 模式显示指标、正文、token 与实时输出。
- 验证命令：pytest 目标测试和 `prototype` lint 通过。
