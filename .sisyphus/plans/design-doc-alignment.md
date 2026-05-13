# 接口与原型对齐计划：前后端代码修改

## TL;DR

> **目标**: 基于 `docs/steering/接口设计文档.md` 和 `docs/steering/原型设计文档.md`，对齐前后端代码实现
>
> **核心发现**:
> - **后端**: 缺失 45 个 API 端点（17 模型管理 + 28 知识管理），但所有后端存储层均已实现
> - **前端(Admin)**: 知识管理、模型管理页面需重写或扩展，MCP 管理缺能力 CRUD，缺侧边栏
> - **前端(Portal)**: 主要缺 API 数据集成、骨架屏、分页等 UX 完善
>
> **阶段规划**: 后端路由 → Admin 前端重构 → Portal API 集成 → 最终验证

---

## Context

### 原始请求
基于接口设计文档（`docs/steering/接口设计文档.md`）和原型设计文档（`docs/steering/原型设计文档.md`），修改前后端代码，使实现与设计文档对齐。

### 评估结论

**后端现状**:
- ✅ 商业务入口 6/6 已实现、模型测试 2/2 已实现、技能 6/6 已实现、MCP 9/9 已实现
- ❌ 知识管理 28 个端点缺失（所有后端存储已就绪）
- ❌ 模型管理 17 个端点缺失（所有后端服务已就绪）

**前端 Admin 现状**:
- ✅ 技能管理 CRUD 完整
- ✅ MCP 服务器注册 + 健康检查
- ❌ 知识管理：当前为只读浏览（`KnowledgeExplorer`），需重写为 5 子 Tab CRUD 管理
- ❌ 模型管理：当前仅模型测试，缺 3 个子 Tab（配置、路由、Provider）
- ❌ 缺 MCP 能力 CRUD
- ❌ 缺侧边栏导航

**前端 Portal 现状**:
- ✅ SettlementChat（SSE 流式完整）
- ✅ DischargeQC
- ✅ Dashboard
- ❌ SettlementExceptionList 需提取为独立组件
- ❌ 多处使用 Mock 数据（需替换为 API 调用）
- ❌ 缺骨架屏、分页、空状态引导

---

## Execution Strategy

### 阶段一：后端路由补齐

**Task 1: 创建知识管理路由（knowledge_routes.py）**
- 创建 `src/runtime/api/knowledge_routes.py`
- 实现 28 个 CRUD 端点，分为 5 组：
  - 错误码管理 (5 endpoints): GET/POST /knowledge/error-codes, GET/PUT/DELETE /knowledge/error-codes/{error_code}
  - 规则解释管理 (5 endpoints): GET/POST /knowledge/rules, GET/PUT/DELETE /knowledge/rules/{rule_id}
  - 知识资产管理 (7 endpoints): GET/POST /knowledge/assets, GET/PUT/DELETE /knowledge/assets/{asset_id}, GET/POST /knowledge/assets/{asset_id}/chunks
  - 申诉模板管理 (5 endpoints): GET/POST /knowledge/appeal-templates, GET/PUT/DELETE /knowledge/appeal-templates/{template_id}
  - 提示词模板管理 (6 endpoints): GET/POST /knowledge/prompt-templates, GET/PUT/DELETE /knowledge/prompt-templates/{template_id}, POST /knowledge/prompt-templates/render
- 后端存储实现已存在：`PostgresKnowledgeStore`, `PostgresRuleExplanationStore`, `PostgresKnowledgeAssetStore`, `PostgresAppealTemplateStore`, `PostgresPromptTemplateStore`
- 注册路由到 `app.py`

**Task 2: 创建模型管理路由（model_routes.py）**
- 创建 `src/runtime/api/model_routes.py`
- 实现 17 个端点，分为 4 组：
  - 模型配置 (2 endpoints): GET/PUT /model-config
  - 模型路由 (7 endpoints): GET/POST /model-routes, GET/PUT/DELETE /model-routes/{route_id}, GET/PUT /model-routes/fallbacks/{model_name}, GET/PUT /model-routes/params/{model_name}
  - Provider 管理 (6 endpoints): GET/POST /model-providers, GET/PUT/DELETE /model-providers/{provider_id}, POST /model-providers/{provider_id}/test
- 后端服务已存在：`ModelRouter`, `OpenAICompatibleProvider`, `ModelServiceConfig`
- 注册路由到 `app.py`

### 阶段二：Admin 前端 — 知识管理重构

**Task 3: 创建 KnowledgeManagement 组件**
- 替换 `knowledge-explorer.tsx`
- 创建 5 个子 Tab: 错误码 / 规则解释 / 知识资产 / 申诉模板 / 提示词模板
- 使用 Tabs + Dialog 组件

**Task 4-8: 知识管理子组件**
- ErrorCodeCrud: 列表 + 创建/编辑 Dialog + 删除确认
- RuleExplanationCrud: 列表 + 按 scenario 筛选 + 表单
- KnowledgeAssetCrud: 资产列表 + 切片管理子视图
- AppealTemplateCrud: 列表 + JSON 编辑器
- PromptTemplateCrud: 列表 + 渲染预览按钮

### 阶段三：Admin 前端 — 模型管理扩展

**Task 9: 创建 ModelManagement 组件**
- 扩展 `model-test.tsx` 为 4 子 Tab
- 使用 Tabs 导航

**Task 10-12: 模型管理子组件**
- ModelConfigPanel: base_url/timeout/max_retries 表单
- ModelRouteCrud: 路由 CRUD + 退避链 + 参数编辑
- ProviderCrud: Provider CRUD + 连通性测试

### 阶段四：Portal 前端 — API 集成与 UX 完善

**Task 13: 提取 SettlementExceptionList**
- 从 page.tsx 提取为独立组件
- 接入 `GET /workflows?scenario=settlement_exception`

**Task 14: 替换 Mock 数据为 API 调用**
- DischargeQC → `GET /workflows?scenario=pre_discharge_qc`
- Dashboard → 后端聚合统计接口
- 移除 mock-data.ts 回退

**Task 15: 通用 UX 增强**
- 所有列表添加 Skeleton 骨架屏
- 分页组件（每页 20 条）
- 空状态 + 创建引导
- 服务不可用状态页面

---

## TODOs

- [x] 1. **创建知识管理路由 knowledge_routes.py**
  - Category: `unspecified-high`
  - 28 个 CRUD 端点
  - Blocks: Task 3-8 (Admin 前端知识管理依赖后端 API)

- [x] 2. **创建模型管理路由 model_routes.py**
  - Category: `unspecified-high`
  - 17 个 CRUD + test 端点
  - Blocks: Task 9-12 (Admin 前端模型管理依赖后端 API)

- [x] 3. **创建 KnowledgeManagement 组件（Admin 前端）**
  - Category: `visual-engineering`
  - 替换 KnowledgeExplorer，5 子 Tab
  - Depends: Task 1

- [x] 4. **创建 ErrorCodeCrud 子组件**
  - Category: `visual-engineering`
  - 错误码 CRUD 列表 + 创建/编辑/删除

- [x] 5. **创建 RuleExplanationCrud + KnowledgeAssetCrud 子组件**
  - Category: `visual-engineering`
  - 规则解释 + 资产管理的子 Tab

- [x] 6. **创建 AppealTemplateCrud + PromptTemplateCrud 子组件**
  - Category: `visual-engineering`
  - 申诉模板 + 提示词模板的子 Tab

- [x] 7. **创建 ModelManagement 组件（Admin 前端）**
  - Category: `visual-engineering`
  - 扩展 ModelTest，4 子 Tab
  - Depends: Task 2

- [x] 8. **创建 ModelConfigPanel + ModelRouteCrud 子组件**
  - Category: `visual-engineering`
  - 模型配置表单 + 路由管理 CRUD

- [x] 9. **创建 ProviderCrud 子组件**
  - Category: `visual-engineering`
  - Provider CRUD + 连通性测试

- [x] 10. **Admin 前端侧边栏 + MCP 能力 CRUD**
- [x] 11. **Portal: 提取 SettlementExceptionList 组件**
- [x] 12. **Portal: Mock 数据替换 + UX 增强**
  - Category: `visual-engineering`
  - 替换 DischargeQC/Dashboard 中的 Mock 数据
  - 添加骨架屏、分页、空状态、服务不可用状态

---

## Final Verification Wave

- [x] F1. **后端 API 完整性验证** — `oracle` → APPROVE (fix: model router prefix)
- [x] F2. **前端与原型一致性验证** — `visual-engineering` → APPROVE
- [x] F3. **集成测试验证** — `unspecified-high` → APPROVE
- [x] F4. **构建与类型检查** — `quick` → APPROVE (backend imports OK, 38/38 tests pass, Admin/Portal tsc OK)
  Verify: TypeScript build passes, Python type checks pass, no lint errors
  Output: `Build [PASS/FAIL] | TypeCheck [PASS/FAIL] | Lint [PASS/FAIL] | VERDICT`

---

## Success Criteria

- [ ] 后端 67 个设计文档端点全部实现并通过测试
- [ ] Admin 前端知识管理 5 子 Tab CRUD 完整
- [ ] Admin 前端模型管理 4 子 Tab CRUD + 测试完整
- [ ] Admin 前端侧边栏导航、MCP 能力 CRUD
- [ ] Portal 前端 SettlementExceptionList 独立组件 + API 集成
- [ ] Portal 前端 Mock 数据替换为真实 API 调用
- [ ] 骨架屏、分页、空状态、服务不可用状态全覆盖
- [ ] TypeScript 编译无错误
- [ ] Python 测试全部通过

---

## Parallelization Map

```
Wave 1 (Parallel - backend):
├── Task 1: 知识管理路由 (knowledge_routes.py)
└── Task 2: 模型管理路由 (model_routes.py)

Wave 2 (Parallel - admin frontend):
├── Task 3: KnowledgeManagement 组件框架
├── Task 4: ErrorCodeCrud
├── Task 5: RuleExplanationCrud + KnowledgeAssetCrud
├── Task 6: AppealTemplateCrud + PromptTemplateCrud
├── Task 7: ModelManagement 组件框架
├── Task 8: ModelConfigPanel + ModelRouteCrud
└── Task 9: ProviderCrud

Wave 3 (Parallel - integration + portal):
├── Task 10: Admin 侧边栏 + MCP 能力 CRUD
├── Task 11: Portal SettlementExceptionList
└── Task 12: Portal Mock 替换 + UX 增强

Wave FINAL:
├── F1: 后端 API 完整性验证
├── F2: 前端与原型一致性验证
├── F3: 集成测试验证
└── F4: 构建与类型检查
```
