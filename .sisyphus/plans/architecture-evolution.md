# 架构改进计划：医保 AI 平台演进

## TL;DR

> **目标**: 基于 Datawhale 框架实践评估，将当前 MVP 架构演进为生产级平台
> 
> **核心策略**: 保留 LangGraph 执行核心，引入 AgentScope 工程化实践，分三阶段渐进演进
> 
> **关键交付**:
> - 阶段一（2个月）: 适配器 Protocol、完整领域层、统一执行引擎
> - 阶段二（2个月）: 状态持久化、消息驱动、可观测性
> - 阶段三（2个月）: 多 Agent 协作、分布式部署、RAG 增强
> 
> **Estimated Effort**: Large (6个月分阶段)
> **Parallel Execution**: YES - 每阶段 5-8 个并行任务
> **Critical Path**: 适配器 Protocol → 领域层补齐 → 执行引擎统一 → 状态持久化 → 消息驱动 → 多 Agent

---

## Context

### 原始请求
基于 Datawhale hello-agents 第六章框架开发实践，评估当前医保 AI 平台架构合理性，并制定可执行的改进计划。

### 评估结论
当前架构方向正确（LangGraph 状态机适合医保场景），但在工程化实践方面存在明显差距：
- 🔴 无适配器协议、依赖注入缺失、完全内存化
- 🟡 双重执行引擎、领域层不完整、单 Agent 限制
- ✅ LangGraph 选择正确、适配器防腐层设计优秀、安全围栏完善

### 研究洞察
- **LangGraph**: 状态机精确控制，适合医保严格流程，保留作为执行核心
- **AgentScope**: 消息驱动、异步解耦、可观测性，需引入作为工程化增强
- **AutoGen**: 多角色群聊，参考用于未来多 Agent 协作设计
- **HelloAgents**: Tool/Skill 简洁抽象，当前已实现，保持

---

## Work Objectives

### Core Objective
将当前 MVP 架构演进为生产级平台，在保留 LangGraph 执行核心的基础上，引入消息驱动、状态持久化、多 Agent 协作等工业级能力。

### Concrete Deliverables
- **阶段一**: 
  - `src/adapters/ports/` - 适配器 Protocol 定义
  - `src/domain/{audit_risk,drg_dip,medical_record,appeal,order_fee}/` - 完整领域模型
  - `src/runtime/orchestration/langgraph_executor.py` - 统一 LangGraph 执行引擎
  - `src/runtime/dependencies.py` - FastAPI Depends 依赖注入
- **阶段二**:
  - `src/data_platform/storage/postgresql/` - PostgreSQL 持久化实现
  - `src/data_platform/storage/redis/` - Redis 缓存实现
  - `src/runtime/event_bus/` - 事件总线（Redis Pub/Sub）
  - `src/observability/tracing/` - OpenTelemetry 链路追踪
- **阶段三**:
  - `src/runtime/multi_agent/` - 多 Agent 注册发现与协调
  - `src/runtime/a2a/` - A2A 协议实现
  - `src/knowledge_extension/rag/milvus/` - 向量检索实现
  - `deploy/k8s/` - Kubernetes 部署配置

### Definition of Done
- [ ] 所有适配器实现统一 Protocol，可通过配置切换实现
- [ ] 领域层覆盖医保全部核心业务对象
- [ ] 单一 LangGraph 执行路径，旧版路径已弃用
- [ ] 状态持久化：重启后 workflow/task/audit 不丢失
- [ ] 消息驱动：模块间通过事件总线通信
- [ ] 可观测性：链路追踪、性能指标、监控看板
- [ ] 多 Agent：复杂场景可分解为多个专业 Agent 协同

### Must Have
- 适配器 Protocol 契约
- 完整领域模型
- 统一执行引擎
- 状态持久化

### Must NOT Have (Guardrails)
- 不推倒重来，保留现有 LangGraph 核心
- 不引入过度复杂的分布式事务
- 不牺牲可审计性换取灵活性
- 不一次性引入所有新技术，分阶段渐进

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

### Parallel Execution Waves

```
Wave 1 (Start Immediately - 阶段一基础):
├── Task 1: 定义适配器 Protocol 契约 [quick]
├── Task 2: 补齐 audit_risk 领域模型 [quick]
├── Task 3: 补齐 drg_dip 领域模型 [quick]
├── Task 4: 补齐 medical_record 领域模型 [quick]
├── Task 5: 补齐 appeal 领域模型 [quick]
├── Task 6: 补齐 order_fee 领域模型 [quick]
└── Task 7: 引入 FastAPI 依赖注入 [quick]

Wave 2 (After Wave 1 - 阶段一核心):
├── Task 8: 重构适配器实现 Protocol (depends: 1) [unspecified-high]
├── Task 9: 统一 LangGraph 执行引擎 (depends: 1, 7) [deep]
├── Task 10: 弃用旧版 orchestration/planning (depends: 9) [quick]
├── Task 11: 重构 routes.py 解耦 (depends: 7, 9) [unspecified-high]
├── Task 12: 技能引擎适配新协议 (depends: 1, 8) [unspecified-high]
└── Task 13: 单元测试覆盖新协议 (depends: 1, 8) [quick]

Wave 3 (After Wave 2 - 阶段二基础):
├── Task 14: PostgreSQL 连接与模型 (depends: 2-6) [unspecified-high]
├── Task 15: Redis 连接与缓存 (depends: 2-6) [unspecified-high]
├── Task 16: Workflow 状态持久化 (depends: 9, 14) [deep]
├── Task 17: Task 状态持久化 (depends: 14) [unspecified-high]
├── Task 18: Audit 日志持久化 (depends: 14) [unspecified-high]
└── Task 19: LangGraph checkpoint 持久化 (depends: 9, 15) [deep]

Wave 4 (After Wave 3 - 阶段二核心):
├── Task 20: 事件总线设计与实现 (depends: 16-19) [deep]
├── Task 21: 核心流程事件化改造 (depends: 11, 20) [unspecified-high]
├── Task 22: OpenTelemetry 链路追踪 (depends: 20) [unspecified-high]
├── Task 23: Prometheus 指标采集 (depends: 20) [unspecified-high]
├── Task 24: 监控看板配置 (depends: 22, 23) [visual-engineering]
└── Task 25: 安全策略配置化 (depends: 11) [unspecified-high]

Wave 5 (After Wave 4 - 阶段三):
├── Task 26: Agent 注册发现机制 (depends: 20) [deep]
├── Task 27: 多 Agent 协调器 (depends: 26) [deep]
├── Task 28: A2A 协议实现 (depends: 26) [unspecified-high]
├── Task 29: Milvus 向量检索 (depends: 14) [unspecified-high]
├── Task 30: RAG 完整链路 (depends: 29) [unspecified-high]
└── Task 31: K8s 部署配置 (depends: 20, 26) [quick]

Wave FINAL (After ALL tasks — 4 parallel reviews):
├── Task F1: 架构合规审计 (oracle)
├── Task F2: 代码质量审查 (unspecified-high)
├── Task F3: 集成测试验证 (unspecified-high)
└── Task F4: 性能基准测试 (deep)
-> Present results -> Get explicit user okay

Critical Path: Task 1 → Task 8 → Task 9 → Task 16 → Task 20 → Task 26 → F1-F4
Parallel Speedup: ~65% faster than sequential
Max Concurrent: 7 (Wave 1)
```

### Dependency Matrix (abbreviated)

- **1-7**: - - 8-13, 1
- **8**: 1 - 12, 13, 2
- **9**: 1, 7 - 10, 11, 16, 19, 3
- **10**: 9 - 11, 4
- **11**: 7, 9 - 21, 25, 5
- **12**: 1, 8 - 13, 6
- **14-15**: 2-6 - 16-19, 7
- **16**: 9, 14 - 20, 8
- **17-18**: 14 - 20, 9
- **19**: 9, 15 - 20, 10
- **20**: 16-19 - 21, 22, 23, 26, 11
- **21**: 11, 20 - 24, 12
- **22-23**: 20 - 24, 13
- **24**: 22, 23 - 25, 14
- **25**: 11 - 26, 15
- **26**: 20 - 27, 28, 16
- **27**: 26 - 28, 17
- **28**: 26 - 29, 18
- **29**: 14 - 30, 19
- **30**: 29 - 31, 20
- **31**: 20, 26 - F1-F4, 21

---

## TODOs

- [ ] 1. **定义适配器 Protocol 契约**

  **What to do**:
  - 在 `src/adapters/ports/` 创建 Protocol 定义文件
  - 定义 `InsuranceInterfacePort`、`BillingPort`、`HisPort`、`EmrPort`、`PreAuditPort`、`DrgDipPort`、`MedicalRecordPort`
  - 每个 Protocol 包含标准方法签名（如 `query_transaction(patient_id, encounter_id) -> AdapterCallResult`）
  - 定义通用基类 `BaseAdapterPort` 包含通用方法（health_check、ping 等）
  - 编写 Protocol 文档说明每个方法的语义和异常约定

  **Must NOT do**:
  - 不修改现有 `in_memory.py` 实现（留到 Task 8）
  - 不引入过度抽象（保持方法扁平，不嵌套太深）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - **Reason**: 纯接口定义，无业务逻辑，适合快速完成

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2-7)
  - **Blocks**: Task 8, Task 12, Task 13
  - **Blocked By**: None

  **References**:
  - `src/adapters/base/models.py:AdapterCallResult` - 返回类型契约
  - `src/adapters/insurance_interface/in_memory.py` - 当前实现参考
  - `src/adapters/billing/in_memory.py` - 当前实现参考
  - Python Protocol: https://docs.python.org/3/library/typing.html#typing.Protocol

  **Acceptance Criteria**:
  - [ ] `src/adapters/ports/` 目录存在且包含所有 Protocol 定义
  - [ ] 每个 Protocol 有完整的方法签名和文档字符串
  - [ ] pytest 可通过 `isinstance(adapter, Protocol)` 验证现有适配器

  **QA Scenarios**:
  ```
  Scenario: Protocol 定义完整性验证
    Tool: Bash (pytest)
    Preconditions: 代码已拉取
    Steps:
      1. 运行 `python -m pytest src/tests/unit/adapters/test_ports.py -v`
      2. 断言所有 Protocol 可被正确导入
      3. 断言现有适配器实例可通过 isinstance 检查
    Expected Result: 所有测试通过，覆盖率 100%
    Evidence: .sisyphus/evidence/task-1-protocol-validation.log
  ```

  **Commit**: YES
  - Message: `feat(adapters): define adapter protocol contracts`
  - Files: `src/adapters/ports/*.py`

- [ ] 2. **补齐 audit_risk 领域模型**

  **What to do**:
  - 创建 `src/domain/audit_risk/__init__.py`
  - 创建 `src/domain/audit_risk/models.py`
  - 定义核心领域对象：`AuditResult`、`RiskFlag`、`RuleHit`、`ComplianceScore`
  - 使用 frozen dataclass（与现有 domain 风格一致）
  - 包含字段验证逻辑

  **Must NOT do**:
  - 不引入 Pydantic（保持与现有 domain 风格一致的 dataclass）
  - 不实现业务逻辑（仅模型定义）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3-7)
  - **Blocks**: Task 14
  - **Blocked By**: None

  **References**:
  - `src/domain/patient/models.py` - 现有领域模型风格参考
  - `src/domain/insurance/models.py` - 现有领域模型风格参考
  - `src/adapters/pre_audit/in_memory.py` - 预审核数据字段参考

  **Acceptance Criteria**:
  - [ ] `src/domain/audit_risk/models.py` 存在且包含所有核心对象
  - [ ] 可通过 `from src.domain.audit_risk import AuditResult` 导入
  - [ ] 包含基本的字段验证（如 risk_level 枚举值）

  **QA Scenarios**:
  ```
  Scenario: 领域模型导入与验证
    Tool: Bash (python REPL)
    Preconditions: 代码已拉取
    Steps:
      1. 运行 `python -c "from src.domain.audit_risk import AuditResult; print(AuditResult)"`
      2. 断言无 ImportError
      3. 运行 `python -m pytest src/tests/unit/domain/test_audit_risk.py -v`
    Expected Result: 导入成功，测试通过
    Evidence: .sisyphus/evidence/task-2-domain-model.log
  ```

  **Commit**: YES
  - Message: `feat(domain): add audit_risk domain models`
  - Files: `src/domain/audit_risk/*.py`

- [ ] 3. **补齐 drg_dip 领域模型**

  **What to do**:
  - 创建 `src/domain/drg_dip/__init__.py`
  - 创建 `src/domain/drg_dip/models.py`
  - 定义核心领域对象：`DrgGroupResult`、`DipGroupResult`、`PaymentRate`、`ProfitLoss`
  - 使用 frozen dataclass

  **Must NOT do**:
  - 不实现分组算法（仅模型定义）

  **Recommended Agent Profile**:
  - **Category**: `quick`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 14
  - **Blocked By**: None

  **References**:
  - `src/adapters/drg_dip/in_memory.py` - DRG/DIP 数据字段参考
  - `src/business_scenarios/pre_discharge_joint_qc/service.py` - 业务使用场景

  **Acceptance Criteria**:
  - [ ] `src/domain/drg_dip/models.py` 存在且包含核心对象
  - [ ] 可通过 `from src.domain.drg_dip import DrgGroupResult` 导入

  **QA Scenarios**:
  ```
  Scenario: DRG/DIP 领域模型验证
    Tool: Bash (python REPL)
    Steps:
      1. 运行 `python -c "from src.domain.drg_dip import DrgGroupResult; print(DrgGroupResult)"`
      2. 断言无 ImportError
    Expected Result: 导入成功
    Evidence: .sisyphus/evidence/task-3-drg-dip-model.log
  ```

  **Commit**: YES
  - Message: `feat(domain): add drg_dip domain models`

- [ ] 4. **补齐 medical_record 领域模型**

  **What to do**:
  - 创建 `src/domain/medical_record/__init__.py`
  - 创建 `src/domain/medical_record/models.py`
  - 定义核心领域对象：`MedicalRecordHomepage`、`Diagnosis`、`Surgery`、`Coding`
  - 使用 frozen dataclass

  **Must NOT do**:
  - 不实现编码校验逻辑（仅模型定义）

  **Recommended Agent Profile**:
  - **Category**: `quick`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 14
  - **Blocked By**: None

  **References**:
  - `src/adapters/medical_record/in_memory.py` - 病案数据字段参考

  **Acceptance Criteria**:
  - [ ] `src/domain/medical_record/models.py` 存在且包含核心对象
  - [ ] 可通过 `from src.domain.medical_record import MedicalRecordHomepage` 导入

  **QA Scenarios**:
  ```
  Scenario: 病案领域模型验证
    Tool: Bash (python REPL)
    Steps:
      1. 运行 `python -c "from src.domain.medical_record import MedicalRecordHomepage; print(MedicalRecordHomepage)"`
      2. 断言无 ImportError
    Expected Result: 导入成功
    Evidence: .sisyphus/evidence/task-4-medical-record-model.log
  ```

  **Commit**: YES
  - Message: `feat(domain): add medical_record domain models`

- [ ] 5. **补齐 appeal 领域模型**

  **What to do**:
  - 创建 `src/domain/appeal/__init__.py`
  - 创建 `src/domain/appeal/models.py`
  - 定义核心领域对象：`DenialRecord`、`AppealCase`、`Evidence`、`AppealMaterial`
  - 使用 frozen dataclass

  **Must NOT do**:
  - 不实现申诉流程逻辑（仅模型定义）

  **Recommended Agent Profile**:
  - **Category**: `quick`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 14
  - **Blocked By**: None

  **References**:
  - 业务架构文档中拒付申诉场景描述

  **Acceptance Criteria**:
  - [ ] `src/domain/appeal/models.py` 存在且包含核心对象
  - [ ] 可通过 `from src.domain.appeal import AppealCase` 导入

  **QA Scenarios**:
  ```
  Scenario: 申诉领域模型验证
    Tool: Bash (python REPL)
    Steps:
      1. 运行 `python -c "from src.domain.appeal import AppealCase; print(AppealCase)"`
      2. 断言无 ImportError
    Expected Result: 导入成功
    Evidence: .sisyphus/evidence/task-5-appeal-model.log
  ```

  **Commit**: YES
  - Message: `feat(domain): add appeal domain models`

- [ ] 6. **补齐 order_fee 领域模型**

  **What to do**:
  - 创建 `src/domain/order_fee/__init__.py`
  - 创建 `src/domain/order_fee/models.py`
  - 定义核心领域对象：`Order`、`FeeItem`、`Drug`、`Consumable`、`Treatment`
  - 使用 frozen dataclass

  **Must NOT do**:
  - 不实现费用计算逻辑（仅模型定义）

  **Recommended Agent Profile**:
  - **Category**: `quick`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 14
  - **Blocked By**: None

  **References**:
  - `src/adapters/his/in_memory.py` - 医嘱数据字段参考
  - `src/adapters/billing/in_memory.py` - 费用数据字段参考

  **Acceptance Criteria**:
  - [ ] `src/domain/order_fee/models.py` 存在且包含核心对象
  - [ ] 可通过 `from src.domain.order_fee import Order` 导入

  **QA Scenarios**:
  ```
  Scenario: 医嘱费用领域模型验证
    Tool: Bash (python REPL)
    Steps:
      1. 运行 `python -c "from src.domain.order_fee import Order; print(Order)"`
      2. 断言无 ImportError
    Expected Result: 导入成功
    Evidence: .sisyphus/evidence/task-6-order-fee-model.log
  ```

  **Commit**: YES
  - Message: `feat(domain): add order_fee domain models`

- [ ] 7. **引入 FastAPI 依赖注入**

  **What to do**:
  - 创建 `src/runtime/dependencies.py`
  - 定义依赖提供函数：`get_insurance_adapter()`、`get_billing_adapter()`、`get_his_adapter()` 等
  - 使用 FastAPI `Depends` 注入到路由中
  - 支持通过环境变量切换实现（memory/real）
  - 创建 `src/config/adapters.py` 配置适配器实现类型

  **Must NOT do**:
  - 不修改业务逻辑（仅修改依赖获取方式）
  - 不一次性修改所有路由（逐步迁移）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 9, Task 11
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
    Evidence: .sisyphus/evidence/task-7-dependency-injection.log
  ```

  **Commit**: YES
  - Message: `feat(runtime): introduce FastAPI dependency injection`
  - Files: `src/runtime/dependencies.py`, `src/config/adapters.py`

- [ ] 8. **重构适配器实现 Protocol**

  **What to do**:
  - 修改所有 `src/adapters/*/in_memory.py` 实现对应 Protocol
  - 确保方法签名与 Protocol 一致
  - 添加 `__init__.py` 导出适配器类
  - 更新导入路径（从 `in_memory` 改为模块级导入）

  **Must NOT do**:
  - 不修改业务逻辑（仅适配 Protocol 接口）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO (需按顺序验证每个适配器)
  - **Blocked By**: Task 1
  - **Blocks**: Task 12, Task 13

  **References**:
  - `src/adapters/ports/*.py` - Protocol 定义
  - `src/adapters/*/in_memory.py` - 当前实现

  **Acceptance Criteria**:
  - [ ] 所有适配器实现对应 Protocol
  - [ ] `isinstance(adapter, Protocol)` 返回 True
  - [ ] 现有测试仍通过

  **QA Scenarios**:
  ```
  Scenario: 适配器 Protocol 实现验证
    Tool: Bash (pytest)
    Steps:
      1. 运行 `python -m pytest src/tests/unit/adapters/ -v`
      2. 断言所有适配器通过 isinstance 检查
      3. 断言现有集成测试仍通过
    Expected Result: 所有测试通过
    Evidence: .sisyphus/evidence/task-8-adapter-protocol.log
  ```

  **Commit**: YES
  - Message: `refactor(adapters): implement adapter protocols`

- [ ] 9. **统一 LangGraph 执行引擎**

  **What to do**:
  - 创建 `src/runtime/orchestration/langgraph_executor.py`
  - 实现 `LangGraphExecutor` 类，统一构建和执行 LangGraph
  - 支持动态加载场景图（settlement_exception、pre_discharge_qc 等）
  - 集成 checkpoint 持久化接口（先使用 MemorySaver，后续替换）
  - 实现统一的错误处理和重试机制
  - 将 `routes.py` 中的 `_try_langgraph_execution` 逻辑迁移到此处

  **Must NOT do**:
  - 不删除现有 LangGraph 图定义（仅统一执行入口）
  - 不修改图的节点逻辑

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 1, Task 7
  - **Blocks**: Task 10, Task 11, Task 16, Task 19

  **References**:
  - `src/runtime/langgraph/settlement_exception.py` - 结算异常图
  - `src/runtime/langgraph/pre_discharge_qc.py` - 出院质控图
  - `src/runtime/api/routes.py:_try_langgraph_execution()` - 当前执行逻辑
  - `src/runtime/orchestration/service.py` - 旧版执行器

  **Acceptance Criteria**:
  - [ ] `LangGraphExecutor` 可执行所有现有场景图
  - [ ] 支持通过场景名称动态选择图
  - [ ] 错误处理覆盖所有异常类型
  - [ ] 现有 E2E 测试通过

  **QA Scenarios**:
  ```
  Scenario: 统一执行引擎验证
    Tool: Bash (pytest + curl)
    Steps:
      1. 运行 `python -m pytest src/tests/langgraph/test_orchestration_unified.py -v`
      2. 运行 E2E 测试 `python -m pytest src/tests/e2e/ -v`
      3. 断言所有场景返回正确 AgentResponse 结构
    Expected Result: 所有测试通过
    Evidence: .sisyphus/evidence/task-9-unified-executor.log
  ```

  **Commit**: YES
  - Message: `feat(runtime): unify LangGraph execution engine`

- [ ] 10. **弃用旧版 orchestration/planning**

  **What to do**:
  - 标记 `src/runtime/orchestration/service.py` 为弃用（添加 DeprecationWarning）
  - 标记 `src/runtime/planning/service.py` 为弃用
  - 将旧版路径调用迁移到 LangGraph 执行引擎
  - 更新 `routes.py` 中的回退逻辑
  - 保留文件但添加文档说明迁移路径

  **Must NOT do**:
  - 不删除文件（保留向后兼容）
  - 不修改旧版文件内容（仅添加弃用标记）

  **Recommended Agent Profile**:
  - **Category**: `quick`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 9
  - **Blocks**: Task 11

  **References**:
  - `src/runtime/orchestration/service.py` - 旧版执行器
  - `src/runtime/planning/service.py` - 旧版规划器
  - `src/runtime/api/routes.py` - 回退逻辑

  **Acceptance Criteria**:
  - [ ] 旧版文件添加弃用标记
  - [ ] `routes.py` 不再调用旧版路径（或调用时发出警告）
  - [ ] 所有场景通过 LangGraph 引擎执行

  **QA Scenarios**:
  ```
  Scenario: 旧版路径弃用验证
    Tool: Bash (pytest)
    Steps:
      1. 运行 `python -m pytest src/tests/e2e/ -v`
      2. 断言无 DeprecationWarning 之外的警告
      3. 断言所有场景返回正确结果
    Expected Result: 测试通过，无异常
    Evidence: .sisyphus/evidence/task-10-deprecate-legacy.log
  ```

  **Commit**: YES
  - Message: `chore(runtime): deprecate legacy orchestration/planning`

- [ ] 11. **重构 routes.py 解耦**

  **What to do**:
  - 创建 `src/runtime/api/orchestrator.py` - `RuntimeOrchestrator` 类
  - 将 `process_chat_request()` 中的编排逻辑迁移到 Orchestrator
  - 将安全校验提取为 FastAPI 依赖（`verify_security()`）
  - 将意图识别提取为服务方法
  - `routes.py` 仅保留 HTTP 层逻辑（参数解析、响应封装）

  **Must NOT do**:
  - 不修改 API 接口契约（保持向后兼容）
  - 不修改业务逻辑（仅重新组织代码）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 7, Task 9
  - **Blocks**: Task 21, Task 25

  **References**:
  - `src/runtime/api/routes.py` - 当前上帝模块
  - `src/runtime/dependencies.py` - 依赖注入
  - `src/runtime/orchestration/langgraph_executor.py` - 统一执行引擎

  **Acceptance Criteria**:
  - [ ] `routes.py` 行数 < 200 行
  - [ ] `RuntimeOrchestrator` 包含核心编排逻辑
  - [ ] 安全校验为独立依赖函数
  - [ ] 所有 E2E 测试通过

  **QA Scenarios**:
  ```
  Scenario: 路由解耦验证
    Tool: Bash (pytest + curl)
    Steps:
      1. 运行 `python -m pytest src/tests/e2e/ -v`
      2. 运行 `python -m pytest src/tests/langgraph/test_orchestration_unified.py -v`
      3. 断言 routes.py 行数 < 200
    Expected Result: 测试通过，routes.py 精简
    Evidence: .sisyphus/evidence/task-11-routes-decoupling.log
  ```

  **Commit**: YES
  - Message: `refactor(api): decouple routes.py into orchestrator service`

- [ ] 12. **技能引擎适配新协议**

  **What to do**:
  - 修改 `src/runtime/skill_registry/engine.py`
  - 使用依赖注入获取适配器（替代直接实例化）
  - 适配器调用通过 Protocol 接口（替代硬编码方法名）
  - 保持 SkillExecutionEngine 对外接口不变

  **Must NOT do**:
  - 不修改 Skill/Tool 领域模型
  - 不修改技能执行顺序逻辑

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 1, Task 8
  - **Blocks**: Task 13

  **References**:
  - `src/runtime/skill_registry/engine.py` - 当前实现
  - `src/adapters/ports/*.py` - Protocol 定义
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
    Evidence: .sisyphus/evidence/task-12-skill-engine-protocol.log
  ```

  **Commit**: YES
  - Message: `refactor(skill): adapt skill engine to adapter protocols`

- [ ] 13. **单元测试覆盖新协议**

  **What to do**:
  - 创建 `src/tests/unit/adapters/test_ports.py`
  - 为每个 Protocol 编写接口契约测试
  - 创建 Mock 适配器实现用于测试
  - 测试适配器切换逻辑（memory → real）

  **Must NOT do**:
  - 不测试具体业务逻辑（仅测试接口契约）

  **Recommended Agent Profile**:
  - **Category**: `quick`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 8-12)
  - **Blocked By**: Task 1, Task 8
  - **Blocks**: None

  **References**:
  - `src/adapters/ports/*.py` - Protocol 定义
  - `src/tests/unit/` - 现有测试结构

  **Acceptance Criteria**:
  - [ ] 每个 Protocol 有对应的契约测试
  - [ ] Mock 适配器可用于单元测试
  - [ ] 适配器切换逻辑有测试覆盖

  **QA Scenarios**:
  ```
  Scenario: 协议契约测试验证
    Tool: Bash (pytest)
    Steps:
      1. 运行 `python -m pytest src/tests/unit/adapters/test_ports.py -v`
      2. 断言覆盖率 > 90%
      3. 断言所有 Protocol 有测试
    Expected Result: 测试通过，高覆盖率
    Evidence: .sisyphus/evidence/task-13-protocol-tests.log
  ```

  **Commit**: YES
  - Message: `test(adapters): add protocol contract tests`

- [ ] 14. **PostgreSQL 连接与模型**

  **What to do**:
  - 创建 `src/data_platform/storage/postgresql/__init__.py`
  - 创建 `src/data_platform/storage/postgresql/client.py` - PostgreSQL 连接管理
  - 创建 `src/data_platform/storage/postgresql/models.py` - SQLAlchemy 模型
  - 定义表结构：workflow、task、audit_log、session
  - 实现连接池和事务管理
  - 添加数据库迁移脚本（Alembic）

  **Must NOT do**:
  - 不替换现有内存存储（仅添加新实现）
  - 不修改业务逻辑

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 15)
  - **Blocked By**: Tasks 2-6
  - **Blocks**: Tasks 16-18

  **References**:
  - `src/data_platform/storage/` - 现有存储抽象
  - `src/runtime/runtime_state/models.py` - 状态模型
  - `src/security/audit/service.py` - 审计模型
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

- [ ] 15. **Redis 连接与缓存**

  **What to do**:
  - 创建 `src/data_platform/storage/redis/__init__.py`
  - 创建 `src/data_platform/storage/redis/client.py` - Redis 连接管理
  - 实现缓存接口：get、set、delete、expire
  - 实现会话状态缓存
  - 实现分布式锁（用于并发控制）

  **Must NOT do**:
  - 不替换现有内存缓存（仅添加新实现）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 14)
  - **Blocked By**: Tasks 2-6
  - **Blocks**: Task 19

  **References**:
  - `src/data_platform/storage/` - 现有存储抽象
  - `src/runtime/session/` - 会话管理
  - Redis-py: https://redis-py.readthedocs.io/

  **Acceptance Criteria**:
  - [ ] Redis 客户端可连接服务器
  - [ ] 支持基本缓存操作
  - [ ] 支持会话状态序列化/反序列化

  **QA Scenarios**:
  ```
  Scenario: Redis 缓存验证
    Tool: Bash (python)
    Steps:
      1. 运行 `python -c "from src.data_platform.storage.redis import client; print(client.ping())"`
      2. 设置测试键值，断言可读取
      3. 断言过期机制生效
    Expected Result: 连接成功，缓存操作正常
    Evidence: .sisyphus/evidence/task-15-redis.log
  ```

  **Commit**: YES
  - Message: `feat(storage): add Redis cache implementation`

- [ ] 16. **Workflow 状态持久化**

  **What to do**:
  - 创建 `src/runtime/runtime_state/postgresql_store.py`
  - 实现 `PostgreSQLRuntimeStateStore` 类
  - 实现 workflow CRUD 操作
  - 实现 step 状态更新
  - 替换 `runtime_state_store` 为可配置实现（memory/postgresql）

  **Must NOT do**:
  - 不删除内存实现（保留用于测试）

  **Recommended Agent Profile**:
  - **Category**: `deep`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Tasks 9, 14
  - **Blocks**: Task 20

  **References**:
  - `src/runtime/runtime_state/store.py` - 现有内存实现
  - `src/runtime/runtime_state/models.py` - 状态模型
  - `src/data_platform/storage/postgresql/` - PostgreSQL 客户端

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
    Evidence: .sisyphus/evidence/task-16-workflow-persistence.log
  ```

  **Commit**: YES
  - Message: `feat(runtime): add workflow state persistence`

- [ ] 17. **Task 状态持久化**

  **What to do**:
  - 创建 `src/runtime/task_closure/postgresql_store.py`
  - 实现 `PostgreSQLTaskStore` 类
  - 实现 task CRUD 操作
  - 替换 `TASKS` 字典为可配置实现

  **Must NOT do**:
  - 不修改 task 领域模型

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 16, 18)
  - **Blocked By**: Task 14
  - **Blocks**: Task 20

  **References**:
  - `src/runtime/task_closure/service.py` - 现有内存实现
  - `src/data_platform/storage/postgresql/` - PostgreSQL 客户端

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
    Evidence: .sisyphus/evidence/task-17-task-persistence.log
  ```

  **Commit**: YES
  - Message: `feat(task): add task state persistence`

- [ ] 18. **Audit 日志持久化**

  **What to do**:
  - 创建 `src/security/audit/postgresql_store.py`
  - 实现 `PostgreSQLAuditLog` 类
  - 实现审计事件写入和查询
  - 替换 `InMemoryAuditLog` 为可配置实现

  **Must NOT do**:
  - 不修改审计事件格式

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 16, 17)
  - **Blocked By**: Task 14
  - **Blocks**: Task 20

  **References**:
  - `src/security/audit/service.py` - 现有内存实现
  - `src/data_platform/storage/postgresql/` - PostgreSQL 客户端

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
    Evidence: .sisyphus/evidence/task-18-audit-persistence.log
  ```

  **Commit**: YES
  - Message: `feat(audit): add audit log persistence`

- [ ] 19. **LangGraph checkpoint 持久化**

  **What to do**:
  - 创建 `src/runtime/langgraph/postgresql_checkpointer.py`
  - 实现 `PostgreSQLCheckpointer` 类（继承 BaseCheckpointSaver）
  - 实现 checkpoint 写入和读取
  - 替换 `MemorySaver` 为可配置实现

  **Must NOT do**:
  - 不修改 LangGraph 图定义

  **Recommended Agent Profile**:
  - **Category**: `deep`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Tasks 9, 15
  - **Blocks**: Task 20

  **References**:
  - `src/runtime/langgraph/checkpoint.py` - 现有 MemorySaver
  - `src/data_platform/storage/redis/` - Redis 客户端（可选）
  - LangGraph Checkpoint: https://langchain-ai.github.io/langgraph/concepts/persistence/

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
    Evidence: .sisyphus/evidence/task-19-checkpoint-persistence.log
  ```

  **Commit**: YES
  - Message: `feat(langgraph): add PostgreSQL checkpoint persistence`

- [ ] 20. **事件总线设计与实现**

  **What to do**:
  - 创建 `src/runtime/event_bus/__init__.py`
  - 创建 `src/runtime/event_bus/bus.py` - 事件总线核心
  - 实现发布-订阅模式
  - 支持同步和异步事件处理
  - 集成 Redis Pub/Sub 作为后端
  - 定义标准事件类型：IntentDetected、WorkflowStarted、StepCompleted 等

  **Must NOT do**:
  - 不替换现有直接调用（先并行运行，后续逐步迁移）

  **Recommended Agent Profile**:
  - **Category**: `deep`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Tasks 16-19
  - **Blocks**: Tasks 21-23, 26

  **References**:
  - `src/runtime/event_bus/` - 新建目录
  - Redis Pub/Sub: https://redis.io/docs/manual/pubsub/
  - Python asyncio: https://docs.python.org/3/library/asyncio.html

  **Acceptance Criteria**:
  - [ ] 事件总线可发布和订阅事件
  - [ ] 支持异步事件处理
  - [ ] 事件不丢失（至少一次交付）

  **QA Scenarios**:
  ```
  Scenario: 事件总线验证
    Tool: Bash (pytest)
    Steps:
      1. 订阅测试事件
      2. 发布事件
      3. 断言订阅者收到事件
    Expected Result: 事件正确传递
    Evidence: .sisyphus/evidence/task-20-event-bus.log
  ```

  **Commit**: YES
  - Message: `feat(runtime): implement event bus with Redis backend`

- [ ] 21. **核心流程事件化改造**

  **What to do**:
  - 修改 `RuntimeOrchestrator` 发布事件（替代直接调用）
  - 修改适配器调用为事件驱动
  - 修改安全校验为事件订阅
  - 保持向后兼容（事件和直接调用并存）

  **Must NOT do**:
  - 不删除直接调用（先并行运行）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Tasks 11, 20
  - **Blocks**: Task 24

  **References**:
  - `src/runtime/api/orchestrator.py` - RuntimeOrchestrator
  - `src/runtime/event_bus/bus.py` - 事件总线

  **Acceptance Criteria**:
  - [ ] 核心流程可通过事件驱动执行
  - [ ] 事件和直接调用结果一致
  - [ ] 性能影响可接受（< 10% 延迟增加）

  **QA Scenarios**:
  ```
  Scenario: 事件化流程验证
    Tool: Bash (pytest + curl)
    Steps:
      1. 运行 E2E 测试（事件模式）
      2. 断言结果与直接调用一致
      3. 断言延迟增加 < 10%
    Expected Result: 功能正确，性能可接受
    Evidence: .sisyphus/evidence/task-21-event-driven-flow.log
  ```

  **Commit**: YES
  - Message: `feat(runtime): migrate core flow to event-driven`

- [ ] 22. **OpenTelemetry 链路追踪**

  **What to do**:
  - 创建 `src/observability/tracing/__init__.py`
  - 集成 OpenTelemetry SDK
  - 实现自动 instrumentation（FastAPI、SQLAlchemy、Redis）
  - 实现自定义 span（意图识别、适配器调用、LangGraph 节点）
  - 配置 Jaeger/Zipkin 导出器

  **Must NOT do**:
  - 不修改业务逻辑（仅添加追踪）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 23)
  - **Blocked By**: Task 20
  - **Blocks**: Task 24

  **References**:
  - `src/observability/` - 新建目录
  - OpenTelemetry: https://opentelemetry.io/docs/
  - FastAPI Instrumentation: https://opentelemetry-python-contrib.readthedocs.io/

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
    Evidence: .sisyphus/evidence/task-22-tracing.log
  ```

  **Commit**: YES
  - Message: `feat(observability): add OpenTelemetry tracing`

- [ ] 23. **Prometheus 指标采集**

  **What to do**:
  - 创建 `src/observability/metrics/__init__.py`
  - 集成 Prometheus 客户端
  - 定义关键指标：请求数、延迟、错误率、适配器调用次数
  - 暴露 `/metrics` 端点
  - 配置 Grafana 仪表盘

  **Must NOT do**:
  - 不修改业务逻辑

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 22)
  - **Blocked By**: Task 20
  - **Blocks**: Task 24

  **References**:
  - `src/observability/metrics/` - 新建目录
  - Prometheus Python Client: https://github.com/prometheus/client_python
  - Grafana: https://grafana.com/docs/

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
    Evidence: .sisyphus/evidence/task-23-metrics.log
  ```

  **Commit**: YES
  - Message: `feat(observability): add Prometheus metrics`

- [ ] 24. **监控看板配置**

  **What to do**:
  - 创建 `deploy/grafana/dashboards/` 目录
  - 配置 Grafana 仪表盘 JSON
  - 包含：请求量、延迟分布、错误率、适配器健康度
  - 配置告警规则（高错误率、高延迟）

  **Must NOT do**:
  - 不修改后端代码

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocked By**: Tasks 22, 23
  - **Blocks**: None

  **References**:
  - `deploy/grafana/` - 新建目录
  - Grafana Dashboard: https://grafana.com/docs/grafana/latest/dashboards/

  **Acceptance Criteria**:
  - [ ] Grafana 仪表盘可导入
  - [ ] 包含所有关键指标可视化
  - [ ] 告警规则可触发

  **QA Scenarios**:
  ```
  Scenario: 监控看板验证
    Tool: Bash (curl)
    Steps:
      1. 导入 Grafana 仪表盘
      2. 断言面板显示正确
      3. 触发告警，断言通知发送
    Expected Result: 看板正常，告警生效
    Evidence: .sisyphus/evidence/task-24-dashboard.log
  ```

  **Commit**: YES
  - Message: `feat(deploy): add Grafana dashboard configuration`

- [ ] 25. **安全策略配置化**

  **What to do**:
  - 创建 `src/config/security_policy/dynamic.py`
  - 实现配置驱动的权限规则（替代硬编码）
  - 支持运行时更新策略（无需重启）
  - 实现策略版本管理

  **Must NOT do**:
  - 不删除现有硬编码规则（先并行运行）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocked By**: Task 11
  - **Blocks**: None

  **References**:
  - `src/config/security_policy/rules.py` - 现有硬编码规则
  - `src/security/authorization/service.py` - 权限服务
  - `src/security/risk_control/service.py` - 风险控制

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
    Evidence: .sisyphus/evidence/task-25-configurable-security.log
  ```

  **Commit**: YES
  - Message: `feat(security): add configurable security policies`

- [ ] 26. **Agent 注册发现机制**

  **What to do**:
  - 创建 `src/runtime/multi_agent/__init__.py`
  - 创建 `src/runtime/multi_agent/registry.py` - Agent 注册表
  - 实现 Agent 注册、发现、心跳机制
  - 定义 Agent 元数据：id、capabilities、role、health

  **Must NOT do**:
  - 不实现 Agent 间通信（留到 Task 27）

  **Recommended Agent Profile**:
  - **Category**: `deep`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 20
  - **Blocks**: Tasks 27, 28

  **References**:
  - `src/runtime/multi_agent/` - 新建目录
  - AutoGen Agent: https://microsoft.github.io/autogen/docs/tutorial/introduction
  - AgentScope Agent: https://doc.agentscope.io/

  **Acceptance Criteria**:
  - [ ] Agent 可注册到注册表
  - [ ] 支持按 capability 发现 Agent
  - [ ] 支持心跳检测

  **QA Scenarios**:
  ```
  Scenario: Agent 注册发现验证
    Tool: Bash (pytest)
    Steps:
      1. 注册测试 Agent
      2. 按 capability 查询 Agent
      3. 断言返回正确 Agent
    Expected Result: 注册发现正常
    Evidence: .sisyphus/evidence/task-26-agent-registry.log
  ```

  **Commit**: YES
  - Message: `feat(multi-agent): add agent registry and discovery`

- [ ] 27. **多 Agent 协调器**

  **What to do**:
  - 创建 `src/runtime/multi_agent/coordinator.py`
  - 实现 `MultiAgentCoordinator` 类
  - 支持任务分解和 Agent 分配
  - 支持结果聚合和冲突解决
  - 实现 RoundRobin、Priority 等调度策略

  **Must NOT do**:
  - 不实现复杂协商逻辑（简单协调即可）

  **Recommended Agent Profile**:
  - **Category**: `deep`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 26
  - **Blocks**: Task 28

  **References**:
  - `src/runtime/multi_agent/registry.py` - Agent 注册表
  - AutoGen GroupChat: https://microsoft.github.io/autogen/docs/tutorial/chat-termination

  **Acceptance Criteria**:
  - [ ] 协调器可分解任务并分配给 Agent
  - [ ] 支持结果聚合
  - [ ] 支持调度策略切换

  **QA Scenarios**:
  ```
  Scenario: 多 Agent 协调验证
    Tool: Bash (pytest)
    Steps:
      1. 创建多个测试 Agent
      2. 提交复杂任务
      3. 断言任务被分解并执行
    Expected Result: 协调正常
    Evidence: .sisyphus/evidence/task-27-multi-agent-coordinator.log
  ```

  **Commit**: YES
  - Message: `feat(multi-agent): add multi-agent coordinator`

- [ ] 28. **A2A 协议实现**

  **What to do**:
  - 创建 `src/runtime/a2a/__init__.py`
  - 实现 A2A (Agent-to-Agent) 通信协议
  - 支持任务委托和结果回调
  - 支持 Agent 间消息加密和鉴权

  **Must NOT do**:
  - 不实现完整 A2A 规范（仅核心功能）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 26
  - **Blocks**: None

  **References**:
  - `src/runtime/a2a/` - 新建目录
  - A2A Protocol: https://github.com/google/A2A

  **Acceptance Criteria**:
  - [ ] Agent 可相互发送任务
  - [ ] 支持结果回调
  - [ ] 支持基本鉴权

  **QA Scenarios**:
  ```
  Scenario: A2A 协议验证
    Tool: Bash (pytest)
    Steps:
      1. Agent A 委托任务给 Agent B
      2. Agent B 执行并回调结果
      3. 断言结果正确
    Expected Result: A2A 通信正常
    Evidence: .sisyphus/evidence/task-28-a2a-protocol.log
  ```

  **Commit**: YES
  - Message: `feat(a2a): implement agent-to-agent protocol`

- [ ] 29. **Milvus 向量检索**

  **What to do**:
  - 创建 `src/knowledge_extension/rag/milvus/__init__.py`
  - 实现 `MilvusVectorStore` 类
  - 支持文档嵌入和向量检索
  - 支持混合检索（向量 + 关键词）

  **Must NOT do**:
  - 不替换现有内存 RAG（仅添加新实现）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with Tasks 26-28)
  - **Blocked By**: Task 14
  - **Blocks**: Task 30

  **References**:
  - `src/knowledge_extension/rag/` - 现有 RAG 抽象
  - Milvus: https://milvus.io/docs/
  - PyMilvus: https://github.com/milvus-io/pymilvus

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
    Evidence: .sisyphus/evidence/task-29-milvus.log
  ```

  **Commit**: YES
  - Message: `feat(rag): add Milvus vector store`

- [ ] 30. **RAG 完整链路**

  **What to do**:
  - 创建 `src/knowledge_extension/rag/pipeline.py`
  - 实现完整 RAG 链路：检索 → 重排 → 上下文组装 → 生成
  - 集成 Milvus 向量检索
  - 实现引用溯源

  **Must NOT do**:
  - 不修改知识服务接口（仅内部实现）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Blocked By**: Task 29
  - **Blocks**: None

  **References**:
  - `src/knowledge_extension/service.py` - 知识服务
  - `src/knowledge_extension/rag/milvus/` - Milvus 实现

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
    Evidence: .sisyphus/evidence/task-30-rag-pipeline.log
  ```

  **Commit**: YES
  - Message: `feat(rag): implement complete RAG pipeline`

- [ ] 31. **K8s 部署配置**

  **What to do**:
  - 创建 `deploy/k8s/` 目录
  - 编写 Deployment、Service、ConfigMap、Secret YAML
  - 配置 HPA（水平自动扩缩容）
  - 配置 Ingress
  - 编写 Helm Chart

  **Must NOT do**:
  - 不修改应用代码

  **Recommended Agent Profile**:
  - **Category**: `quick`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5
  - **Blocked By**: Tasks 20, 26
  - **Blocks**: F1-F4

  **References**:
  - `deploy/` - 现有部署目录
  - Kubernetes: https://kubernetes.io/docs/
  - Helm: https://helm.sh/docs/

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
    Evidence: .sisyphus/evidence/task-31-k8s-deployment.log
  ```

  **Commit**: YES
  - Message: `feat(deploy): add Kubernetes deployment configuration`

---

## Final Verification Wave

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [ ] F1. **架构合规审计** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **代码质量审查** — `unspecified-high`
  Run `tsc --noEmit` + linter + `bun test`. Review all changed files for: `as any`/`@ts-ignore`, empty catches, console.log in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names (data/result/item/temp).
  Output: `Build [PASS/FAIL] | Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **集成测试验证** — `unspecified-high`
  Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration (features working together, not isolation). Test edge cases: empty state, invalid input, rapid actions. Save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **性能基准测试** — `deep`
  Run load tests with k6 or locust. Measure: API latency (p50/p95/p99), throughput (RPS), error rate, resource usage (CPU/memory). Compare against baseline. Identify bottlenecks.
  Output: `Latency [p50/p95/p99] | Throughput [RPS] | Error Rate [%] | Resource [CPU/Mem] | VERDICT`

---

## Commit Strategy

- **阶段一**: `feat(adapters): define adapter protocol contracts`
- **阶段一**: `feat(domain): add {audit_risk,drg_dip,medical_record,appeal,order_fee} domain models`
- **阶段一**: `feat(runtime): introduce FastAPI dependency injection`
- **阶段一**: `refactor(adapters): implement adapter protocols`
- **阶段一**: `feat(runtime): unify LangGraph execution engine`
- **阶段一**: `chore(runtime): deprecate legacy orchestration/planning`
- **阶段一**: `refactor(api): decouple routes.py into orchestrator service`
- **阶段一**: `refactor(skill): adapt skill engine to adapter protocols`
- **阶段一**: `test(adapters): add protocol contract tests`
- **阶段二**: `feat(storage): add PostgreSQL storage implementation`
- **阶段二**: `feat(storage): add Redis cache implementation`
- **阶段二**: `feat(runtime): add workflow state persistence`
- **阶段二**: `feat(task): add task state persistence`
- **阶段二**: `feat(audit): add audit log persistence`
- **阶段二**: `feat(langgraph): add PostgreSQL checkpoint persistence`
- **阶段二**: `feat(runtime): implement event bus with Redis backend`
- **阶段二**: `feat(runtime): migrate core flow to event-driven`
- **阶段二**: `feat(observability): add OpenTelemetry tracing`
- **阶段二**: `feat(observability): add Prometheus metrics`
- **阶段二**: `feat(deploy): add Grafana dashboard configuration`
- **阶段二**: `feat(security): add configurable security policies`
- **阶段三**: `feat(multi-agent): add agent registry and discovery`
- **阶段三**: `feat(multi-agent): add multi-agent coordinator`
- **阶段三**: `feat(a2a): implement agent-to-agent protocol`
- **阶段三**: `feat(rag): add Milvus vector store`
- **阶段三**: `feat(rag): implement complete RAG pipeline`
- **阶段三**: `feat(deploy): add Kubernetes deployment configuration`

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
- [ ] 所有适配器实现统一 Protocol，可通过配置切换实现
- [ ] 领域层覆盖医保全部核心业务对象
- [ ] 单一 LangGraph 执行路径，旧版路径已弃用
- [ ] 状态持久化：重启后 workflow/task/audit 不丢失
- [ ] 消息驱动：模块间通过事件总线通信
- [ ] 可观测性：链路追踪、性能指标、监控看板
- [ ] 多 Agent：复杂场景可分解为多个专业 Agent 协同
- [ ] 所有测试通过（单元测试、集成测试、E2E测试）
- [ ] 代码覆盖率 > 80%
- [ ] 性能基准：p95 延迟 < 500ms，错误率 < 0.1%
