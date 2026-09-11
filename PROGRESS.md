# PROGRESS.md — 开发进度追踪

> **定位**：本文件是项目进度的唯一权威来源。三条进度线并行追踪：
> 1. **功能领域单元**（业务能力视图，§1）——按"最小可验证单元"切片，回答"功能做没做、验没验"。
> 2. **政策知识管线重构**（开发主线，§2）——P0-P10 重构阶段，回答"知识模型重构推进到哪、什么时候能切换生产"。
> 3. **Runtime 建设**（开发主线，§3）——医保 Agent Runtime V1.0 三阶段落地，回答"运行时智能增强验证到什么程度"。
> 状态实时更新；每个单元/阶段状态变更必须在此记录。禁止仅口头/IM 同步进度。

---

## 0. 当前焦点

**Issue #37 可信问题库与匹配引擎（分支 ktyhwangfei/issue-37-38，进行中）**：Slice 1 领域模型+存储四件套（trusted_questions 表，DDL 双写）✅ `6b8a99e`；Slice 2 确定性匹配引擎（matched/candidates/no_match 三态，不确定必澄清不猜测执行）✅ `b0bf30b`；Slice 3 审核流 API（/trusted-questions CRUD + 状态机 + 同义表达运营 + /match）✅ `6065d50`；Slice 4 冷启动脚本（QA 轨迹高频挖掘 → 幂等 draft 候选，真实 PG 入库 20 条）✅ `2001e78`；Slice 5 Portal 管理页（/trusted-questions：审核流操作 + 同义表达运营 + 匹配测试；Vitest 59 文件 427 passed、build 通过、真实 PG 全链路冒烟 submit→approve→match 命中）✅。Slice 6 命中执行闭环 ✅：`/trusted-questions/match-and-execute`（matched 才回放 SemanticQuery 快照，candidates/no_match 绝不执行）+ `expected_result_traits` 确定性校验（quality/行数/必需列），golden 用例集 10 条；真实 PG+语义层端到端冒烟通过（mzjyxx.T_FundPay 回放 executed/complete）。Issue #37 六个 Slice 全部完成。**验收后修复轮（2026-09-08）**：①`query_plan` 快照口径由 LogicalQueryPlan 纠正为 `SemanticQuery`（回放实际构造对象）；②approve 查询计划闸门——pending_review→active 强制校验合法 SemanticQuery 快照，400 `QUERY_PLAN_REQUIRED`/`QUERY_PLAN_INVALID`，非法流转仍由状态机裁定 409；③错位冷启动通路拆除：Slice 4 的 seed 脚本/cold_start 挖掘的是政策问答结算解释类问题，与受控问数场景双重错位（问题类型错 + 无执行能力），删除 `seed_trusted_questions.py`/`cold_start.py` 及其测试，新增 `scripts/cleanup_trusted_question_seeds.py` 物理清理存量——真实 PG 已清理 20 条 `tq_seed_*` 无计划草稿（含 1 条本不该 active 的），全表收敛至 3 条且均带合法计划。待验收。**数据错位修复（2026-09-08）**：approve 增加 query_plan 闸门（pending_review→active 强制绑定合法 SemanticQuery 快照，400 `QUERY_PLAN_REQUIRED`/`QUERY_PLAN_INVALID`，`trusted_question_routes.py`）；拆除错位冷启动（删除 `seed_trusted_questions.py`+`cold_start.py`，其数据源 policy_qa_trajectories 是结算单解释类问题、天然无 query_plan；`scripts/cleanup_trusted_question_seeds.py --apply` 已清除 20 条 tq_seed_* 错位草稿，含 1 条 active）；真实写入路径打通——问数工作台 `/semantic-layer/query` 执行验证成功后可"存为可信问题草稿"（携带同一 SemanticQuery 快照 + metric_codes）；可信问题页匹配测试改调 `/match-and-execute`，命中即展示回放执行结果（outcome/质量/行数/违例）。验证：Unit 52 + API 23 passed（新增 approve 闸门 3 例、no_plan 防御路径改写为直接写库），前端 Vitest 61 文件 439 passed + tsc 零错误。遗留：自然语言问数入口尚未建（无 NL→SemanticQuery 链路），match-and-execute 消费方目前为可信问题页匹配测试面板。**统一验收轮（2026-09-10）**：机制复测通过——list 3 条（1 active）、match-and-execute 命中即回放（"门诊统筹基金支付是多少" → executed / quality complete / T_FundPay 0.00）；API 78 passed + 关联 Unit 116 passed；Portal /trusted-questions 页面 200。⚠️ 验收中发现数据事故：`trusted_questions` 主表为空，3 条有效数据被 09-07 的流程移入 `trusted_questions_abandoned_20260907` 备份表（多工作区共享 PG 所致）；已按列名对齐 + 从 query_plan 派生 object_code/metrics 补齐新 NOT NULL 约束恢复 3 条（1 active + 2 retired；其中 1 条 retired 问题文本为历史乱码，不影响机制）。

**Issue #38 数据目录（同分支，六个 Slice 全部完成，待统一验收）**：Slice 1 资产登记表 ✅ `1a0eb84`（`data_catalog_assets` 表 DDL 双写 + 存储四件套 + 领域字典 §13.8）；Slice 2 目录构建器 ✅ `c5d97ec`（发布版本快照口径与 planner._published_version 一致；门诊批次/行数只作用于门诊投影数据集；真实源刷新 139 资产）；Slice 3 数据目录 API ✅ `15eb867`（`/data-catalog/assets` 搜索/详情、`/refresh`、`/sla` 门诊 P95+质量门禁独立降级）；Slice 4 血缘动态推导 ✅ `99880e9`（零新表：源表 feeds 指标 belongs_to 对象 consumed_by 消费方；真实子图 106 节点/205 边）；Slice 5 Portal `/data-catalog` 页 ✅ `eb83ee7`（统一搜索+详情+血缘视图+SLA 概览+刷新；Vitest 60 文件 433 passed、build 通过）；Slice 6 验收对账 ✅：四类资产均可搜索/详情/溯源；血缘批次、`get_sync_status`、`/sla` 三口径与 `outpatient_sync_batches` 最新批次 `39934e3d` 逐字一致（ACCEPTANCE PASS）。**开源对标增强轮（2026-09-08，对标 DataHub/OpenMetadata）**：①第五类资产 `vector_collection`（Milvus 集合，真实扫描 18 个，dynamic key 以 `enable_dynamic_field` 记入摘要）；②列级元数据 `CatalogColumn` + `data_catalog_columns` 表（源表列来自发布版本 SemanticField 同源，向量集合列来自 describe_collection，刷新整体重建）；③血缘边从"查询期全量现推"改为刷新时推导落表 `data_catalog_lineage_edges`（edge_id 确定性派生幂等，查询走索引）；④`/assets` 增 owner/tag 分面过滤 + `total` 真分页，新增 `/assets/{id}/columns` 端点，`/refresh` 返回列/边重建统计；⑤owner 真实来源改发布人（published_by）、tags（域编码/指标类型/门诊同步/skill/portal页面）、值域码表回填 source_table `value_ranges`、Portal 页面声明真实消费的 `business_object` 以出血缘边；⑥Portal `/data-catalog`、`/trusted-questions` 两页重写（分面/字段清单/组件化 Dialog/Input/Textarea）。验证：Unit 38 + API 35 passed；Flow 144 passed（3 失败为 Milvus/真实 LLM 环境依赖存量，与本轮改动零 import 关联）；Portal Vitest 60 文件 435 passed、tsc 零错误、Next.js build 通过；真实 PG 冒烟刷新 157 资产/269 列/230 边，血缘子图回读 107 节点/206 边，分面过滤口径一致；领域字典 §13.8 已补录新实体。**统一验收轮（2026-09-10）**：五类资产实测可查（source_table 6 / semantic_object 11 / metric 115 / consumer 7 / vector_collection 18，共 157），血缘端点 200，/sla 双区正常；验收中复现并修复白屏 bug（前端 TYPE_META 缺 `vector_collection` 类型 + TypeBadge 无未知类型兑底，`data-catalog-api.ts`/`page.tsx`），经前端代理复测 vector_collection total=18、页面 200；API + storage 测试 passed。#37/#38 待用户统一验收。

**当前领域**：Issue #33 — 政策知识上线补强（门诊+通用，§1.1 单元 6.7）

**当前阶段**：Issue #33 机制、回填与门禁复测完成（2026-09-02 终态：structured 诚实拒答 87.5%，FAR/P@3 未达）；需求方决定门禁不放行、提交仅留档。后续已落地：路由拒答①（broad→structured 三判据路由/拒答，9/3）、加固① structured 空上下文拒答（报告 §9）、加固② broad 有效期/status 硬过滤（报告 §10）、加固③ 路由证据重排与相关性过滤（9/4）、加固④ 路由针对性修复（rule_type 硬过滤拆除 + 推断维度分区降级 + 候选池 20→50；验收表 #7-#10 SSE 复测 #8/#9/#10 达标 #7 大幅改善）、加固⑤ 双人群覆盖 + 回答按险种分组出处标注（#7 全人群覆盖实测；详见 6.7 加固③④⑤补充证据）；门禁整体仍关闭；Issue #31 仍为 `editing` 草稿（等待真实预结算接口），Issue #30（单元 1.8 轨迹持久化）待浏览器人工验收

**门诊医保数据底座 P1（2026-08-31，`impl_done`；2026-09-01 同步已启动）**：当前测试环境已自动登记 `bjybdb`，SQL Server 三张门诊表及 117 个契约字段可读，PostgreSQL 门诊结构与事务读写通过，真实页面显示“数据底座可用”；CDC 未开启并单独显示“等待 DBA”，不影响默认 5 分钟定时 SQL。**2026-09-01 定时 SQL 任务已人工启动**：基线快照 3350 行（592/2139/619）幂等落库，5 分钟心跳正常，P95 样本积累中（首批 batch `5d56bfaa`/`a3a9edb0`）。启动时修复多 worker 重复认领缺陷（认领 WHERE 补 `active_attempt_id IS NULL`、`start_job` 清残留 attempt），全量 Unit 2013 passed/2 skipped → API+Flow 460 passed/1 skipped。Firefox 在本机被 Next dev/HMR 请求停滞阻断，保留生产态复验。[P1 验证记录](docs/reviews/2026-08-28-outpatient-p1-verification.md) 持续保持证据边界；达到 P95 ≤ 300 秒并完成同步验收前不改整个 P1 为 `complete`，P2 不改 `ready_for_planning`。

| 阻塞项 | 原因 | 解锁条件 |
|---|---|---|
| §10.1/10.2 安全审计 | 需对接医院 SSO / 外部系统 | 获取医院 SSO 文档 |
| §11.1/11.2 适配器 | 需真实医保 / DRG 系统 API | 获取系统 API 文档和测试环境 |
| Issue #31 真实预结算 | 缺医院收费系统正式预结算 API 契约 | 获取接口文档、鉴权方式和联调环境 |

---

## 1. 功能领域单元（业务能力视图）

| 领域 | 单元数 | ✅ verified | 🟢 impl_done | 🔴 blocked | ⚪ pending | 备注 |
|------|:--:|:--:|:--:|:--:|:--:|---|
| 政策问答 | 8 | 2 | 5 | 1 | 0 | 单元 1.6–1.7 已验证；1.8 轨迹持久化待浏览器人工验收；单元 1.9 等待真实预结算、候选评测和审批 |
| 模型服务与管理 | 6 | 1 | 5 | 0 | 0 | 真实资产版本、加密凭据和 dev/test 运行时路由已验证；端点模型列表探测待页面验收 |
| MCP 工具管理 | 3 | 0 | 3 | 0 | 0 | — |
| 知识库管理 | 7 | 1 | 6 | 0 | 0 | §2 P9 5 tab 已上线；语义提议 S1 已完成 R4，S5 冲突维度候选已完成聚焦验证；6.7 Issue #33 上线补强已完成，门禁 3 项中 1 项达标（待需求方判定） |
| 技能管理 | 11 | 7 | 4 | 0 | 0 | 版本、治理、草稿、AI 创作、日常工作台与门诊全人群固定自测已验证；端到端评测闭环后端/页面已验证，真实 UI 端到端待执行 |
| 嵌入式组件 | 1 | 0 | 1 | 0 | 0 | — |
| 安全与审计 | 2 | 0 | 0 | 0 | 2 | 待外部系统 |
| 适配器接入 | 2 | 0 | 0 | 2 | 0 | 需真实系统 |
| **合计** | **38** | **11** | **22** | **3** | **2** | 已删除的结算异常、出院质控、运营看板不再计入现行业务能力 |

> **现状**：现行业务流只有 `policy-qa`；结算单是政策问答的必填业务数据。`/settlement`、`/qc`、`/dashboard`、`/chat` 及其旧后端编排已退役，不得作为兼容入口恢复。验证流程见 `src/tests/AGENTS.md`
> 与 `docs/governance/TEST-VERIFICATION-MATRIX.md`。政策问答最新进度以 §1.1 单元 1.6–1.8 和 §4 为准；
> 知识库管理最新进度以 §2 政策知识管线重构为准。

### 1.1 各领域详情

#### 政策问答（Policy QA）
| # | 单元 | 涉及层 | 前端 | 后端 | 存储 | 状态 |
|---|------|:--:|------|------|------|:--:|
| 1.1 | 用户携带结算单号提交政策问题 | F+B+S | `policy-qa/page.tsx` | `policy_qa_routes.py` | Milvus + SQL Server | impl_done |
| 1.2 | AI 检索政策知识库片段 | B+S | — | `structured_policy_retriever.py` | Milvus | impl_done |
| 1.3 | 问题路由到结算费用解释 Skill | B | — | `skill_router.py` → `settlement_explain_skill` | — | impl_done |
| 1.4 | 医保政策规则语义匹配 | B | — | `semantic_mapping.py` | SQLServer | impl_done |
| 1.5 | 历史问答记录查询 | F+B+S | `qa-history/page.tsx` | `history_service.py` | PostgreSQL | impl_done |
| 1.6 | 院端经办通过 Chat-first 连续问答获取单一、安全且可追溯的政策解释 | F+B+S | `PolicyQAWorkspace` → `PolicyConversation` | `policy_qa_routes.py` → `PolicyQAPublicResult` | 任务/工作流记录 + SQL Server + Milvus | verified |
| 1.7 | 瞬时结算/政策检索故障执行一次有界恢复，确定性缺失立即停止 | B+S | 恢复与查证步骤 | `policy_qa_routes.py` + 数据提供器/检索器错误分类 | SQL Server + Milvus | verified |
| 1.8 | 轨迹持久化与会话生命周期：每轮可重放公开快照落库、刷新恢复、挂起/恢复/升级医保办/回复回填 | F+B+S | `PolicyConversation` 生命周期横幅/操作 | `session_lifecycle.py` + `/sessions*` 端点 | PostgreSQL（policy_qa_trajectories + sessions 状态列） | impl_done |
| 1.9 | 院端经办按费用明细 ID 和数量预览门诊部分项目退费影响 | B | — | `skill_drafts/outpatient_pre_refund_analysis_skill`（未物化）→ `BillingPort` | 医院收费系统正式预结算（待真实接入） | blocked |

> **1.8 验收标准**（Issue #30）：每轮 QA 公开轨迹（context_need/memory_updates/完整 result）持久化，按会话回放重建对话/记忆/锚点；会话状态机 active⇄suspended、active→escalated→(resolve)→active、→closed；非活跃会话拒绝新问答（409 SESSION_NOT_ACTIVE）；升级工单复用 task_closure（waiting_human_confirmation），医保办回复回填后会话恢复。设计见 `docs/steering/政策问答-轨迹持久化与挂起升级恢复-设计-V1.0.md`。

> **1.6–1.7 验收标准**：Portal 只通过 `/policy-qa/stream` 展示单一 `answer`，请求必须携带 `settlement_id`；`/settlement`、`/qc`、`/dashboard`、`/chat` 返回 404。确定性政策结论携带可展示引用，证据不足时明确不确定性。瞬时结算或政策检索故障全局最多执行 2 次尝试；结算不存在、配置错误和普通业务错误不重试；`done` 事件记录 `attempt_count` 与 `halt_reason`，公开步骤不泄露 SQL、表字段或内部推理。

> **Issue #21 验证证据（2026-08-25）**：T1 聚焦单元 177 passed（全量 Unit 因缺 `fakeredis`/`mcp` 在收集期中止）；T2a Policy QA API 40 passed；T2b Flow 全覆盖 139 passed / 1 optional skipped；Portal 相关 Vitest 65 passed、TypeScript、scoped ESLint、Next.js build 与 `compileall` 通过；Chromium Policy QA + smoke 9 passed，真实确认 `/settlement`、`/qc`、`/dashboard` 为 404。Locust 在当前 Windows 环境因 `gevent` DLL 加载失败未运行，使用 5 并发 SSE 25 次等价烟压补证：0 失败、P95 406.32ms、`max_attempt_count=1`。全量 API、Portal 与 lint 的范围外存量失败如实记录在 §4–§5，不计作本单元通过证据。

> **Issue #31 状态更正（2026-08-31）**：此前误将未完成真实接口接入和发布门禁的候选包放入正式 `skills/` 并接入 `/policy-qa/stream`。现已撤出正式加载与公开 API，候选包通过既有导入服务登记为 `editing` 草稿；金额一致性、高风险拦截和一次恢复逻辑仅在隔离候选测试中验证。聚焦 T1/T2a 分别 187/79 passed，T2b 全量 139 passed / 1 skipped；全量 T1 因已记录的 `fakeredis`/`mcp` 缺失在收集期中止，全量 T2a 为 282 passed / 18 个已记录存量失败。解锁条件为真实收费系统接入、候选评测通过和人工审批。

#### 模型服务与管理（Model Service）
| # | 单元 | 后端 | 状态 |
|---|------|------|:--:|
| 4.1 | 模型配置 CRUD | `model_routes.py` | impl_done |
| 4.2 | 模型在线测试（流式 SSE） | `model_routes.py` → SSE | impl_done |
| 4.3 | 模型路由（type+scene 策略） | `model_service/gateway/` → `router/` | impl_done |
| 4.4 | 模型异常分类处理 | `model_service/exceptions/` | impl_done |
| 4.5 | 提示词/模型/路由真实资产版本治理并驱动 dev/test 运行时 | `model_service/governance_*` → `ModelGateway` → Portal `/model-governance` | verified |
| 4.6 | OpenAI-compatible 端点模型列表探测与模型名可搜索选择/手填兜底 | `OpenAICompatibleProvider.list_models` → `/model-governance/models/probe-list` → Portal 模型表单 | impl_done |

4.5 验证证据（2026-08-17）：治理发布后的提示词、模型与路由成为 dev/test 真实运行时来源，无活动发布时才使用代码/静态配置回退；配置损坏失败关闭。API Key 通过 Fernet 密文保存，凭据以 endpoint fingerprint 和 revision 绑定，响应、日志与页面不回显明文；模型发布要求内容哈希与当前密钥指纹完全匹配的成功连接测试。按 T1 → T2a → T2b → T3 → Portal → T4 顺序分别为 89 passed、23 passed、2 passed、4 passed（20 条治理路由解析均值 0.876ms）、Vitest 21 passed + `tsc --noEmit` + Next.js build、Chromium E2E 连续两次各 1 passed（清空外部主密钥，治理 flow 专用 Playwright 配置禁止复用 8000/3000 服务并以 dev + 内存存储 + E2E 专用 Fernet key 独立启动；OpenAI-compatible 测试 Provider 严格校验 method/path/auth/model/参数），覆盖收费员直入、真实提示词全文、模型连接/审核/发布、下拉路由、提示词新版本生效/回滚、390px 无横向溢出及 API Key 页面/响应无泄漏。显式运行计划原命令 `npm test -- flows/portal/model-governance.flow.ts --project=chromium` 或别名 `npm run test:model-governance -- --project=chromium` 时才进入专用配置，默认/全量 E2E 明确排除该写流程。补充独立性验证：父 shell 故意设置错误的 `PORTAL_BASE_URL` / `NEXT_PUBLIC_API_BASE_URL` / `PORT` 时 Chromium 仍 1 passed；发布新提示词后故意中断的首次执行由 afterEach 恢复基线，同一 Playwright 进程 retry #1 完整通过。权限管理页尚未实现，当前仍沿用开发身份写/审/发门禁，是下一阶段工作。

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
| 6.4 | 政策抽取主动生成可审核的指标/值域提议与冲突维度候选，发布后进入统一语义契约 | `/semantic-layer/proposals` | `pipeline_orchestrator.py` → `semantic_alignment.py` → `semantic_alignment_routes.py` | verified |
| 6.5 | 从指定发布版本的异常规则生成结构诊断、bjyb 证据和未发布治理草稿 | `/policy-knowledge/knowledge/semantic-discovery` | `rule_governance.py` → `semantic_alignment_routes.py` | impl_done |
| 6.6 | 政策—数据语义协同发现（PDSC）：检测引擎、发现簇去重聚类、全政策交叉验证、价值分、值域对齐、人工裁决、拆分/合并、激活流水线与 PolicyApplicabilityRelation/Skill 解析 | `/policy-knowledge/knowledge/semantic-discovery` 语义发现决策卡（含扫描/拆分/激活） | `pdsc.py` + `pdsc_detectors.py` + `pdsc_routes.py` + `pdsc_filter_bridge.py` | impl_done |
| 6.7 | 政策知识上线补强（Issue #33，门诊+通用）：读路径统一 resolver、金额段/适用性存量回填、dynamic field 过滤修复、诚实拒答出口、真实语料门禁复测 | — | `release_resolver.py` + 五条读路径 + `backfill_amount_band.py` / `backfill_applicability_outpatient.py` + `broad_policy_retriever` 硬冲突排除 | impl_done |

6.4 验证证据（2026-08-12，R4）：严格按 T1 → T2a → T2b → T3 → T4 执行。T1 聚焦回归 125 passed / 1 optional skipped，真实 PostgreSQL 事务节点另 1 passed；T2a 语义提议与指标变更门禁 API 37 passed；T2b 抽取未知概念→提议→审核→发布→契约可读 Flow 及相关知识流程 7 passed；Portal Vitest 24 passed、TypeScript 与 Next.js 生产构建通过；真实 PostgreSQL 后端的 Locust 50 用户运行 60 秒完成 12,683 次提议列表请求，0 失败、P95 29 ms；Chromium 提议审核发布流程 1 passed。V1 交付设计 §11–§12 规定的 S1 最小闭环，S2 需求缺口、S3 数据扫描、S4 派生模式保留为后续增量信号源。

6.4 S5 验证证据（2026-08-14，聚焦）：规则值归一化、身份签名、严格分区、竞争分区降级、候选幂等/失效/再出现、七类人工建模结论、Enum 维度和值域发布及抽取快照接入已实现。T1 85 passed / 1 optional skipped；T2a 16 passed；T2b 1 passed；Portal Vitest 8 passed，TypeScript 与 Next.js build 通过。按本次需求未扩大到全量、性能或浏览器 E2E 测试。

6.4 原子规则语义修复（2026-08-18，聚焦）：规范规则主体改为表达完整业务度量，综合报销比例与具体基金分项比例不再压扁为通用 `payment_ratio`；细化主体仍复用基础比例结果字段，不扩张语义层指标。相关单元 17 passed、API 1 passed、Flow 1 passed；真实任务 `CS_TASK_630837f92752b70d` 重建后 7/7 规范规则可发布，实时审核页返回 200。

6.5 验证证据（2026-08-20，聚焦）：按单元 → API → Flow 顺序完成 61 passed / 1 skipped、19 passed、1 passed；Portal 12 passed，TypeScript 检查通过。真实 PostgreSQL 的 `REL_202608182` 复验输出三个独立问题：医疗机构类别（两条规则）、大额医疗互助资金（`rule_3222a148156d8c7d`）和综合待遇比例纠偏（`rule_4df372b59673556e`）。页面与新增 API 路径实时返回 200；草稿仅进入审核队列，不写 Milvus、不自动发布。

6.6 验证证据（2026-08-21，PDSC 后端+前端+全 Phase 补齐）：后端单元 30 passed（§4.2 六类检测器、§5.2 自动库值与失败降级、§6.1 拆分、§11.2/§11.3 激活流水线含 §13.10 失败不改活动版本、未预期异常落激活记录、无受影响文档平凡通过，及 §13 项 1-9 与门禁）；API 10 passed（鉴权、完整治理流、扫描接入、拆分、激活失败步骤上报）；桥接 4 passed（无关系/异常服务退回旧路径、已发布关系转换、draft 关系不消费）；前端决策卡 Vitest 8 passed（扫描报告、激活失败步骤展示、拆分需理由）；TypeScript 检查通过；回归 semantic_alignment 78 / semantic_layer 145 / Portal 相关 20 passed（trace_store 1 个失败与会话前 WIP 改动相关，与 PDSC 零 import 关联）；真实 PG 数据冒烟：304 条提取行扫描 → 8 个结构压缩信号 → 去重聚 4 簇，检测器对不可重放行自动过滤。设计偏差：§11.1 状态机未收敛至 SemanticProposal（簇独立 ClusterStatus，功能等价，两套审核入口待后续收敛）；激活中重提取依赖 MODEL_API_KEY，未配置时明确失败而非静默跳过。

6.7 验证证据（2026-09-02，Issue #33 收尾）：统一 resolver `release_resolver.py` 接入五条读路径 + 回填 API 改 active 感知写入；金额段 27 条数值化与门诊+通用 351 条 ×6 适用性字段已 --apply 到 active release 集合 `policy_rules_REL_20260827_MZ8_V3`（住院 67 条全部未回填）；dynamic field 修复使适用性/金额段过滤在生产真实生效（此前 describe 看不到动态键被静默跳过）。单元 814 passed / 1 skipped，API 105 passed。真实语料门禁终态复测（82 条用例，`docs/reviews/2026-09-02-issue33-real-corpus-baseline.md` §8）：structured 诚实拒答 87.5% **达标**；FAR structured 12.5% / broad 39.6%（目标 <8%）与 P@3 structured 8.3% / broad 23.8%（目标 >90%）**未达**，剩余失败逐案归因与后续候选见报告 §8.4/§8.6，门禁不放行（需求方 2026-09-02 决定）。

6.7 加固①补充证据（2026-09-02）：structured 空上下文必须拒答落地（`plan_queries` 返回空 + `retrieve` 短路 `refusal_reason/refusal_message`，显式 custom_queries 不受限），先红后绿 5 例，单元 819 / API 105 passed。真实语料复测（报告 §9）：structured 负例误答 6/48→0/48，负例 FAR 0%、诚实拒答 100%，正向不受影响；合成 text_only 对照不变、structured FAR 下降（§9.4 新基线）。门禁整体仍关闭。

6.7 加固②补充证据（2026-09-02）：broad 有效期/publish_status 硬过滤落地，与 structured 共用 `policy_validity` helper（publish_status=published + effective<=ref + expiry>=ref/9999 哨兵，精确当天有效），broad 补 `_get_collection_fields` 字段存在性判定（缺字段跳过不误杀）。先红后绿 8 例，单元 827 / API 105 passed。**关键实测修正**：19 条 broad 负例误召规则全部 published/expiry=9999，加固后真实语料 eval 四基线逐位一致——broad FAR 39.6% 不因本加固移动（语料无过期/未发布规则），版本类 5 条负例属问题语义 gap；报告 §10 落档。门禁整体仍关闭。

6.7 加固③补充证据（2026-09-04）：路由层证据相关性治理——`build_structured_queries` 挂 `search_text=原问题` 激活 execute_query 内置 BM25 重排（候选不再退化 Milvus 插入序）；路由消费前 `_rerank_evidence_by_relevance` 对证据做 BM25×向量几何平均融合重排，top5 截断 + 0.25 相关性带剔除缴费/划入类噪声；候选池最高语义余弦 <0.62 整体不相关时 `low_relevance` 诚实拒答；embedding 不可用时降级 BM25-only，零词面信号不误杀。先红后绿 5 例，路由单测 33 passed；全量回归单元 2344 / API 368 / Flow 144 passed（7 个失败均为 HEAD 预存，stash 前后复现验证，与本次无关）。API 复测（SSE）：「门诊报销比例是多少」答案消费证据从 20 条（统筹60%/90%、个人账户划入等噪声）收敛为门诊大额互助 80%/70% 相关规则。路由三口径基线重跑（13 用例，`scripts/eval/issue33_router_baseline_result.json` 2026-09-04）：路由准确率 1.0 / 误路由 0.0 / 确定性拒答率 1.0 不变，structured 命中案 evidence_count 20→2~4、top 证据全部换成问题相关规则。门禁整体仍关闭。

6.7 加固④补充证据（2026-09-04，验收表第 2 步 A/B 向四用例固化）：路由针对性三缺陷修复——①推断不出规则类型时不再兜底 `rule_type=支付比例` 硬过滤（备案流程类候选池曾被清空导致答非所问，验收 #10 实证），类型偏好交重排软把关；②推断维度（险种/医疗类别/人群/医院等级/规则类型）进入重排：非空错配分区降级（用户点名维度上事实不适用=答错而非不相关）、匹配有界加分 0.12、空值中性不误伤通用规则（人群/医院等级做"人员"/"医院"归一，"在职人员"vs"在职职工"实测过）——相关词面 2 倍差距实证加权压不过，故采用分区而非加权；③路由候选池 top-K 20→50（`StructuredPolicyQuery.top_k` 透传，期望 70% 规则曾截在池外，验收 #8 实证），消费仍 top5。先红后绿 5 例（3 红 2 锁），路由单测 38 passed；全量回归单元 2349 / API 368 / Flow 144 passed（失败集与加固③前逐位一致，全为 HEAD 预存）。13 例路由基线前后 diff：三口径 1.0/0.0/1.0 不变，7 条拒答 + B_CAP + CLOSED 逐位 same 零回退，5 条命中案全改善（#8 top 换成三级/在职 60%+70% 两条 golden 规则，#10 top 换成真备案规则）；82 例真实语料基线质量指标逐位不变（仅时间戳差异，已还原）。线上 SSE 复测：#8 答 60%+70% 针对性命中、#9 封顶线 10 万、#10 答出备案手续流程，#7 答出退休/在职 90%+大额 80%（居民 55% 在证据 top5 但模型未采纳，残留小项：#8 混入一条缴费规则）。门禁整体仍关闭。

6.7 加固⑤补充证据（2026-09-04，双人群覆盖 + 回答结构出处）：面向用户以职工/居民为主——①B 向无险种问题时 `_ensure_insu_coverage` 保障两大人群各有代表证据（相关性 top-N 曾把居民全裁，#7 实证），用排位最高的人群代表替换选中列表最低位非代表项、不扩答案长度，A 向已限定险种不扩展；②回答组织对齐政策原文习惯：按【职工医保】【居民医保】分组（职工优先）、每条标注出处（险种·规则类型·施行年份，1900 日期哨兵不渲染），LLM prompt 与降级 fallback 同结构（`_format_broad_evidence` 共用）；`StructuredPolicyEvidence` 增 `doc_id` 透传（文件名级标注待 doc 注册表）。先红后绿 7 例（覆盖 2 + 格式 5），全量回归单元 2356 / API 368 / Flow 144 passed（失败集不变）；线上 SSE 复测：#7 答出【职工医保】4 条（退休/在职 90%、大额 80%/70%）+【居民医保】55%/50% 全人群覆盖，#8 分组命中 60%+70%（出处标注正确，残留：混入缴费规则与一条"60%。"碎片）。门禁整体仍关闭。

#### 技能管理（Skill）
| # | 单元 | 后端 | 状态 |
|---|------|------|:--:|
| 7.1 | 技能注册/加载/路由 | `skill_loader.py` → `skill_router.py` | impl_done |
| 7.2 | 费用解释 Skill 执行 | `settlement_explain_skill/` → assembler | impl_done |
| 7.3 | 技能列表与管理 | `infra_skill_routes.py` | impl_done |
| 7.4 | 版本化 Skill 资产库：制品哈希、版本登记、证据查询与 Portal 展示 | `skill_infra/artifact.py` → `runtime/skill_management/version_service.py` → `infra_skill_routes.py` → Portal `/skills` | verified |
| 7.5 | 固定路由评测与 test 发布门禁：候选/基线差异、人工审批、唯一 active 与 shadow resolver | `skill_infra/route_evaluator.py` → `runtime/skill_management/governance_service.py` → `infra_skill_routes.py` → Portal `/skills` | verified |
| 7.6 | Skill 治理工作台方案 2：聚合读模型、双栏目录、生命周期证据、单主动作发布与调试抽屉 | `runtime/skill_management/workbench_service.py` → `/infra-skills/workbench` → Portal `/skills` | verified |
| 7.7 | Skill 管理工作台（草稿生命周期）：草稿 CRUD/复制（乐观锁）、校验/包生成、导入（ZIP/Git/受控目录）、输入指标契约与语义层交互、物化+版本登记+loader 热重载、停用/恢复/归档 | `domain/skill/draft_models.py` → `data_platform/storage/skill/draft_*` → `runtime/skill_management/{draft_service,draft_validator,package_generator,import_service,skill_input_service,materializer,lifecycle_service}.py` → `infra_skill_routes.py` → Portal `/skills`（四页签） | verified |
| 7.8 | Skill AI 创作与候选评测：已发布指标生成、人工接受、差异优化、草稿校验、隔离路由/行为评测、人工物化 | `runtime/skill_management/ai_authoring` → `candidate_evaluation.py` → `infra_skill_routes.py` → Portal `/skills/new` 与草稿编辑器 | verified |
| 7.9 | Skill 日常治理工作台：由既有版本、评测、Release 和草稿事实派生治理待办，默认主链为评测→定位问题→修改→复审→Test Shadow 发布；无第二套可变状态机。 | `/infra-skills/workbench` → Portal `/skills`、`/skills/releases` | verified |
| 7.10 | 门诊结算全人群固定自测：保留结算单原始金额、禁止通用公式反推个人自付一，固定不同人群/险种/支付渠道真实快照并支持页面编辑和一键回归 | `mzsettlement_verify_skill/self_test_cases.yaml` → 自测 API → Portal `/skills/evaluations?skill=mzsettlement_verify_skill` | verified |
| 7.11 | Skill 端到端评测闭环：通用任务/数据集版本/Benchmark 三类资产、真实 Policy QA 执行与 prefix 归因、可选 Judge（blocked 不伪造通过、不可翻确定性失败）、失败簇改进任务与复测、正式 Benchmark 驱动 Release 门禁、评测页四工作区重组 | `domain/skill/governance_models.py` → `runtime/skill_management/{evaluation_runner,evaluation_attribution,evaluation_judge}.py` → `governance_service.create_benchmark_run` → `/infra-skills/eval-benchmarks|eval-runs` → Portal `/skills/evaluations` | impl_done |

7.4 验证证据（2026-08-05）：T1 新功能相关测试 18 passed；T2a Skill API 10 passed；T2b 版本目录 Flow 1 passed；Portal Vitest 3 passed、变更文件 ESLint 通过、Next.js build 通过；Chromium E2E 1 passed。旧 `test_skill_mention.py` / `test_skill_intent_matching.py` 中 8 个请求已下线路由的 404 为预存测试债务，不计入 7.4 通过证据。

7.5 验证证据（2026-08-05）：T1 治理模型/路由评测/存储/应用服务及统一路由回归 71 passed；T2a Skill API 14 passed；T2b 固定评测到 test shadow active Flow 1 passed；Portal Vitest 5 passed、变更文件 ESLint 通过、Next.js build 通过；Chromium E2E 2 passed；本地 PostgreSQL 治理表初始化与查询通过。发布门禁会在制品、评测配置、测试集、全量路由 Manifest 或活动基线变化后拒绝激活；高风险标签自动进入必测集，评测运行原子冻结 suite revision 与用例快照；同一 Skill 与环境由事务和唯一索引保证最多一个 active。发布写操作默认关闭，仅由本地开发脚本显式开启并要求 `skill:release:test` 权限，候选创建人与审批人均来自认证上下文且禁止自审；生产 SSO/JWT 校验仍按 §10.1 作为外部系统接入项推进。

7.6 验证证据（2026-08-05）：按 T1 → T2a → T2b 顺序分别为 35 passed、18 passed、1 passed；Portal Vitest 17 passed、全变更范围 ESLint 零错误、Next.js 生产构建通过；Chromium E2E 4 passed，覆盖固定评测到 Test Shadow 激活及刷新恢复、路由抽屉上下文、390px 无横向溢出和目录键盘导航。Orca 真实浏览器视觉检查通过，并据此修复了 Tabs 横向挤压问题；前后端最终通过统一脚本停止。聚合接口失败时目录可回退，详情证据独立失败不清空目录；审批摘要只暴露审批人、角色和时间，不包含审批理由。

兼容与回滚：运行时仍由 `SkillLoader` / `SkillRouter` 选择当前文件系统 Skill；test active 仅由 Release Resolver 以 shadow 模式解析，不切换真实流量。需要回滚控制面时停止调用 eval/release 端点即可，已登记版本、评测与发布证据不会影响现有业务执行。

7.7 验证证据（2026-08-06）：按 T1 → T2a → T2b 顺序分别为 138 passed（单元：存储 35/草稿 14/校验包 18/导入 17/输入指标 12/物化 8/生命周期 10/回归 24）、20 passed（API：草稿 14 + 端到端流程 5 + 导入 1）、5 passed（Flow：创建→保存→校验→物化→停用→恢复→归档）；Portal Vitest 118 passed（含 API client 10 + 新建向导 4）、Next.js build 通过。真实浏览器验证：经前端代理全链路 2xx（物化 201 + 版本登记）。物化写盘后 loader 热重载（`rediscover()`），占位 assembler 提供 `load()` 入口。

7.8 验证证据（2026-08-10）：Task 8 完成候选制品隔离目录、固定路由快照、Docker 行为执行适配器与 fail-closed 策略（提交 `1775779`）；Task 9 补齐六个低基数 AI 创作指标、Portal 候选评测面板和完整 Flow。按 T1 → T2a → T2b 顺序为 104/56/1 passed；Portal Vitest 31 文件 268 passed，变更范围 ESLint 零错误，Next.js 16.2.12 生产构建通过，`skill` 工作区 3173 端口 Chromium E2E 1 passed（含 390px 横向溢出门禁）。当前 Windows 环境未安装 Docker CLI，候选 runner 镜像需在部署环境构建并配置；镜像不可用时行为评测会阻断，不会回退到宿主机执行。

7.9 验证证据（2026-08-11）：严格按 T1 → T2a → T2b 为 25/31/1 passed，其中 T2b 是真实后端固定评测到 Release 的领域闭环；Portal 全量 Vitest 33 文件 328 passed，最终相关 3 文件 66 passed，全分支 57 个 Portal 改动文件 scoped ESLint 0 errors/0 warnings，Next.js 16.2.12 生产构建通过（36/36 静态页生成）。全仓 `npm run lint` 仍有范围外历史基线 107 errors/66 warnings，集中于 policy-knowledge、dashboard、settlement、thinking-chain、sse-hooks 等，未扩大本任务修复。中央 `skill` 工作区后端/前端为 8173/3173，代理与直连 workbench total 均为 1；最终 Chromium E2E 11 passed。浏览器治理主链使用 stateful route interception 验证同一 API 契约及 creator/reviewer token 分离，不声明真实持久化闭环；自动化 409 使用确定性 route interception 并验证待办、生命周期、选中 URL 不丢失，当前持久态 `settlement_explain_skill` 的语义版本 2.0.0 绑定旧 artifact hash、真实 `/versions/sync` 返回 409 仅作为现场观察的已知边界，不作为自动化证明，完整 source commit 不展示，此持久数据冲突未在本任务修复。响应式视觉矩阵覆盖 1440×1000 与 1600×1000 内联待办/决策/证据三栏、1024×900 证据抽屉、390×844 零占位移动导航及占满可用视口的详情/返回聚焦，以及 CSS zoom 2× stress check；均无页面横向溢出，全页仅一个 Skill H1，390px 产品/连接标签隐藏且角色切换控件不裁切，移动抽屉打开时主区退出可访问树，Tab/Shift+Tab 焦点循环、导航 Link 关闭及打开/关闭/Escape/遮罩焦点交接经真实浏览器验证，ArrowDown/ArrowUp 只移动焦点、Enter 打开，主操作和证据入口可聚焦。Impeccable detector 按 Task 7 一次性规则执行一次，结果 `[]`；规格复核修正未重复执行。构建稳定性偏差：未恢复 Google `next/font`，因构建端请求曾返回 101×404 且仓库无本地 Noto 字体资产，继续使用 `globals.css` 的 `Noto Sans SC, system-ui, sans-serif` 字体栈。回滚边界：恢复旧 `/skills` 编排或停止消费新增只读字段；既有 version/eval/draft/release 证据不受影响。

7.10 验证证据（2026-08-31，聚焦）：Skill 单元 25 passed，新增 API 1 passed，门诊政策问答 Flow 1 passed；Portal 相关 Vitest 4 文件 50 passed，TypeScript、scoped ESLint 与 Next.js 生产构建通过。真实服务使用交易号 `011100030X260417004975` 复验：个人自付一保留结算单原值 510.96 元，旧通用反推公式与中间实际/期望值均未进入回答正文；28 个固定人群案例全部通过，自测页面返回 200。

7.11 验证证据（2026-08-31）：严格按层验证，Unit（领域/存储/runner/评测器/治理）66 passed → API（infra_skill_routes + policy_qa_routes）78 passed → Flow（suite + benchmark + release）3 passed；评测闭环 Benchmark Flow 覆盖导入 28 例 → 冻结 → 建 Benchmark → person-21 错误金额归因 calculation → 改进任务 → 修复后完整通过。Portal 聚焦 Vitest 4 文件 13 passed、TypeScript 零错误、scoped ESLint 零错误、Next.js 生产构建通过。确定性规则已验证：Judge blocked/needs_review 不伪造通过、不可翻确定性失败；发布门禁接入 `_benchmark_evidence_failures`。回答质量首轮 0/28：回答未报告任何金额原值；修复后回答完整报告费用组成（标签+原值+零值业务提示），并将数据集断言从单数字子串强化为组成六要素（个人自付一/医保范围内金额/基金支付总金额的标签与原值）；v2 数据集（EVD_71b7660471bd4f37b5c5a90a1e7e0669）Benchmark 运行 EVR_cb9485f96dbb4f98bb647a0e80e1ac15 status=passed，behavior 28/28、answer_quality 28/28。环境阻塞：真实服务 UI 端到端（页面导入/冻结/正式 Benchmark 运行与运行 ID 记录）待执行，交易号 `011100030X260417004975` 的真实运行验收待补。

#### 嵌入式 / 安全与审计 / 适配器接入
| # | 单元 | 状态 | 备注 |
|---|------|:--:|---|
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
> 当前 Chat-first 单答案链路已使用新模型；Issue #21 已完成唯一入口、有界恢复、并发 SSE 烟压与 E2E 验收。

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
| **政策问答切换到新模型** | **P10** | **M7** | ✅ 完成（纯 v2 读路径，旧 collection/旧 schema/旧发布通路已下线；Issue #21 E2E 与 SSE 烟压已验收） |

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
> **当前架构边界（Issue #21）**：保留 RuntimeContext、Memory、Context Planner 等通用支撑；现行业务只由
> `runtime/api/policy_qa_routes.py` 编排。历史 `scenario_executor`、LangGraph、通用 orchestrator 及其结算异常/出院质控场景已删除。

### 3.1 三阶段路线图进度

| 阶段 | 内容 | 状态 |
|------|------|:--:|
| 阶段一：地基建设（任务 1.1-1.7） | RuntimeContext 跨轮字段、BusinessMemory、MemoryStore/Manager、ContextComposer 骨架、WorkflowInstance 扩展 reasoning_state | ✅ 完成 |
| 阶段二：智能增强（任务 2.1-2.6） | ContextPlanner、Token Budget + 摘要策略、ReasoningState、ExpirePolicy.TIME、主体切换检测 | ✅ 完成；旧 scenario_executor 集成已于 Issue #21 退役 |
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

### 3.5 Issue #21 有界恢复循环

- 依据：`docs/research/LoopEngineering.md`。
- 边界：只包围 Policy QA 的结算数据读取与政策检索两个可恢复步骤，不恢复已退役业务编排。
- 预算：一次请求全局最多 2 次尝试；只有连接、超时及数据库/向量服务瞬时异常可重试一次；Milvus SDK 内部重试已关闭，避免绕过全局预算。
- 停止：结算记录不存在、配置错误、业务校验错误立即停止；相同瞬时失败再次出现记为 `stalled`，不同数据源耗尽共享预算记为 `max_attempts`，成功记为 `verified`。
- 可观测：SSE `done` 与任务输出记录 `attempt_count`、`halt_reason`；只发布恢复/查证状态，不发布内部推理。

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
| Policy QA 唯一入口与有界恢复 | ✅ 全链路验证通过 | T1 177、T2a 40、T2b 139 passed / 1 skipped；并发 SSE 25/25、Chromium E2E/smoke 9/9，详见 §1.1 |
| 门诊部分项目预退费分析 | 🟡 草稿候选 | 正式加载与公开 API 已撤回；T1/T2a 187/79 passed，T2b 139 passed / 1 skipped；真实接口、评测和审批未完成 |
| Policy QA Chat-first Portal | ✅ 聚焦验证通过 | 相关 Vitest 65 passed；`tsc --noEmit`、scoped ESLint、Next.js build 通过；全量 352 passed / 3 个范围外知识治理失败 |
| 模型治理真实资产运行时 | ✅ 全链路验证通过 | T1 89、T2a 23、T2b 2、T3 4、Portal Vitest 21、TypeScript/build、Chromium E2E 1 均通过 |
| 全量回归（2026-08-25） | ⚠️ 有范围外存量问题 | Unit：缺 `fakeredis`/`mcp` 导致 3 个收集错误；API：273 passed / 19 failed；Flow：139 passed / 1 optional skipped；Portal：352 passed / 3 failed，见 §5 |

### 4.1 已知验证环境约束

- 全量单元测试收集依赖仓库当前未安装的可选测试包 `fakeredis`、`mcp`、`respx`；Issue #21 聚焦单元不依赖这些包。缺包结果必须单独记录，不得伪报为代码失败或跳过分层验证。
- Locust 已安装，但当前 Windows Python 的 `gevent` 扩展 DLL 无法加载；本次用 5 并发、25 次真实 SSE 请求补证，不声称 Locust 正式压测通过。
- Portal 全仓 lint 现有 92 errors / 62 warnings；Issue #21 变更的 Portal 文件 scoped ESLint 为 0。

---

## 5. 测试套件债务（已知失败）

> 历史失败口径已随 Issue #21 删除无效旧业务测试而失效。当前只保留下列仍存在的环境/模块债务：

| 类别 | 数量 | 根因 | 治理方式 |
|---|---|---|---|
| MCP API | 2 | 当前 `create_app()` 未注册 `/mcp/*`，测试期望 200 | 单独确认 MCP 管理面是否继续对外暴露 |
| 政策知识 API | 3 | release build 409；编译 trace 最新版本选择不稳定 | 在政策知识治理任务修复 |
| Skill 草稿/工作台 API | 14 | `create_from_template()` 与路由的 `output_schema` 参数不一致 | 在 Skill 治理任务统一契约 |
| Portal 知识治理 | 3 | 导航工作域数量、region 语义和未发布快照断言与实现不一致 | 在政策知识前端任务修复 |
| Portal 全仓 lint | 154 | 92 errors / 62 warnings，集中于政策知识、语义层和 Skill 历史页面 | 分模块治理；本次只要求变更范围零新增 |
| 可选测试依赖 | 收集期 | `fakeredis`、`mcp`、`respx` 未安装 | 在完整测试环境安装仓库测试依赖后重跑；不为 Issue #21 增加运行时依赖 |

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
| 2026-08-17 | **后台管理真实资产版本与模型接入**：真实提示词/模型/路由发布接入 dev/test 运行时；Fernet 凭据、连接测试发布门槛、版本只读/新建/回滚与资产中心 E2E 完成 | §1 模型服务与管理 4.5；§4 验证证据 |
| 2026-08-19 | **dummy 假数据模式移除**：ModelGateway 删除 dummy 分支，未配置模型直接抛 `ModelConfigError`（`.env` 从 main 检出拷贝，gitignored）；测试重写 3 组；真实 deepseek-chat 端到端验证第十九条提取 2 条规则逐字溯源。model_service 单元 115 passed | 模型服务；需求迭代记录 Issue 19 四轮节；AGENTS.md 陷阱更新 |
| 2026-08-19 | **Issue #19 单元医疗类别区分（按用户设计重做）**：第一轮方向错误（提取回填+审核页筛选）已回退。现行实现：知识构建页新增「医疗类别分类」面板（执行分类→类别数量卡片→明细下钻→人工修正/恢复自动，PG 持久化 policy_unit_med_types）；新建构建任务向导按医疗类别筛选单元。T1 3+592、T2a 3+41、前端 2+17+139、tsc/build 通过；失败均为预存环境依赖。待用户验证 | 政策知识管线；需求迭代记录 Issue 19 节；领域字典新增 med_type_classifier/UnitMedTypeOverride |
| 2026-08-19 | **模型治理新模型接入辅助**：通用 OpenAI-compatible `/models` 探测、写权限与脱敏审计、安全失败提示；Portal 模型名支持可搜索列表和手填兜底，端点/密钥变更后列表失效。真实 OpenCode Go 匿名探测 28 个模型且含 `deepseek-v4-flash`，Portal tsc 通过，待用户页面验收 | 模型服务与管理 4.6；`/model-governance` |
| 2026-08-25 | **Issue #21 完成并验证**：确认 `policy-qa` 为唯一业务入口，结算单作为必填问答上下文；删除结算异常、出院质控、运营看板、静态旧 Chat 原型及通用编排代码和测试，退役路径保持 404；按 Loop Engineering 为结算读取与政策检索增加全局最多 2 次的有界恢复、稳定停止原因及公开验证步骤。T1/T2a/T2b 177/40/139（另 1 optional skipped），Portal 相关 65、E2E/smoke 9、并发 SSE 25/25，TypeScript/build/compileall 通过 | §1.1 单元 1.6–1.7；§3.5；§4；核心 AGENTS/接口/原型文档 |
| 2026-08-20 | **政策字段 bjyb 数据证据增强最小闭环**：统一语义提案只读关联最新 discovery 字段画像，按业务角色推荐 `H_TYPE`/基金款项与支付分项，明确排除 `H_LEVEL`/险种 `FUND_TYPE`；Portal 增加只读数据库证据预览和历史提议切换。聚焦验证：匹配/API 3、Flow 1、Portal 11 passed，TypeScript 通过；未扩展 Milvus schema 或自动发布。 | §1 知识库管理 6.4；Issue 20 |
| 2026-08-31 | **Issue #31 草稿治理更正**：撤回未具备上线条件的正式 Skill 与 `/policy-qa/stream` 退费分支；候选包迁至 `skill_drafts/` 并通过既有导入服务登记为 `editing`，保留适配器契约和隔离核心流程。真实预结算、候选评测、人工审批完成前不参与运行时发现或路由（进度编号由 1.8 重编为 1.9，避开 Issue #30 占用） | §1.1 单元 1.9；Skill 草稿管理 |
| 2026-08-31 | **Issue #30 轨迹持久化与挂起/升级/恢复**：新增 `policy_qa_trajectories` 表（每轮可重放公开快照）与 sessions 状态列（active/suspended/escalated/closed，CREATE+ALTER 双写）；`session_lifecycle.py` 状态机 + 升级工单（复用 task_closure，waiting_human_confirmation→resolve 回填）；7 个生命周期/轨迹端点；/stream 收尾写轨迹 + 非活跃会话 409；前端刷新恢复（localStorage sessionId + 轨迹重建）与挂起/升级 UI。顺带修复预存缺陷：PG task_store.create_task 缺 input_data/status 等参数（与 service 层协议不匹配，PG 模式下 record_qa_task 曾静默失败）。T1 单元 15+307、T2a API 9+47、T2b Flow 1、Portal Vitest 聚焦 82/全量 358（3 failed 为 §5 预存债务）、TSC/ESLint/build/compileall 通过；真实 PG 冒烟（DDL 双写 + jsonb 读写 + 状态机）通过 | §1.1 单元 1.8；数据库/接口文档待同步；SSO 接入后 user_id 改认证上下文 |
| 2026-08-31 | **门诊测试数据底座接入就绪**：复用既有 SQL Server/PostgreSQL 测试凭据，自动登记并验证三表 117 字段与 PG 事务读写；页面拆分展示数据底座、门诊源表、PG、CDC 和同步草稿状态，CDC 可选；修复端点变化后凭据 revision 丢失导致启动不幂等 | 门诊数据治理中心；P1 接入就绪 |
| 2026-09-01 | **门诊同步任务人工启动 + 多 worker 竞态修复**：定时 SQL 从草稿转 running，基线 3350 行幂等落库、5 分钟心跳正常，P95 样本开始积累；发现并修复他检出目录遗留 worker 共享 PG 抢任务导致的重复认领与成功批次孤儿化（先红后绿补 2 个回归测试），杀僵尸 worker 后全量 Unit 2013 → API+Flow 460 通过 | 门诊数据治理中心；P1 同步验收进行中 |
| 2026-09-02 | **源表映射向导（探查/选表/字段映射/SQL 预览）**：新增 outpatient_source_mappings 存储（CREATE+ALTER 双写）与 CaptureMapping 域模型（标识符白名单防注入，契约锚点 T_TradeNo/T_TradeDate 不可改名）；轮询适配器映射化，SQL 构造器与预览共用（所见即所执行，预览支持草稿 POST）；5 个新端点（explore 表/列、mapping GET/PUT、sql-preview）+ Portal「表探查」「字段映射」弹窗（自动同名匹配、主键勾选、SQL 预览）；无映射行回退默认固定契约，存量 bjybdb 零迁移。Unit 2024 → API+Flow 461 → Portal 378/build/tsc 通过；真实库实测 361 表 195 列探查、默认映射预览与心跳同步正常 | 门诊数据治理中心；真实医院接入向导 |
| 2026-09-04 | **Issue #65 Phase 0 契约冻结**：治理数据流 GovernedFlow DSL 落地（8 节点白名单判别联合 / draft→published 状态机 / revision+content_hash 乐观锁 / 23 个 FLOW_* 错误码 / 口径未签核 fail closed 发布门禁）+ #62 四指标 Golden Flow 基准夹具（口径句 v4、T_CureType 值域与 med_type 隔离）+ 领域字典 §14.6（20 词）+ @xyflow/react 12 画布技术验证（MIT、jsdom 可测、键盘可达、tsc/build 通过，验证后未引入依赖，5 个实施陷阱归档）。Unit 49 passed、compileall 通过 | `docs/steering/治理Flow控制面-Phase0契约冻结-V1.0.md`；Phase 1 依赖 #62 分支合并 |
| 2026-09-04 | **Issue #65 Phase 1 后端闭环**：#62 分支合入 main（d51d908）后，落地 Flow 编译器（线性管道→CREATE OR ALTER VIEW，标识符/字面量/AST 三重防注入，Golden Flow 编译产物与 #62 视图口径语义等价）+ 存储四件套（governed_flows/governed_flow_revisions 双表，is_active 部分唯一索引，单条 UPDATE 原子回滚）+ FlowGovernanceService（发布原子锁 flow revision+semantic revision+artifact hash，签核上下文从语义层已发布指标推导）+ /flow 前缀 12 操作 API（Depends 注入可 override）；语义层补登记 o_trade 数据集（独立源对象 mzjy_src，不并入 mzjyxx 单数据源模型）。Unit 78 + API 16 + Flow 2 + PG 活库冒烟 1 全绿；相关模块全量回归 304 passed | `docs/steering/治理Flow控制面-Phase0契约冻结-V1.0.md` §8 |
| 2026-09-07 | **架构裁决：加工视图落位 PG 落地库（#62/#65 原子修正）**：裁决「加工一律在本院 PG 落地库执行，禁止在 SQL Server 源库 DDL」——#62 视图 SQL/registry.yaml 重写为 PG 方言（FROM mz_trade 治理视图、标识符双引号、状态码列 NULLIF(col,'')::NUMERIC 显式转型），T2a 活库验收从源库改指 PG（4 passed：部署/权限、view==落地表同口径直接聚合逐值一致、勾稽恒等、med_type 边界）；#65 编译器切 CREATE OR REPLACE VIEW+全标识符引号化，金标 Flow 源契约 o_trade→mz_trade，op_* 指标 source_field 路由 outpatient_postgres，回退 o_trade/mzjy_src 登记；归档两条 PG 陷阱（视图列保留大小写须双引号、CREATE OR REPLACE 不能改列类型）。口径句 v4 原文与签核不变 | Phase 0 文档 §9；Phase 3 需做列类型迁移或执行器注入转型 |
| 2026-09-07 | **Issue #65 Phase 2 可视化画布 + T13 加固**：portal 落地 `/flow` 列表页 + `/flow/[flowId]` 画布编辑器（`@xyflow/react@12` 正式引入；8 类自定义节点卡带校验徽标、组件盘节点上限禁用、属性面板按类型编辑器、校验报告点击定位节点、编译预览/发布修订回滚面板，操作栏按状态机门控；新建对话框生成结构合法最小骨架），12 端点 TS 客户端类型逐一镜像 Pydantic snake_case；T13 落 `FlowDefinition.nodes/edges` 的 `Field(max_length)`（MAX_FLOW_NODES=50/MAX_FLOW_EDGES=100，解析期 422 全入口拒止，未新增 FLOW_* 错误码）。后端 Unit 81 + API 17（新增 T13 3+1 例）+ 受影响面回归 312 passed；前端新增 16 测 + 全量 436 passed + tsc/build 通过；活体 E2E 经前端代理全链路（创建→校验→评审→发布落证据→修订/预览 PG 方言 SQL/回滚→55 节点创建 422）+ Playwright 真实浏览器复测画布渲染与节点→属性面板联动（T12 复测通过） | Phase 0 文档 §10；移动端 390px/键盘矩阵与质量门禁运行时留 Phase 3 |
| 2026-09-07 | **Issue #65 Phase 3 受控问数消费契约接线**：编译器对 mz_trade text 落地状态四列渲染 NULLIF(col,'')::NUMERIC 转型（编译期进 artifact_hash，产物与 #62 视图同构可直接部署）；发布闭环补 FlowViewDeployer 端口（publish 先部署 DDL 再落证据、部署失败无证据留 pending_review，rollback 重编译验哈希后重部署）；新增 FlowQueryService + POST /flow/{id}/query 受控问数（消费前验 artifact_hash、指标 ⊆ consumer.consumes、维度 ⊆ 绑定白名单 T11、勾稽门禁逐行评估失败扣发数值），错误码 24→26；修复 /semantic/query/processed-snapshot 弃 SQL Server 通道改 PG 直读（旧通道 live 必 503 被测试桩掩盖）；对活库执行 switch_outpatient_query_model_to_postgres 迁移（mz_trade 数据集映射原为 §9 前旧登记 dbo.o_Trade）。活体三路对数一致：flow/query == processed-snapshot == mz_trade 直聚合（12 笔/6643.69/113.66/6530.03），T11 越权与未知指标 live 422。域内 108+10+6 passed、全仓 unit+api 2855 passed（4 预存失败 stash 甄别） | Phase 0 文档 §11；permission_level×调用方角色强制留后续 |
| 2026-09-07 | **Issue #65 Phase 3 补全：指标码驱动消费接入点**：兑现验收「四字段可被 query_planner 消费」缺失的接入点——消费方只知语义指标码、不知 flow_id，新增 `FlowQueryService.query_by_metrics` + `POST /flow/consume`（全码按 SourceNode.object_code 归一为契约短码；解析边界=活跃发布版本；无契约 422 点名缺失码、多契约 409 FLOW_CONSUME_AMBIGUOUS 拒猜、空请求 422；解析后走既有 T8/白名单/勾稽门禁链路不设旁路），错误码 26→27；架构裁决：#36 锚点内核（SemanticQuery 必带 scope.anchor）不适配全局快照指标，query_planner 侧经消费契约接入点落地、不把快照指标塞进 SQL 规划器。附带修复预存缺陷：set_active_revision 单条多行翻转 UPDATE 在部分唯一索引 uq_governed_flow_active_revision 上逐行检查触发瞬态重复（pg_smoke 活库必红，stash 甄别预存），拆「先撤旧活跃、再启目标」两条语句。活体四路一致：/flow/consume == flow/query == processed-snapshot == mz_trade 直聚合（12 笔/6643.69/基金 113.66/个人 6530.03，双门禁通过），未知指标 live 422；新增 6 例先红后绿，域内 273 passed，全仓 unit+api 2855 passed（4 预存失败与既往清单一致；policy_qa_outpatient 脱敏断言失败经干净 worktree 复跑确证预存） | Phase 0 文档 §12；#36 内核对接（NL 识别→指标码→consume）随智能问数落地 |
| 2026-09-07 | **Issue #65 Phase 2 补全：390px 与键盘全路径真实浏览器矩阵**：兑现验收总则第 4 条（1440/1024/390 画布与详情页可用、关键操作可键盘完成）。最小修复：编辑页中段窄屏纵向堆叠（画布显式 h-[320px]+flex-none、属性面板全宽、节点面板横向滚动条），新建对话框补 role=dialog/autoFocus/Escape 关闭还焦/窄屏单列，键盘 Enter 选中画布节点同步打开属性面板（原仅 onNodeClick 驱动，真浏览器实测键盘断点）。Playwright 真实浏览器（活库 8178 + portal 3178）矩阵实证：1440/1024(CSS 实测)/390(CSS 实测) 三档两页均无横向溢出，390 画布 247px 可用、main 纵向滚动；键盘 Tab 序完整（列表 11 站）、节点 tabindex=0+role=group（5 节点 4 边）、Enter 选中→面板、Escape 关对话框/侧栏抽屉、编辑页 56 可聚焦元素 0 inert。两个 jsdom 测不出的 CSS 陷阱入 §13.3（h-full 不解析 min-height 派生高度；纵向 flex 的 flex-basis:0% 压掉 height）。先红后绿 +4 例，portal 全量 440 passed、tsc 0 错误 | Phase 0 文档 §13；Phase 4 性能实测（物化/调度/缓存决策）待启动 |
| 2026-09-08 | **Issue #37 验收后修复 + Issue #38 开源对标增强**：#37 —— query_plan 快照口径纠正为 SemanticQuery、approve 查询计划闸门（400 QUERY_PLAN_REQUIRED/INVALID）、错位冷启动通路拆除（删 seed 脚本/cold_start，cleanup 脚本清理真实 PG 20 条 tq_seed_* 无计划草稿，全表收敛 3 条均带合法计划）；#38 —— 第五类资产 vector_collection（Milvus 18 集合）、列级元数据 data_catalog_columns（269 列）、血缘边推导落表 data_catalog_lineage_edges（230 边，查询走索引）、owner/tag 分面 + total 真分页 + /columns 端点、owner/tags/value_ranges 真实来源回填、Portal 两页重写。Unit 38 + API 35 + Flow 144 passed（3 失败为环境依赖存量）、Portal Vitest 435/tsc/build 通过、真实 PG 冒烟通过；领域字典 §13.7/§13.8 同步 | Issue #37/#38；`trusted_qa/`、`data_catalog/`、Portal 两页 |

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

| 2026-09-02 | Issue #35 语义指标治理字段补齐：`semantic_metrics` 增加 8 个治理字段，Metric/API/Portal 复用现有指标链路；`mzjyxx` 首批只发布 `T_State`、`T_FeeAll`、`T_FundPay`、`T_SelfPayAll` 4 个指标，`average_fee` 与 `insured_encounter_count` 同批暂缓并保持 draft/unavailable，发布拒绝明确提示“就诊人次口径未定”。最终验证：semantic layer Unit 179、相关 API 32、Flow 3 通过；Portal 依赖已安装，`tsc --noEmit` 零错误，Vitest 58 files / 418 tests 通过 | Issue #35 |

> **维护约定**：每次状态变更必须在此记录。§2 与 `docs/steering/政策知识管线开发计划.md` 双向同步。
### 2026-09-07 Issue #65 Phase 4 启动：View 性能基线

- 已新增真实 PostgreSQL View 性能基准：顺序热连接 30 次、10 个独立连接并发 50 次，复用 `PostgresFlowViewReader.read()`，只测查询热路径。
- 当前活库结果：顺序 P95 2.91ms、并发 P95 4.30ms，均低于只读接口 300ms 阈值；当前 View 仅 1 行，结果仅作为小规模基线。
- 当前决策：不提前引入物化表、调度器、缓存或异步运行层；接入代表性生产规模数据且 P95 超阈值或出现明确资源瓶颈后再评估。
- 验证：`src/tests/performance/test_governed_flow_view.py` 1 passed；详细证据见 `docs/reviews/2026-09-07-issue65-phase4-performance.md`。

| 2026-09-09 | **Issue #45 健康运营 P0 落地（#65 关联 issue 依赖序第 1 位）**：`ops_findings` 问题库（fingerprint=`asset_type:asset_id:check_id` 唯一索引 + ON CONFLICT 单语句 upsert，occurrence_count/revision 原子累计；CREATE+ALTER 双写 DDL）+ 存储四件套（ports/内存/PG/工厂，USE_MEMORY_STORAGE=1 回退）+ 数据域只读检查器 2 个（data_sync_failed：failed=critical/degraded=warning/滞后=超 max(2×调度间隔,15min) 宽限 warning；data_source_down：connection_status=error critical，payload 仅 safe 字段）+ `OpsHealthService` 巡检编排（单检查器失败不中断，记 checker_errors）+ API `POST /ops/inspections`、`GET /ops/findings`（severity/asset_type/status 过滤+分页，severeity→last_seen 排序；ops:read/ops:write 签名 JWT 鉴权，start-servers.ps1 签发 NEXT_PUBLIC_OPS_TOKEN dev token）+ portal `/ops` 独立页（导航「健康运营」入口、立即巡检按钮、severity 徽标、证据摘要、发生次数、分页、「全部健康」空态）。领域字典 §14.7（10 词条）+ 附录 A 8 行。验证：Unit 18 + API 10 + Flow 活库冒烟 2（DDL 幂等/去重/过滤实测）全绿；portal 新增 6 测 + 全量 446 passed + tsc 0 错误；全仓 unit+api 2886 passed（4 失败 stash 甄别为预存：scripts 启动脚本断言、policy_rules_search、infra_skill×2，与本次改动无关） | #50 详情页/生命周期与 P1 诊断的存储前置已就绪 |

| 2026-09-09 | **Issue #50 finding 详情页与生命周期操作落地**：`ops_finding_events` 事件表（CREATE+ALTER 双写 DDL，追加只增不改）+ 存储 `get_finding`/`transition_finding`（条件 UPDATE `WHERE revision=expected` 承载乐观锁，0 行回读区分 NotFound/RevisionConflict，状态更新与事件留痕同调用）/`list_finding_events`（created_at 升序），内存实现同步对齐 + 领域模型 `OpsFindingEvent`/`OpsFindingEventType`(ignored/reopened)/`OpsFindingDetail` 与 3 异常（NotFound/InvalidFindingTransition/RevisionConflict）+ 服务状态机（ignore：open→ignored reason 必填；reopen：ignored|resolved→open；先验状态后验版本）+ API `GET /ops/findings/{id}`、`POST .../ignore?expected_revision=N`（body reason 必填 1..500）、`POST .../reopen`（actor 取 JWT sub；404 FINDING_NOT_FOUND / 409 FINDING_TRANSITION_INVALID / 409 FINDING_REVISION_CONFLICT）+ portal 详情抽屉（`finding-detail-drawer.tsx`：证据快照键值表带中文标签与问题码翻译、诊断 P1 占位、忽略原因表单（空值禁提交）、重开按钮、流转时间线含原因引用，操作以响应回填并通知列表刷新；列表页加状态列徽标+状态筛选（默认全部），行点开抽屉；标签/格式化抽到 `app/ops/shared.ts`）。复现巡检不复活 ignored 状态（upsert 语义回归）。领域字典 §14.7 扩 3 词条改 1 词条 + 业务规则 5→8 条 + 附录 A 3 行。验证：Unit 29（存储 13+服务 4+既有）+ API 20（新增 10：404/422/409×2/403/复现不复活等）+ Flow 活库冒烟 4（新增 2：真实 PG 事件留痕与乐观锁冲突无半写；既有过滤断言收窄 SMOKE_ASSET 作用域修复活库数据污染）全绿；portal ops 页 8 + 抽屉 7 新测、全量 455 passed + tsc 0 错误；全仓 unit+api 2907 passed（4 失败与 #45 甄别的预存集完全一致） | #53 自动修复闭环的 resolved 状态与 reopen 通道已就绪 |

| 2026-09-09 | **Issue #53 L1 白名单自动修复 + 修复后验证闭环落地**：`ops_remediation_runs` 修复留痕表（CREATE+ALTER 双写 DDL + (finding_id, created_at) 索引，追加只增不改）+ 存储 `insert_remediation_run`/`list_remediation_runs`（created_at 升序）四件套同步 + 领域模型 `OpsRemediationRun`/`RemediationRiskLevel`(L1/L2)/`RemediationRunStatus`(succeeded=动作已执行/failed=未发起)/`VerificationResult`(passed/failed) + `src/runtime/ops/remediation.py` 修复白名单（`RemediationSpec` 代码内注册，本期仅 `data_sync_failed → retry_data_sync` L1；重试执行器复用 data_governance 同步入口：failed/degraded→start_job、滞后 ready/running→request_run_once、paused/draft/不存在→诚实拒绝不执行，内联 `OutpatientSyncWorker.run_one()` 与后台 worker 同执行路径（FOR UPDATE SKIP LOCKED 原子认领），被抢认领时有界 settle 等待）+ 服务 `remediate_finding`（仅 open；执行→**强制重跑触发检查器**按 fingerprint 匹配：通过→resolved+事件「L1 修复动作 xxx 验证通过」，仍报→复现 upsert occurrence+1 保持 open，检查器异常→不判定验证 `after_evidence.verification_error` 记原因；动作未发起→failed 运行行不触发验证状态不动；乐观锁只约束 resolved 流转，冲突仍留运行行）+ 巡检自动重开 resolved 复现（系统 actor `system:ops-inspector`；ignored 不复活）+ API `GET /ops/remediation-actions`、`POST /ops/findings/{id}/remediate?expected_revision=N`（409 REMEDIATION_NOT_WHITELISTED / FINDING_TRANSITION_INVALID / FINDING_REVISION_CONFLICT）+ portal 详情抽屉「执行修复」按钮（仅 open+白名单 check_id 显示，成功回填已解决徽标，时间线合并修复记录「已执行 · 验证通过」/「未发起 · 未验证 · 原因：xxx」）。领域字典 §14.7 扩 6 词条改 3 词条 + 业务规则 8→12 条 + 附录 A 6 行（补漏 GovernanceStatusReader）。验证：Unit 48（修复闭环 8+巡检重开 2+重试执行器 6+存储 3+既有）+ API 29（新增 9：白名单外 409/非 open 409/权限 403/未发起留痕等）+ Flow 活库冒烟 5（新增 1：真实 PG 修复闭环 run 行往返/状态/事件/详情聚合）全绿；portal 抽屉新增 4 测、全量 459 passed + tsc 0 错误；全仓 unit+api 2935 passed（4 失败与 #45/#50 甄别的预存集完全一致） | #38 数据目录的存储与 API 模式已就绪 |

| 2026-09-09 | **Issue #38 数据目录（三级资产统一目录/搜索/血缘/SLA）落地**：**只读聚合、零新表**——`src/runtime/catalog/service.py` `CatalogService` 双端口编排（SemanticRegistry 门面 + `CatalogSyncReader` Protocol 新建：list_sources/get_job/get_sync_status/list_recent_batches/list_attempts，`PgCatalogSyncReader` 包 OutpatientGovernanceStore+OutpatientPostgresStore 活库实现；消费方从 `skills/*/skill_manifest.yaml` needed_objects 解析为 skill 级 consumer；字段描述/主键来自 DiscoveryStore `table:column` 键）+ 五类资产（dataset/field/object/metric/consumer）统一搜索（大小写折叠子串命中名称/编码/描述/指标同义词，matched_on 可追溯）+ 资产详情（五类分派：数据集→字段清单含角色徽标/主键/发现层描述、指标→政策承载 KVs 含生效期「YYYY-MM-DD 起现行｜start ~ end」与 subkind 标签、消费方→消费对象/指标、对象/字段级联）+ **血缘链**（数据源→同步批次→投影表/字段→指标→消费方+语义版本；指标↔数据集双向挂接：object_code 或 source_field 三段式 datasource.table.column；批次仅挂 `datasource_id==outpatient_postgres` 落地库数据集）+ **SLA 看板**（每源：连接/任务状态、P95 与最近非空延迟（get_sync_status 真实样本）、质量门、语义版本、近 10 次尝试成功/失败统计与 last_error_code、最近批次真实行非捏造）+ API `GET /catalog/search|overview|sla|assets/{type}/{id}|lineage/{type}/{id}`（Literal 参数自动 422；404 CATALOG_ASSET_NOT_FOUND；open-GET 沿语义层只读先例无鉴权、无任何写端点）+ portal `/catalog` 页（导航「数据目录」Library 图标；资产目录页签：300ms 防抖搜索+类型过滤+结果列表类型徽标/命中字段，行点开右侧抽屉「详情/血缘」双页签——详情摘要 KVs+值域码表+字段/指标/数据集/消费方/批次/语义版本分节，血缘链六段式展示；SLA 页签：源卡片 P95 formatSeconds/质量门徽标/运行统计+最近批次表；标签/格式化抽到 `app/catalog/shared.ts`）。存储侧新增 `OutpatientPostgresStore.list_recent_batches`（frozen `RecentOutpatientBatch`，source_id 可选过滤+LIMIT）+ `RecentOutpatientBatch` 入库。领域字典 §14.8 新建（8 词条+4 业务规则）+ 附录 A 4 行。验证：Unit 28（搜索 7/详情 7 含政策承载生效期两形态与 5×未知资产/血缘 6/SLA 3/概览 1）+ API 11（422×2/404×5/血缘链断言）+ Flow 活库冒烟 4（真实注册中心「结算」命中 mzjyxx 对象；SLA 批次与直查 `outpatient_sync_batches` 逐字段一致；指标血缘触达批次+版本；只读性：调用前后表行数不变）全绿；portal 新增 7 测（概览/防抖搜索/过滤/空态/错误/抽屉+血缘切换/SLA 看板）、全量 466 passed + tsc 0 错误 | #60 政策承载 gap-fill（effective_end 已废止门禁/查询层生效期裁剪）可开工 |

| 2026-09-09 | **Issue #60 政策承载切片④补齐（溯源 + 幽灵档 + 查询层生效期裁剪）**：背景——#60 切片①-③ 已随 PR#61 合 main（subkind/policy_carrier 字段、A/B 两态门禁、快照携带，验收#1/#3/#5 覆盖），切片④ 原阻塞于「知识 get_rule 只读句柄」，本期 zcgz 行读取条件已具备（policy_extractions + PipelineStore.get_extraction 先例）。落地：`PolicyRuleReader` Port（registry.py 内 Protocol，get_rule(rule_ref)→行或 None）+ `PgPolicyRuleReader`（同库窄列 SELECT extraction_id/status，惰性连接，不反向 import knowledge_extension 保持依赖方向）+ `SemanticRegistry.__init__` 增可选 policy_rule_reader 注入（生产 get_semantic_registry() PG 分支注入；内存/存量构造路径 None=不校验，验收#3 回归）+ 发布门禁切片④（policy_rule_ref 非空不分 A/B：引用不存在 → ValueError「政策承载溯源不合法」指明指标与引用值（验收#4）；行 status=archived 已废止而承载缺 effective_end → 幽灵档拒绝，补齐废止日或引用现行行合法（验收#2）；沿既有 ValueError→HTTP 映射）+ 查询层生效期裁剪 `_assert_metric_in_force`（query_planner `_resolve_metrics`：effective_start>今日未生效/effective_end<今日已废止 → SemanticQueryPlanningError 拒查；日期格式非法跳过不因脏数据阻断；plan/compile 双路径覆盖）。领域字典 §14.9 新建（7 词条+5 业务规则，补 PR#61 未登记的 policy_carrier/subkind 概念）+ 附录 A 2 行（PolicyRuleReader/PgPolicyRuleReader）。验证：test_metric_governance 新增 4（引用不存在/幽灵档两态/现行行放行+B 类填 ref 也校验+无句柄存量兼容）、test_query_planner 新增 1（已废止/未生效拒查+现行与无承载放行，日期相对真实今日构造）；语义层全量 Unit 193 + API 57 全绿；全仓 unit+api 2979 passed（4 失败与 #45 甄别预存集完全一致） | #27 数据接入规范文档 + SQL Server 直连收敛 adapter 可开工 |

| 2026-09-10 | **Issue #27 数据供给接入规范落地（语义层需求侧标准 + 供给侧分档）**：`docs/steering/数据接入规范.md` 一页纸——三档供给模型（一档 CDR 只读视图直连=SQL Server PEP 249、二档厂商 API/中间件同步=门诊 PG 同步已产品化的形态、三档医保局代理暂缓）+ 语义层视角的字段级需求清单（住院：yb_brdjxx/yb_dyxxzy/yb_zyfdxx/yb_zyjyxx 四视图逐字段角色与年度累计 zqxh 口径；门诊：mz_trade/mz_fee_item）+ 5 个值域码表（insu_type/med_type/hosp_lv/psn_type/setl_type）+ 供给侧四承诺（只读/可审计/单条低频/码值稳定）与平台侧承诺。代码侧收敛既有 SQL Server 直连为正式适配器：`DataSupplyConnectionPort`（ports/data_supply.py，runtime_checkable Protocol，`connect(datasource_id)` 只读契约）+ `SqlServerDirectSupplyAdapter`（一档实现，构造注入 `connect_fn`，不反向 import runtime，组合根在 `SemanticSettlementDataProvider`）+ `SemanticDataSource.open_connection` 公开只读入口（新公开方法承载 provider 历史回退链：注册数据源→发现层最近扫描→env 配置，区别于严格的 `connect_datasource`）+ `SemanticSettlementDataProvider` 改造（默认组合根组装 supply 端口，去除对 semantic_source 私有方法的触达）。验证：`test_data_supply_adapter` 新增 2（端口协议合规+委托、provider 默认组装经注入 fake source 惰性 connect）；adapters + policy_qa 单测 166 passed、discovery 33 passed 全绿 | #37 可信问题库可开工 |

| 2026-09-10 | **Issue #37 可信问题库（确定性匹配 + 澄清降级 + 审核流 + 越问越准）落地**：设计 §14.1——每条可信问题沉淀 标准问题/同义表达/适用角色/指标/维度/时间口径/筛选/查询计划/允许下钻/预期结果特征，生产问数优先匹配可信问题执行，不确定降级澄清**绝不猜测执行**。落地四层：**领域** `src/domain/question_library/models.py`（`TrustedQuestionDraft`/`TrustedQuestion` frozen，`normalize_question_text` NFKC+小写+剥标点空白；draft 校验 metadata 镜像 query_plan（object_code/metrics/group_by 三一致，model_validator）、scope 非空、同义去空白；`applies_to_roles` 空角色=全员）；**匹配引擎** `src/runtime/question_library/matcher.py`（命中=归一化文本与标准问题或任一同义**完全相等**——「文本一致+计划人工审核」是 100% 正确的机制保证；其余一律 clarify：字符 bigram Jaccard 候选排序，MIN_CANDIDATE_SCORE=0.35 截断 MAX_CANDIDATES=5，只澄清不执行）；**服务** `QuestionLibraryService`（match/resolve/execute/create_draft/review/archive/add_synonym/cold_start；草稿创建经 SemanticQueryPlanner dry-run 校验绑定计划可编译；审核 draft→published 版本+1 记审核人 / draft→archived；同义采纳查全库归一化冲突（冲突报持有 question_id）；execute 按角色门禁后**逐字执行**存储的 query_plan 走 SemanticQueryService 与结算问数同通道；冷启动从 tasks 表 policy_qa 历史 `question_excerpt` 频次聚合排除已覆盖文本）；**越问越准** `question_match_events` append 表记录每次 hit/clarify/selected，澄清事件在 portal 一键采纳为已发布问题同义。存储四件套（ports/in_memory/postgres/factory，CREATE+ALTER 双写；update_question 显式列+`revision=expected+1` WHERE revision=expected RETURNING 乐观锁）。API `question_library_routes.py`（`/question-library`：match 与 `{id}/execute 开放沿目录只读先例；questions/审查/归档/同义/事件/统计/冷启动走 question_library:read/write JWT 权限，同 ops 先例；409 REVISION_CONFLICT/TRANSITION_INVALID/SYNONYM_CONFLICT、422 DRAFT_INVALID 等）。portal `/question-library`（BookMarked 导航「可信问题库」；概览 chips+问题库页签：防抖搜索/状态过滤/行展开详情+审核发布/驳回/归档+行内加同义+新建草稿对话框（默认计划 JSON）；试问页签：命中面板展示计划+执行看结果、澄清面板候选「选择并执行」；越问越准页签：澄清事件采纳；冷启动页签：候选表+创建草稿）+ `question-library-api.ts`（NEXT_PUBLIC_QUESTION_LIBRARY_TOKEN 由 start-servers.ps1 签发注入）。领域字典 §14.11 新建 + 附录 A。活库迁移：发现废弃并行分支遗留旧 schema `trusted_questions` 表（applicable_roles/metric_codes 等异构列），非破坏改名 `trusted_questions_abandoned_20260907` 后新 DDL 生效。验证：Unit 43（模型 12：归一化全角/标点/空+draft 校验；匹配 9：同义命中/角色过滤/澄清排序截断/大小写标点容错；服务 22：生命周期/乐观锁/同义冲突/execute 逐字执行/cold_start 频次排序排除已覆盖）+ API 22（鉴权 401/403、match 三态、生命周期流转、execute draft 409、冲突 409、事件/统计/冷启动）+ Flow 活库冒烟 3（PG 往返/乐观锁 revision 1→2 旧 revision 拒绝/事件追加过滤）全绿；portal 10 测新增、全量 476 passed + tsc 0 错误 | #39 P2 门诊结算核验 Skill 主体已落地待对照验收查漏 |

| 2026-09-10 | **Issue #39 P2 门诊结算核验 Skill 对照验收查漏收口（含吸并 #24 表格条款解析升级）**：九 Profile / Decimal 勾稽 / 字段四态 / 政策证据 / 回归矩阵主体已在（`skills/mzsettlement_verify_skill/`：config.yaml routing_priority 九 Profile + money_states 四态 + verifier Decimal 勾稽 + policy_queries.yaml 政策证据 + self_test_cases.yaml 31 例回归矩阵；36 Skill 测 + 11 桥接测全绿），本期查漏补齐三件：**① 政策表格条款解析升级（吸并 #24，原管线缺口实证：爬虫 `extract_content` 用 `soup.get_text("\n")` 把 HTML `<table>` 拍平成逐单元格孤立行，行列结构全丢，活库 400 篇已发布文档无一保留表格结构）**——`crawl/html_text.py` `extract_text_with_tables`（`<table>` 原位替换为「单元格 | 单元格」行文本，其余保持 get_text 语义；四个爬虫 extract_content 全部切换）+ `policy_struct/table_parser.py`（块识别=连续 ≥2 行含 ≥2 个 `|` 单元格；表头启发=整行数字占比 <0.2；参差行补空对齐；**RagFlow 风格行组切片**=每片重复表头上下文携带 header/rows/row_range/line_range；**单元格级定位单元** `{node_id}#r{n}c{m}` 带 column_header/row_header）+ `leaf_match` `collect_cell_units`/`match_cell_units` 三层匹配（combo=行表头与值成分同现→优先于条款归属；value/lcs 裸值层仅条款无匹配时兜底——正文条款也提表格数值，裸值不能抢占条款；run_extraction 的 unit_id 据此携带单元格定位，`_by_id` 查找按 `#` 截断回条款节点，extraction_id/下游按不透明串消费不受影响）；**② 基线文档最小修订**（`2026-08-26-mzsettlement-verify-skill.md` 增 2026-09-10 修订段：P0/P1 冻结事实对齐——mz_trade/mz_fee_item PG 落地视图+§9 切换、query_planner #36 与指标治理 #35 已合入、Task 1-4 落地形态、表格升级落位知识管线而非 Skill 内）；**③ 不自动激活/不可变回滚核验**（既有护栏：`test_candidate_artifact_is_written_outside_runtime_skills`+`test_candidate_root_inside_runtime_skills_is_rejected` 候选制品强制在 runtime skills 目录之外；`test_settlement_query_model_is_seeded_and_frozen_on_publish` 发布即冻结快照）。验证：`test_html_text` 4（表格渲染保序/无表格语义不变/空行跳过/多表全渲）+ `test_table_parser` 15（块识别/孤行不成表/表头与数据行切分/参差补空/无表头全数据/定位单元带表头/空格跳过/行组切片重复表头/行号区间/combo 命中 r0c1 与 r1c2/无关正文不命中/裸值兜底/run_extraction 表格事实落 #r0c1 定位+正文事实保持条款级无抢占）全绿；knowledge_extension 全量 736 passed（1 预存 skip）+ reextract/knowledge_build flow 6 passed；Skill 36 + 桥接 11 复跑全绿 | #40 P3 受控问数与运营指导可开工 |
| 2026-09-10 | **Issue #40 P3 受控问数与运营指导（仪表盘/下钻/周报）落地**：冻结契约六指标（门诊医保就诊人次、有效结算笔数、总费用、统筹基金支付、个人支付、次均费用）×五维度（就诊时间、科室、门诊业务类别、险种、结算状态），result_status ∈ complete/partial/unavailable 且恰好一个 halt_reason。选型裁决：SemanticQueryPlanner 是实体锚定（QueryScope 必须携带唯一 identifier 锚点，`anchor_count != 1` 即拒绝）、MetricDataQueryService 是单实体 MVP，都不适合仪表盘无锚点聚合 → 新建 **`OpsAnalyticsService`**（`src/runtime/ops_analytics/service.py`）走有界确定性聚合：常量 SQL 模板 + 参数化过滤，**口径句 v4 谓词逐字取自 `docs/processing/outpatient_processed_view.sql`**（与签核加工视图同口径，不重新发明；活库冒烟与 `v_op_outpatient_processed` 四指标值对账一致）。冻结诚实语义：**就诊人次/次均费用/科室维度保持 unavailable（halt_reason=data_unavailable，HIS 就诊关联是 P1 必需输入、禁止跨源临时 JOIN，绝不估算）**；四可用指标（有效结算笔数 COUNT DISTINCT T_TradeNo/总费用/统筹/个人）+ 月度趋势（T_TradeDate）+ 险种/业务类别/结算状态拆分（码→中文标签唯一真源 `seed.py _YB_DICTIONARY_MAPPINGS`）+ **行级下钻**（T_TradeNo 粒度就诊明细，维度/日期过滤分页，行携带 data_batch_id 指标批次溯源）+ **周报**（本周/上周四指标环比 delta/pct/方向，除零 pct=None 不猜；每条结论 citations = metric_definition（口径）+ metric_batch（指标批次，两周并集）；AI 运营摘要走 ModelGateway 统一入口 scene=`ops_weekly_summary`、prompt 仅含已计算结论并明令禁止引入未给出数字，模型未配置/失败诚实降级 summary=None + uncertainties，不返回假数据）。读取面注入 `PostgreSQLClient.execute`（Protocol seam，测试注入假实现）。领域模型 `src/domain/ops_analytics/models.py`（OpsMetricCard/OpsOverview/OpsDimensionBreakdown/OpsTrendPoint/OpsDrillRow/OpsWeekDelta/OpsConclusion/OpsWeeklyReport + dec_to_float）字典 §14.12 新建。API `ops_analytics_routes.py`（`/ops-analytics`：overview/trend/breakdown/drill/weekly-report，ops:read 签名 JWT 与 /ops 同 token（start-servers 既有 NEXT_PUBLIC_OPS_TOKEN 已含 ops:read，无需新增环境变量）；department 维度返回 unavailable 单例而非 422，未知维度 422）。portal `/ops-analytics`（BarChart3 导航「运营分析」；六指标卡——四卡显值、人次/次均卡显 halt_reason+原因文案；月度趋势条形；维度拆分四页签（科室页签显 unavailable 提示含原因）；就诊明细下钻表带批次列+分页；周报区：AI 摘要卡（有才显）/不确定性列表/环比表（up 红 down 绿）/结论卡带批次+口径引用 chips）+ `ops-analytics-api.ts`（DTO 与后端逐字段对齐，token 复用 ops-token sessionStorage/NEXT_PUBLIC_OPS_TOKEN）。验证：Unit 11（总览六卡状态+口径句 v4 谓词逐字断言/拆分中文标签与占比/科室 unavailable/趋势升序/下钻行批次溯源/空结果 partial 不猜/周报 delta·pct·除零 None·结论批次引用/网关摘要 prompt 只含已计算结论+scene/模型异常降级）+ API 12（401/403/坏 token、六卡冻结状态、拆分与科室 unavailable、未知维度 422、下钻批次、周报引用+降级、非法 week_start 422）+ Flow 活库冒烟 3（真实 SQL 可执行性+四指标与 v_op_outpatient_processed 对账一致/拆分下钻趋势在活库成立/周报选 v4 范围内周）全绿；portal vitest 4（六指标卡/科室 unavailable 切换/下钻批次/周报引用与摘要降级）+ tsc 0 错误。**边界说明**：周报为按需生成（on-demand），订阅推送机制留待后续迭代；人次/次均/科室在 HIS 关联接入前持续 unavailable | issue-65 全部关联 issue 开发闭环，待用户最终页面验证 |


