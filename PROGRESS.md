# PROGRESS.md — 开发进度追踪

> **定位**：本文件是项目进度的唯一权威来源。两条进度线并行追踪：
> 1. **功能领域单元**（业务能力视图，§1）——按"最小可验证单元"切片，回答"功能做没做、验没验"。
> 2. **政策知识管线重构**（开发主线，§2）——P0-P10 重构阶段，回答"知识模型重构推进到哪、什么时候能切换生产"。
> 状态实时更新；每个单元/阶段状态变更必须在此记录。禁止仅口头/IM 同步进度。

---

## 0. 当前焦点

**当前领域**：政策知识管线重构（§2）

**当前阶段**：P8.4（迁移后重提取拉高填充率）/ P10（灰度切换）

| 阻塞项 | 原因 | 解锁条件 |
|---|---|---|
| P8.4 重提取 | 依赖 LLM 调用 | 配置 `MODEL_API_KEY` |
| P10 灰度切换 | 需 P8 完成（P8.4 待做）| 完成 P8.4 或决定跳过重提取直接切 |
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
| 技能管理 | 3 | 0 | 3 | 0 | 0 | — |
| 运营看板 | 2 | 0 | 2 | 0 | 0 | — |
| 嵌入式组件 | 1 | 0 | 1 | 0 | 0 | — |
| 安全与审计 | 2 | 0 | 0 | 0 | 2 | 待外部系统 |
| 适配器接入 | 2 | 0 | 0 | 2 | 0 | 需真实系统 |
| **合计** | **32** | **0** | **28** | **2** | **2** | — |

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
| 现有数据进新模型 | P8 | M5 | 🟡 进行中（8.1+8.2+8.3 完成；8.4 重提取待做） |
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
| P8.4 | 迁移后重提取拉高填充率（现状 3/15） | ⚪ 待做（需 MODEL_API_KEY） |
| P9 | 前端 5 tab 重构（概览/政策/事实/结构化/发现） | ✅ commit `610272c`→`c87a99d` |
| P10.1 | 政策问答读入口切到新 collection（P0 配置开关） | ⚪ 未开始 |
| P10.2 | 下线旧 policy_rules / 旧 policy_facts / 旧 extractions API | ⚪ 未开始 |

### 2.3 里程碑达成情况

| 里程碑 | 含义 | 收口 Phase | 状态 |
|--------|------|:--:|:--:|
| M1 地基就绪 | 语义层契约 + 新 schema 可用，零生产影响 | P0,P1,P2 | ✅ |
| M2 数据通路打通 | 一篇政策端到端入库新模型 | P3 | ✅ |
| M3 发布闭环 | 质量门禁 + schema 演化可用 | P4,P5 | 🟡 部分（P4 简化版 + P5 部分，LLM 提取推迟） |
| M4 检索能力完整 | 三模式 + 跨世界查找可用 | P6,P7 | ✅ |
| M5 知识资产迁移完成 | 现状数据全部进入新模型 | P8 | 🟡 部分（8.1-8.3 完成，8.4 待做） |
| M6 前端重构完成 | 5 tab 上线 | P9 | ✅ |
| M7 生产切换 | 政策问答跑在新模型，旧路径下线 | P10 | ⚪ |

---

## 3. 测试套件状态

> 后端：单元（`src/tests/unit/`）→ API（`src/tests/integration/api/`）→ Flow（`src/tests/integration/flow/`）。
> 详见 `src/tests/AGENTS.md` 与 `docs/governance/TEST-VERIFICATION-MATRIX.md`。

| 套件 | 状态 | 备注 |
|------|------|------|
| semantic_layer 单元 | ✅ 全绿 | P8.3 收口测试 + 契约/发布/版本（139 passed） |
| rule_explanation 单元 + rules_search 流式 | ✅ 全绿 | 142 passed（含 Milvus 连真集） |
| 提取契约 API（extraction-schema） | ✅ 全绿 | P8.3 更新断言后 3 passed |
| 前端 policy-knowledge 5 tab | ✅ dev 编译 200 + 内容渲染 | tsc 5 页面零错误；`next dev` 烟测通过 |
| 全量回归 | ⚠️ ~56 failed（预存债务） | 见 §4 测试债务 |

### 3.1 已知预存技术债（非当前任务引入，治理时优先级参考）
- `src/components/settlement-explanation-page.tsx`：TS 类型错误（OutputItemValue.value 应为 number，传了 string|number）。**预先存在**，P9 之外。
- `src/tests/e2e/settlement-explanation.spec.ts`：缺 `@playwright/test` 类型（dev 依赖）。**预先存在**。
- `extractions/page.tsx` JSX 多根错误：**已消除**（P9.7 删除该路由）。

---

## 4. 测试套件债务（已知失败）

> 全量回归当前 ~56 failed。分类如下，按需治理：

| 类别 | 数量 | 根因 | 治理方式 |
|---|---|---|---|
| 端点迁移 404 | ~46 | chat 端点迁移到 `/policy-qa/stream`(SSE)，flow/langgraph 测试 POST 旧 `/chat` 返回 404 | 迁移测试到新 SSE 契约（大工程） |
| skill_infra | 33 | skill manifest name 改名，测试断言旧值 | 更新断言 |
| error_code stub | 4 | knowledge 模块已删除，stub 返回 `{}`，测试断言旧数据 | skip（测试已失效） |
| data_platform | 2 | `CachedSkillStorage.get_skill` 返回 dict，测试期望 Skill 对象 | 加 model reconstruction 或更新测试 |
| test_service | 1 | Milvus E001 政策数据缺失 | skip（环境依赖） |

---

## 5. 变更日志

| 日期 | 变更 | 影响 |
|------|------|------|
| 2026-07-07 | 初始化进度追踪文件 | 全部 32 单元 |
| 2026-07-24 | A 测试治理：修复 demo_tools broken import（~158→~56 failed） | runtime/langgraph + integration/flow |
| 2026-07-24 | 政策管线 P0→P8 爆发（72 提交，M1-M4 达成） | §2（当时未入本表） |
| 2026-07-27 | P8.3 种子政策值域 + zcgz 发布解锁契约 | §2 P8.3 ✅ |
| 2026-07-27 | P9 前端 5 tab 重构全部完成（9.1-9.7，7 提交，M6 达成） | §2 P9 ✅ |
| 2026-07-27 | 重写 PROGRESS.md：补入 §2 政策管线主线，修正当前焦点 | 本文件整体 |

---

## 6. 状态定义

| 状态 | 含义 |
|------|------|
| `pending` | 未启动，可开工 |
| `blocked` | 阻塞（外部依赖未就绪），禁止开工 |
| `in_progress` | 进行中 |
| `impl_done` | 代码已写完，待验证（进入单元→API→Flow 验证流程） |
| `verified` | 全链路验证通过，可归档 |
| `archived` | 已归档 |

> **维护约定**：每次状态变更必须在此记录。§2 与 `docs/steering/政策知识管线开发计划.md` 双向同步。
