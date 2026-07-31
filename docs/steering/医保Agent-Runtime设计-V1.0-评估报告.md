# 医保 Agent Runtime 设计（V1.0）— 评估报告

> **评估日期**：2026-07-30 ｜ **评估人**：Architect
> **评估对象**：`docs/steering/医保Agent-Runtime设计-V1.0.md`
> **配套资料**：`架构设计.md`、`语义层设计文档.md`、`src/domain/AGENTS.md`、`src/runtime/` 源码

---

## 一、文档综合评价

### 1.1 优点

| 维度 | 评价 |
|------|------|
| **架构定位清晰** | 明确区分了 Runtime（状态管理）与语义层（知识承载），避免了"什么都管"的臃肿设计 |
| **问题诊断准确** | 对传统 RAG 五个问题的归纳（无状态、无记忆、无连续追问、无指代解析、Prompt 膨胀）切中要害 |
| **渐进策略合理** | ADR-006 的分阶段建设（先替换 ad-hoc 拼装，再上智能升级）符合项目现状 |
| **现状衔接务实** | 每个模块都给出了"现状地基 → 落位建议"的映射，不是推倒重来 |
| **Reasoning State 差异化** | 第 6 模块是亮点，区分了"事实记忆"与"推理过程"，这是医保 Agent 的核心差异化能力 |
| **ADR 机制规范** | 6 条架构决策记录覆盖了关键权衡，为后续评审提供了讨论基础 |
| **对齐意识强** | §十三明确与通用语言字典对齐，体现了契约 2"同步更新"的遵循 |

### 1.2 存在的问题

| # | 问题 | 严重程度 | 说明 |
|---|------|---------|------|
| 1 | **Context Planner 与现有意图识别的边界模糊** | 中 | 文档说 Planner 负责"决定需要哪些上下文"，但 `runtime/intent/` 已经做了一部分实体识别和指标解析，两者职责有重叠 |
| 2 | **Memory Manager 的"压缩"操作定义不清** | 中 | "多轮压缩为结论"具体怎么做？调用模型服务摘要？还是规则驱动？ |
| 3 | **Token Budget 机制缺少量化设计** | 中高 | "摘要而非截断"很好，但没有给出预算分配策略（如 Settlement 占 40%、Policy 占 30% 等） |
| 4 | **Reasoning State 与 LangGraph checkpoint 的集成细节缺失** | 中 | ADR-004 说"复用 checkpoint"，但具体如何扩展字段、如何序列化推理链，没有展开 |
| 5 | **缺少与现有 `scenario_executor.py` 的交互设计** | 高 | `UnifiedScenarioExecutor` 是当前实际入口，Runtime 六模块如何嵌入这个流程，文档没有明确 |
| 6 | **Session 持久化与现有 WorkflowInstance 的关系未厘清** | 中 | `WorkflowInstance` 已有 `session_id` 字段，新的 `BusinessSession` 是替代还是共存？ |
| 7 | **模块关系是平铺不是管道** | 建议 | 六模块平铺让人误解为并列关系，实际上应组织为"会话层 → 规划层 → 组装层"的三层管道 |

---

## 二、核心架构调整建议

### 2.1 从"六模块并列"到"三层管道"

当前文档把六个模块平铺，容易让人误解为它们是并列关系。实际上它们应该构成一个**三层处理管道**：

```
┌─────────────────────────────────────────┐
│  Layer 1: 会话层（Session + Memory）      │
│  - Business Session: 当前业务场景锚点      │
│  - Business Memory: 已理解的事实缓存       │
│  - Memory Manager: 事实生命周期管理        │
├─────────────────────────────────────────┤
│  Layer 2: 规划层（Planner）               │
│  - Context Planner: 需要什么（What）       │
│  - 意图识别增强: 指代消解、主体切换检测      │
├─────────────────────────────────────────┤
│  Layer 3: 组装层（Composer + Reasoning）  │
│  - Context Composer: 怎么组织（How）       │
│  - Reasoning State: 推理链维护            │
└─────────────────────────────────────────┘
```

**关键调整**：把 Context Planner 从"独立模块"重新定位为**意图识别管道的增强阶段**，而不是并列的新模块。

### 2.2 与 `scenario_executor.py` 的集成点

这是最关键的设计决策。当前 `UnifiedScenarioExecutor.execute()` 的流程是：

```
1. @-mention skill → 直接执行
2. 关键词 skill 匹配 → 执行
3. LangGraph 场景 → 图执行
4. 费用问题 → Policy QA 管道
5. MCP → 工具调用
```

**Runtime 六模块应该嵌入在步骤 2 和 3 之间**，作为横切关注点：

```
1. @-mention skill → 直接执行（跳过 Runtime 增强，Skill 自带上下文）
2. 关键词 skill 匹配 → 执行（跳过 Runtime 增强）
3. === Runtime 上下文增强（横切）===
   a. 加载/创建 Session
   b. 加载 Memory
   c. Context Planner：决定需要什么
   d. 按需下探语义层回填
   e. Context Composer：组装 LLM Context
   f. 加载 Reasoning State
   g. 注入增强后的上下文
4. LangGraph / Policy QA / MCP → 使用增强的上下文执行
```

**关键原则**：Runtime 增强是**横切关注点**，不应该替换现有的执行流程，而是为其提供"更聪明的上下文"。

---

## 三、精确代码落位建议

### 3.1 落位总表

| 设计模块 | 建议落位 | 策略 |
|---------|---------|------|
| Business Session | **演进** `src/runtime/context/models.py` | 在 `RuntimeContext` 上扩展跨轮字段，不新建 `BusinessSession` 类 |
| Business Memory | **新建** `src/runtime/memory/` | MemoryStore + MemoryManager |
| Memory Manager | **新建** `src/runtime/memory/manager.py` | 生命周期逻辑，复用 `runtime_state/store.py` 工厂模式 |
| Context Planner | **增强** `src/runtime/intent/planner.py` | 作为意图识别第三阶段，不独立建目录 |
| Context Composer | **新建** `src/runtime/context_composer/` | 收编 `policy_qa/*` 的 ad-hoc 拼装能力 |
| Reasoning State | **演进** `src/runtime/runtime_state/models.py` | 扩展 `WorkflowInstance`，不做独立模块 |

### 3.2 落位 1：RuntimeContext 升级（替代独立 BusinessSession）

```python
# src/runtime/context/models.py — 演进而非新建
class RuntimeContext(BaseModel):
    # === 保留现有字段 ===
    request_id: str
    workflow_id: str
    user_id: str
    role: str
    message: str
    patient_id: str | None = None
    encounter_id: str | None = None
    intent: str
    intent_confidence: float
    intent_entities: dict[str, Any] = Field(default_factory=dict)
    intent_citations: list[str] = Field(default_factory=list)
    requested_at: str
    mentioned_skill_ids: list[str] = Field(default_factory=list)
    
    # === 新增：跨轮会话状态 ===
    session_id: str | None = None           # 跨轮会话标识
    current_topic: str | None = None        # 当前话题
    current_settlement_id: str | None = None  # 当前结算
    active_memory_ids: list[str] = Field(default_factory=list)  # 活跃记忆
    conversation_turns: list[Turn] = Field(default_factory=list)  # 对话轮次

    # === 新增：Runtime 增强注入 ===
    enriched_memories: list[BusinessMemory] | None = None  # 增强后的记忆
    llm_context: LLMContext | None = None                  # 组装后的 LLM Context
    reasoning_state: ReasoningState | None = None          # 推理状态
```

**理由**：
- `RuntimeContext` 已经是全系统的事实标准（`orchestrator.py`、`scenario_executor.py`、所有 Skill 都在用）
- 新增 `BusinessSession` 会导致"两个上下文对象"的混乱
- 跨轮持久化通过 `session_id` + `SessionStore` 实现，`RuntimeContext` 作为运行时载体

### 3.3 落位 2：Business Memory + Memory Manager

```python
# src/runtime/memory/models.py
class BusinessMemory(BaseModel):
    memory_id: str
    session_id: str
    type: MemoryType                # PATIENT / VISIT / SETTLEMENT / POLICY / RULE / ...
    ref_id: str | None = None       # 领域对象标识
    object_snapshot: dict = Field(default_factory=dict)  # 关键字段快照
    importance: float = 0.5         # 0~1
    confidence: float = 0.5         # 0~1
    expire_policy: ExpirePolicy = ExpirePolicy.TOPIC
    relations: list[str] = Field(default_factory=list)  # 关联 memory_id
    version: int = 1                # 快照版本，用于刷新检测
    last_used_at: str
    created_at: str

# 新增 ExpirePolicy.TIME
class ExpirePolicy(str, Enum):
    SESSION = "session"     # 会话结束即失效
    TOPIC = "topic"         # 话题切换即失效
    STICKY = "sticky"       # 跨话题保留（如政策/规则）
    TIME = "time"           # 时间过期（如 30 分钟无活动）

# src/runtime/memory/manager.py
class MemoryManager:
    def __init__(self, store: MemoryStore):
        self._store = store
    
    def upsert(self, memory: BusinessMemory) -> BusinessMemory: ...
    def get_for_context(self, session_id: str, context: RuntimeContext) -> list[BusinessMemory]: ...
    def get_or_resolve(self, session_id: str, type: MemoryType, ref_id: str | None) -> BusinessMemory | None: ...
    def expire_by_policy(self, session_id: str, policy: ExpirePolicy) -> int: ...
    def invalidate_object(self, session_id: str, object_kind: str) -> int: ...
    def expire_on_topic_change(self, session_id: str, new_topic: str) -> int: ...
    def compress(self, session_id: str, keep_types: list[MemoryType]) -> None: ...
    def refresh_from_semantic(self, memory: BusinessMemory) -> BusinessMemory: ...
```

**存储复用**：复用 `runtime_state/store.py` 的工厂模式，新增 `MemoryStore` Protocol + PG/内存双实现，`USE_MEMORY_STORAGE` 兜底。

### 3.4 落位 3：Context Planner → 增强 `runtime/intent/`

```python
# src/runtime/intent/planner.py — 新增
"""
Context Planner — 意图识别的增强阶段。

输入：IntentResult + RuntimeContext（含 session/memory）
输出：ContextNeed（需要加载哪些业务对象）

与现有模块的协作：
- parser.py: 解析用户意图 → IntentResult
- skill_matcher.py: 匹配 Skill
- planner.py: 规划上下文（本模块）

执行流程：
1. 从意图识别结果提取所需业务对象类型
2. 检查 Memory 中是否已有
3. 缺失的标记 must_query_semantic=True
4. 检测业务主体切换（patient_id 变更）
"""

class ContextNeed(BaseModel):
    object_types: list[str] = Field(default_factory=list)   # 需要哪些 BusinessObject 类型
    memory_ids: list[str] = Field(default_factory=list)     # 优先命中记忆
    must_query_semantic: bool = False                       # 记忆缺失则下探语义层
    reasoning_refs: list[str] = Field(default_factory=list) # 关联推理状态

class ContextPlanner:
    def plan(self, 
             intent_result: IntentResult,
             context: RuntimeContext,
             memories: list[BusinessMemory]) -> ContextNeed: ...
```

**理由**：
- 意图识别的自然流程：解析意图 → 匹配 Skill → 规划上下文
- `intent/` 目录已有 `parser.py`、`skill_matcher.py`、`knowledge.py`，Planner 是合理延伸
- 避免目录过度扩散（当前 `runtime/` 下已有 15+ 子目录）

### 3.5 落位 4：Context Composer

```python
# src/runtime/context_composer/composer.py
class ContextComposer:
    """
    统一上下文编排器，收编 policy_qa 的 ad-hoc 拼装能力。
    
    策略：
    1. 按 importance + recency 排序记忆
    2. 高优先级记忆全量放入
    3. 中优先级记忆放入摘要
    4. 低优先级记忆丢弃
    5. 保留 token_budget 的 10% 给 reasoning chain
    """
    
    def __init__(self, 
                 retriever: PolicyRetriever | None = None,
                 summarizer: ModelGateway | None = None):
        self._retriever = retriever
        self._summarizer = summarizer
    
    def compose(self, 
                need: ContextNeed,
                memories: list[BusinessMemory],
                reasoning: ReasoningState | None = None,
                token_budget: int = 4000) -> LLMContext: ...
```

**关键决策**：Composer 内部保留 `policy_qa/structured_policy_retriever` 作为"政策检索策略"之一，而不是删除它。

### 3.6 Token Budget 量化策略

```python
# src/runtime/context_composer/budget.py
class TokenBudget:
    """Token 预算分配策略。"""
    
    DEFAULT_BUDGET = 4000
    
    ALLOCATION = {
        "session_summary": 0.05,      # 5%  会话摘要
        "current_entity": 0.30,       # 30% 当前业务实体
        "related_entities": 0.20,     # 20% 相关实体
        "reasoning_chain": 0.15,      # 15% 推理链
        "conversation": 0.20,         # 20% 对话历史
        "reserve": 0.10,              # 10% 预留
    }
    
    def allocate(self, total: int) -> dict[str, int]:
        return {k: int(total * v) for k, v in self.ALLOCATION.items()}
```

**摘要策略**：
- 超出预算时，按 importance 排序，低 importance 记忆调用 `ModelGateway` 生成摘要
- 摘要长度 = 原长度的 20%（经验值）
- 保留 `ref_id` 和 `confidence`，丢弃 `object_snapshot` 中的非关键字段

### 3.7 落位 5：Reasoning State → 扩展 WorkflowInstance

```python
# src/runtime/runtime_state/models.py — 演进
class StepState(BaseModel):
    step_id: str
    status: str
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    error: str | None = None
    audit_refs: list[str] = Field(default_factory=list)
    reasoning_chain: list[ReasoningStep] = Field(default_factory=list)  # 新增

class WorkflowInstance(BaseModel):
    workflow_id: str
    scenario: str
    status: str
    current_step: str | None = None
    steps: list[StepState] = Field(default_factory=list)
    audit_refs: list[str] = Field(default_factory=list)
    knowledge_events: list[dict] = Field(default_factory=list)
    knowledge_degradation_reasons: list[str] = Field(default_factory=list)
    session_id: str | None = None
    patient_id: str | None = None
    reasoning_state: ReasoningState | None = None  # 新增
```

**与 LangGraph checkpoint 的集成**：
- LangGraph 的 `checkpoint.py` 保存的是图执行状态（节点、边、中断点）
- `ReasoningState` 保存的是业务推理状态（事实、假设、结论）
- 两者通过 `workflow_id` 关联，而不是合并存储

---

## 四、落地路线图（三阶段）

### 阶段一：地基建设（2 周）—— 低风险、高回报

| 任务 | 落位 | 验证标准 | 依赖 |
|------|------|---------|------|
| 1.1 升级 `RuntimeContext` 添加跨轮字段 | `src/runtime/context/models.py` | UT: session_id 跨轮保持一致 | 无 |
| 1.2 新建 `BusinessMemory` 模型 | `src/runtime/memory/models.py` | UT: CRUD | 1.1 |
| 1.3 新建 `MemoryStore` + `MemoryManager` | `src/runtime/memory/` | UT: CRUD + 过期策略 + PG/内存双实现 | 1.2 |
| 1.4 新建 `ContextComposer` 骨架 | `src/runtime/context_composer/` | UT: compose 排序 + 预算分配 | 1.2 |
| 1.5 收编 `structured_policy_retriever` 为 Composer 策略 | `src/runtime/context_composer/` | API 测试: 费用问题仍能正常回答 | 1.4 |
| 1.6 扩展 `WorkflowInstance` 新增 `reasoning_state` | `src/runtime/runtime_state/models.py` | UT: 序列化/反序列化 | 无 |
| 1.7 新增 `MemoryStore` Protocol + PG/内存双实现 | `src/data_platform/storage/memory/` | UT: 配 `USE_MEMORY_STORAGE` 回退 | 1.3 |

**风险**：极低。所有新增模块都是"旁路"，不影响现有执行流程。

### 阶段二：智能增强（2 周）—— 中等风险

| 任务 | 落位 | 验证标准 | 依赖 |
|------|------|---------|------|
| 2.1 实现 `ContextPlanner`（意图识别增强） | `src/runtime/intent/planner.py` | Flow 测试: 连续追问正确识别所需上下文 | 1.1, 1.3 |
| 2.2 实现 Token Budget + 摘要策略 | `src/runtime/context_composer/budget.py` | UT: 超长上下文正确摘要 | 1.4 |
| 2.3 `scenario_executor.py` 集成 Runtime 增强 | `src/runtime/scenario_executor.py` | Flow 测试: 结算异常导办 + 连续追问 | 2.1, 2.2 |
| 2.4 实现 `ReasoningState` 推理链维护 | `src/runtime/reasoning/` | UT: 推理链正确序列化/反序列化 | 1.6 |
| 2.5 补充 `ExpirePolicy.TIME` 时间过期 | `src/runtime/memory/manager.py` | UT: 30 分钟无活动自动失效 | 1.3 |
| 2.6 `ContextPlanner` 集成主体切换检测 | `src/runtime/intent/planner.py` | Flow 测试: "查询张三"→"查询李四"正确切换 | 2.1 |

**风险**：中。需要修改 `scenario_executor.py` 的核心流程，必须有 Flow 测试覆盖。

### 阶段三：全面验证（1 周）—— 低风险

| 任务 | 验证标准 |
|------|---------|
| 3.1 全量回归测试 | 单元 → API → Flow 全部通过 |
| 3.2 性能基准测试 | Memory 操作 < 10ms，Composer < 50ms |
| 3.3 灰度切换验证 | `USE_MEMORY_STORAGE=1` 回退验证零功能回归 |
| 3.4 更新领域通用语言字典 | `src/domain/AGENTS.md` 新增 Runtime 相关概念 |
| 3.5 更新 `PROGRESS.md` | 新增 Runtime 建设开发主线 |
| 3.6 更新 `架构设计.md` | 在 PaaS 层补充 Runtime 模块描述 |

---

## 五、补充数据模型建议

### 5.1 `ExpirePolicy` 增加 `TIME` 类型

医保场景中，Settlement Memory 如果 30 分钟没有用到，应该自动失效（用户可能已经办完业务离开了）。

### 5.2 `BusinessMemory` 增加 `version` 字段

当 `semantic_bridge.fetch()` 发现领域对象的版本比 Memory 中的新时，自动更新快照，避免使用过时的数据。

### 5.3 `ReasoningStep` 增加 `source_memory_ids`

```python
class ReasoningStep(BaseModel):
    ...
    source_memory_ids: list[str] = Field(default_factory=list)
```

用于追溯推理链的事实来源，满足"来源可追溯"的安全约束。

---

## 六、关键设计决策（补充 ADR）

### ADR-007：RuntimeContext 升级替代独立 BusinessSession

- **状态**：Proposed
- **上下文**：设计文档建议新建 `BusinessSession` 类，但 `RuntimeContext` 已是全系统事实标准。
- **决策**：升级 `RuntimeContext` 而非新建 `BusinessSession`，Session 持久化通过独立的 `SessionStore` 实现。
- **后果**：零改动现有调用方；`RuntimeContext` 职责更清晰（运行时载体），不混合持久化逻辑。

### ADR-008：Context Planner 作为意图识别增强阶段

- **状态**：Proposed
- **上下文**：设计文档将 Context Planner 设为独立模块，与 `runtime/intent/` 职责边界模糊。
- **决策**：Planner 作为 `runtime/intent/planner.py`，是意图识别管道的第三阶段（解析 → 匹配 → 规划）。
- **后果**：避免目录扩散；意图识别相关能力集中在 `runtime/intent/`。

### ADR-009：Runtime 增强作为 scenario_executor 的横切关注点

- **状态**：Proposed
- **上下文**：设计文档未描述六模块如何嵌入现有执行流程。
- **决策**：在 `UnifiedScenarioExecutor.execute()` 的技能匹配后、场景执行前嵌入 Runtime 增强。
- **后果**：Skill 执行路径不受影响；LangGraph/Policy QA 场景获得更丰富的上下文。

---

## 七、需同步更新的文档清单

| 文档 | 更新内容 | 优先级 |
|------|---------|--------|
| `src/domain/AGENTS.md` | 新增 Runtime 相关概念：`BusinessMemory`、`MemoryType`、`ExpirePolicy`、`ContextNeed`、`ReasoningState`、`ReasoningStep`、`ReasoningKind` | P0 |
| `PROGRESS.md` | 新增"Runtime 建设"作为 §3 开发主线 | P0 |
| `docs/steering/架构设计.md` | 在 PaaS 层"会话上下文服务域"中补充 Runtime 模块定位 | P1 |
| `src/tests/AGENTS.md` | 新增 Runtime 模块的测试映射 | P1 |
| `docs/governance/TEST-VERIFICATION-MATRIX.md` | 补充 Runtime 模块的风险等级分级 | P1 |

---

*本评估报告将在评审通过后更新 `PROGRESS.md` 与 `src/domain/AGENTS.md`。*
