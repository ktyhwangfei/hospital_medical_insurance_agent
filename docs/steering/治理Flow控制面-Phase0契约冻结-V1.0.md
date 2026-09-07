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
| T12 | 画布 XSS | 节点名/口径句回显注入 | React 默认转义 + 字段 max_length；Phase 2 页面复测 | ✅ Phase 2 页面全 React 文本节点渲染，无 dangerouslySetInnerHTML |
| T13 | 大 payload DoS | 超大 definition | 字段级 max_length + 节点/边数量上限（`MAX_FLOW_NODES=50`/`MAX_FLOW_EDGES=100`，Pydantic Field max_length 解析期 422；前端组件盘同步上限禁用） | ✅ Phase 2 补齐 |
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
5. 移动端（390px）与键盘全路径可达性需真实浏览器矩阵验证——已于 §13 完成（2026-09-07）。

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

## 10. Phase 2 落地记录（2026-09-07：可视化画布 + T13 加固）

**前置**：Phase 1（§8）+ §9 架构裁决均已合入；`@xyflow/react@12.11.6`
按 §5 决策正式引入（`npm install`，非 spike 的 --no-save）。

### 10.1 交付物

| 层 | 文件 | 内容 |
|----|------|------|
| API 客户端 | `src/apps/portal/src/lib/flow-api.ts` | 12 端点全量 TS 客户端；类型逐一镜像 Pydantic snake_case；`MAX_FLOW_NODES` 与后端同源常量导出 |
| 画布映射 | `src/apps/portal/src/components/flow/canvas-dto.ts` | 画布 ↔ FlowDefinition 双向映射 + 8 类新节点最小骨架（结构合法，画布补全） |
| 画布组件 | `flow-node-card.tsx` / `flow-canvas.tsx` | 8 类自定义节点卡（按类型配色/图标/摘要、校验问题数红徽标）；组件盘（节点达上限禁用 + `节点 n/50` 计数）+ 受控画布（只读模式、删除键、自环边拒绝） |
| 属性面板 | `node-property-panel.tsx` / `flow-detail-panels.tsx` | 8 类节点编辑器（filter 条件行含 11 操作符、`in*` 逗号分隔 + 数值自动转型；gate params JSON 文本域带解析红守卫）+ 契约/指标产出定义级编辑器；校验报告（问题点击定位节点）/编译预览（view_sql + query_plan + artifact_hash）/发布修订（活跃徽标 + 回滚）三面板 |
| 页面 | `app/flow/page.tsx` / `app/flow/[flowId]/page.tsx` | 列表页（状态徽标、draft 删除、新建对话框生成最小合法骨架）+ 画布编辑器（状态机门控操作栏：校验/提交/发布/退役按 §3.1 前置禁用，published 保存修订=开新 draft 修订） |
| 导航 | `app/layout.tsx` | 侧边栏「治理Flow」入口 |
| 后端加固 | `src/domain/governed_flow/models.py` | **T13**：`MAX_FLOW_NODES=50` / `MAX_FLOW_EDGES=100` 以 `Field(max_length=...)` 落在 `FlowDefinition.nodes/edges`，解析期 422 覆盖全部 12 个入口 |

### 10.2 实现裁决（偏离/细化 §3.3 之处）

1. **画布 data 载荷存完整节点 definition**（非 §3.3 的「只存展示所需子集」）：
   画布节点是唯一事实源，位置与参数就地编辑，`canvasToDefinition` 原位组装
   PUT 载荷——避免页面再持一份节点参数镜像导致双向失同步。定义级字段
   （name/owner/契约/指标产出）仍在页面 state，不进节点 data。
2. **单节点组件 + 类型配置表**：`GovernedFlowNode`（memo）按 `node_type`
   查表取样式/摘要函数/Handle 布局，非 §3.3 设想的每类型一个组件类；
   8 类型共用一套选中/徽标/连线桩逻辑。
3. **边 id 策略**：加载沿用后端 `edge_id`；画布新建边生成
   `e_<base36时间戳>_<序号>`，保存时随 definition 全量提交。
4. **新建 flow 的最小合法结构**：FlowDefinition 要求非空 `nodes`/
   `source_contracts`/`metric_outputs`，列表页新建对话框生成
   source→aggregate→consumer 三节点骨架 + 占位口径句（「请在画布补全并经
   知识签核」），口径句未签核在发布门禁 fail closed（T6 不变）。
5. **T13 未新增错误码**：超限走 Pydantic 422 标准校验错误（issues 随
   `audit_event` 返回），冻结清单维持 24 项不动；前端组件盘同步在
   50 节点禁用添加，给出与后端一致的提前反馈。

### 10.3 验证证据

- 后端：`src/tests/unit/governed_flow/` + API → **98 passed**
  （单元 81 = Phase 1 的 78 + T13 3 例：超限节点拒/超限边拒/50+100 边界过；
  API 17 = 16 + 超限 payload 422）。受影响面回归共 312 passed。
- 前端：新增 16 测（flow-api 7 / 列表页 4 / 编辑器页 5）+ 全量 **436 passed**；
  `tsc --noEmit` 通过；`npm run build` 通过（`/flow` 静态、`/flow/[flowId]` 动态）。
- 活体 E2E（经前端代理全链路）：金标 flow 创建 201 → 校验 0 阻断 →
  提交评审 rev2 → 发布（content_hash + semantic_revision + artifact_hash 落证据）→
  revisions 双修订 → 预览 PG 方言 SQL（`CREATE OR REPLACE VIEW v_flow_* … mz_trade`）→
  回滚切活跃 → 55 节点超限创建 **422**（T13 实测）。
- 真实浏览器（Playwright）：列表页（状态徽标/rev4 发布信息）与编辑器画布
  （5 节点 4 边、组件盘 8 类 + `节点 5/50`、Controls/MiniMap、契约 9 字段、
  4 指标产出携口径句 v4）渲染完整；点击「口径过滤」节点 → 属性面板联动
  切换，5 个过滤条件的操作符/值/值域（MZ_CURE_TYPE）逐项正确；
  `in*` 操作符自动切换逗号分隔输入。§5 陷阱 1-4（具名导入/双桩/边走真实
  浏览器/'use client'）全部按约执行。
- 遗留（Phase 3）：落地视图状态码列类型数值化迁移（DROP+重建）或执行器
  注入 `NULLIF::NUMERIC`；质量门禁运行时执行（勾稽查数）；T11 消费侧
  权限强制；移动端 390px 与键盘全路径矩阵（§5 陷阱 5）。

## 11. Phase 3 落地记录（2026-09-07：受控问数消费契约接线）

兑现 issue #65 验收：**发布后四字段可被 query_planner 和受控问数消费，
结果与既有路径一致**。§10 遗留的「编译产物可部署 / 门禁运行时执行 /
T11 消费侧强制」三项全部落地。

### 11.1 交付物

| 切片 | 内容 | 位置 |
|------|------|------|
| P3a 编译器数值转型 | mz_trade text 落地状态四列（T_State/NP_Settle_State/T_HasRefundmented/T_CureType）数值比较渲染为 `NULLIF(col,'')::NUMERIC`，白名单 `_TEXT_ENCODED_NUMERIC_FIELDS` 按源数据集登记 | `src/domain/governed_flow/compiler.py` |
| P3b 发布部署闭环 | `FlowViewDeployer` 端口 + PG 适配器（经 PostgreSQLClient）+ `get_flow_view_deployer` 工厂；publish **先部署 DDL 再落发布证据**；rollback 重编译目标定义验 artifact_hash（T8）后重部署再切活跃指针 | `flow_ports.py` / `flow_view_deployer.py` / `flow_factory.py` / `flow_service.py` |
| P3c 消费执行器 | `FlowQueryService` + `FlowViewReader` 端口（PG 真读 / 内存 fail-closed）+ `POST /flow/{flow_id}/query`；`FlowQueryResult`/`FlowGateResult` 领域模型；错误码 24→26（新增 `FLOW_ARTIFACT_MISMATCH`、`FLOW_CONSUME_DIMENSION_FORBIDDEN`） | `flow_query_service.py` / `flow_view_reader.py` / `flow_routes.py` / `models.py` |
| P3d 快照 PG 通道修复 | `/semantic/query/processed-snapshot` 弃 SQL Server pyodbc 多源路由，改 `_processed_view_sql`（PG 方言纯函数）+ `_read_processed_view_rows`（PG 读取 seam，测试 monkeypatch 点）；响应结构不变（Portal 卡片无感） | `semantic_routes.py` |
| P3e 活体验证 | 真实 PG 发布→部署→消费三路对数（见 11.3） | 一次性脚本（已删） |

### 11.2 实现裁决

1. **转型在编译期**：NULLIF 转型进入 view_sql 即进入 artifact_hash；
   部署期改写产物会破坏发布证据防篡改锁（T8），禁止。命中条件 =
   源数据集已登记该列 **且** 比较值全为数值；字符串值（`IN ('')`）、
   IS NULL、未登记列、其他数据集同名列一律不转型（`in_or_null` 的
   `IS NULL` 侧保留原列——`NULLIF(col,'') IS NULL` 含空串，语义不同）。
2. **部署顺序 fail closed**：compile → deploy → save revision。部署失败
   无新证据、状态留 pending_review；反向顺序会产生「证据已发布但视图
   不存在」的破契约状态。
3. **消费前防篡改**：每次消费重编译活跃定义并校验 artifact_hash 与
   发布证据一致（T8），不一致 409 `FLOW_ARTIFACT_MISMATCH` 拒止。
4. **白名单边界**：请求指标 ⊆ consumer.consumes（复用
   `FLOW_CONSUMES_UNKNOWN_METRIC`）；请求维度 ⊆ DimensionNode 绑定
   field_codes（T11，新码 `FLOW_CONSUME_DIMENSION_FORBIDDEN`，422）。
   permission_level × 调用方角色的对接是后续接入点，当前边界=绑定白名单。
5. **门禁列随读全口径**：读取列 = 请求列 ∪ 勾稽恒等引用列，出参投影回
   请求列——子集消费不会因未选指标缺列而误判恒等失败。恒等失败返回
   200 + `quality_status=unavailable` + 数值扣发（可审计不报错）；
   空数据集 SUM=NULL 按 0 参与勾稽（0=0+0 口径不破）。
6. **快照直读 PG**：`outpatient_postgres` 从未注册为 SQL Server 源，
   旧通道 live 必 503（测试桩掩盖）；§9 裁决后唯一正确通道是 PG 直读。

### 11.3 验证证据

- 单元/API/Flow：`src/tests/unit/governed_flow/` + flow API 17 +
  lifecycle = **108 passed**（新增部署纪律 4 例：先部署后落证据 / 部署
  失败无证据 / 回滚重部署逐字一致 / 篡改证据拒绝回滚）；消费契约
  `test_flow_query.py` **10 passed**（默认全量+证据回带 / 子集投影 /
  未知指标 422 / T11 越权 422 / 绑定维度放行 / 恒等失败扣发 /
  NULL 过恒等 / 未发布 409 / 篡改证据 409 / 404）；快照
  `test_semantic_processed_snapshot_api.py` **6 passed**（含 PG 方言
  SQL 纯函数断言）。全仓 unit+api 回归 **2855 passed**，4 失败经
  stash 复跑确证为预存（policy 检索 Milvus 数据态 / 脚本作用域 / 
  skill 导入 PG 态），与本切片无关。
- **活体三路对数**（真实 hospital_mcp，一次性脚本）：
  A `POST /flow/{id}/query` == B `/semantic/query/processed-snapshot`
  == C 直接聚合 `public.mz_trade`（口径句 v4 手写 SQL 独立 oracle）：
  12 笔 / 6643.69 / 113.66 / 6530.03 全等；门禁 caliber_signoff +
  identity_assertion 双通过；T11 越权维度与未知指标 live 422。
  发布真实部署 `v_flow_flow_op_outpatient_processed` 至 hospital_mcp。
  **fail closed 实证**：切换迁移前的发布在部署阶段 500，无证据落库、
  状态留 pending_review，二次修复后才成功发布。
- **活库数据修复**：注册中心 mz_trade/mz_fee_item 数据集映射仍为
  §9 前旧登记（`dbo.o_Trade`），对活库执行官方迁移
  `switch_outpatient_query_model_to_postgres`（→ public.* +
  outpatient_postgres）。注意 `ensure_outpatient_query_model` 遇旧名
  即跳过不会自愈——§9 后的环境必须显式跑迁移。

### 11.4 遗留（后续）

- permission_level × 调用方角色的消费侧强制（当前边界=维度绑定白名单）。
- 消费结果的维度值域展示映射（MZ_CURE_TYPE 编码→名称）。
- 活库 op_* 指标 `source_field` 前缀（bjybdb）与种子（outpatient_postgres）
  不一致——快照 `datasource_id` 回显仅装饰性，建议数据治理对齐。
- 移动端 390px 与键盘全路径矩阵（承 §5 陷阱 5，Phase 2 遗留）——已完成，见 §13。

## 12. Phase 3 补全：指标码驱动消费接入点（2026-09-07）

兑现验收总则第二句「四字段可被 **query_planner** 和受控问数消费」中缺失的
query_planner 侧接线：§11 只交付了按 flow_id 的消费通道，消费方（问数 /
query_planner 层）实际只知**语义指标码**、不知 flow_id，缺一个可调用的
契约解析接入点。

### 12.1 交付物

| 切片 | 内容 | 位置 |
|------|------|------|
| 契约解析消费 | `FlowQueryService.query_by_metrics`：指标码（全码 `<object_code>.<短码>` 或短码）→ 解析「已发布 flow 活跃版本中 consumer 契约 consumes ⊇ 请求码」的唯一契约 → 走既有 query() 的 T8/白名单/勾稽门禁链路，不设旁路 | `flow_query_service.py` |
| API | `POST /flow/consume`（body 同 FlowQueryRequest）：无契约 422 `FLOW_CONSUMES_UNKNOWN_METRIC`（错误消息点名未覆盖码）、多契约 409 `FLOW_CONSUME_AMBIGUOUS`（拒绝猜测）、空请求 422 | `flow_routes.py` |
| 错误码 | 26 → 27：`FLOW_CONSUME_AMBIGUOUS`；`FlowConsumeAmbiguousError(FlowStateInvalidError)`，路由映射子类先判 | `models.py` / `flow_routes.py` |
| 附带缺陷修复 | `set_active_revision` 单条多行翻转 `SET is_active = (revision_id = %s)` 在部分唯一索引 `uq_governed_flow_active_revision` 上逐行检查触发瞬态重复（stash 甄别预存，pg_smoke 活库必红）；拆「先撤旧活跃、再启目标」两条语句，瞬态空窗方向安全（消费侧要求活跃存在，空窗即 fail closed） | `flow_postgres.py` |

### 12.2 实现裁决

1. **#36 锚点内核不强改**：`SemanticQuery` 必须携带 `scope.anchor`
   （患者/就诊锚点），是「按实体锚点的受控聚合」内核；op_* 是全局快照
   指标（单行全院口径），强行进入锚点模型会同时扭曲 #36 契约与指标
   语义。裁决：query_planner 侧消费经**消费契约接入点**落地
   （方案文档 §73「published views → query_planner」、#36 定位
   「消费执行内核与安全边界，新增消费契约接入点」），执行必须落到
   已发布语义和消费契约（issue 关键约束原文），而非把快照指标塞进
   SQL 规划器。
2. **解析边界=活跃发布版本**：契约匹配只看 `active.definition`（当前
   flow 定义可能已进入新一轮草稿），与 query() 的消费口径一致。
3. **拒猜纪律**：无契约覆盖 422（点名缺失码）；多个已发布契约覆盖
   同组指标 409 拒绝猜测（不做跨 flow 联邦，那属于新能力）。
4. **全码归一按来源对象域**：`mzjyxx.op_total_fee` → 按该 flow
   SourceNode.object_code 剥前缀归一为契约短码；对象域不符的全码
   保持原样 → 匹配不到契约 → fail closed；裸短码透传。

### 12.3 验证证据

- 先红后绿：`test_flow_query.py` 新增 6 例（全量解析/子集投影/无契约
  422/未发布不构成契约/多契约 409/空请求 422）；冻结清单 26→27 同步。
- 域内回归 273 passed（pg_smoke 修复后转绿）；全仓 unit+api
  **2855 passed**，4 失败与既往甄别清单完全一致（预存）；
  `test_policy_qa_outpatient_settlement_flow` 经干净 worktree（HEAD
  341f4ac）复跑确证预存（答案脱敏断言，数据态类）。
- **活体四路一致**：`POST /flow/consume` 四指标全码 → 解析到
  `flow_op_outpatient_processed` rev2（artifact 85bbe9b1…），
  12 笔 / 6643.69 / 基金 113.66 / 个人 6530.03，与 P3e 三路对数
  （flow/query == processed-snapshot == mz_trade 直聚合）逐值一致，
  双门禁通过；未知指标 live 422、子集投影 live 通过。

## 13. Phase 2 补全：390px 移动端与键盘全路径真实浏览器矩阵（2026-09-07）

承 §11.4 遗留（验收总则第 4 条「1440px、1024px、390px 下画布和详情页可用，
关键操作可键盘完成」）。本节为**真实浏览器矩阵验证记录**，非 UI 重写。

### 13.1 交付物（最小修复）

| 文件 | 改动 |
|------|------|
| `app/flow/page.tsx` | 头部 `flex-wrap` 防挤压；新建对话框 `role=dialog`+`aria-modal`+`aria-label`、`autoFocus` 落 flow_id、Escape 关闭并把焦点归还「新建 Flow」按钮（rAF）、表单栅格 `grid-cols-1 sm:grid-cols-2` |
| `app/flow/[flowId]/page.tsx` | 根容器窄屏内容高度（`md:h-full`）；中段 `flex-col md:flex-row` 堆叠；画布包裹层窄屏 `h-[320px] flex-none`、桌面 `md:h-auto md:flex-1`；属性面板窄屏全宽（`w-full md:w-80`）；`handleNodesChange` 把 XYFlow selection change 同步到属性面板（键盘 Enter 选中节点不经 `onNodeClick`，原实现面板不打开——真浏览器实测确认的键盘断点） |
| `src/components/flow/flow-canvas.tsx` | 根 `flex-col md:flex-row`；节点面板窄屏横向滚动条（`flex-row overflow-x-auto md:flex-col`），按钮 `shrink-0 whitespace-nowrap` |

### 13.2 矩阵验证证据（Playwright 真实浏览器，后端 8178 活库 + portal 3178 dev）

> 环境注记：该浏览器视口按 1.5 反向缩放（DPR 0.667），setViewportSize(260,563)
> 即 CSS 390×844；1024×768 同理换算，均以 `window.innerWidth` 实测复核。

- **1440×900**：列表/编辑器/新建对话框正常；Tab 序 11 站完整
  （收起侧栏→7 导航→后台管理→角色切换→新建 Flow），Enter 开对话框、
  初始焦点 flow_id、Escape 关闭并归还焦点。
- **1024×768（CSS 实测）**：两页 `scrollWidth==clientWidth` 无横向溢出；
  编辑器 aside 320px + 画布 288px（Phase 2 既有布局，未回归）。
- **390×844（CSS 实测）**：两页均无横向溢出；中段 `flex-direction=column`、
  属性面板全宽 320px、节点面板 `flex-direction=row` + `overflow-x=auto`、
  画布包裹层 320px（画布区 247px、节点可见）；`main` 纵向滚动
  （scrollHeight 1887 > clientHeight 789）；侧栏抽屉 Escape 关闭；
  对话框单列（gridTemplateColumns 1 列）、键盘路径与 1440 一致。
- **键盘全路径**：Tab 到画布节点（XYFlow wrapper `tabindex=0`+`role=group`，
  5 节点 + 4 边均可聚焦）→ Enter 选中 → 属性面板打开（`数据源 · src_trade`，
  修复后实测）；编辑页 56 个可聚焦元素、0 个被 inert 阻断；保存/校验/提交/
  发布/退役/预览/页签/回滚均为原生 button（状态门控禁用项按状态机正确禁用，
  草稿态启用路径由组件测试覆盖）。

### 13.3 两个真浏览器才暴露的实现陷阱（jsdom 测不出）

1. **`h-full` 不解析 `min-height` 派生高度**：窄屏根容器改内容高度后，
   画布链上 `height:100%` 失去解析基准 → ReactFlow 视口 0 高。
   修法：窄屏显式 `h-[320px]`。
2. **纵向 flex 中 `flex-1` 的 `flex-basis:0%` 压掉 `height`**：`h-[320px]+flex-1`
   仍 0 高。修法：窄屏 `flex-none`，桌面 `md:flex-1`。
   （断言这两点的组件测试 `flow-editor-page.test.tsx` 同步钉住。）

### 13.4 验证

- 先红后绿：`flow-list-page.test.tsx` +2（对话框键盘、栅格断言）、
  `flow-editor-page.test.tsx` +2（键盘 Enter→面板、窄屏类契约）；
  首轮 3 红（对话框 role/Escape、栅格、编辑页 testid）+ 键盘 Enter 断点 1 红，
  修复后全绿。portal 全量 **440 passed**（61 文件）、`tsc --noEmit` 0 错误。
- 矩阵会话产物（截图/快照）为临时证据未入库，数值结论以本节为准。
