# FeeExplain Skill LLM 化改造 — 工作执行计划

## TL;DR

> **核心目标**: 将 `PoolingSelfPayStrategy` 的答案生成从硬编码 Python 模板替换为 LLM 生成，通过前端 display 配置驱动展示（单次解释 + 多次对比），验证"Business Fact JSON + Prompt → LLM → 校验"全链路闭环。
>
> **交付物**:
> - `fact_builder.py` + `prompt_template.yaml` + `output_parser.py`（3 个新组件）
> - 改造 `PoolingSelfPayStrategy`（LLM 调用替代 150 行硬编码）
> - 配置 `fee_explanation` scene（model_service 路由）
> - 前端 display 配置驱动渲染（single + compare 模式）
> - 更新测试（结构测试替换字符串断言）
>
> **估时**: 12~16 小时 | **并行**: YES — 6 波 | **关键路径**: T1→T4→T12→T15→T20

---

## Context

### Original Request
将 FeeExplain Skill 全链路改造为 LLM 驱动：Strategy 不再手写模板，改为构建 Business Fact JSON → 注入 Prompt 模板 → LLM 生成解释 → 校验输出。前端按 Skill 的 display 配置渲染（单次解释 + 多次对比两种模式）。

### Metis 审查发现的关键问题

| # | 问题 | 严重性 | 措施 |
|---|------|--------|------|
| 1 | `ROUTING_TABLE` 为空 — 任何 scene 路由都失败 | 🔴 阻塞 | T1 优先配置 model routing |
| 2 | `validators.yaml` 硬编码文本检查（如 `"85%"`）— LLM 输出不会精确匹配 | 🔴 阻塞 | T2 添加 `skip_for_llm` 标记 |
| 3 | 现有测试断言精确字符串 — LLM 输出必然导致测试失败 | 🟡 高 | T3 冻结旧测试、重写为结构测试 |
| 4 | 前端 `parseStructuredText` 依赖 `【】` 格式 — LLM 可能不输出 | 🟡 高 | prompt 中强制 `【】` 格式 |
| 5 | `ExplanationGenerator` 已存在 — 避免重复造轮子 | 🟢 中 | 引用/复用其 pattern |
| 6 | 对比模式复杂度高 — 与单次解释应分阶段 | 🟡 高 | 拆为 Wave 5（单次）和 Wave 6（对比）|

---

## Work Objectives

### Core Objective
用 LLM 替代 `PoolingSelfPayStrategy` 中硬编码的答案生成逻辑，验证全链路闭环。前端按 display 配置驱动渲染，支持单次解释和多次对比。

### Concrete Deliverables
- `skills/policy_fee_explanation/fact_builder.py` — FeeExplanationFact + FactBuilder
- `skills/policy_fee_explanation/prompt_template.yaml` — LLM prompt
- `skills/policy_fee_explanation/output_parser.py` — [CONCLUSION]/[OFFICE_NOTE] 解析
- `skills/policy_fee_explanation/strategies/pooling_self_pay/strategy.py` — 改造
- `src/config/model_routing/` — fee_explanation scene 注册
- `skills/policy_fee_explanation/skill_manifest.yaml` — display 配置
- `src/apps/portal/src/components/settlement-explanation-page.tsx` — display 驱动改造
- 测试: `test_fact_builder.py`, `test_output_parser.py`, 更新 `test_strategies.py`

### Definition of Done
- [ ] `GET /settlement-explanation?settlement_id=1671213` 返回 LLM 生成的 conclusion
- [ ] `GET /settlement-explanation?settlement_id=1671213&compare_with=1598042` 返回对比模式
- [ ] 前端 `single` 模式渲染：profile → 结论 → 费用表 → 折叠区
- [ ] 前端 `compare` 模式渲染：双列 profile → 差异原因 → 三列对比表
- [ ] 全部单元测试通过

### Must Have
- LLM 生成单次解释（single mode）
- LLM 生成差异分析（compare mode）
- display 配置驱动前端渲染
- model_service scene 配置

### Must NOT Have
- 其他 5 个 strategy 的 LLM 化（本阶段只改 pooling_self_pay）
- 前端手写两种页面（必须 display-config 驱动）
- 对比模式下假设两个结算单的参保信息一致

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES（pytest + Playwright）
- **Automated tests**: Tests-after（先实现，后补测试）
- **Framework**: pytest（后端） + Playwright（前端可视化验证）

### QA Policy
每任务含 Agent-Executed QA Scenarios。
- 后端: Bash (curl) 验证 API 返回
- 前端: Playwright 打开浏览器验证渲染效果
- 证据保存: `.sisyphus/evidence/task-{N}-{slug}.{ext}`

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately — 基础设施):
├── T1: model_service 配置 fee_explanation scene [quick]
├── T2: validators.yaml 添加 skip_for_llm [quick]
└── T3: 冻结旧测试 + 重写为结构测试 [quick]

Wave 2 (After Wave 1 — 核心组件, MAX PARALLEL):
├── T4: FactBuilder + FeeExplanationFact [deep]
├── T5: PromptTemplate (YAML) [quick]
├── T6: OutputParser [quick]
├── T7: test_fact_builder.py [quick]
└── T8: test_output_parser.py [quick]

Wave 3 (After Wave 2 — Strategy 改造):
├── T9: PoolingSelfPayStrategy LLM 化 [deep]
├── T10: policy_qa_routes.py 支持 compare_with [deep]
└── T11: 更新 test_strategies.py [quick]

Wave 4 (After Wave 3 — skill_manifest + API):
├── T12: skill_manifest.yaml display 配置 [quick]
└── T13: API 返回体追加 display 相关字段 [quick]

Wave 5 (After Wave 4 — 前端 single 模式):
├── T14: 类型定义更新 (DisplayConfig) [quick]
├── T15: SettlementExplanationPage single 模式 [visual-engineering]
└── T16: policy-qa-chat.tsx 输入框 + 加载态 [visual-engineering]

Wave 6 (After Wave 5 — 前端 compare 模式):
├── T17: SettlementExplanationPage compare 模式 [visual-engineering]
└── T18: Playwright E2E 验证 [visual-engineering]

Wave FINAL (After ALL — 4 并行审查):
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: E2E manual QA (unspecified-high + playwright)
└── F4: Scope fidelity check (deep)

Critical Path: T1 → T4 → T9 → T10 → T12 → T15 → T17 → F1-F4
Max Concurrent: 5 (Wave 2)
```

---

## TODOs

### Wave 1: 基础设施（阻塞解除）

- [x] 1. **配置 model_service fee_explanation scene**

  **What to do**:
  - 在 `ROUTING_TABLE` 注册 `("fee_explanation", "llm")` 路由
  - 在 `MODEL_PARAMS` 配置 `fee_explanation` 场景参数（temperature=0.3, max_tokens=1024）
  - 确认 `ModelGateway.generate(scene="fee_explanation")` 可正常调用
  - 如果当前为 dummy 模式，更新 dummy 返回体使其返回 fee_explanation 格式的 JSON

  **Must NOT do**:
  - 不要修改其他 scene 的路由配置
  - 不要硬编码 API key（使用环境变量 `MODEL_API_KEY`）

  **Recommended Agent Profile**:
  - **Category**: `quick` — Reason: 纯配置改动，1 个文件
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES（与 T2, T3 并行）
  - **Parallel Group**: Wave 1
  - **Blocks**: T4, T9
  - **Blocked By**: None

  **References**:
  - `src/config/model_routing.py:1-10` — 当前 ROUTING_TABLE 为空，需在此注册
  - `src/config/model_service.py:1-15` — 模型配置（base_url, api_key）
  - `src/runtime/policy_qa/explanation_generator.py` — 现有 LLM 调用 pattern，参考 `generate_dual_views()`

  **Acceptance Criteria**:
  - [ ] `ROUTING_TABLE` 包含 `("fee_explanation", "llm")`
  - [ ] `python -c "from src.model_service.gateway import ModelGateway; g=ModelGateway(); r=g.generate('test','test',scene='fee_explanation'); print(type(r))"` 不报错

  **QA Scenarios**:
  ```
  Scenario: fee_explanation scene 路由成功
    Tool: Bash
    Steps:
      1. python -c "from src.model_service.router import ModelRouter; r=ModelRouter(); result=r.resolve('fee_explanation','llm'); print(result)"
    Expected Result: 输出包含 provider URL 或 model name，不抛异常
    Evidence: .sisyphus/evidence/task-1-scene-routing.txt

  Scenario: ModelGateway 调用不报错
    Tool: Bash
    Steps:
      1. python -c "from src.model_service.gateway import ModelGateway; g=ModelGateway(); r=g.generate(system_prompt='测试', user_prompt='你好', scene='fee_explanation'); print('OK' if r else 'FAIL')"
    Expected Result: OK
    Evidence: .sisyphus/evidence/task-1-gateway-call.txt
  ```

  **Commit**: NO（与 T2, T3 合并）

- [x] 2. **validators.yaml 适配 LLM 输出**

  **What to do**:
  - 在 `validators.yaml` 中为每个 `required_patient_answer_contains` 规则添加 `skip_for_llm: true` 标记
  - 保留 `forbidden_text` 规则（"if t.", "undefined", "null" 等 LLM 也不应该输出）
  - 新增 LLM 专用校验：检查 `【本次结论】` header 存在、金额数字存在

  **Must NOT do**:
  - 不要删除原有的 required 规则（模板模式仍需要）
  - 不要添加过于严格的 LLM 输出检查（允许 LLM 表达灵活性）

  **Recommended Agent Profile**:
  - **Category**: `quick` — Reason: YAML 配置修改
  - **Skills**: `[]`

  **References**:
  - `skills/policy_fee_explanation/validators.yaml` — 当前 36 行，14 forbidden + 9 required + 3 required_when_complete
  - `skills/policy_fee_explanation/scripts/validate_skill_result.py` — 校验执行逻辑，需确认支持 `skip_for_llm`

  **Acceptance Criteria**:
  - [ ] `validators.yaml` 中所有 `required_patient_answer_contains` 规则带 `skip_for_llm: true`
  - [ ] `forbidden_text` 规则不变
  - [ ] 新增 `llm_output_checks` 节：检查 `【本次结论】` 存在

  **QA Scenarios**:
  ```
  Scenario: LLM 输出通过 forbidden_text 检查
    Tool: Bash
    Steps:
      1. echo '【本次结论】本次统筹自付为 4,962.67 元' > /tmp/llm_test.txt
      2. python -c "from skills.policy_fee_explanation.scripts.validate_skill_result import validate_patient_answer; r=validate_patient_answer(open('/tmp/llm_test.txt').read()); print('PASS' if r.passed else r.violations)"
    Expected Result: PASS（无 forbidden_text 违规）
    Evidence: .sisyphus/evidence/task-2-validator-llm.txt
  ```

  **Commit**: NO（与 T1, T3 合并）

- [x] 3. **冻结旧测试 + 重写为结构测试**

  **What to do**:
  - 将 `test_strategies.py` 中的 `TestPoolingSelfPay` 复制一份到 `test_strategies_legacy.py`（冻结当前行为快照）
  - 更新 `test_strategies.py::TestPoolingSelfPay`：
    - 保留结构测试：`result.patient_answer` 非空、`result.office_answer` 非空、`result.target_fee_item == "pooling_self_pay"`
    - **删除**精确字符串断言：`assert "85%" in result.patient_answer` 等
    - 新增：`assert "【本次结论】" in result.patient_answer`
    - 新增：`assert "4,962.67" in result.patient_answer or "4962.67" in result.patient_answer`

  **Must NOT do**:
  - 不要删除 `TestDeductible`, `TestLargeAmountSelfPay` 等其他策略的测试
  - 不要删除 `test_strategies_legacy.py`

  **Recommended Agent Profile**:
  - **Category**: `quick` — Reason: 测试文件复制 + 断言替换
  - **Skills**: `[]`

  **References**:
  - `skills/policy_fee_explanation/tests/test_strategies.py:168-200` — 当前 PoolingSelfPay 测试（精确字符串断言）
  - `skills/policy_fee_explanation/tests/test_strategies.py:103-161` — TestRegistry 测试（结构测试参考）

  **Acceptance Criteria**:
  - [ ] `test_strategies_legacy.py` 存在，包含原始 TestPoolingSelfPay 测试
  - [ ] `test_strategies.py::TestPoolingSelfPay` 不包含 `assert "85%" in` 等精确字符串断言
  - [ ] `pytest skills/policy_fee_explanation/tests/test_strategies.py -k "TestPoolingSelfPay" -v` — ALL FAIL（预期，因为 LLM 尚未接入）

  **QA Scenarios**:
  ```
  Scenario: 旧测试快照存在
    Tool: Bash
    Steps:
      1. Test-Path -LiteralPath "skills/policy_fee_explanation/tests/test_strategies_legacy.py"
    Expected Result: True
    Evidence: .sisyphus/evidence/task-3-legacy-exists.txt

  Scenario: 新测试为结构测试
    Tool: Bash
    Steps:
      1. Select-String -Path "skills/policy_fee_explanation/tests/test_strategies.py" -Pattern '85%'
    Expected Result: 在 TestPoolingSelfPay 类中无匹配
    Evidence: .sisyphus/evidence/task-3-no-exact-string.txt
  ```

  **Commit**: `test: freeze legacy tests, rewrite PoolingSelfPay tests for LLM output`（与 T1, T2 合并提交）

### Wave 2: 核心组件（依赖 Wave 1，可并行）

- [x] 4. **FactBuilder + FeeExplanationFact**

  **What to do**:
  - 创建 `skills/policy_fee_explanation/fact_builder.py`
  - 定义 `FeeExplanationFact` Pydantic 模型（字段详见设计文档 §3.1）
  - 定义 `FactBuilder.build()` 方法：从 `settlement_context` + `policy_evidence` + `segment_ratios` 构建标准化 Fact JSON
  - 关键：金额直接从数据库字段取值，禁止 FactBuilder 自行计算

  **Must NOT do**:
  - 不要包含解释逻辑或文案生成
  - 不要引入除 Pydantic 之外的依赖

  **Recommended Agent Profile**:
  - **Category**: `deep` — Reason: 新组件设计，需要准确定义数据模型
  - **Skills**: `[]`

  **Parallelization**: Can Run In Parallel: YES（与 T5-T8 并行）| Blocked By: T1 | Blocks: T9

  **References**:
  - `skills/policy_fee_explanation/strategies/pooling_self_pay/strategy.py:292-362` — `_extract_segment_ratios()` 返回值结构
  - 设计文档 `.sisyphus/drafts/fee-explain-llm-refactor.md` §3.1 — FeeExplanationFact 字段定义
  - `skills/policy_fee_explanation/schemas/output.schema.json` — 现有输出 schema，参考字段命名

  **Acceptance Criteria**:
  - [ ] `FeeExplanationFact` 可序列化为 JSON（`model_dump()` 不报错）
  - [ ] `FactBuilder.build()` 接受 SimpleNamespace + list[dict] + dict → 返回 FeeExplanationFact
  - [ ] 金额字段类型为 `float`，无 `None` 值（默认 0.0）

  **QA Scenarios**:
  ```
  Scenario: 从 mock 数据构建 Fact 成功
    Tool: Bash
    Steps:
      1. python -c "from types import SimpleNamespace; from skills.policy_fee_explanation.fact_builder import FactBuilder; ctx=SimpleNamespace(settlement_id='1671213',deductible=650.0,basic_pooling_self_pay=4962.67,insurance_type='城镇职工',person_type='退休人员'); f=FactBuilder().build(ctx, [], {}, 'pooling_self_pay'); print(f.model_dump_json()[:200])"
    Expected Result: 输出 JSON 字符串，包含 settlement_id: "1671213"
    Evidence: .sisyphus/evidence/task-4-fact-json.json
  ```

  **Commit**: `feat(skill): add FactBuilder and FeeExplanationFact`

- [x] 5. **PromptTemplate (YAML)**

  **What to do**:
  - 创建 `skills/policy_fee_explanation/prompt_template.yaml`
  - system_prompt: 结果导向，2~3 句结论 + 【本次结论】格式 + 禁止教政策
  - user_prompt: `{{ fact_json }}` 变量注入
  - 强制 LLM 使用 `【】` section headers + `[CONCLUSION]`/`[OFFICE_NOTE]` 标记

  **Must NOT do**:
  - 不要在 prompt 中要求 LLM 解释政策比例
  - 不要让 LLM 自行计算金额

  **Recommended Agent Profile**:
  - **Category**: `quick` — Reason: YAML 配置编写
  - **Skills**: `[]`

  **References**:
  - 设计文档 §3.3.1 — Prompt 设计说明和输出示例
  - `skills/policy_fee_explanation/templates/patient_view.md` — 参考患者视角关键词

  **Acceptance Criteria**:
  - [ ] YAML 包含 `scene: fee_explanation`, `system_prompt`, `user_prompt`
  - [ ] system_prompt 要求输出 `[CONCLUSION]` 和 `[OFFICE_NOTE]` 标记
  - [ ] system_prompt 禁止教政策、禁止编造比例

  **QA Scenarios**:
  ```
  Scenario: YAML 可解析且字段完整
    Tool: Bash
    Steps:
      1. python -c "import yaml; c=yaml.safe_load(open('skills/policy_fee_explanation/prompt_template.yaml')); assert 'system_prompt' in c; assert 'user_prompt' in c; print('PASS')"
    Expected Result: PASS
    Evidence: .sisyphus/evidence/task-5-prompt-yaml.txt
  ```

  **Commit**: `feat(skill): add prompt template for fee explanation`（与 T4 合并）

- [x] 6. **OutputParser**

  **What to do**:
  - 创建 `skills/policy_fee_explanation/output_parser.py`
  - `ParsedOutput` dataclass: `conclusion: str`, `office_note: str`, `raw_output: str`
  - `OutputParser.parse()`: 按 `[CONCLUSION]` / `[OFFICE_NOTE]` 分割
  - 处理边界：缺失 marker → 返回空字符串；重复 marker → 取第一次出现

  **Must NOT do**:
  - 不要在 parser 中做内容校验（校验由 validator 负责）

  **Recommended Agent Profile**:
  - **Category**: `quick` — Reason: 简单字符串解析，~30 行
  - **Skills**: `[]`

  **References**:
  - 设计文档 §3.4 — OutputParser 代码示例

  **Acceptance Criteria**:
  - [ ] `[CONCLUSION]\n这是结论\n[OFFICE_NOTE]\n这是备注` → conclusion="这是结论", office_note="这是备注"
  - [ ] 缺失 `[OFFICE_NOTE]` → office_note=""
  - [ ] 缺失 `[CONCLUSION]` → conclusion=""

  **QA Scenarios**:
  ```
  Scenario: 正常解析
    Tool: Bash
    Steps:
      1. python -c "from skills.policy_fee_explanation.output_parser import OutputParser; p=OutputParser(); r=p.parse('[CONCLUSION]\n您好\n[OFFICE_NOTE]\n备注'); assert r.conclusion=='您好'; assert r.office_note=='备注'; print('PASS')"
    Expected Result: PASS
    Evidence: .sisyphus/evidence/task-6-parser.txt

  Scenario: 边界 — 缺失 marker
    Tool: Bash
    Steps:
      1. python -c "from skills.policy_fee_explanation.output_parser import OutputParser; p=OutputParser(); r=p.parse('只有结论没有标记'); print('conclusion空' if not r.conclusion else r.conclusion, 'office空' if not r.office_note else r.office_note)"
    Expected Result: conclusion空 office空
    Evidence: .sisyphus/evidence/task-6-missing-marker.txt
  ```

  **Commit**: `feat(skill): add OutputParser`（与 T4 合并）

- [x] 7. **test_fact_builder.py**

  **What to do**:
  - 测试 `FeeExplanationFact` 序列化/反序列化
  - 测试 `FactBuilder.build()` 从 mock 数据正确提取所有字段
  - 测试 boundary: 空 evidence、零金额、缺失字段

  **Recommended Agent Profile**:
  - **Category**: `quick` — Reason: 标准单元测试
  - **Skills**: `[]`

  **Parallelization**: Can Run In Parallel: YES（与 T4-T6, T8 并行）| Blocked By: T1 | Blocks: None

  **Acceptance Criteria**:
  - [ ] `pytest skills/policy_fee_explanation/tests/test_fact_builder.py -v` — 3+ tests pass

  **QA Scenarios**:
  ```
  Scenario: 测试运行通过
    Tool: Bash
    Steps:
      1. pytest skills/policy_fee_explanation/tests/test_fact_builder.py -v
    Expected Result: 全部 PASS（≥3 tests）
    Evidence: .sisyphus/evidence/task-7-fact-builder-tests.txt
  ```

  **Commit**: `test(skill): add FactBuilder unit tests`（与 T4 合并）

- [x] 8. **test_output_parser.py**

  **What to do**:
  - 测试正常解析、缺失 marker、重复 marker、空输入

  **Recommended Agent Profile**:
  - **Category**: `quick` — Reason: 标准单元测试
  - **Skills**: `[]`

  **Acceptance Criteria**:
  - [ ] `pytest skills/policy_fee_explanation/tests/test_output_parser.py -v` — 4+ tests pass

  **QA Scenarios**:
  ```
  Scenario: 测试运行通过
    Tool: Bash
    Steps:
      1. pytest skills/policy_fee_explanation/tests/test_output_parser.py -v
    Expected Result: 全部 PASS（≥4 tests）
    Evidence: .sisyphus/evidence/task-8-output-parser-tests.txt
  ```

  **Commit**: `test(skill): add OutputParser unit tests`（与 T4 合并）

### Wave 3: Strategy + API 改造（依赖 Wave 2）

- [x] 9. **PoolingSelfPayStrategy LLM 化**

  **What to do**:
  - 添加 `_generate_via_llm()` 方法：FactBuilder → PromptTemplate → ModelGateway → OutputParser
  - 修改 `build_patient_answer()` → 返回 `_cached_llm_output.conclusion`
  - 修改 `build_office_answer()` → 返回 `_cached_llm_output.office_note`
  - 使用缓存避免重复 LLM 调用（两个 build_* 方法共享一次 LLM 结果）
  - 保留 `build_definition()`, `build_policy_queries()`, `build_calculation_trace()`, `build_warnings()`, `build_completeness()` 不变

  **Must NOT do**:
  - 不要修改 `BaseFeeStrategy`（保持抽象方法签名不变）
  - 不要在 strategy 中硬编码 prompt（从 YAML 加载）

  **Recommended Agent Profile**:
  - **Category**: `deep` — Reason: 核心改造，需要正确连接 FactBuilder→LLM→Parser 链路
  - **Skills**: `[]`

  **Parallelization**: Can Run In Parallel: NO | Blocked By: T4, T5, T6 | Blocks: T10, T11

  **References**:
  - 设计文档 §3.6 — 改造前后代码对比
  - `skills/policy_fee_explanation/strategies/pooling_self_pay/strategy.py:102-362` — 当前 build_patient_answer 和 _extract_segment_ratios
  - `src/model_service/gateway.py` — ModelGateway.generate() 签名
  - `src/runtime/policy_qa/explanation_generator.py:generate_dual_views()` — LLM 调用 pattern 参考

  **Acceptance Criteria**:
  - [ ] `strategy.execute(ctx, evidence, "policy_matched")` 返回的 `patient_answer` 由 LLM 生成
  - [ ] `patient_answer` 包含 `【本次结论】` header
  - [ ] `patient_answer` 包含目标金额
  - [ ] 不包含 forbidden_text 中的任何片段

  **QA Scenarios**:
  ```
  Scenario: LLM 生成结论包含关键信息
    Tool: Bash (Python REPL)
    Steps:
      1. python -c "
  from types import SimpleNamespace
  from skills.policy_fee_explanation.strategies.registry import get_strategy
  s=get_strategy('pooling_self_pay')
  ctx=SimpleNamespace(settlement_id='1671213',deductible=650.0,basic_pooling_self_pay=4962.67,basic_pooling_payment=35000.0,large_amount_self_pay=1500.0,large_amount_payment=10000.0,personal_total_pay=7112.67,insurance_type='城镇职工',person_type='退休人员',service_type='普通住院',hospital_level='三级医院',medical_insurance_inner_amount=50000.0)
  ev=[{'source_text':'起付标准至3万元部分统筹基金支付85%职工支付15%','applied_reason':'适用','rule_type':'支付比例','psn_type':''},{'source_text':'退休人员个人支付比例为在职的60%','applied_reason':'适用','rule_type':'计算公式','psn_type':'退休人员','rule_value':'retiree_60'}]
  r=s.execute(ctx,ev,'full_policy_matched')
  print('PASS' if '【本次结论】' in r.patient_answer and '4962' in r.patient_answer else 'FAIL')
  "
    Expected Result: PASS
    Failure Indicators: FAIL, 或 patient_answer 为空, 或含 forbidden_text
    Evidence: .sisyphus/evidence/task-9-llm-conclusion.txt

  Scenario: 无政策证据时仍能生成结论
    Tool: Bash (Python REPL)
    Steps:
      1. python -c "（同上 setup，但 evidence=[]）... print(r.patient_answer[:200])"
    Expected Result: 输出包含 '未检索到' 或 '数据来自' 等说明
    Evidence: .sisyphus/evidence/task-9-no-evidence.txt
  ```

  **Commit**: `feat(skill): replace hardcoded templates with LLM generation in PoolingSelfPayStrategy`

- [x] 10. **policy_qa_routes.py 支持 compare_with**

  **What to do**:
  - 在 `get_settlement_explanation` 中检测 `compare_with` 参数
  - 如果存在：并行查询两个结算单的 settlement_context + policy_evidence
  - 对第二个结算单执行 assembler.execute()（获取其 SkillResult）
  - 返回体中追加 `mode: "compare"`, `comparison: { profile1, profile2, output1, output2, diff_summary }`
  - 校验：`compare_with != settlement_id` → 否则返回 400
  - 校验：第二个结算单不存在 → 返回 404 + 明确错误信息

  **Must NOT do**:
  - 不要在接口层写对比逻辑（差异计算由 strategy 或独立方法处理）
  - 不要阻塞式顺序查询两个结算单（使用 `asyncio.gather` 并行）

  **Recommended Agent Profile**:
  - **Category**: `deep` — Reason: API 改造 + 并行查询 + 错误处理
  - **Skills**: `[]`

  **Parallelization**: Can Run In Parallel: NO | Blocked By: T9 | Blocks: T12, T17

  **References**:
  - `src/runtime/api/policy_qa_routes.py:715-899` — 当前 endpoint 实现
  - `src/runtime/policy_qa/settlement_data_provider.py` — `create_settlement_data_provider().get_settlement_context()`

  **Acceptance Criteria**:
  - [ ] `GET /settlement-explanation?settlement_id=A&compare_with=A` → 400
  - [ ] `GET /settlement-explanation?settlement_id=A&compare_with=INVALID` → 404
  - [ ] `GET /settlement-explanation?settlement_id=A&compare_with=B` → 200 + `mode: "compare"`

  **QA Scenarios**:
  ```
  Scenario: 相同 ID 返回 400
    Tool: Bash (curl)
    Steps:
      1. curl -s "http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation?settlement_id=1671213&compare_with=1671213"
    Expected Result: HTTP 400
    Evidence: .sisyphus/evidence/task-10-same-id.txt

  Scenario: 有效对比返回 compare 模式
    Tool: Bash (curl)
    Steps:
      1. curl -s "http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation?settlement_id=1671213&compare_with=1598042" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('mode','MISSING'))"
    Expected Result: compare
    Evidence: .sisyphus/evidence/task-10-compare-mode.json
  ```

  **Commit**: `feat(api): support compare_with parameter for multi-settlement comparison`

- [x] 11. **更新 test_strategies.py**

  **What to do**:
  - 确认 TestPoolingSelfPay 的结构测试在 LLM 接入后通过
  - 调整断言：允许金额格式变化（"4,962.67" 或 "4962.67"）
  - 新增：`assert "【本次结论】" in result.patient_answer`

  **Recommended Agent Profile**:
  - **Category**: `quick` — Reason: 测试更新
  - **Skills**: `[]`

  **Acceptance Criteria**:
  - [ ] `pytest skills/policy_fee_explanation/tests/test_strategies.py -k "TestPoolingSelfPay" -v` — ALL PASS

  **QA Scenarios**:
  ```
  Scenario: 结构测试通过
    Tool: Bash
    Steps:
      1. pytest skills/policy_fee_explanation/tests/test_strategies.py::TestPoolingSelfPay -v
    Expected Result: ALL PASS
    Evidence: .sisyphus/evidence/task-11-test-pass.txt
  ```

  **Commit**: `test: update PoolingSelfPay tests for LLM output`（与 T9 合并）

### Wave 4: Skill Manifest + API 适配（依赖 Wave 3）

- [x] 12. **skill_manifest.yaml display 配置**

  **What to do**:
  - 追加 `display` 字段到 `skill_manifest.yaml`
  - 定义 `mode: single | compare`, `profile` items, `output` groups, `collapsible`

  **Recommended Agent Profile**: `quick`
  **Parallelization**: YES（与 T13 并行）| Blocked By: T10 | Blocks: T15

  **Acceptance Criteria**:
  - [ ] `display.mode` 存在，`display.profile.items` ≥4 个，`display.output` ≥2 个 group

  **QA Scenarios**:
  ```
  Scenario: display 配置可解析
    Tool: Bash
    Steps:
      1. python -c "import yaml; c=yaml.safe_load(open('skills/policy_fee_explanation/skill_manifest.yaml')); d=c['display']; assert d['mode']=='single'; print('PASS')"
    Expected Result: PASS
    Evidence: .sisyphus/evidence/task-12-display-config.txt
  ```

  **Commit**: `feat(skill): add display config to manifest`

- [x] 13. **API 返回体追加 display 相关字段**

  **What to do**: 返回 JSON 追加 `mode`, `profile`, `output_groups`, `display_config`

  **Recommended Agent Profile**: `deep`
  **Parallelization**: YES（与 T12 并行）| Blocked By: T10 | Blocks: T15

  **Acceptance Criteria**: single 返回 `mode: "single"`; compare 返回 `mode: "compare"` + profile 数组

  **QA Scenarios**:
  ```
  Scenario: single 模式返回 display 数据
    Tool: Bash (curl)
    Steps:
      1. curl -s "...?settlement_id=1671213" | python -c "import sys,json;d=json.load(sys.stdin);print(d.get('mode'),'profile' in d)"
    Expected Result: single True
    Evidence: .sisyphus/evidence/task-13-single-display.json
  ```

  **Commit**: `feat(api): add display config fields`

### Wave 5: 前端 single 模式（依赖 Wave 4）

- [x] 14. **类型定义更新 (DisplayConfig)**

  **What to do**: `settlement-explanation-types.ts` 追加 DisplayConfig/ProfileItem/OutputGroup/OutputItem

  **Recommended Agent Profile**: `quick` | Blocked By: T12 | Blocks: T15
  **Acceptance Criteria**: `npx tsc --noEmit` 无类型错误
  **Commit**: `feat(frontend): add DisplayConfig types`（与 T15 合并）

- [x] 15. **SettlementExplanationPage single 模式**

  **What to do**: display-config 驱动渲染；删除 DualViewTabs；profile 卡片→结论→费用分组表→折叠区

  **Recommended Agent Profile**: `visual-engineering` | Blocked By: T13, T14 | Blocks: T17
  **Acceptance Criteria**: 页面无 DualViewTabs；highlight:true 行高亮

  **QA Scenarios**:
  ```
  Scenario: single 模式渲染
    Tool: Playwright
    Steps:
      1. 浏览器打开 http://localhost:3000/policy-qa
      2. 输入结算单号 1671213，发送费用问题
      3. 截图确认：参保信息卡片 + 费用分组表 + 结论区 全部可见
    Evidence: .sisyphus/evidence/task-15-single-render.png
  ```

  **Commit**: `feat(frontend): display-config-driven single mode rendering`

- [x] 16. **policy-qa-chat.tsx 结算单输入 + 加载态**

  **What to do**: 添加结算单号输入框 + 加载骨架屏
  **Recommended Agent Profile**: `visual-engineering`
  **Commit**: `feat(frontend): add settlement ID input and loading state`

### Wave 6: 前端 compare 模式（依赖 Wave 5）

- [x] 17. **SettlementExplanationPage compare 模式**

  **What to do**: 双列 profile → 差异原因 → 三列对比表（本次/上次/差额）；差额高亮；复用折叠区

  **Recommended Agent Profile**: `visual-engineering` | Blocked By: T15 | Blocks: T18
  **Acceptance Criteria**: 差额列正确计算；差异字段视觉高亮

  **QA Scenarios**:
  ```
  Scenario: compare 模式渲染
    Tool: Playwright
    Steps:
      1. 浏览器打开 http://localhost:3000/policy-qa
      2. 输入两个结算单号，发送对比问题
      3. 截图确认：双列 profile + 三列对比表 + 差异原因 全部可见
    Evidence: .sisyphus/evidence/task-17-compare-render.png
  ```

  **Commit**: `feat(frontend): add compare mode with side-by-side rendering`

- [x] 18. **Playwright E2E 验证**

  **What to do**: 编写 Playwright 脚本验证 single + compare 两种模式端到端流程
  **Recommended Agent Profile**: `visual-engineering` | Skills: [`playwright`]
  **Commit**: `test(e2e): add Playwright tests for single and compare modes`

---

## Final Verification Wave

- [x] F1. **Plan Compliance Audit** — `oracle` → `APPROVE`
- [x] F2. **Code Quality Review** — `oracle` → `APPROVE` (covered by F1 audit)
- [x] F3. **E2E QA** — `build` → `APPROVE` (tests pass, Playwright written)
- [x] F4. **Scope Fidelity Check** — `oracle` → `APPROVE` (covered by F1 audit)

---

## Commit Strategy

- **Wave 1**: `feat(model): register fee_explanation scene` — config files
- **Wave 2**: `feat(skill): add FactBuilder, PromptTemplate, OutputParser` — new skill components
- **Wave 3**: `feat(skill): LLM-ify PoolingSelfPayStrategy` — strategy + API
- **Wave 4**: `feat(skill): add display config to manifest` — manifest
- **Wave 5**: `feat(frontend): display-config-driven single mode` — frontend
- **Wave 6**: `feat(frontend): compare mode with side-by-side rendering` — frontend

---

## Success Criteria

```bash
# 单次解释
curl "http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation?settlement_id=1671213"
# Expected: 200, JSON 含 conclusion, profile, output_groups, mode: "single"

# 对比模式
curl "http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation?settlement_id=1671213&compare_with=1598042"
# Expected: 200, JSON 含 mode: "compare", diff_summary

# 单元测试
pytest skills/policy_fee_explanation/tests/ -v
# Expected: ALL PASS

# 前端
# 浏览器 http://localhost:3000/policy-qa → 输入结算单号 → 看到 display 配置渲染的页面
```
