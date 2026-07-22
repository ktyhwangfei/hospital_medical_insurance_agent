# Skill Management APIs Design Document

**Goal:** 设计“技能列表、技能详情、技能测试、技能相关的接口”，基于真正的底层基础设施 `src/skill_infra` 和 `skills/` 目录结构，为“技能研发与管理后台”提供完整的 API 支持。

**Architecture:**
真正的 Skill 架构采用基于文件系统的动态发现和加载（`SkillLoader` 和 `SkillRouter`）：
- 技能存放在项目根目录的 `skills/` 文件夹中。
- 每个技能是高度结构化、自包含的能力包，包含 `SKILL.md`、`skill_manifest.yaml`、`assembler.py`，以及 `agents/`、`schemas/`、`templates/`、`scripts/`、`references/` 和 `tests/` 等子目录。
- `src/skill_infra/skill_loader.py` 提供了 `get_loader().get_all()` 和 `get()` 方法。
- `src/skill_infra/skill_router.py` 提供了 `route_question()` 和 `get_assembler()`。

本次设计将新增一套 `infra_skill_routes.py` 路由，专门暴露供前端或管理后台查看与测试文件系统级技能的接口。

**Tech Stack:** FastAPI, Pydantic, Python `importlib`, YAML, `pathlib`

---

## 1. 接口设计清单

我们将在 `src/runtime/api/infra_skill_routes.py` 中提供以下端点。

### 1.1 技能列表 (List Skills)
- **Method:** `GET /api/v1/medical-insurance-ai-agent/infra-skills`
- **说明:** 从 `SkillLoader` 加载并返回所有本地发现的技能包基本信息。
- **Response:**
  ```json
  [
    {
      "skill_id": "settlement_explain_skill",
      "skill_name": "政策与费用解释",
      "include_keywords": ["统筹自付", "起付线"],
      "excluded_intents": ["投诉", "退费"]
    }
  ]
  ```
- **核心逻辑:** 调用 `get_loader().get_all()`。

### 1.2 技能详情 (Get Skill Detail)
- **Method:** `GET /api/v1/medical-insurance-ai-agent/infra-skills/{skill_id}`
- **说明:** 获取某个技能的完整“研发态”元数据和结构。包括 `skill_manifest.yaml`、`SKILL.md` 内容，以及子目录结构（特别是 `strategies/` 策略模式的内容）。
- **Response:**
  ```json
  {
    "skill_id": "settlement_explain_skill",
    "skill_name": "政策与费用解释",
    "include_keywords": ["统筹自付", "起付线"],
    "excluded_intents": [],
    "manifest": { ... },
    "readme": "# SKILL.md 内容...",
    "files_structure": {
      "agents": ["openai.yaml"],
      "schemas": ["input.json", "output.json"],
      "templates": ["patient_view.md"],
      "scripts": ["..."],
      "references": ["..."],
      "tests": ["..."],
      "strategies": [
        "base.py",
        "registry.py",
        "pooling_self_pay/",
        "deductible/",
        "large_amount_self_pay/"
      ]
    }
  }
  ```
- **核心逻辑:** 
  1. 调用 `get_loader().get(skill_id)`
  2. 使用 `pathlib` 扫描 `skills/{skill_id}/` 目录，读取 `SKILL.md` 并列出各个子目录的文件结构（特别是对 `strategies/` 目录进行解析展示）。

### 1.3 技能执行测试 (Test Skill Execution)
- **Method:** `POST /api/v1/medical-insurance-ai-agent/infra-skills/{skill_id}/test`
- **说明:** 触发某个技能的 `assembler.execute(...)` 进行真实测试。
- **Request Body:**
  ```json
  {
    "question": "统筹自付怎么算的？",
    "target_fee_item": "pooling_self_pay", // 可选，测试特定的 Strategy
    "context": {
      "patient_id": "P001",
      "encounter_id": "E001"
    },
    "evidence": {}, // 可选，外部提供的规则解释证据
    "status": {} // 可选，数据完备度状态
  }
  ```
- **Response:**
  ```json
  {
    "skill_id": "settlement_explain_skill",
    "status": "success",
    "result": {
      // assembler.execute() 返回的具体内容，通常是一个字典或对象
      "answer": "统筹自付是指...",
      "citations": []
    }
  }
  ```
- **核心逻辑:** 
  1. 调用 `get_assembler(skill_id)`
  2. 调用 `assembler.execute(...)`，传入请求参数
  3. 捕获并包装结果返回

### 1.4 技能路由测试 (Test Skill Routing)
- **Method:** `POST /api/v1/medical-insurance-ai-agent/infra-skills/route-test`
- **说明:** 测试给定一个自然语言问题，系统会将其路由到哪一个技能。
- **Request Body:**
  ```json
  {
    "question": "我的统筹自付为什么这么多？"
  }
  ```
- **Response:**
  ```json
  {
    "question": "我的统筹自付为什么这么多？",
    "matched_skill_id": "settlement_explain_skill"
  }
  ```
- **核心逻辑:** 调用 `route_question(question)`。

## 2. 代码实现计划

1. **新建路由文件**: `src/runtime/api/infra_skill_routes.py`。
2. **注册路由**: 在 `src/runtime/api/app.py` 或 `routes.py` 中引入并注册新的 Router。
3. **实现功能**:
   - `list_infra_skills()`
   - `get_infra_skill_details(skill_id)` -> 增加文件系统扫描逻辑
   - `test_infra_skill_execution(skill_id, payload)`
   - `test_infra_skill_routing(payload)`
4. **Pydantic Schema**: 编写请求和响应结构体验证 (`InfraSkillDetailResponse`, `SkillTestRequest` 等)。
5. **集成测试**: 编写 `src/tests/integration/api/test_infra_skill_routes.py`，测试这 4 个接口。
