# 数据治理流程一体化与治理 Flow 迁移设计 V2.0

> 日期：2026-09-15
> 范围：治理 Flow 迁移、数据治理流程 redesign、语义发现接入、Tool → SQL 可视化优化
> 关联 issue：#34 数据底座路线、#65 治理 Flow 控制面、#69 Tool/Workflow 首增量

---

## 1. 背景与目标

### 1.1 当前问题

| 问题 | 现状 | 影响 |
|---|---|---|
| 治理 Flow 位置孤立 | 后端在 `src/runtime/flow/`，前端只有 `/flow/[flowId]` 且无列表页 | 用户从数据治理入口找不到 Flow 编排 |
| 数据治理流程不完整 | `/data-governance` 只展示“数据源接入→同步→质量” | 看不到后续语义建模、Flow 编排、消费运营 |
| 语义发现未接入数据治理 | 发现中心在 `/semantic-layer/discovery`，扫描入口独立 | 数据源登记后不能在同一流程里做字段发现 |
| Tool → SQL 无可视化 | Tool 调用语义查询生成 SQL，但 `/tools` 只展示元数据 | 运维人员无法直观看到 Tool 最终产出的 SQL |

### 1.2 目标

- 把治理 Flow 并入数据治理，成为数据治理流程的一个阶段。
- 设计端到端的**五阶段数据治理流水线**，所有阶段从 `/data-governance` 进入。
- 数据源详情页一键进入语义发现，发现结果可跳转语义层建模型。
- Tool 和 Workflow 增加“查看生成 SQL / 执行计划”可视化能力。

---

## 2. 目标流程：五阶段数据治理流水线

```
A. 数据源接入  →  B. 字段探查/语义发现  →  C. 语义建模  →  D. 治理 Flow 编排  →  E. 消费运营
```

| 阶段 | 用户动作 | 涉及模块 | 当前状态 |
|---|---|---|---|
| A. 数据源接入 | 登记 SQL Server 数据源 → 配置凭据 → 连接/CDC 检测 → 配置同步任务 | `runtime/data_governance` | ✅ 已上线 |
| B. 字段探查/语义发现 | 从数据源触发扫描 → 查看字段与语义字段匹配情况 → 未映射字段提交语义提议 | `runtime/discovery` + `semantic_layer` | 🟡 能力有，入口割裂 |
| C. 语义建模 | 评审/发布语义对象、数据集、指标、值域、关系 | `semantic_layer` | ✅ 已上线 |
| D. 治理 Flow 编排 | 从已发布语义对象构建消费视图 → 校验 → 发布 → 部署 SQL view | `runtime/flow`（待迁入数据治理） | ✅ 能力有，位置错 |
| E. 消费运营 | query_planner / assistant 消费；数据目录/血缘；运营仪表盘 | `runtime/ops_analytics` + `data_catalog` | ✅ 已上线 |

---

## 3. 模块重组设计

### 3.1 后端模块迁移

- `src/runtime/flow/` → **`src/runtime/data_governance/flow/`**
  - `flow_service.py` → `data_governance/flow/flow_service.py`
  - `flow_query_service.py` → `data_governance/flow/flow_query_service.py`
- `src/domain/governed_flow/` **保持不变**（领域模型不随运行时模块迁移）。
- `src/data_platform/storage/flow/` **保持不变**（存储端口位置稳定）。
- `src/runtime/api/flow_routes.py` 保留，但内部转发到新的 `data_governance.flow.*` 导入路径；同时新增 `data_governance_routes.py` 中的 `/flows` 子路由。

### 3.2 前端页面迁移

- `src/apps/portal/app/flow/[flowId]/page.tsx` → **`src/apps/portal/app/data-governance/flows/[flowId]/page.tsx`**
- 新增 **`src/apps/portal/app/data-governance/flows/page.tsx`**（Flow 列表）
- 新增 **`src/apps/portal/app/data-governance/flows/new/page.tsx`**（创建 Flow）
- 旧 `/flow/[flowId]` 和 `/flow` 做 **301 重定向**到 `/data-governance/flows/*`，保留书签兼容。

### 3.3 导航调整

- 顶部导航/侧边栏的“数据治理”入口下增加子菜单：
  - 概览 `/data-governance`
  - 数据源 `/data-governance/data-sources`
  - Flow 编排 `/data-governance/flows`
- 原顶部独立的 `/flow` 入口移除。

---

## 4. API 设计

### 4.1 路由迁移与别名

| 旧路由（保留别名） | 新规范路由 | 说明 |
|---|---|---|
| `/api/v1/medical-insurance-ai-agent/flow` | `/api/v1/medical-insurance-ai-agent/data-governance/flows` | Flow 生命周期 CRUD |
| `/api/v1/medical-insurance-ai-agent/flow/{id}/...` | `/api/v1/medical-insurance-ai-agent/data-governance/flows/{id}/...` | validate/publish/rollback/query 等 |
| `/api/v1/medical-insurance-ai-agent/flow/consume` | `/api/v1/medical-insurance-ai-agent/data-governance/flows/consume` | 指标码驱动受控消费 |

- 旧 `/flow/*` 在 `app.py` 中注册为 **deprecated alias**，返回时响应头带 `Deprecation: true`，至少保留 1 个版本。
- 新 `/data-governance/flows/*` 由 `data_governance_routes.py` 的子 router 承载。

### 4.2 数据源级语义发现接口（只读聚合）

```
GET /api/v1/medical-insurance-ai-agent/data-governance/data-sources/{source_id}/discovery
```

- 调用 `src.runtime.discovery.service.run_discovery(datasource_id=source_id, governance_service=...)`
- 返回：
  ```json
  {
    "source_id": "bjybdb",
    "total_tables": 12,
    "total_fields": 156,
    "mapped_fields": 47,
    "unmapped_fields": 109,
    "tables": [...],
    "fields": [
      {
        "field_name": "T_FundPay",
        "table_name": "dbo.o_Trade",
        "data_type": "decimal",
        "mapped": true,
        "semantic_field_code": "outpatient_trade.fund_pay",
        "semantic_metrics": ["mz_trade.fund_pay"]
      }
    ]
  }
  ```

扫描触发和历史继续复用现有的 `/api/v1/medical-insurance-ai-agent/semantic/discovery/*` SSE 端点，避免重复实现流式扫描。

### 4.3 Tool SQL Trace 接口

```
POST /api/v1/medical-insurance-ai-agent/tool-registry/tools/{tool_id}/sql-trace
```

- 仅对 `contract_kind=function` 且 target_ref 指向语义查询的数据类 Tool 有效（如 `tool_query_semantic_metrics`）。
- 请求体：Tool 所需的 sample 参数（如 `object_code`、`entity_code`、`anchor_value`、`metrics`）。
- 响应：
  ```json
  {
    "tool_id": "tool_query_semantic_metrics",
    "params": { "object_code": "mz_trade", ... },
    "trace": {
      "semantic_query": { "object_code": "mz_trade", "metrics": ["fund_pay"], ... },
      "logical_plan": { "branches": [...], "joins": [...] },
      "sql": "SELECT ...",
      "readonly": true
    },
    "uncertainty": null
  }
  ```
- 非数据类 Tool 返回 `422 TOOL_SQL_TRACE_NOT_APPLICABLE`。

### 4.4 Flow SQL 分步可视化接口

```
GET /api/v1/medical-insurance-ai-agent/data-governance/flows/{flow_id}/sql-trace
```

- 复用 `preview_flow()` 的编译产物，按 node_id 拆分：
  ```json
  {
    "flow_id": "flow_outpatient_summary",
    "view_name": "vw_flow_outpatient_summary_v1",
    "steps": [
      { "node_id": "src_trade", "node_type": "source", "sql": "SELECT ... FROM mz_trade" },
      { "node_id": "join_fee", "node_type": "join", "sql": "... LEFT JOIN mz_fee_item ..." },
      { "node_id": "dim_dept", "node_type": "dimension", "sql": "... GROUP BY dept" },
      { "node_id": "metric_fund", "node_type": "metric", "sql": "... SUM(fund_pay) ..." },
      { "node_id": "consumer_ops", "node_type": "consumer", "sql": "CREATE OR REPLACE VIEW ..." }
    ]
  }
  ```
- 当前 `GET /flows/{id}/preview` 继续保留完整编译产物返回。

---

## 5. 前端页面重组

### 5.1 `/data-governance` 概览页升级

从“指标卡 + 表格”升级为**五阶段流程导航** + 详情折叠：

- 顶部流程条：A → B → C → D → E，每阶段显示当前状态徽章。
  - A：数据源数量 / 健康数
  - B：待发现数据源数 / 已映射字段数
  - C：已发布对象数 / 待评审提议数
  - D：已发布 Flow 数 / 草稿数
  - E：今日消费查询数 / 运营仪表盘入口
- 下方保留现有的医院同步状态表格（A 阶段详情）。

### 5.2 数据源详情发现入口

在 `/data-governance/data-sources` 表格的每行操作列增加：**“语义发现”** 按钮。

点击后进入：

```
/data-governance/data-sources/{sourceId}/discovery
```

该页面复用 `/semantic-layer/discovery` 的字段扫描结果组件，但：
- 预筛选当前数据源；
- 突出显示 **已映射 / 未映射** 字段；
- 未映射字段支持“提交语义字段提议”跳转 `/semantic-layer/mapping?object_code=...&table=...&field=...`。

### 5.3 Flow 列表与编辑器

- `/data-governance/flows`：卡片/表格列表，展示 `flow_id`、`name`、`status`、`published_revision`、`owner`、最近发布时间和操作（编辑/发布/退役）。
- `/data-governance/flows/[flowId]`：迁移后的画布编辑器，左侧画布、右侧属性面板、下方校验/编译预览/修订标签页。
- 编译预览标签拆分为两栏：
  - 左：节点级 SQL trace（Source → Join → Dimension → Metric → Consumer）
  - 右：最终完整 `view_sql`

### 5.4 Tool / Workflow SQL Trace 可视化

- `/tools` 每个 Tool 卡片增加 **“查看生成 SQL”** 按钮（仅数据类 Tool 可用）。
- 点击展开抽屉/弹窗，三栏展示：
  1. **语义查询**：object_code / metrics / scope / filters
  2. **逻辑计划**：branches / joins / result_grain
  3. **生成 SQL**：高亮只读 SQL
- Workflow 执行结果中，每个步骤若调用数据类 Tool，展开后显示同样的 SQL Trace 面板。

---

## 6. 权限设计

Flow 迁入数据治理后，统一使用数据治理权限：

| 操作 | 权限 |
|---|---|
| `GET /data-governance/flows/*` | `data_governance:read` |
| `POST /data-governance/flows` | `data_governance:write` |
| `PUT /data-governance/flows/{id}` | `data_governance:write` |
| `POST /data-governance/flows/{id}/publish` | `data_governance:write` |
| `POST /data-governance/flows/{id}/query` | `data_governance:read` + 角色级别映射（保留现有 `FLOW_CALLER_ROLE_LEVELS`） |
| `GET /data-governance/data-sources/{id}/discovery` | `data_governance:read` |
| `POST /tool-registry/tools/{id}/sql-trace` | `data_governance:read`（只读 trace，不执行） |

旧 `/flow/*` 别名在转发前补权限校验，避免原先部分写接口未显式鉴权的问题。

---

## 7. 数据模型变化

**本次迁移不修改数据库表结构。**

涉及的数据库表/端口：
- `governed_flows` / `governed_flow_revisions` / `governed_flow_active_revision`：位置不变。
- `data_catalog_assets` / `data_catalog_lineage_edges`：在阶段 E 消费时复用。
- `discovery_*`：由 `runtime/discovery` 继续使用。

---

## 8. 实现阶段（最小可验证单元）

### 阶段 1：后端迁移（1.5 天）

- [ ] 移动 `src/runtime/flow/` → `src/runtime/data_governance/flow/`
- [ ] 更新 `flow_routes.py` 导入路径
- [ ] 在 `data_governance_routes.py` 中挂载 `/flows` 子路由
- [ ] `app.py` 同时注册旧 `/flow` 别名（标记 `Deprecation` 头）
- [ ] 修复 import 与单元测试路径
- [ ] 后端测试全绿

### 阶段 2：前端迁移（1.5 天）

- [ ] 移动 Flow 编辑器页面到 `/data-governance/flows/[flowId]`
- [ ] 新增 `/data-governance/flows` 列表页
- [ ] 旧 `/flow/*` 添加 301 重定向
- [ ] 更新 Portal 导航，数据治理菜单下加入 Flow 编排
- [ ] 前端 Vitest + build 通过

### 阶段 3：数据治理概览流程视图（1 天）

- [ ] `/data-governance` 页面顶部增加五阶段流程条
- [ ] 每阶段状态从对应服务读取（数据源自 `overview`、发现从 `discovery`、语义从 `registry`、Flow 从 flow storage）
- [ ] 阶段卡片可点击跳转到对应页面

### 阶段 4：数据源 → 语义发现打通（1 天）

- [ ] 后端新增 `GET /data-governance/data-sources/{id}/discovery`
- [ ] 数据源列表增加“语义发现”按钮
- [ ] 新增 `/data-governance/data-sources/[sourceId]/discovery` 页面
- [ ] 未映射字段支持跳转 `/semantic-layer/mapping`

### 阶段 5：Tool / Workflow SQL Trace（1.5 天）

- [ ] 后端新增 `POST /tool-registry/tools/{id}/sql-trace`
- [ ] 前端 `/tools` 增加 SQL Trace 抽屉
- [ ] Workflow 执行结果组件增加每步 SQL Trace 展开面板

### 阶段 6：Flow SQL 分步可视化（1 天）

- [ ] 后端新增 `GET /data-governance/flows/{id}/sql-trace`
- [ ] Flow 编辑器编译预览标签增加节点级 SQL 拆解

---

## 9. 验收标准

### 总体验收

- [ ] 从 `/data-governance` 可完成 A→D 全链路跳转，无需记忆独立 `/flow` URL。
- [ ] 旧 `/flow/*` 访问自动重定向到新路径。
- [ ] 数据治理流程五阶段状态与后端实际状态一致。
- [ ] 数据类 Tool 可展示从语义查询到最终 SQL 的完整 trace。
- [ ] 所有既有 Flow 相关的 API 测试、Flow 测试、Portal 测试保持通过。

### 各阶段验收

| 阶段 | 验收动作 |
|---|---|
| 1 | `pytest src/tests/unit/runtime/flow src/tests/integration/api/test_flow_routes.py` 全绿；旧 `/flow` 别名返回 200 |
| 2 | Portal `/data-governance/flows` 能列出 Flow；点击可进入编辑器；旧 `/flow/xxx` 重定向成功 |
| 3 | `/data-governance` 页面五阶段条显示正确；点击各阶段跳转正确 |
| 4 | 数据源详情“语义发现”能加载字段映射结果；未映射字段可跳转语义层 |
| 5 | `/tools` 中 `tool_query_semantic_metrics` 能弹出 SQL trace；Workflow 执行后步骤可展开 SQL |
| 6 | Flow 编辑器编译预览能看到 Source→Consumer 每步 SQL；最终 view_sql 与既有 preview 一致 |

---

## 10. 风险与回滚

| 风险 | 应对 |
|---|---|
| 移动模块破坏既有测试 | 阶段 1 只做目录移动 + import 修复，不改逻辑；全量测试通过后进入下一阶段 |
| 旧 `/flow` URL 被外部书签依赖 | 保留 301 重定向至少一个版本，并加 `Deprecation` 响应头 |
| Flow 权限升级导致现有调用 403 | 旧别名沿用原权限；新 `/data-governance/flows` 按数据治理权限，过渡期双轨运行 |
| SQL Trace 暴露敏感字段 | Trace 只读不执行；detail 级维度仍按 `FLOW_CALLER_ROLE_LEVELS` 拦截 |

---

## 11. 非目标

- 不替换 `SemanticQueryPlanner` 的 SQL 生成逻辑。
- 不引入新的通用 DAG 引擎或 Airflow/dbt。
- 不修改 `src/domain/governed_flow/` 领域模型。
- 不改动现有 `data_catalog` 资产模型与血缘存储。
