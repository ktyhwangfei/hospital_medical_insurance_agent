# PROGRESS.md — 开发进度追踪

> **定位**：本文件是项目进度的唯一权威来源。每个最小单元占一行，状态实时更新。

---

## 整体状态总览

| 领域 | 单元总数 | ✅ verified | 🟢 impl_done | 🔴 blocked | ⚪ pending | 完成度 |
|------|:--:|:--:|:--:|:--:|:--:|:--:|
| 政策问答 | 5 | 0 | 5 | 0 | 0 | 0% |
| 结算异常导办 | 4 | 0 | 4 | 0 | 0 | 0% |
| 出院前质控 | 3 | 0 | 3 | 0 | 0 | 0% |
| 模型服务与管理 | 4 | 0 | 4 | 0 | 0 | 0% |
| MCP 工具管理 | 3 | 0 | 3 | 0 | 0 | 0% |
| 知识库管理 | 3 | 0 | 3 | 0 | 0 | 0% |
| 技能管理 | 3 | 0 | 3 | 0 | 0 | 0% |
| 运营看板 | 2 | 0 | 2 | 0 | 0 | 0% |
| 嵌入式组件 | 1 | 0 | 1 | 0 | 0 | 0% |
| 安全与审计 | 2 | 0 | 0 | 0 | 2 | 0% |
| 适配器接入 | 2 | 0 | 0 | 2 | 0 | 0% |
| **合计** | **32** | **0** | **28** | **2** | **2** | **0%** |

> 注：现有代码单元均处于 `impl_done` 状态（代码已写完但未走正式验证流程）。需要通过 §6 对账流程逐一验证后才能跃迁到 `verified`。

---

## 当前焦点

**当前领域**：政策问答（Policy QA）
**当前单元**：#1.1 用户通过 Chat 提交政策问题

| 阻塞项 | 原因 | 解锁条件 |
|---|---|---|

---

## 状态定义

| 状态 | 含义 | Agent 可执行动作 |
|------|------|-----------------|
| `pending` | 未启动 | ✅ 可开工（先改为 in_progress） |
| `blocked` | 阻塞（外部依赖未就绪） | ❌ 禁止开工 |
| `in_progress` | 进行中 | — |
| `impl_done` | 代码已写完，待验证 | 进入步骤 6（验证/对账） |
| `verified` | 全链路验证通过 | 可归档 |
| `archived` | 已归档 | — |

---

## 各领域详情

### 1. 政策问答（Policy QA）

| # | 单元名 | 涉及层 | 前端文件 | 后端文件 | 存储 | 状态 | 阻断 | 备注 |
|---|--------|:--:|------|------|------|:--:|:---:|---|
| 1.1 | 用户通过 Chat 提交政策问题 | F+B+S | `policy-qa/page.tsx` | `policy_qa_routes.py` → `orchestrator.py` | Milvus + SQLServer | impl_done | — | SSE 流式回答问题 |
| 1.2 | AI 检索政策知识库片段 | B+S | — | `policy_rules_search.py` → `structured_policy_retriever.py` | Milvus 向量库 | impl_done | — | 关键词+向量混合检索 |
| 1.3 | 费用项目自动检测（从用户问题中提取费用名称） | B | — | `fee_item_detector.py` | — | impl_done | — | 字典规范化 |
| 1.4 | 医保政策规则语义匹配 | B | — | `semantic_mapping.py` | SQLServer 政策规则库 | impl_done | — | 结构化检索 |
| 1.5 | 历史问答记录查询 | F+B+S | `qa-history/page.tsx` | `history_service.py` | PostgreSQL | impl_done | — | 会话级历史展示 |

### 2. 结算异常导办（Settlement Exception Guide）

| # | 单元名 | 涉及层 | 前端文件 | 后端文件 | 存储 | 状态 | 阻断 | 备注 |
|---|--------|:--:|------|------|------|:--:|:---:|---|
| 2.1 | 用户输入错误码 → AI 分析异常原因 | F+B+S | `settlement-chat.tsx` | `settlement_exception_guide/service.py` → `settlement_nodes.py` | PostgreSQL | impl_done | — | LangGraph 编排 |
| 2.2 | AI 查询医保交易详情 | B+S | — | adapters → `insurance_transactions` 表 | PostgreSQL | impl_done | — | 内存适配器 |
| 2.3 | AI 给出异常处理步骤（导办卡） | F+B | `settlement-chat.tsx` | `settlement_nodes.py` → `GuidanceCard` | — | impl_done | — | 步骤化展示 |
| 2.4 | 高风险动作人工确认 | F+B+S | `settlement-chat.tsx` | `security/risk_control/` → `langgraph/checkpoint.py` | PostgreSQL + Redis | impl_done | — | interrupt() 暂停 |

### 3. 出院前联合质控（Pre-Discharge QC）

| # | 单元名 | 涉及层 | 前端文件 | 后端文件 | 存储 | 状态 | 阻断 | 备注 |
|---|--------|:--:|------|------|------|:--:|:---:|---|
| 3.1 | 用户触发质控 → AI 返回风险扫描结果 | F+B+S | `qc/page.tsx` | `pre_discharge_joint_qc/service.py` → `qc_nodes.py` | PostgreSQL | impl_done | — | LangGraph 编排 |
| 3.2 | AI 调用事前审核适配器获取审核结果 | B+S | — | adapters → `audit_risk` 表 | PostgreSQL | impl_done | — | 内存适配器 |
| 3.3 | AI 分析 DRG/DIP 分组结果 | B+S | — | adapters → `drg_dip` 表 | PostgreSQL | impl_done | — | 内存适配器 |

### 4. 模型服务与管理（Model Service & Management）

| # | 单元名 | 涉及层 | 前端文件 | 后端文件 | 存储 | 状态 | 阻断 | 备注 |
|---|--------|:--:|------|------|------|:--:|:---:|---|
| 4.1 | 模型配置 CRUD | F+B+S | admin model 管理页 | `model_routes.py` | PostgreSQL | impl_done | — | Provider 管理 |
| 4.2 | 模型在线测试（流式 SSE） | F+B | admin model 测试页 | `model_routes.py` → SSE streaming | — | impl_done | — | 流式对比测试 |
| 4.3 | 模型路由（type+scene 策略） | B | — | `model_service/gateway/` → `router/` | — | impl_done | — | 多 Provider 路由 |
| 4.4 | 模型异常分类处理 | B | — | `model_service/exceptions/` | — | impl_done | — | 错误码体系 |

### 5. MCP 工具管理（MCP Tool Management）

| # | 单元名 | 涉及层 | 前端文件 | 后端文件 | 存储 | 状态 | 阻断 | 备注 |
|---|--------|:--:|------|------|------|:--:|:---:|---|
| 5.1 | MCP 服务器注册与管理 | F+B+S | admin MCP 管理页 | `mcp_routes.py` → `mcp_registry/` | PostgreSQL | impl_done | — | CRUD |
| 5.2 | MCP 工具发现与能力展示 | F+B+S | admin MCP 管理页 | `mcp_registry/` → `mcp_discovery.py` | PostgreSQL | impl_done | — | stdio 传输 |
| 5.3 | MCP 工具安全边界校验 | B | — | `security/test_mcp_security_boundaries.py` | — | impl_done | — | 风险等级 + 角色权限 |

### 6. 知识库管理（Knowledge Base）

| # | 单元名 | 涉及层 | 前端文件 | 后端文件 | 存储 | 状态 | 阻断 | 备注 |
|---|--------|:--:|------|------|------|:--:|:---:|---|
| 6.1 | 知识资产上传与管理 | F+B+S | admin knowledge 页 | `policy_knowledge_routes.py` | PostgreSQL + Milvus | impl_done | — | 向量化入库 |
| 6.2 | 知识检索（RAG） | B+S | — | `rule_explanation/` → `policy_retrieval/` | Milvus + SQLServer | impl_done | — | 检索→重排 |
| 6.3 | 政策知识浏览 | F+B | `policy-knowledge/page.tsx` | `policy_knowledge_routes.py` | — | impl_done | — | 列表/搜索/详情 |

### 7. 技能管理（Skill Management）

| # | 单元名 | 涉及层 | 前端文件 | 后端文件 | 存储 | 状态 | 阻断 | 备注 |
|---|--------|:--:|------|------|------|:--:|:---:|---|
| 7.1 | 技能注册/加载/路由 | B+S | — | `skill_loader.py` → `skill_router.py` | PostgreSQL | impl_done | — | YAML 配置驱动 |
| 7.2 | 费用解释 Skill 执行 | B+S | — | `settlement_explain_skill/` → `skill_registry/engine.py` | — | impl_done | — | 语义层计算 |
| 7.3 | 技能列表与管理 | F+B+S | `skills/page.tsx` | `infra_skill_routes.py` | PostgreSQL | impl_done | — | CRUD |

### 8. 运营看板（Dashboard）

| # | 单元名 | 涉及层 | 前端文件 | 后端文件 | 存储 | 状态 | 阻断 | 备注 |
|---|--------|:--:|------|------|------|:--:|:---:|---|
| 8.1 | 运营指标展示（结算异常/质控/问答统计） | F+B | `dashboard/page.tsx` | 聚合查询 | PostgreSQL | impl_done | — | 图表组件 |
| 8.2 | 工作流状态监控 | F+B | `dashboard/page.tsx` | `GET /workflows` 聚合 | PostgreSQL | impl_done | — | 列表+筛选 |

### 9. 嵌入式组件（Embed）

| # | 单元名 | 涉及层 | 前端文件 | 后端文件 | 存储 | 状态 | 阻断 | 备注 |
|---|--------|:--:|------|------|------|:--:|:---:|---|
| 9.1 | 嵌入式 Chat Widget | F | `src/apps/embed/` | 复用后端 API | — | impl_done | — | 可嵌入 HIS/EMR |

### 10. 安全与审计（Security & Audit）

| # | 单元名 | 涉及层 | 前端文件 | 后端文件 | 存储 | 状态 | 阻断 | 备注 |
|---|--------|:--:|------|------|------|:--:|:---:|---|
| 10.1 | 用户认证鉴权（SSO/RBAC） | B | — | `security/authorization/` | — | pending | — | 需对接医院 SSO |
| 10.2 | 审计日志持久化与查询 | B+S | — | `security/audit/postgresql_store.py` | PostgreSQL | pending | — | 审计事件查询 |

### 11. 适配器接入（Adapter Integration）

| # | 单元名 | 涉及层 | 前端文件 | 后端文件 | 存储 | 状态 | 阻断 | 备注 |
|---|--------|:--:|------|------|------|:--:|:---:|---|
| 11.1 | 医保接口适配器对接真实系统 | B | — | `adapters/insurance/` | — | blocked | 需真实医保接口 | 当前内存实现 |
| 11.2 | DRG/DIP 适配器对接真实系统 | B | — | `adapters/drg_dip/` | — | blocked | 需大瑞集思系统 | 当前内存实现 |

---

## 阻塞项汇总

| 单元 | 领域 | 阻塞原因 | 解锁条件 |
|---|---|---|---|
| 11.1 | 适配器接入 | 医保接口适配器需要真实医院医保系统接口 | 获取医院医保系统 API 文档和测试环境 |
| 11.2 | 适配器接入 | DRG/DIP 适配器需要大瑞集思 DRG/DIP 系统接口 | 获取大瑞集思系统 API 文档和测试环境 |

---

## 变更日志

| 日期 | 变更 | 影响单元 |
|------|------|---------|
| 2026-07-07 | 初始化进度追踪文件 | 全部 32 个单元 |

---

> **维护约定**：每次状态变更必须在此文件记录。禁止仅口头/IM 同步进度。
