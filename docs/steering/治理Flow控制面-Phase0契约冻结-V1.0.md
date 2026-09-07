# 治理 Flow 控制面 — Phase 0 契约冻结 V1.0

> 状态：已冻结（Phase 0 交付物）  
> 日期：2026-09-04  
> 父 issue：[#65 治理 Flow 控制面](https://github.com/ktyhwangfei/hospital_medical_insurance_agent/issues/65)  
> 方案依据：`docs/research/治理中心全流程可视化配置-开源调研与落地方案-V1.0.md`（§9 决策已确认）  
> 代码落位：`src/domain/governed_flow/models.py`（DSL）+ `validation.py`（校验）  
> 测试基线：`src/tests/unit/governed_flow/`（49 passed）

---

## 1. 冻结范围

| 冻结项 | 落位 | 变更要求 |
|---|---|---|
| Flow DSL（节点/边/聚合根） | `models.py` | 过评审 + 同步领域字典 §14.6 |
| 节点类型白名单（8 类） | `FlowNodeType` | 同上 |
| 聚合算子白名单 | `AggregateOperator`：count/count_distinct/sum/avg | 同上 |
| 过滤算子（含 `in_or_null`） | `FilterOperator` | 同上 |
| 状态机 | `FLOW_STATUS_TRANSITIONS` + `transition_flow_status()` | 同上 |
| content_hash 规则 | `compute_flow_content_hash()` | 同上 |
| 错误码（23 个 `FLOW_*`） | `FLOW_ERROR_CODES` | 同上 |
| T_CureType/med_type 边界 | `validation.py` FLOW_CURE_TYPE_DOMAIN_INVALID | 同上 |

**DSL 结构速览**（完整定义见代码，此处为阅读入口）：

```text
FlowDefinition（聚合根）
  nodes[]        FlowNode 判别联合：source | filter | join | aggregate
                 | derived_metric | dimension | quality_gate | consumer
  edges[]        FlowEdge（DAG，source 无入边，consumer 无出边）
  source_contracts[]   SourceContract（dataset_code + 字段白名单）
  metric_outputs[]     MetricOutputBinding（metric_code + 口径句 policy_definition 必填
                       + policy_carrier 复用 #60：doc_number/region_scope/effective_*）
  materialization      仅 view（Phase 0/1）
  revision             乐观锁
  content_hash         规范化 JSON sha256（排除 revision/status/发布元数据/画布坐标，
                       节点顺序无关——拓扑由 edges 决定）
```

**状态机**：`draft → validating → pending_review → published → deprecated`。
已发布 flow 再编辑 = 新 revision 从 draft 开始，active revision 不受影响；
回滚只切换 active revision，不删除历史证据；deprecated 为终态。

**设计裁决记录**（Phase 0 讨论中确定）：
1. 过滤条件为 AND 扁平列表，`in_or_null` 算子精确表达口径句 v4 的
   `IN (...) OR IS NULL` 分支，避免引入任意 OR 组合能力。
2. 聚合度量显式携带 `null_policy` / `reversal_policy` / `distinct_key`
   （count_distinct 必填），策略不可隐式。
3. 画布坐标 `position` 是展示元数据：随定义存储但不参与 content_hash。
4. 派生公式走 AST 白名单（仅 `+ - * /`、一元正负、依赖变量、数值常量），
   与 `FormulaEvaluator` 同域，禁止函数调用/属性访问/字符串常量。

## 2. Golden Flow（#62 四字段，唯一首批）

基准夹具：`src/tests/unit/governed_flow/golden_flow.py`
（`build_golden_flow()` + `golden_validation_context()`）。

```text
src_trade(source: mz_trade) → filter_valid(口径句 v4)
  → agg_snapshot(count_distinct T_TradeNo; sum T_FeeAll/T_FundPay/T_SelfPayAll)
  → gate_caliber(caliber_signoff + identity_assertion 总费用=基金+个人, tol=0)
  → consumer_qp(query_planner)
```

- 口径句 v4 全文（发布门禁按全文精确匹配签核集合）：
  `T_State IN (2,3) AND NP_Settle_State=1 AND T_HasRefundmented != 1
  AND (T_PartialReturnFlag IS NULL OR T_PartialReturnFlag='')
  AND (T_CureType IN (11,17,18,19) OR T_CureType IS NULL)`
- 勾稽恒等：`op_total_fee = op_fund_pay + op_self_pay`（活库实测差 0.00）。
- **T_CureType 与 med_type 不混用（冻结）**：T_CureType 是 SQL Server 物理列，
  值域走已发布 `MZ_CURE_TYPE = {11,17,18,19}`；med_type 是政策知识管线的
  医疗类别维度，不得作为 T_CureType 的过滤值域（校验器强制
  `value_domain=MZ_CURE_TYPE`，违规发 FLOW_CURE_TYPE_DOMAIN_INVALID）。
- 次均费用/就诊人次口径未定：DSL 可表达（derived_metric）但依赖未发布
  指标时 FLOW_DEPENDENCY_NOT_PUBLISHED 挡发布，与 #35 暂缓门禁一致。

## 3. API / 数据库 / 前端 DTO 对照

### 3.1 Phase 1 API 规划（`/api/v1/medical-insurance-ai-agent/flow` 前缀）

| 端点 | 方法 | 状态前置 | 错误码 |
|---|---|---|---|
| `/flows` | POST/GET | — | FLOW_REVISION_CONFLICT |
| `/flows/{flow_id}` | GET/PUT/DELETE | draft | FLOW_NOT_FOUND / FLOW_REVISION_CONFLICT |
| `/flows/{flow_id}/validate` | POST | draft→validating→draft | FLOW_*（校验报告全量返回） |
| `/flows/{flow_id}/submit-review` | POST | validating | FLOW_STATE_INVALID |
| `/flows/{flow_id}/publish` | POST | pending_review | FLOW_CALIBER_NOT_SIGNED 等 fail closed |
| `/flows/{flow_id}/rollback` | POST | published | FLOW_NOT_FOUND |
| `/flows/{flow_id}/deprecate` | POST | published | FLOW_STATE_INVALID |
| `/flows/{flow_id}/revisions` | GET | — | — |
| `/flows/{flow_id}/preview` | GET | draft+ | 编译产物预览（SQL/计划） |

鉴权沿用 data-governance 模式（`flow:read` / `flow:write` 权限 + signed token）。

### 3.2 数据库（Phase 1，遵循 CREATE+ALTER 双写 + JSONB）

| 表 | 关键列 | 说明 |
|---|---|---|
| `governed_flows` | flow_id PK, status, revision, content_hash, definition JSONB, published_at/by | 草稿/当前态；乐观锁 revision |
| `governed_flow_revisions` | revision_id PK, flow_id, flow_revision, content_hash, semantic_revision, artifact_hash, definition JSONB, is_active | 不可变发布证据；`(flow_id) WHERE is_active` 部分唯一索引；回滚只切 is_active |

存储四件套照 skill 模式：`flow_ports.py / flow_in_memory.py / flow_postgres.py / flow_factory.py`
（`USE_MEMORY_STORAGE=1` 回退内存）。

### 3.3 前端 DTO 映射（Phase 2 画布）

| 后端（snake_case） | 前端/XYFlow（camelCase） | 说明 |
|---|---|---|
| `node_id` | `id` | XYFlow 节点主键 |
| `position {x,y}` | `position {x,y}` | 同构直传 |
| `node_type` | `type` | 自定义节点组件注册名（source→FlowSourceNode 等） |
| `name` + 节点参数 | `data` | XYFlow data 载荷；只存展示所需子集 |
| `edges[].from_node/to_node` | `source/target` | XYFlow 边 |
| `edge_id` | `id` | — |
| 校验报告 `issues[]` | 属性面板错误列表 | `has_blocking` 顶部横幅 |

序列化方向：画布 XYFlow 状态 → 前端组装 FlowDefinition JSON（snake_case）→
后端 Pydantic 校验。禁止前端直接产出 SQL 或绕过 definition 结构。

## 4. 威胁模型（Phase 0 冻结的安全边界）

| # | 威胁 | 向量 | 缓解（已实现/规划） | 状态 |
|---|---|---|---|---|
| T1 | 任意 SQL/脚本注入画布 | 伪造 node_type=script | 判别联合白名单 + FLOW_NODE_TYPE_INVALID | ✅ |
| T2 | 连接串直连外部库 | source 节点夹带 DSN | SourceNode 仅 dataset_code，无连接字段；Phase 1 校验已登记 | ✅ 契约 |
| T3 | 字段越权读取 | filter/aggregate 引用契约外字段 | SourceContract 白名单 + FLOW_FIELD_NOT_IN_CONTRACT | ✅ |
| T4 | 值域混淆 | T_CureType 走 med_type 值域 | FLOW_CURE_TYPE_DOMAIN_INVALID（强制 MZ_CURE_TYPE） | ✅ |
| T5 | 公式 RCE | derived expression 夹带 eval/`__import__` | AST 白名单（算术+依赖变量+数值常量） | ✅ |
| T6 | 未签核口径发布 | 跳过知识签核直接 publish | FLOW_CALIBER_NOT_SIGNED fail closed（签核集合由服务层注入） | ✅ 契约 |
| T7 | 依赖未发布指标 | derived 引用 draft 指标 | FLOW_DEPENDENCY_NOT_PUBLISHED | ✅ |
| T8 | 篡改历史证据 | 回滚时改写旧 revision | 发布修订不可变；回滚只切 is_active | ✅ 契约 |
| T9 | 并发写冲突 | 双人同时编辑 | expected_revision 乐观锁 + FLOW_REVISION_CONFLICT | ✅ 契约 |
| T10 | 笛卡尔积 join | 未登记关系自由 join | FLOW_RELATION_NOT_REGISTERED | ✅ |
| T11 | 越权维度下钻 | detail 级维度给 summary 用户 | DimensionBinding.permission_level；Phase 3 消费侧强制 | 🟡 契约已冻结，执行 Phase 3 |
| T12 | 画布 XSS | 节点名/口径句回显注入 | React 默认转义 + 字段 max_length；Phase 2 页面复测 | 🟡 Phase 2 |
| T13 | 大 payload DoS | 超大 definition | 字段级 max_length 已有；**节点/边数量上限 Phase 1 API 层补** | 🟡 Phase 1 待办 |
| T14 | 自然语言直译 SQL | 问数绕过消费契约 | 执行只走 query_planner 已发布语义（#36 边界），DSL 不含 NL 入口 | ✅ 继承 |

## 5. 画布组件技术验证结论（决策记录 #3 兑现）

验证对象：`@xyflow/react@12.11.6`（React Flow v12）。验证后已按决策
「不提前引入依赖」移除（`--no-save` 安装 + `npm prune`），Phase 2 执行
`npm install @xyflow/react` 重新引入即可复跑。

| 验证项 | 结果 |
|---|---|
| 许可证 | MIT（核心与 @xyflow/system 均 MIT）✅ |
| 版本/依赖 | 12.11.6；仅 zustand/classcat/@xyflow/system，portal 无版本冲突 ✅ |
| 包体积 | unpacked ~1.2MB（含样式/源码）；node_modules 连依赖 3.0MB，可接受 ✅ |
| jsdom+Vitest 渲染 | 节点/viewport/pane 正常渲染（2 个 API 桩即可，见下）✅ |
| 键盘可达性 | wrapper `role="application"`，节点 `tabindex="0"` + `role="group"` ✅ |
| TypeScript | `tsc --noEmit` 通过（类型完备）✅ |
| Next.js 16 构建 | `'use client'` 页面静态预渲染通过（`/flow-spike` 产物确认）✅ |

**已验证的实施陷阱（Phase 2 必须遵守）**：
1. **必须具名导入** `import { ReactFlow } from "@xyflow/react"`；
   默认导出在部分打包链路下解析为 undefined（本项目 Vitest 实测）。
2. jsdom 测试需要两个桩：`ResizeObserver`（observe 时**同步回调非零尺寸**，
   否则视口不初始化、pane 缺失）与 `DOMMatrixReadOnly`（`m22=1`）。
3. SVG 边在 jsdom 下不渲染（无真实布局测量）——边交互验证走 Playwright
   真实浏览器 E2E，不在 Vitest 断言。
4. 服务端渲染必须 `'use client'`；样式 `@xyflow/react/dist/style.css` 随组件导入。
5. 移动端（390px）与键盘全路径可达性需真实浏览器矩阵验证，Phase 2 验收项。

复跑命令（Phase 2 引入依赖后）：
`cd src/apps/portal && npx vitest run src/tests/flow-canvas-spike.test.tsx`

## 6. Phase 0 验证证据（2026-09-04）

- 单元测试：`uv run python -m pytest src/tests/unit/governed_flow/ -q`
  → **49 passed**（契约 28 + 校验 21；含 Golden Flow 正反例、发布门禁
  fail closed、hash 稳定性、状态机全路径）。
- `python -m compileall src/domain/governed_flow` 通过。
- Portal：spike Vitest 2 passed、`tsc --noEmit` 通过、`npm run build` 通过
  （验证后产物已清理，见 §5）。

## 7. 遗留与下一步（Phase 1 入口）

1. **合并 #62 分支**：`ktyhwangfei/issue-62-processing-fields` 已签核未合并；
   Phase 1 的注册表接线与存量一致断言依赖其交付物
   （`docs/processing/registry.yaml`、`v_op_outpatient_processed` 视图）。
2. Phase 1 范围（按父 issue）：草稿 CRUD、图校验服务化、查询计划预览、
   View 编译（`CREATE OR REPLACE VIEW`，PG 落地库方言，见 §9）、质量门禁执行、发布/回滚 + 存储
   四件套 + API 路由 + 审计。
3. T13 节点/边数量上限在 Phase 1 API 层补齐。
4. 领域字典 §14.6 已同步（本仓库规则：新增领域概念必须同步更新）。

## 8. Phase 1 落地记录（2026-09-04，同日完成）

**前置**：`ktyhwangfei/issue-62-processing-fields` 已合入 main（merge `d51d908`），
issue-65 分支已同步合并。

### 8.1 交付物

| 层 | 文件 | 内容 |
|---|---|---|
| 域编译器 | `src/domain/governed_flow/compiler.py` | 线性管道 → `CREATE OR REPLACE VIEW`（PG 落地库方言，§9 裁决）；标识符白名单正则 + 双引号渲染 + 字面量转义 + 派生公式 AST 重序列化（T5 注入面全关）；Golden Flow 编译产物与 #62 视图 SELECT/WHERE 语义等价 |
| 存储 | `src/data_platform/storage/flow/` | 四件套（ports/in_memory/postgres/factory）；`governed_flows` + `governed_flow_revisions` 双表，`(flow_id) WHERE is_active` 部分唯一索引，活跃切换单条 UPDATE 原子完成 |
| 服务 | `src/runtime/flow/flow_service.py` | 草稿 CRUD/校验编排/发布原子锁（flow revision + semantic revision + artifact hash）/回滚只切活跃指针/退役终态；签核上下文从语义层已发布指标定义推导 |
| API | `src/runtime/api/flow_routes.py` | §3.1 全部 12 操作挂载（`/flow` 前缀），错误码映射 404/409/422；服务经 `Depends(get_flow_service)` 注入（可 override） |
| 语义层 | `src/semantic_layer/seed.py` | 四个 op_* 指标 `source_field` 前缀切换为 `outpatient_postgres.v_op_outpatient_processed.*`（§9 裁决：加工落位 PG 落地库）；曾短暂登记的 `o_trade`/`mzjy_src` 已按 §9 回退删除 |

### 8.2 实现裁决（偏离/细化 §3 之处）

1. **已发布再编辑**：PUT 在 published 状态 = 从当前定义开新修订（draft 起步），
   活跃发布证据不动——对齐状态机注释「新 revision 从 draft 开始」。
2. **validating 为瞬态**：validate 端点 draft→validating→draft 一次完成；
   submit-review 内部过 validating 直达 pending_review，避免出现无法离开的中间态。
3. **签核口径句提取**：#62 批次二治理指标定义为散文格式
   （「口径句v4：<签核说明>。<口径句全文>」），上下文构建把 marker 后尾巴
   整体及按「。」切分的句段都收入签核集合，发布门禁按口径句全文精确匹配不变。
4. **错误码扩展 23→24**：新增 `FLOW_COMPILE_UNSUPPORTED`（图形态超出 Phase 1
   线性编译能力：分叉/缺聚合输出），已同步冻结清单与防逃逸测试。
5. **MZ_CURE_TYPE 值域超集**：语义层字典并集语义下该值域含政策字典补充值
   （15 个），黄金过滤值 {11,17,18,19} ⊆ 值域仍通过；结构强制
   （T_CureType 必须声明 MZ_CURE_TYPE）不受影响。

### 8.3 验证证据

- Unit（T1）：`src/tests/unit/governed_flow/` → **78 passed**
  （新增编译器 15：golden SQL 等价/注入三连拒/分叉拒/hash 确定性；
  新增存储 14：CRUD 乐观锁/发布证据/活跃切换/深拷贝隔离）。
- API（T2a）：`src/tests/integration/api/test_governed_flow_api.py` → **16 passed**
  （12 端点 happy path + 404/409/422；口径句篡改过评审但发布 422 fail closed 携全量报告）。
- Flow（T2b）：`src/tests/integration/flow/test_governed_flow_lifecycle.py` → **2 passed**
  （完整生命周期：发布→再编辑开新修订→二次发布→回滚证据不可变→终态全拒止）。
- PG 活库冒烟：`test_governed_flow_pg_smoke.py` → 1 passed（DDL + 部分唯一索引 + 原子切换实测）。
- 遗留：T13 节点/边数量上限未做（Phase 2 API 加固）；质量门禁运行时执行
  （勾稽恒等查数断言）留 Phase 3 消费接线时落地。

## 9. 架构裁决修订：加工视图落位 PG 落地库（2026-09-07）

> 推翻本契约 §2 冻结的「source=o_trade（SQL Server 源库）」一项；其余冻结项不变。
> 由用户裁决 + 全量查证后原子落地（`fix(#62,#65)` 单提交）。

### 9.1 裁决内容与理由

**加工（含加工视图 DDL）一律在本院 PG 落地库执行，禁止在 SQL Server 源库执行。**

- 违反仓库自身铁律：外部系统只经 `adapters/` 防腐层访问、平台不修改既有业务系统
  ——往医保中心源库写 DDL 属于修改外部系统，生产环境亦无此权限。
- #62 原实现 `outpatient_processed_view.sql` 为 T-SQL（`CREATE OR ALTER ... FROM o_Trade`），
  T2a 活库测试曾真实往源库部署视图——本裁决一并纠正。
- **签核不失效**：口径句 v4 签核对象是口径语义（过滤条件与算子），不是执行位置；
  裁决只改「在哪里算」，口径句原文一字未动。

### 9.2 修正后的数据流

```
SQL Server bjybdb dbo.o_Trade（只读，同步 worker 经防腐层拉取）
  → PG outpatient_trade_current（原始落地 + 质量标记）
  → PG mz_trade（治理视图：payload 摊平，排除删除行/质量拦截行）
  → PG v_op_outpatient_processed（★ 加工视图：口径句 v4 + 四指标）
  → op_* 指标 source_field 路由 outpatient_postgres，供受控问数消费
```

附带收益：质量门禁先行（blocked 行进不了加工），代价是新鲜度受同步节奏限制
（指标本就声明 refresh_frequency 5m，口径一致）。

### 9.3 影响面（原子落地清单）

| 产物 | 变更 |
|------|------|
| `docs/processing/outpatient_processed_view.sql` | PG 方言重写：`CREATE OR REPLACE VIEW ... FROM mz_trade`，标识符双引号 |
| `docs/processing/registry.yaml` | `datasource: postgres://landing/outpatient_postgres`、`source_table: public.mz_trade`，`dbo.o_Trade` 降为 lineage 血缘标注 |
| `test_outpatient_processed_view_t2a.py` | 活库部署验收从源库改为 PG 落地库（对数基准 mz_trade） |
| `src/domain/governed_flow/compiler.py` | `CREATE OR REPLACE VIEW` + 全标识符双引号渲染（点分段各自包裹） |
| `golden_flow.py` 基准夹具 | source 契约 `o_trade/OutpatientTrade` → `mz_trade/mzjyxx`（列名与源契约一致） |
| `src/semantic_layer/seed.py` | op_* 指标 `source_field` 前缀 `bjybdb.` → `outpatient_postgres.`；回退删除 Phase 1 曾加的 `o_trade` 数据集与 `mzjy_src` 对象登记 |

### 9.4 实施中发现并裁决的衍生问题

1. **落地视图列名保留大小写**（`AS "T_TradeNo"`，payload 抽取）：PG 裸标识符折叠
   小写会报 column does not exist，故 #62 视图 SQL 与编译器产物统一双引号渲染
   （`"public"."mz_trade"`、`"T_State"`）。
2. **状态码列在落地视图为 text**（payload 抽取未数值化）：口径句的数值比较
   （IN/=/!=）经 `NULLIF(col,'')::NUMERIC` 显式转型执行，与落地视图数值列的
   渲染约定一致。曾尝试直接把 T_State 等 4 列加入 `_TRADE_NUMERIC_FIELDS`，
   活库验证发现 `CREATE OR REPLACE VIEW` 不能改既有视图列类型
   （`cannot change data type of view column ... from text to numeric`），
   需 DROP 重建即破坏既有库——回退为视图内显式转型；列类型数值化迁移留 Phase 3。
3. **编译器产物暂不带转型**：编译器只解析物理表名、不感知列类型；Phase 3
   执行器接线时负责按落地视图列类型注入 `NULLIF::NUMERIC` 转型
   （或届时做列类型迁移）后执行。

### 9.5 验证证据

- T2a 活库（PG 落地库 hospital_mcp）：`test_outpatient_processed_view_t2a.py` →
  **4 passed**（部署/权限、view==落地表同口径直接聚合逐值一致、勾稽恒等、med_type 边界）。
- 受影响确定性套件全绿：governed_flow Unit / processing / semantic_layer /
  data_platform outpatient_store / Flow API + 生命周期 + PG 冒烟（详见 PROGRESS 当日行）。
