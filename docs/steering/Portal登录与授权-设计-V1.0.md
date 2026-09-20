# Portal 登录与授权设计 V1.0

> Issue: [#75 Portal 登录与授权入口：会话 token 签发与权限校验统一（#43 最小切片）](https://github.com/ktyhwangfei/hospital_medical_insurance_agent/issues/75)
> 上游: #43 底座五·P5 上线加固（SSO/权限矩阵/审计）。本设计是其中的**最小可用切片**：先用过渡本地账号体系让生产环境具备登录授权能力，不阻塞于医院 SSO 文档。
> 状态: 设计稿（待评审）

---

## 1. 背景与目标

### 1.1 问题

Portal 所有治理写操作的 token 唯一来源是启动脚本注入的 `NEXT_PUBLIC_*_TOKEN`（dev 专用）：

- `NODE_ENV=production` 时前端权限判断统一返回 false → 治理按钮全部禁用；
- 部分域（skill-control / model-governance）dev 下直接用**硬编码假 JWT**；
- `AUTH_JWT_SECRET` 未预设时每次启动随机生成（`start-servers.ps1:107`），重启即全员失效。

**结论：生产环境目前无法完成任何治理写操作。**

### 1.2 目标（对照 issue #75 验收）

| # | 验收项 | 设计落点 |
|---|--------|----------|
| 1 | 生产构建下登录后可完成 Workflow 启停写入并可回读 | §5.2 签发接口 + §5.5 登录页 |
| 2 | 无权限账号访问治理写接口 403，前端按钮禁用且给出原因 | §5.4 统一校验 + §5.5 `hasPermission` |
| 3 | token 过期行为明确（续期或重登），不静默降级为匿名 | §5.7 过期与刷新策略 |
| 4 | 审计能回答「谁在什么时候改了哪条治理配置」 | §5.8 审计留痕 |

### 1.3 非目标

- 医院 SSO / 扫码登录（归 #43，本设计账号体系为可替换的过渡实现，接口形态兼容后续 SSO 对接）；
- 三级权限矩阵完整版、组织/租户级授权；
- `/policy-qa` 业务查询入口强制登录（本切片只覆盖治理写操作与治理页面授权渲染）。

---

## 2. 现状证据

### 2.1 后端

- **验签已有、签发没有**。`src/gateway/auth/__init__.py` 自实现 HS256 验签（`AUTH_JWT_SECRET`，fail-closed），payload 必填 `sub` / `exp` / `roles` / `permissions`；**全仓库无任何 token 签发代码**。
- **权限校验模式事实统一但实现散落**：`validate_signed_token` + `check_permission` → 401 `AUTH_REQUIRED`/`AUTH_INVALID` → 403 `AUTH_FORBIDDEN`。但 5+ 份本地 helper 各自复制：`tool_workflow_routes.py:74`、`semantic_alignment_routes.py:214`、`ops_routes.py:76`、`question_library_routes.py:104`、`data_governance_routes.py:88`、`model_governance_routes.py:93`、`flow_routes.py:68/242`、`infra_skill_routes.py:286`。
- **权限词汇表**（后端实际校验的全集）：
  `workflow:read/write`、`ops:read/write`、`question_library:read/write`、`data_governance:read/write`、`semantic:review`、`flow:read`、`model_governance:read/write/review/publish`、`skill:release:test`、`skill:evaluate`。
- **审计**：`PostgreSQLAuditLog`（`src/security/audit/postgresql_store.py`）的 `audit_logs` 表有 `user_id/role/request_path/request_method/request_summary/response_status/client_ip/duration_ms`，是请求级审计，**无 `action`/`target_ref` 显式字段**；写入失败静默吞掉。操作人取自 JWT 主体的先例已存在：`flow_routes.py:245`（`publish_flow(operator=auth.user_id)`）、语义审核 `reviewed_by=principal.user_id`；**反例**：`question_library_routes.py:150` 的 `ReviewRequest.reviewer` 仍自报。
- **账号体系完全不存在**：无用户表、密码哈希、登录端点、refresh token。
- **过期**：`exp` 必填且强制校验（过期 → `EXPIRED_TOKEN`）；无刷新机制；撤销仅进程内存黑名单（重启失效）。

### 2.2 前端（src/apps/portal）

- **9 套并行 token 孤岛**：每域一个 `xxxToken()`（sessionStorage 优先 → dev env 回退），5 个 sessionStorage 键（`workflow-token` / `ops-token` / `question-library-token` / `data-governance-token` / `semantic-review-token`）+ skill/model-governance 的 dev 硬编码假 JWT。
- 权限判断函数：`hasWorkflowWritePermission()`（`lib/tool-workflow-api.ts:89`）、`hasOpsPermission()`、`hasQuestionLibraryPermission()`、`hasDataGovernancePermission()`，均为手工 base64url 解码 payload 查 `permissions`，**不验签、不验 exp**；production 下 env 回退被禁用 → 一律 false；dev 下无 token 反而默认放行。
- **无 `/login` 页、无 `middleware.ts`、无登录态上下文**；唯一身份交互是模型治理页 dev 身份下拉（`model-governance-workspace.tsx:563`，假 JWT 写入 sessionStorage）。
- `Authorization` header 在 12 处由各域 lib 自行拼接；统一 client `lib/api-client.ts` 不带鉴权。
- dev token 签发（`start-servers.ps1:106-158`）：5 个身份（`portal-dev-reviewer` / `-data-governance` / `-ops` / `-question-library` / `-workflow`），roles 均为 `information_department`，有效期统一 24h。

---

## 3. 总体方案

```
Portal /login（登录页）
  → POST /api/v1/medical-insurance-ai-agent/auth/login（账号+密码）
  → 后端校验 portal_accounts（PostgreSQL，env 种子初始化）
  → 签发 HS256 JWT（sub/roles/permissions/iat/exp，密钥=AUTH_JWT_SECRET）
  → 前端存 sessionStorage["portal-token"]，AuthProvider 解析权限
  → 治理请求统一带 Authorization: Bearer <token>
  → 后端统一 require_permission(scope) 依赖（收敛现有 5+ 份 helper）
  → 403 → 前端按钮禁用 + 原因；401/EXPIRED → 跳 /login
  → 治理写操作显式审计（user_id + action + target_ref）
```

四个新增面：**账号体系（过渡）→ 签发/续期接口 → 统一权限校验与渲染 → 治理审计**。业务系统对接（HIS/SSO）仍走 `adapters/` 防腐层原则，本地账号是 adapter 背后的第一种实现。

---

## 4. 关键决策

| # | 决策点 | 结论 | 理由 |
|---|--------|------|------|
| D1 | token 存储 | `sessionStorage`，单键 `portal-token` | XSS 场景下攻击面与 `localStorage` 相同（JS 均可读），但 sessionStorage 随标签页关闭即失效、多标签页会话互不影响，符合"院内工作站台式机暂离"场景；不引入 cookie（避免 CSRF 与新中间件面）。**代价**：新标签页需重新登录——院内治理操作低频，可接受 |
| D2 | 账号存储 | PostgreSQL `portal_accounts` 表 + 启动时 env 种子初始化 | 生产可运维（可禁用账号、改角色），开发零配置（种子账号）；比纯 env 账号多一张表，但换来审计/禁用的完整性 |
| D3 | 密码哈希 | stdlib `hashlib.pbkdf2_hmac`（sha256，≥60 万轮，随机 16B salt，格式 `pbkdf2$<iter>$<salt>$<hash>`） | 零新依赖；避免引入 bcrypt/passlib |
| D4 | 签发算法 | 复用现有 HS256 + `AUTH_JWT_SECRET`，签发函数放入 `src/gateway/auth/` | 与验签同密钥、同实现，无迁移成本；SSO 接入时仅替换签发来源，验签面不变 |
| D5 | 过期/刷新 | access token 2h；`POST /auth/refresh` 持**未过期** token 滑动续签（新 token 的 `iat` 向前滑动，绝对上限 12h，超则 401 重登）；过期后**一律 401 重定向登录页，绝不静默降级匿名** | 满足验收 #3；实现最简（无 refresh token 表/轮换），12h 绝对上限兜住"永不清退"风险 |
| D6 | 前端权限渲染 | 单一 `hasPermission(scope)` + `AuthProvider`；各页现有 `hasXxxPermission` 改为薄包装 | 消除 9 套孤岛；后端仍是唯一裁决者，前端禁用只是体验层 |
| D7 | 服务端路由守卫 | 不做 `middleware.ts`；登录态守卫在客户端（sessionStorage 本就不可被 middleware 读取） | Next 16 middleware 读不到 sessionStorage；后端 401/403 已是硬边界 |
| D8 | dev token 处置 | 保留现有 dev env token 兜底与宽松行为，标记 deprecated；登录页在 dev 同样可用（种子账号） | 最小侵入；后续切片再移除 `NEXT_PUBLIC_*_TOKEN` 注入 |
| D9 | 审计模型 | 复用 `audit_logs` 表，新增 `action` / `target_ref` 两列（CREATE + ALTER 双写，遵守项目 PG 迁移陷阱）；关键写端点显式写入 | 请求级审计已能答 who/when，补 action/target 答"改了哪条配置" |

---

## 5. 详细设计

### 5.1 账号体系（过渡）

**表 `portal_accounts`**（新建，DDL 含 `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 双写）：

| 列 | 类型 | 说明 |
|---|---|---|
| id | BIGSERIAL PK | |
| username | TEXT NOT NULL UNIQUE | 登录名 |
| password_hash | TEXT NOT NULL | `pbkdf2$<iter>$<salt_b64>$<hash_b64>` |
| role | TEXT NOT NULL | 角色编码，见 §5.3 |
| status | TEXT NOT NULL DEFAULT 'active' | `active` / `disabled` |
| created_at / updated_at | TIMESTAMPTZ DEFAULT now() | |

**种子初始化**：启动时读取环境变量 `PORTAL_SEED_ACCOUNTS`（JSON 数组 `[{"username","password","role"}]`），仅当 username 不存在时插入（幂等，已存在不覆盖密码）。未配置该变量时跳过（生产必须配置，否则登录接口无可用账号）。

领域模型落位：`src/domain/` 新增 `portal_account` 聚合（遵循 `src/domain/AGENTS.md` 战术分类与命名字典，通用语言：**门户账号 PortalAccount / 角色 PortalRole**），存储走 ports/adapter 模式（默认 PostgreSQL，`USE_MEMORY_STORAGE=1` 回退内存）。

### 5.2 后端认证 API

路由前缀 `/api/v1/medical-insurance-ai-agent/auth`，全部 fail-closed（`AUTH_JWT_SECRET` 缺失 → 端点不可用，绝不回退假数据）：

| 端点 | 说明 |
|---|---|
| `POST /auth/login` | body `{username, password}`；校验账号（含 `status=active` 与角色→权限展开）→ 签发 access token（2h）。错误统一 401 `AUTH_INVALID_CREDENTIALS`（不区分用户不存在/密码错误）。**挂现有 gateway 限流器**（防爆破，如 5 次/分钟/IP） |
| `POST /auth/refresh` | Authorization 持未过期 token → 校验 `iat` 滑动窗口（≤12h）→ 签发新 token；过期/超限 → 401 `EXPIRED_TOKEN` |
| `POST /auth/logout` | token 加入黑名单（现有进程内存机制；文档注明重启即清空的边界） |
| `GET /auth/me` | 返回当前主体 `{user_id, roles, permissions, exp}`，供前端 `AuthProvider` 初始化 |

**JWT payload**（新增 `iat`，与现有验签兼容）：

```json
{ "sub": "<username>", "roles": ["<role>"], "permissions": ["<scope>", ...], "iat": 1730000000, "exp": 1730007200 }
```

签发实现：`src/gateway/auth/` 新增 `sign_token(payload) -> str`（HS256，与验签共用密钥与实现风格）。

### 5.3 权限矩阵最小集

角色 → 权限映射集中定义在 `src/config/security_policy/`（或现有安全配置模块），签发时展开进 token，后端校验只认 token 内 `permissions`：

| 角色 | 权限 | 对应治理面 |
|---|---|---|
| `admin` | 全部权限 | 平台管理员 |
| `governance_admin` | `data_governance:read/write`、`workflow:read/write`、`flow:read` | 数据治理 / 工具工作流 |
| `ops_admin` | `ops:read/write` | 资产健康运营 / 运营分析 |
| `knowledge_admin` | `question_library:read/write`、`semantic:review` | 可信问题库 / 语义审核 |
| `reviewer` | `semantic:review` | 政策知识审核（最小权限示例） |
| `skill_admin` | `skill:evaluate`、`skill:release:test`、`model_governance:read/write/review/publish` | 技能评测 / 模型治理 |

说明：
- 矩阵即现有 dev token scope 词汇表的全集收口，**不新增 scope 语义**；`flow:read` 维持现有 `FLOW_CALLER_ROLE_LEVELS` 角色分级逻辑不变。
- 一个账号一个角色（本切片不做角色组合）；后续 #43 三级矩阵在此基础上扩展。

### 5.4 后端统一权限校验

新增公共依赖工厂（建议 `src/runtime/api/auth_deps.py`，与 gateway auth 分层：gateway 管验签，runtime 管 scope 依赖）：

```python
def require_permission(scope: str) -> Callable[..., DataGovernancePrincipal]
```

行为与现有各 helper 完全一致（401 `AUTH_REQUIRED`/`AUTH_INVALID`/`EXPIRED_TOKEN` → 403 `AUTH_FORBIDDEN` → 返回含 `user_id/roles/permissions` 的 principal），**仅一份实现**。既有 5+ 份本地 helper 逐步迁移替换（迁移是机械替换，本切片完成 workflow-catalog 一个端点验证模式，其余可在同切片内批量替换或留 TODO——倾向同切片内全部替换，避免两套并存）。

同时修两个已有偏差：
- `question_library_routes.py:150` 的 `ReviewRequest.reviewer` 自报 → 改为从 principal 取（与 flow 发布、语义审核先例对齐）；
- 原 `validate_token` 的模拟放行分支（`gateway/auth/__init__.py:270`）治理接口已不经过，维持不动，但文档标注"仅遗留路径使用"。

### 5.5 前端设计

**新增 `src/apps/portal/app/login/page.tsx`**：
- 账号 + 密码表单，提交 `POST /auth/login`；
- 成功 → token 写 `sessionStorage["portal-token"]` → 跳 `?redirect=` 指定页（缺省 `/policy-qa`）；
- 失败 → 表单内错误提示（401 文案统一「账号或密码错误」）；
- 已有有效 token 访问 `/login` → 直接跳回。

**新增 `src/apps/portal/src/lib/auth.ts`（统一鉴权库，替代 9 套孤岛）**：

```ts
const TOKEN_KEY = 'portal-token';
export function getToken(): string | null            // sessionStorage 读取
export function setToken(token: string): void
export function clearToken(): void
export function getPrincipal(): Principal | null      // 解码 payload + 本地 exp 预检（过期即视为无）
export function hasPermission(scope: string): boolean // dev 无 token 维持现状宽松行为；production 无 token = false
export function authHeaders(): Record<string, string> // { Authorization: 'Bearer ...' } 或 {}
```

**新增 `AuthProvider`（React Context）**：挂载于根 layout，初始化读 `portal-token` → 暴露 `{ principal, hasPermission, login, logout }`；`login()` 供 `/login` 页写入，token 本地 exp 预检失败或收到 401 → `logout()` + 跳 `/login?redirect=<当前路径>`。

**各域改造（机械替换）**：
- `workflowToken()` / `opsToken()` / `questionLibraryToken()` / `governanceToken()` / `semanticReviewRequest()` 的 token 来源统一改读 `getToken()`；Authorization 拼接统一改 `authHeaders()`（12 处收敛）；
- `hasWorkflowWritePermission()` 等改为 `hasPermission('workflow:write')` 薄包装（保留导出签名，页面零改动）；
- 模型治理页 dev 身份下拉、`skill-auth.ts` 硬编码假 JWT：dev 保留（D8），但 production 分支改走登录态；
- 无权限按钮：禁用 + `title`/tooltip 给出原因（如「需要 workflow:write 权限，请使用有权限的账号登录」），已有先例样式对齐。

**401 处理**：`requestJson` 捕获 401 → 若响应体 `error_code` 为 `EXPIRED_TOKEN`/`AUTH_INVALID` → `clearToken()` + 跳登录页；其余 401 按现状上抛。

### 5.6 过期与刷新策略

- 后端唯一裁决：`exp <= now` → `EXPIRED_TOKEN`（现有逻辑不变）。
- 前端：**不做静默后台续期**；治理写请求发出前 `getPrincipal()` 本地预检，临期（剩余 < 5 分钟）的写操作先同步调 `/auth/refresh` 换新 token 再发请求；其余场景 401 后统一跳登录。
- 滑动上限 12h（`iat` 超窗拒绝续期）→ 强制重登。文档化：不做 refresh token 持久化，进程重启黑名单清空，接受此边界。

### 5.7 审计留痕

- `audit_logs` 表新增两列（D9）：`action TEXT`（如 `workflow.config.update` / `flow.publish` / `semantic.review` / `question.review`）、`target_ref TEXT`（如 `workflow_id=<id>` / `flow_id=<id>`）。DDL 双写遵守项目「CREATE + ALTER」陷阱约定。
- 新增 `record_governance_action(principal, action, target_ref, request_context)`，在关键写端点**显式调用**（workflow config、flow publish、semantic review、question review、model governance 写操作族），与现有 GatewayAuditMiddleware 请求级日志互补。
- 修复写入失败静默吞掉：审计写入失败记录 warning 日志（仍不阻断业务，但可观测）。

---

## 6. 兼容与迁移

- **dev 行为不变**：非 production 下无 token 仍放行浏览/写操作（现状宽松行为），登录页可用种子账号体验完整链路。`NEXT_PUBLIC_*_TOKEN` 注入保留但标注 deprecated，移除归后续切片。
- **生产行为变化**：治理写接口无 token 一律 401（现状已如此）；变化在于登录后可真实获得权限（现状是永不可能）。
- `start-servers.ps1` / `ws.ps1` 无需改动（`AUTH_JWT_SECRET` 已注入；重启 token 失效在过渡期内可接受，生产部署应预设固定密钥，写入部署文档）。

## 7. 验收对照与验证

| 验收 | 验证方式 |
|---|---|
| 1 生产构建登录后可 Workflow 启停并回读 | 单测（签发/校验）→ API 测试（login → PUT config → GET 目录回读）→ Flow：portal 登录页真实走一遍启停 |
| 2 无权限 403 + 前端禁用给原因 | API 测试 reviewer 账号调 workflow:write 断言 403；组件测试按钮 disabled + tooltip |
| 3 过期行为明确 | 单测 exp 边界；API 测试过期 token 401 `EXPIRED_TOKEN`；前端 401 跳登录页测试 |
| 4 审计可答 who/when/what | API 测试写操作后查 `audit_logs` 断言 user_id/action/target_ref/时间 |

测试分层遵循 `docs/governance/TEST-VERIFICATION-MATRIX.md`（登录授权属 R2-R3，需 API + 前端组件测试覆盖）。

## 8. 风险与开放问题

- **R1 密钥稳定性**：`AUTH_JWT_SECRET` 未预设时重启即全员失效——生产部署文档强制预设固定密钥（部署侧约束，非代码）。
- **R2 爆破防护**：本地账号过渡期内是唯一防线，依赖 gateway 限流 + PBKDF2 高迭代成本；SSO 接入后收敛。
- **R3 黑名单进程内存**：logout 不跨进程生效；单进程部署下无实际风险，多副本部署前需持久化（归 #43）。
- **开放 1**：`skill:control` 相关写操作当前走 `SKILL_CONTROL_DEV_MODE` dev 开关绕过鉴权，其正式 scope 命名需在实现时与后端现有校验点对齐。
- **开放 2**：`RoleSwitcher`（header 前端角色切换）与登录态的关系——本切片建议保留为"业务视角切换"（与鉴权无关），避免混淆。

## 9. 实施切分建议（后续）

1. **S1 后端账号 + 签发**：`portal_accounts` 表、seed、`sign_token`、四个 `/auth/*` 端点 + 单测/API 测试。
2. **S2 统一权限依赖**：`require_permission` 工厂 + 既有 helper 全量替换 + reviewer 自报修复。
3. **S3 前端登录与统一鉴权**：`/login`、`lib/auth.ts`、`AuthProvider`、12 处 header 收敛、各页 `hasPermission` 包装。
4. **S4 审计**：`audit_logs` 扩列 + `record_governance_action` + 关键写端点接入。
5. **S5 验证闭环**：按 §7 验收矩阵跑 单元 → API → Flow 三级验证，生产构建（`next build` + uvicorn）实测 Workflow 启停。
