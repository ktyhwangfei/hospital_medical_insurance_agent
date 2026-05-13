# 架构改进计划：医保 AI 平台演进（修订版 v2）

## TL;DR

> **目标**: 基于 Datawhale 框架实践评估，将当前 MVP 架构演进为生产级平台
> 
> **核心策略**: 保留 LangGraph 执行核心，优先解决运行时治理和状态持久化，消息驱动与多 Agent 按成熟度渐进引入
> 
> **关键交付**:
> - 阶段一（运行时治理）: 适配器 Port/Protocol、RuntimeOrchestrator、统一执行引擎、依赖注入
> - 阶段二（状态与可观测性）: 领域层补齐、PostgreSQL 持久化、OpenTelemetry 追踪、Prometheus 指标
> - 阶段三（能力扩展）: 事件记录增强、RAG 向量检索、可治理业务能力节点、K8s 部署
> 
> **Estimated Effort**: Large（成熟度驱动，非时间驱动）
> **Parallel Execution**: YES - 每阶段 5-8 个并行任务
> **Critical Path**: 适配器 Port -> RuntimeOrchestrator -> 统一执行引擎 -> 状态持久化 -> 可观测性

---

## Context

### 原始请求
基于 Datawhale hello-agents 第六章框架开发实践，评估当前医保 AI 平台架构合理性，并制定可执行的改进计划。

### 评估结论（修订版）
当前架构方向正确（LangGraph 状态机适合医保场景），但在运行时治理和工程化实践方面存在差距：
- 🔴 **运行时治理薄弱**: routes.py 上帝模块、双重执行引擎、编排职责不清
- 🔴 **状态完全内存化**: workflow/task/audit 重启丢失，无法支撑生产
- 🟡 **适配器契约不完整**: 已有统一返回结果模型（AdapterCallResult），但缺少面向业务能力的 Port/Protocol
- 🟡 **领域层不完整**: 仅实现 patient/insurance/task/common，缺失 audit_risk、drg_dip 等
- 🟡 **可观测性不足**: 仅审计日志，缺少链路追踪和性能指标
- 🟢 **LangGraph 选择正确**: 状态机精确控制适合医保严格流程
- 🟢 **适配器防腐层设计优秀**: 统一返回模型和错误处理机制已建立
- 🟢 **安全围栏完善**: 高风险拦截、人工确认、审计留痕机制到位

### 关键修正（基于用户反馈）

**修正 1: 适配器协议表述**
- 原表述: "无适配器协议/契约"
- 修正: "已有统一适配器返回结果模型（AdapterCallResult、AdapterCallContext、AdapterCallStatus），但缺少面向业务能力的 Port/Protocol 契约"
- 影响: 优先级从 🔴 降为 🟡，任务从"从零定义"改为"补充 Port 层"

**修正 2: 消息驱动优先级**
- 原表述: "消息驱动缺失"列为 🔴 债务，阶段二引入 Redis Pub/Sub
- 修正: "消息驱动"降为 🟡 债务，短期通过领域事件和运行时事件记录增强可观测性，中期在任务闭环、异步通知场景引入消息队列
- 影响: 阶段二移除"事件总线"和"核心流程事件化改造"任务，改为"事件记录与审计增强"

**修正 3: 多智能体协作表述**
- 原表述: "单 Agent 限制"是债务，需 A2A、Agent 注册发现
- 修正: "当前不缺自治多智能体，缺的是统一编排下的可注册、可治理业务能力节点"。多智能体作为中长期能力，但不应在 MVP 阶段优先
- 影响: 阶段三移除"Agent 注册发现"、"多 Agent 协调器"、"A2A 协议"任务，改为"可治理业务能力节点"

**修正 4: 执行引擎统一策略**
- 原表述: "统一为 LangGraph 执行模型"
- 修正: "先抽象 RuntimeOrchestrator，由 RuntimeOrchestrator 接管 process_chat_request() 中的业务流程，LangGraph 作为场景工作流执行器，Skill 和 MCP 作为能力节点接入图"
- 影响: 增加 Task 9.1 "设计 RuntimeOrchestrator 抽象"，细化 Task 9 和 Task 10

**修正 5: 阶段规划改为成熟度驱动**
- 原表述: "阶段一 2个月、阶段二 2个月、阶段三 2个月"
- 修正: "成熟度驱动：每阶段有明确的准入条件和退出标准，不预设时间"
- 影响: 每个阶段增加"准入条件"和"退出标准"，移除时间承诺

---

## Work Objectives

### Core Objective
将当前 MVP 架构演进为生产级平台，优先解决运行时治理和状态持久化，按成熟度渐进引入消息驱动与业务能力节点扩展。

### Concrete Deliverables
- **阶段一（运行时治理）**:
  - `src/adapters/ports/` - 适配器 Port/Protocol 定义
  - `src/runtime/orchestrator.py` - RuntimeOrchestrator 抽象
  - `src/runtime/orchestration/langgraph_executor.py` - LangGraph 场景工作流执行器
  - `src/runtime/dependencies.py` - FastAPI Depends 依赖注入
  - `src/runtime/api/routes.py` - 精简为 HTTP 层（< 200 行）
- **阶段二（状态与可观测性）**:
  - `src/domain/{audit_risk,drg_dip,medical_record,appeal,order_fee}/` - 完整领域模型
  - `src/data_platform/storage/postgresql/` - PostgreSQL 持久化实现
  - `src/runtime/runtime_state/postgresql_store.py` - Workflow 状态持久化
  - `src/runtime/task_closure/postgresql_store.py` - Task 状态持久化
  - `src/security/audit/postgresql_store.py` - Audit 日志持久化
  - `src/observability/tracing/` - OpenTelemetry 链路追踪
  - `src/observability/metrics/` - Prometheus 指标采集
- **阶段三（能力扩展）**:
  - `src/runtime/event_log/` - 运行时事件记录（非消息总线）
  - `src/knowledge_extension/rag/milvus/` - 向量检索实现
  - `src/runtime/capability_nodes/` - 可治理业务能力节点注册
  - `deploy/k8s/` - Kubernetes 部署配置

### Definition of Done
- [ ] 所有适配器实现统一 Port/Protocol，可通过配置切换实现
- [ ] RuntimeOrchestrator 接管所有业务流程编排
- [ ] 单一执行入口：RuntimeOrchestrator -> LangGraph 场景执行器
- [ ] 状态持久化：重启后 workflow/task/audit 不丢失
- [ ] 可观测性：链路追踪、性能指标、审计事件记录
- [ ] 领域层覆盖医保全部核心业务对象
- [ ] 可治理业务能力节点可注册、可发现

### Must Have
- RuntimeOrchestrator 抽象与实现
- 适配器 Port/Protocol 契约
- 统一执行引擎（LangGraph 场景执行器）
- 状态持久化（PostgreSQL）
- 可观测性基础（追踪 + 指标）

### Must NOT Have (Guardrails)
- 不推倒重来，保留现有 LangGraph 核心
- 不引入全局消息总线（仅局部事件记录）
- 不实现自治多 Agent 协作（仅可治理业务能力节点）
- 不牺牲可审计性换取灵活性
- 不预设阶段时间，按成熟度准入/退出

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES (pytest)
- **Automated tests**: YES (Tests-after)
- **Framework**: pytest
- **Agent-Executed QA**: 每个任务包含具体 QA 场景

### QA Policy
每个任务 MUST 包含 agent-executed QA scenarios：
- **Backend/API**: Bash (curl) - 发送请求，断言状态码和响应字段
- **Library/Module**: Bash (pytest) - 运行测试，断言通过率
- **Integration**: Bash (curl + pytest) - 端到端验证

---

## Execution Strategy

### 成熟度驱动阶段模型

```
阶段一：运行时治理（准入：MVP 可运行；退出：编排职责清晰、可测试）
├── 任务 1: 定义适配器 Port/Protocol
├── 任务 2: 设计 RuntimeOrchestrator 抽象
├── 任务 3: 重构适配器实现 Port
├── 任务 4: 引入 FastAPI 依赖注入
├── 任务 5: 实现 LangGraph 场景执行器
├── 任务 6: 统一执行入口（弃用旧版路径）
├── 任务 7: 重构 routes.py 解耦
└── 任务 8: 技能引擎适配新协议

阶段二：状态与可观测性（准入：阶段一完成；退出：重启不丢状态、可监控）
├── 任务 9: 补齐 audit_risk 领域模型
├── 任务 10: 补齐 drg_dip 领域模型
├── 任务 11: 补齐 medical_record 领域模型
├── 任务 12: 补齐 appeal 领域模型
├── 任务 13: 补齐 order_fee 领域模型
├── 任务 14: PostgreSQL 连接与模型
├── 任务 15: Workflow 状态持久化
├── 任务 16: Task 状态持久化
├── 任务 17: Audit 日志持久化
├── 任务 18: LangGraph checkpoint 持久化
├── 任务 19: OpenTelemetry 链路追踪
├── 任务 20: Prometheus 指标采集
└── 任务 21: 运行时事件记录增强

阶段三：能力扩展（准入：阶段二完成；退出：可水平扩展、知识检索可用）
├── 任务 22: Milvus 向量检索
├── 任务 23: RAG 完整链路
├── 任务 24: 可治理业务能力节点
├── 任务 25: K8s 部署配置
└── 任务 26: 安全策略配置化

最终验证（所有阶段完成后）
├── F1: 架构合规审计
├── F2: 代码质量审查
├── F3: 集成测试验证
└── F4: 性能基准测试
```

### 并行执行波次

```
Wave 1 (Start Immediately - 阶段一基础):
├── Task 1: 定义适配器 Port/Protocol [quick]
├── Task 2: 设计 RuntimeOrchestrator 抽象 [deep]
├── Task 4: 引入 FastAPI 依赖注入 [quick]
└── Task 7: 重构 routes.py 解耦 [unspecified-high]

Wave 2 (After Wave 1 - 阶段一核心):
├── Task 3: 重构适配器实现 Port (depends: 1) [unspecified-high]
├── Task 5: 实现 LangGraph 场景执行器 (depends: 2) [deep]
├── Task 6: 统一执行入口 (depends: 5) [quick]
└── Task 8: 技能引擎适配 (depends: 3, 4) [unspecified-high]

Wave 3 (After Wave 2 - 阶段二基础):
├── Task 9: 补齐 audit_risk 领域模型 [quick]
├── Task 10: 补齐 drg_dip 领域模型 [quick]
├── Task 11: 补齐 medical_record 领域模型 [quick]
├── Task 12: 补齐 appeal 领域模型 [quick]
├── Task 13: 补齐 order_fee 领域模型 [quick]
└── Task 14: PostgreSQL 连接与模型 [unspecified-high]

Wave 4 (After Wave 3 - 阶段二核心):
├── Task 15: Workflow 状态持久化 (depends: 14) [deep]
├── Task 16: Task 状态持久化 (depends: 14) [unspecified-high]
├── Task 17: Audit 日志持久化 (depends: 14) [unspecified-high]
├── Task 18: LangGraph checkpoint 持久化 (depends: 14) [deep]
├── Task 19: OpenTelemetry 链路追踪 (depends: 15-18) [unspecified-high]
├── Task 20: Prometheus 指标采集 (depends: 15-18) [unspecified-high]
└── Task 21: 运行时事件记录增强 (depends: 19-20) [unspecified-high]

Wave 5 (After Wave 4 - 阶段三):
├── Task 22: Milvus 向量检索 [unspecified-high]
├── Task 23: RAG 完整链路 (depends: 22) [unspecified-high]
├── Task 24: 可治理业务能力节点 [deep]
├── Task 25: K8s 部署配置 [quick]
└── Task 26: 安全策略配置化 [unspecified-high]

Wave FINAL (After ALL tasks):
├── F1: 架构合规审计 (oracle)
├── F2: 代码质量审查 (unspecified-high)
├── F3: 集成测试验证 (unspecified-high)
└── F4: 性能基准测试 (deep)
-> Present results -> Get explicit user okay

Critical Path: Task 1 -> Task 3 -> Task 5 -> Task 6 -> Task 14 -> Task 15-18 -> Task 19-21 -> F1-F4
```

---

## TODOs

- [x] 1. **定义适配器 Port/Protocol**

  **What to do**:
  - 在 `src/adapters/ports/` 创建 Port 定义文件
  - 为每种业务能力定义 Protocol：`InsuranceInterfacePort`、`BillingPort`、`HisPort`、`EmrPort`、`PreAuditPort`、`DrgDipPort`、`MedicalRecordPort`
  - 每个 Port 声明标准方法签名（如 `query_transaction(patient_id, encounter_id) -> AdapterCallResult`）
  - 说明：项目已有统一返回结果模型（AdapterCallResult、AdapterCallContext、AdapterCallStatus），本任务补充的是面向业务能力的调用契约层

  **Must NOT do**:
  - 不修改现有 `in_memory.py` 实现（留到 Task 3）
  - 不重复定义返回结果模型（复用现有 AdapterCallResult）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - **Reason**: 纯接口定义，无业务逻辑

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 4, 7)
  - **Blocks**: Task 3, Task 8
  - **Blocked By**: None

  **References**:
  - `src/adapters/base/models.py:AdapterCallResult` - 已有返回结果契约
  - `src/adapters/base/models.py:AdapterCallContext` - 调用上下文契约
  - `src/adapters/insurance_interface/in_memory.py` - 当前实现参考
  - Python Protocol: https://docs.python.org/3/library/typing.html#typing.Protocol

  **Acceptance Criteria**:
  - [ ] `src/adapters/ports/` 目录存在且包含所有 Port 定义
  - [ ] 每个 Port 有完整的方法签名和文档字符串
  - [ ] pytest 可通过 `isinstance(adapter, Port)` 验证现有适配器

  **QA Scenarios**:
  ```
  Scenario: Port 定义完整性验证
    Tool: Bash (pytest)
    Preconditions: 代码已拉取
    Steps:
      1. 运行 `python -m pytest src/tests/unit/adapters/test_ports.py -v`
      2. 断言所有 Port 可被正确导入
      3. 断言现有适配器实例可通过 isinstance 检查
    Expected Result: 所有测试通过，覆盖率 100%
    Evidence: .sisyphus/evidence/task-1-port-validation.log
  ```

  **Commit**: YES
  - Message: `feat(adapters): define business capability ports`
  - Files: `src/adapters/ports/*.py`

- [x] 2. **设计 RuntimeOrchestrator 抽象**

  **What to do**:
  - 创建 `src/runtime/orchestrator.py`
  - 设计 `RuntimeOrchestrator` 类，明确职责边界：
    - 接收请求并构建 RuntimeContext
    - 调用安全校验（权限、风控）
    - 识别意图并选择执行策略
    - 委托给场景执行器（LangGraph）或技能引擎
    - 组装 AgentResponse
  - 定义执行策略接口：`ScenarioExecutor`、`SkillExecutor`
  - 当前 process_chat_request() 中的多类执行入口需被 Orchestrator 统一接管

  **Must NOT do**:
  - 不实现具体执行逻辑（仅抽象和接口）
  - 不修改 routes.py（留到 Task 7）

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 5, Task 6, Task 7
  - **Blocked By**: None

  **References**:
  - `src/runtime/api/routes.py:process_chat_request()` - 当前编排逻辑
  - `src/runtime/context/service.py` - 上下文构建
  - `src/runtime/intent/service.py` - 意图识别
  - `src/security/risk_control/service.py` - 风控校验
  - `src/security/authorization/service.py` - 权限校验

  **Acceptance Criteria**:
  - [ ] `RuntimeOrchestrator` 类定义完成
  - [ ] 职责边界文档清晰
  - [ ] 执行策略接口定义完成

  **QA Scenarios**:
  ```
  Scenario: Orchestrator 抽象验证
    Tool: Bash (python)
    Steps:
      1. 运行 `python -c "from src.runtime.orchestrator import RuntimeOrchestrator; print(RuntimeOrchestrator)"`
      2. 断言类可实例化
      3. 断言包含核心方法（execute_request、validate_security、select_executor）
    Expected Result: 导入成功，接口完整
    Evidence: .sisyphus/evidence/task-2-orchestrator-design.log
  ```

  **Commit**: YES
  - Message: `feat(runtime): design RuntimeOrchestrator abstraction`

- [x] 3. **重构适配器实现 Port**

  **What to do**:
  - 修改所有 `src/adapters/*/in_memory.py` 显式实现对应 Port
  - 添加 `__init__.py` 导出适配器类
  - 更新导入路径
  - 保持现有行为不变

  **Must NOT do**:
  - 不修改业务逻辑
  - 不修改返回结果模型

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: NO (需逐个验证)
  - **Blocked By**: Task 1
  - **Blocks**: Task 8

  **References**:
  - `src/adapters/ports/*.py` - Port 定义
  - `src/adapters/*/in_memory.py` - 当前实现

  **Acceptance Criteria**:
  - [ ] 所有适配器显式实现 Port
  - [ ] `isinstance(adapter, Port)` 返回 True
  - [ ] 现有测试仍通过

  **QA Scenarios**:
  ```
  Scenario: 适配器 Port 实现验证
    Tool: Bash (pytest)
    Steps:
      1. 运行 `python -m pytest src/tests/unit/adapters/ -v`
      2. 断言所有适配器通过 isinstance 检查
      3. 断言现有集成测试仍通过
    Expected Result: 所有测试通过
    Evidence: .sisyphus/evidence/task-3-adapter-port-impl.log
  ```

  **Commit**: YES
  - Message: `refactor(adapters): implement business capability ports`

- [x] 4. **引入 FastAPI 依赖注入**

  **What to do**:
  - 创建 `src/runtime/dependencies.py`
  - 定义依赖提供函数：`get_insurance_adapter()`、`get_billing_adapter()` 等
  - 使用 FastAPI `Depends` 注入到路由中
  - 支持通过环境变量切换实现（memory/real）
  - 创建 `src/config/adapters.py` 配置适配器实现类型

  **Must NOT do**:
  - 不修改业务逻辑
  - 不一次性修改所有路由（逐步迁移）

  **Recommended Agent Profile**:
  - **Category**: `quick`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 8
  - **Blocked By**: None

  **References**:
  - `src/runtime/api/routes.py` - 当前路由实现
  - `src/runtime/api/app.py` - FastAPI 应用工厂
  - FastAPI Dependencies: https://fastapi.tiangolo.com/tutorial/dependencies/

  **Acceptance Criteria**:
  - [ ] `src/runtime/dependencies.py` 存在且包含所有适配器依赖函数
  - [ ] `src/config/adapters.py` 支持配置切换实现类型
  - [ ] 至少一个路由已使用 Depends 注入适配器

  **QA Scenarios**:
  ```
  Scenario: 依赖注入验证
    Tool: Bash (pytest)
    Steps:
      1. 运行 `python -m pytest src/tests/unit/runtime/test_dependencies.py -v`
      2. 断言依赖函数可正确返回适配器实例
      3. 断言切换配置后返回不同实现
    Expected Result: 测试通过
    Evidence: .sisyphus/evidence/task-4-dependency-injection.log
  ```

  **Commit**: YES
  - Message: `feat(runtime): introduce FastAPI dependency injection`

- [x] 5. **实现 LangGraph 场景执行器**

  **What to do**:
  - 创建 `src/runtime/orchestration/langgraph_executor.py`
  - 实现 `LangGraphScenarioExecutor` 类（实现 ScenarioExecutor 接口）
  - 统一加载和执行场景图（settlement_exception、pre_discharge_qc）
  - 集成 checkpoint 持久化接口（先使用 MemorySaver，后续替换）
  - 实现统一的错误处理和重试机制
  - Skill 和 MCP 作为能力节点接入图，而非独立绕行

  **Must NOT do**:
  - 不删除现有 LangGraph 图定义
  - 不修改图的节点逻辑

  **Recommended Agent Profile**:
  - **Category**: `deep`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 2
  - **Blocks**: Task 6

  **References**:
  - `src/runtime/langgraph/settlement_exception.py` - 结算异常图
  - `src/runtime/langgraph/pre_discharge_qc.py` - 出院质控图
  - `src/runtime/api/routes.py:_try_langgraph_execution()` - 当前执行逻辑

  **Acceptance Criteria**:
  - [ ] `LangGraphScenarioExecutor` 可执行所有现有场景图
  - [ ] 支持通过场景名称动态选择图
  - [ ] Skill/MCP 可作为节点接入图

  **QA Scenarios**:
  ```
  Scenario: 场景执行器验证
    Tool: Bash (pytest)
    Steps:
      1. 运行 `python -m pytest src/tests/langgraph/ -v`
      2. 断言所有场景可通过执行器运行
      3. 断言返回正确 AgentResponse 结构
    Expected Result: 所有测试通过
    Evidence: .sisyphus/evidence/task-5-scenario-executor.log
  ```

  **Commit**: YES
  - Message: `feat(runtime): implement LangGraph scenario executor`

- [x] 6. **统一执行入口（弃用旧版路径）**

  **What to do**:
  - 修改 `RuntimeOrchestrator` 使用 `LangGraphScenarioExecutor`
  - 标记 `src/runtime/orchestration/service.py` 为弃用
  - 标记 `src/runtime/planning/service.py` 为弃用
  - 将旧版路径调用迁移到场景执行器
  - 更新 `routes.py` 中的回退逻辑

  **Must NOT do**:
  - 不删除旧版文件（保留向后兼容）
  - 不修改旧版文件内容

  **Recommended Agent Profile**:
  - **Category**: `quick`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 5
  - **Blocks**: None

  **References**:
  - `src/runtime/orchestration/service.py` - 旧版执行器
  - `src/runtime/planning/service.py` - 旧版规划器
  - `src/runtime/api/routes.py` - 回退逻辑

  **Acceptance Criteria**:
  - [ ] 旧版文件添加弃用标记
  - [ ] 所有场景通过场景执行器执行
  - [ ] 无 DeprecationWarning 之外的警告

  **QA Scenarios**:
  ```
  Scenario: 统一执行入口验证
    Tool: Bash (pytest)
    Steps:
      1. 运行 `python -m pytest src/tests/e2e/ -v`
      2. 断言无异常警告
      3. 断言所有场景返回正确结果
    Expected Result: 测试通过，无异常
    Evidence: .sisyphus/evidence/task-6-unified-execution.log
  ```

  **Commit**: YES
  - Message: `chore(runtime): deprecate legacy execution paths`

- [x] 7. **重构 routes.py 解耦**

  **What to do**:
  - 将 `process_chat_request()` 中的编排逻辑迁移到 `RuntimeOrchestrator`
  - 将安全校验提取为 FastAPI 依赖（`verify_security()`）
  - `routes.py` 仅保留 HTTP 层逻辑（参数解析、响应封装）
  - 目标：`routes.py` 行数 < 200 行

  **Must NOT do**:
  - 不修改 API 接口契约
  - 不修改业务逻辑

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/runtime/api/routes.py` - 当前上帝模块
  - `src/runtime/dependencies.py` - 依赖注入
  - `src/runtime/orchestrator.py` - RuntimeOrchestrator

  **Acceptance Criteria**:
  - [ ] `routes.py` 行数 < 200 行
  - [ ] `RuntimeOrchestrator` 包含核心编排逻辑
  - [ ] 安全校验为独立依赖函数

  **QA Scenarios**:
  ```
  Scenario: 路由解耦验证
    Tool: Bash (pytest + curl)
    Steps:
      1. 运行 `python -m pytest src/tests/e2e/ -v`
      2. 断言 routes.py 行数 < 200
      3. 断言所有 API 端点正常工作
    Expected Result: 测试通过，routes.py 精简
    Evidence: .sisyphus/evidence/task-7-routes-decoupling.log
  ```

  **Commit**: YES
  - Message: `refactor(api): decouple routes.py into orchestrator`

- [x] 8. **技能引擎适配新协议**

  **What to do**:
  - 修改 `src/runtime/skill_registry/engine.py`
  - 使用依赖注入获取适配器
  - 适配器调用通过 Port 接口
  - 保持 SkillExecutionEngine 对外接口不变

  **Must NOT do**:
  - 不修改 Skill/Tool 领域模型
  - 不修改技能执行顺序逻辑

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Tasks 3, 4
  - **Blocks**: None

  **References**:
  - `src/runtime/skill_registry/engine.py` - 当前实现
  - `src/adapters/ports/*.py` - Port 定义
  - `src/runtime/dependencies.py` - 依赖注入

  **Acceptance Criteria**:
  - [ ] SkillExecutionEngine 使用注入的适配器
  - [ ] 所有技能测试通过
  - [ ] 支持 @-mention 技能调用

  **QA Scenarios**:
  ```
  Scenario: 技能引擎协议适配验证
    Tool: Bash (pytest)
    Steps:
      1. 运行 `python -m pytest src/tests/unit/runtime/skill_registry/ -v`
      2. 运行 `python -m pytest src/tests/e2e/test_settlement_exception.py -v`
      3. 断言技能执行结果正确
    Expected Result: 所有测试通过
    Evidence: .sisyphus/evidence/task-8-skill-engine-port.log
  ```

  **Commit**: YES
  - Message: `refactor(skill): adapt skill engine to adapter ports`

- [x] 9. **补齐 audit_risk 领域模型**

  **What to do**:
  - 创建 `src/domain/audit_risk/__init__.py`
  - 创建 `src/domain/audit_risk/models.py`
  - 定义核心领域对象：`AuditResult`、`RiskFlag`、`RuleHit`、`ComplianceScore`
  - 使用 frozen dataclass（与现有 domain 风格一致）

  **Must NOT do**:
  - 不引入 Pydantic（保持 dataclass）
  - 不实现业务逻辑

  **Recommended Agent Profile**:
  - **Category**: `quick`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 14
  - **Blocked By**: None

  **References**:
  - `src/domain/patient/models.py` - 现有领域模型风格
  - `src/adapters/pre_audit/in_memory.py` - 预审核数据字段

  **Acceptance Criteria**:
  - [ ] `src/domain/audit_risk/models.py` 存在且包含核心对象
  - [ ] 可通过 `from src.domain.audit_risk import AuditResult` 导入

  **QA Scenarios**:
  ```
  Scenario: 领域模型导入验证
    Tool: Bash (python)
    Steps:
      1. 运行 `python -c "from src.domain.audit_risk import AuditResult; print(AuditResult)"`
      2. 断言无 ImportError
    Expected Result: 导入成功
    Evidence: .sisyphus/evidence/task-9-audit-risk-model.log
  ```

  **Commit**: YES
  - Message: `feat(domain): add audit_risk domain models`

- [x] 10. **补齐 drg_dip 领域模型**

  **What to do**:
  - 创建 `src/domain/drg_dip/__init__.py`
  - 创建 `src/domain/drg_dip/models.py`
  - 定义核心领域对象：`DrgGroupResult`、`DipGroupResult`、`PaymentRate`、`ProfitLoss`

  **Must NOT do**:
  - 不实现分组算法

  **Recommended Agent Profile**:
  - **Category**: `quick`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 14
  - **Blocked By**: None

  **References**:
  - `src/adapters/drg_dip/in_memory.py` - DRG/DIP 数据字段

  **Commit**: YES
  - Message: `feat(domain): add drg_dip domain models`

- [x] 11. **补齐 medical_record 领域模型**

  **What to do**:
  - 创建 `src/domain/medical_record/__init__.py`
  - 创建 `src/domain/medical_record/models.py`
  - 定义核心领域对象：`MedicalRecordHomepage`、`Diagnosis`、`Surgery`、`Coding`

  **Must NOT do**:
  - 不实现编码校验逻辑

  **Recommended Agent Profile**:
  - **Category**: `quick`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 14
  - **Blocked By**: None

  **References**:
  - `src/adapters/medical_record/in_memory.py` - 病案数据字段

  **Commit**: YES
  - Message: `feat(domain): add medical_record domain models`

- [x] 12. **补齐 appeal 领域模型**

  **What to do**:
  - 创建 `src/domain/appeal/__init__.py`
  - 创建 `src/domain/appeal/models.py`
  - 定义核心领域对象：`DenialRecord`、`AppealCase`、`Evidence`、`AppealMaterial`

  **Must NOT do**:
  - 不实现申诉流程逻辑

  **Recommended Agent Profile**:
  - **Category**: `quick`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 14
  - **Blocked By**: None

  **References**:
  - `docs/steering/架构设计.md` - 拒付申诉场景描述
  - `src/business_scenarios/` - 业务场景参考

  **Commit**: YES
  - Message: `feat(domain): add appeal domain models`

- [x] 13. **补齐 order_fee 领域模型**

  **What to do**:
  - 创建 `src/domain/order_fee/__init__.py`
  - 创建 `src/domain/order_fee/models.py`
  - 定义核心领域对象：`Order`、`FeeItem`、`Drug`、`Consumable`、`Treatment`

  **Must NOT do**:
  - 不实现费用计算逻辑

  **Recommended Agent Profile**:
  - **Category**: `quick`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 14
  - **Blocked By**: None

  **References**:
  - `src/adapters/his/in_memory.py` - 医嘱数据字段
  - `src/adapters/billing/in_memory.py` - 费用数据字段

  **Commit**: YES
  - Message: `feat(domain): add order_fee domain models`

- [x] 14. **PostgreSQL 连接与模型**

  **What to do**:
  - 创建 `src/data_platform/storage/postgresql/__init__.py`
  - 创建 `src/data_platform/storage/postgresql/client.py`
  - 创建 `src/data_platform/storage/postgresql/models.py`
  - 定义表结构：workflow、task、audit_log、session
  - 实现连接池和事务管理
  - 添加 Alembic 迁移脚本

  **Must NOT do**:
  - 不替换现有内存存储
  - 不修改业务逻辑

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: Tasks 15-18
  - **Blocked By**: Tasks 9-13

  **References**:
  - `src/data_platform/storage/` - 现有存储抽象
  - SQLAlchemy: https://docs.sqlalchemy.org/
  - Alembic: https://alembic.sqlalchemy.org/

  **Acceptance Criteria**:
  - [ ] PostgreSQL 客户端可连接数据库
  - [ ] 所有表结构可通过 Alembic 迁移创建
  - [ ] 支持连接池和事务

  **QA Scenarios**:
  ```
  Scenario: PostgreSQL 连接验证
    Tool: Bash (python)
    Steps:
      1. 运行 `python -c "from src.data_platform.storage.postgresql import client; print(client.test_connection())"`
      2. 运行 `alembic upgrade head`
      3. 断言数据库表已创建
    Expected Result: 连接成功，表结构正确
    Evidence: .sisyphus/evidence/task-14-postgresql.log
  ```

  **Commit**: YES
  - Message: `feat(storage): add PostgreSQL storage implementation`

- [x] 15. **Workflow 状态持久化**

  **What to do**:
  - 创建 `src/runtime/runtime_state/postgresql_store.py`
  - 实现 `PostgreSQLRuntimeStateStore`
  - 实现 workflow CRUD
  - 替换 `runtime_state_store` 为可配置实现

  **Must NOT do**:
  - 不删除内存实现

  **Recommended Agent Profile**:
  - **Category**: `deep`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 14
  - **Blocks**: Tasks 19-21

  **Acceptance Criteria**:
  - [ ] Workflow 可持久化到 PostgreSQL
  - [ ] 重启后可恢复 workflow 状态
  - [ ] 性能满足要求（< 100ms 读写）

  **QA Scenarios**:
  ```
  Scenario: Workflow 持久化验证
    Tool: Bash (pytest)
    Steps:
      1. 创建 workflow，保存到 PostgreSQL
      2. 重启应用，读取 workflow
      3. 断言状态一致
    Expected Result: 状态不丢失
    Evidence: .sisyphus/evidence/task-15-workflow-persistence.log
  ```

  **Commit**: YES
  - Message: `feat(runtime): add workflow state persistence`

- [x] 16. **Task 状态持久化**

  **What to do**:
  - 创建 `src/runtime/task_closure/postgresql_store.py`
  - 实现 `PostgreSQLTaskStore`
  - 实现 task CRUD
  - 替换 `TASKS` 字典

  **Must NOT do**:
  - 不修改 task 领域模型

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocked By**: Task 14
  - **Blocks**: Tasks 19-21

  **Acceptance Criteria**:
  - [ ] Task 可持久化到 PostgreSQL
  - [ ] 支持任务状态查询和更新

  **QA Scenarios**:
  ```
  Scenario: Task 持久化验证
    Tool: Bash (pytest)
    Steps:
      1. 创建 task，保存到 PostgreSQL
      2. 更新 task 状态
      3. 断言状态持久化
    Expected Result: 状态不丢失
    Evidence: .sisyphus/evidence/task-16-task-persistence.log
  ```

  **Commit**: YES
  - Message: `feat(task): add task state persistence`

- [x] 17. **Audit 日志持久化**

  **What to do**:
  - 创建 `src/security/audit/postgresql_store.py`
  - 实现 `PostgreSQLAuditLog`
  - 实现审计事件写入和查询
  - 替换 `InMemoryAuditLog`

  **Must NOT do**:
  - 不修改审计事件格式

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocked By**: Task 14
  - **Blocks**: Tasks 19-21

  **Acceptance Criteria**:
  - [ ] 审计事件可持久化到 PostgreSQL
  - [ ] 支持按 workflow_id 查询审计记录

  **QA Scenarios**:
  ```
  Scenario: 审计持久化验证
    Tool: Bash (pytest)
    Steps:
      1. 记录审计事件
      2. 查询审计记录
      3. 断言记录完整
    Expected Result: 审计不丢失
    Evidence: .sisyphus/evidence/task-17-audit-persistence.log
  ```

  **Commit**: YES
  - Message: `feat(audit): add audit log persistence`

- [x] 18. **LangGraph checkpoint 持久化**

  **What to do**:
  - 创建 `src/runtime/langgraph/postgresql_checkpointer.py`
  - 实现 `PostgreSQLCheckpointer`
  - 替换 `MemorySaver`

  **Must NOT do**:
  - 不修改 LangGraph 图定义

  **Recommended Agent Profile**:
  - **Category**: `deep`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 14
  - **Blocks**: Tasks 19-21

  **Acceptance Criteria**:
  - [ ] LangGraph checkpoint 可持久化
  - [ ] 中断后可从 checkpoint 恢复
  - [ ] 支持人工确认后恢复执行

  **QA Scenarios**:
  ```
  Scenario: Checkpoint 持久化验证
    Tool: Bash (pytest)
    Steps:
      1. 启动 LangGraph 执行，触发 interrupt
      2. 重启应用
      3. 从 checkpoint 恢复，完成执行
    Expected Result: 状态恢复，执行完成
    Evidence: .sisyphus/evidence/task-18-checkpoint-persistence.log
  ```

  **Commit**: YES
  - Message: `feat(langgraph): add PostgreSQL checkpoint persistence`

- [x] 19. **OpenTelemetry 链路追踪**

  **What to do**:
  - 创建 `src/observability/tracing/__init__.py`
  - 集成 OpenTelemetry SDK
  - 实现自动 instrumentation
  - 配置 Jaeger 导出器

  **Must NOT do**:
  - 不修改业务逻辑

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocked By**: Tasks 15-18
  - **Blocks**: None

  **Acceptance Criteria**:
  - [ ] 请求可追踪完整链路
  - [ ] 每个 LangGraph 节点有独立 span
  - [ ] 追踪数据可导出到 Jaeger

  **QA Scenarios**:
  ```
  Scenario: 链路追踪验证
    Tool: Bash (curl + pytest)
    Steps:
      1. 发送请求，触发完整流程
      2. 查询 Jaeger，断言链路完整
      3. 断言包含所有关键节点
    Expected Result: 链路追踪数据完整
    Evidence: .sisyphus/evidence/task-19-tracing.log
  ```

  **Commit**: YES
  - Message: `feat(observability): add OpenTelemetry tracing`

- [x] 20. **Prometheus 指标采集**

  **What to do**:
  - 创建 `src/observability/metrics/__init__.py`
  - 集成 Prometheus 客户端
  - 定义关键指标
  - 暴露 `/metrics` 端点

  **Must NOT do**:
  - 不修改业务逻辑

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocked By**: Tasks 15-18
  - **Blocks**: None

  **Acceptance Criteria**:
  - [ ] `/metrics` 端点可访问
  - [ ] 关键指标有数据
  - [ ] Grafana 仪表盘可显示

  **QA Scenarios**:
  ```
  Scenario: 指标采集验证
    Tool: Bash (curl)
    Steps:
      1. 访问 `/metrics` 端点
      2. 断言包含关键指标
      3. 发送请求，断言指标增加
    Expected Result: 指标数据正确
    Evidence: .sisyphus/evidence/task-20-metrics.log
  ```

  **Commit**: YES
  - Message: `feat(observability): add Prometheus metrics`

- [x] 21. **运行时事件记录增强**

  **What to do**:
  - 创建 `src/runtime/event_log/__init__.py`
  - 实现运行时事件记录（非消息总线）
  - 记录关键事件：IntentDetected、WorkflowStarted、StepCompleted、AdapterCalled
  - 事件写入 PostgreSQL（与 audit 分开）
  - 支持按 workflow_id 查询事件时间线

  **Must NOT do**:
  - 不实现消息总线（仅记录，不驱动流程）
  - 不替换现有直接调用

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Tasks 19-20
  - **Blocks**: None

  **References**:
  - `src/runtime/event_log/` - 新建目录
  - `src/data_platform/storage/postgresql/` - PostgreSQL 客户端

  **Acceptance Criteria**:
  - [ ] 事件可记录到 PostgreSQL
  - [ ] 支持按 workflow_id 查询事件时间线
  - [ ] 事件不丢失

  **QA Scenarios**:
  ```
  Scenario: 事件记录验证
    Tool: Bash (pytest)
    Steps:
      1. 触发工作流执行
      2. 查询事件记录
      3. 断言包含 IntentDetected、WorkflowStarted、StepCompleted 事件
    Expected Result: 事件记录完整
    Evidence: .sisyphus/evidence/task-21-event-logging.log
  ```

  **Commit**: YES
  - Message: `feat(runtime): add runtime event logging`

- [x] 22. **Milvus 向量检索**

  **What to do**:
  - 创建 `src/knowledge_extension/rag/milvus/__init__.py`
  - 实现 `MilvusVectorStore`
  - 支持文档嵌入和向量检索

  **Must NOT do**:
  - 不替换现有内存 RAG

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5
  - **Blocked By**: None
  - **Blocks**: Task 23

  **Acceptance Criteria**:
  - [ ] Milvus 连接成功
  - [ ] 支持文档嵌入和检索
  - [ ] 检索结果相关性可接受

  **QA Scenarios**:
  ```
  Scenario: Milvus 向量检索验证
    Tool: Bash (pytest)
    Steps:
      1. 插入测试文档
      2. 执行向量检索
      3. 断言返回相关文档
    Expected Result: 检索结果正确
    Evidence: .sisyphus/evidence/task-22-milvus.log
  ```

  **Commit**: YES
  - Message: `feat(rag): add Milvus vector store`

- [x] 23. **RAG 完整链路**

  **What to do**:
  - 创建 `src/knowledge_extension/rag/pipeline.py`
  - 实现完整 RAG 链路
  - 集成 Milvus 向量检索
  - 实现引用溯源

  **Must NOT do**:
  - 不修改知识服务接口

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 22
  - **Blocks**: None

  **Acceptance Criteria**:
  - [ ] RAG 链路可执行
  - [ ] 检索结果有引用溯源
  - [ ] 性能满足要求（< 2s）

  **QA Scenarios**:
  ```
  Scenario: RAG 链路验证
    Tool: Bash (pytest + curl)
    Steps:
      1. 提交知识查询
      2. 断言返回结果包含引用
      3. 断言延迟 < 2s
    Expected Result: RAG 正常工作
    Evidence: .sisyphus/evidence/task-23-rag-pipeline.log
  ```

  **Commit**: YES
  - Message: `feat(rag): implement complete RAG pipeline`

- [x] 24. **可治理业务能力节点**

  **What to do**:
  - 创建 `src/runtime/capability_nodes/__init__.py`
  - 实现业务能力节点注册表
  - 支持节点注册、发现、版本管理
  - 节点示例：病案风险分析节点、DRG/DIP 风险分析节点、事前审核结果解释节点
  - 节点可被 LangGraph 图调用

  **Must NOT do**:
  - 不实现自治 Agent 协作
  - 不实现 A2A 协议

  **Recommended Agent Profile**:
  - **Category**: `deep`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: None
  - **Blocks**: None

  **Acceptance Criteria**:
  - [ ] 节点可注册到注册表
  - [ ] 支持按 capability 发现节点
  - [ ] 节点可被 LangGraph 图调用

  **QA Scenarios**:
  ```
  Scenario: 业务能力节点验证
    Tool: Bash (pytest)
    Steps:
      1. 注册测试节点（病案风险分析）
      2. 按 capability 查询节点
      3. 在 LangGraph 图中调用节点
    Expected Result: 节点注册发现和调用正常
    Evidence: .sisyphus/evidence/task-24-capability-nodes.log
  ```

  **Commit**: YES
  - Message: `feat(runtime): add governable capability nodes`

- [x] 25. **K8s 部署配置**

  **What to do**:
  - 创建 `deploy/k8s/` 目录
  - 编写 Deployment、Service、ConfigMap、Secret YAML
  - 配置 HPA
  - 编写 Helm Chart

  **Must NOT do**:
  - 不修改应用代码

  **Recommended Agent Profile**:
  - **Category**: `quick`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5
  - **Blocked By**: None
  - **Blocks**: F1-F4

  **Acceptance Criteria**:
  - [ ] K8s 配置可应用
  - [ ] 服务可正常运行
  - [ ] HPA 可根据负载扩缩容

  **QA Scenarios**:
  ```
  Scenario: K8s 部署验证
    Tool: Bash (kubectl)
    Steps:
      1. 应用 K8s 配置
      2. 断言 Pod 正常运行
      3. 访问服务，断言响应正确
    Expected Result: 部署成功
    Evidence: .sisyphus/evidence/task-25-k8s-deployment.log
  ```

  **Commit**: YES
  - Message: `feat(deploy): add Kubernetes deployment configuration`

- [x] 26. **安全策略配置化**

  **What to do**:
  - 创建 `src/config/security_policy/dynamic.py`
  - 实现配置驱动的权限规则
  - 支持运行时更新策略
  - 实现策略版本管理

  **Must NOT do**:
  - 不删除现有硬编码规则

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5
  - **Blocked By**: None
  - **Blocks**: None

  **Acceptance Criteria**:
  - [ ] 策略可从配置文件加载
  - [ ] 支持运行时更新
  - [ ] 与现有规则结果一致

  **QA Scenarios**:
  ```
  Scenario: 配置化策略验证
    Tool: Bash (pytest)
    Steps:
      1. 加载配置策略
      2. 运行权限检查
      3. 断言结果与硬编码一致
    Expected Result: 策略正确加载
    Evidence: .sisyphus/evidence/task-26-configurable-security.log
  ```

  **Commit**: YES
  - Message: `feat(security): add configurable security policies`

---

## Final Verification Wave

> 4 review agents run in PARALLEL. ALL must APPROVE.

- [ ] F1. **架构合规审计** — `oracle`
  Verify: RuntimeOrchestrator exists and routes all requests; all adapters implement Port; unified execution entry; no legacy orchestration calls; state persistence works after restart.
  Output: `RuntimeOrchestrator [OK/FAIL] | Adapter Ports [OK/FAIL] | Unified Execution [OK/FAIL] | Persistence [OK/FAIL] | VERDICT`

- [ ] F2. **代码质量审查** — `unspecified-high`
  Run `mypy src/` + `ruff check src/` + `pytest src/tests`. Review for: empty catches, print statements, commented-out code, unused imports. Check AI slop.
  Output: `Type Check [PASS/FAIL] | Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **集成测试验证** — `unspecified-high`
  Execute all QA scenarios. Test edge cases: empty state, invalid input, rapid actions. Verify event timeline completeness.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **性能基准测试** — `deep`
  Run load tests. Measure: API latency (p50/p95/p99), throughput (RPS), error rate. Compare against baseline.
  Output: `Latency [p50/p95/p99] | Throughput [RPS] | Error Rate [%] | VERDICT`

---

## Commit Strategy

- **阶段一**: `feat(adapters): define business capability ports`
- **阶段一**: `feat(runtime): design RuntimeOrchestrator abstraction`
- **阶段一**: `refactor(adapters): implement business capability ports`
- **阶段一**: `feat(runtime): introduce FastAPI dependency injection`
- **阶段一**: `feat(runtime): implement LangGraph scenario executor`
- **阶段一**: `chore(runtime): deprecate legacy execution paths`
- **阶段一**: `refactor(api): decouple routes.py into orchestrator`
- **阶段一**: `refactor(skill): adapt skill engine to adapter ports`
- **阶段二**: `feat(domain): add {audit_risk,drg_dip,medical_record,appeal,order_fee} domain models`
- **阶段二**: `feat(storage): add PostgreSQL storage implementation`
- **阶段二**: `feat(runtime): add workflow state persistence`
- **阶段二**: `feat(task): add task state persistence`
- **阶段二**: `feat(audit): add audit log persistence`
- **阶段二**: `feat(langgraph): add PostgreSQL checkpoint persistence`
- **阶段二**: `feat(observability): add OpenTelemetry tracing`
- **阶段二**: `feat(observability): add Prometheus metrics`
- **阶段二**: `feat(runtime): add runtime event logging`
- **阶段三**: `feat(rag): add Milvus vector store`
- **阶段三**: `feat(rag): implement complete RAG pipeline`
- **阶段三**: `feat(runtime): add governable capability nodes`
- **阶段三**: `feat(deploy): add Kubernetes deployment configuration`
- **阶段三**: `feat(security): add configurable security policies`

---

## Success Criteria

### Verification Commands
```bash
# 运行全部测试
python -m pytest src/tests -v

# 运行 E2E 测试
python -m pytest src/tests/e2e -v

# 启动服务验证
uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory

# API 健康检查
curl http://127.0.0.1:8000/health

# 结算异常场景测试
curl -X POST http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u-001","role":"medical_office","message":"医保结算失败","patient_id":"P001","encounter_id":"E001"}'
```

### Final Checklist
- [ ] 所有适配器实现统一 Port/Protocol，可通过配置切换实现
- [ ] RuntimeOrchestrator 接管所有业务流程编排
- [ ] 单一执行入口：RuntimeOrchestrator -> LangGraph 场景执行器
- [ ] 状态持久化：重启后 workflow/task/audit 不丢失
- [ ] 可观测性：链路追踪、性能指标、审计事件记录
- [ ] 领域层覆盖医保全部核心业务对象
- [ ] 可治理业务能力节点可注册、可发现
- [ ] 所有测试通过（单元测试、集成测试、E2E测试）
- [ ] 代码覆盖率 > 80%
- [ ] 性能基准：p95 延迟 < 500ms，错误率 < 0.1%

---

## 成熟度准入与退出标准

### 阶段一：运行时治理

**准入条件**:
- MVP 可运行，所有现有测试通过
- LangGraph 场景图已定义

**退出标准**:
- [ ] RuntimeOrchestrator 已接管所有请求编排
- [ ] routes.py 行数 < 200
- [ ] 所有适配器实现 Port/Protocol
- [ ] 旧版执行路径已标记弃用
- [ ] 代码审查通过

### 阶段二：状态与可观测性

**准入条件**:
- 阶段一所有退出标准达成
- PostgreSQL 实例可用

**退出标准**:
- [ ] Workflow/Task/Audit 状态可持久化
- [ ] 重启后状态不丢失
- [ ] OpenTelemetry 链路追踪可用
- [ ] Prometheus 指标可采集
- [ ] 运行时事件记录完整
- [ ] 压力测试通过

### 阶段三：能力扩展

**准入条件**:
- 阶段二所有退出标准达成
- Milvus 实例可用（如需要）

**退出标准**:
- [ ] RAG 向量检索可用
- [ ] 可治理业务能力节点可注册
- [ ] K8s 部署配置可用
- [ ] 安全策略可配置
- [ ] 生产环境部署验证通过
