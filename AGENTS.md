# AGENTS.md - 院端医保智能体系统

> **Agent 动工前先读本文件（5 分钟）**，然后按需深入子目录的 AGENTS.md。
> **进度追踪**：当前项目进度见 **`PROGRESS.md`**。
> **详细治理**：模块边界、风险分级、变更证据模板见 **`docs/governance/`**。

## Agent 动工前检查清单

□ 已读 §安全约束（高风险拦截、来源可追溯、脱敏）
□ 已查 `PROGRESS.md` 当前焦点领域
□ 已确认改动范围不超出"最小可验证单元"（见 §精准修改）
□ 已查 `src/domain/AGENTS.md` 相关领域的通用语言字典
□ 涉及外部系统 → 走 `adapters/` 防腐层
□ 涉及模型调用 → 走 `model_service/gateway` 统一入口

## Agent 收工前检查清单

□ 所有改动已通过 LSP 诊断（零新增错误）
□ 遇到任何阻塞性故障？→ 运行 `/retrospect`，自动评估能自动化还是留文档
□ 学到新模式？→ 同上

## 启动命令

```bash
# 启动开发服务器（--factory 必须指定，因为 create_app 是工厂函数）
uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory --reload

# 前端开发服务器（Next.js 16 应用）
cd src/apps/portal && npm run dev    # 业务应用入口（默认端口 3000）

```
## 架构

完整架构定义见 `docs/steering/架构设计.md`，采用四层体系：SaaS 应用产品层 → PaaS 平台支撑层 → DaaS 数据与知识服务层 → 系统接入与基础设施层。

PaaS 层七个服务域是系统的核心能力分解：接入安全（gateway）、会话上下文（runtime/session+context）、智能编排（runtime/intent+planning+orchestration）、模型服务（model_service）、知识服务（knowledge_extension）、业务适配（adapters）、任务闭环（runtime/task_closure）。

当前已实现后端核心子集（`src/` 下）及前端应用 portal（`src/apps/portal` 下）。

### 目录职责映射

Agent 编码时根据以下映射定位代码位置：

| 目录 | 职责 | 当前状态 |
|------|------|----------|
| `runtime/` | Agent 核心运行时：API 入口、会话上下文、意图识别、澄清、编排（含 LangGraph）、调度、响应（含 SSE 流式）、任务闭环、事件日志、技能注册、政策问答 | 已实现（api/context/intent/clarification/planning/orchestration/scheduling/task_closure/runtime_state/event_log/capability_nodes/skill_registry/langgraph/policy_qa） |
| `business_scenarios/` | 医保业务场景：结算异常导办、出院前联合质控 | 场景代码已实现（settlement_exception_guide、pre_discharge_joint_qc），运行时入口整合至 runtime/scenario_executor |
| `model_service/` | 模型服务网关：统一调用入口、路由策略、OpenAI 兼容 Provider、流式生成、异常分类、模型配置管理、Provider 管理 | 已实现（gateway/router/providers/openai_compatible/exceptions/models/ports） |
| `knowledge_extension/` | 知识与扩展：规则解释（含 Milvus 政策检索+SQL Server 数据源）、MCP 注册中心、扩展注册 | 已实现（common/extension_registry/mcp_registry/rule_explanation + policy_retrieval 含 Milvus/SQLServer/语义映射；原 knowledge/rag/assets/prompt_templates 已删除，由 stub 提供兼容） |
| `adapters/` | 外部系统防腐层：医保接口、事前审核、DRG/DIP、HIS、EMR、病案、收费 | 7 个内存适配器 + base 基类（models/service）+ ports 端口定义均已实现 |
| `data_platform/` | DaaS 数据底座：数据访问、存储端口、缓存（含 Redis）、持久化（含 PostgreSQL 方言/迁移/执行器）、Skill/MCP/向量存储 | 已实现（data_access/cache/persistence/storage 含 skill/mcp/postgresql/vector 子目录） |
| `domain/` | 领域模型：患者、医保、费用、审核风险、DRG/DIP、病案、任务、申诉、医嘱费用、技能 | 已实现（patient/insurance/task/common/drg_dip/medical_record/audit_risk/appeal/order_fee/skill） |
| `security/` | 安全围栏：权限、脱敏、风险控制、审计（含 PostgreSQL 持久化） | 已实现（authorization/desensitization/risk_control/audit 含 postgresql_store） |
| `config/` | 全局配置：安全策略、适配器配置、模型路由、模型服务、MCP 配置 | 已实现（security_policy/adapters/model_routing/model_service/mcp） |
| `observability/` | 可观测性：指标定义 + 中间件、链路追踪中间件 | 基础实现（metrics + tracing） |
| `shared/` | 共享基础：异常模型、响应契约、Schema 契约、技能加载器/注册表 | 已实现（exceptions/schemas/skills） |
| `gateway/` | 统一接入网关：API网关、渠道识别、认证鉴权、租户隔离、限流熔断、请求安全校验、接入日志 | 已实现（api_gateway/channel/auth/tenant/rate_limiter/request_guard/access_log） |
| `interaction/` | 多模态交互层：Chat对话、文件上传、语音交互、页面上下文、消息提醒、知识上传 | 已实现（chat/file/voice/page_context/notification/knowledge_upload） |
| `apps/` | SaaS 应用入口层：Next.js 16 应用 Portal（业务导办与政策问答） | 已实现（portal/ 含 policy-qa/semantic-layer/policy-knowledge/skills/qa-history 路由，及 settlement/qc/dashboard） |
| `skills/` | Skill 驱动架构：自包含的医保业务能力包（费用解释、起付线、大额自付等），通过 YAML 配置 + Python assembler 实现声明式业务逻辑。每个 Skill 通过 `business_action` + `business_object` 挂载到平台七类业务动作 | 已实现（settlement_explain_skill/ 含 SKILL.md + schemas + templates + scripts，已声明 `explain` + `settlement`） |
| `src/skill_infra/` | Skill 基础设施：动态加载器（SkillLoader）、关键词路由器（SkillRouter），自动扫描 skills/ 目录发现和加载 skill 包 | 已实现（skill_loader.py, skill_router.py） |
| `src/domain/common/actions.py` | Business Action 枚举：平台最高层业务分类（七类动作 + 十类对象 + 能力矩阵白名单） | 已实现（BusinessAction, BusinessObject, VALID_ACTION_OBJECT_PAIRS） |
| `deploy/` | 部署配置：Docker、K8s、环境变量模板 | 已实现（docker/k8s/env） |

### 业务流向

```
runtime/api (FastAPI 路由)
  → runtime/intent (意图识别：关键词降级 / LLM 解析 / LangGraph 图式)
  → src/domain/common/actions (Business Action 分类：Explain/Query/Guide/Verify/Compare/Evaluate/Analyze)
  → security/risk_control (高风险拦截)
  → security/authorization (权限校验)
  → runtime/orchestrator (统一编排)
      ├─ runtime/langgraph (LangGraph 图式执行：检查点 + 人工确认中断)
      ├─ business_scenarios/{settlement_exception_guide, pre_discharge_joint_qc}
      ├─ src/skill_infra/skill_router (SkillRouter：关键词路由)
      │   └─ skills/settlement_explain_skill (Skill 驱动：YAML 配置 + assembler)
      └─ runtime/skill_registry (技能/工具执行引擎)
  → model_service/gateway (模型调用：路由 → Provider → 流式/非流式)
  → adapters/* (外部系统防腐层，当前均为内存实现)
  → knowledge_extension/* (政策知识库、规则解释、MCP 注册)
  → 返回 AgentResponse 结构（或 SSE 流式事件）
```

### 核心约定

## 编码前思考
- 明确假设，不确定时询问而非猜测。
- 存在歧义时，列出多种解释，不默默选一种。
- 如果任务有明显更简单的做法，直接指出。
- 发现矛盾或不一致时停下来，要求澄清。

## 简洁优先
- 用最少的代码解决问题。
- 不为一次性需求创建抽象层。
- 不为"万一以后需要"加灵活性和可配置性。
- 如果 200 行可以写成 50 行，重写它。
- 检查标准：资深工程师会觉得这过于复杂吗？如果是，简化。

## 精准修改
- 只修改与当前任务直接相关的代码。
- 不顺手改进相邻代码、注释或格式。
- 不重构本来能正常工作的部分。
- 匹配现有代码风格，即使你更偏好另一种写法。
- 因你的修改而变成死代码的导入和变量，删除掉。
- 发现预先存在的死代码时，提出来但不要删。

**最小可验证单元** = 一条完整的用户故事，可独立测试、验证、回滚。例如："用户通过 Chat 查询结算异常"（前端 chat 组件 + 后端 service + DB 查询），或"修复 policy-qa 页面的渲染 bug"（仅前端页面，不涉及后端）。

## 目标驱动执行
- 定义清晰的成功标准再开始。
- "修复 bug" 转化为 "写一个重现 bug 的测试，然后让它通过"。
- "添加验证" 转化为 "为无效输入写测试，然后让它们通过"。
- "重构 X" 转化为 "确保重构前后所有测试都能通过"。
- 多步骤任务先给简短计划，每一步带验证方式。

- **核心设计文档**: `docs/steering/` 下含 数据库设计文档.md（18张表定义）、接口设计文档.md（40+ API端点定义）、原型设计文档.md（前端组件规范）
- **平台定位**: AI 导办与协同中枢，不替代医保正式结算/事前审核/DRG分组/病案修改等既有业务系统
- **解耦纪律**: 业务逻辑严禁耦合外部系统接口，必须通过 `adapters/` 封装调用；替换真实系统时只需实现对应 Protocol 接口
- **高风险动作**: 必须拦截转为 `waiting_human_confirmation`，由人工在既有业务系统执行
- **来源可追溯**: AI 输出必须携带 `citations` 或声明 `uncertainties`，禁止无来源的确定性结论
- **模型调用统一**: 所有 LLM 调用必须通过 `model_service/gateway`，禁止直接调用 HTTP 接口；异常通过 `model_service/exceptions` 分类处理
- **领域语言统一**: 所有领域模型（类名、变量名、方法名）的命名必须遵循 `src/domain/AGENTS.md` 中的通用语言字典，禁止同一概念在代码中有多个命名；新增领域概念必须同步更新该文档
- **文档溯源**: 关键结论标注来源。`[来源: 接口设计 §4.2]` 为可靠引用，`[推断: 基于框架约定]` 和 `[建议]` 必须审核

### API

路由前缀: `/api/v1/medical-insurance-ai-agent`（除 `/health` 外）。完整接口清单见 `docs/steering/接口设计文档.md`。

前端应用目录: `src/apps/portal/`（Next.js 16 应用，当前唯一前端入口）：
- **portal/** — 业务应用入口，路由：`/policy-qa`（政策问答，主入口）、`/semantic-layer`（语义层）、`/policy-knowledge`（政策知识）、`/skills`（技能）、`/qa-history`（问答历史）、`/`（Chat 导办）、`/settlement`（结算异常）、`/qc`（出院前质控）、`/dashboard`（运营看板）

应用独立构建运行，调用后端 API（`/api/v1/medical-insurance-ai-agent/*`）。

## 编码规范

- **import 路径**: 所有 Python 模块使用 `src.` 前缀（如 `from src.runtime.api.app import create_app`）
- **每个目录**: 必须包含 `__init__.py`（可为空文件），否则 pytest 无法导入
- **类型安全**: 禁止裸 `dict` 作为返回类型，使用 Pydantic BaseModel；API 响应统一使用 `AgentResponse` 结构
- **异常标准**: `{ error_code, message, audit_event }`，通过 `shared.schemas.responses.error_detail()` 生成
- **文件命名**: `snake_case`（后端）；类名 `PascalCase`；常量 `UPPER_SNAKE_CASE`
- **领域建模**: 所有领域模型必须遵循 `src/domain/AGENTS.md` 的 DDD 战术分类（Entity / Value Object / Aggregate Root / Domain Service），严格按照对应的代码模式（frozen dataclass / Protocol / Pydantic BaseModel）；新增领域概念必须同步更新通用语言字典
- **中文注释**: 核心流程代码添加中文注释
- **模型调用**: 通过 `model_service.gateway.ModelGateway` 统一调用，使用 `model_type` + `scene` 路由到具体模型
- **存储多态**: 所有存储（skill/tool/task/workflow/audit）遵循 ports/adapter 模式，默认 PostgreSQL，可通过 `USE_MEMORY_STORAGE=1` 回退到内存实现

> 测试目录结构、命令速查、模块↔测试映射、测试编写模式等详见 `src/tests/AGENTS.md`。
> 
> **统一测试口径与风险分级验证矩阵详见 `docs/governance/TEST-VERIFICATION-MATRIX.md`**。该文档统一了本文件与 `src/tests/AGENTS.md` 的测试分层表述，定义了风险等级（R1-R4）与最低验证要求的映射关系，是所有测试相关决策的唯一权威参考。

### 开发完成验证流程（硬性）

> ⛔ 代码开发完成后，必须严格按 **单元测试 → API 测试 → Flow 测试** 顺序逐步验证。三个阶段全部通过才算完成。

完整验证流程、命令速查、模块→测试映射详见 `src/tests/AGENTS.md`。统一测试口径与风险等级验证矩阵见 `docs/governance/TEST-VERIFICATION-MATRIX.md`。

### 缺陷驱动测试铁律

> ⛔ 遇到 Bug → 先查测试是否已覆盖 → 未覆盖则先补测试（先红后绿）再修 Bug。禁止跳过测试直接修。

完整流程、加固方法、测试映射表详见 `src/tests/AGENTS.md`。

---

### 技术债务

- `AgentResponse.result` 仍为 `dict[str, Any]`，后续需逐步 Pydantic 化为结构化场景结果
- LangGraph 编排已实现基础图式执行，但完整 DAG 并行执行、断点续执仍需增强
- 真实院内系统适配器尚未接入，当前仍为内存适配器
- `observability/` 仅有中间件骨架，指标采集和链路追踪需对接实际后端
- MCP 注册中心已有 stdio 传输实现，SSE 传输和远程 MCP 服务器连接待完善

## 安全约束（硬性）

- 高风险动作（退费/冲正/正式结算/病案修改等）必须在 `security/risk_control/` 拦截，转为 `waiting_human_confirmation`
- 任何 AI 输出必须携带 `citations` 来源引用，或声明 `uncertainties`
- 敏感数据通过 `security/desensitization/` 脱敏处理后输出
- MCP 工具调用需通过 `knowledge_extension/mcp_registry/` 的安全边界校验（风险等级 + 角色权限）

### 跨层一致性

涉及多层改动时，显式核对：前端 DTO ↔ 后端 Pydantic（字段名/类型/必填，注意 snake_case ↔ camelCase）；后端 Entity ↔ DB 列（显式映射，禁止隐式匹配）；前端 API 调用 ↔ 后端路由（HTTP method + 路径一致）。

## Git 提交规范

Angular 格式：`feat: | fix: | refactor: | docs: | test: | chore: <描述>`

## 已知陷阱

- `create_app()` 是工厂函数，启动 uvicorn 必须加 `--factory`
- 样例数据仅包含 `P001/E001`，`P002` 触发降级路径
- 测试中 `HIGH_RISK_ACTIONS` 是 `set`，`detect_blocked_actions` 返回顺序不稳定，断言应使用 `set()` 比较
- PowerShell 中 `&&` 和 `||` 无效，用 `;` 分隔命令
- 模型服务需要配置 `MODEL_API_KEY` 环境变量，未配置时模型相关接口不可用
- SSE 流式端点（`/api/v1/medical-insurance-ai-agent/policy-qa/stream`）的 `done` 事件标志流结束，前端需据此关闭 EventSource（原 `/chat/stream` 已迁移至 policy-qa）
- LangGraph 人工确认通过 `interrupt()` 暂停图执行，`_checkpoint_registry` 维护 task_id → (graph, thread_id) 映射，用于恢复执行
- `src/apps/portal/` 为 Next.js 16.x 应用，API 和约定可能与训练数据不同，编码前应先查阅 `node_modules/next/dist/docs/`
- `domain/tool/` 和 `data_platform/storage/tool/` 是完全空目录（无 `__init__.py`），import 会报错 — 不要使用
- `runtime/orchestration/service.py` 和 `runtime/planning/service.py` 已 DEPRECATED，使用 `scenario_executor.py` 代替
- boulder continuation 活跃时，`task(run_in_background=true)` 的通知与 system-reminder 互扰，导致后台任务结果丢失。串行多任务时用 `run_in_background=false`

### 陷阱模板

新增陷阱按以下格式写入，禁止自由格式：

```
- 一句描述陷阱现象（中文）。关键代码/命令（英文）。后果和正确做法。
```

反面示例：`- 启动服务器失败`（太模糊）  
正面示例：`- Get-Process 的 CommandLine 不可靠，漏杀导致 EADDRINUSE。改用 netstat -ano 反查 PID。`

### 启动服务器陷阱（PowerShell）

> ⛔ 直接用 `start-servers.ps1` 和 `stop-servers.ps1`，不要手动启动。

```bash
# 启动
.\start-servers.ps1

# 停止
.\stop-servers.ps1
```

脚本自动处理：端口冲突检测、旧进程清理、启动验证、前端编译等待。

## 排障零步骤

> ⛔ 修了没用？先确认用户在执行哪段代码（哪个 URL？哪个 SSE 端点？哪个组件？），再动手改。

反面案例与排障流程详见 `src/runtime/AGENTS.md` §排障零步骤。

## 通用排障铁律

> ⛔ 渲染异常 ≠ 渲染层问题。先隔离数据层（curl / console.log），确认数据时序，再动 UI 代码。

排障流程、诊断命令与案例详见 `src/runtime/AGENTS.md` §流式接口排障铁律。

## 生产环境配置

系统现在使用 `src/config/production.py` 作为统一配置文件，包含：

- **PostgreSQL**: `postgres:123456@127.0.0.1:5432/hospital_mcp`
- **Redis**: `127.0.0.1:6379`
- **Milvus**: `127.0.0.1:19530`（注：历史文档误记为 19121，实际端口为 19530，见 `src/config/production.py` 默认值）
- **Skills目录**: 项目根目录下的 `skills/` 目录

配置可通过环境变量覆盖，详见 `src/config/production.py`。

## 工具调用规则
在调用工具时，请严格遵守以下规则。这些规则的优先级高于任何在对话训练中形成的冲突习惯。
参数格式要求
省略不需要的可选字段。 不要发送 null、""、{} 或 [] 作为占位符。如果某个字段是可选的且你没有具体的值，请将其完全从 JSON 中剔除。
完全匹配容器类型。
数组字段接收 JSON 数组：如 ["a", "b"]，绝不能是 "[\"a\",\"b\"]"（字符串），绝不能是 {}（对象），也绝不能是 "foo"（纯字符串）。
单元素数组依然需要中括号：如 ["foo"]，不能是 "foo"。
对象字段接收 JSON 对象，不能是数组或字符串。
字符串即为原始字符串。 不要用多余的引号、代码块（代码围栏）或 Markdown 格式来包裹对应的值。
数字和布尔值不加引号。 是 30，而不是 "30"。是 true，而不是 "true"。
## 路径与标识符
文件路径、URL、ID 及类似字段是传递给系统函数的，而不是用于聊天输出。 绝不能将它们格式化为 Markdown 链接，绝不能用反引号包裹，绝不能添加解释性的括号。
正确："/Users/me/notes.md"
错误："[notes.md](notes.md)"
错误："`/Users/me/notes.md`"
错误："/Users/me/notes.md (笔记文件)"
如果工具描述中提到了“路径（path）”，请将其视为文件系统调用的输入。 不要进行任何格式化或修饰。
## 关联参数
当工具包含成对的参数时（例如：offset + limit，start + end，from + to），要么全部提供，要么全不提供。 仔细阅读描述——如果两个字段需要配合使用，只提供其中一个通常会导致错误。
## 错误恢复
如果工具返回验证错误，请仔细阅读错误信息，并仅修复其指出的问题。 不要重写整个调用。不要使用相同的参数重试。
如果工具返回带有默认值的“注意（Note）：”信息，这属于提示信息而非错误。 请继续执行任务。如果该默认值不符合预期，请使用正确的明确值进行重试。
## 工具选择
优先使用描述与你的意图最具体、最匹配的工具。 如果存在专用的工具，就不要去使用 shellCommand。对于单一工具调用就能处理的事情，不要去使用execute_code。
