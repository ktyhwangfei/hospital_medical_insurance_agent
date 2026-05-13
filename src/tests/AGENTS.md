# tests/ — 测试套件

## 概述

测试按 **四层金字塔** 组织，从底层到顶层依次为：

| 层级 | 目录 | 职责 | 依赖 |
|------|------|------|------|
| ① 单元测试 | `unit/` | 纯逻辑验证，不启动 FastAPI | 无外部依赖 |
| ② 集成测试 | `integration/` | API 端点 + 业务流程 | 内存运行，无外部依赖 |
| ③ 性能测试 | `performance/` | API 接口压力测试（Locust） | 需启动后端服务 |
| ④ E2E 测试 | `e2e/` | 前端流程测试（Playwright） | 需启动后端 + 前端服务 |

**验证顺序（严格串行）**：单元测试 → 集成测试 → 性能测试 → E2E 测试。前一阶段通过后才能执行下一阶段。

---

## 目录结构

```
tests/
├── conftest.py                              # 全局 fixtures：build_client()
│
├── unit/                                    # ══ ① 单元测试：纯逻辑，不启动 FastAPI ══
│   ├── adapters/
│   │   ├── test_adapter_contracts.py        # AdapterResult 结构 + 内存适配器返回值
│   │   └── test_ports.py                    # 7 个适配器 Protocol 接口签名
│   ├── data_platform/                       # 数据平台层（11 个文件）
│   │   ├── test_cache_contracts.py          # 内存缓存契约
│   │   ├── test_redis_cache_client.py       # Redis 缓存客户端
│   │   ├── test_persistence_contracts.py    # SQL 语句 + 查询结果模型
│   │   ├── test_sql_dialects.py             # PostgreSQL/Kingbase 方言 + UPSERT
│   │   ├── test_database_executor.py        # 数据库执行器
│   │   ├── test_schema_migrator.py          # Schema 迁移器
│   │   ├── test_mcp_storage.py              # MCP 内存存储
│   │   ├── test_mcp_postgres_storage.py     # MCP PostgreSQL 存储
│   │   ├── test_mcp_redis_cache.py          # MCP Redis 缓存
│   │   ├── test_mcp_storage_factory.py      # MCP 存储工厂
│   │   └── test_mcp_storage_health.py       # MCP 存储健康检查
│   ├── domain/
│   │   └── test_domain_and_sample_data.py   # 样例数据 + 安全策略常量
│   ├── knowledge_extension/                 # 知识服务层（14 个文件）
│   │   ├── test_assets.py                   # 知识资产模型
│   │   ├── test_common_models.py            # Citation/Degradation/Visibility
│   │   ├── test_extension_registry.py       # 扩展注册
│   │   ├── test_prompt_templates.py         # 提示词模板
│   │   ├── test_rag.py                      # RAG 检索
│   │   ├── test_rule_explanation.py         # 规则解释
│   │   ├── test_service.py                  # KnowledgeService 门面
│   │   ├── test_mcp_client_gateway.py       # MCP Client Gateway
│   │   ├── test_mcp_config_import.py        # MCP 配置导入
│   │   ├── test_mcp_demo_tools.py           # MCP Demo 工具
│   │   ├── test_mcp_discovery.py            # MCP 工具发现
│   │   ├── test_mcp_registry_models.py      # MCP 注册模型
│   │   ├── test_mcp_registry_service.py     # MCP 注册服务
│   │   └── test_transport.py                # MCP SDK 传输
│   ├── model_service/                       # 模型服务层（4 个文件）
│   │   ├── test_gateway.py                  # ModelGateway
│   │   ├── test_router.py                   # ModelRouter
│   │   ├── test_openai_provider.py          # OpenAI Provider
│   │   └── test_streaming_errors.py         # 流式错误转换
│   ├── runtime/
│   │   ├── intent/                          # 意图识别（5 个文件）
│   │   │   ├── test_intent_models.py        # IntentResult 模型
│   │   │   ├── test_intent_parser.py        # LLM/降级/关键词解析
│   │   │   ├── test_intent_prompts.py       # Prompt 模板
│   │   │   ├── test_intent_registry.py      # 意图注册表
│   │   │   └── test_intent_service_compat.py # 旧版兼容
│   │   ├── langgraph/                       # LangGraph 图（6 个文件）
│   │   │   ├── test_state_types.py          # 状态 TypedDict
│   │   │   ├── test_scenario_nodes.py       # 图节点单元测试
│   │   │   ├── test_settlement_exception.py # 结算异常图
│   │   │   ├── test_pre_discharge_qc.py     # 出院前质控图
│   │   │   ├── test_orchestration_unified.py # 场景分发
│   │   │   └── test_human_confirmation.py   # interrupt/confirm 机制
│   │   ├── context/
│   │   │   └── test_runtime_context_and_planning.py # 上下文+规划
│   │   ├── streaming/
│   │   │   └── test_streaming_events.py     # SSE 事件格式
│   │   ├── test_capability_nodes.py         # 能力节点
│   │   └── test_dependencies.py             # 依赖注入
│   ├── security/
│   │   ├── test_security_policy.py          # 安全策略 CRUD
│   │   ├── test_security_contracts.py       # 安全契约模型
│   │   ├── test_knowledge_extension_security.py # 知识服务安全
│   │   └── test_mcp_security_boundaries.py  # MCP 安全边界
│   ├── shared/skills/                       # 技能加载器（3 个文件）
│   │   ├── test_skill_loader.py             # YAML 解析
│   │   ├── test_skill_registry.py           # SkillRegistry
│   │   └── test_dynamic_addition.py         # 动态添加
│   └── test_tech_debt_fixes.py              # 返回类型契约
│
├── integration/                             # ══ ② 集成测试 ══
│   ├── api/                                 # ── API 端点测试（覆盖全部 70 个端点）──
│   │   ├── test_openapi_contract.py         # /health + /version + OpenAPI 契约 + 流式端点
│   │   ├── test_mcp_management_api.py       # MCP 存储 health + 服务器注册
│   │   ├── test_skill_routes.py             # 技能 CRUD（创建/删除/按角色）
│   │   ├── test_knowledge_routes.py         # ★ 知识管理全 28 端点 CRUD + 过滤 + 404
│   │   ├── test_model_routes.py             # ★ 模型管理全 17 端点（配置/路由/Provider）
│   │   ├── test_mcp_routes.py               # ★ MCP 管理 9 端点全覆盖
│   │   └── test_skill_routes_api.py         # ★ 技能 6 端点完整 CRUD + 404
│   └── flow/                                # ── 流程测试（多端点联动的业务场景）──
│       ├── test_settlement_exception_flow.py # 结算异常导办全流程
│       ├── test_pre_discharge_qc_flow.py    # 出院前质控全流程
│       ├── test_langgraph_e2e_flow.py        # LangGraph 端到端
│       ├── test_intent_routing.py           # 意图路由流程
│       ├── test_skill_intent_matching.py    # 技能关键词匹配流程
│       ├── test_skill_mention.py            # @-mention 技能执行流程
│       ├── test_human_confirmation.py       # 人工确认/拒绝流程
│       ├── test_mcp_runtime_integration.py  # MCP 运行时集成流程
│       ├── test_runtime_execution_loop.py   # 工作流/任务生命周期
│       ├── test_audit_and_degradation.py    # 降级路径流程
│       ├── test_full_mvp_contract.py        # MVP 全链路契约
│       ├── test_knowledge_extension_runtime.py # 知识引用校验流程
│       ├── test_high_risk_and_permission.py # 高风险拦截流程
│       └── test_security_boundaries.py      # 安全边界流程
│
├── performance/                             # ══ ③ 性能测试：API 接口压力测试（Locust） ══
│   ├── conftest.py                          # 性能测试 fixtures：服务健康检查、基线配置
│   ├── locustfile.py                        # Locust 入口：用户行为定义 + 场景注册
│   ├── config.py                            # 性能基线配置：阈值、权重、目标 RPS
│   ├── scenarios/                           # ── 压测场景（按 API 域分组）──
│   │   ├── business_api.py                  # 业务入口压测：/chat、/chat/stream、/patient-context
│   │   ├── knowledge_api.py                 # 知识管理压测：error-codes/rules/assets CRUD
│   │   ├── model_api.py                     # 模型管理压测：config/routes/providers CRUD
│   │   ├── skill_api.py                     # 技能管理压测：skills CRUD + by-role
│   │   └── mcp_api.py                       # MCP 管理压测：servers/capabilities CRUD
│   ├── assertions/                          # ── 自定义断言 ──
│   │   ├── response_time.py                 # 响应时间断言：P50/P95/P99 阈值
│   │   ├── error_rate.py                    # 错误率断言：按端点类别设定容忍阈值
│   │   └── throughput.py                    # 吞吐量断言：最低 RPS 要求
│   └── reports/                             # ── 压测报告（.gitignore）──
│       └── .gitkeep
│
├── e2e/                                     # ══ ④ E2E 测试：前端流程测试（Playwright） ══
│   ├── conftest.py                          # E2E fixtures：浏览器启动、服务就绪等待、Auth
│   ├── playwright.config.ts                 # Playwright 配置：浏览器、超时、重试、baseURL
│   ├── pages/                               # ── Page Object Model ──
│   │   ├── base.page.ts                     # BasePage：通用导航、等待、截图
│   │   ├── portal/                          # Portal 应用页面对象
│   │   │   ├── chat.page.ts                 # Chat 导办页：消息输入、流式响应、引用展示
│   │   │   ├── settlement.page.ts           # 结算异常页：异常查询、导办步骤
│   │   │   ├── qc.page.ts                   # 质控页：质控项列表、联合质控流程
│   │   │   └── dashboard.page.ts            # 运营看板页：图表渲染、数据刷新
│   │   ├── admin/                           # Admin 应用页面对象
│   │   │   ├── mcp.page.ts                  # MCP 管理页：服务器注册、能力列表
│   │   │   ├── knowledge.page.ts            # 知识管理页：CRUD 操作、模板渲染
│   │   │   ├── model.page.ts                # 模型管理页：配置编辑、Provider 测试
│   │   │   └── skills.page.ts               # 技能管理页：技能 CRUD、按角色筛选
│   │   └── embed/                           # Embed 应用页面对象
│   │       └── chat-widget.page.ts          # 嵌入式 Chat Widget：精简对话、上下文传递
│   ├── flows/                               # ── 业务流程测试（跨页面联动）──
│   │   ├── portal/                          # Portal 业务流程
│   │   │   ├── settlement-guide.flow.ts     # 结算异常导办全流程：输入→意图识别→步骤引导
│   │   │   ├── pre-discharge-qc.flow.ts     # 出院前质控流程：患者选择→质控检查→结果确认
│   │   │   └── chat-streaming.flow.ts       # SSE 流式对话流程：输入→流式响应→引用展示→done
│   │   ├── admin/                           # Admin 管理流程
│   │   │   ├── mcp-lifecycle.flow.ts        # MCP 生命周期：注册→发现→调用→删除
│   │   │   ├── knowledge-crud.flow.ts       # 知识管理 CRUD：创建→查询→编辑→删除全链路
│   │   │   ├── model-config.flow.ts         # 模型配置流程：路由配置→Provider 注册→连通测试
│   │   │   └── skill-management.flow.ts     # 技能管理流程：创建→编辑→按角色筛选→删除
│   │   └── cross-app/                       # 跨应用联动流程
│   │       ├── portal-admin-sync.flow.ts    # Portal 使用 Admin 配置的技能/MCP
│   │       └── embed-standalone.flow.ts     # Embed Widget 独立对话流程
│   ├── smoke/                               # ── 冒烟测试（快速验证关键路径）──
│   │   ├── portal-smoke.spec.ts             # Portal 核心页面可达性 + 渲染
│   │   ├── admin-smoke.spec.ts              # Admin 核心页面可达性 + 渲染
│   │   └── embed-smoke.spec.ts              # Embed Widget 加载 + 基础交互
│   └── utils/                               # ── 测试工具函数 ──
│       ├── api-helpers.ts                   # API 状态设置/清理：测试数据预置
│       ├── wait-strategies.ts               # 等待策略：SSE 连接、流式完成、异步渲染
│       └── assertions.ts                    # 自定义断言：流式事件序列、引用格式、脱敏校验
```

---

## 常用命令

### 单元测试 + 集成测试（pytest）

```bash
# 全部测试
python -m pytest src/tests -v

# 按层级运行
python -m pytest src/tests/unit -v                     # 全部单元测试
python -m pytest src/tests/integration/api -v           # 全部 API 端点测试
python -m pytest src/tests/integration/flow -v          # 全部流程测试

# 按模块运行（修改某模块后）
python -m pytest src/tests/unit/model_service -v
python -m pytest src/tests/unit/knowledge_extension -v
python -m pytest src/tests/unit/runtime/langgraph -v
python -m pytest src/tests/unit/security -v
python -m pytest src/tests/unit/data_platform -v
python -m pytest src/tests/unit/runtime/intent -v
python -m pytest src/tests/unit/adapters -v
python -m pytest src/tests/unit/shared -v

# 单文件
python -m pytest src/tests/integration/api/test_knowledge_routes.py -v
python -m pytest src/tests/integration/flow/test_settlement_exception_flow.py -v

# 按关键词
python -m pytest src/tests -v -k "settlement"
python -m pytest src/tests -v -k "knowledge"
```

### 性能测试（Locust）

```bash
# 前置条件：启动后端服务
uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory

# Web UI 模式（推荐，可视化监控）
cd src/tests/performance
locust -f locustfile.py --host=http://127.0.0.1:8000

# 无头模式（CI 环境）
locust -f locustfile.py --host=http://127.0.0.1:8000 \
  --headless --users 50 --spawn-rate 5 --run-time 60s \
  --html reports/report.html

# 按场景运行
locust -f locustfile.py --host=http://127.0.0.1:8000 \
  --tags business          # 仅业务入口压测
locust -f locustfile.py --host=http://127.0.0.1:8000 \
  --tags knowledge         # 仅知识管理压测
locust -f locustfile.py --host=http://127.0.0.1:8000 \
  --tags crud              # 仅 CRUD 操作压测
```

### E2E 测试（Playwright）

```bash
# 前置条件：启动后端 + 前端服务
uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory
cd src/apps/portal && npm run dev    # 端口 3000
cd src/apps/admin  && npm run dev    # 端口 3001
cd src/apps/embed  && npm run dev    # 端口 3002

# 安装 Playwright（首次）
npx playwright install

# 全部 E2E 测试
cd src/tests/e2e
npx playwright test

# 按应用运行
npx playwright test smoke/portal-smoke.spec.ts        # Portal 冒烟
npx playwright test smoke/admin-smoke.spec.ts         # Admin 冒烟
npx playwright test flows/portal/                     # Portal 业务流程
npx playwright test flows/admin/                      # Admin 管理流程
npx playwright test flows/cross-app/                  # 跨应用联动

# 带 UI 模式（调试用）
npx playwright test --ui

# 生成报告
npx playwright show-report

# 仅冒烟测试（快速验证部署可用性）
npx playwright test smoke/
```

---

## 模块 ↔ 测试映射

修改某个模块后，**必须运行对应测试目录，全部通过才算修改完成**。

| 修改的模块 | 对应单元测试 | 对应集成测试 | 对应性能测试 | 对应 E2E 测试 |
|-----------|------------|------------|------------|--------------|
| `runtime/api/routes.py` | — | `integration/api/test_openapi_contract.py` + `integration/flow/` | `performance/scenarios/business_api.py` | `e2e/flows/portal/chat-streaming.flow.ts` |
| `runtime/api/knowledge_routes.py` | — | `integration/api/test_knowledge_routes.py` | `performance/scenarios/knowledge_api.py` | `e2e/flows/admin/knowledge-crud.flow.ts` |
| `runtime/api/model_routes.py` | — | `integration/api/test_model_routes.py` | `performance/scenarios/model_api.py` | `e2e/flows/admin/model-config.flow.ts` |
| `runtime/api/mcp_routes.py` | — | `integration/api/test_mcp_routes.py` | `performance/scenarios/mcp_api.py` | `e2e/flows/admin/mcp-lifecycle.flow.ts` |
| `runtime/api/skill_routes.py` | — | `integration/api/test_skill_routes.py` + `test_skill_routes_api.py` | `performance/scenarios/skill_api.py` | `e2e/flows/admin/skill-management.flow.ts` |
| `runtime/intent/` | `unit/runtime/intent/` | — | — | — |
| `runtime/langgraph/` | `unit/runtime/langgraph/` | `integration/flow/test_langgraph_e2e_flow.py` | — | — |
| `runtime/orchestration/` | `unit/runtime/langgraph/test_orchestration_unified.py` | — | — | — |
| `runtime/context/` + `runtime/planning/` | `unit/runtime/context/` | — | — | — |
| `runtime/capability_nodes/` | `unit/runtime/test_capability_nodes.py` | — | — | — |
| `runtime/skill_registry/` | `unit/shared/skills/` | `integration/flow/test_skill_*.py` | — | — |
| `model_service/` | `unit/model_service/` | `integration/api/test_model_routes.py` | `performance/scenarios/model_api.py` | — |
| `knowledge_extension/` | `unit/knowledge_extension/` | `integration/api/test_knowledge_routes.py` | `performance/scenarios/knowledge_api.py` | — |
| `data_platform/` | `unit/data_platform/` | — | — | — |
| `security/` | `unit/security/` | `integration/flow/test_high_risk_*.py` + `test_security_boundaries.py` | — | — |
| `adapters/` | `unit/adapters/` + `unit/runtime/test_dependencies.py` | — | — | — |
| `domain/` | `unit/domain/` | — | — | — |
| `shared/schemas/` | `unit/test_tech_debt_fixes.py` + `unit/security/test_security_contracts.py` | — | — | — |
| `shared/skills/` | `unit/shared/skills/` | — | — | — |
| `apps/portal/` | — | — | — | `e2e/smoke/portal-smoke.spec.ts` + `e2e/flows/portal/` |
| `apps/admin/` | — | — | — | `e2e/smoke/admin-smoke.spec.ts` + `e2e/flows/admin/` |
| `apps/embed/` | — | — | — | `e2e/smoke/embed-smoke.spec.ts` + `e2e/flows/cross-app/embed-standalone.flow.ts` |

---

## API 接口测试覆盖矩阵

全部 **70 个端点** 的测试覆盖状态。

### 图例
- ✅ = 有 API 级测试（通过 TestClient 调用）

### 业务入口（routes.py — 10 端点）100% ✅

| 方法 | 路径 | 测试文件 |
|------|------|---------|
| GET | `/health` | `api/test_openapi_contract.py` |
| GET | `/version` | `api/test_openapi_contract.py` |
| POST | `/chat` | `flow/test_settlement_exception_flow.py`, `flow/test_intent_routing.py` 等 |
| POST | `/chat/stream` | `api/test_openapi_contract.py` |
| POST | `/tasks/confirm` | `flow/test_human_confirmation.py` |
| GET | `/patient-context/{pid}/{eid}` | `flow/test_security_boundaries.py` |
| GET | `/workflows` | `flow/test_runtime_execution_loop.py` |
| GET | `/workflows/{id}` | `flow/test_runtime_execution_loop.py` |
| GET | `/tasks/{id}` | `flow/test_runtime_execution_loop.py` |
| POST | `/model-test` | `api/test_openapi_contract.py` |
| POST | `/model-test/stream` | `api/test_openapi_contract.py` |

### 技能管理（skill_routes.py — 6 端点）100% ✅

| 方法 | 路径 | 测试文件 |
|------|------|---------|
| POST | `/skills` | `api/test_skill_routes_api.py` |
| GET | `/skills` | `api/test_skill_routes_api.py` |
| GET | `/skills/{skill_id}` | `api/test_skill_routes_api.py` |
| PUT | `/skills/{skill_id}` | `api/test_skill_routes_api.py` |
| DELETE | `/skills/{skill_id}` | `api/test_skill_routes_api.py` |
| GET | `/skills/by-role/{role}` | `api/test_skill_routes_api.py` |

### MCP 管理（mcp_routes.py — 9 端点）100% ✅

| 方法 | 路径 | 测试文件 |
|------|------|---------|
| GET | `/mcp/storage/health` | `api/test_mcp_routes.py` |
| GET | `/mcp/servers` | `api/test_mcp_routes.py` |
| POST | `/mcp/servers` | `api/test_mcp_routes.py` |
| GET | `/mcp/servers/{server_id}` | `api/test_mcp_routes.py` |
| GET | `/mcp/capabilities` | `api/test_mcp_routes.py` |
| POST | `/mcp/capabilities` | `api/test_mcp_routes.py` |
| GET | `/mcp/capabilities/{capability_id}` | `api/test_mcp_routes.py` |
| GET | `/mcp/capabilities/by-server/{server_id}` | `api/test_mcp_routes.py` |
| DELETE | `/mcp/capabilities/{capability_id}` | `api/test_mcp_routes.py` |

### 知识管理（knowledge_routes.py — 28 端点）100% ✅

| 方法 | 路径 | 测试文件 |
|------|------|---------|
| GET/POST | `/knowledge/error-codes` | `api/test_knowledge_routes.py` |
| GET/PUT/DELETE | `/knowledge/error-codes/{error_code}` | `api/test_knowledge_routes.py` |
| GET/POST | `/knowledge/rules` | `api/test_knowledge_routes.py` |
| GET/PUT/DELETE | `/knowledge/rules/{rule_id}` | `api/test_knowledge_routes.py` |
| GET/POST | `/knowledge/assets` | `api/test_knowledge_routes.py` |
| GET/PUT/DELETE | `/knowledge/assets/{asset_id}` | `api/test_knowledge_routes.py` |
| GET/POST | `/knowledge/assets/{asset_id}/chunks` | `api/test_knowledge_routes.py` |
| GET/POST | `/knowledge/appeal-templates` | `api/test_knowledge_routes.py` |
| GET/PUT/DELETE | `/knowledge/appeal-templates/{template_id}` | `api/test_knowledge_routes.py` |
| GET/POST | `/knowledge/prompt-templates` | `api/test_knowledge_routes.py` |
| GET/PUT/DELETE | `/knowledge/prompt-templates/{template_id}` | `api/test_knowledge_routes.py` |
| POST | `/knowledge/prompt-templates/render` | `api/test_knowledge_routes.py` |

### 模型管理（model_routes.py — 17 端点）100% ✅

| 方法 | 路径 | 测试文件 |
|------|------|---------|
| GET/PUT | `/model-config` | `api/test_model_routes.py` |
| GET/POST | `/model-routes` | `api/test_model_routes.py` |
| GET/PUT/DELETE | `/model-routes/{route_id}` | `api/test_model_routes.py` |
| GET/PUT | `/model-routes/fallbacks/{model_name}` | `api/test_model_routes.py` |
| GET/PUT | `/model-routes/params/{model_name}` | `api/test_model_routes.py` |
| GET/POST | `/model-providers` | `api/test_model_routes.py` |
| GET/PUT/DELETE | `/model-providers/{provider_id}` | `api/test_model_routes.py` |
| POST | `/model-providers/{provider_id}/test` | `api/test_model_routes.py` |

---

## 总体覆盖率

| 模块 | 端点数 | API 级测试 |
|------|--------|-----------|
| 业务入口 (routes.py) | 10 | 10 ✅ |
| 技能管理 (skill_routes.py) | 6 | 6 ✅ |
| MCP 管理 (mcp_routes.py) | 9 | 9 ✅ |
| 知识管理 (knowledge_routes.py) | 28 | 28 ✅ |
| 模型管理 (model_routes.py) | 17 | 17 ✅ |
| **合计** | **70** | **70 ✅** |

**API 级测试覆盖率: 70/70 = 100%** ✅

---

## 性能测试覆盖矩阵

### 压测场景与阈值

| API 域 | 场景文件 | 核心端点 | 目标 RPS | P95 响应时间 | 错误率阈值 |
|--------|---------|---------|---------|-------------|-----------|
| 业务入口 | `scenarios/business_api.py` | `/chat`、`/chat/stream`、`/patient-context` | ≥ 10 | ≤ 2s (chat) / ≤ 8s (stream) | ≤ 5% |
| 知识管理 | `scenarios/knowledge_api.py` | error-codes/rules/assets CRUD | ≥ 30 | ≤ 500ms | ≤ 2% |
| 模型管理 | `scenarios/model_api.py` | config/routes/providers CRUD | ≥ 30 | ≤ 500ms | ≤ 2% |
| 技能管理 | `scenarios/skill_api.py` | skills CRUD + by-role | ≥ 30 | ≤ 500ms | ≤ 2% |
| MCP 管理 | `scenarios/mcp_api.py` | servers/capabilities CRUD | ≥ 30 | ≤ 500ms | ≤ 2% |

### 压测负载配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--users` | 50 | 并发虚拟用户数 |
| `--spawn-rate` | 5 | 每秒新增用户数 |
| `--run-time` | 60s | 压测持续时间 |
| `--tags` | 全部 | 按标签过滤场景 |

---

## E2E 测试覆盖矩阵

### 冒烟测试（smoke/）

| 应用 | 测试文件 | 验证内容 |
|------|---------|---------|
| Portal | `smoke/portal-smoke.spec.ts` | Chat 页面加载、消息输入、导航到 settlement/qc/dashboard |
| Admin | `smoke/admin-smoke.spec.ts` | 管理首页加载、导航到 mcp/knowledge/model/skills |
| Embed | `smoke/embed-smoke.spec.ts` | Widget 加载、基础对话交互 |

### 业务流程测试（flows/）

| 应用 | 流程文件 | 验证场景 | 核心断言 |
|------|---------|---------|---------|
| Portal | `flows/portal/settlement-guide.flow.ts` | 结算异常导办全流程 | 意图路由正确、步骤引导完整、citations 存在 |
| Portal | `flows/portal/pre-discharge-qc.flow.ts` | 出院前质控流程 | 质控项加载、联合检查、结果确认 |
| Portal | `flows/portal/chat-streaming.flow.ts` | SSE 流式对话 | step→intent_trace→final→done 事件序列 |
| Admin | `flows/admin/mcp-lifecycle.flow.ts` | MCP 生命周期 | 注册→发现→调用→删除 |
| Admin | `flows/admin/knowledge-crud.flow.ts` | 知识管理 CRUD | 创建→查询→编辑→删除全链路 |
| Admin | `flows/admin/model-config.flow.ts` | 模型配置流程 | 路由配置→Provider 注册→连通测试 |
| Admin | `flows/admin/skill-management.flow.ts` | 技能管理流程 | 创建→编辑→按角色筛选→删除 |
| Cross | `flows/cross-app/portal-admin-sync.flow.ts` | 跨应用联动 | Portal 使用 Admin 配置的技能/MCP |
| Cross | `flows/cross-app/embed-standalone.flow.ts` | Embed 独立对话 | Widget 加载、上下文传递、精简响应 |

---

## 测试编写模式

### API 集成测试
```python
from fastapi.testclient import TestClient
from src.runtime.api.app import create_app

PREFIX = "/api/v1/medical-insurance-ai-agent"

def test_crud():
    client = TestClient(create_app())
    resp = client.post(f"{PREFIX}/knowledge/error-codes", json={...})
    assert resp.status_code == 201
```

### 单元测试
```python
from unittest.mock import patch

@patch('src.runtime.intent.parser.ModelGateway')
def test_fallback(mock_cls):
    mock_cls.return_value.generate.side_effect = TimeoutError('timeout')
```

### LangGraph 测试
```python
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

graph = build_graph(checkpointer=MemorySaver())
result = graph.invoke(inputs, {"configurable": {"thread_id": "test-1"}})
final = graph.invoke(Command(resume={"confirmed": True}), ...)
```

### 性能测试（Locust）

```python
# performance/scenarios/business_api.py
from locust import HttpUser, task, tag

class BusinessAPIUser(HttpUser):
    """业务入口 API 压测用户"""

    # 每个任务间隔 1-3 秒，模拟真实用户思考时间
    wait_time = between(1, 3)

    @task(5)  # 权重 5：最频繁调用
    @tag("business", "chat")
    def chat(self):
        self.client.post(
            "/api/v1/medical-insurance-ai-agent/chat",
            json={
                "message": "P001 患者结算异常",
                "patient_id": "P001",
                "encounter_id": "E001",
                "role": "billing_staff",
            },
            name="/chat",
        )

    @task(3)
    @tag("business", "stream")
    def chat_stream(self):
        with self.client.post(
            "/api/v1/medical-insurance-ai-agent/chat/stream",
            json={"message": "查询质控结果", "role": "doctor"},
            name="/chat/stream",
            stream=True,
        ) as resp:
            # 消费 SSE 流，避免连接堆积
            for line in resp.iter_lines():
                pass

    @task(2)
    @tag("business", "readonly")
    def get_patient_context(self):
        self.client.get(
            "/api/v1/medical-insurance-ai-agent/patient-context/P001/E001",
            name="/patient-context",
        )
```

```python
# performance/assertions/response_time.py
"""自定义响应时间断言 — 在 Locust 事件钩子中使用"""

# 各端点类别的响应时间阈值（毫秒）
THRESHOLDS = {
    "health":        {"p50": 50,   "p95": 100,  "p99": 200},
    "readonly":      {"p50": 100,  "p95": 300,  "p99": 500},
    "crud":          {"p50": 150,  "p95": 500,  "p99": 1000},
    "chat":          {"p50": 500,  "p95": 2000, "p99": 5000},
    "stream":        {"p50": 1000, "p95": 3000, "p99": 8000},
}

# 各端点类别的错误率容忍阈值
ERROR_RATE_TOLERANCE = {
    "health":   0.0,    # 健康检查不允许失败
    "readonly": 0.01,   # 只读接口 ≤ 1%
    "crud":     0.02,   # CRUD 接口 ≤ 2%
    "chat":     0.05,   # Chat 接口（含 LLM）≤ 5%
    "stream":   0.05,   # SSE 流式 ≤ 5%
}
```

### E2E 测试（Playwright + Page Object）

```typescript
// e2e/pages/portal/chat.page.ts — Page Object
import { BasePage } from '../base.page';

export class ChatPage extends BasePage {
  // 定位器
  readonly messageInput = this.page.getByPlaceholder('输入消息...');
  readonly sendButton = this.page.getByRole('button', { name: '发送' });
  readonly responseArea = this.page.locator('[data-testid="chat-response"]');
  readonly streamingIndicator = this.page.locator('[data-testid="streaming"]');
  readonly doneIndicator = this.page.locator('[data-testid="stream-done"]');
  readonly citations = this.page.locator('[data-testid="citation"]');

  async sendMessage(text: string): Promise<void> {
    await this.messageInput.fill(text);
    await this.sendButton.click();
    // 等待流式完成（done 事件）
    await this.doneIndicator.waitFor({ state: 'visible', timeout: 30_000 });
  }

  async waitForStreamingComplete(): Promise<void> {
    await this.streamingIndicator.waitFor({ state: 'hidden', timeout: 60_000 });
  }

  async getResponseText(): Promise<string> {
    return this.responseArea.innerText();
  }

  async hasCitations(): Promise<boolean> {
    return (await this.citations.count()) > 0;
  }
}
```

```typescript
// e2e/flows/portal/settlement-guide.flow.ts — 业务流程测试
import { test, expect } from '@playwright/test';
import { ChatPage } from '../../pages/portal/chat.page';
import { SettlementPage } from '../../pages/portal/settlement.page';
import { waitForAPIReady } from '../../utils/wait-strategies';

test.describe('结算异常导办全流程', () => {
  let chatPage: ChatPage;
  let settlementPage: SettlementPage;

  test.beforeAll(async () => {
    await waitForAPIReady(); // 等待后端就绪
  });

  test.beforeEach(async ({ page }) => {
    chatPage = new ChatPage(page);
    settlementPage = new SettlementPage(page);
    await chatPage.goto();
  });

  test('结算异常查询→导办步骤→引用展示', async () => {
    // 1. 发送结算异常消息
    await chatPage.sendMessage('P001 患者 5月门诊结算被拒付');

    // 2. 验证意图识别正确路由到结算异常场景
    const response = await chatPage.getResponseText();
    expect(response).toContain('结算异常');

    // 3. 验证 AI 输出携带 citations 来源引用
    expect(await chatPage.hasCitations()).toBeTruthy();

    // 4. 导航到结算异常详情页
    await settlementPage.goto();
    await settlementPage.selectPatient('P001', 'E001');
    await settlementPage.verifyExceptionList();
  });

  test('SSE 流式对话完整性', async () => {
    await chatPage.sendMessage('查询 DRG 分组结果');

    // 验证流式事件序列：step → intent_trace → final → done
    await chatPage.waitForStreamingComplete();
    const response = await chatPage.getResponseText();
    expect(response.length).toBeGreaterThan(0);
    expect(response).not.toContain('我无法'); // 不应出现无来源的拒绝
  });
});
```

```typescript
// e2e/flows/admin/mcp-lifecycle.flow.ts — 管理流程测试
import { test, expect } from '@playwright/test';
import { MCPPage } from '../../pages/admin/mcp.page';
import { createTestServer, cleanupTestServer } from '../../utils/api-helpers';

test.describe('MCP 服务器生命周期', () => {
  let mcpPage: MCPPage;

  test.beforeEach(async ({ page }) => {
    mcpPage = new MCPPage(page);
    await mcpPage.goto();
  });

  test('注册→发现→调用→删除', async () => {
    // 1. 注册 MCP 服务器
    await mcpPage.registerServer({
      name: 'test-drg-server',
      transport_type: 'stdio',
      command: 'python',
    });

    // 2. 验证服务器出现在列表
    await expect(mcpPage.getServerRow('test-drg-server')).toBeVisible();

    // 3. 查看服务器能力
    await mcpPage.viewServerCapabilities('test-drg-server');
    await expect(mcpPage.capabilityList).toBeVisible();

    // 4. 删除服务器
    await mcpPage.deleteServer('test-drg-server');
    await expect(mcpPage.getServerRow('test-drg-server')).not.toBeVisible();
  });

  test.afterEach(async () => {
    await cleanupTestServer('test-drg-server');
  });
});
```

---

## 注意事项

### 通用
- 辅助函数 `_make_*()` 定义在测试函数内部
- `HIGH_RISK_ACTIONS` 是 `set`，断言用 `set()` 比较
- 根 `conftest.py` 最小化，仅 `build_client()`
- `create_app()` 是工厂函数，启动 uvicorn 必须加 `--factory`
- 样例数据仅 `P001/E001`，`P002` 触发降级路径
- SSE 流式端点的 `done` 事件标志流结束
- 知识管理路由使用 PostgreSQL 存储，写入操作需数据库实例
- 模型管理路由使用内存存储，测试天然隔离
- `unit/` 和 `integration/` 下的旧目录（`adapters/`、`data_platform/` 等）保留原文件以保证向后兼容

### 性能测试（performance/）
- **必须先启动后端服务**：性能测试通过真实 HTTP 请求访问运行中的服务
- **基线阈值**：所有阈值定义在 `performance/config.py`，修改前需确认团队共识
- **场景隔离**：每个场景文件独立运行，避免场景间干扰
- **报告归档**：压测报告输出到 `performance/reports/`（已 .gitignore）
- **CI 集成**：无头模式下运行，失败阈值通过 `--tags` 和配置文件控制
- **禁止 Mock**：性能测试直接调用真实服务，不使用 Mock

### E2E 测试（e2e/）
- **必须启动全栈服务**：后端 + 三个前端应用均需运行
- **Page Object 模式**：所有页面交互通过 `pages/` 下的 Page Object 封装，测试文件禁止直接使用 Playwright 选择器
- **服务就绪等待**：`conftest.py` 中通过健康检查端点等待后端就绪，避免启动时序问题
- **测试数据管理**：通过 `utils/api-helpers.ts` 预置/清理测试数据，每个测试保持独立性
- **SSE 等待策略**：流式对话使用 `wait-strategies.ts` 中封装的等待函数，不使用硬编码 `sleep`
- **浏览器配置**：`playwright.config.ts` 统一配置浏览器类型、视口大小、超时时间
- **截图与 Trace**：失败时自动截图 + 录制 Trace，存放于 `test-results/`（已 .gitignore）
- **跨应用测试**：`flows/cross-app/` 下的测试需同时启动 Portal + Admin + Embed
