# 架构熵增巡检报告 — M1（首次巡检）

**巡检日期**：2026-06-29
**巡检范围**：全项目 `src/` + `skills/` + `docs/`
**执行方式**：5 个 explore agent 并行扫描 + PowerShell 直接检查
**参考模板**：`docs/governance/ARCHITECTURE-ENTROPY-AUDIT.md`

---

## 检查摘要

| 类别 | 检查项数 | 通过 | 发现问题 | 严重度分布 |
|------|---------|------|---------|-----------|
| 3.1 重复路径 | 5 | 3 | 2 | 🟡×1 🔵×1 |
| 3.2 新旧并存 | 6 | 3 | 3 | 🔴×1 🟡×2 |
| 3.3 目录漂移 | 6 | 3 | 3 | 🔴×1 🟡×2 |
| 3.4 跨层调用 | 6 | 5 | 1 | 🔴×1 |
| 3.5 契约漂移 | 5 | 3 | 2 | 🔴×1 🟡×1 |
| 3.6 测试退化 | 8 | 5 | 3 | 🔴×2 🟡×1 |

**合计：发现问题 14 个（🔴 严重 ×6，🟡 一般 ×6，🔵 观察 ×2）**

---

## 严重问题（必须本里程碑修复）

### 🔴 #1 — 5 个路由源文件缺失，22+ API 端点无响应（3.2/3.5）

**发现**：以下 `.py` 源文件已删除，但测试仍在 import，文档仍以它们为参照：

| 缺失文件 | 仅存 .pyc | 影响 |
|----------|----------|------|
| `src/runtime/api/routes.py` | ❌ | `/chat`, `/chat/stream`, `/version`, `/patient-context`, `/workflows`, `/tasks`, `/model-test`, `/tasks/confirm` 等 10+ 端头无 handler |
| `src/runtime/api/model_routes.py` | ✅ | 17 个模型管理端点无 handler |
| `src/runtime/api/mcp_routes.py` | ✅ | 9 个 MCP 端点无 handler |
| `src/runtime/api/skill_routes.py` | ❌ | 6 个技能端点无 handler |
| `src/runtime/api/semantic_mapping_routes.py` | ✅ | 低影响（无测试引用） |

**证据**：
- `tests/integration/api/test_openapi_contract.py:5` 直接 `from src.runtime.api import routes` 将失败
- `tests/integration/api/test_model_routes.py:12` 直接 import 将失败
- `tests/AGENTS.md` 声称 "70/70 = 100% API 覆盖率" — 在源文件缺失的情况下不可能

**修复建议**：从 git 历史恢复缺失文件，或确认功能已退役后同步更新 `tests/` 和 `AGENTS.md`。

---

### 🔴 #2 — 7 处 skills/ 黑名单违规：直接 import src.runtime（3.4）

**发现**：6 个 strategy 文件 + 1 个工具文件从**明确列入黑名单的 `src.runtime`** 导入 `StructuredPolicyQuery`：

| 文件 | 行号 |
|------|------|
| `skills/.../strategies/deductible/strategy.py` | 35 |
| `skills/.../strategies/large_amount_self_pay/strategy.py` | 39 |
| `skills/.../strategies/out_of_scope/strategy.py` | 46-48 |
| `skills/.../strategies/personal_total_pay/strategy.py` | 43 |
| `skills/.../strategies/pooling_payment/strategy.py` | 47-49 |
| `skills/.../strategies/pooling_self_pay/strategy.py` | 40 |
| `skills/.../strategies/semantic_utils.py` | 354 |

**违反了** `SKILL-ISOLATION-DESIGN.md` §3.2 黑名单第 3 条。

**修复建议**：将 `StructuredPolicyQuery` 定义为 `tool_interfaces.py` 中的 `@dataclass` 或 Protocol，strategy 从 `from .tool_interfaces import StructuredPolicyQuery` 导入。

---

### 🔴 #3 — Model_service → Runtime 循环依赖（3.3）

**发现**：`src/model_service/gateway.py:40,45` 延迟导入 `src.runtime.infra_event.context` 和 `src.runtime.infra_event.recorder`，注释明确写道"避免循环依赖"——这本身就确认了双向耦合。

**修复建议**：引入事件总线模式，model_service 只发信号，runtime 层注册监听器。短期方案：将事件记录抽象为独立模块（如 `src/shared/telemetry.py`）。

---

### 🔴 #4 — Security → Runtime 非法依赖（3.3）

**发现**：`src/security/risk_control/service.py` 从 runtime 导入 `runtime_state_store`（第 1 行）、`AgentResponse`（第 6 行）、`create_task`（第 7 行）。Security 是横切关注点，不应依赖 runtime 实现。

**修复建议**：security 层定义 Protocol 接口，runtime 在编排层通过依赖注入提供实现。`AgentResponse` 应通过 `shared/schemas` 共享。

---

### 🔴 #5 — Domain → Knowledge_extension 唯一非法依赖（3.3）

**发现**：`src/domain/skill/models.py:8` 从 `src.knowledge_extension.mcp_registry.models` 导入 `McpRiskLevel`。已在 `src/domain/AGENTS.md` 中标记为"唯一的外部依赖"，但仍属违规。

**修复建议**：将 `McpRiskLevel` 枚举定义移至 `src/shared/schemas/` 或 domain 自身。

---

### 🔴 #6 — Policy QA 测试套件 42% 跳过率（3.6）

**发现**：`test_policy_qa.py` 14/42 跳过（33%），`test_policy_qa_routes.py` 13/22 跳过（59%）。原因均为 `FeeDecompositionSkill`、`QuestionRewriter`、`IntentDetector`、`ExplanationGenerator`、`PolicyQAOrchestrator` "not available"。

**这不是合理跳过**，而是测试架构问题——stub 一直触发 skip 条件，导致近一半测试无效。

**修复建议**：修复 import 链使这些组件在测试环境中可用，或替换为 mock。27 个测试应恢复执行。

---

## 一般问题（下个里程碑修复）

### 🟡 #7 — SSE 事件格式不统一（3.5）

**发现**：存在**三种不兼容的 SSE 事件格式**：

| 来源 | 事件前缀 | 示例 |
|------|---------|------|
| `streaming.py` + `streaming_emitter.py` | `stream:` | `event: stream:step` |
| `langgraph/streaming.py` | `stream:` | `event: stream:error` |
| `policy_qa_routes.py`（自有实现） | 裸名 | `event: step` |

测试 `test_openapi_contract.py` 断言裸名格式，与 `StreamingEmitter` 输出的 `stream:` 前缀格式不一致。

**修复建议**：统一为一种格式。推荐保留 `stream:` 前缀（在 `streaming.py` 常量中定义）。`policy_qa_routes.py` 的自有 `_sse_event()` 改为使用 `streaming.py` 的统一事件常量。

---

### 🟡 #8 — DEPRECATED 模块的 `__init__.py` 仍在重新导出（3.2）

**发现**：
- `src/runtime/orchestration/__init__.py:1` 重新导出 deprecated `execute_plan`
- `src/runtime/planning/__init__.py:1-2` 重新导出 deprecated `build_execution_plan` 和 models

虽然无生产代码通过 `__init__.py` 路径导入（已验证），但重新导出意味着 `from src.runtime.orchestration import execute_plan` 仍能正常工作，存在隐式风险。

**修复建议**：移除 `__init__.py` 中的重新导出，或添加 `__all__` + deprecation 注释。

---

### 🟡 #9 — 两个 PostgreSQLTaskStore 实现并存（3.1）

**发现**：
- `src/data_platform/storage/postgresql/task_store.py:37` — 持久化层版本
- `src/runtime/task_closure/postgresql_store.py:49` — 运行时层版本

同一概念的两个独立实现，接口不同，可能产生分歧。

**修复建议**：保留 `data_platform/` 中的版本（架构上更正确），`runtime/task_closure/` 改为通过端口/适配器模式引用它。

---

### 🟡 #10 — observability/ 和 gateway/ 零测试覆盖（3.6）

**发现**：
- `src/observability/`（3 个源文件）— 无任何测试
- `src/gateway/`（1 个源文件，audit_middleware.py）— 无任何测试
- `src/semantic_layer/`（10 个源文件）— 仅 1 个测试文件覆盖公式评估器

**修复建议**：至少为 `observability/metrics/` 和 `observability/tracing/` 中间件补充单元测试。`gateway/audit_middleware.py` 补充集成测试。

---

### 🟡 #11 — skills/ 中 10 处白名单违规（3.4）

**发现**：除 #2 的 7 处黑名单违规外，skill 中还有 10 处白名单违规——从非标准库、非 skill-local、非 tool_interfaces 的来源导入：

| 违规来源 | 文件数 | 示例 |
|----------|--------|------|
| `src.domain.indicator.models` | 3 | `IndicatorContext`, `MetricFormula` |
| `src.semantic_layer.*` | 5 | `FormulaEvaluator`, `get_normalizer`, `get_registry` |
| `import yaml`（第三方包） | 1 | `base.py:50` |

**修复建议**：将这些类型定义为 `tool_interfaces.py` 中的 Protocol，或将它们声明在 `skill_manifest.yaml` 的 `context_dependencies` 中。`yaml` 需在 manifest 中声明依赖。

---

### 🟡 #12 — `src/semantic_layer/` 未归档模块（3.3）

**发现**：`src/semantic_layer/` 包含 11 个 Python 文件和一个 `AGENTS.md`，但在项目根 `AGENTS.md` 的四层架构描述中**完全未被提及**。Skill 直接依赖它，但它不属于任何已记录的层级。

**修复建议**：在架构文档中正式记录 `semantic_layer` 的定位（建议作为 DaaS 层的子模块或 runtime 层的工具模块），或将其功能迁移到已记录层级中。

---

## 观察项（持续关注）

### 🔵 #13 — 7 个游离测试文件在源码树中（3.6）

**发现**：`src/knowledge_extension/rule_explanation/` 下存在 7 个 `test_*.py` 文件，不在 `src/tests/` 目录中。这些是临时脚本，不会被 pytest 自动发现，可能给人错误的安全感。

---

### 🔵 #14 — 编排器命名繁杂（3.1）

**发现**：`orchestrator.py`、`scenario_executor.py`、`orchestration/service.py`（deprecated）、`planning/service.py`（deprecated）、`policy_qa/orchestrator.py`（undocumented deprecated）、`capability_nodes/executor.py`——6 个编排/执行相关文件分散在 4 个目录中。当前只有 2 个活跃（`orchestrator.py` + `scenario_executor.py`），但未来的开发者很难一眼看清哪条路径是"正确的"。

---

## 通过的检查 ✅

| 检查项 | 结果 |
|--------|------|
| `src/runtime/` 无 HTTP/DB 直接 import | ✅ |
| `skills/` 无 requests/httpx/psycopg2 等库 import | ✅ |
| 无应用源码中的 v2/-old/-new 并存文件 | ✅ |
| adapters/ 无业务逻辑混入 | ✅ |
| 无硬编码报销比例/起付线等业务规则 | ✅ |
| 前端组件无直接调 openai/数据库/权限校验 | ✅ |
| 路由前缀全部以 `/api/v1/medical-insurance-ai-agent` 开头 | ✅ |
| 零 `@pytest.mark.skip` / `# noqa` / flaky 标记 | ✅ |
| 所有 95 个测试文件均包含实际测试函数 | ✅ |
| 零 `@deprecated` 装饰器滥用 | ✅ |

---

## 与上次巡检对比

这是首次巡检，无历史数据可比对。

---

## 优先修复路线

```
本里程碑（必须）：
  ├─ 🔴 #1  恢复或退役 5 个缺失路由文件 + 更新测试
  ├─ 🔴 #2  修复 7 处 skills/ → src.runtime 黑名单违规
  ├─ 🔴 #3  解耦 model_service → runtime 循环依赖
  ├─ 🔴 #4  解耦 security → runtime 非法依赖
  ├─ 🔴 #5  移除 domain → knowledge_extension 依赖
  └─ 🔴 #6  修复 Policy QA 测试 42% 跳过率

下个里程碑：
  ├─ 🟡 #7  统一 SSE 事件格式
  ├─ 🟡 #8  清理 deprecated __init__.py 重新导出
  ├─ 🟡 #9  合并两个 PostgreSQLTaskStore
  ├─ 🟡 #10 补 observability/gateway 测试
  ├─ 🟡 #11 修复 skills/ 白名单违规
  └─ 🟡 #12 归档 semantic_layer 模块

持续关注：
  ├─ 🔵 #13 迁移游离测试文件
  └─ 🔵 #14 收口编排器命名
```
