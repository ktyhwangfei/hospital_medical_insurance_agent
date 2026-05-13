# 架构评估报告：医保 AI 平台 vs Datawhale Agent 框架实践

## 评估背景

基于 Datawhale hello-agents 第六章《框架开发实践》对业界主流 Agent 框架（AutoGen、AgentScope、CAMEL、LangGraph）的系统性分析，结合当前 MVP 实现现状，对架构设计进行阶段性评估。

**评估日期**: 2026-05-11
**评估范围**: 当前 MVP 实现（src/ 目录）vs 目标架构（docs/steering/架构设计.md）
**参考框架**: AutoGen、AgentScope、CAMEL、LangGraph

---

## 一、业界框架核心洞察

### 1.1 四种框架设计哲学

| 框架 | 核心思想 | 协作模式 | 控制方式 | 适用场景 |
|------|----------|----------|----------|----------|
| **AutoGen** | 对话驱动协作 | 多角色群聊 | 系统消息角色定义 | 流程化任务、软件开发模拟 |
| **AgentScope** | 工程化优先平台 | 消息驱动、异步解耦 | MsgHub消息路由 | 大规模并发、分布式部署 |
| **CAMEL** | 角色扮演与引导性提示 | 双智能体深度协作 | Inception Prompting | 创意内容生成、研究辅助 |
| **LangGraph** | 状态机与有向图建模 | 节点-边工作流 | 条件边动态路由 | 严格流程应用、可审计系统 |

### 1.2 关键架构模式

**AgentScope 消息驱动架构**:
- `Msg`: 统一消息格式，支持多模态
- `MsgHub`: 消息中心，异步路由与分布式通信
- `AgentBase`: 智能体基类，核心为 `reply` 方法
- **核心创新**: 组合式架构 + 消息驱动模式（非继承式）

**LangGraph 图结构工作流**:
- 节点(Node): 具体计算步骤（调用LLM、执行工具）
- 边(Edge): 节点间转换逻辑
- **革命性**: 原生支持循环，适合迭代、反思、自纠正

### 1.3 设计哲学权衡
- **涌现式协作** (AutoGen/CAMEL) vs **显式控制** (LangGraph)
- **灵活性** vs **可靠性/可观测性/可审计性**
- AgentScope 试图在两者之间找到平衡

---

## 二、当前项目架构分析

### 2.1 已实现部分（MVP）

**分层结构**:
```
runtime/api (FastAPI 路由)
  → runtime/intent (意图识别)
  → security/risk_control (高风险拦截)
  → security/authorization (权限校验)
  → business_scenarios/{settlement_exception_guide, pre_discharge_joint_qc}
  → adapters/* (外部系统防腐层，当前均为内存实现)
  → knowledge_extension/knowledge (错误码/政策知识库)
  → 返回 AgentResponse 结构
```

**核心模块状态**:
- ✅ runtime/api: FastAPI 路由实现
- ✅ runtime/intent: LLM解析 + 关键词降级 + 注册表
- ✅ runtime/langgraph: 两个场景的图结构工作流
- ✅ business_scenarios: 结算异常导办、出院前联合质控
- ✅ adapters: 7个内存适配器
- ✅ security: 权限、脱敏、风险控制、审计
- ⚠️ runtime/orchestration: 简单顺序执行器
- ⚠️ runtime/planning: 基础计划生成
- ❌ gateway/: 未实现
- ❌ model_service/: 未实现（除基础gateway）
- ❌ knowledge_extension/rag: 未实现
- ❌ data_platform/vector: 未实现

### 2.2 两个并行的执行路径

**路径 1 – 旧版（顺序编排）**:
`process_chat_request()` → `orchestration/service.py:execute_plan()` → `planning/service.py:build_execution_plan()` → 业务场景服务函数
- 顺序执行 — 无 DAG、无并行、无检查点

**路径 2 – 新版（LangGraph 状态机）**:
`_try_langgraph_execution()` → LangGraph 图构建 → `graph.invoke()` → 通过条件边执行节点
- 支持通过 `interrupt()` 实现人工确认
- 使用 `MemorySaver` 检查点器（内存中的 LangGraph 持久化）
- 优先级高于旧版路径

### 2.3 关键代码文件映射

| 模块 | 文件路径 | 职责 | 状态 |
|------|----------|------|------|
| API入口 | `src/runtime/api/routes.py` | 主路由、请求处理、安全校验 | 629行，上帝模块 |
| 意图识别 | `src/runtime/intent/parser.py` | LLM解析+关键词降级 | 63行 |
| 结算异常图 | `src/runtime/langgraph/settlement_exception.py` | 状态机工作流 | 124行 |
| 出院质控图 | `src/runtime/langgraph/pre_discharge_qc.py` | 状态机工作流 | 196行 |
| 编排执行 | `src/runtime/orchestration/service.py` | 简单if-else分发 | 29行，薄弱 |
| 任务规划 | `src/runtime/planning/service.py` | 生成ExecutionPlan | 31行，未被执行 |
| 技能引擎 | `src/runtime/skill_registry/engine.py` | 顺序执行Skill | 117行 |
| 适配器基类 | `src/adapters/base/models.py` | 结果类型定义 | 46行 |
| 结算异常场景 | `src/business_scenarios/settlement_exception_guide/service.py` | 业务逻辑 | 92行 |
| 出院质控场景 | `src/business_scenarios/pre_discharge_joint_qc/service.py` | 业务逻辑 | 149行 |

---

## 三、详细架构评估

### 3.1 LangGraph 使用评估 ✅

**当前实现**:
- `runtime/langgraph/settlement_exception.py`: 结算异常导办图
  - 节点: validate_claim → check_high_risk → [human_confirmation] → query_error_knowledge → build_recommendation
  - 条件边: route_after_high_risk_check (高风险→人工确认)
  - 状态: SettlementState (claim_detail, error_code, error_detail, recommendation)
  
- `runtime/langgraph/pre_discharge_qc.py`: 出院前联合质控图
  - 节点: get_patient_summary → run_qc_rules → check_qc_issues → [human_confirmation] → build_qc_report
  - 条件边: route_qc_issues (有问题→人工确认)
  - 状态: PreDischargeState (patient_summary, quality_issues, rule_results, qc_recommendation)

**与 Datawhale 评价对比**:
- ✅ **状态机精确控制**: LangGraph 的节点-边模型完美匹配医保场景的严格流程要求
- ✅ **循环支持**: interrupt() + Command(resume) 实现人工确认循环
- ✅ **可审计性**: 每个节点执行都有明确的状态转换，便于审计追踪
- ⚠️ **缺少可视化**: 未利用 LangGraph 的图结构可视化能力

### 3.2 消息驱动架构缺失 ⚠️

**Datawhale AgentScope 核心优势**:
- MsgHub 实现异步解耦和位置透明
- 智能体只需向消息中心发送消息，无需关心接收者
- 天然支持分布式部署和高并发
- 每条消息可被记录、追踪、分析

**当前项目问题**:
```python
# 当前: 直接函数调用，强耦合
def guide_settlement_exception(patient_id, encounter_id):
    claim = query_claim(patient_id, encounter_id)  # 直接调用
    error_detail = get_error_detail(error_code)    # 直接调用
    # ...

# 对比: 消息驱动（理想状态）
def guide_settlement_exception(patient_id, encounter_id):
    msg_hub.send("query_claim", {"patient_id": patient_id, "encounter_id": encounter_id})
    result = msg_hub.receive("query_claim_result")
    # ...
```

**影响**:
- 模块间耦合度高
- 难以实现分布式部署
- 调试复杂多步骤流程困难
- 缺少消息级别的可观测性

### 3.3 多智能体协作缺失 ❌

**Datawhale 框架对比**:
- AutoGen: 多角色群聊（RoundRobinGroupChat）
- AgentScope: MsgHub + Pipeline 多智能体协作
- CAMEL: 双智能体深度协作

**当前项目**: 
- 单 Agent 模式（一个请求一个工作流）
- 无多 Agent 协同场景
- 无角色分工（医生、病案室、医保办等是角色权限，不是独立 Agent）

**医保场景潜在需求**:
- 出院前质控: 需要"医生 Agent"、"病案室 Agent"、"医保办 Agent"协同
- 拒付申诉: 需要"证据收集 Agent"、"材料生成 Agent"、"审核 Agent"协同
- DRG/DIP 运营: 需要"数据分析 Agent"、"规则解释 Agent"、"建议生成 Agent"协同

### 3.4 编排层薄弱 ⚠️

**当前实现** (`runtime/orchestration/service.py`):
```python
def execute_plan(context, plan):
    steps = [StepState(step_id=step.step_id, status="completed") for step in plan.steps]
    if plan.scenario == "settlement_exception_guidance":
        response = guide_settlement_exception(...)  # 直接调用场景服务
    elif plan.scenario == "pre_discharge_quality_control":
        response = run_pre_discharge_qc(...)        # 直接调用场景服务
    # ...
```

**问题**:
- 仅为简单的 if-else 分发
- 未实现 DAG 调度
- 无并行执行能力
- 无断点续执能力
- 计划生成 (`planning/service.py`) 与执行脱节

**Datawhale 推荐**: AgentScope Pipeline 系统支持顺序、并发等多种执行模式

### 3.5 工程化实践对比

| 维度 | Datawhale AgentScope | 当前项目 | 差距 |
|------|---------------------|----------|------|
| **异步执行** | 原生支持 | 部分支持(LangGraph) | 中等 |
| **状态持久化** | 内置支持 | 内存(MemorySaver) | 大 |
| **分布式通信** | MsgHub | 无 | 大 |
| **可观测性** | 消息追踪 | 审计日志 | 中等 |
| **容错恢复** | 内置 | 无 | 大 |
| **并发性能** | 优秀 | 未测试 | 未知 |
| **工具注册** | 标准化 | 有基础 | 小 |

---

## 四、架构债务详细清单

### 债务一：无适配器协议/契约 🔴
- **现状**：适配器为裸类，无 Protocol/ABC 约束
- **影响**：替换真实适配器需触及所有引用点
- **文件影响**：`business_scenarios/*/service.py`、`runtime/langgraph/*.py`、`runtime/skill_registry/engine.py`
- **改进**：为每种适配器定义 Protocol（如 `InsuranceInterfacePort`）

### 债务二：依赖注入缺失 🔴
- **现状**：适配器、数据存储直接实例化
- **影响**：模块耦合度高，单元测试需大量 Mock
- **文件影响**：全项目
- **改进**：引入 FastAPI `Depends` 或 Provider 模式

### 债务三：双重执行引擎 🟡
- **现状**：旧版路径与新版 LangGraph 路径共存
- **影响**：职责重叠，维护成本高
- **文件影响**：`runtime/orchestration/service.py`、`runtime/planning/service.py`
- **改进**：统一为 LangGraph 执行模型

### 债务四：核心入口耦合 🔴
- **现状**：`runtime/api/routes.py`（629行）协调所有层
- **影响**：上帝模块，变更影响面广
- **改进**：抽象 `RuntimeOrchestrator` 服务

### 债务五：完全内存化 🔴
- **现状**：所有状态存储为内存字典
- **影响**：重启后全部丢失
- **改进**：PostgreSQL + Redis + Milvus

### 债务六：领域层不完整 🟡
- **现状**：仅实现 patient/insurance/task/common
- **缺失**：audit_risk、drg_dip、medical_record、appeal、order_fee
- **改进**：按业务优先级补齐

### 债务七：消息驱动缺失 🔴
- **现状**：模块间直接函数调用
- **影响**：无法异步解耦，不支持分布式
- **改进**：引入事件总线

### 债务八：单 Agent 限制 🟡
- **现状**：一个请求对应一个工作流
- **影响**：复杂场景难以分解为专业 Agent 协同
- **改进**：设计 Agent 注册发现机制

---

## 五、演进路线规划

### 阶段一：MVP 完善（当前 → 2个月内）

**目标**: 补齐领域层、统一执行引擎、建立适配器契约

**关键任务**:
1. 定义适配器 Protocol（InsuranceInterfacePort、BillingPort 等）
2. 补齐缺失的领域模型（audit_risk、drg_dip、medical_record、appeal、order_fee）
3. 统一执行引擎：将旧版 orchestration/service.py 逻辑迁移到 LangGraph
4. 引入依赖注入：使用 FastAPI Depends 注入适配器实例

**预期产出**:
- 所有适配器实现统一 Protocol
- 领域层完整覆盖医保核心业务
- 单一 LangGraph 执行路径
- 可测试的模块化代码

### 阶段二：生产准备（2个月 → 4个月）

**目标**: 状态持久化、消息驱动、可观测性

**关键任务**:
1. 状态持久化：PostgreSQL 存储 workflow/task/audit，Redis 存储会话热状态
2. 消息驱动：引入事件总线（Redis Pub/Sub 或 RabbitMQ），解耦模块通信
3. 可观测性：链路追踪（OpenTelemetry）、性能指标（Prometheus）、运行监控看板
4. 安全增强：配置化策略（替代硬编码规则）、动态权限

**预期产出**:
- 重启后状态不丢失
- 模块间异步解耦
- 完整的监控告警体系
- 生产级安全策略

### 阶段三：平台化（4个月 → 6个月）

**目标**: 多 Agent 协作、分布式部署、完整生态

**关键任务**:
1. 多 Agent 架构：Agent 注册发现、任务委托、A2A 协议实现
2. 分布式部署：服务拆分（模型服务、知识服务独立部署）、负载均衡
3. 完整 MCP/A2A：标准化工具调用协议、外部 Agent 协同
4. RAG 增强：向量检索（Milvus）、重排、引用溯源

**预期产出**:
- 多 Agent 协同处理复杂场景
- 微服务架构支持水平扩展
- 标准化协议对接外部系统
- 智能知识检索与问答

---

## 六、与 Datawhale 框架的融合策略

**不照搬任何单一框架，汲取各家之长**:

1. **以 LangGraph 为执行核心**：保留状态机+图结构，这是当前架构的最大优势
2. **引入 AgentScope 工程化**：消息驱动、异步解耦、可观测性、容错恢复
3. **参考 AutoGen 协作模式**：多角色群聊设计，用于未来多 Agent 协同场景
4. **保持 HelloAgents 简洁性**：Tool/Skill 统一抽象，降低学习成本

**关键设计原则**:
- **显式控制优先**：医保场景要求可审计、可追溯，牺牲部分灵活性换取可靠性
- **渐进式演进**：不推倒重来，在现有 LangGraph 基础上逐步增强
- **接口先行**：先定义 Protocol/契约，再替换实现
- **状态外置**：将内存状态逐步迁移到外部存储，实现无状态服务

---

## 七、关键决策记录

### 决策 1: 保留 LangGraph 作为核心执行引擎
- **理由**: 医保场景需要严格流程控制、可审计性、状态机精确控制
- **替代方案**: AutoGen（对话驱动，不够严格）、AgentScope（消息驱动，需大规模重构）
- **风险**: LangGraph 生态较新，长期维护需关注

### 决策 2: 引入消息驱动机制（阶段二）
- **理由**: 当前模块耦合度高，消息驱动可提升可维护性和可扩展性
- **实现方式**: Redis Pub/Sub 或 RabbitMQ，非自研 MsgHub
- **风险**: 引入分布式复杂度，需处理消息可靠性

### 决策 3: 单 Agent → 多 Agent 演进（阶段三）
- **理由**: 当前 MVP 足够，但未来复杂场景需要多 Agent 协同
- **演进路径**: 先完善单 Agent 能力，再逐步拆分专业 Agent
- **风险**: 多 Agent 协作增加系统复杂度，需精心设计协调机制

### 决策 4: 优先补齐领域层而非重构架构
- **理由**: 领域模型是业务核心，先夯实基础再优化架构
- **顺序**: 领域层 → 适配器契约 → 执行引擎统一 → 消息驱动
- **风险**: 延迟架构优化可能增加后续重构成本

---

## 八、风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| LangGraph 生态变化 | 中 | 高 | 封装抽象层，隔离框架细节 |
| 消息驱动引入复杂度 | 高 | 中 | 渐进式引入，先单进程异步 |
| 多 Agent 协调困难 | 中 | 高 | 参考 AutoGen/AgentScope 最佳实践 |
| 状态持久化性能瓶颈 | 中 | 中 | 分层存储（热数据Redis，冷数据PostgreSQL） |
| 领域模型设计偏差 | 低 | 高 | 与业务专家充分沟通，迭代验证 |

---

*本报告作为架构设计文档的补充，指导后续迭代开发。建议每两个月回顾一次，根据实际进展调整演进路线。*
