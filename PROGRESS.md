# PROGRESS.md — 开发进度追踪

> **定位**：本文件是项目进度的唯一权威来源。三条进度线并行追踪：
> 1. **功能领域单元**（业务能力视图，§1）——按"最小可验证单元"切片，回答"功能做没做、验没验"。
> 2. **政策知识管线重构**（开发主线，§2）——P0-P10 重构阶段，回答"知识模型重构推进到哪、什么时候能切换生产"。
> 3. **Runtime 建设**（开发主线，§3）——医保 Agent Runtime V1.0 三阶段落地，回答"运行时智能增强验证到什么程度"。
> 状态实时更新；每个单元/阶段状态变更必须在此记录。禁止仅口头/IM 同步进度。

---

## 0. 当前焦点

**当前领域**：政策问答 Chat-first 单答案重构（§1.1 单元 1.6）

**当前阶段**：核心实现与聚焦验证已完成；R4 性能、E2E 与最终全链路验证收口中

| 阻塞项 | 原因 | 解锁条件 |
|---|---|---|
| Policy QA R4 最终验收 | 性能与 E2E 证据尚待补充 | 完成 Task 8 性能/E2E 资产与 Task 9 严格验证 |
| §10.1/10.2 安全审计 | 需对接医院 SSO / 外部系统 | 获取医院 SSO 文档 |
| §11.1/11.2 适配器 | 需真实医保 / DRG 系统 API | 获取系统 API 文档和测试环境 |

---

## 1. 功能领域单元（业务能力视图）

| 领域 | 单元数 | ✅ verified | 🟢 impl_done | 🔴 blocked | ⚪ pending | 备注 |
|------|:--:|:--:|:--:|:--:|:--:|---|
| 政策问答 | 6 | 0 | 6 | 0 | 0 | P10 已切换；Chat-first 单答案最小单元已实现，待 R4 性能/E2E 收口 |
| 结算异常导办 | 4 | 0 | 4 | 0 | 0 | — |
| 出院前质控 | 3 | 0 | 3 | 0 | 0 | — |
| 模型服务与管理 | 4 | 0 | 4 | 0 | 0 | — |
| MCP 工具管理 | 3 | 0 | 3 | 0 | 0 | — |
| 知识库管理 | 3 | 0 | 3 | 0 | 0 | §2 P9 5 tab 已上线，详见 §2 |
| 技能管理 | 9 | 6 | 3 | 0 | 0 | Skill AI 创作、候选隔离评测、人工物化与日常治理主链已验证 |
| 运营看板 | 2 | 0 | 2 | 0 | 0 | — |
| 嵌入式组件 | 1 | 0 | 1 | 0 | 0 | — |
| 安全与审计 | 2 | 0 | 0 | 0 | 2 | 待外部系统 |
| 适配器接入 | 2 | 0 | 0 | 2 | 0 | 需真实系统 |
| **合计** | **39** | **6** | **29** | **2** | **2** | — |

> **现状**：现有功能代码均 `impl_done`（写完未走正式验证流程）。验证流程见 `src/tests/AGENTS.md`
> 与 `docs/governance/TEST-VERIFICATION-MATRIX.md`。政策问答最新进度以 §1.1 单元 1.6 和 §4 为准；
> 知识库管理最新进度以 §2 政策知识管线重构为准。

### 1.1 各领域详情

#### 政策问答（Policy QA）
| # | 单元 | 涉及层 | 前端 | 后端 | 存储 | 状态 |
|---|------|:--:|------|------|------|:--:|
| 1.1 | 用户通过 Chat 提交政策问题 | F+B+S | `policy-qa/page.tsx` | `policy_qa_routes.py` → `orchestrator.py` | Milvus + SQLServer | impl_done |
| 1.2 | AI 检索政策知识库片段 | B+S | — | `policy_rules_search.py` → `structured_policy_retriever.py` | Milvus | impl_done |
| 1.3 | 费用项目自动检测 | B | — | `fee_item_detector.py` | — | impl_done |
| 1.4 | 医保政策规则语义匹配 | B | — | `semantic_mapping.py` | SQLServer | impl_done |
| 1.5 | 历史问答记录查询 | F+B+S | `qa-history/page.tsx` | `history_service.py` | PostgreSQL | impl_done |
| 1.6 | 院端经办通过 Chat-first 连续问答获取单一、安全且可追溯的政策解释 | F+B+S | `PolicyQAWorkspace` → `PolicyConversation` | `policy_qa_routes.py` → `PolicyQAPublicResult` | 任务/工作流记录 + SQL Server + Milvus | impl_done |

> **1.6 最小可验证单元成功标准**：Portal 通过 `/policy-qa/stream` 展示单一 `answer`，按 `complete/partial/unavailable` 表达可信度；确定性政策结论携带可展示引用，证据不足时明确列出不确定性；公开响应与 UI 不含内部推理、SQL、表字段或已删除的双视角/结算来源字段。核心单元、API、Flow 与 Portal 构建已通过，R4 性能和 E2E 证据完成后再转为 `verified`。

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
| 7.5 | 固定路由评测与 test 发布门禁：候选/基线差异、人工审批、唯一 active 与 shadow resolver | `skill_infra/route_evaluator.py` → `runtime/skill_management/governance_service.py` → `infra_skill_routes.py` → Portal `/skills` | verified |
| 7.6 | Skill 治理工作台方案 2：聚合读模型、双栏目录、生命周期证据、单主动作发布与调试抽屉 | `runtime/skill_management/workbench_service.py` → `/infra-skills/workbench` → Portal `/skills` | verified |
| 7.7 | Skill 管理工作台（草稿生命周期）：草稿 CRUD/复制（乐观锁）、校验/包生成、导入（ZIP/Git/受控目录）、输入指标契约与语义层交互、物化+版本登记+loader 热重载、停用/恢复/归档 | `domain/skill/draft_models.py` → `data_platform/storage/skill/draft_*` → `runtime/skill_management/{draft_service,draft_validator,package_generator,import_service,skill_input_service,materializer,lifecycle_service}.py` → `infra_skill_routes.py` → Portal `/skills`（四页签） | verified |
| 7.8 | Skill AI 创作与候选评测：已发布指标生成、人工接受、差异优化、草稿校验、隔离路由/行为评测、人工物化 | `runtime/skill_management/ai_authoring` → `candidate_evaluation.py` → `infra_skill_routes.py` → Portal `/skills/new` 与草稿编辑器 | verified |
| 7.9 | Skill 日常治理工作台：由既有版本、评测、Release 和草稿事实派生治理待办，默认主链为评测→定位问题→修改→复审→Test Shadow 发布；无第二套可变状态机。 | `/infra-skills/workbench` → Portal `/skills`、`/skills/releases` | verified |

7.4 验证证据（2026-08-05）：T1 新功能相关测试 18 passed；T2a Skill API 10 passed；T2b 版本目录 Flow 1 passed；Portal Vitest 3 passed、变更文件 ESLint 通过、Next.js build 通过；Chromium E2E 1 passed。旧 `test_skill_mention.py` / `test_skill_intent_matching.py` 中 8 个请求已下线路由的 404 为预存测试债务，不计入 7.4 通过证据。

7.5 验证证据（2026-08-05）：T1 治理模型/路由评测/存储/应用服务及统一路由回归 71 passed；T2a Skill API 14 passed；T2b 固定评测到 test shadow active Flow 1 passed；Portal Vitest 5 passed、变更文件 ESLint 通过、Next.js build 通过；Chromium E2E 2 passed；本地 PostgreSQL 治理表初始化与查询通过。发布门禁会在制品、评测配置、测试集、全量路由 Manifest 或活动基线变化后拒绝激活；高风险标签自动进入必测集，评测运行原子冻结 suite revision 与用例快照；同一 Skill 与环境由事务和唯一索引保证最多一个 active。发布写操作默认关闭，仅由本地开发脚本显式开启并要求 `skill:release:test` 权限，候选创建人与审批人均来自认证上下文且禁止自审；生产 SSO/JWT 校验仍按 §10.1 作为外部系统接入项推进。

7.6 验证证据（2026-08-05）：按 T1 → T2a → T2b 顺序分别为 35 passed、18 passed、1 passed；Portal Vitest 17 passed、全变更范围 ESLint 零错误、Next.js 生产构建通过；Chromium E2E 4 passed，覆盖固定评测到 Test Shadow 激活及刷新恢复、路由抽屉上下文、390px 无横向溢出和目录键盘导航。Orca 真实浏览器视觉检查通过，并据此修复了 Tabs 横向挤压问题；前后端最终通过统一脚本停止。聚合接口失败时目录可回退，详情证据独立失败不清空目录；审批摘要只暴露审批人、角色和时间，不包含审批理由。

兼容与回滚：运行时仍由 `SkillLoader` / `SkillRouter` 选择当前文件系统 Skill；test active 仅由 Release Resolver 以 shadow 模式解析，不切换真实流量。需要回滚控制面时停止调用 eval/release 端点即可，已登记版本、评测与发布证据不会影响现有业务执行。

7.7 验证证据（2026-08-06）：按 T1 → T2a → T2b 顺序分别为 138 passed（单元：存储 35/草稿 14/校验包 18/导入 17/输入指标 12/物化 8/生命周期 10/回归 24）、20 passed（API：草稿 14 + 端到端流程 5 + 导入 1）、5 passed（Flow：创建→保存→校验→物化→停用→恢复→归档）；Portal Vitest 118 passed（含 API client 10 + 新建向导 4）、Next.js build 通过。真实浏览器验证：经前端代理全链路 2xx（物化 201 + 版本登记）。物化写盘后 loader 热重载（`rediscover()`），占位 assembler 提供 `load()` 入口。

7.8 验证证据（2026-08-10）：Task 8 完成候选制品隔离目录、固定路由快照、Docker 行为执行适配器与 fail-closed 策略（提交 `1775779`）；Task 9 补齐六个低基数 AI 创作指标、Portal 候选评测面板和完整 Flow。按 T1 → T2a → T2b 顺序为 104/56/1 passed；Portal Vitest 31 文件 268 passed，变更范围 ESLint 零错误，Next.js 16.2.12 生产构建通过，`skill` 工作区 3173 端口 Chromium E2E 1 passed（含 390px 横向溢出门禁）。当前 Windows 环境未安装 Docker CLI，候选 runner 镜像需在部署环境构建并配置；镜像不可用时行为评测会阻断，不会回退到宿主机执行。

7.9 验证证据（2026-08-11）：严格按 T1 → T2a → T2b 为 25/31/1 passed，其中 T2b 是真实后端固定评测到 Release 的领域闭环；Portal 全量 Vitest 33 文件 328 passed，最终相关 3 文件 66 passed，全分支 57 个 Portal 改动文件 scoped ESLint 0 errors/0 warnings，Next.js 16.2.12 生产构建通过（36/36 静态页生成）。全仓 `npm run lint` 仍有范围外历史基线 107 errors/66 warnings，集中于 policy-knowledge、dashboard、settlement、thinking-chain、sse-hooks 等，未扩大本任务修复。中央 `skill` 工作区后端/前端为 8173/3173，代理与直连 workbench total 均为 1；最终 Chromium E2E 11 passed。浏览器治理主链使用 stateful route interception 验证同一 API 契约及 creator/reviewer token 分离，不声明真实持久化闭环；自动化 409 使用确定性 route interception 并验证待办、生命周期、选中 URL 不丢失，当前持久态 `settlement_explain_skill` 的语义版本 2.0.0 绑定旧 artifact hash、真实 `/versions/sync` 返回 409 仅作为现场观察的已知边界，不作为自动化证明，完整 source commit 不展示，此持久数据冲突未在本任务修复。响应式视觉矩阵覆盖 1440×1000 与 1600×1000 内联待办/决策/证据三栏、1024×900 证据抽屉、390×844 零占位移动导航及占满可用视口的详情/返回聚焦，以及 CSS zoom 2× stress check；均无页面横向溢出，全页仅一个 Skill H1，390px 产品/连接标签隐藏且角色切换控件不裁切，移动抽屉打开时主区退出可访问树，Tab/Shift+Tab 焦点循环、导航 Link 关闭及打开/关闭/Escape/遮罩焦点交接经真实浏览器验证，ArrowDown/ArrowUp 只移动焦点、Enter 打开，主操作和证据入口可聚焦。Impeccable detector 按 Task 7 一次性规则执行一次，结果 `[]`；规格复核修正未重复执行。构建稳定性偏差：未恢复 Google `next/font`，因构建端请求曾返回 101×404 且仓库无本地 Noto 字体资产，继续使用 `globals.css` 的 `Noto Sans SC, system-ui, sans-serif` 字体栈。回滚边界：恢复旧 `/skills` 编排或停止消费新增只读字段；既有 version/eval/draft/release 证据不受影响。

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
> **实施策略（P10 前）**：「平行建新通路 → 最后一把切换」。P0-P9 在新 collection（`*_v2`）上建设，
> 当时政策问答继续读取旧 `policy_rules`。P10 已在未上线阶段直接切换为纯 v2 读路径并下线旧 collection；
> 当前 Chat-first 单答案链路已使用新模型。R4 性能与 E2E 仍待完成，属于本次交付验收，不影响 P10/M7 已完成状态。

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
| **政策问答切换到新模型** | **P10** | **M7** | ✅ 完成（纯 v2 读路径，旧 collection/旧 schema/旧发布通路已下线；Chat-first 单答案已实现，R4 性能/E2E 待验收） |

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

### 2.4 V4.1 AI 原生阶段一（迭代 14，最小可信闭环）

> **设计**：`docs/steering/政策知识治理-知识页前端改造设计-V4.1.md`（V4.0 全文 + §26–§31 现状落地对齐，决策按推荐项确认）。
> **路线**：知识页从三栏流水线升级为 AI 原生四工作空间（变更集/待决策/已发布/驾驶舱）；底层沿用 V3.2 PolicyRuleUnit 契约。

| 步骤 | 内容 | 状态 |
|------|------|:--:|
| S1 | PolicyRuleUnit 契约：KnowledgeItem + rule_group_id/topic_concept/rule_type_enum/validity/evidences/semantic_bindings，服务组装派生 | ✅ 含测试 |
| S2 | 知识变更集：模型 + 存储（PG+内存）+ 按文档批次聚合服务（启发式风险分级/质量报告） | ✅ 含测试 |
| S3 | 已发布快照：published_snapshots 表 + promote 登记不可变快照 | ✅ 含测试 |
| S4 | API：`/change-sets`(列表/详情/build-from-doc) + `/published`(列表/active) | ✅ 含测试 |
| S5 | 前端：变更集列表页 + 知识 tab 工作空间导航 | ✅ 页面 200 |
| S6 | 前端：变更集审核页（AI 结论/分类 Tab/证据/风险/语义 Diff/通过驳回） | ✅ 页面 200 |
| S7 | 前端：已发布知识页（快照列表/活动版本） | ✅ 页面 200 |
| S8a | 变更集状态流转 API（submit-review/approve/reject/reprocess，状态机校验） | ✅ 含测试 |
| S8b | 规则详情 API（GET /rules/{rule_id}：规则+原文+证据+变更集归属） | ✅ 含测试 |
| S8c | 待决策队列（DecisionTask 模型+存储+从变更集生成+resolve；排除描述字段误报） | ✅ 含测试 |
| S8d | AI 治理驾驶舱聚合 API（/governance/dashboard） | ✅ 含测试 |
| S9a | 规则详情页（原文×规则双栏 + 高亮联动 + 语义映射抽屉三 Tab） | ✅ 页面 200 |
| S9b | 待决策队列页（决策卡片：问题/推荐/候选/影响/接受/跳过/看上下文） | ✅ 页面 200 |
| S9c | 驾驶舱页 + 工作空间导航（驾驶舱/工作台/变更集/待决策/已发布） | ✅ 页面 200 |
| S10 | 收尾：全量测试 + 端到端验证 | ✅ 后端 31 + 前端 39 |
| S11 | 待决策队列阶段二增强（批量决策/联动重校验） / 语义映射状态机后端化 | ⚪ 后置 |

**端到端验证**（2026-08）：doc_466953309ccf 构建变更集 CS_f8283d5c7747cdfd（111 条 additions、PENDING_REVIEW、质量报告+风险分级）；两张新表已落 PG；三个前端路由 200。

**迭代 14 阶段一·S8–S10（2026-08，V4.0 四工作空间全量落地）**：
- 变更集状态流转（submit-review/approve/reject/reprocess，状态机 409 拦截）；
- 规则详情 API（GET /rules/{rule_id}）+ 规则详情页（原文×规则双栏 + 高亮联动 + 语义映射抽屉三 Tab）；
- 待决策队列：DecisionTask 落库（PG 表 policy_knowledge_decision_tasks），从变更集生成（证据不足/值域未映射/低置信，排除描述字段误报），前端决策卡片（接受推荐/跳过/看上下文）；
- AI 治理驾驶舱：聚合 API + 前端页（处理进度/人工任务/风险/质量 + 快捷入口）；
- 工作空间导航 5 项（驾驶舱/工作台/变更集/待决策/已发布）；
- 端到端验证：CS_f8283d5c7747cdfd 状态机流转（approve→409→reprocess→approve）、500 决策任务生成与 resolve、dashboard 聚合、7 个前端路由 200；
- 测试：后端 31 通过（变更集流转/决策任务/规则详情/驾驶舱）、前端 39 通过（预存在 test_service.py Milvus 失败除外）。

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
| Policy QA Chat-first 后端契约 | ✅ 聚焦验证通过 | 严格按 T1 单元 → T2a API → T2b Flow：130 passed → 39 passed → 99 passed |
| Policy QA Chat-first Portal | ✅ 聚焦验证通过 | Task 4 流契约 37 passed；Task 5 完成时全量 Vitest 112 passed；Task 6 删除旧测试后 94 passed；`tsc --noEmit` 与 `next build` 通过。未执行或声明全仓 lint 通过 |
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
| 2026-08-05 | **Policy QA Chat-first 单答案重构（最小可验证单元 1.6）**：后端 Skill、Runtime、SSE/REST 统一为严格白名单单答案契约；删除 `patient_view`、`office_view`、`settlement_evidence`；Portal 改为最大 840px 单列 Chat-first、Composer 结算上下文标签、查证摘要与计算/来源渐进披露；旧三栏、双视角与推理链展示删除。当前已通过后端 T1/T2a/T2b 130/39/99、Portal 37/112/94、TypeScript 与构建验证；R4 性能/E2E 待收口，未声称全仓 lint 通过 | §1.1 单元 1.6；接口/原型/设计 spec |
| 2026-08-06 | **迭代 16：知识页功能优化**：①构建页性能（eligible-units ~2s→~0.7s：store 批量 claims/get_many 消除 N+1、workbench 单遍 `list_document_ids` 枚举 + `get_document(include_knowledge=False)` 跳过 KnowledgeItem 构建；前端独立并行加载 + 骨架屏，任务表首屏即时渲染）②新建任务抽屉新增全选 + 按来源文档筛选 ③审核详情页改表格化（每行一条候选知识：指标字段/单元原文/置信度/操作），表头按单元筛选，行级 通过/拒绝/退回/查看详情（行级走 `reviewKnowledge` 落库留痕，退回以 `[退回重提取]` 前缀 note 落库）；操作按钮用途与交互细节见迭代记录迭代 16 | §2 迭代 16；知识页三页 + wizard + 审核详情；后端 build/workbench 性能链路 |
| 2026-08 | **issue-9：问题1+问题2 根因修复（U1-U3）**：①U1 parse 单元边界——`structure_parser` 新增 proviso 叶子（句号收尾结构性信号），`doc_1d44e2e1db0c` 的 `n_hI9sUrj0uvBe` 收敛为仅（四）一句；②U2 指标——seed 增 `zcgz.personal_payment_ratio`（个人支付比例，draft）+ schema DETAIL_FIELDS；③U3 折算展开——新增 `rule_derivation.derive_personal_payment_ratios`（退休×系数规则 × 在职基数反解析 → 退休 personal_payment_ratio 绝对值规则，接入 migrate），检索端去掉硬编码 `rule_type=计算公式`；端到端 dry-run：273 extractions → 368 rules（含 6 derived_rules）；回归 530 passed（唯一失败为预存 test_service）。待办：U4 提取契约双值、U5 psn_type 数组化、U6 准入治理、上线（publish_object + 重跑 migrate） | §2 迭代记录；政策知识治理-需求迭代记录.md（issue-9 节） |

| 2026-08-07 | **Skill 管理页功能错误修复（GitHub issue #12）**：修复 `/skills` 草稿编辑/生命周期工作流的前端缺陷——①`skill-draft-api.ts` 6 个写操作（save/validate/delete/disable/restore/archive）漏带 `Authorization` 头，后端 dev 模式鉴权一律 401；②`deleteSkillDraft` 漏传必填 `expected_revision` 查询参数（额外 422，与 AGENTS.md 已知陷阱一致）；③校验结果响应契约错配：前端类型声明 `report:{blocking,warnings}` 而后端返回扁平 `issues`（+`has_blocking`/`revision`），编辑页读 `validation.report.blocking` 触发 TypeError 崩页，`issue.field` 应为 `issue.path`+`severity`。修复后 create→save→validate→delete 全链路经 dev token 2xx；Portal Vitest 224 passed（skill 子集 33）、tsc EXIT=0、next build 通过 | §7 Skill 管理；`infra_skill_routes` 草稿/生命周期端点 |
| 2026-08-07 | **Skill 工作台“操作过深”重构（issue #12 体验）**：治理动作从 5 Tab 钻取（选中→总览→Tab→找按钮，3-4 层）降为工作台顶层一键执行。新增纯函数 `computePrimaryAction` 依据已加载证据（item/versions/evalRuns/releases）推导唯一下一步（运行评测/创建候选/申请审批/人工审批/激活/查看证据/已激活），由顶层 `SkillPrimaryActionBar` 直接执行写操作并刷新证据，navigate 态仅切 Tab，dev 环境只读禁用。复用既有 api-client 动作函数与 Token 体系，不引入新依赖；色彩沿用蓝/琥珀/翠绿 tint 与 portal 一致。Portal Vitest 235 passed（新增 `skill-primary-action` 11 例、改写 workbench 2 例验证“不进 Tab 即见主动作”）、tsc EXIT=0、next build 通过、设计反模式检测 [] | §7.6 Skill 工作台；Portal `/skills` 工作区 |
| 2026-08-07 | **Skill 页面两个 bug 修复**：①`/skills` 顶部页签（Skill/草稿/评测记录/发布记录）active 态错乱——“Skill” tab 正则 `/\/skills\/[^/]+(\/edit)?$/` 误匹配 drafts/evaluations/releases，导致无论在哪个子页都高亮“Skill”；改为显式排除保留路径段（`RESERVED_SEGS`）。②`/skills` 工作台目录与所有 skill 列表全空（“没有符合条件的 Skill”）——前端 dev 进程复用旧实例、`NEXT_PUBLIC_API_BASE_URL` 仍指向 next.config 默认 8000，API 代理转发到错误后端实例（空数据）；重启前端指向本工作区后端 8173 修复，并记录陷阱到 AGENTS.md。Portal Vitest 235 passed、tsc EXIT=0、Orca 浏览器验证目录显示 settlement_explain_skill 与页签高亮均正确 | §7 Skill 管理；Portal `/skills` layout + 工作台 |
| 2026-08-10 | **Skill AI 创作与候选隔离评测完成**：已发布指标→AI 候选→人工接受→差异优化→校验→固定路由/隔离行为评测→人工物化全链路通过；补齐低基数观测指标与 fail-closed 部署约束 | §7.8 Skill AI 创作 |

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

### 2026-08-10 Skill 错误挖掘案例池与分型回归（plan 2026-08-10-skill-eval-mining）

- 状态：**impl_done**（后端全链路 verified；前端反馈流 + 案例池浏览 verified；分型编辑 UI / 发布门禁接入 / 浏览器 E2E 为后续）。
- 范围：把 Policy QA 的「回答有误」反馈整合进统一案例池，经 AI 类型化转换 + 人工确认投影到严格判别联合的回归资产，五个可执行维度各有确定性评测器。
- 提交：`daa51fb`(T5) · `9d5f519`(T6 后端) · `dc91f4c`(T6 前端) · `e22cf87`(T7+T8) · `885144b`(T9) · `ace8a84`(T10)。
- 已完成（10/10 计划任务）：
  1. 服务端 `qa_turn_id` 全链路（持久化 input/output、result/done/error SSE 事件、`PolicyQAHistoryItem` DTO）
  2. 前端 `qaTurnId`/`selectedSkillId`/`feedbackState`，解析器保留 qa_turn_id 同时禁止 selected_skill_id
  3. 统一案例池 + 分型回归领域模型（7 维度、5 类判别联合断言、6 类 proposal、`SkillRegressionCase`）
  4. 案例池 + 回归资产存储端口（内存/Postgres，软删除、唯一索引、乐观锁）
  5. 安全入池服务（服务端按 ID 读来源、用户+租户所有权、脱敏、二次敏感扫描、tenant+turn 去重）
  6. 反馈 / 历史批量入池 / 案例池查询 API + 前端反馈抽屉 + 评测者案例池表格
  7. AI 类型化转换服务（ModelGateway scene=`skill_eval_transform`，严格 other↔proposal 约束，失败不改状态）
  8. 人工确认/拒绝（routing→`SkillEvalCase`、5 维→`SkillRegressionCase`、other 不可执行、幂等）
  9. 五个确定性评测器（calculation/policy_content/citation/answer_quality/safety）+ 注册表，缺失 evaluator 返回 `blocked_by_evaluator` 绝不 passed
  10. 三条后端 Flow 主链 + 安全负向链 + 6 个低基数 skill_eval_* 指标
- 评测器状态：calculation / safety **available**（确定性断言）；policy_content / citation **available**（确定性）；answer_quality **available**（确定性部分，rubric 需模型时走 ModelGateway，当前未接入发布门禁）。
- 发布门禁接入：当前仅 routing（现有 SkillEvalCase 路由回归）计入 top1；safety/calculation 的 `required=true` 用例接入 candidate gate 属后续（Step 9.5 未全量落地，避免误伤）。
- 验证证据：后端三阶段全绿——单元 76（models/storage/mining/transform/confirm/evaluator/desensitization）+ API 11（feedback/pool/transform/confirm/reject）+ Flow 8（三主链 + 五安全负向）；前端 Vitest 247 passed、tsc EXIT=0。
- 仍需人工审核的风险：①answer_quality rubric 稳定性未达门禁门槛；②policy_content/citation 证据版本冻结后才能纳入门禁；③浏览器 E2E（Playwright skill-error-mining.flow）与分型编辑 UI（eval-case-editor）未实现（Task 9 Step 1-2、Task 10 Step 5）。
- 已知预存问题（非本次改动）：`ai_authoring/security.py` 工作树有未提交改动，导致 `test_draft_validator_and_package.py` 40 例失败；已 stash 验证与本次工作无关。`policy_qa/test_policy_qa.py` 4 例 `@pytest.mark.asyncio` 受 pytest_asyncio 不兼容陷阱影响，环境性失败。

### 2026-08-11 Skill 评测收尾与治理工作台增量（分支 ktyhwangfei/skill）

- 状态：**impl_done，本工作区已提交并合并 main**。
- 范围：skill-eval-mining 收尾（评测启动面板 skill-eval-launch-panel、运行详情 skill-eval-run-detail、案例池分型编辑 UI 增强、错误挖掘 E2E flow）+ governance 存储加固（`regression_results`/`regression_summary` CREATE+ALTER 双写）+ 工作台边角（evaluations 页重组、目录面板、布局导航）。
- 验证证据：后端 governance/eval 聚焦 42 passed、全量 111 passed；前端 Vitest 37 files / 342 passed；tsc EXIT=0。
- E2E 说明：新增 `skill-error-mining.flow.ts` 未在本环境运行——`playwright.config` 写死 3000/8000，当前 3000 被主工作区 D:/project（main 分支）前端占用，不含本工作区新代码（已知陷阱：多工作区端口互斥）。flow 组件交互逻辑已由 Vitest（eval-case-pool-table / eval-launch / eval-run-detail / layout-tabs 共 71 例）覆盖，合并后可在干净端口环境补跑。
- 新增文档：`docs/steering/skill草稿-指标选择与多意图输入契约-设计.md`（草稿第三步改造设计，待评审）。

> **维护约定**：每次状态变更必须在此记录。§2 与 `docs/steering/政策知识管线开发计划.md` 双向同步。
