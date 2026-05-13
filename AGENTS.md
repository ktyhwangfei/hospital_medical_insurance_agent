# AGENTS.md - 院端医保智能体系统

## 启动命令

```bash
# 启动开发服务器（--factory 必须指定，因为 create_app 是工厂函数）
uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory --reload

# 前端开发服务器（三个独立 Next.js 16 应用，各自独立运行）
cd src/apps/portal && npm run dev    # 业务应用入口（默认端口 3000）
cd src/apps/admin  && npm run dev    # 平台管理入口（默认端口 3001）
cd src/apps/embed  && npm run dev    # 嵌入式组件（默认端口 3002）

```
## 架构

完整架构定义见 `docs/steering/架构设计.md`，采用四层体系：SaaS 应用产品层 → PaaS 平台支撑层 → DaaS 数据与知识服务层 → 系统接入与基础设施层。

PaaS 层七个服务域是系统的核心能力分解：接入安全（gateway）、会话上下文（runtime/session+context）、智能编排（runtime/intent+planning+orchestration）、模型服务（model_service）、知识服务（knowledge_extension）、业务适配（adapters）、任务闭环（runtime/task_closure）。

当前已实现后端核心子集（`src/` 下）及三个前端应用（`src/apps/` 下）。

### 目录职责映射

Agent 编码时根据以下映射定位代码位置：

| 目录 | 职责 | 当前状态 |
|------|------|----------|
| `runtime/` | Agent 核心运行时：API 入口、会话上下文、意图识别、澄清、编排（含 LangGraph）、调度、响应（含 SSE 流式）、任务闭环、事件日志、技能注册 | 已实现（api/context/intent/clarification/planning/orchestration/scheduling/task_closure/runtime_state/event_log/capability_nodes/skill_registry/langgraph） |
| `business_scenarios/` | 医保业务场景：结算异常导办、出院前联合质控、MCP 工具调用 | 三个场景已实现 |
| `model_service/` | 模型服务网关：统一调用入口、路由策略、OpenAI 兼容 Provider、流式生成、异常分类、模型配置管理、Provider 管理 | 已实现（gateway/router/providers/openai_compatible/exceptions/models/ports） |
| `knowledge_extension/` | 知识与扩展：错误码知识库、RAG（含 Milvus 向量库端口）、规则解释、提示模板（含渲染引擎）、MCP 注册中心、扩展注册、知识资产（含切片管理→向量化）、申诉模板 | 已实现（knowledge/rag/rule_explanation/assets/extension_registry/mcp_registry + postgres CRUD） |
| `adapters/` | 外部系统防腐层：医保接口、事前审核、DRG/DIP、HIS、EMR、病案、收费 | 7 个内存适配器 + base 基类（models/service）+ ports 端口定义均已实现 |
| `data_platform/` | DaaS 数据底座：数据访问、存储端口、缓存（含 Redis）、持久化（含 PostgreSQL 方言/迁移/执行器）、Skill/MCP/向量存储 | 已实现（data_access/cache/persistence/storage 含 skill/mcp/postgresql/vector 子目录） |
| `domain/` | 领域模型：患者、医保、费用、审核风险、DRG/DIP、病案、任务、申诉、医嘱费用、技能 | 已实现（patient/insurance/task/common/drg_dip/medical_record/audit_risk/appeal/order_fee/skill） |
| `security/` | 安全围栏：权限、脱敏、风险控制、审计（含 PostgreSQL 持久化） | 已实现（authorization/desensitization/risk_control/audit 含 postgresql_store） |
| `config/` | 全局配置：安全策略、适配器配置、模型路由、模型服务、MCP 配置 | 已实现（security_policy/adapters/model_routing/model_service/mcp） |
| `observability/` | 可观测性：指标定义 + 中间件、链路追踪中间件 | 基础实现（metrics + tracing） |
| `shared/` | 共享基础：异常模型、响应契约、Schema 契约、技能加载器/注册表 | 已实现（exceptions/schemas/skills） |
| `gateway/` | 统一接入网关：API网关、渠道识别、认证鉴权、租户隔离、限流熔断、请求安全校验、接入日志 | 已实现（api_gateway/channel/auth/tenant/rate_limiter/request_guard/access_log） |
| `interaction/` | 多模态交互层：Chat对话、文件上传、语音交互、页面上下文、消息提醒、知识上传 | 已实现（chat/file/voice/page_context/notification/knowledge_upload） |
| `apps/` | SaaS 应用入口层：三个独立 Next.js 16 应用 — Portal（业务导办）、Admin（平台管理）、Embed（嵌入式组件） | 已实现（portal/ 含 chat/settlement/qc/dashboard 路由，admin/ 含 mcp/knowledge/model/skills 路由，embed/ 含嵌入式 chat widget） |
| `deploy/` | 部署配置：Docker、K8s、环境变量模板 | 已实现（docker/k8s/env） |

### 业务流向

```
runtime/api (FastAPI 路由)
  → runtime/intent (意图识别：关键词降级 / LLM 解析 / LangGraph 图式)
  → security/risk_control (高风险拦截)
  → security/authorization (权限校验)
  → runtime/orchestrator (统一编排)
      ├─ runtime/langgraph (LangGraph 图式执行：检查点 + 人工确认中断)
      ├─ business_scenarios/{settlement_exception_guide, pre_discharge_joint_qc, mcp_tool_invocation}
      └─ runtime/skill_registry (技能/工具执行引擎)
  → model_service/gateway (模型调用：路由 → Provider → 流式/非流式)
  → adapters/* (外部系统防腐层，当前均为内存实现)
  → knowledge_extension/* (错误码/政策知识库、RAG、规则解释、MCP 注册)
  → 返回 AgentResponse 结构（或 SSE 流式事件）
```

### 核心约定

- **核心设计文档**: `docs/steering/` 下含 数据库设计文档.md（18张表定义）、接口设计文档.md（40+ API端点定义）、原型设计文档.md（前端组件规范）
- **平台定位**: AI 导办与协同中枢，不替代医保正式结算/事前审核/DRG分组/病案修改等既有业务系统
- **解耦纪律**: 业务逻辑严禁耦合外部系统接口，必须通过 `adapters/` 封装调用；替换真实系统时只需实现对应 Protocol 接口
- **高风险动作**: 必须拦截转为 `waiting_human_confirmation`，由人工在既有业务系统执行
- **来源可追溯**: AI 输出必须携带 `citations` 或声明 `uncertainties`，禁止无来源的确定性结论
- **模型调用统一**: 所有 LLM 调用必须通过 `model_service/gateway`，禁止直接调用 HTTP 接口；异常通过 `model_service/exceptions` 分类处理
- **领域语言统一**: 所有领域模型（类名、变量名、方法名）的命名必须遵循 `src/domain/AGENTS.md` 中的通用语言字典，禁止同一概念在代码中有多个命名；新增领域概念必须同步更新该文档

### API

路由前缀: `/api/v1/medical-insurance-ai-agent`（除 `/health` 外）。完整接口清单见 `docs/steering/接口设计文档.md`。

前端应用目录: `src/apps/` 下三个独立 Next.js 16 应用：
- **portal/** — 业务应用入口，路由：`/`（Chat 导办）、`/settlement`（结算异常）、`/qc`（出院前质控）、`/dashboard`（运营看板）
- **admin/** — 平台管理入口，路由：`/`（管理首页）、`/mcp`（MCP 管理）、`/knowledge`（知识管理）、`/model`（模型测试）、`/skills`（技能管理）
- **embed/** — 嵌入式组件（嵌入 HIS/EMR），路由：`/`（精简版 Chat widget）

三个应用各自独立构建、独立运行，共享同一后端 API（`/api/v1/medical-insurance-ai-agent/*`）。

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

### 开发完成验证流程（硬性，不可跳过）

> **⛔ 核心规则：代码开发完成后，必须严格按 单元测试 → API 测试 → Flow 测试 的顺序逐步验证。三个阶段全部通过才算开发完成。任何阶段失败即视为开发未完成，禁止声称"开发完成"。**

**验证顺序（严格串行，前一步通过后才能执行下一步）：**

**第一步：单元测试（必须全部通过）**
```bash
# 根据修改的模块，运行对应的单元测试目录
python -m pytest src/tests/unit/<模块目录> -v

# 示例：
python -m pytest src/tests/unit/runtime/intent -v           # 修改了 intent 模块
python -m pytest src/tests/unit/model_service -v             # 修改了 model_service
python -m pytest src/tests/unit/knowledge_extension -v       # 修改了 knowledge_extension
python -m pytest src/tests/unit/security -v                  # 修改了 security
python -m pytest src/tests/unit/data_platform -v             # 修改了 data_platform
```

**第二步：API 端点测试（单元测试通过后执行，必须全部通过）**
```bash
# 根据修改的路由文件，运行对应的 API 测试
python -m pytest src/tests/integration/api/test_<路由名>.py -v

# 示例：
python -m pytest src/tests/integration/api/test_knowledge_routes.py -v   # 修改了 knowledge_routes.py
python -m pytest src/tests/integration/api/test_model_routes.py -v       # 修改了 model_routes.py
python -m pytest src/tests/integration/api/test_mcp_routes.py -v         # 修改了 mcp_routes.py
python -m pytest src/tests/integration/api/test_skill_routes_api.py -v   # 修改了 skill_routes.py
python -m pytest src/tests/integration/api/test_openapi_contract.py -v   # 修改了 routes.py
```

**第三步：Flow 流程测试（API 测试通过后执行，必须全部通过）**
```bash
python -m pytest src/tests/integration/flow -v -k "<场景关键词>"

# 示例：
python -m pytest src/tests/integration/flow -v -k "settlement"            # 结算异常相关
python -m pytest src/tests/integration/flow -v -k "human_confirmation"    # 人工确认相关
python -m pytest src/tests/integration/flow -v -k "langgraph"             # LangGraph 相关
```

**快速验证全部（适用于大范围修改）**：
```bash
python -m pytest src/tests/unit -v --tb=short -x              # 全部单元测试
python -m pytest src/tests/integration/api -v --tb=short       # 全部 API 测试
python -m pytest src/tests/integration/flow -v --tb=short      # 全部 Flow 测试
```

**硬性约束（违反即视为开发未完成）：**

1. **顺序不可颠倒**：必须先通过单元测试，再跑 API 测试，最后跑 Flow 测试。禁止跳过任何阶段。
2. **失败必须修复**：任何步骤中有测试失败，必须修复后从失败步骤重新开始验证。禁止跳过失败的测试、禁止用 `# noqa` / `@pytest.mark.skip` 跳过失败用例。
3. **全部通过才算完成**：三个阶段全部绿色通过后，才能标记开发任务为完成状态，才能进行代码提交。
4. **修复后需回归**：修复测试失败后，需重新运行该阶段全部测试（而非仅之前失败的用例），确保修复未引入新问题。

### 缺陷驱动的测试强化铁律（硬性）

> **⛔ 核心规则：遇到任何 Bug，必须从测试层面双向归因，杜绝同一类问题反复出现。**

**Bug 修复前必须执行的两步检查（不可跳过）：**

**第一步：检查当前测试是否已覆盖该 Bug 场景**
- 根据 Bug 涉及的模块路径，对照「模块 ↔ 测试映射」表找到对应测试目录
- 运行对应测试，确认是否存在覆盖该逻辑路径的用例
- 若为前端 Bug，同步检查 `src/tests/e2e/` 下的业务流程测试和冒烟测试

**第二步 A：若测试未覆盖 → 先补测试，再修 Bug**
1. 在对应模块的测试文件中新增用例，精确复现 Bug 的触发条件与输入
2. 确认新增的测试用例**当前状态为 FAIL**（红）——证明测试能有效捕获该 Bug
3. 修复业务代码，使测试通过（绿）
4. 运行该模块全量测试（单元 → API → Flow 按顺序），确保修复未引入回归

**第二步 B：若测试已覆盖但未能发现 → 排查测试为何失效，并加固**
1. 检查已覆盖测试的断言是否不够精确（如仅断言 `status_code == 200`，未校验响应体关键字段）
2. 检查 Mock/Stub 是否过度宽松导致真实异常被屏蔽（如异常被 `mock.return_value` 吞没）
3. 加固测试用例：
   - 增加边界条件与异常路径的断言
   - 减少过度 Mock，优先使用集成级验证
   - 对关键字段增加类型与值域校验
4. 确认加固后的测试能暴露当前 Bug（先红后绿，同上）

**硬性约束：**
- **禁止跳过上述步骤直接修 Bug**——跳步修复视为流程违规
- Bug 修复的 commit message 中必须注明覆盖该 Bug 的测试文件路径
- 同一类型 Bug 出现第二次时，视为测试体系缺陷，需在团队复盘会上讨论加固方案

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

## Git 提交规范

Angular 格式：`feat: | fix: | refactor: | docs: | test: | chore: <描述>`

## 已知陷阱

- `create_app()` 是工厂函数，启动 uvicorn 必须加 `--factory`
- 样例数据仅包含 `P001/E001`，`P002` 触发降级路径
- 测试中 `HIGH_RISK_ACTIONS` 是 `set`，`detect_blocked_actions` 返回顺序不稳定，断言应使用 `set()` 比较
- PowerShell 中 `&&` 和 `||` 无效，用 `;` 分隔命令
- 模型服务需要配置 `MODEL_API_KEY` 环境变量，未配置时 `/model-test` 返回 503
- SSE 流式端点（`/chat/stream`、`/model-test/stream`）的 `done` 事件标志流结束，前端需据此关闭 EventSource
- LangGraph 人工确认通过 `interrupt()` 暂停图执行，`_checkpoint_registry` 维护 task_id → (graph, thread_id) 映射，用于恢复执行
- `src/apps/` 下的三个 Next.js 应用版本均为 16.x，API 和约定可能与训练数据不同，编码前应先查阅 `node_modules/next/dist/docs/`
- `domain/tool/` 和 `data_platform/storage/tool/` 是完全空目录（无 `__init__.py`），import 会报错 — 不要使用
- `runtime/orchestration/service.py` 和 `runtime/planning/service.py` 已 DEPRECATED，使用 `scenario_executor.py` 代替

## 生产环境配置

系统现在使用 `src/config/production.py` 作为统一配置文件，包含：

- **PostgreSQL**: `postgres:123456@127.0.0.1:5432/hospital_mcp`
- **Redis**: `127.0.0.1:6379`
- **Milvus**: `127.0.0.1:19121`
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
