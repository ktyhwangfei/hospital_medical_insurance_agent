# 实施计划：Business Semantic Registry 前端

## TL;DR

> **快速摘要**：在 portal 应用 `/semantic-layer/` 路由下实施 Business Semantic Registry，采用后端先行策略，先补齐 8 个 API，再构建 6 个前端页面（Dashboard + Domain + Object + Metric Center + Mapping + Discovery）。所有编辑操作收敛到 Object 页面。
> 
> **交付物**：
> - 8 个后端 API（Dashboard 聚合、字段元数据、值域标化、Discovery 扫描）
> - 6 个前端页面 + 布局框架 + 导航
> - 1 个三步映射工坊（Object 页面行内展开）
> - 1 个全局搜索组件（V2）
> 
> **预估工作量**：Medium
> **并行执行**：YES — 4 个 Wave
> **关键路径**：后端 API → 布局框架 → Object 页面 → 其余页面

---

## 上下文

### 原始需求
在现有 portal 应用 `/semantic-layer` 路由下，将简单的实体配置页面升级为完整的 Business Semantic Registry（业务语义资产中心），服务数据架构师、实施工程师、产品经理、AI 研发四类用户。

### 设计规范
完整产品设计规范见：`.sisyphus/drafts/semantic-registry-frontend.md`

### Metis 审查
**识别的缺口**（已解决）：
- 路由策略：使用 `/semantic-layer/` 子路由，新建 layout.tsx 承载顶部 Tab 导航 ✅
- 旧页面处理：保留至新页面验证完成后再清理 ✅
- 深色主题范围：仅限 registry 页面，通过 CSS wrapper class 隔离 ✅
- 存储策略：MVP 使用 InMemoryRegistryStore 扩展，不做 PostgreSQL ✅
- Discovery 扫描：使用 seed/mock 数据，不做真实适配器扫描 ✅

---

## 工作目标

### 核心目标
在 portal 应用的 `/semantic-layer/` 路由下，实现 Business Semantic Registry 的全部 6 个 MVP 页面 + 布局框架。

### 具体交付物
- `src/apps/portal/app/semantic-layer/layout.tsx` — Registry 布局（顶部 Tab 导航 + 深色主题 wrapper）
- `src/apps/portal/app/semantic-layer/page.tsx` — Dashboard
- `src/apps/portal/app/semantic-layer/domain/page.tsx` — Domain 列表
- `src/apps/portal/app/semantic-layer/domain/[domainId]/page.tsx` — Domain 详情
- `src/apps/portal/app/semantic-layer/object/[objectId]/page.tsx` — Object 详情（+ 三步工坊）
- `src/apps/portal/app/semantic-layer/metrics/page.tsx` — Metric Center
- `src/apps/portal/app/semantic-layer/mapping/page.tsx` — Mapping Center
- `src/apps/portal/app/semantic-layer/discovery/page.tsx` — Discovery Center
- 8 个后端 API（`src/runtime/api/semantic_routes.py` 扩展）

### 完成标准
- [ ] 所有 6 个页面可通过导航正常访问
- [ ] Object 页面可完成完整的"添加指标 → 三步映射 → 确认保存"流程
- [ ] Discovery Center 可触发扫描、查看进度、查看结果、快速创建指标
- [ ] 所有页面跳转关系正确（Object ↔ Metric Center ↔ Mapping Center ↔ Discovery）
- [ ] `bun test` 全部通过

### 必须做
- 6 个 MVP 页面完整实现
- 8 个后端 API（MVP）
- Object 页面三步映射工坊（含字段元数据展示、值域标化）
- 深色主题仅限 registry 页面

### 必须不做（护栏）
- ❌ 不改动 portal 全局主题（layout.tsx、sidebar 不做深色改造）
- ❌ 不实现 PostgreSQL RegistryStore（MVP 用 InMemory）
- ❌ 不删除旧 `semantic-layer/page.tsx`（新页面验证后再清理）
- ❌ 不做真实适配器扫描（Discovery 用 seed/mock 数据）
- ❌ 不引入全局状态管理库（用 React useState/useReducer）
- ❌ 不实现 Publish Center（V2）

---

## 验证策略

### 测试决策
- **自动化测试**：None（MVP 阶段聚焦功能实现）
- **Agent 执行 QA**：每个任务含 Agent-Executed QA Scenarios

### QA 策略
每个任务包含 Agent-Executed QA Scenarios，使用以下工具：
- **API 验证**：curl 验证端点响应格式和状态码
- **UI 验证**：Playwright 验证页面渲染、导航、交互
- **组件验证**：bun/node REPL 验证导入和函数签名

---

## 执行策略

### 并行执行 Wave

```
Wave 1（后端 API — 5 个任务并行）：
├── T1: Dashboard 聚合 API (GET /semantic/summary)
├── T2: 字段元数据 API (GET /semantic/field-metadata)
├── T3: 值域标化 API (GET mismatch + POST mapping)
├── T4: Discovery 扫描 API (POST scan + GET status SSE + GET results)
├── T5: Discovery 历史 API (GET /semantic/discovery/history)

Wave 2（布局框架 — 串行，依赖 Wave 1）：
├── T6: Registry 布局 + 路由框架 + 深色主题
├── T7: 全局搜索组件（V2，可与 T6 并行）

Wave 3（前端页面 — 6 个任务，最大并行）：
├── T8: Dashboard 页面
├── T9: Domain 列表 + Domain 详情
├── T10: Object 详情页面 + 三步映射工坊
├── T11: Metric Center 页面
├── T12: Mapping Center 页面
├── T13: Discovery Center 页面

Wave 4（集成验证）：
├── T14: 跨页面跳转验证 + 旧页面清理 + 导航更新
```

关键路径：T1-T5 → T6 → T10 → T14
并行加速：约 60% 效率提升

---

## TODOs

### Wave 1：后端 API（5 个并行任务）

- [x] 1. Dashboard 聚合 API — `GET /semantic/summary`

  **What to do**：
  - 在 `src/runtime/api/semantic_routes.py` 新增 `GET /summary` 端点
  - 返回 Domain/Object/Metric 计数、已映射/未映射统计、Skill 引用数、建设进度百分比
  - 聚合逻辑通过 `SemanticRegistry` store 查询（已有方法 + 新增 query）

  **Must NOT do**：
  - 不做 PostgreSQL 直接查询
  - 不实现时间序列/趋势数据

  **Recommended Agent Profile**：
  - **Category**：`quick` — 单一路由扩展
  - **Skills**：`[]`

  **Parallelization**：
  - **Can Run In Parallel**：YES（T1-T5 全部并行）
  - **Parallel Group**：Wave 1
  - **Blocks**：T8（Dashboard 页面）

  **References**：
  - `src/runtime/api/semantic_routes.py:1-50` — 现有路由注册模式和路径前缀
  - `src/semantic_layer/registry.py` — `SemanticRegistry` 类，已有 get_all_domains()、get_metrics_by_object()
  - `src/semantic_layer/models.py` — 数据模型定义

  **QA Scenarios**：
  ```
  Scenario: 返回完整聚合统计
    Tool: Bash (curl)
    Preconditions: seed 已运行，注册表有数据
    Steps:
      1. curl -s http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/semantic/summary
      2. 验证 JSON 含 domains_count、objects_count、metrics_count、mapped_count
      3. 验证 mapped_count + unmapped_count = metrics_count
    Expected Result: HTTP 200，所有字段为正整数，且等式成立
    Evidence: .sisyphus/evidence/task-1-summary.json
  ```

  **Commit**：YES
  - Message：`feat(semantic): add GET /semantic/summary dashboard endpoint`
  - Files：`src/runtime/api/semantic_routes.py`

- [x] 2. 字段元数据 API — `GET /semantic/field-metadata`

  **What to do**：
  - 新增端点 `GET /semantic/field-metadata?adapter={port}&table={table}`
  - 返回字段列表，每项含 field_name、description、non_null_rate、distinct_count、last_updated、sample_value
  - MVP 使用 seed/mock 数据（InMemory adapter 已知字段）

  **Must NOT do**：不连接真实数据库做实时统计

  **Recommended Agent Profile**：
  - **Category**：`quick`
  - **Skills**：`[]`

  **Parallelization**：
  - **Can Run In Parallel**：YES
  - **Parallel Group**：Wave 1
  - **Blocks**：T10（三步工坊步骤 1）

  **References**：
  - `src/runtime/api/semantic_routes.py` — 路由模式
  - `src/domain/indicator/models.py` — IndicatorSource 字段定义

  **QA Scenarios**：
  ```
  Scenario: 返回字段质量元数据
    Tool: Bash (curl)
    Steps:
      1. curl -s "http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/semantic/field-metadata?adapter=InsuranceInterfacePort&table=yb_settlement"
      2. 验证 fields 数组非空，每项含 field_name、sample_value
    Expected Result: fields.length > 0
    Evidence: .sisyphus/evidence/task-2-field-metadata.json
  ```

  **Commit**：YES
  - Message：`feat(semantic): add GET /semantic/field-metadata endpoint`
  - Files：`src/runtime/api/semantic_routes.py`

- [x] 3. 值域标化 API — `GET mismatch` + `POST mapping`

  **What to do**：
  - `GET /semantic/metrics/{code}/value-mismatch` — 返回指标关联字段在数据库中未标化的值及分布
  - `POST /semantic/value-domain/mapping` — 保存 source_value → standard_value 映射
  - MVP 使用 InMemory 字典数据模拟

  **Must NOT do**：不做真实 SQL 查询

  **Recommended Agent Profile**：
  - **Category**：`quick`
  - **Skills**：`[]`

  **Parallelization**：
  - **Can Run In Parallel**：YES
  - **Parallel Group**：Wave 1
  - **Blocks**：T10（三步工坊步骤 2）、T12（Mapping Center 值域待办）

  **References**：
  - `src/semantic_layer/registry.py` — `normalize_value()` 方法
  - `src/domain/indicator/models.py` — `SemanticMapping`、`ValueDomainMapping` 模型

  **QA Scenarios**：
  ```
  Scenario: 获取未标化值列表
    Tool: Bash (curl)
    Steps:
      1. curl -s http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/semantic/metrics/Settlement.hosp_lv/value-mismatch
      2. 验证返回 JSON 含 source_values 数组
    Expected Result: source_values 数组列出未映射值及出现次数
    Evidence: .sisyphus/evidence/task-3-mismatch.json
  ```

  **Commit**：YES
  - Message：`feat(semantic): add value domain mismatch and mapping endpoints`
  - Files：`src/runtime/api/semantic_routes.py`

- [x] 4. Discovery 扫描 API — `POST scan` + `GET status` + `GET results`

  **What to do**：
  - `POST /semantic/discovery/scan` — 启动异步扫描任务，返回 task_id
  - `GET /semantic/discovery/scan/{task_id}/status` — SSE 推送扫描进度
  - `GET /semantic/discovery/results` — 获取最新扫描结果（未映射字段 + 质量元数据）
  - MVP 使用 InMemory 模拟扫描：遍历已接入表，对比 metric 的 source_field

  **Must NOT do**：
  - 不连真实数据库 schema
  - 不实现并行扫描引擎

  **Recommended Agent Profile**：
  - **Category**：`unspecified-high` — 涉及 SSE + 异步任务
  - **Skills**：`[]`

  **Parallelization**：
  - **Can Run In Parallel**：YES
  - **Parallel Group**：Wave 1
  - **Blocks**：T13（Discovery Center 页面）

  **References**：
  - `src/runtime/api/policy_qa_routes.py` — SSE 流式端点参考模式（StreamingResponse）
  - `src/semantic_layer/registry.py` — 扩展 store 接口

  **QA Scenarios**：
  ```
  Scenario: 触发扫描并查看进度
    Tool: Bash (curl)
    Steps:
      1. curl -s -X POST http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/semantic/discovery/scan
      2. 验证返回 JSON 含 task_id
      3. curl -N http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/semantic/discovery/scan/{task_id}/status
      4. 验证 SSE stream 含 event: progress 和 event: done
    Expected Result: SSE 流包含进度更新和完成事件
    Evidence: .sisyphus/evidence/task-4-scan-sse.txt
  ```

  **Commit**：YES
  - Message：`feat(semantic): add discovery scan API with SSE progress`
  - Files：`src/runtime/api/semantic_routes.py`

- [x] 5. Discovery 历史 API — `GET /semantic/discovery/history`

  **What to do**：
  - 新增端点返回扫描历史列表（时间、范围、结果摘要）
  - MVP 使用 InMemory 列表存储

  **Must NOT do**：不做分页

  **Recommended Agent Profile**：
  - **Category**：`quick`
  - **Skills**：`[]`

  **Parallelization**：
  - **Can Run In Parallel**：YES
  - **Parallel Group**：Wave 1
  - **Blocks**：T13（Discovery Center）

  **QA Scenarios**：
  ```
  Scenario: 返回扫描历史列表
    Tool: Bash (curl)
    Steps:
      1. curl -s http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/semantic/discovery/history
      2. 验证 JSON 为数组，每项含 timestamp、status、summary
    Expected Result: 数组格式，字段完整
    Evidence: .sisyphus/evidence/task-5-history.json
  ```

  **Commit**：YES
  - Message：`feat(semantic): add discovery scan history endpoint`
  - Files：`src/runtime/api/semantic_routes.py`

### Wave 2：布局框架

- [x] 6. Registry 布局 + 路由框架 + 深色主题隔离

  **What to do**：创建 `app/semantic-layer/layout.tsx`（顶部 Tab 导航 Dashboard/Domain/Mapping/Discovery），深色主题通过 `.semantic-registry-dark` CSS class 隔离追加到 globals.css，创建各子路由 page.tsx 骨架。保留旧 page.tsx。

  **Must NOT do**：不改动全局 layout.tsx、不改动 portal 整体亮色主题

  **Category**：`visual-engineering` | **Skills**：`[]`
  **Parallel**：否（Wave 3 全部依赖） | **Blocks**：T7-T12 | **Blocked By**：Wave 1

  **QA Scenarios**：
  ```
  Scenario: 主题隔离验证
    Tool: Playwright
    Steps: /semantic-layer 验证深色背景 → 点击 Domain Tab URL 变化 → / 验证仍为亮色
    Evidence: .sisyphus/evidence/task-6-layout.png
  ```

  **Commit**：`feat(semantic): add registry layout with scoped dark theme`
  - Files：`app/semantic-layer/layout.tsx`、`app/globals.css`

### Wave 3：前端页面（6 个并行任务）

- [x] 7. Dashboard 页面

  **What to do**：`/semantic-layer/page.tsx`：4 张统计卡片 + 建设进度条 + 数据质量 + Skill 排行，数据源 `GET /semantic/summary`，使用 shadcn Progress + Card。

  **Category**：`visual-engineering` | **Skills**：`[]`
  **Parallel**：YES | **Blocked By**：T6

  **QA Scenarios**：
  ```
  Scenario: 数据渲染 → Playwright 导航 /semantic-layer → 验证 4 张卡片有数字
  Evidence: .sisyphus/evidence/task-7-dashboard.png
  ```

  **Commit**：`feat(semantic): implement dashboard page` — `app/semantic-layer/page.tsx`

- [x] 8. Domain 列表 + 详情

  **What to do**：`domain/page.tsx` Card 网格 + `domain/[domainId]/page.tsx` Object 树 + 卡片列表，数据源 `GET /semantic/objects`。

  **Category**：`visual-engineering` | **Skills**：`[]`
  **Parallel**：YES | **Blocked By**：T6

  **QA Scenarios**：
  ```
  Scenario: 导航流程 → /semantic-layer/domain → 点击卡片 → 验证树+列表
  Evidence: .sisyphus/evidence/task-8-domain.png
  ```

  **Commit**：`feat(semantic): implement domain pages` — `app/semantic-layer/domain/page.tsx` + `[domainId]/page.tsx`

- [x] 9. Object 详情 + 三步映射工坊 ⭐

  **What to do**：`object/[objectId]/page.tsx`：Object 信息头 + 指标表格 + 三步工坊行内展开 + 底部折叠。步骤1字段选择（调用 field-metadata），步骤2值域标化（调用 value-mismatch），步骤3确认。筛选：类型/重要性/只看未映射。不用弹窗、不用状态机库。

  **Category**：`unspecified-high` | **Skills**：`[]`
  **Parallel**：YES | **Blocked By**：T6

  **QA Scenarios**：
  ```
  Scenario: 三步工坊 → /semantic-layer/object/Settlement → 编辑未映射指标 → 步骤1→2→3 → 确认保存
  Evidence: .sisyphus/evidence/task-9-workshop.png
  ```

  **Commit**：`feat(semantic): implement object detail with mapping workshop` — `app/semantic-layer/object/[objectId]/page.tsx`

- [x] 10. Metric Center

  **What to do**：`metrics/page.tsx`：统计卡片 + 筛选器 + 指标表格（只读，点击跳转 Object 页面）。筛选：对象/类型/状态/搜索。

  **Category**：`quick` | **Skills**：`[]`
  **Parallel**：YES | **Blocked By**：T6

  **QA Scenarios**：
  ```
  Scenario: 筛选跳转 → /semantic-layer/metrics → 只看未映射 → 点击行 → 跳转 Object
  Evidence: .sisyphus/evidence/task-10-metrics.png
  ```

  **Commit**：`feat(semantic): implement metric center` — `app/semantic-layer/metrics/page.tsx`

- [x] 11. Mapping Center

  **What to do**：`mapping/page.tsx`：数据源概览卡片 + 映射明细 + 值域待办。视图切换：按数据源/按对象/只看未映射。值域待办点击跳转 Object 步骤2。

  **Category**：`quick` | **Skills**：`[]`
  **Parallel**：YES | **Blocked By**：T6

  **QA Scenarios**：
  ```
  Scenario: 值域待办 → /semantic-layer/mapping → 去标化 → 跳转 Object
  Evidence: .sisyphus/evidence/task-11-mapping.png
  ```

  **Commit**：`feat(semantic): implement mapping center` — `app/semantic-layer/mapping/page.tsx`

- [x] 12. Discovery Center

  **What to do**：`discovery/page.tsx`：扫描任务区 + 结果表格 + 字段展开详情 + 快速创建表单 + 扫描历史。SSE 进度展示。字段行展开含值分布 + 快速创建表单。

  **Category**：`unspecified-high` | **Skills**：`[]`
  **Parallel**：YES | **Blocked By**：T6

  **QA Scenarios**：
  ```
  Scenario: 扫描+创建 → /semantic-layer/discovery → 扫描 → 展开字段 → 创建 → 字段消失
  Evidence: .sisyphus/evidence/task-12-discovery.png
  ```

  **Commit**：`feat(semantic): implement discovery center` — `app/semantic-layer/discovery/page.tsx`

### Wave 4：集成验证

- [x] 13. 跨页面跳转验证 + 导航更新

  **What to do**：端到端验证所有页面间跳转、更新 portal 侧边栏入口、验证旧页面不受影响、清理 dead code。

  **Category**：`quick` | **Skills**：`[]`
  **Parallel**：否 | **Blocked By**：T7-T12

  **QA Scenarios**：
  ```
  Scenario: 全链路 → Dashboard→Domain→Object→编辑→跳转Metric/Mapping/Discovery→返回
  Evidence: .sisyphus/evidence/task-13-navigation.png
  ```

  **Commit**：`chore(semantic): verify cross-page links and update navigation`

---

## Final Verification Wave

- [x] F1. **API 完整性审计** — `oracle`
  对所有 8 个 MVP API 端点执行 curl 验证，确认返回格式、状态码、字段完整性。对比设计规范中的 API 需求。
  Output：`APIs [8/8] | PASS/FAIL | VERDICT`

- [x] F2. **页面渲染验证** — `unspecified-high` + `playwright`
  用 Playwright 遍历全部 6 个页面，截图验证渲染正常。验证深色主题隔离（registry 页面深色，portal 首页亮色）。
  Output：`Pages [6/6 rendered] | Theme Isolation [PASS/FAIL] | VERDICT`

- [x] F3. **跳转链路验证** — `unspecified-high`
  验证设计规范中定义的全部跳转关系：Object ↔ Metric Center ↔ Mapping Center ↔ Discovery Center
  Output：`Links [N/N verified] | VERDICT`

- [x] F4. **代码质量审查** — `unspecified-high`
  运行 `npx tsc --noEmit` + ESLint，检查旧代码未受影响（旧 page.tsx 仍存在且可访问）。
  Output：`TS [PASS/FAIL] | Lint [PASS/FAIL] | Old Code [INTACT/MODIFIED] | VERDICT`

---

## 提交策略

| Wave | 任务 | 提交信息 | 文件 |
|------|------|---------|------|
| 1 | T1 | `feat(semantic): add GET /semantic/summary endpoint` | `semantic_routes.py` |
| 1 | T2 | `feat(semantic): add GET /semantic/field-metadata endpoint` | `semantic_routes.py` |
| 1 | T3 | `feat(semantic): add value domain mismatch and mapping endpoints` | `semantic_routes.py` |
| 1 | T4 | `feat(semantic): add discovery scan API with SSE progress` | `semantic_routes.py` |
| 1 | T5 | `feat(semantic): add discovery scan history endpoint` | `semantic_routes.py` |
| 2 | T6 | `feat(semantic): add registry layout with scoped dark theme` | `layout.tsx`, `globals.css` |
| 3 | T7 | `feat(semantic): implement dashboard page` | `page.tsx` |
| 3 | T8 | `feat(semantic): implement domain pages` | `domain/page.tsx`, `[domainId]/page.tsx` |
| 3 | T9 | `feat(semantic): implement object detail with mapping workshop` | `object/[objectId]/page.tsx` |
| 3 | T10 | `feat(semantic): implement metric center page` | `metrics/page.tsx` |
| 3 | T11 | `feat(semantic): implement mapping center page` | `mapping/page.tsx` |
| 3 | T12 | `feat(semantic): implement discovery center page` | `discovery/page.tsx` |
| 4 | T13 | `chore(semantic): verify cross-page links and update navigation` | — |

---

## 成功标准

### 可验证的检查点

```bash
# API 检查
curl -s http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/semantic/summary | python -m json.tool
# 预期：{ domains_count: N, objects_count: N, metrics_count: N, ... }

# 前端检查
cd src/apps/portal && npx tsc --noEmit
# 预期：无类型错误

# 页面访问检查（Playwright）
# 预期：6 个页面均 200，无 404
```

### 最终检查清单
- [ ] 所有 8 个后端 API 可正常调用
- [ ] 所有 6 个前端页面可正常渲染
- [ ] Object 三步映射工坊可完成完整流程
- [ ] Discovery 扫描→创建指针流程可完成
- [ ] 所有跨页面跳转链接正确
- [ ] 深色主题仅限 registry 页面
- [ ] 旧 semantic-layer 页面未受影响
- [ ] TypeScript 编译无错误

