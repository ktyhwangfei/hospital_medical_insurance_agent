# 医保 Agent Runtime 设计（V1.0）

> **版本**：V1.0 ｜ **日期**：2026-07-28 ｜ **状态**：设计评审稿
> **定位**：Agent 运行时（Runtime）设计，位于「语义层 / World Model」之上、「LLM」之下。
> **配套文档**：`docs/steering/语义层设计文档.md`（World Model，已完成）、`docs/steering/架构设计.md`、`src/domain/AGENTS.md`（通用语言字典）

## 修订记录

| 版本 | 日期 | 操作 | 内容 | 操作人 |
|---|---|---|---|---|
| V1.0 | 2026-07-28 | 新建 | 基于产品现状完善 Agent Runtime 六模块设计，补齐现状地基、数据模型、ADR、落地路线 | Architect |

---

## 〇、一句话结论

> **Memory 不是一个模块，而是一套 Runtime Operating System（Agent 运行时）。**

六个模块（Business Session / Business Memory / Memory Manager / Context Planner / Context Composer / Reasoning State）共同构成 **Agent Runtime**。它不负责知识——知识由已经完成的**语义层（World Model）**承载。Runtime 负责：**管理 Agent 当前正在理解的业务世界，并支撑跨轮次的持续推理。**

```
                 医保 Agent
        ┌────────────────────┐
        │        LLM         │
        └────────────────────┘
                   ▲
                   │  消费 LLM Context
        ┌──────────────────────────────────┐
        │     Agent Runtime（本次设计）      │
        ├──────────────────────────────────┤
        │  Business Session                 │
        │  Business Memory                  │
        │  Memory Manager                  │
        │  Context Planner                 │
        │  Context Composer                │
        │  Reasoning State（第 6 模块）      │
        └──────────────────────────────────┘
                   ▲
                   │  查询/下探
        ┌──────────────────────────────────┐
        │    Semantic Layer（World Model）   │
        │            —— 已完成 ——           │
        ├──────────────────────────────────┤
        │  业务对象  业务指标  业务动作       │
        │  业务规则  值域      对象关系       │
        │  SQL 映射  政策映射                │
        └──────────────────────────────────┘
```

**关于"比 Context Engineering 更重要"的校准**：Context Engineering 关心的是"如何把信息塞进 Prompt 窗口"；Runtime 关心的是"Agent 如何理解并持续推理一个业务世界"。六模块中的 **Context Composer** 才是 Context Engineering 的落点，仅占六分之一。Runtime 比 Context Engineering 重要，是因为它先把"业务世界的状态、记忆、推理"管起来——没有这些，再好的拼装技巧也只是更快地把错误上下文喂给模型。

---

## 一、设计目标

### 1.1 传统 RAG 的五个问题

```
用户问题 → 查询知识 → Prompt → LLM
```

| # | 问题 | 根因 |
|---|---|---|
| 1 | 无法持续理解当前业务状态 | 每轮都是无状态调用，没有"当前世界"的容器 |
| 2 | 每次问题都重新检索 | 没有记忆，无法复用已理解的事实 |
| 3 | 无法真正支持连续追问 | 没有会话/主题状态，分不清"这个""刚才那个" |
| 4 | 无法理解上下文引用 | 没有把指代词（为什么/这个/昨天）解析到具体业务对象 |
| 5 | Prompt 越来越大 | 没有裁剪与预算机制，只能不断追加 |

### 1.2 Runtime 的职责边界

> **Runtime 不负责知识。知识在语义层（World Model）。**
> **Runtime 负责：管理 Agent 当前正在理解的业务世界。**

具体职责：
- 记住**当前是谁、办什么业务**（Business Session）
- 记住**已经理解的业务事实**（Business Memory）
- 管理这些事实的**生老病死**（Memory Manager）
- 决定**下一步需要哪些上下文**（Context Planner）
- 把最相关的信息**组织成 LLM Context**（Context Composer）
- 保存**推理链、假设与中间结论**（Reasoning State）

### 1.3 与现有代码的衔接原则

本设计**不是推翻重写**，而是把散落在 `runtime/context`（请求级上下文）、`policy_qa/*`（ad-hoc 检索拼装）、`runtime_state`（工作流状态）中的能力，收敛、升级为一套有清晰边界的运行时。详见 §十三「现状地基与代码落位」。

---

## 二、Business Session（业务会话）

### 2.1 为什么需要 Session

很多系统的 Session 只是 Chat Session：

```
Human → AI → Human → AI → …
```

医保不是。一次导办往往是**同一个业务对象上的一连串追问**。例如：

> 患者：「查询住院费用。」

随后：

```
「为什么统筹支付这么少？」
「为什么这两个药没报？」
「如果退掉这个药呢？」
「为什么昨天和今天不一样？」
```

这些问题背后，全是**同一个 Settlement（结算）**。如果每次都当作孤立问题重新检索，模型永远无法理解"这个""为什么""刚才那个"。

**因此 Session 保存的不是聊天记录，而是当前业务场景：**

```
Patient（患者）
Visit（就诊，对应 encounter_id）
Settlement（当前结算）
Hospital（院区/机构，对应 tenant）
Current Intent（当前业务动作 BusinessAction）
Current Topic（当前话题，如"统筹支付偏少"）
```

### 2.2 数据模型

> 命名对齐通用语言字典：`patient_id` + `encounter_id` 为跨域复合键（`src/domain/AGENTS.md` §1）；`BusinessAction` / `BusinessObject` 见 `src/domain/common/actions.py`。

```python
from enum import Enum
from pydantic import BaseModel, Field

class SessionStatus(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    UPDATED = "updated"
    ARCHIVED = "archived"

class Turn(BaseModel):
    role: str                       # "human" | "ai"
    message: str
    intent: str | None = None      # BusinessAction
    object: str | None = None      # BusinessObject
    cited_memory_ids: list[str] = Field(default_factory=list)

class BusinessSession(BaseModel):
    session_id: str
    patient_id: str | None = None          # 当前业务主体（身份锚点）
    encounter_id: str | None = None        # 当前就诊（住院/门诊）
    current_settlement_id: str | None = None
    current_hospital: str | None = None    # 院区/机构（tenant）
    current_topic: str | None = None       # 当前话题，如"统筹支付偏少"
    current_intent: str | None = None      # BusinessAction
    current_object: str | None = None      # BusinessObject
    active_memory_ids: list[str] = Field(default_factory=list)
    conversation_turns: list[Turn] = Field(default_factory=list)
    created_at: str
    last_active_at: str
    status: SessionStatus = SessionStatus.ACTIVE
```

### 2.3 生命周期

```
创建 → 激活 → 更新（每轮追问刷新 current_topic/object）→ 结束 → 归档
```

### 2.4 现状地基与落位

| 项 | 现状 | 落位 |
|---|---|---|
| 请求级上下文 | `src/runtime/context/models.py::RuntimeContext`（每轮 `build_runtime_context` 重建，含 `patient_id`/`encounter_id`/`intent`） | 升级为**跨轮持久化**的 `BusinessSession`，`RuntimeContext` 作为单次请求的子结构保留 |
| 落位建议 | — | 新增 `src/runtime/session/`（models + store，沿用 `runtime_state` 的 PostgreSQL/内存双实现模式） |

---

## 三、Business Memory（业务记忆）

### 3.1 Memory 不是聊天记录

Memory 保存的是 **Agent 已经理解的业务事实（对象）**，而不是 Prompt 片段。

```
Patient Memory      Visit Memory
Settlement Memory   Policy Memory
Rule Memory         Drug Memory
Disease Memory      Indicator Memory
Conversation Memory
```

例如 Settlement Memory 保存：

```
总费用 / 基金支付 / 个人支付 / 起付线 / 医院等级 / 参保类型 / 费用明细 / 已解释指标
```

### 3.2 关键设计决策：Memory 是"引用 + 快照"，不是"第二份真相"

> **Memory 不复制领域对象的全部数据**，而是保存：
> 1. 指向领域对象的引用（`ref_id` + `type`）；
> 2. 当前推理所需的**关键字段快照**（`object_snapshot`）；
> 3. 元数据（重要性、置信度、过期策略、关联）。

原因：领域真相权威来源是语义层与外部系统（经 `adapters/` 防腐层）。Memory 只是一层**会话级缓存与索引**，避免双写不一致。详见 ADR-002。

### 3.3 数据模型

```python
from enum import Enum
from pydantic import BaseModel, Field

class MemoryType(str, Enum):
    PATIENT = "patient"
    VISIT = "visit"
    SETTLEMENT = "settlement"
    POLICY = "policy"
    RULE = "rule"
    DRUG = "drug"
    DISEASE = "disease"
    INDICATOR = "indicator"
    CONVERSATION = "conversation"

class ExpirePolicy(str, Enum):
    SESSION = "session"     # 会话结束即失效
    TOPIC = "topic"         # 话题切换即失效
    STICKY = "sticky"       # 跨话题保留（如政策/规则）

class BusinessMemory(BaseModel):
    memory_id: str
    session_id: str
    type: MemoryType
    ref_id: str | None = None              # 领域对象标识，如 settlement_id
    object_snapshot: dict = Field(default_factory=dict)  # 关键字段快照
    importance: float = 0.5                # 0~1，供 Composer 排序
    confidence: float = 0.5                # 0~1
    expire_policy: ExpirePolicy = ExpirePolicy.TOPIC
    relations: list[str] = Field(default_factory=list)  # 关联 memory_id
    last_used_at: str
    created_at: str
```

### 3.4 支持的操作

```
新增 / 更新 / 覆盖 / 失效 / 压缩 / 淘汰
```

### 3.5 现状地基与落位

| 项 | 现状 | 落位 |
|---|---|---|
| 业务记忆 | **无**独立模块；当前每轮重新检索 | 新增 `src/runtime/memory/`（store + 模型） |
| 落位建议 | 复用 `runtime_state/store.py` 的 PostgreSQL/内存双实现工厂模式 | 内存/PG 双存储，`USE_MEMORY_STORAGE` 回退保持一致 |

---

## 四、Memory Manager（记忆管理器）

### 4.1 这是 Runtime 的核心

负责整个 Memory 的生命周期。典型场景：

```
用户：查询张三住院费用
  → 新增 Patient / Visit / Settlement

用户：为什么统筹支付少？
  → Settlement 已存在，复用；仅新增 Policy / Rule

用户：这个药为什么不能报？
  → 新增 Drug / Catalog / ChargeItem；Settlement 继续复用
```

于是 Memory 越来越丰富，**不是每次重新查询**。

主体切换时自动失效：

```
用户：查询李四
  → 失效 Patient / Visit / Settlement（expire_policy=TOPIC/SESSION）
  → 保留 Policy / Rule（expire_policy=STICKY）
```

### 4.2 职责

```
Memory Merge（合并同对象多次观察）
Memory Replace（覆盖过期快照）
Memory Expire（按策略失效）
Memory Refresh（下探语义层刷新）
Memory Compression（多轮压缩为结论）
Memory Replay（会话恢复时重建）
```

### 4.3 数据模型（接口契约）

```python
class MemoryManager:
    def upsert(self, memory: BusinessMemory) -> BusinessMemory: ...
    def get_by_session(self, session_id: str) -> list[BusinessMemory]: ...
    def get_or_resolve(self, session_id: str, type: MemoryType, ref_id: str | None) -> BusinessMemory | None: ...
    def expire_by_policy(self, session_id: str, policy: ExpirePolicy) -> int: ...
    def invalidate_object(self, session_id: str, object_kind: str) -> int: ...
    def compress(self, session_id: str, keep_types: list[MemoryType]) -> None: ...
```

### 4.4 现状地基与落位

| 项 | 现状 | 落位 |
|---|---|---|
| 生命周期管理 | `runtime_state/store.py` 提供 PG/内存双存储骨架 | Manager 逻辑叠加在该骨架之上 |
| 落位建议 | — | `src/runtime/memory/manager.py` |

---

## 五、Context Planner（上下文规划）

### 5.1 Runtime 最"聪明"的地方

决定**当前问题到底需要哪些 Context**。

```
Memory 已有：Patient / Settlement
用户问：为什么统筹支付这么少？
Planner 发现缺：Policy / Rule
→ 只加载 Policy Context + Rule Context，不重查 Settlement
```

### 5.2 输入 / 输出

```
输入：Question + Business Session + Business Memory + Semantic Layer
输出：ContextNeed { 需要哪些 BusinessObject 类型 + 优先命中哪些 memory_id + 是否下探语义层 }
```

### 5.3 还负责 Topic 切换识别

```
用户突然：查询李四
Planner 识别：业务主体变化（patient_id 变更）
→ 通知 Memory Manager 清除 Patient Memory（并级联 Visit/Settlement）
```

### 5.4 数据模型

```python
from pydantic import BaseModel, Field

class ContextNeed(BaseModel):
    object_types: list[str] = Field(default_factory=list)   # 需要哪些 BusinessObject 类型
    memory_ids: list[str] = Field(default_factory=list)     # 优先命中记忆
    must_query_semantic: bool = False                       # 记忆缺失则下探语义层
    reasoning_refs: list[str] = Field(default_factory=list) # 关联推理状态

class ContextPlanner:
    def plan(self, question: str, session: BusinessSession,
             memory: list[BusinessMemory], semantic) -> ContextNeed: ...
```

### 5.5 重要区分：Context Planner ≠ 已废弃的 Execution Planner

> `src/runtime/planning/` 的 `ExecutionPlan` **已被弃用**（源码注释：`"This module is deprecated. Use UnifiedScenarioExecutor instead."`）。
> 它是**执行步骤规划**（决定调哪个 Skill/能力），而 Context Planner 是**上下文规划**（决定加载哪些业务对象）。两者职责正交，不可混淆。详见 ADR-003。

### 5.6 现状地基与落位

| 项 | 现状 | 落位 |
|---|---|---|
| 上下文规划 | **无**（现有 planning 是执行规划且已废弃） | 新增 `src/runtime/context_planner/` |
| 输入源 | `runtime/intent`（意图识别）、`runtime/context`（上下文）已可用 | 直接复用作为 Planner 输入 |

---

## 六、Context Composer（上下文编排）

### 6.1 不是拼 Prompt，而是选信息

Memory 可能有 50 个对象，Prompt 只能放 10 个。Composer 负责**挑选最有价值的信息并排序**：

```
Current Settlement
Current Policy
Current Rule
Current Drug
Conversation Summary
Historical Conclusion
```

### 6.2 Token Budget：超长则"摘要"，不"截断"

> 超出预算时，**摘要（summarize）而非截断（truncate）**，保证语义不丢。详见 ADR-005。

### 6.3 输出 LLM Context，不是 Prompt

```
Composer → LLM Context（结构化对象）
Prompt Template（最后一步模板拼装，已有 PromptTemplate 实体）→ LLM
```

### 6.4 数据模型

```python
from pydantic import BaseModel, Field

class MemoryBrief(BaseModel):
    memory_id: str
    type: str
    summary: str
    importance: float

class LLMContext(BaseModel):
    session_summary: str
    selected_memories: list[MemoryBrief] = Field(default_factory=list)
    reasoning_so_far: list[str] = Field(default_factory=list)   # 来自 Reasoning State
    token_budget_used: int = 0
    token_budget_total: int = 0

class ContextComposer:
    def compose(self, need: ContextNeed, memory: list[BusinessMemory],
                reasoning) -> LLMContext: ...
```

### 6.5 现状地基与落位

| 项 | 现状 | 落位 |
|---|---|---|
| 上下文组装 | `policy_qa/structured_policy_retriever.py`、`question_rewriter.py`、`contextual_policy_qa.py` 等 **ad-hoc RAG 拼装** | Composer 统一收编这些能力，作为"检索回填"子能力 |
| 落位建议 | — | 新增 `src/runtime/context_composer/`；现有 retriever/rewriter 降格为其内部策略 |

---

## 七、Reasoning State（推理状态，第 6 模块）

> 这是本设计相对"五个模块"的关键增量：**Memory 记录事实，Reasoning State 记录推理过程。**

### 7.1 为什么需要

Memory 保存的是**已确认的事实**，但 Agent 在推理过程中会产生大量**中间结论、假设、待验证项**。这些：
- 不适合写回语义层（语义层是权威世界知识，不是推理草稿）；
- 不适合长期放入 Business Memory（Memory 是稳定的业务事实，不是临时推演）；
- 但对**连续追问**至关重要。

示例：

```
用户：为什么统筹支付这么少？
Agent 推理：
  事实：三级医院 / 退休人员 / 起付线 650 元
  推理：已满足起付线 → 超过部分进入统筹计算 → 部分费用属目录外，不参与统筹
  结论：统筹支付偏少主要由目录外费用导致

后续追问：「目录外费用有哪些？」「如果去掉这个药呢？」
→ 直接基于 Reasoning State 的推理链继续，无需重新推导
```

### 7.2 数据模型

```python
from enum import Enum
from pydantic import BaseModel, Field

class ReasoningKind(str, Enum):
    FACT = "fact"                 # 已确认事实
    INFERENCE = "inference"       # 由事实推出的中间结论
    HYPOTHESIS = "hypothesis"     # 假设（待验证）
    VERIFIED = "verified"         # 已验证结论

class ReasoningStep(BaseModel):
    step_id: str
    claim: str                               # 中间结论/事实表述
    kind: ReasoningKind
    depends_on: list[str] = Field(default_factory=list)  # 依赖的 step_id
    confidence: float = 0.5
    citations: list[str] = Field(default_factory=list)    # 来源（对接 Citation）

class Hypothesis(BaseModel):
    hypothesis_id: str
    statement: str
    status: str = "open"          # open | confirmed | rejected
    tested_by: list[str] = Field(default_factory=list)

class ReasoningState(BaseModel):
    session_id: str
    workflow_id: str | None = None
    chain: list[ReasoningStep] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
```

### 7.3 生命周期与持久化

- **会话级临时态**：不长期持久化为"知识"，会话归档后可丢弃或压缩进 Conversation Memory。
- **复用既有基础设施**：`runtime_state`（WorkflowInstance/StepState）+ LangGraph `checkpoint.py` / `postgresql_checkpointer.py` 已提供可恢复的执行状态——Reasoning State 在其上扩展推理链字段，而非另起炉灶。详见 ADR-004。

### 7.4 为什么这是医保 Agent 的差异化能力

医保咨询本质是**持续推理**（一笔费用为什么这样算、如果改一个变量会怎样），而不只是**持续检索**。Reasoning State 让 Agent 能在多轮对话中保持一条连贯的推理链，而不是每轮从零开始——这是它与普通 RAG 最大的区别之一。

---

## 八、六模块协同

### 8.1 单轮流程

```
                User Question
                       │
                       ▼
              Business Session   ← 解析"这个/为什么/刚才那个"到具体业务对象
                       │
                       ▼
              Context Planner     ← 判断需要哪些业务对象
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
   Memory Manager              Reasoning State
   （命中/失效记忆）          （载入已有推理链/假设）
          │                         │
          ▼                         ▼
   Business Memory  ──────┐   ┌──── Semantic Layer（World Model，缺失时下探）
          │               │   │
          └───────┬───────┘   │
                  ▼           │
           Context Composer  ←┘ 挑选+排序+Token 预算（摘要非截断）
                  │
                  ▼
             LLM Context
                  │
                  ▼
            Prompt Template（已有 PromptTemplate）
                  │
                  ▼
                 LLM
                  │
                  ▼
       Reasoning State 回写本轮推理链/结论
```

### 8.2 模块职责一览

| # | 模块 | 一句话职责 | 是否新增 |
|---|---|---|---|
| 1 | Business Session | 当前业务场景（谁、什么业务） | 演进（基于 `runtime/context`） |
| 2 | Business Memory | 长期保存本次会话已理解的业务事实 | 新增 |
| 3 | Memory Manager | 管理业务事实生命周期 | 新增 |
| 4 | Context Planner | 规划下一步需要哪些上下文 | 新增（区别于已废弃 Execution Planner） |
| 5 | Context Composer | 从 Memory 选上下文并组织为 LLM Context | 新增（收编 ad-hoc RAG 拼装） |
| 6 | Reasoning State | 保存推理链、假设、中间结论、已验证结果 | 演进（基于 `runtime_state` + LangGraph checkpoint） |

---

## 九、与语义层（World Model）的职责边界

| 模块 | 职责 | 是否已有 | 现状地基 |
|---|---|---|---|
| 语义层 | 定义世界（业务对象、指标、规则、关系、政策） | ✅ 已完成 | `docs/steering/语义层设计文档.md` v3.0（L1/L2/L3 + Metric Layer + 语义映射） |
| Business Session | 定义当前业务场景 | 演进 | `runtime/context`（请求级） |
| Business Memory | 保存 Agent 已理解的业务事实 | 新增 | — |
| Memory Manager | 管理业务记忆生命周期 | 新增 | `runtime_state/store.py`（PG/内存骨架） |
| Context Planner | 决定下一步需要哪些业务对象 | 新增 | `runtime/planning`（已废弃，需新建） |
| Context Composer | 从 Memory 选上下文并组织为 LLM Context | 新增 | `policy_qa/*`（ad-hoc 拼装） |
| Reasoning State | 保存推理链与中间结论 | 演进 | `runtime_state` + LangGraph checkpoint |
| Prompt Template | 最终模板拼装 | ✅ 已有 | `knowledge` 上下文 `PromptTemplate` |

**边界铁律**：Runtime 不生产世界知识，只消费语义层；当 Memory 缺失所需事实时，Context Planner 标记 `must_query_semantic=True`，由适配器/检索下探语义层取回，再回填 Memory。

---

## 十、架构决策记录（ADR）

> 模板见治理规范；此处给出本设计的关键决策，供评审。

### ADR-001：Agent Runtime 作为语义层之上的运行时层
- **状态**：Proposed
- **上下文**：语义层（World Model）已完成，但缺少"当前业务世界状态 + 跨轮推理"的运行时。
- **决策**：在 LLM 与语义层之间引入六模块 Agent Runtime。
- **后果**：语义层保持纯知识；Runtime 承载状态与推理；两者解耦，可独立演进。

### ADR-002：Business Memory 以"引用 + 快照"存储，不复制领域真相
- **状态**：Proposed
- **上下文**：若 Memory 全量复制领域对象，会和语义层/外部系统产生双写不一致。
- **决策**：Memory 仅存 `ref_id` + `object_snapshot`（关键字段）+ 元数据。
- **后果**：Memory 是会话级缓存/索引；真相权威仍在语义层与外部系统（经 `adapters/`）。

### ADR-003：Context Planner 与 Execution Planner 是两个概念
- **状态**：Proposed
- **上下文**：`runtime/planning` 的 `ExecutionPlan` 已废弃，且是"执行步骤规划"。
- **决策**：Context Planner 负责"加载什么上下文"，Execution 规划由 `UnifiedScenarioExecutor` 负责；不复用废弃模块。
- **后果**：避免概念混淆；Context Planner 是 Runtime 内部新增能力。

### ADR-004：Reasoning State 为会话级临时态，不长期持久化为知识
- **状态**：Proposed
- **上下文**：推理草稿若写回语义层会污染世界知识；若长期存 Memory 会稀释稳定事实。
- **决策**：Reasoning State 会话级存活，复用 `runtime_state` + LangGraph checkpoint 持久化；会话归档后可丢弃或压缩进 Conversation Memory。
- **后果**：连续追问连贯，但不污染权威知识。

### ADR-005：Context Composer 超预算采用"摘要"而非"截断"
- **状态**：Proposed
- **上下文**：截断会丢失关键信息，尤其医保费用解释类长上下文。
- **决策**：Token 超预算时调用摘要能力压缩低优先级记忆，保留高 importance/recency 项。
- **后果**：语义不丢；需引入摘要步骤（可复用模型服务网关）。

### ADR-006：六模块渐进建设，先替换 ad-hoc 拼装
- **状态**：Proposed
- **决策**：阶段一先建 Business Session + Business Memory + Context Composer（替换现有 `policy_qa/*` ad-hoc 拼装）；阶段二上 Context Planner + Reasoning State。
- **后果**：低风险起步，每阶段可独立验证（见 §十三）。

---

## 十一、适用边界与反模式（架构师视角）

> 你判断"这六个模块比 Context Engineering 更重要"，方向我认可。但作为工程决策，需明确：**它解决的是"有状态、多轮、业务实体稳定"的场景。** 以下情况不应急于全量建设：

| 场景 | 是否值得建 | 说明 |
|---|---|---|
| 医保结算/待遇多轮导办 | ✅ 强需要 | 业务实体稳定（Patient/Settlement），连续追问频繁 |
| 政策问答（单轮为主） | ⚠️ 先做 Composer | 主要痛点是上下文拼装，Session/Memory 收益有限 |
| 一次性批处理/统计 | ❌ 不需要 | 无跨轮状态，Runtime 反成负担 |
| 纯检索增强 | ⚠️ 先做 Composer | 先收编 ad-hoc RAG，再考虑 Memory |

**反模式**：
- ❌ 把 Memory 当第二数据库全量复制领域对象（违反 ADR-002）。
- ❌ 用已废弃的 `runtime/planning` 当作 Context Planner（违反 ADR-003）。
- ❌ 把推理草稿写回语义层（违反 ADR-004）。
- ❌ Token 超预算直接截断（违反 ADR-005）。

---

## 十二、落地路线与代码落位

### 12.1 现状地基总表

| 设计模块 | 现有地基 | 净新增 | 建议落位 |
|---|---|---|---|
| Business Session | `runtime/context`（请求级 `RuntimeContext`） | 持久化 SessionStore + 跨轮状态 | `src/runtime/session/` |
| Business Memory | （无） | MemoryStore（PG/内存） | `src/runtime/memory/` |
| Memory Manager | `runtime_state/store.py`（PG/内存骨架） | 生命周期逻辑 | `src/runtime/memory/manager.py` |
| Context Planner | `runtime/planning`（已废弃） | 新上下文规划器 | `src/runtime/context_planner/` |
| Context Composer | `policy_qa/structured_policy_retriever`、`question_rewriter`、`contextual_policy_qa` | Composer 模块 | `src/runtime/context_composer/` |
| Reasoning State | `runtime_state`（WorkflowInstance/StepState）+ LangGraph `checkpoint` | ReasoningState 模型，复用 checkpoint | `src/runtime/reasoning/` |
| 语义层（World Model） | `docs/steering/语义层设计文档.md` + `src/domain/indicator` 等 | — | 已有 |

### 12.2 分阶段实施（低风险优先，复用种子）

**阶段一（替换 ad-hoc 拼装，回报最快）**
1. Business Session：把 `RuntimeContext` 升级为跨轮持久化 `BusinessSession`（新增 `session/` + store）。
2. Business Memory + Memory Manager：建立内存/PG 双存储（复用 `runtime_state` 工厂模式）。
3. Context Composer：收编 `policy_qa/*` 的检索拼装为统一 Composer（摘要非截断）。

**阶段二（智能升级）**
4. Context Planner：新建上下文规划器，串联 Session/Memory/语义层。
5. Reasoning State：在 `runtime_state` + LangGraph checkpoint 上扩展推理链。

每阶段遵循项目验证流程（单元 → API → Flow），并保持 `USE_MEMORY_STORAGE=1` 可回退。

### 12.3 风险与回退
- 现有 `policy_qa/*` 拼装通过 Composer 内部策略保留，可灰度切换，失败回退原路径。
- 所有存储沿用 PG/内存双实现，`USE_MEMORY_STORAGE` 兜底，不影响现有部署。

---

## 十三、与通用语言字典的对齐

本设计新增概念须同步 `src/domain/AGENTS.md`（§15 契约 2「同步更新」）：

| 新增概念 | 建议英文命名 | DDD 分类 | 归属 |
|---|---|---|---|
| 业务会话 | `BusinessSession` | Entity | Runtime |
| 业务记忆 | `BusinessMemory` | Entity | Runtime |
| 记忆类型 | `MemoryType` | Value Object | Runtime |
| 过期策略 | `ExpirePolicy` | Value Object | Runtime |
| 上下文需求 | `ContextNeed` | DTO | Runtime |
| 推理状态 | `ReasoningState` | Entity | Runtime |
| 推理步骤 | `ReasoningStep` | Entity | Runtime |
| 推理种类 | `ReasoningKind` | Value Object | Runtime |

命名须遵循三位一体：`中文术语 ↔ 英文命名 ↔ 代码标识符`，禁止同一概念多命名。

---

## 附录 A：术语对照

| 设计术语 | 对应现有概念 |
|---|---|
| Business Session | 演进自 `RuntimeContext`（请求级 → 跨轮） |
| Business Memory | 新增（会话级缓存/索引） |
| Memory Manager | 基于 `runtime_state/store.py` 骨架 |
| Context Planner | 新增（区别于已废弃 `ExecutionPlan`） |
| Context Composer | 收编 `policy_qa/structured_policy_retriever` 等 |
| Reasoning State | 演进自 `WorkflowInstance`/`StepState` + LangGraph checkpoint |
| Semantic Layer / World Model | `docs/steering/语义层设计文档.md` v3.0 |

*本文档将在评审通过后同步更新 `src/domain/AGENTS.md` 与 `PROGRESS.md`。*
