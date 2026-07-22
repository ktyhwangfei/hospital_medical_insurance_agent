# 统一测试口径与风险分级验证矩阵

> 适用范围：`hospital_medical_insurance_agent` 项目  
> 当前状态：v1.0  
> 文档定位：统一项目级测试口径，定义风险分级与最低验证要求的映射  
> 配套文档：`AI-CODING-GOVERNANCE.md` / `AI-CODING-MODULE-BOUNDARIES.md` / `AI-CHANGE-EVIDENCE-TEMPLATE.md`

---

## 1. 文档目的

根 `AGENTS.md` 和 `src/tests/AGENTS.md` 分别定义了不同的测试分层表述，可能造成执行时的口径不一。本文件：

1. **统一测试层级定义**，消除两份文档间的表述差异。
2. **建立风险等级 → 最低验证要求映射**，让不同风险等级的改动有明确的可执行标准。
3. **提供「改了什么 → 该跑哪些测试」速查表**，降低执行门槛。

---

## 2. 统一测试层级（项目唯一口径）

本文件为项目级唯一测试分层定义。其他文档（`AGENTS.md`、`src/tests/AGENTS.md`）若表述不一致，以此处为准。

| 层级 | 名称 | 目录 | 定义 | 依赖 |
|------|------|------|------|------|
| T1 | **单元测试** | `src/tests/unit/` | 纯逻辑验证，不启动 FastAPI，不访问外部服务 | 无 |
| T2 | **集成测试** | `src/tests/integration/` | API 端点（通过 TestClient）+ 业务流程（多端点联动） | 仅内存，无外部依赖 |
| T3 | **性能测试** | `src/tests/performance/` | API 接口压力测试（Locust） | 需启动后端服务 |
| T4 | **E2E 测试** | `src/tests/e2e/` | 前端流程测试（Playwright），含冒烟 + 业务流程 + 跨应用联动 | 需启动后端 + 前端服务 |

其中 T2 集成测试内部又分为两个子层（与根 `AGENTS.md` 中"API 测试 → Flow 测试"的表述一致）：

| 子层 | 目录 | 职责 |
|------|------|------|
| T2a API 端点测试 | `src/tests/integration/api/` | 单端点请求/响应验证、契约校验 |
| T2b Flow 流程测试 | `src/tests/integration/flow/` | 多端点联动的业务场景、状态机路径 |

**说明**：

- 根 `AGENTS.md` 的"单元测试 → API 测试 → Flow 测试"是 T1 + T2 的子集描述，适用于大部分后端改动场景。
- `src/tests/AGENTS.md` 的"单元测试 → 集成测试 → 性能测试 → E2E 测试"是完整的四层表述。
- 本矩阵统一为 T1-T4 四层，其中 T2 = API + Flow。

---

## 3. 风险等级 → 最低验证要求映射

此映射表是**准入性质**的最低门槛，来源于 `AI-CODING-MODULE-BOUNDARIES.md` §6，并在此处细化为可执行命令。

| 风险等级 | 最低验证层级 | 是否必须人工确认边界 | 是否必须提供回滚说明 | 改动后必须执行的验证 |
|----------|-------------|----------------------|----------------------|---------------------|
| **R1**（绿区） | T1 单元测试 | 否 | 建议 | 修改模块对应的单元测试 |
| **R2**（黄区） | T1 + T2（API 或 Flow） | 否（但需审边界） | 建议 | 单元测试 + 对应 API 或 Flow 测试 |
| **R3**（橙区） | T1 + T2a + T2b（全部串行） | **是** | **是** | 单元测试 → API 端点测试 → Flow 流程测试，三步串行全部通过 |
| **R4**（红区） | T1 + T2 + 人工先行设计 | **是** | **是** | 需人工先行设计说明 + 全套对应回归 + 兼容性说明 |

**串行规则**：T1 → T2a → T2b 必须严格按顺序执行，前一步通过后才能进入下一步。任一阶段失败即中止，不执行后续层级。

**跨风险等级的改动**：若一次改动涉及多个风险等级的目录，按最高等级执行。

**高风险动作**：涉及高风险动作、权限、结算、病案、人工确认链路的改动，无论目录风险等级如何，**一律至少按 R3 执行**。

---

## 4. 按目录速查表

以下表格将「改了什么目录」直接映射到「最低该跑哪些测试命令」。

### 4.1 后端模块

| 修改的目录 | 风险等级 | 最低验证命令 |
|-----------|----------|-------------|
| `skills/` | R1 | `python -m pytest src/tests/unit/shared/skills/ -v` |
| `docs/` | R1 | 无自动化测试要求（需人工审内容一致性） |
| `src/observability/` | R2 | `python -m pytest src/tests/unit -v -k "observability"`（若存在对应测试） |
| `src/apps/`（前端） | R2 | `npx playwright test smoke/` |
| `src/skill_infra/` | R3 | `python -m pytest src/tests/unit/shared/skills/ -v` → `python -m pytest src/tests/integration/flow/test_skill_*.py -v` |
| `src/runtime/api/` | R3 | `python -m pytest src/tests/integration/api/test_openapi_contract.py -v` → `python -m pytest src/tests/integration/flow/ -v -k "<相关场景>"` |
| `src/runtime/` 其他模块 | R3 | 对应 `unit/runtime/<子模块>/` → 对应 `integration/flow/test_*` |
| `src/model_service/` | R3 | `python -m pytest src/tests/unit/model_service/ -v` → `python -m pytest src/tests/integration/api/test_model_routes.py -v` |
| `src/knowledge_extension/` | R3 | `python -m pytest src/tests/unit/knowledge_extension/ -v` → `python -m pytest src/tests/integration/api/test_knowledge_routes.py -v` |
| `src/adapters/` | R3 | `python -m pytest src/tests/unit/adapters/ -v` |
| `deploy/` | R3 | 需说明环境影响 + 最小化改动说明 |
| `src/domain/` | R4 | 需人工先行设计 + `python -m pytest src/tests/unit/domain/ -v` |
| `src/data_platform/storage/` | R4 | 需人工先行设计 + `python -m pytest src/tests/unit/data_platform/ -v` |
| `src/config/security_policy/` | R4 | 需人工先行设计 + 安全评审 |
| `src/security/risk_control/` | R4 | 需人工先行设计 + `python -m pytest src/tests/unit/security/ -v` → `python -m pytest src/tests/integration/flow/test_high_risk_*.py -v` |
| `src/security/authorization/` | R4 | 需人工先行设计 + 必须有拒绝路径断言 |
| `src/shared/schemas/` | R4 | 需说明兼容性 + `python -m pytest src/tests/unit/test_tech_debt_fixes.py -v` |

### 4.2 完整模块 ↔ 测试映射（详细版）

> 以下为 `src/tests/AGENTS.md` 已有映射的本文件统一版本，覆盖所有测试层级。

| 修改的模块 | T1 单元测试 | T2a API 测试 | T2b Flow 测试 | T4 E2E 测试 |
|-----------|------------|-------------|--------------|------------|
| `runtime/api/routes.py` | — | `integration/api/test_openapi_contract.py` | `integration/flow/` 全部 | `e2e/flows/portal/chat-streaming.flow.ts` |
| `runtime/api/knowledge_routes.py` | — | `integration/api/test_knowledge_routes.py` | `integration/flow/test_knowledge_extension_runtime.py` | `e2e/flows/admin/knowledge-crud.flow.ts` |
| `runtime/api/model_routes.py` | — | `integration/api/test_model_routes.py` | — | `e2e/flows/admin/model-config.flow.ts` |
| `runtime/api/mcp_routes.py` | — | `integration/api/test_mcp_routes.py` | `integration/flow/test_mcp_runtime_integration.py` | `e2e/flows/admin/mcp-lifecycle.flow.ts` |
| `runtime/api/skill_routes.py` | — | `integration/api/test_skill_routes_api.py` | `integration/flow/test_skill_mention.py` | `e2e/flows/admin/skill-management.flow.ts` |
| `runtime/intent/` | `unit/runtime/intent/` | — | `integration/flow/test_intent_routing.py` | — |
| `runtime/langgraph/` | `unit/runtime/langgraph/` | — | `integration/flow/test_langgraph_e2e_flow.py` | — |
| `runtime/context/` + `runtime/planning/` | `unit/runtime/context/` | — | — | — |
| `runtime/capability_nodes/` | `unit/runtime/test_capability_nodes.py` | — | — | — |
| `runtime/skill_registry/` | `unit/shared/skills/` | — | `integration/flow/test_skill_*.py` | — |
| `model_service/` | `unit/model_service/` | `integration/api/test_model_routes.py` | — | — |
| `knowledge_extension/` | `unit/knowledge_extension/` | `integration/api/test_knowledge_routes.py` | `integration/flow/test_knowledge_extension_runtime.py` | — |
| `data_platform/` | `unit/data_platform/` | — | — | — |
| `security/` | `unit/security/` | — | `integration/flow/test_high_risk_*.py` | — |
| `adapters/` | `unit/adapters/` | — | — | — |
| `domain/` | `unit/domain/` | — | — | — |
| `shared/schemas/` | `unit/test_tech_debt_fixes.py` | — | — | — |
| `shared/skills/` | `unit/shared/skills/` | — | — | — |
| `apps/portal/` | — | — | — | `e2e/smoke/portal-smoke.spec.ts` + `e2e/flows/portal/` |
| `apps/admin/` | — | — | — | `e2e/smoke/admin-smoke.spec.ts` + `e2e/flows/admin/` |
| `apps/embed/` | — | — | — | `e2e/smoke/embed-smoke.spec.ts` + `e2e/flows/cross-app/embed-standalone.flow.ts` |

---

## 5. 场景分类速查

按改动场景而非改动目录来查，更符合日常开发直觉。

| 改动场景 | 风险最低按 | 必须执行的测试 | 可能豁免的测试 |
|----------|-----------|---------------|---------------|
| 新增 skill | R1 | T1（skill 加载器 + assembler） | T3/T4（不涉及后端/前端核心链路） |
| 修改 skill 内部逻辑 | R1 | T1（skill 对应单元测试） | T2/T3/T4 |
| 修复前端展示 bug | R2 | T4（对应页面 smoke 或 flow） | T1/T2/T3（不涉及后端时可豁免） |
| 补可观测性埋点 | R2 | 无自动化测试要求 | T1-T4（但需说明埋点生效链路） |
| 新增 API 端点 | R3 | T1 + T2a + T2b | T3/T4（按需） |
| 修改路由/协议 | R3 | T2a + T2b（全部串行） | T3 |
| 修改编排/工作流 | R3 | T1 + T2b（对应 flow） | T3/T4 |
| 修改模型服务 | R3 | T1 + T2a | T2b/T3/T4 |
| 修改知识检索/MCP | R3 | T1 + T2a + T2b | T3/T4 |
| 修改领域模型 | R4 | 人工设计 → T1 | — |
| 修改存储 Schema | R4 | 人工设计 → T1 → 迁移脚本 | — |
| 修改风控/权限 | R4 | 人工设计 → T1 → T2b | — |
| 修改 API 核心契约 | R4 | 人工设计 → T1 → T2a + T2b | — |

---

## 6. 三个验证口径（按使用场景）

### 6.1 基础准入口径（每次改动必跑）

适用于：任何代码改动提交前。

```
# 按模块运行对应单元测试
python -m pytest src/tests/unit/<模块名> -v --tb=short
```

**最低要求**：改动的模块对应的 T1 单元测试全部通过。

### 6.2 标准回归口径（R2/R3 改动必跑）

适用于：修改 `src/runtime/`、`src/model_service/`、`src/knowledge_extension/` 等 R2+ 目录。

```bash
# 步骤 1：单元测试
python -m pytest src/tests/unit/<模块名> -v --tb=short

# 步骤 2：API 端点测试（步骤 1 通过后）
python -m pytest src/tests/integration/api/<相关测试文件> -v --tb=short

# 步骤 3：Flow 流程测试（步骤 2 通过后）
python -m pytest src/tests/integration/flow/ -v -k "<场景关键词>"
```

**最低要求**：三步全部通过。

### 6.3 完整回归口径（发版前 / 大规模重构时）

适用于：发版前验证、红区改动、横跨多模块的大范围重构。

```bash
# 全部单元测试
python -m pytest src/tests/unit -v --tb=short -x

# 全部 API 端点测试
python -m pytest src/tests/integration/api -v --tb=short

# 全部 Flow 流程测试
python -m pytest src/tests/integration/flow -v --tb=short

# 可选：性能测试（需启动后端服务）
cd src/tests/performance && locust -f locustfile.py --host=http://127.0.0.1:8000 --headless --users 50 --run-time 60s

# 可选：E2E 冒烟测试（需启动全栈服务）
cd src/tests/e2e && npx playwright test smoke/
```

---

## 7. 与 AI 改动证据包模板的对接

本矩阵中的风险等级和验证要求，对应于 `AI-CHANGE-EVIDENCE-TEMPLATE.md` 中以下章节：

| 证据包模板章节 | 本矩阵中的对应内容 |
|---------------|-------------------|
| 一、变更概览 → 风险等级 | §3 风险等级定义 |
| 五、验证说明 → 已执行测试 | §4 按目录速查表 |
| 五、验证说明 → 未执行测试及原因 | §5 场景分类速查（豁免说明） |
| 八、一票否决自检 | §3 跨风险等级规则 |

---

## 8. 常见问题

### Q1：我只改了一个文件的几行代码，也要跑全部 Flow 测试吗？

A：按改动目录查 §4 速查表。如果改动在 R1 区（如 `skills/`），只需跑 T1。如果在 R3 区（如 `runtime/`），必须跑 T1 + T2a + T2b 串行。如果改动确实极小且不影响业务逻辑（如修注释），可在证据包模板中说明豁免理由。

### Q2：单元测试 → API 测试 → Flow 测试的串行顺序能不能跳？

A：不能。这是根 `AGENTS.md` 中的硬性约束。原因：如果单元测试就挂了，继续跑集成测试是浪费时间和掩盖根因。

### Q3：改动同时涉及 R2 和 R3 目录怎么办？

A：按最高等级 R3 执行。这是 §3 的跨风险等级规则。

### Q4：性能测试和 E2E 测试什么时候必须跑？

A：T3（性能测试）和 T4（E2E 测试）在基础准入和标准回归口径中属于**建议但非必须**层级。以下情况**必须**执行：

- T3 性能测试：修改了模型调用链路、API 响应结构、或引入新的数据库查询模式。
- T4 E2E 测试：修改了前端页面路径、流式事件格式、或跨应用交互逻辑。

### Q5：API 测试和 Flow 测试的区别是什么？

A：API 测试（T2a）验证单个端点是否正确返回；Flow 测试（T2b）验证多个端点联动的业务场景是否完整（如"用户发消息 → 意图识别 → 场景执行 → 返回结果"）。

---

## 9. 变更记录

| 版本 | 日期 | 作者 | 说明 |
|------|------|------|------|
| v1.0 | 2026-06-29 | — | 初始版本，统一 AGENTS.md 和 src/tests/AGENTS.md 的测试口径，建立风险分级验证映射 |
