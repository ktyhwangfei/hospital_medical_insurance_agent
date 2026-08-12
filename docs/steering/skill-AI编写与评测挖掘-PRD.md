# Skill 模块演进 PRD：AI 编写 + 评测挖掘

> **版本**：V1.1（评审修订版）
>
> **定位**：Skill 管理模块（`src/apps/portal/app/skills/`）两项演进需求的 PRD。
>
> **前提**：意见 4 已选方案 A（详情工作区瘦身，只留概览+版本；评测/发布只看顶层列表页）。本 PRD 的新页面挂载基于此 IA。
>
> **设计依据**：`skill-workbench-implementation-plan.md`、`语义层设计文档.md`、`医保Agent-政策问答前端改造设计-V1.0.md`、现有 Skill 草稿/物化/评测/发布实现。
>
> **状态**：🟡 已按评审意见修订，待复审（未动代码）

---

## 0. 评审决策与共同约束

### 0.1 本轮已确认的产品决策

1. **Skill 对其完整输出链路负责**。Skill 错误不限于路由错误；只要某次回答由该 Skill 处理，路由错误、计算错误、政策内容错误、引用错误、回答完整性或安全错误都先进入统一的 Skill 问题案例池，再按错误维度生成不同类型的回归资产。
2. **统一收集、分型治理**。所有 Skill 错误使用同一个案例池和人工确认流程，但不能全部压缩成 `expected_skill_id`；不同错误维度必须由对应评测器验证，避免用路由准确率掩盖计算或内容缺陷。
3. **目标是形成防复发门禁**。确认后的案例必须成为可重复执行、可追溯的回归资产，并逐步接入版本评测/发布门禁，以降低同类错误再次发生的概率。
4. **AI 只能提出候选，不直接生效**。AI 生成或优化的 Python、Schema、模板和配置必须经过校验、隔离评测和人工确认，生成阶段不得导入或执行代码。

### 0.2 Skill 错误维度

| 错误维度 | 含义 | 确认后形成的评测资产 | 评测方式 |
|----------|------|----------------------|----------|
| `routing` | 未命中正确 Skill，或不应命中却被接管 | 现有 `SkillEvalCase` | 固定路由候选/基线对比 |
| `calculation` | 公式、口径、取值、舍入或结果错误 | `SkillRegressionCase`（计算断言） | 隔离执行 + 数值/容差断言 |
| `policy_content` | 政策事实、适用条件、时效或结论错误 | `SkillRegressionCase`（政策内容断言） | 答案事实/禁止结论/政策版本断言 |
| `citation` | 缺少来源、引用错误或引用不支持结论 | `SkillRegressionCase`（引用断言） | 引用数量、来源 ID、结论支撑关系检查 |
| `answer_quality` | 答非所问、关键信息缺失、不可回答性判断错误 | `SkillRegressionCase`（答案质量断言） | 必含/禁含内容、answerability、人工 rubric |
| `safety` | 泄露敏感信息、绕过人工确认或产生高风险动作 | `SkillRegressionCase`（安全断言） | 脱敏、风险拦截、人工确认状态断言 |
| `other` | 暂不能可靠归类 | 保留在案例池待人工分诊 | 不自动进入发布门禁 |

> `SkillEvalCase` 保持现有“固定、脱敏的路由评测用例”语义；非路由错误使用新的 `SkillRegressionCase`，不得修改路由指标含义。[来源: `src/domain/skill/governance_models.py`、`src/runtime/skill_management/governance_service.py`]

### 0.3 工程与安全约束（遵循 AGENTS.md）

- 所有 LLM 调用**必须走 `model_service.gateway.ModelGateway`**，禁止直接 HTTP；本需求使用独立 scene：`skill_authoring`、`skill_eval_transform`。
- 新存储遵循 ports/adapter，默认 PostgreSQL，`USE_MEMORY_STORAGE=1` 可回退内存。
- 领域概念命名遵循 `src/domain/AGENTS.md` 通用语言字典，新增 `SkillRegressionCase`、AI 草稿来源和案例池状态后同步更新。
- 「业务指标」= 语义层标准指标（`MetricSourceBinding` 体系，`GET /semantic/metrics`），**不是**评测指标（如 `top1_accuracy`）。
- API 请求/响应使用显式 Pydantic DTO；不得以裸 `dict` 作为接口返回类型。
- AI 输出必须携带 `citations` 或 `uncertainties`，并记录模型路由、提示词版本、输入指标版本、生成时间和内容哈希。
- 任何进入 ModelGateway、案例池或评测集的真实问答内容，必须先经过 `security/desensitization/`；禁止在评测资产中保存患者原始上下文。
- Skill 治理写操作复用现有权限边界：AI 编写/草稿变更要求 `skill:release:test`，评测案例转换/确认要求 `skill:evaluate`；普通用户只能反馈本人可访问的问答轮次。
- 草稿更新、案例转换和确认必须使用乐观锁 revision；创建、反馈和确认接口必须支持幂等。

---

# 意见 2：AI 编写 Skill（脚本 + Schema + 提示词模板）

## 2.1 背景与目标

当前 `/skills/new` 是人工填表，`/skills/[id]/edit` 需要手工维护 YAML/脚本，效率低、门槛高。

**目标**：用户用自然语言描述需求并选择已发布业务指标，AI 自动生成一个**可审查、可校验的 Skill 候选草案**，包括 assembler 脚本、输入/输出 Schema、提示词模板和基础结构化配置；用户审核后保存草稿，再按“静态校验 → 输入指标验证 → 隔离评测 → 人工确认”推进。

AI 生成不承诺首次输出即可发布。产品价值是减少从空白到合格草稿的工作量，而不是绕过工程和业务审核。

## 2.2 用户故事

- 作为 Skill 作者，我描述“做一个解释统筹自付的技能”并选择相关业务指标，AI 返回结构完整且带来源/不确定性的候选草案，我审核后保存，无需从零编写文件。
- 作为 Skill 维护者，我对已有草稿发起“AI 优化”，AI 基于指定 revision 的现有内容和新需求生成候选差异；只有我接受后才覆盖草稿。
- 作为 Skill 评测者，我可以分别查看结构校验、输入指标验证、路由评测和行为/答案评测结果，不把某一种评测通过误认为整个 Skill 已正确。

## 2.3 非目标

- 不允许 AI 自动物化、启用或发布 Skill。
- 不允许 AI 自行添加第三方 Python 依赖、直接访问数据库/网络/文件系统或调用外部系统。
- P1 不以现有路由 `eval-runs` 代替 assembler、计算和答案质量评测。
- 不承诺通过一次生成覆盖复杂 Skill 的全部业务逻辑；复杂需求允许生成骨架并明确列出 `uncertainties`。

## 2.4 流程

```text
/skills/new（对话式创建）
  ① 需求描述（自然语言）
  ② 选择已发布业务指标（GET /semantic/metrics，多选；前端过滤、后端复验）
        ↓
POST /infra-skills/ai-generate（ModelGateway scene=skill_authoring）
  → 规范化候选：structured_config + raw_files
  → validation_preview + provenance + citations/uncertainties
  → 此阶段不落 skills/、不导入 assembler.py、不执行代码
        ↓
前端只读预览（按文件查看）+ 风险/不确定性提示
        ↓
  ③ 接受新草案 → POST /infra-skills/drafts/from-ai（原子创建）
     或接受优化 → PATCH /infra-skills/drafts/{draft_id}
                      （必须携带 expected_revision）
        ↓
  ④ 现有草稿校验 + 输入指标校验 + 样例取数
        ↓
  ⑤ 可选隔离评测
     ├─ 路由：从候选 manifest 评测，不导入 Python
     └─ 行为/答案：在无院端凭证的隔离执行器中运行
        ↓
  ⑥ 人工确认后才允许进入物化/版本/发布流程
```

“AI 优化”生成的是候选提案，不直接修改草稿。用户拒绝提案时，原草稿 revision 和内容保持不变。

## 2.5 前端改动

| 文件 | 改动 |
|------|------|
| `app/skills/new/page.tsx` | **改造**：从表单式改为对话式生成；包含需求输入、已发布指标多选、生成、预览、校验摘要和接受操作 |
| `app/skills/[skillId]/edit/page.tsx` | **新增**“AI 优化”；基于当前 draft_id/revision 生成候选并展示 diff，接受时处理 409 冲突 |
| `src/components/skills/ai-skill-generator.tsx` | **新建**：生成交互、loading、超时、错误和降级状态 |
| `src/components/skills/skill-draft-preview.tsx` | **新建**：按规范文件路径预览 assembler、Schema、提示词和派生配置；展示风险、引用、不确定性和校验预览 |
| `src/components/skills/skill-generation-diff.tsx` | **新建**：按 `structured_config` 字段和 `raw_files` 文件展示差异，不自动合并 |
| `src/lib/api-client.ts` | **新增** `generateSkillWithAI`、`optimizeSkillWithAI`、`createDraftFromAI`；所有 DTO 与后端字段逐项对齐 |

## 2.6 后端接口与 DTO

**新接口**（`src/runtime/api/infra_skill_routes.py`）：

```text
POST /api/v1/medical-insurance-ai-agent/infra-skills/ai-generate
  权限: skill:release:test
  入参: {
    description: str,
    metric_codes: list[str]
  }
  出参 SkillAIGenerationResponse: {
    generation_id: str,
    proposal_hash: str,
    structured_config: {
      basic: {...},
      business_mounting: {...},
      inputs: [...],
      schemas: {input: {...}, output: {...}}
    },
    raw_files: {
      "assembler.py": str,
      "prompt_template.yaml": str
    },
    validation_preview: SkillValidationReportResponse,
    provenance: {
      model_type: str,
      scene: "skill_authoring",
      prompt_version: str,
      metric_versions: list[MetricVersionRef],
      generated_at: datetime,
      content_hash: str
    },
    citations: list[Citation],
    uncertainties: list[str]
  }

POST /api/v1/medical-insurance-ai-agent/infra-skills/drafts/{draft_id}/ai-optimize
  权限: skill:release:test
  入参: {
    description: str,
    metric_codes: list[str],
    expected_revision: int
  }
  出参: SkillAIGenerationResponse
  约束: 仅生成提案；若 expected_revision 已过期返回 409，不修改草稿

POST /api/v1/medical-insurance-ai-agent/infra-skills/drafts/from-ai
  权限: skill:release:test
  入参: {
    generation_id: str,
    proposal_hash: str,
    skill_id: str,
    skill_name: str,
    structured_config: {...},
    raw_files: {...}
  }
  出参: SkillDraftResponse（201）
  约束: 服务端重新校验 proposal_hash、文件白名单、指标状态和安全规则后原子创建
```

`config.yaml`、`skill_manifest.yaml` 和两个 Schema 文件继续由现有 `SkillPackageGenerator` 从 `structured_config` 派生，避免 AI 返回的 YAML 与草稿事实源冲突。AI 只直接提供白名单内的 `assembler.py` 和 `prompt_template.yaml`。

## 2.7 实现层

新建 `src/runtime/skill_management/ai_authoring/`：

- `service.py`：读取指标定义与版本 → 构造 prompt → 调 ModelGateway → 解析结构化输出 → 规范化候选 → 运行预校验。
- `schemas.py`：AI 输出的严格 Pydantic DTO，拒绝多余字段和未知文件路径。
- `prompts.py`：版本化 prompt；注入本项目 Skill 文件契约、Business Action/Object 白名单和指标定义。用户描述放入明确的不可信数据边界，不允许覆盖系统指令。
- `security.py`：路径白名单、大小限制、敏感信息扫描、Python AST allowlist 和危险能力拦截。

领域及持久化调整：

- `SkillDraftSourceType` 新增 `AI_GENERATED = "ai_generated"`，同步 `src/domain/AGENTS.md` 和前端 `SkillDraftSourceType`。
- 生成来源元数据写入草稿的 `raw_files["__generation_meta__.json"]`，现有包生成器物化时忽略 `__` 前缀文件；完整调用证据进入现有事件/审计链路。
- AI 优化接受后复用现有 `save_draft`，必须提交 `expected_revision`，内容变化后状态回到 `editing`。

## 2.8 代码安全与隔离门禁

AI 生成的 `assembler.py` 视为不可信代码，必须满足：

1. 生成、预览、保存草稿和普通校验阶段均不导入、不执行。
2. AST 采用能力白名单；禁止动态执行/导入、进程、网络、任意文件、环境变量、反射和直接数据库访问。
3. 禁止新增依赖；只允许导入批准的标准库和项目公开端口。
4. 行为评测在独立进程或容器中运行，不注入生产密钥和院端凭证，并限制时间、内存、输出大小和可访问目录。
5. AI 产物不得直接写入运行时扫描的 `SKILLS_DIR`。候选制品先进入隔离制品区；通过安全校验、隔离评测并经人工确认后，才可调用正式物化流程。
6. 正式物化前再次校验 proposal_hash、草稿 revision 和全部 blocking gate，防止生成后内容被替换。

> 现有 `SkillMaterializer` 会写入 `skills/`、热重载并创建 enabled 定义；实施本需求前必须增加候选隔离路径，不能直接复用其当前行为。[来源: `src/runtime/skill_management/materializer.py`]

## 2.9 数据模型

**不新增业务表**。生成结果确认后写入现有 `SkillDraft`：

- `structured_config`：basic、business_mounting、inputs、schemas。
- `raw_files`：assembler、提示词模板和不参与物化的生成元数据。
- `source_type=ai_generated`。
- `revision`：沿用现有乐观锁。

模型调用证据复用现有基础设施事件/审计存储；若现有审计字段无法完整保存 `prompt_version`、metric version 和 content hash，再单独提交最小数据库迁移，不在本 PRD 中预设新表。

## 2.10 异常与降级

- ModelGateway 未配置、超时或限流：返回标准错误结构；前端提示“AI 生成暂不可用，可继续手动创建”。
- 模型输出无法解析：最多进行一次结构修复重试；仍失败则返回 `SKILL_AI_OUTPUT_INVALID`，不得保存半成品。
- 指标不存在、未发布或对象无查询实现：返回 blocking 校验，不调用或不接受 AI 结果。
- 草稿 revision 冲突：返回 409，要求重新加载后再生成，禁止静默覆盖。
- 命中危险代码或敏感内容：返回 `SKILL_AI_GENERATION_REJECTED`，记录审计事件，不向运行时写盘。
- 用户主动取消：不创建草稿，不保留生成内容，只保留不含业务正文的调用审计摘要。

## 2.11 验收标准

- [ ] 描述需求并选择已发布指标后，返回严格 DTO：结构化配置、assembler、输入/输出 Schema、提示词模板、校验预览、来源和不确定性。
- [ ] 生成接口不写入 `SKILLS_DIR`，不导入或执行 assembler。
- [ ] 新建草稿为原子操作，`source_type=ai_generated`，生成元数据不进入正式 Skill 包。
- [ ] AI 优化基于 draft_id + expected_revision，接受前只展示 diff；冲突返回 409 且不覆盖内容。
- [ ] 未发布指标、畸形 JSON/YAML、未知文件路径、敏感信息和危险 Python 均被 blocking gate 拒绝。
- [ ] 输入指标校验和样例取数结果单独展示，不与路由/答案评测混为一项。
- [ ] 可选路由评测不导入 Python；可选行为评测在无生产凭证的隔离执行器中运行。
- [ ] 人工确认前不能物化、启用或发布 AI 生成的 Skill。
- [ ] AI 不可用时可继续走手动创建流程。
- [ ] 每次生成可按 generation_id 追溯模型 scene、prompt 版本、指标版本、内容哈希、引用和不确定性。

## 2.12 成功指标

- 从开始描述到保存首个草稿的中位时长下降 ≥ 50%。
- AI 草稿人工接受率 ≥ 60%。
- 接受后的草稿首次结构校验无 blocking 比例 ≥ 80%。
- AI 生成内容因安全规则被拒绝的案例 100% 不进入运行时目录。
- 因 AI 优化造成的未提示覆盖冲突为 0。

## 2.13 分阶段

- **P1**：AI 候选生成、严格 DTO、预览、原子存草稿、来源追溯、指标和安全静态门禁、降级流程。
- **P2**：基于 revision 的 AI 优化/diff、候选隔离制品、无代码导入的路由评测、隔离行为评测。
- **P3**：基于真实回归资产迭代生成质量；优化 prompt、验证器和生成成功指标。

---

# 意见 3：从 policy-qa 真实使用挖掘 Skill 回归数据

## 3.1 背景与目标

当前评测用例主要靠人工维护，容易脱离真实用户问题。目标是从 policy-qa 真实问答中收集 Skill 错误：用户主动标记“回答有误”，或评测者从 `/qa-history` 选择异常问答，进入统一问题案例池；AI 辅助归因错误维度并生成结构化回归候选，人工修改确认后形成对应评测资产，逐步纳入发布门禁。

这里的 Skill 错误覆盖路由、计算、政策内容、引用、回答质量和安全问题。统一入口不意味着统一断言结构；不同问题必须由对应评测器验证。

## 3.2 用户故事

- 作为 policy-qa 用户，我可以对某一轮回答标记“回答有误”、选择原因并补充说明，系统将该轮问答归入实际处理它的 Skill。
- 作为 Skill 评测者，我可以从 `/qa-history` 单选或批量选择问答加入案例池，并看到来源 Skill、脱敏快照和当前处理状态。
- 作为 Skill 评测者，我可以让 AI 提出错误维度、根因和回归断言，人工修改后确认。
- 作为 Skill 维护者，我可以看到每个确认案例对应的失败版本、修复版本和最近回归结果，验证同类问题是否复发。

## 3.3 稳定问答轮次标识（前置依赖）

现有前端消息没有稳定 `message_id`，后端历史以 task 为问答轮次且只保存回答摘要。本需求统一新增公开、稳定的 `qa_turn_id`：

1. Policy QA 开始处理请求时由服务端生成 `qa_turn_id`，并与该轮 task 一一对应。
2. SSE `result` 和 `done` 事件都返回 `qa_turn_id`；前端 assistant 消息保存该字段。
3. `/policy-qa/history` 在每条 QA task 中返回 `qa_turn_id`、`selected_skill_id` 和允许展示的脱敏问答摘要。
4. 反馈接口只接收 `qa_turn_id`，由服务端读取来源数据并校验用户/租户访问权；不得信任客户端回传的 question、answer 或 selected_skill_id。
5. 案例池保存脱敏快照和来源哈希，用于历史数据过期后复现；原始患者上下文不复制到评测存储。

## 3.4 流程

```text
policy-qa 回答旁“回答有误”
  → reason_code + 可选说明 + qa_turn_id ─────────┐
                                                  ├→ 统一 Skill 问题案例池
/qa-history 评测者单选/批量加入 qa_turn_id ───────┘
                          ↓
服务端校验来源权限 → 读取真实问答 → 脱敏 → 去重 → 记录实际 selected_skill_id
                          ↓
案例池管理页 /skills/eval-mining
                          ↓
人工初筛或 POST .../{pool_id}/transform（ModelGateway scene=skill_eval_transform）
  → error_dimension + root_cause + target_skill_id + typed_case_proposal
                          ↓
人工修改并确认错误维度、目标 Skill 和断言
                          ↓
  routing ───────────────→ 现有 SkillEvalCase
  calculation/content/
  citation/quality/safety → SkillRegressionCase
                          ↓
对应评测器重复执行 → 关联失败版本/修复版本 → 逐步纳入发布门禁
```

## 3.5 反馈原因与错误归因

用户反馈原因采用可理解的 UI 文案，后端映射为稳定枚举：

| UI 原因 | `reason_code` | AI 默认候选维度 |
|---------|---------------|------------------|
| 找错了处理能力/答非所问 | `wrong_route` | `routing` 或 `answer_quality` |
| 金额或计算过程不对 | `wrong_calculation` | `calculation` |
| 政策说法或适用条件不对 | `wrong_policy_content` | `policy_content` |
| 来源缺失或引用不对 | `wrong_citation` | `citation` |
| 回答遗漏关键信息 | `incomplete_answer` | `answer_quality` |
| 包含敏感信息或不安全操作 | `unsafe_answer` | `safety` |
| 其他 | `other` | `other` |

`reason_code` 只是用户观察，不直接决定最终错误维度。AI 只能给出候选，最终以有 `skill:evaluate` 权限的人工确认结果为准。即使最终维度为 `routing`，案例仍归属于产生该回答的 Skill，同时记录人工确认的目标 Skill。

## 3.6 前端改动

| 文件 | 改动 |
|------|------|
| `src/components/policy-qa/policy-agent-answer.tsx` | **新增**：每条 assistant 回答展示“回答有误”，提交 qa_turn_id、reason_code 和可选说明；成功后防重复提交 |
| `src/lib/policy-qa-session.ts` | **扩展**：`PolicyQAChatMessage` 增加 `qaTurnId`、`selectedSkillId` 和反馈状态 |
| `app/qa-history/page.tsx` | **新增**：评测者按 qa_turn_id 单选/批量加入案例池；显示脱敏摘要和处理状态 |
| `app/skills/eval-mining/page.tsx` | **新建**：案例池列表、筛选、分诊、AI 转换、人工确认、拒绝和回归状态 |
| `src/components/skills/eval-case-pool-list.tsx` | **新建**：状态、错误维度、来源 Skill、创建人、更新时间和最近评测结果 |
| `src/components/skills/eval-case-editor.tsx` | **新建**：编辑 target_skill_id、错误维度及对应的类型化断言；原始敏感上下文不可见 |
| `src/lib/api-client.ts` | **新增**反馈、批量加入、列表、转换、确认、拒绝 API；对齐 snake_case/camelCase 转换 |

## 3.7 后端接口与 DTO

**Policy QA 接口调整**（`policy_qa_routes.py`）：

```text
POST /api/v1/medical-insurance-ai-agent/policy-qa/feedback
  权限: 已登录用户；只能反馈本人可访问 qa_turn_id
  Header: Idempotency-Key
  入参 PolicyQAFeedbackRequest: {
    qa_turn_id: str,
    reason_code: FeedbackReasonCode,
    comment?: str
  }
  出参: SkillEvalCasePoolResponse（201；重复幂等请求返回同一 pool_id）
```

**Skill 案例池接口**（`infra_skill_routes.py`）：

```text
GET /api/v1/.../infra-skills/eval-case-pool
  权限: skill:evaluate
  查询: status + error_dimension + target_skill_id + limit + offset

POST /api/v1/.../infra-skills/eval-case-pool/from-history
  权限: skill:evaluate
  Header: Idempotency-Key
  入参: { qa_turn_ids: list[str] }

POST /api/v1/.../infra-skills/eval-case-pool/{pool_id}/transform
  权限: skill:evaluate
  入参: { expected_revision: int }
  出参 SkillEvalTransformResponse: {
    error_dimension: SkillErrorDimension,
    root_cause: str,
    target_skill_id: str,
    case_proposal: SkillRegressionCaseProposal,
    provenance: {...},
    citations: list[Citation],
    uncertainties: list[str],
    revision: int
  }

POST /api/v1/.../infra-skills/eval-case-pool/{pool_id}/confirm
  权限: skill:evaluate
  Header: Idempotency-Key
  入参: {
    expected_revision: int,
    error_dimension: SkillErrorDimension,
    target_skill_id: str,
    case_proposal: SkillRegressionCaseProposal
  }
  出参: { pool: SkillEvalCasePoolResponse, eval_case_ref: EvalCaseRef }

POST /api/v1/.../infra-skills/eval-case-pool/{pool_id}/reject
  权限: skill:evaluate
  入参: { expected_revision: int, rejection_reason: str }
```

确认接口按 `error_dimension` 分流：

- `routing`：调用现有 `SkillGovernanceService.create_case`，写入 `SkillEvalCase`；`source_type=policy_qa_feedback`，`source_ref=qa_turn_id`。
- 其他可执行维度：写入 `SkillRegressionCase`。
- `other`：不能确认成可执行评测用例，必须先人工选择具体维度或拒绝。

## 3.8 类型化回归断言

`SkillRegressionCaseProposal` 使用 Pydantic discriminated union，API 不暴露无约束的裸 JSON：

- `CalculationCaseProposal`：脱敏输入模板、输出字段、期望值、容差、舍入规则。
- `PolicyContentCaseProposal`：适用条件、政策/条款引用、必含事实、禁止结论、政策版本。
- `CitationCaseProposal`：期望来源 ID、最低引用数、每个关键结论是否必须有支撑。
- `AnswerQualityCaseProposal`：answerability、必含/禁含内容、人工评分 rubric。
- `SafetyCaseProposal`：期望脱敏字段、应拦截动作、期望 `waiting_human_confirmation` 或不确定性声明。

AI 不得把历史系统回答直接当作 expected。expected 只能来自可追溯政策/结构化事实、确定性计算结果或人工确认；证据不足时必须返回 `uncertainties` 并要求人工补充。

## 3.9 数据模型

### 3.9.1 新表 `skill_eval_case_pool`

| 字段 | 类型 | 说明 |
|------|------|------|
| `pool_id` | str pk | 案例池 ID |
| `tenant_id` | str | 租户隔离键 |
| `source_type` | enum | `policy_qa_feedback` / `qa_history_selection` |
| `source_qa_turn_id` | str | 稳定问答轮次 ID |
| `source_session_id` | str | 来源会话，仅用于追溯 |
| `source_hash` | str | 脱敏快照内容哈希，用于去重和追溯 |
| `source_selected_skill_id` | str? | 当时实际执行的 Skill |
| `sanitized_question` | text | 脱敏问题快照 |
| `sanitized_answer_excerpt` | text | 脱敏回答摘要；不默认复制完整回答 |
| `feedback_reason` | enum | 稳定 `reason_code` |
| `feedback_comment` | text? | 限长并脱敏的用户说明 |
| `error_dimension` | enum? | AI 候选/人工最终确认维度 |
| `target_skill_id` | str? | 最终归因或期望处理 Skill |
| `status` | enum | `pending_triage / transformed / confirmed / rejected` |
| `transformed_payload` | jsonb? | 类型化 proposal 的持久化结果 |
| `transform_provenance` | jsonb? | 模型、prompt、输入哈希、引用和不确定性 |
| `eval_case_type` | str? | `route` 或 regression case 类型 |
| `eval_case_id` | str? | 确认后生成的评测资产 ID |
| `revision` | int | 乐观锁 |
| `created_by / transformed_by / confirmed_by` | str? | 操作人追溯 |
| `created_at / updated_at / confirmed_at` | datetime | 时间追溯 |
| `rejection_reason` | text? | 拒绝原因 |
| `deleted_at` | datetime? | 软删除/保留策略 |

唯一约束：`(tenant_id, source_qa_turn_id)`，同一问答轮次无论来自用户反馈还是历史选取，都只创建一个案例；重复提交返回已有 pool_id。必要时由评测者在同一案例内追加反馈原因，不复制问答正文。

### 3.9.2 新表 `skill_regression_cases`

| 字段 | 类型 | 说明 |
|------|------|------|
| `case_id` | str pk | 回归案例 ID |
| `target_skill_id` | str | 负责修复并接受回归约束的 Skill |
| `case_type` | enum | calculation / policy_content / citation / answer_quality / safety |
| `input_template` | jsonb | 脱敏、可重复执行的输入模板 |
| `expected_assertions` | jsonb | 由 discriminated union 校验的类型化断言 |
| `source_type / source_ref` | str | 来源案例池和 qa_turn_id |
| `required / enabled` | bool | 是否纳入发布门禁、是否启用 |
| `evaluator_status` | enum | `available / blocked_by_evaluator`；评测器可用性，不参与案例池状态机 |
| `risk_tags / business_tags` | text[] | 风险与业务标签 |
| `created_by / created_at / updated_at` | str/datetime | 审计字段 |

路由维度继续复用 `skill_eval_cases`；`skill_regression_cases` 只承载非路由回归，避免改变现有路由评测和发布门禁语义。

## 3.10 状态机、幂等与并发

```text
pending_triage → transformed → confirmed
       │              │
       └──────────────┴→ rejected
```

- `transform`、`confirm`、`reject` 必须校验 expected_revision；过期返回 409。
- AI 转换失败时保持原状态和原 revision，可重试，不产生半转换数据。
- `confirm` 使用 pool_id 作为业务幂等键；重试返回同一 eval_case_id。
- 已 confirmed 的案例不可重新转换；需修订时复制为新 revision/新案例，不修改已经进入历史评测快照的资产。
- `target_skill_id` 可以是当前实际 Skill、人工选择的其他 Skill，或在路由“不应接管”场景下为空；归档 Skill 的历史案例保留但默认不进入新评测运行。

## 3.11 隐私、权限与审计

- 普通用户反馈时，服务端按认证上下文校验 qa_turn_id 所属用户和租户。
- `/qa-history` 批量选取、AI 转换、确认、拒绝只允许 `skill:evaluate`。
- 从来源任务读取数据后先脱敏，再写案例池和调用 ModelGateway；模型不得接收患者姓名、身份证号、手机号、结算号等原始标识。
- 案例池与评测资产不保存完整患者上下文；需要字段值时使用合成值、区间、占位符或不可逆脱敏值。
- 保存 transform/confirm 操作的操作者、模型证据、来源哈希和 audit_event。
- 定义保留期限：未确认案例默认保留 90 天；confirmed 案例随评测资产保留；来源用户依法删除时按治理策略解除来源关联并保留匿名化回归模板。

## 3.12 异常与降级

- 来源 qa_turn_id 不存在或不属于当前用户/租户：返回 404 或 403，不泄露是否存在其他用户数据。
- 历史记录只有摘要且不足以生成断言：保持 `pending_triage`，提示评测者补充证据，不让 AI 猜 expected。
- ModelGateway 不可用或输出不合法：案例保留，可人工分型和编辑，不阻塞收集。
- AI 推断 target_skill_id 不存在：返回 uncertainty，由人工选择；允许路由“不应由任何 Skill 接管”的空目标场景。
- 脱敏失败或仍检测到敏感信息：阻断入池/转换并记录安全审计。
- 对应非路由评测器尚未实现：案例可 confirmed，但其 `evaluator_status=blocked_by_evaluator`，不得显示为“已验证”或用于通过发布门禁。

## 3.13 验收标准

- [ ] Policy QA 每轮回答都有服务端生成的 qa_turn_id，SSE result/done、前端消息和 QA history 一致。
- [ ] 用户可对本人问答提交任一 reason_code；路由、计算、政策内容、引用、回答质量和安全错误均进入统一案例池。
- [ ] 服务端从 qa_turn_id 读取来源数据，拒绝客户端伪造 question、answer 和 selected_skill_id。
- [ ] 入池前完成租户/用户权限校验、脱敏和去重；重复反馈返回同一 pool_id。
- [ ] AI 返回错误维度、根因、目标 Skill、类型化回归候选、来源和不确定性；人工可以修改后确认。
- [ ] `routing` 确认后写入现有 SkillEvalCase；非路由维度写入 SkillRegressionCase；`other` 不得直接确认成可执行用例。
- [ ] 计算、政策内容、引用、回答质量和安全案例分别具有可执行的类型化断言，不能只保存自然语言 expected。
- [ ] confirm 重试不产生重复 eval case；revision 冲突返回 409。
- [ ] 跨用户/跨租户反馈和案例读取被拒绝；评测存储和模型输入中不出现患者原始敏感信息。
- [ ] 评测器未实现的案例明确显示 `blocked_by_evaluator`，不产生虚假的“已通过”。
- [ ] 已实现评测器的 confirmed 案例可关联失败版本、修复版本和最近一次结果，并可配置为发布必测项。

## 3.14 成功指标

- 真实使用案例占新增回归资产比例 ≥ 50%。
- 用户反馈成功入池率 ≥ 99%，重复案例率 ≤ 2%。
- AI 错误维度经人工确认后无需修改的比例 ≥ 70%。
- confirmed 案例中具备可执行断言的比例 = 100%。
- confirmed 案例的最近一次回归状态可追溯率 = 100%。
- 敏感信息进入评测资产或 ModelGateway 的事件数 = 0。

## 3.15 分阶段

- **P1**：qa_turn_id 全链路、反馈入口、qa-history 选取、案例池 ports/adapter、权限/脱敏/去重、列表与人工分诊。
- **P2**：AI 分型与转换、类型化 proposal、人工编辑确认；路由案例接入现有 SkillEvalCase，非路由案例写入 SkillRegressionCase。
- **P3**：计算/政策内容/引用/答案质量/安全评测器，失败版本—修复版本追溯，按风险逐步接入发布门禁和批量转换。

---

## 4. 跨需求非功能要求

### 4.1 LLM 可靠性与成本

- description、comment、历史问答和现有草稿均设置长度上限；超长内容拒绝或显式摘要。
- 每个 scene 配置模型路由、超时、最大 token、最多一次结构修复重试和并发限制。
- 记录调用成功率、解析失败率、超时率、token 用量、人工接受率和人工纠正率。
- ModelGateway 不可用时保留所有手动路径；任何 LLM 故障都不能阻塞案例收集或草稿人工编辑。

### 4.2 来源与版本追溯

- AI 编写冻结输入指标的 metric_code、对象版本和状态快照。
- 案例转换冻结 qa_turn_id、脱敏来源哈希、当时 selected_skill_id、模型/prompt 版本和人工确认 revision。
- 评测运行继续冻结 suite revision、用例快照、候选/基线版本和配置哈希。

### 4.3 可观测性

- 新增指标：生成请求数/成功率/拒绝率、危险代码命中数、案例入池数、各错误维度分布、转换成功率、确认率、评测器阻塞数。
- 所有生成、转换、确认、拒绝、物化和发布动作关联 audit_event；日志不输出原始问答或生成脚本全文。

---

## 5. 验证策略

严格按 **单元测试 → API 测试 → Flow 测试** 顺序执行；涉及前端后再执行组件测试、构建和浏览器 E2E。[来源: `docs/governance/TEST-VERIFICATION-MATRIX.md`]

### 5.1 单元测试

- AI DTO 严格解析、畸形输出修复一次后失败。
- proposal_hash、文件路径白名单、文件大小、AST allowlist、敏感信息扫描。
- published 指标及对象版本校验。
- SkillDraftSourceType、revision 冲突和生成元数据不物化。
- qa_turn_id 映射、反馈 reason_code、案例池状态机、去重和确认幂等。
- 各类 `SkillRegressionCaseProposal` 判别联合和断言校验。
- 脱敏后仍含敏感模式时阻断。

### 5.2 API 测试

- AI 生成/优化/接受 DTO、权限、401/403/409/422/模型异常契约。
- feedback 所有权、跨用户/租户拒绝、Idempotency-Key。
- 案例池分页筛选、transform/confirm/reject revision 冲突。
- route 与 regression case 分流正确，confirmed 重试不重复写入。
- API 错误统一 `{error_code, message, audit_event}`。

### 5.3 Flow 测试

- 创建：自然语言+指标 → AI 提案 → 接受草稿 → 校验 → 候选隔离 → 人工确认。
- 优化：读取 revision → AI diff → 并发修改导致 409 → 重新加载后接受。
- 路由错误：Policy QA → 反馈 → 入池 → 转换 → 人工确认 → SkillEvalCase → 路由回归。
- 计算/政策内容错误：反馈 → 类型化断言 → SkillRegressionCase → 对应评测器失败 → 修复后通过。
- 安全：提示词注入、危险 Python、敏感问答均不能进入运行时或模型输入。

### 5.4 前端验证

- Vitest：生成状态、diff、错误降级、反馈 reason、重复提交、案例分型编辑。
- Next.js build 和变更文件 ESLint 零新增错误。
- 浏览器 E2E：AI 创建、AI 优化、回答反馈、案例确认各一条主链路；验证 390px 无横向溢出和键盘可操作。

---

## 6. 推进顺序（总体）

1. **意见 4（IA 方案 A）**：详情页瘦身、评测/发布归顶层列表，作为页面信息架构基础。
2. **共同前置 P0**：qa_turn_id、AI 候选不执行原则、候选隔离方案、权限/脱敏/审计 DTO 定稿。
3. **意见 2（AI 编写）**：P1 → P2 → P3。
4. **意见 3（评测挖掘）**：P1 可与意见 2 P1 后半段并行；P2/P3 复用评测资产和候选隔离能力。

每阶段只拆分最小可验证用户故事，并按单元测试 → API 测试 → Flow 测试提交证据。P1 不得以“页面可操作”代替安全、隐私、幂等和跨层契约验收。

---

## 7. 待复审确认项

以下决策已在 V1.1 中给出推荐默认值，复审时只需确认是否接受：

1. AI 代码先进入隔离制品区，通过校验/评测/人工确认后才进入运行时目录。
2. 所有回答错误统一归入 Skill 案例池，但按错误维度形成不同评测资产。
3. 路由继续复用 `SkillEvalCase`；非路由新增 `SkillRegressionCase`，不改变现有 top1_accuracy 语义。
4. 统一使用服务端 `qa_turn_id`，不采用前端临时 message_id。
5. 案例池只保存脱敏快照和来源哈希，不复制患者原始上下文。
6. 非路由评测器未实现前，案例允许确认但标记 `blocked_by_evaluator`，不能宣称已验证。
