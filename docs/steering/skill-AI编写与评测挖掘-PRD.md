# Skill 模块演进 PRD：AI 编写 + 评测挖掘

> **定位**：Skill 管理模块（`src/apps/portal/app/skills/`）两项演进需求的 PRD。
> **前提**：意见 4 已选方案 A（详情工作区瘦身，只留 概览+版本；评测/发布 只看顶层列表页）。本 PRD 的新页面挂载基于此 IA。
> **设计依据**：`skill-workbench-implementation-plan.md`、`语义层设计文档.md`、`医保Agent-政策问答前端改造设计-V1.0.md`
> **状态**：📋 待评审（未动代码）

---

## 共同约束（遵循 AGENTS.md）

- 所有 LLM 调用**必须走 `model_service.gateway.ModelGateway`**，禁止直接 HTTP
- 新存储遵循 ports/adapter，默认 PostgreSQL，`USE_MEMORY_STORAGE=1` 可回退内存
- 领域概念命名遵循 `src/domain/AGENTS.md` 通用语言字典，新增概念同步更新
- 「业务指标」= 语义层标准指标（`MetricSourceBinding` 体系，`GET /semantic/metrics`），**不是**评测指标（top1_accuracy）

---

# 意见 2：AI 编写 Skill（脚本 + Schema + 提示词模板）

## 2.1 背景与目标

当前 `/skills/new` 是人工填表 + `/skills/[id]/edit` 手改 YAML/脚本，全程人工，效率低、门槛高。

**目标**：用户用自然语言描述需求 + 选择已发布业务指标，**大模型自动生成 skill 的 assembler 脚本、输入/输出 schema、提示词模板、基础 config**；人只做审核确认。生成后**可选**跑一次评测验证（不强制）。

## 2.2 用户故事

- 作为 skill 作者，我描述"做一个解释统筹自付的技能"+ 选定相关业务指标，AI 返回完整可用的 skill 草案，我审核脚本/模板/schema 后一键存草稿，无需手写代码。
- 作为 skill 维护者，我对已有草稿点「AI 优化」，AI 基于现有内容 + 新需求重新生成，我 diff 确认。

## 2.3 流程

```
/skills/new（对话式创建）
  ① 需求描述（自然语言）
  ② 选择已发布业务指标（GET /semantic/metrics，多选）
        ↓
POST /infra-skills/ai-generate （走 ModelGateway）
  → assembler 脚本(Python) + input/output schema(JSON) + 提示词模板(YAML) + config.yaml
        ↓
前端展示生成结果（详情 + 各文件只读预览）
        ↓
③ 可选：跑一次评测（POST /infra-skills/{id}/eval-runs，用选定指标关联用例）—— 不强制
        ↓
④ 人确认：✅ 接受→存草稿  ·  🔄 重新生成  ·  ✏️ 去 edit 精修
```

## 2.4 前端改动

| 文件 | 改动 |
|------|------|
| `app/skills/new/page.tsx` | **改造**：从表单式 → 对话式（需求输入 + 指标多选 + 生成按钮 + 结果预览 + 确认） |
| `app/skills/[skillId]/edit/page.tsx` | **新增**「AI 优化」按钮（基于现有草稿 + 新需求重新生成，展示 diff） |
| `src/components/skills/ai-skill-generator.tsx` | **新建**：生成交互组件（需求/指标输入、调用生成、loading/错误态） |
| `src/components/skills/skill-draft-preview.tsx` | **新建**：生成结果预览（assembler/schema/prompt_template/config 分页或分栏只读展示 + 可选 diff） |
| `src/lib/api-client.ts` | **新增** `generateSkillWithAI({description, metric_codes, base_skill_id?})`、`optimizeSkillWithAI(draft_id, {description, metric_codes})` |

## 2.5 后端改动

**新接口**（`src/runtime/api/infra_skill_routes.py`）：

```
POST /api/v1/medical-insurance-ai-agent/infra-skills/ai-generate
  入参: { description: str, metric_codes: list[str], base_skill_id?: str }
  出参: {
    skill_name_suggestion: str,
    assembler_script: str,          # Python，含 _FACT_FIELD_MAP 对齐选定指标
    input_schema: dict, output_schema: dict,
    prompt_template: str,           # YAML 文本
    config_yaml: str,               # business_action/object 挂载
    generation_notes: str           # AI 说明/不确定性
  }
```

**实现层**（新建 `src/runtime/skill_management/ai_authoring/`）：
- `service.py`：编排（取指标定义 → 构造 prompt → 调 ModelGateway → 解析输出）
- `prompts.py`：prompt 工程，参考 `writing-skills` 的 skill 结构 + 本项目 assembler/schema 约定 + 选定指标的 `metric_code`（注入语义层编码，满足 assembler 版本准入守卫）
- **必须走 `ModelGateway`**，异常走 `model_service/exceptions` 分类

**评测验证（可选）**：复用现有 `POST /infra-skills/{skill_id}/eval-runs`（生成结果存为草稿/版本后即可跑）

**指标查询**：复用 `GET /semantic/metrics`（已有，返回 `MetricSummary` 列表）

## 2.6 数据模型

**无新表**。生成结果确认后写入现有 `SkillDraft`（structured_config + 脚本/schema 物化时落 skills/ 目录）。

## 2.7 依赖与约束

- `ModelGateway` 可用（需配置 `MODEL_API_KEY`）；不可用时前端降级提示"AI 生成暂不可用，可手动创建"
- 选定的业务指标必须为**已发布**状态（assembler 版本准入守卫要求）
- AI 生成内容须标注 `generation_notes`/不确定性（来源可追溯约束）

## 2.8 验收标准

- [ ] 描述需求 + 选指标 → AI 返回 4 类文件（脚本/schema×2/模板/config）
- [ ] 生成结果可一键存为草稿，进入 edit 页精修
- [ ] 可选跑评测，结果可查看
- [ ] edit 页「AI 优化」能基于现有草稿重新生成
- [ ] AI 不可用时降级，不阻塞手动创建

## 2.9 分阶段

- **P1**：后端 `ai-generate` 接口（prompt 工程 + gateway）+ 前端 new 页对话式生成 + 预览 + 存草稿
- **P2**：edit 页「AI 优化」+ 可选评测验证
- **P3**：生成质量迭代（借鉴 writing-skills 的 baseline→生成→验证思路）

---

# 意见 3：从 policy-qa 真实使用挖掘评测数据

## 3.1 背景与目标

当前评测用例人工维护，脱离真实用户问题。目标：从 **policy-qa 真实问答**中，用户标记「回答有误」+ 从 `/qa-history` 统计选出 → **AI 自动转成结构化评测用例**（推断 expected）→ 人工可改 → 入评测用例集。

## 3.2 用户故事

- 作为用户，我在 policy-qa 看到错误回答，点「回答有误」并选原因，系统收集为案例。
- 作为 skill 评测者，我从 `/qa-history` 统计中选出可疑问答加入案例池。
- 作为 skill 评测者，AI 把案例转成评测用例（question + 推断的 expected_skill），我在页面手动改 expected 后确认入库。

## 3.3 流程

```
policy-qa 回答旁「回答有误」按钮（选 reason）──┐
                                              ├→ 问题案例池(新存储)
/qa-history 统计页「加入案例池」操作 ──────────┘
                        ↓
案例池管理页（/skills/eval-mining）
                        ↓
POST .../eval-case-pool/{id}/transform （走 ModelGateway）
  → 结构化用例：question_template + expected_skill_id（AI 推断）
                        ↓
人工在页面改 expected → 确认
                        ↓
入评测用例集（SkillEvalCase），用于后续 skill 评测
```

## 3.4 前端改动

| 文件 | 改动 |
|------|------|
| `app/policy-qa/page.tsx` | **新增**：每条回答加「回答有误」反馈按钮 + reason 选择（单条问答粒度） |
| `app/qa-history/page.tsx` | **新增**：「加入案例池」操作（单条或批量） |
| `app/skills/eval-mining/page.tsx` | **新建**：案例池管理页（浏览待转化案例 → AI 转化 → 编辑 expected → 确认入库） |
| `src/components/skills/eval-case-pool-list.tsx` | **新建**：案例池列表 + 状态（待转化/已转化/已确认） |
| `src/components/skills/eval-case-editor.tsx` | **新建**：转化后的用例编辑（question 只读 + expected 可改） |
| `src/lib/api-client.ts` | **新增** `markAnswerWrong(session_id, message_id, reason)`、`listEvalCasePool()`、`addToEvalCasePool(session_id, message_id)`、`transformEvalCase(pool_id)`、`confirmEvalCase(pool_id, {expected_skill_id})` |

## 3.5 后端改动

**新接口**（`infra_skill_routes.py` + `policy_qa_routes.py`）：

```
POST /api/v1/.../policy-qa/feedback           # 标记回答有误 → 写案例池
  入参: { session_id, message_id, reason }

GET  /api/v1/.../infra-skills/eval-case-pool   # 案例池列表（按状态过滤）
POST /api/v1/.../infra-skills/eval-case-pool   # 从 qa-history 手动加入
  入参: { session_id, message_id }

POST /api/v1/.../infra-skills/eval-case-pool/{id}/transform   # AI 转化（走 ModelGateway）
  出参: { question_template, expected_skill_id, transform_notes }

POST /api/v1/.../infra-skills/eval-case-pool/{id}/confirm     # 确认入库
  入参: { expected_skill_id }（人工可能改过）
  → 写入 SkillEvalCase 集
```

**实现层**（新建 `src/runtime/skill_management/eval_mining/`）：
- `service.py`：案例池 CRUD + 转化编排
- `prompts.py`：案例 → 用例的 prompt（从 question + 系统回答 + reason 推断 expected_skill，匹配已注册 skill 目录）
- 走 `ModelGateway`

## 3.6 数据模型

**新表 `skill_eval_case_pool`**（PostgreSQL，ports/adapter）：

| 字段 | 类型 | 说明 |
|------|------|------|
| pool_id | str pk | |
| source_session_id | str | 来源 policy-qa 会话 |
| source_message_id | str | 来源问答消息 |
| question | text | 用户原始问题 |
| system_answer | text | 系统当时的回答 |
| feedback_reason | str | "回答有误"原因 / "qa-history 手选" |
| status | enum | pending / transformed / confirmed / rejected |
| transformed_question_template | text? | AI 转化后 |
| transformed_expected_skill_id | str? | AI 推断 + 人工可改 |
| eval_case_id | str? | 确认后写入 SkillEvalCase 的 id |
| created_at / updated_at | datetime | |

转化结果**复用** `SkillEvalCase`（question_template + expected_skill_id）。

## 3.7 依赖与约束

- policy-qa 问答需有稳定 `session_id` / `message_id` 标识（确认现有结构）
- `ModelGateway` 可用
- 推断的 `expected_skill_id` 必须命中已注册 skill 目录（否则提示人工选）

## 3.8 验收标准

- [ ] policy-qa 单条回答可标记「有误」+ reason → 进案例池
- [ ] qa-history 可选问答加入案例池
- [ ] 案例池页可触发 AI 转化，返回 question + 推断的 expected
- [ ] expected 可在页面手动修改
- [ ] 确认后写入评测用例集，在评测记录页可见

## 3.9 分阶段

- **P1**：反馈入口（policy-qa 按钮 + qa-history 选取）+ 案例池存储与列表
- **P2**：AI 转化 + expected 编辑 + 确认入评测用例集
- **P3**：转化质量迭代（reason 分类、批量转化）

---

## 推进顺序（总体）

1. **意见 4（IA 方案 A）**：详情页瘦身、评测/发布归顶层列表 —— 先做，是 IA 基础
2. **意见 2（AI 编写）**：P1→P2→P3
3. **意见 3（评测挖掘）**：P1→P2→P3（依赖评测用例集，与意见 2 的评测验证呼应）

> 待评审通过后，按阶段拆 issue 实施。每阶段遵循 AGENTS.md 的 单元测试→API 测试→Flow 测试 验证流程。
