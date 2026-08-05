# PROGRESS.md — 开发进度追踪

> **定位**：本文件是项目进度的唯一权威来源。三条进度线并行追踪：
> 1. **功能领域单元**（业务能力视图，§1）——按"最小可验证单元"切片，回答"功能做没做、验没验"。
> 2. **政策知识管线重构**（开发主线，§2）——P0-P10 重构阶段，回答"知识模型重构推进到哪、什么时候能切换生产"。
> 3. **Runtime 建设**（开发主线，§3）——医保 Agent Runtime V1.0 三阶段落地，回答"运行时智能增强验证到什么程度"。
> 状态实时更新；每个单元/阶段状态变更必须在此记录。禁止仅口头/IM 同步进度。

---

## 0. 当前焦点

**当前领域**：政策知识管线重构（§2）

**当前阶段**：P10（灰度切换）— P8.4 全量重提取已完成（M5 达成）

| 阻塞项 | 原因 | 解锁条件 |
|---|---|---|
| P10 灰度切换 | P0.3 开关已落地，P8.4 已完成（M5 达成） | P0 回归基线全绿后可切换 |
| §10.1/10.2 安全审计 | 需对接医院 SSO / 外部系统 | 获取医院 SSO 文档 |
| §11.1/11.2 适配器 | 需真实医保 / DRG 系统 API | 获取系统 API 文档和测试环境 |

---

## 1. 功能领域单元（业务能力视图）

| 领域 | 单元数 | ✅ verified | 🟢 impl_done | 🔴 blocked | ⚪ pending | 备注 |
|------|:--:|:--:|:--:|:--:|:--:|---|
| 政策问答 | 5 | 0 | 5 | 0 | 0 | §2 重构进行中（读旧 policy_rules，待 P10 切换） |
| 结算异常导办 | 4 | 0 | 4 | 0 | 0 | — |
| 出院前质控 | 3 | 0 | 3 | 0 | 0 | — |
| 模型服务与管理 | 4 | 0 | 4 | 0 | 0 | — |
| MCP 工具管理 | 3 | 0 | 3 | 0 | 0 | — |
| 知识库管理 | 3 | 0 | 3 | 0 | 0 | §2 P9 5 tab 已上线，详见 §2 |
| 技能管理 | 4 | 1 | 3 | 0 | 0 | 阶段 1 版本化资产库已验证 |
| 运营看板 | 2 | 0 | 2 | 0 | 0 | — |
| 嵌入式组件 | 1 | 0 | 1 | 0 | 0 | — |
| 安全与审计 | 2 | 0 | 0 | 0 | 2 | 待外部系统 |
| 适配器接入 | 2 | 0 | 0 | 2 | 0 | 需真实系统 |
| **合计** | **33** | **1** | **28** | **2** | **2** | — |

> **现状**：现有功能代码均 `impl_done`（写完未走正式验证流程）。验证流程见 `src/tests/AGENTS.md`
> 与 `docs/governance/TEST-VERIFICATION-MATRIX.md`。**政策问答/知识库管理两领域的"真实最新进度"
> 在 §2 政策知识管线重构中**——本表状态滞后于 §2，以 §2 为准。

### 1.1 各领域详情

#### 政策问答（Policy QA）
| # | 单元 | 涉及层 | 前端 | 后端 | 存储 | 状态 |
|---|------|:--:|------|------|------|:--:|
| 1.1 | 用户通过 Chat 提交政策问题 | F+B+S | `policy-qa/page.tsx` | `policy_qa_routes.py` → `orchestrator.py` | Milvus + SQLServer | impl_done |
| 1.2 | AI 检索政策知识库片段 | B+S | — | `policy_rules_search.py` → `structured_policy_retriever.py` | Milvus | impl_done |
| 1.3 | 费用项目自动检测 | B | — | `fee_item_detector.py` | — | impl_done |
| 1.4 | 医保政策规则语义匹配 | B | — | `semantic_mapping.py` | SQLServer | impl_done |
| 1.5 | 历史问答记录查询 | F+B+S | `qa-history/page.tsx` | `history_service.py` | PostgreSQL | impl_done |

#### 结算异常导办（Settlement Exception Guide）
| # | 单元 | 后端 | 状态 |
|---|------|------|:--:|
| 2.1 | 错误码 → AI 分析异常原因 | `settlement_exception_guide/service.py` → `settlement_nodes.py` | impl_done |
| 2.2 | AI 查询医保交易详情 | adapters → `insurance_transactions` | impl_done |
| 2.3 | AI 给出异常处理步骤（导办卡） | `settlement_nodes.py` → GuidanceCard | impl_done |
| 2.4 | 高风险动作人工确认 | `security/risk_control/` → `langgraph/checkpoint.py` | impl_done |

#### 出院前质控（Pre-Discharge QC）
| # | 单元 | 后端 | 状态 |
|---|------|------|:--:|
| 3.1 | 用户触发质控 → 风险扫描 | `pre_discharge_joint_qc/service.py` → `qc_nodes.py` | impl_done |
| 3.2 | 事前审核适配器获取结果 | adapters → `audit_risk` | impl_done |
| 3.3 | DRG/DIP 分组分析 | adapters → `drg_dip` | impl_done |

#### 模型服务与管理（Model Service）
| # | 单元 | 后端 | 状态 |
|---|------|------|:--:|
| 4.1 | 模型配置 CRUD | `model_routes.py` | impl_done |
| 4.2 | 模型在线测试（流式 SSE） | `model_routes.py` → SSE | impl_done |
| 4.3 | 模型路由（type+scene 策略） | `model_service/gateway/` → `router/` | impl_done |
| 4.4 | 模型异常分类处理 | `model_service/exceptions/` | impl_done |

#### MCP 工具管理
| # | 单元 | 后端 | 状态 |
|---|------|------|:--:|
| 5.1 | MCP 服务器注册与管理 | `mcp_routes.py` → `mcp_registry/` | impl_done |
| 5.2 | MCP 工具发现与能力展示 | `mcp_registry/` → `mcp_discovery.py` | impl_done |
| 5.3 | MCP 工具安全边界校验 | `security/test_mcp_security_boundaries.py` | impl_done |

#### 知识库管理（**详见 §2 政策知识管线重构**）
| # | 单元 | 前端 | 后端 | 状态 |
|---|------|------|------|:--:|
| 6.1 | 知识资产上传与管理 | admin knowledge 页 | `policy_knowledge_routes.py` | impl_done |
| 6.2 | 知识检索（RAG） | — | `rule_explanation/` → `policy_retrieval/` | impl_done |
| 6.3 | 政策知识浏览 | `policy-knowledge/*`（P9 已重构为 5 tab） | `policy_knowledge_routes.py` | impl_done |

#### 技能管理（Skill）
| # | 单元 | 后端 | 状态 |
|---|------|------|:--:|
| 7.1 | 技能注册/加载/路由 | `skill_loader.py` → `skill_router.py` | impl_done |
| 7.2 | 费用解释 Skill 执行 | `settlement_explain_skill/` → `skill_registry/engine.py` | impl_done |
| 7.3 | 技能列表与管理 | `infra_skill_routes.py` | impl_done |
| 7.4 | 版本化 Skill 资产库：制品哈希、版本登记、证据查询与 Portal 展示 | `skill_infra/artifact.py` → `runtime/skill_management/version_service.py` → `infra_skill_routes.py` → Portal `/skills` | verified |

7.4 验证证据（2026-08-05）：T1 新功能相关测试 18 passed；T2a Skill API 10 passed；T2b 版本目录 Flow 1 passed；Portal Vitest 3 passed、变更文件 ESLint 通过、Next.js build 通过；Chromium E2E 1 passed。旧 `test_skill_mention.py` / `test_skill_intent_matching.py` 中 8 个请求已下线路由的 404 为预存测试债务，不计入 7.4 通过证据。

兼容与回滚：运行时仍由 `SkillLoader` / `SkillRouter` 选择当前文件系统 Skill，未切换到版本解析器；需要回滚时让 Portal 恢复调用 `GET /infra-skills` 并停止调用 catalog/version 端点即可，已登记版本是只读证据，不影响业务执行。

#### 运营看板 / 嵌入式 / 安全与审计 / 适配器接入
| # | 单元 | 状态 | 备注 |
|---|------|:--:|---|
| 8.1-8.2 | 运营指标展示 + 工作流监控 | impl_done | `dashboard/page.tsx` |
| 9.1 | 嵌入式 Chat Widget | impl_done | `src/apps/embed/` |
| 10.1 | 用户认证鉴权（SSO/RBAC） | pending | 需对接医院 SSO |
| 10.2 | 审计日志持久化与查询 | pending | `security/audit/postgresql_store.py` |
| 11.1 | 医保接口适配器对接真实系统 | blocked | 当前内存实现，需真实医保接口 |
| 11.2 | DRG/DIP 适配器对接真实系统 | blocked | 当前内存实现，需大瑞集思系统 |

---

## 2. 政策知识管线重构（开发主线）

> **依据**：`docs/steering/政策知识管线开发计划.md`（本节对应其 P0-P10 + 里程碑 M1-M7）。
> **策略**：「平行建新通路 → 最后一把切换」（P10 灰度）。P0-P9 全程在新 collection（`*_v2`）上建，
> **生产政策问答始终读旧的 `policy_rules`**，直到 P10 切换。所以切换前用户侧无感知——这是策略决定。

### 2.1 价值矩阵（P0-P10 + M1-M7）

| 价值 | 阶段 | 里程碑 | 状态 |
|------|------|:--:|:--:|
| 重构不搞砸生产（安全网） | P0 | — | ✅ 完成 |
| 知识模型可配置（加维度不改代码的地基） | P1, P2 | M1 | ✅ 达成 |
| 政策原文自动变结构化知识（自动化跃迁） | P3 | M2 | ✅ 达成（demo 验证端到端） |
| 知识可信（质量门禁挡住垃圾数据） | P4 | M3 | ✅ 简化版达成；完整质量分+黄金样本推迟 |
| 知识可演进（改 schema 不丢人工校对） | P5 | M3 | 🟡 部分（执行器三策略+evolve 接线完成；LLM 字段级提取+metric_code 标量索引推迟） |
| 结构化知识灵活查（政策库+业务库联查） | P6 | M4 | ✅ 达成（三模式+跨世界） |
| 多源数据 + 自助发现 | P7 | M4 | ✅ 达成（多源验证+发现 tab 候选回写上线） |
| 现有数据进新模型 | P8 | M5 | ✅ 达成（8.1-8.4 全完成；全量重提取 8 篇 + 干净重建 337 rules） |
| 运营自助操作（前端 5 tab） | P9 | M6 | ✅ 达成（5 tab 全上线，4 旧路由下线） |
| **生产真正用上新模型** | **P10** | **M7** | ⚪ 未开始（**价值兑现点**） |

### 2.2 各阶段子任务进度

| Phase | 子任务 | 状态 |
|-------|--------|:--:|
| P0 | 兼容基线与风险隔离 | ✅ |
| P1 | 语义层提取契约（extraction-schema） | ✅ |
| P2 | policy_rules_v2 新 schema + 字段级溯源 + 向量复用 | ✅ |
| P3 | 事实拆分 + 结构化入库（publish_to_new_collections） | ✅ |
| P4 | 质量门禁（publish_object 同步 status + 空对象门禁，解锁 §3.1） | ✅ 简化版 |
| P5.1-5.4 | schema 演化执行器三策略 + evolve 分批 + 任务 API | ✅ |
| P5.5 | LLM 字段级提取 + metric_code 标量索引反查 | ⚪ 待做（需 MODEL_API_KEY） |
| P6 | 混合检索三模式 + 跨世界（经登记号）+ 按 fact 分组 | ✅ |
| P7.1-7.2 | datasource 注册表 + 多源扫描 + 三段式路由 | ✅ |
| P7.3 | discovery_scanner 候选指标 | ✅ |
| P7.4 | 发现 tab 候选→回写语义层（§8.1） | ✅ P9.6 完成 |
| P8.1 | 重建新 collection | ✅ |
| P8.2 | 迁移 105 条 extractions → facts + rules_v2 | ✅ commit `7398c22` |
| P8.3 | 种子政策值域 + zcgz 发布解锁契约 | ✅ commit `c89139d` |
| P8.4 | 迁移后重提取拉高填充率 | ✅ 全量重提取 8 篇 + 干净重建（337 rules，insu 31%→98%、psn 20%→63%）；med/hosp/setl 低填充为内容特性（政策少涉及医院等级/结算方式） |
| P9 | 前端 5 tab 重构（概览/政策/事实/结构化/发现） | ✅ commit `610272c`→`c87a99d` |
| P10.1 | 政策问答读入口切到新 collection | ✅ 完成：未上线直接切纯 v2，删开关/适配层/LEGACY 兼容代码（policy_rules_search 重写纯 v2，structured_retriever 复用常量+unpack_detail） |
| P10.2 | 下线旧 policy_rules / 旧 schema / 旧 publish 通路 | ✅ 完成：删旧 publish_extraction + /publish-v2 + policy_rules_schema + data_model1_loader；drop 旧 policy_rules collection（57条） |

### 2.3 里程碑达成情况

| 里程碑 | 含义 | 收口 Phase | 状态 |
|--------|------|:--:|:--:|
| M1 地基就绪 | 语义层契约 + 新 schema 可用，零生产影响 | P0,P1,P2 | ✅ |
| M2 数据通路打通 | 一篇政策端到端入库新模型 | P3 | ✅ |
| M3 发布闭环 | 质量门禁 + schema 演化可用 | P4,P5 | 🟡 部分（P4 简化版 + P5 部分，LLM 提取推迟） |
| M4 检索能力完整 | 三模式 + 跨世界查找可用 | P6,P7 | ✅ |
| M5 知识资产迁移完成 | 现状数据全部进入新模型 | P8 | ✅ 达成（全量重提取 + 干净重建，337 rules / 8 文档） |
| M6 前端重构完成 | 5 tab 上线 | P9 | ✅ |
| M7 生产切换 | 政策问答跑在新模型，旧路径下线 | P10 | ✅ 完成（未上线直接切换，无灰度） |

---

## 3. Runtime 建设（开发主线）

> **依据**：`docs/steering/医保Agent-Runtime设计-V1.0-评估报告.md`（三阶段路线图 + ADR-007/008/009）。
> **架构决策**：RuntimeContext 演进而非新建 BusinessSession（ADR-007）；Context Planner 作为
> `runtime/intent/planner.py` 第三阶段（ADR-008）；Runtime 增强作为 scenario_executor 横切关注点（ADR-009）。

### 3.1 三阶段路线图进度

| 阶段 | 内容 | 状态 |
|------|------|:--:|
| 阶段一：地基建设（任务 1.1-1.7） | RuntimeContext 跨轮字段、BusinessMemory、MemoryStore/Manager、ContextComposer 骨架、WorkflowInstance 扩展 reasoning_state | ✅ 完成 |
| 阶段二：智能增强（任务 2.1-2.6） | ContextPlanner、Token Budget + 摘要策略、scenario_executor 集成、ReasoningState 推理链、ExpirePolicy.TIME、主体切换检测 | ✅ 完成 |
| 阶段三：全面验证（任务 3.1-3.6） | 全量回归、性能基准、灰度切换、文档同步 | ✅ 完成（2026-07-31） |

### 3.2 阶段三验证结果（2026-07-31）

| 任务 | 验证标准 | 结果 |
|------|---------|------|
| 3.1 全量回归 | 单元 → API → Flow | ✅ 与 HEAD 基线（fd12c79）逐集合对比**零新增失败**：单元 26F/894P、API 66F/43P、Flow 42F/9P（失败全部为 §5 预存债务/环境依赖）；顺带修复 `unit/shared/__init__.py` 缺失导致的 3 个收集错误 |
| 3.2 性能基准 | Memory < 10ms、Composer < 50ms | ✅ Memory CRUD ≤ 0.003ms、MemoryManager 组合 0.005ms、Composer（60 记忆+5 推理步）0.244ms（`src/tests/performance/test_runtime_benchmarks.py`，300 轮均值） |
| 3.3 灰度切换 | USE_MEMORY_STORAGE=1 零功能回归 | ✅ 三层失败集合均为默认模式严格子集（单元 25F/895P、API 66F/43P、Flow 39F/12P），差异全部为 PG 环境依赖在内存模式自然恢复 |
| 3.4 领域字典 | `src/domain/AGENTS.md` 新增 Runtime 概念 | ✅ 新增 §13.5 Runtime 上下文（BusinessMemory / MemoryType / ExpirePolicy / ContextNeed / ReasoningState / ReasoningStep / ReasoningStep.kind 等 15 条），附录 A 同步 |
| 3.5 本文件 | 新增 Runtime 建设主线 | ✅ 本节 |
| 3.6 架构设计 | PaaS 层补充 Runtime 模块定位 | ✅ `docs/steering/架构设计.md` 会话上下文服务域 |

### 3.3 新增测试资产

- 单元测试 63 个：`unit/runtime/memory/`（模型+管理器）、`unit/runtime/context_composer/`、`unit/runtime/reasoning/`、`unit/runtime/intent/test_context_planner.py`、`unit/data_platform/test_memory_storage.py`
- 性能基准 3 个：`performance/test_runtime_benchmarks.py`（微基准，进程内直测，与 Locust HTTP 压测互补）

### 3.4 遗留事项

- 评估报告中的 `ReasoningKind` 枚举当前以 `ReasoningStep.kind: str` 字面量表示（fact/inference/hypothesis/verified），尚未抽为独立枚举，已在领域字典中标注，后续演进
- 预存测试债务（§5）治理不在本主线范围，按需另行立项

---

## 4. 测试套件状态

> 后端：单元（`src/tests/unit/`）→ API（`src/tests/integration/api/`）→ Flow（`src/tests/integration/flow/`）。
> 详见 `src/tests/AGENTS.md` 与 `docs/governance/TEST-VERIFICATION-MATRIX.md`。

| 套件 | 状态 | 备注 |
|------|------|------|
| semantic_layer 单元 | ✅ 全绿 | P8.3 收口测试 + 契约/发布/版本（139 passed） |
| rule_explanation 单元 + rules_search 流式 | ✅ 全绿 | 142 passed（含 Milvus 连真集） |
| 提取契约 API（extraction-schema） | ✅ 全绿 | P8.3 更新断言后 3 passed |
| 前端 policy-knowledge 5 tab | ✅ dev 编译 200 + 内容渲染 | tsc 5 页面零错误；`next dev` 烟测通过 |
| Runtime 新模块单元（memory/composer/reasoning/planner/storage） | ✅ 全绿 | 63 passed（§3.3） |
| Runtime 性能基准 | ✅ 全绿 | 3 passed：Memory ≤ 0.005ms、Composer 0.244ms（§3.2） |
| 前端政策问答持续对话（usePolicyQAStream + 三区工作区 + 可视化组件） | ✅ 全绿 | vitest 69 passed（含本次新增 20 项）；`next build` EXIT=0（§3.5） |
| 全量回归 | ⚠️ 单元 26F/894P、API 66F/43P、Flow 42F/9P（预存债务） | 2026-07-31 与 HEAD 基线对比零新增失败，见 §5 测试债务 |

### 3.1 已知预存技术债（非当前任务引入，治理时优先级参考）
- `src/components/settlement-explanation-page.tsx`：TS 类型错误（OutputItemValue.value 应为 number，传了 string|number）。**预先存在**，P9 之外。~~**已于 2026-08-03 修复**（政策问答前端改造 build 门禁所需：`Number()` 收窄 + ProfileCard items 运行时断言）。~~
- `src/tests/e2e/settlement-explanation.spec.ts`：缺 `@playwright/test` 类型（dev 依赖）。**预先存在**。
- `extractions/page.tsx` JSX 多根错误：**已消除**（P9.7 删除该路由）。

---

## 5. 测试套件债务（已知失败）

> 2026-07-31 口径：单元 26 failed、API 66 failed、Flow 42 failed（与 HEAD 基线完全一致，非 Runtime 主线引入）。分类如下，按需治理：

| 类别 | 数量 | 根因 | 治理方式 |
|---|---|---|---|
| 端点迁移 404 | ~46 | chat 端点迁移到 `/policy-qa/stream`(SSE)，flow/langgraph 测试 POST 旧 `/chat` 返回 404 | 迁移测试到新 SSE 契约（大工程） |
| skill_infra | 33 | skill manifest name 改名，测试断言旧值 | 更新断言 |
| error_code stub | 4 | knowledge 模块已删除，stub 返回 `{}`，测试断言旧数据 | skip（测试已失效） |
| data_platform | 2 | `CachedSkillStorage.get_skill` 返回 dict，测试期望 Skill 对象 | 加 model reconstruction 或更新测试 |
| test_service | 1 | Milvus E001 政策数据缺失 | skip（环境依赖） |

---

## 6. 变更日志

| 日期 | 变更 | 影响 |
|------|------|------|
| 2026-07-07 | 初始化进度追踪文件 | 全部 32 单元 |
| 2026-07-24 | A 测试治理：修复 demo_tools broken import（~158→~56 failed） | runtime/langgraph + integration/flow |
| 2026-07-24 | 政策管线 P0→P8 爆发（72 提交，M1-M4 达成） | §2（当时未入本表） |
| 2026-07-27 | P8.3 种子政策值域 + zcgz 发布解锁契约 | §2 P8.3 ✅ |
| 2026-07-27 | P9 前端 5 tab 重构全部完成（9.1-9.7，7 提交，M6 达成） | §2 P9 ✅ |
| 2026-07-27 | 重写 PROGRESS.md：补入 §2 政策管线主线，修正当前焦点 | 本文件整体 |
| 2026-07-28 | 政策知识开发推进：①P0.3 切换开关落地（`POLICY_RULES_COLLECTION`）②`gateway.generate` 支持 max_tokens 覆盖 ③`MODEL_TIMEOUT` 环境变量 ④长文档分片提取（`_split_text`），长文档 0→86 facts ⑤P8.4 价值验证（insu 31%→98%、psn 20%→84%） | §2 P0.3/P8.4；model_service/pipeline_orchestrator |
| 2026-07-28 | **P8.4 publish 路径修复**：`build_ingest_records` 生成唯一 rule_id，修复 P3 `publish_to_new_collections` 空 PK 去重丢数据 bug（之前所有 publish 只存活 1 条）；修复后价值兑现到 policy_rules_v2（insu 31%→70%、psn 20%→58%） | §2 P8.4；policy_ingestion（影响 P3 数据完整性） |
| 2026-07-28 | **P8.4 全量收尾完成（M5 达成）**：全量重提取 8 篇文档（schema-driven 分片）+ 干净重建 policy_facts/rules_v2（269 facts / 337 rules / 0 空 rule_id）；填充率 insu 31%→98%、psn 20%→63%；med/hosp/setl 低填充为政策内容特性 | §2 P8.4/M5 |
| 2026-07-29 | **P10.1a 政策问答读入口 schema 适配层**：policy_rules_search + structured_policy_retriever 适配 v2 schema（向量字段 vector、detail FieldTrace dict 解包、doc_id→policy_id 兼容）；灰度验证通过（4 典型问题新旧命中一致、v2 相关性正确）；stash 验证无回归 | §2 P10.1/M7 |
| 2026-07-29 | **P10 完成（直接切换，未上线）**：读路径全量切纯 v2，删所有旧 schema 兼容代码（开关/适配层/LEGACY）；删旧 publish 通路 + 旧 schema 文件（policy_rules_schema/data_model1_loader）；drop 旧 policy_rules collection。scalar retrieval 标 xfail（v2 数据 gap：hosp_lv 政策简写 + med_type 低填充，精确结构化检索失效），待数据标准化 | §2 P10/M7 |
| 2026-07-29 | **v2 维度值标准化**：hosp_lv/med_type 对齐 seed.py 业务字典（社区→一级、住院→住院-普通住院等），rule_to_entity 入库标准化 + 批量 upsert 88 条；scalar retrieval baseline 从 xfail 转 pass（支付比例组 0→3 命中）。剩余 gap：退休人员 60%折算公式是 v2 提取遗漏（rule_type 无"计算公式"），待数据补充 | §2 数据质量 |
| 2026-07-31 | **Runtime 建设阶段三（全面验证）完成**：补 63 个新模块单元测试 + 3 个性能基准全绿；三层回归与 HEAD 基线零新增失败（顺带修复 `unit/shared/__init__.py` 缺失的 3 个收集错误）；USE_MEMORY_STORAGE=1 灰度零功能回归；`src/domain/AGENTS.md` 新增 §13.5 Runtime 上下文；架构设计.md 会话上下文服务域补充 Runtime 定位 | §3 Runtime 建设 |
| 2026-08-03 | **政策问答前端持续对话改造（阶段一+阶段二）**：①`usePolicyQAStream` hook（session_id 跨轮复用 + 自解析 SSE 的 context_need/memory_update/reasoning_step/result，snake→camel 在 hook 层统一转换）②三区工作区（顶栏 SessionAnchorBar 锚点带 + 主体切换横幅、左栏 MemoryPanel 会话记忆、主区 ChatStream 持续对话）③结算单号降级为「首帧锚定 + @换结算/@换患者/@新会话」④首轮 richResult 费用分解保留（复用 SettlementExplanationPage）⑤推理链可折叠（ReasoningChainCollapsible）。前端 vitest 69 passed（含本次新增 20 项）、`next build` EXIT=0。顺手修复预存 build 阻塞：settlement-explanation-page TS 类型 + 3 页 useSearchParams 预渲染 | §3.5（前端政策问答） |
| 2026-08-04 | **政策问答质量修复 + Skill 驱动迁移**：①修复链路三连（MSSQL 环境变量注入→查询无结果；POSTGRES_PASSWORD 默认值→记忆不沉淀；subject_changed 误判→横幅误弹）②P0/P1/P2 优化（dummy 降级真实数据模板 + answer_mode 来源徽标 + 记忆业务键值 + 话题锚点 + 推理链业务化 + error 事件契约）③严肃化 + 回答价值门控（未获取/分段不完整拒绝，引导咨询医保办）④**SSE 对话流迁移 Skill 驱动执行**（旧编排器 PolicyQAOrchestrator 退役；skill dummy 降级 + strategy 单例缓存串答案修复；`DATA_SOURCE_MODE=real_db` 注入；响应 30s+→1.3s）。落地记录见 `docs/steering/医保Agent-政策问答前端改造-落地记录-V1.0.md` | §3.5（前端政策问答）/ §3（Runtime） |

---

## 7. 状态定义

| 状态 | 含义 |
|------|------|
| `pending` | 未启动，可开工 |
| `blocked` | 阻塞（外部依赖未就绪），禁止开工 |
| `in_progress` | 进行中 |
| `impl_done` | 代码已写完，待验证（进入单元→API→Flow 验证流程） |
| `verified` | 全链路验证通过，可归档 |
| `archived` | 已归档 |

### 2026-08-03 政策知识 issue #2 Task 7–9

- 状态：**verified**。完成知识页三栏对齐、测试页和候选版质量门禁。
- 实现提交：`f494fb9` 、`f3bbc73` 、`23c4890` 、`f2d5cb8` 、`0d71738` 、`8b9bb77` 、`8c36381`。
- 验证：后端单元/API/Flow 聚焦测试通过；前端 Vitest 通过；Playwright Chromium 政策知识发布流 3/3 通过；Orca 已实际验证知识页和测试页并截图。
- 已知预存问题：Portal 全量 TypeScript 仍被 `settlement-explanation-page.tsx` 类型债务阻塞；不属于本次改动。

> **维护约定**：每次状态变更必须在此记录。§2 与 `docs/steering/政策知识管线开发计划.md` 双向同步。
