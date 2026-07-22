# Infra Skill Management API Implementation Plan

**Goal:** 基于 `src/skill_infra` 实现研发态技能的列表、详情、路由测试、执行测试接口。

**Architecture:** 
- 创建 `infra_skill_routes.py`
- Pydantic 模型放入 `schemas.py`
- 在 `app.py` 中挂载该路由

**Tech Stack:** FastAPI, Pydantic, pytest

---

### Task 1: 定义 Pydantic Schemas

**Files:**
- Modify: `src/runtime/api/schemas.py`

- [ ] **Step 1: 添加请求和响应模型**
  - `InfraSkillItem` (列表项)
  - `InfraSkillDetailResponse` (含 manifest, readme, files_structure)
  - `SkillRouteTestRequest` / `SkillRouteTestResponse`
  - `SkillExecuteTestRequest` / `SkillExecuteTestResponse`

### Task 2: 实现路由 infra_skill_routes.py

**Files:**
- Create: `src/runtime/api/infra_skill_routes.py`

- [ ] **Step 1: 实现 list_infra_skills()**
  - 调用 `get_loader().get_all()`
- [ ] **Step 2: 实现 get_infra_skill_details()**
  - 组装 `manifest`，读取 `SKILL.md`，使用 `pathlib` 扫描目录结构 (含 `strategies/`)
- [ ] **Step 3: 实现 test_infra_skill_routing()**
  - 调用 `route_question(request.question)`
- [ ] **Step 4: 实现 test_infra_skill_execution()**
  - 调用 `get_assembler(skill_id)`，执行 `execute()`

### Task 3: 注册路由到 FastAPI App

**Files:**
- Modify: `src/runtime/api/app.py`

- [ ] **Step 1: 注册 infra_skill_routes**
  - `app.include_router(infra_skill_routes.router, prefix="/api/v1/medical-insurance-ai-agent", tags=["infra-skills"])`

### Task 4: 编写并运行集成测试

**Files:**
- Create: `src/tests/integration/api/test_infra_skill_routes.py`

- [ ] **Step 1: 编写测试用例**
  - `test_list_infra_skills`
  - `test_get_infra_skill_details`
  - `test_test_infra_skill_routing`
  - `test_test_infra_skill_execution`
- [ ] **Step 2: 运行测试确保全部 PASS**
