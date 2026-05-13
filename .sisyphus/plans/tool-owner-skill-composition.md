# Tool Ownership + Skill Composition + @-Mention Invocation

## TL;DR

> **Quick Summary**: 为院端医保智能体系统引入 Tool 所有权模型（owner 归属四科室）、Skill 组合编排（多 tools → skill，静态预定义，灵活执行策略）和 @-mention 唤醒机制。意图识别增强为自动匹配可访问 skill，替换现有固定 scenario 路由。
> 
> **Deliverables**:
> - Tool 领域模型 + 数据库持久化 + CRUD API
> - Skill 领域模型（含编排步骤 + 执行策略）+ 数据库持久化 + CRUD API
> - @-mention 解析器（前后端协同）
> - 意图→Skill 自动匹配路由（替换现有 if/elif scenario dispatch）
> - 前端 @-autocomplete 输入组件
> - 前端 Skill 管理 UI（CRUD 界面）
> - 角色化 Tool/Skill 加载
> - 完整自动化测试
> 
> **Estimated Effort**: Large
> **Parallel Execution**: YES - 5 waves
> **Critical Path**: T1(domain models) → T3(storage) → T5(Skill service) → T7(intent→skill routing) → T9(集成测试) → F1-F4

---

## Context

### Original Request
tools 应该配置 owner，分为收费员、医保办、信息科、病案室。不是当前的场景，页面 AI 导办的时候也应该基于 tools 的 owner 进行加载。同时不同的 tools 可以组合成 skill，导办的时候可以通过 @ 方式唤醒 skill 进行调用。

### Interview Summary
**Key Discussions**:
- **Tool Owner 语义**: 管理归属 + 默认权限。owner 表示科室管理归属，同时影响默认访问权限。不同于 required_roles 的精确访问控制
- **Tool 粒度**: Tool = 原子操作（如"查询结算状态"）；Skill = 工具编排（如"结算异常导办" = 查询交易→查错误码→查账单→构建结果）
- **Skill 组合**: 静态预定义。每个 Skill 的 manifest 声明包含哪些 tools 和执行策略（串行/并行/条件分支）
- **Skill Owner**: 单 owner。跨科室通过多 Skill 协作
- **@唤醒**: 输入时实时提示，按 @ 弹出下拉列表显示当前角色可用的 skills
- **默认行为**: 意图识别自动从 skill 注册表匹配可访问 skill 并执行，替换现有固定 scenario 路由
- **存储**: 数据库持久化 + 管理 UI（集成到现有 prototype）
- **测试**: 包含自动化测试

**Research Findings**:
- `McpCapability` 已有 required_roles、supported_scenarios、risk_level — 但无 owner 概念
- 角色模型: 5 个角色（cashier, medical_office, information_department, medical_record_staff, clinician）
- MCP storage 已有 PostgreSQL + in-memory 双模式工厂模式可复用
- 意图路由: 静态 INTENT_REGISTRY + LLM/关键词解析 → scenario_route
- 编排: if/elif dispatch in execute_plan()
- 前端: RoleSwitcher (4 角色), 简单 Input 聊天组件, 无 @-mention

### Metis Review
**Identified Gaps** (addressed):
- Tool 与 McpCapability 关系: Tool 是全新领域模型，McpCapability 保留给 MCP 协议层工具，两者通过 adapter 连接
- 向后兼容: 现有结算异常导办和出院前质控场景迁移为预置 Skill 定义
- 数据库迁移: 复用 MCP storage 的双模式工厂模式（PostgreSQL + in-memory）
- @-mention 解析: 前端提取 skill 引用，后端验证并执行

---

## Work Objectives

### Core Objective
引入 Tool（原子操作）+ Skill（工具编排）两层领域模型，配置 owner 归属科室，通过 @-mention 和意图自动匹配两种方式调用 Skill，替换现有固定 scenario 路由为灵活的 skill 注册表匹配。

### Concrete Deliverables
- `src/domain/tool/` — Tool 领域模型、枚举、仓储接口
- `src/domain/skill/` — Skill 领域模型（含 SkillStep、执行策略枚举）、仓储接口
- `src/data_platform/storage/tool/` — Tool 数据持久化（PostgreSQL + in-memory）
- `src/data_platform/storage/skill/` — Skill 数据持久化（PostgreSQL + in-memory）
- `src/runtime/skill_registry/` — Skill 注册表服务、匹配、执行引擎
- `src/runtime/skill_registry/parser.py` — @-mention 解析
- `src/runtime/intent/skill_matcher.py` — 意图→Skill 自动匹配
- `src/runtime/api/routes.py` — 新增 Tool/Skill CRUD 端点，增强 /chat 流程
- `prototype/src/components/skill-mention-input.tsx` — @-autocomplete 输入组件
- `prototype/src/components/skill-management.tsx` — Skill 管理 UI
- `prototype/src/lib/types.ts` — 新增 Tool/Skill 前端类型
- `prototype/src/lib/api-client.ts` — 新增 API 调用函数
- `src/tests/` — 完整单元测试 + 集成测试
- 数据库迁移脚本（Tool 表、Skill 表、SkillStep 表）

### Definition of Done
- [ ] `python -m pytest src/tests -v` 全部通过
- [ ] `POST /api/v1/medical-insurance-ai-agent/chat` 带 `@skill-name` 消息正确路由到 skill 执行
- [ ] 不带 @ 的消息通过意图识别自动匹配可访问 skill 并执行
- [ ] 角色 X 只能看到和使用 owner=X 或被授权的 skills
- [ ] 前端输入框按 @ 弹出 skill 列表（按角色过滤）
- [ ] 管理 UI 可 CRUD Tool 和 Skill
- [ ] 现有结算异常导办、出院前质控场景迁移为预置 Skill 定义并通过测试

### Must Have
- Tool 领域模型含 owner 字段（Role 枚举值之一）
- Skill 领域模型含 steps 列表 + execution_strategy（SEQUENTIAL / PARALLEL / CONDITIONAL）
- @-mention 前端 autocomplete + 后端解析验证
- 意图识别增强：从 skill 注册表匹配（基于 intent_keywords / description）
- 角色化加载：API 返回的 skills 按 role 过滤（owner 匹配 + required_roles 匹配）
- 预置数据：现有两个业务场景迁移为 skill 定义
- 数据库持久化（复用 MCP 双模式工厂模式）
- 完整自动化测试
- 向后兼容：现有 API 行为不变（/chat 入口、AgentResponse 结构）

### Must NOT Have (Guardrails)
- **不修改 McpCapability 模型** — Tool 是新领域模型，不扩展现有 McpCapability
- **不修改现有 security 模型** — 复用 SCENARIO_ALLOWED_ROLES 逻辑，不重写 authorization
- **不做 Skill 动态组合** — Skill 是静态预定义的，不提供用户运行时自行组合工具的能力
- **不替换 ModelGateway** — Skill 执行引擎调用现有 service 层，不绕过模型服务
- **不过度抽象** — SkillStep 的 input_mapping/output_mapping 保持简单，不做 DSL
- **不加注释** — 遵循项目编码规范：代码不加注释，除非明确要求
- **避免 AI slop** — 不过度泛化（不用泛型仓储），不加 unnecessary Pydantic validator，不用 dict 作返回类型

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES (pytest)
- **Automated tests**: YES (TDD where applicable, tests-after for integration)
- **Framework**: pytest
- **Test location**: `src/tests/`

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Backend API**: Use Bash (curl) - Send requests, assert status + response fields
- **Domain Models**: Use Bash (pytest) - Run tests, assert pass/fail
- **Frontend UI**: Use Playwright - Navigate, interact, assert DOM, screenshot

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Foundation - domain models + storage interfaces):
├── Task 1: Tool domain model + enums [quick]
├── Task 2: Skill domain model + enums [quick]
├── Task 3: Storage interfaces + in-memory impl (Tool) [quick]
├── Task 4: Storage interfaces + in-memory impl (Skill) [quick]
├── Task 5: Role enum unification + owner constants [quick]

Wave 2 (Core services + API):
├── Task 6: Tool CRUD service + API endpoints (depends: 1, 3, 5) [unspecified-high]
├── Task 7: Skill CRUD service + API endpoints (depends: 2, 4, 5) [unspecified-high]
├── Task 8: @-mention parser (depends: 2) [deep]
├── Task 9: Intent→Skill matcher (depends: 2, 5) [deep]
├── Task 10: Skill execution engine (depends: 2, 4, 8) [ultrabrain]

Wave 3 (Chat integration + seed data):
├── Task 11: Enhance /chat route with skill routing (depends: 6-10) [deep]
├── Task 12: Seed data - migrate existing scenarios to skills (depends: 6, 7) [unspecified-high]
├── Task 13: PostgreSQL storage impl for Tool (depends: 3) [unspecified-high]
├── Task 14: PostgreSQL storage impl for Skill (depends: 4) [unspecified-high]

Wave 4 (Frontend):
├── Task 15: Frontend Tool/Skill types + API client (depends: 6, 7) [quick]
├── Task 16: @-mention autocomplete input component (depends: 15) [visual-engineering]
├── Task 17: Skill management UI (CRUD) (depends: 15) [visual-engineering]
├── Task 18: Chat component integration (depends: 16) [visual-engineering]
├── Task 19: Role-based tool/skill display (depends: 17, 18) [quick]

Wave 5 (Integration tests + polish):
├── Task 20: Integration tests - full @-mention flow (depends: 11, 16, 18) [unspecified-high]
├── Task 21: Integration tests - intent→skill auto-matching (depends: 11, 12) [unspecified-high]
├── Task 22: Integration tests - role-based access (depends: 11, 19) [unspecified-high]

Wave FINAL (Verification):
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: Real manual QA (unspecified-high + playwright)
└── F4: Scope fidelity check (deep)
```

### Dependency Matrix

| Task | Depends On | Blocks | Wave |
|------|-----------|--------|------|
| 1 | - | 3, 6 | 1 |
| 2 | - | 4, 7, 8, 9, 10 | 1 |
| 3 | 1 | 6, 13 | 1 |
| 4 | 2 | 7, 10, 14 | 1 |
| 5 | - | 6, 7, 9 | 1 |
| 6 | 1, 3, 5 | 12, 15 | 2 |
| 7 | 2, 4, 5 | 12, 15 | 2 |
| 8 | 2 | 10, 11 | 2 |
| 9 | 2, 5 | 11 | 2 |
| 10 | 2, 4, 8 | 11 | 2 |
| 11 | 6-10 | 20, 21, 22 | 3 |
| 12 | 6, 7 | 21 | 3 |
| 13 | 3 | - | 3 |
| 14 | 4 | - | 3 |
| 15 | 6, 7 | 16, 17, 18, 19 | 4 |
| 16 | 15 | 18, 20 | 4 |
| 17 | 15 | 19 | 4 |
| 18 | 16 | 19, 20 | 4 |
| 19 | 17, 18 | 22 | 4 |
| 20 | 11, 16, 18 | F3 | 5 |
| 21 | 11, 12 | F3 | 5 |
| 22 | 11, 19 | F3 | 5 |

### Agent Dispatch Summary

- **Wave 1**: 5 agents - T1-T5 → `quick`
- **Wave 2**: 5 agents - T6-T7 → `unspecified-high`, T8-T9 → `deep`, T10 → `ultrabrain`
- **Wave 3**: 4 agents - T11 → `deep`, T12 → `unspecified-high`, T13-T14 → `unspecified-high`
- **Wave 4**: 5 agents - T15, T19 → `quick`, T16-T18 → `visual-engineering`
- **Wave 5**: 3 agents - T20-T22 → `unspecified-high`
- **FINAL**: 4 agents - F1 → `oracle`, F2-F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

### Wave 1 — Foundation (domain models + storage interfaces)

- [x] T1. Create Tool domain model with owner support — `src/domain/tool/models.py`
  - Create `src/domain/tool/__init__.py` (empty)
  - Create `src/domain/tool/models.py` with `ToolOwner` StrEnum (`CASHIER`, `MEDICAL_OFFICE`, `INFORMATION_DEPARTMENT`, `MEDICAL_RECORD_STAFF`), `ToolType` StrEnum (`ADAPTER_CALL`, `KNOWLEDGE_RETRIEVAL`, `MCP_TOOL_CALL`, `RESULT_BUILDING`), `Tool` BaseModel (tool_id, name, description, owner: ToolOwner, tool_type: ToolType, capability_ref: str, input_schema: dict, output_schema: dict, risk_level: McpRiskLevel, enabled: bool=True, required_roles: set[str], metadata: dict)
  - Pattern: follow `src/knowledge_extension/mcp_registry/models.py` (Pydantic BaseModel, StrEnum, field_validator)
  - Verify: `python -c "from src.domain.tool.models import Tool, ToolOwner, ToolType"` succeeds

- [x] T2. Create Skill domain model with step orchestration — `src/domain/skill/models.py`
  - Create `src/domain/skill/__init__.py` (empty)
  - Create `src/domain/skill/models.py` with `ExecutionStrategy` StrEnum (`SEQUENTIAL`, `PARALLEL`, `CONDITIONAL`), `SkillStep` BaseModel (step_id, tool_id, input_mapping: dict, output_mapping: dict, condition: str|None, depends_on: list[str]), `Skill` BaseModel (skill_id, name, description, owner: ToolOwner, steps: list[SkillStep], execution_strategy: ExecutionStrategy, intent_keywords: list[str], required_roles: set[str], enabled: bool=True, risk_level: McpRiskLevel, metadata: dict)
  - Pattern: follow `src/runtime/planning/models.py` (PlanStep + ExecutionPlan pattern)
  - Verify: `python -c "from src.domain.skill.models import Skill, SkillStep, ExecutionStrategy"` succeeds

- [x] T3. Create Tool storage port + in-memory implementation — `src/data_platform/storage/tool/`
  - Create `src/data_platform/storage/tool/__init__.py` (empty)
  - Create `src/data_platform/storage/tool/ports.py` with `ToolStorage` Protocol (save_tool, get_tool, list_tools, list_tools_by_owner, delete_tool, health)
  - Create `src/data_platform/storage/tool/in_memory.py` with `InMemoryToolStorage` (follow `src/data_platform/storage/mcp/in_memory.py` pattern exactly: model_copy(deep=True), sorted dict iteration)
  - Create `src/data_platform/storage/tool/factory.py` with `create_tool_storage()` (in-memory default, same pattern as `create_mcp_storage`)
  - Create `src/data_platform/storage/tool/models.py` with `ToolStorageHealth` model (follow `src/data_platform/storage/mcp/models.py`)
  - Verify: `python -c "from src.data_platform.storage.tool.factory import create_tool_storage; s=create_tool_storage(); print(s.health())"` succeeds

- [x] T4. Create Skill storage port + in-memory implementation — `src/data_platform/storage/skill/`
  - Create `src/data_platform/storage/skill/__init__.py` (empty)
  - Create `src/data_platform/storage/skill/ports.py` with `SkillStorage` Protocol (save_skill, get_skill, list_skills, list_skills_by_owner, list_skills_by_role, delete_skill, health)
  - Create `src/data_platform/storage/skill/in_memory.py` with `InMemorySkillStorage` (same pattern as T3)
  - Create `src/data_platform/storage/skill/factory.py` with `create_skill_storage()`
  - Create `src/data_platform/storage/skill/models.py` with `SkillStorageHealth` model
  - Verify: `python -c "from src.data_platform.storage.skill.factory import create_skill_storage; s=create_skill_storage(); print(s.health())"` succeeds

- [x] T5. Unify role enum and owner constants — `src/domain/common/roles.py`
  - Create `src/domain/common/roles.py` with `Role` StrEnum (`CASHIER`, `MEDICAL_OFFICE`, `INFORMATION_DEPARTMENT`, `MEDICAL_RECORD_STAFF`, `CLINICIAN`), `OWNER_ROLES` frozenset (first 4), `ROLE_LABELS` dict mapping role→中文标签
  - Update `src/domain/common/__init__.py` to export Role
  - Update `src/config/security_policy/rules.py` to import Role from `src.domain.common.roles` and use enum values instead of raw strings in `ROLE_VISIBLE_FIELDS` and `SCENARIO_ALLOWED_ROLES` (backward compatible: enum values match existing string keys)
  - Verify: `python -m pytest src/tests -v` still passes (backward compatibility check)

### Wave 2 — Core Services + API

- [x] T6. Tool CRUD service + API endpoints — `src/runtime/skill_registry/tool_service.py` + `src/runtime/api/routes.py`
  - Create `src/runtime/skill_registry/__init__.py` (empty)
  - Create `src/runtime/skill_registry/tool_service.py` with `ToolService` class (create_tool, get_tool, list_tools, list_tools_by_role, update_tool, delete_tool) — delegates to ToolStorage
  - Add API endpoints to `src/runtime/api/routes.py`: `POST /tools`, `GET /tools`, `GET /tools/{tool_id}`, `PUT /tools/{tool_id}`, `DELETE /tools/{tool_id}`, `GET /tools/by-role/{role}`
  - Add request/response schemas to `src/runtime/api/schemas.py`: `ToolCreateRequest`, `ToolUpdateRequest`, `ToolResponse`, `ToolListResponse`
  - Verify: `python -c "from src.runtime.skill_registry.tool_service import ToolService"` succeeds

- [x] T7. Skill CRUD service + API endpoints — `src/runtime/skill_registry/skill_service.py` + `src/runtime/api/routes.py`
  - Create `src/runtime/skill_registry/skill_service.py` with `SkillService` class (create_skill, get_skill, list_skills, list_skills_by_role, update_skill, delete_skill) — delegates to SkillStorage, validates tool_ids exist
  - Add API endpoints: `POST /skills`, `GET /skills`, `GET /skills/{skill_id}`, `PUT /skills/{skill_id}`, `DELETE /skills/{skill_id}`, `GET /skills/by-role/{role}`
  - Add schemas: `SkillCreateRequest`, `SkillUpdateRequest`, `SkillResponse`, `SkillListResponse`, `SkillStepRequest`
  - Verify: `python -c "from src.runtime.skill_registry.skill_service import SkillService"` succeeds

- [ ] T8. @-mention parser — `src/runtime/skill_registry/parser.py`
  - Create `src/runtime/skill_registry/parser.py` with `parse_skill_mentions(message: str) -> list[str]` — extracts `@skill-id` patterns from message (regex: `@([a-z0-9_]+(?:-[a-z0-9_]+)*)`)
  - Create `MentionResult` dataclass: `mentioned_skill_ids: list[str]`, `clean_message: str` (message with @-mentions removed)
  - Create `parse_message(message: str) -> MentionResult` function
  - Verify: `python -c "from src.runtime.skill_registry.parser import parse_message; r=parse_message('@settlement-guide 结算失败'); assert r.mentioned_skill_ids==['settlement-guide']; assert r.clean_message=='结算失败'"` succeeds

- [ ] T9. Intent→Skill auto-matcher — `src/runtime/intent/skill_matcher.py`
  - Create `src/runtime/intent/skill_matcher.py` with `match_skill_by_intent(message: str, role: str, skill_storage: SkillStorage) -> Skill | None` — loads all enabled skills accessible to role, scores each by keyword overlap with message, returns best match (or None)
  - Create `SkillMatchResult` dataclass: `skill: Skill, confidence: float, matched_keywords: list[str]`
  - Scoring: count keyword hits in message, divide by total keywords, threshold 0.3 minimum
  - Verify: unit test with mock storage containing 2 skills, assert correct match for "结算失败怎么办"

- [x] T10. Skill execution engine — `src/runtime/skill_registry/engine.py`
  - Create `src/runtime/skill_registry/engine.py` with `SkillExecutionEngine` class
  - `execute_skill(skill: Skill, context: RuntimeContext, tool_storage: ToolStorage) -> AgentResponse` — orchestrates skill step execution
  - SEQUENTIAL strategy: execute steps in order, pass output as input to next
  - PARALLEL strategy: execute independent steps simultaneously, merge results
  - CONDITIONAL strategy: evaluate condition per step, skip if false
  - Each step delegates to existing business scenario functions via capability_ref (adapter pattern: map tool capability_ref to existing adapter/service calls)
  - High-risk tools → intercept as `waiting_human_confirmation` (reuse existing risk_control)
  - Verify: `python -c "from src.runtime.skill_registry.engine import SkillExecutionEngine"` succeeds

### Wave 3 — Chat Integration + Seed Data

- [x] T11. Enhance /chat route with skill-based routing — `src/runtime/api/routes.py`
  - Modify `process_chat_request()` in routes.py: after blocked action check, try @-mention parse first (`parse_message`); if mentions found, resolve skill via SkillService, validate role access, execute via engine; if no mentions, use `match_skill_by_intent` to find matching skill; if skill found, execute; if no skill found, fall back to existing scenario routing (backward compat)
  - Add `skill_id` field to ChatRequest (optional, for explicit @-mention from frontend)
  - Add `matched_skill` field to AgentResponse audit dict
  - Verify: `python -m pytest src/tests -v` passes; curl with @-mention routes to skill; curl without @ auto-matches

- [x] T12. Seed data — migrate existing scenarios as skill definitions — `src/data_platform/storage/skill/seed.py`
  - Create `src/data_platform/storage/skill/seed.py` with `seed_default_skills(tool_storage, skill_storage)` function
  - Define Tool entries: query_transaction (ADAPTER_CALL, cashier), retrieve_error_code (KNOWLEDGE_RETRIEVAL, medical_office), query_billing_status (ADAPTER_CALL, cashier), query_orders (ADAPTER_CALL, information_department), query_insurance_status (ADAPTER_CALL, medical_office), query_pre_audit (ADAPTER_CALL, medical_office), query_drg_dip (ADAPTER_CALL, medical_office), query_medical_record (ADAPTER_CALL, medical_record_staff), retrieve_rule_explanation (KNOWLEDGE_RETRIEVAL, medical_office), match_mcp_capability (RESULT_BUILDING, information_department), invoke_mcp_tool (MCP_TOOL_CALL, information_department)
  - Define Skill "settlement_exception_guidance" (owner=CASHIER, SEQUENTIAL, steps: query_transaction→retrieve_error_code→query_billing_status→build_result, intent_keywords: ["结算失败","结算异常","医保结算报错"])
  - Define Skill "pre_discharge_quality_control" (owner=MEDICAL_OFFICE, SEQUENTIAL, steps: query_orders→query_insurance_status→query_pre_audit→query_drg_dip→query_medical_record→retrieve_rule_explanation→build_risk_list→create_tasks, intent_keywords: ["出院前","医保风险","质控"])
  - Define Skill "mcp_tool_invocation" (owner=INFORMATION_DEPARTMENT, SEQUENTIAL, steps: match_mcp_capability→invoke_mcp_tool, intent_keywords: ["画图","图表","导出","drawio"])
  - Verify: `python -c "from src.data_platform.storage.skill.seed import seed_default_skills"` succeeds

- [ ] T13. PostgreSQL storage for Tool — `src/data_platform/storage/tool/postgres.py`
  - Create `src/data_platform/storage/tool/postgres.py` with `PostgresToolStorage` class (follow `src/data_platform/storage/mcp/postgres.py` pattern)
  - Add schema migration statements for `tools` table (tool_id PK, name, description, owner, tool_type, capability_ref, input_schema JSONB, output_schema JSONB, risk_level, enabled, required_roles TEXT[], metadata JSONB)
  - Update `src/data_platform/storage/tool/factory.py` to support `postgresql` backend
  - Verify: `python -c "from src.data_platform.storage.tool.postgres import PostgresToolStorage"` succeeds

- [ ] T14. PostgreSQL storage for Skill — `src/data_platform/storage/skill/postgres.py`
  - Create `src/data_platform/storage/skill/postgres.py` with `PostgresSkillStorage` class
  - Add schema migration for `skills` table (skill_id PK, name, description, owner, steps JSONB, execution_strategy, intent_keywords TEXT[], required_roles TEXT[], enabled, risk_level, metadata JSONB)
  - Update `src/data_platform/storage/skill/factory.py` to support `postgresql` backend
  - Verify: `python -c "from src.data_platform.storage.skill.postgres import PostgresSkillStorage"` succeeds

### Wave 4 — Frontend

- [ ] T15. Frontend Tool/Skill types + API client functions — `prototype/src/lib/types.ts` + `prototype/src/lib/api-client.ts`
  - Add to `types.ts`: `ToolOwner` type, `ToolType` type, `ExecutionStrategy` type, `Tool` interface (tool_id, name, description, owner, tool_type, capability_ref, risk_level, enabled, required_roles), `SkillStep` interface, `Skill` interface (skill_id, name, description, owner, steps, execution_strategy, intent_keywords, required_roles, enabled, risk_level), `ToolCreateRequest`, `SkillCreateRequest`, `SkillMentionResult`
  - Add to `api-client.ts`: `fetchTools()`, `fetchToolsByRole(role)`, `createTool(data)`, `updateTool(id, data)`, `deleteTool(id)`, `fetchSkills()`, `fetchSkillsByRole(role)`, `createSkill(data)`, `updateSkill(id, data)`, `deleteSkill(id)`, `sendChatWithMention(request)` — all with mock fallback
  - Verify: `cd prototype && npx tsc --noEmit` passes

- [ ] T16. @-mention autocomplete input component — `prototype/src/components/skill-mention-input.tsx`
  - Create `SkillMentionInput` component: wraps Input, detects `@` keypress, shows autocomplete dropdown with skills filtered by current role, inserts skill_id on selection, highlights @-mentions in input
  - Props: `value`, `onChange`, `onSubmit`, `role`, `skills: Skill[]`, `placeholder`, `disabled`
  - Behavior: type `@` → dropdown appears with filtered skills → arrow keys or click to select → inserts `@skill-id` into input → dropdown closes
  - Pattern: follow existing `src/components/ui/` components (Tailwind CSS, no external deps)
  - Verify: component renders in Storybook or page without errors

- [ ] T17. Skill management UI — `prototype/src/components/skill-management.tsx`
  - Create `SkillManagement` component: tab panel with two sections (Tools / Skills)
  - Tools section: table listing tools with columns (name, owner badge, type, risk_level, enabled toggle), add/edit/delete actions
  - Skills section: table listing skills with columns (name, owner badge, strategy, step count, enabled toggle), add/edit dialog with step builder
  - Add/edit skill dialog: form fields (name, description, owner select, execution_strategy select), step list builder (add/remove/reorder steps, each step selects a tool)
  - Follow existing `mcp-management.tsx` layout patterns (Card, Table, Dialog)
  - Verify: component renders without errors

- [ ] T18. Integrate @-mention input into chat component — `prototype/src/components/settlement-chat.tsx`
  - Replace the existing `<Input>` in settlement-chat.tsx (line 363) with `<SkillMentionInput>`
  - Fetch skills on mount (filtered by current role) via `fetchSkillsByRole(role)`
  - On send: detect @-mentions in input, if present add `mentioned_skill_ids` to ChatRequest
  - Update ChatRequest type to include optional `mentioned_skill_ids: string[]`
  - Verify: chat still works normally; typing @ shows skill dropdown

- [ ] T19. Role-based tool/skill display in management + chat — `prototype/src/components/`
  - Add "Tools" and "Skills" tabs to main page.tsx Tabs component (alongside existing 结算导办, 出院质控, etc.)
  - Skills tab: show SkillManagement component
  - In chat: when role changes, refetch skills filtered by new role
  - Owner badges: show role-colored badge on each tool/skill (reuse RoleSwitcher colors)
  - Verify: switching role updates visible skills; skill management CRUD works

### Wave 5 — Integration Tests

- [ ] T20. Integration tests — @-mention end-to-end flow — `src/tests/integration/test_skill_mention.py`
  - Test: `POST /chat` with `@settlement-exception-guidance 结算失败` returns skill execution result
  - Test: `POST /chat` with `@nonexistent-skill test` returns error/not found
  - Test: `POST /chat` with `@settlement-exception-guidance` by role=medical_record_staff (unauthorized) returns 403
  - Test: multiple @-mentions in single message
  - Verify: `python -m pytest src/tests/integration/test_skill_mention.py -v` passes

- [ ] T21. Integration tests — intent→skill auto-matching — `src/tests/integration/test_skill_intent_matching.py`
  - Test: "结算失败怎么办" auto-matches settlement_exception_guidance skill
  - Test: "出院前检查" auto-matches pre_discharge_quality_control skill
  - Test: "画架构图" auto-matches mcp_tool_invocation skill
  - Test: unrelated message returns not_implemented (backward compat)
  - Test: role=cashier cannot auto-match pre_discharge_quality_control (owned by medical_office, not in required_roles)
  - Verify: `python -m pytest src/tests/integration/test_skill_intent_matching.py -v` passes

- [ ] T22. Integration tests — role-based access control — `src/tests/integration/test_skill_role_access.py`
  - Test: `GET /skills/by-role/cashier` returns only skills where cashier is in required_roles or owner
  - Test: `GET /tools/by-role/medical_office` returns only tools where medical_office is in required_roles or owner
  - Test: `POST /skills` with valid data creates skill
  - Test: `PUT /skills/{id}` updates skill
  - Test: `DELETE /skills/{id}` removes skill
  - Test: create skill with nonexistent tool_id returns validation error
  - Verify: `python -m pytest src/tests/integration/test_skill_role_access.py -v` passes

---

## Final Verification Wave

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `python -m pytest src/tests -v` + check for code smells: bare dict returns, missing __init__.py, unused imports, console.log in frontend, commented-out code. Check AI slop: excessive comments, over-abstraction, generic names.
  Output: `Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high` (+ `playwright` skill)
  Start from clean state. Execute EVERY QA scenario from EVERY task. Test cross-task integration. Test edge cases: empty skill list, invalid @-mention, unauthorized skill access. Save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1. Check "Must NOT do" compliance. Detect cross-task contamination. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

| Wave | Commit Message | Files |
|------|---------------|-------|
| 1 | `feat(domain): add Tool and Skill domain models with owner support` | `src/domain/tool/`, `src/domain/skill/` |
| 1 | `feat(storage): add Tool and Skill storage interfaces with in-memory impl` | `src/data_platform/storage/tool/`, `src/data_platform/storage/skill/` |
| 1 | `feat(config): unify role enum and owner constants` | `src/domain/common/` |
| 2 | `feat(runtime): add Tool and Skill CRUD services and API endpoints` | `src/runtime/skill_registry/`, `src/runtime/api/` |
| 2 | `feat(runtime): add @-mention parser and intent→skill matcher` | `src/runtime/skill_registry/parser.py`, `src/runtime/intent/skill_matcher.py` |
| 2 | `feat(runtime): add skill execution engine` | `src/runtime/skill_registry/engine.py` |
| 3 | `feat(runtime): enhance chat route with skill-based routing` | `src/runtime/api/routes.py` |
| 3 | `feat(data): seed existing scenarios as skill definitions` | `src/data_platform/storage/skill/seed.py` |
| 3 | `feat(storage): add PostgreSQL storage for Tool and Skill` | `src/data_platform/storage/tool/`, `src/data_platform/storage/skill/` |
| 4 | `feat(prototype): add @-mention input and skill management UI` | `prototype/src/components/` |
| 5 | `test: add integration tests for skill-based chat flow` | `src/tests/` |

---

## Success Criteria

### Verification Commands
```bash
python -m pytest src/tests -v  # Expected: all tests pass
curl -X POST http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/chat -H "Content-Type: application/json" -d '{"user_id":"u1","role":"cashier","message":"@settlement-exception-guide 结算失败"}'  # Expected: skill matched and executed
curl -X POST http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/chat -H "Content-Type: application/json" -d '{"user_id":"u1","role":"cashier","message":"结算失败怎么办"}'  # Expected: intent auto-matches settlement skill
curl http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/skills?role=cashier  # Expected: only skills accessible to cashier
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass (`python -m pytest src/tests -v`)
- [ ] @-mention triggers skill execution end-to-end
- [ ] Intent auto-matches skill without @-mention
- [ ] Role-based filtering works for both API and frontend
- [ ] Existing scenarios migrated as seed data and pass tests
- [ ] Frontend @-autocomplete shows role-filtered skills
- [ ] Skill management UI supports CRUD operations
