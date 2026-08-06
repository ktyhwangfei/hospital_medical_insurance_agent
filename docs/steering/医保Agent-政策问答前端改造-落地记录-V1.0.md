# 医保 Agent · 政策问答前端改造 — 落地记录（V1.0）

> **版本**：V1.0 ｜ **日期**：2026-08-04 ｜ **状态**：已落地
> **定位**：`docs/steering/医保Agent-政策问答前端改造设计-V1.0.md`（设计稿）的落地记录。记录实际实现、演进决策（ADR）、当前架构、配置要求与已知问题，供后续维护者快速对齐"系统现状"。
> **范围**：政策问答前端持续对话改造 + 后端 skill 驱动迁移 + 多轮质量修复（2026-08-03 ~ 2026-08-04）。

---

## 一、演进脉络（从设计稿到当前现状）

```
设计稿 V1.0（2026-08-03）
  ↓ 阶段一：usePolicyQAStream + 三区工作区 + 会话跨轮
  ↓ 阶段二：Runtime 可视化（锚点带 / 记忆面板 / 推理链）
  ↓ 修复：MSSQL 环境变量（查询无结果）→ POSTGRES 默认值（记忆不沉淀）→ subject_changed 误判
  ↓ P0/P1/P2 优化：dummy 降级 / 来源徽标 / 记忆键值 / 话题锚点 / 双视角（后移除）
  ↓ 严肃化 + 回答价值门控（无价值拒绝，引导咨询医保办）
  ↓ ★ 架构迁移：SSE 对话流接入 Skill 驱动执行（旧编排器退役）   ← 当前形态
```

**核心结论**：设计稿的"持续对话 + Runtime 可视化"骨架全部落地；回答生成路径从"旧编排器（orchestrator）"迁移到"Skill 策略引擎（assembler + Strategy）"，产品层只剩路由与事件转发。

---

## 二、当前架构

### 2.1 请求处理链路（/policy-qa/stream，Skill 驱动五步）

```
POST /api/v1/medical-insurance-ai-agent/policy-qa/stream
  ├─ ensure_session_and_workflow（PostgreSQL 持久化，失败不阻塞）
  ├─ runtime_bridge.prepare_turn → SSE: context_need（含 settlement_id/topic/memory_ids）
  ├─ Step 1 intent_detection      → 关键词 → target_fee_item（deductible/pooling_self_pay/...）
  ├─ Step 2 skill_routing         → route_question() → skill_id（settlement_explain_skill）
  ├─ Step 3 settlement_query      → settlement_data_provider.get_settlement_context()（真实 SQL）
  │                                 → runtime_bridge.record_step → SSE: memory_update(SETTLEMENT) + reasoning_step(fact)
  ├─ Step 4 policy_rule_search    → assembler.build_policy_queries() + retrieve_policy_evidence()（Milvus 结构化检索）
  │                                 → SSE: memory_update(POLICY) + reasoning_step(fact)
  ├─ Step 5 skill_execution       → assembler.execute()（Strategy 策略引擎：LLM 生成 / dummy 降级）
  │                                 → SSE: reasoning_step(inference)
  ├─ runtime_bridge.finalize_turn → SSE: result（reasoning_chain / memory_count / answer_mode）
  └─ SSE: done
```

- 每步发送 `step` + `trace_event`（前端执行链路展示）。
- 错误路径：`error` 事件（含 message）→ `done`（前端据此展示引导，不静默）。

### 2.2 SSE 事件契约（前端消费）

| 事件 | 内容 | 前端消费 |
|---|---|---|
| `context_need` | object_types / memory_ids / settlement_id / topic / subject_changed | 锚点带、记忆命中标注、主体切换横幅 |
| `step` / `trace_event` | 执行步骤状态 | 对话流执行链路折叠 |
| `memory_update` | 记忆卡（含脱敏 snapshot 业务值） | 左栏记忆面板 |
| `reasoning_step` | 推理步骤（含真实金额 claim） | 推理链折叠（回答上方） |
| `result` | patient_view / office_view / policy_evidence / answer_mode / reasoning_chain / memory_count | AI 回答 + 来源徽标 |
| `error` / `done` | 错误信息 / 结束 | 错误引导 |

> snake_case → camelCase 转换统一在 `usePolicyQAStream`（前端 hook）内完成。

### 2.3 前端结构

```
app/policy-qa/page.tsx → components/policy-qa/
├── policy-qa-workspace.tsx   三区布局（顶栏锚点 + 左栏记忆 + 主区对话流）
├── session-anchor-bar.tsx    业务主体锚点带（结算/话题徽标 + 主体切换横幅）
├── memory-panel.tsx          会话记忆面板（按类型分组 + 业务键值 + 来源标注）
├── chat-stream.tsx           对话流（推理链在回答上方 + 来源徽标 + 输入 @指令）
├── reasoning-chain-collapsible.tsx  推理链折叠
└── lib/
    ├── policy-qa-session.ts      类型 + snake→camel 转换 + 纯函数 reducer（可单测）
    └── use-policy-qa-stream.ts   SSE hook（session_id 跨轮复用，自解析事件）
```

---

## 三、关键决策记录（ADR）

### ADR-1：SSE 对话流迁移到 Skill 驱动执行（旧编排器退役）
- **背景**：设计落地初期，`/policy-qa/stream`（对话流）走旧编排器 `PolicyQAOrchestrator`（仅 `route_question` 标记 skill_id，从不执行 skill）；`/policy-qa/settlement-explanation`（richResult）走 skill 但受 `DATA_SOURCE_MODE=mock` 限制从未真正执行。**skill 从未在任何可用路径生效**。
- **决策**：`_policy_qa_stream` 重写为 skill 五步流程（provider 查结算 → skill 查询计划检索 → `assembler.execute`），保留完整 SSE 契约；删除 `_init_search_engine` 等旧编排器死代码（净 -72 行）。
- **收益**：回答质量与 richResult 统一（同一 skill 策略引擎）；响应从 30s+（每次加载 embedding 模型）降到 ~1.3s（skill 查询计划走结构化检索，不加载 embedding）；产品层只剩路由与事件转发。
- **代价**：需 `DATA_SOURCE_MODE=real_db`（`start-servers.ps1` 已注入）。

### ADR-2：dummy 模式统一降级为真实数据模板（不写死金额）
- **背景**：`MODEL_BASE_URL` 默认 `dummy`，`ModelGateway.generate` 返回固定 mock（写死金额，换结算单即错）—— 医疗场景事故级风险。
- **决策**：skill `PoolingSelfPayStrategy._generate_via_llm` 检测 dummy → `_build_dummy_fallback`（基于真实结算数据的确定性模板 + 诚实引导）；`explanation_generator` 同步兜底（JSON 输出回退占位模板）。
- **效果**：任何场景不输出写死金额；接入真实 LLM 后自动切到模型生成（架构已预留）。

### ADR-3：回答价值门控（无价值拒绝，引导咨询医保办）
- **决策**：`_has_valuable_data` 检查（treatment 金额 + 统筹自付类问题的分段完整性）+ 生成后文本检查（含"未获取/待定"→ 拒绝）；orchestrator `can_answer=False` 分支输出统一引导文案。
- **效果**：宁可拒绝也不输出"未获取"半成品 —— 「算不出就明确说算不出，建议携带结算单前往医院医保办或拨打当地医保局热线」。

### ADR-4：双视角移除 + 全页面严肃化
- **决策**：移除患者/院端双视角切换（只输出合适内容）；全页面去 emoji/装饰符号（锚点带、记忆面板、徽标、错误文案全部严肃化）；推理链移到回答文本上方。
- **理由**：医保严肃场景，避免随意的视觉表达。

### ADR-5：修复 strategy 单例缓存串答案 bug
- **背景**：`build_patient_answer` 的 `_cached_llm_output` 缓存在 **strategy 单例**（registry 实例缓存）上 —— 跨请求/跨结算单会串答案（生产 bug），且造成测试污染。
- **决策**：移除缓存，每次请求重新生成。

---

## 四、配置要求

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `MSSQL_HOST/PORT/DATABASE/USER/PASSWORD` | `localhost/1433/bjybdb/sa/<密码见 deploy/docker/.env，已 gitignore>` | 结算数据源（`start-servers.ps1` 注入） |
| `POSTGRES_PASSWORD` | `postgres` | 记忆/持久化（`production.py` 默认值已修正） |
| `DATA_SOURCE_MODE` | `mock`（生产代码默认） | **skill 路径要求 `real_db`**（`start-servers.ps1` 注入） |
| `MODEL_BASE_URL` / `MODEL_API_KEY` | `dummy` | 未配置时走 dummy 降级（真实数据模板）；配置后走真实 LLM |

> 启动统一用 `start-servers.ps1` / `stop-servers.ps1`（AGENTS.md 硬性约定）。

---

## 五、已知问题与遗留（维护参考）

| # | 问题 | 性质 | 修复方向 |
|---|---|---|---|
| 1 | **退休人员统筹分段规则缺失**：Milvus `policy_rules_v2` 统筹分段规则 `psn_type` 均标"在职职工"，退休用户检索不到 → 统筹自付分段无法精确还原（当前行为：诚实引导） | 数据治理 | 补提取退休统筹段规则，或通用基础段 `psn_type` 改为"全部" |
| 2 | **真实 LLM 未接入**：当前为 dummy 降级（真实数据模板），回答为确定性文本非模型生成 | 配置 | 配 `MODEL_BASE_URL`/`MODEL_API_KEY` |
| 3 | 政策检索 `text_must_include_any` 匹配失败（「起付标准至3万元」vs 规则文本「起付标准以上至3万元」） | 代码 | 检索器文本匹配放宽（含"以上/至"变体） |
| 4 | 记忆面板缺 patient/encounter 信息（context_need 未携带，数据链路未接 SQL 结果） | 增强 | context_need 增发（需 bridge 接入结算数据） |
| 5 | 预存测试债：model_service gateway 7 failed（fixture 默认 dummy）、skill_infra 1 failed（描述断言）、CachedSkillStorage 2 failed | 测试 | 按 PROGRESS.md §5 治理 |
| 6 | `/_policy_qa_stream` 不产 `trace_events_list`（skill 流程无 trace_result 步骤）→ result.trace_events 为空 | 轻微 | 如需历史链路可补 |

---

## 六、验证路径

- **启动**：`start-servers.ps1`（后端 8000 + 前端 3000）
- **SSE 冒烟**（UTF-8 body，勿用字符串编码）：
  ```bash
  curl -N -X POST http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/policy-qa/stream \
    -H "Content-Type: application/json" \
    -d '{"question":"为什么统筹自付这么多","settlement_id":"1671213","session_id":"diag","user_id":"demo","role":"cashier"}'
  ```
- **前端**：浏览器 `http://localhost:3000/policy-qa`，首轮「查询住院费用，结算单 1671213」→ 追问「那起付线呢」→「统筹支付多少」；观察记忆增长、推理链、话题锚点、来源徽标。
- **测试**：前端 `vitest run`（71 通过）+ `next build`；后端 `pytest src/tests/unit/runtime/policy_qa/ src/tests/unit/skill_infra/ skills/settlement_explain_skill/tests/`。

---

## 七、提交清单（2026-08-03 ~ 08-04）

| 提交 | 内容 |
|---|---|
| `a1496ba` | feat: 阶段一（hook + 会话状态模型） |
| `a1f6ca5` | feat: 阶段二（三区工作区 + Runtime 可视化） |
| `c4c016f` | fix: 查询无结果（MSSQL 注入 + subject_changed 误判） |
| `3352c79` | fix: POSTGRES_PASSWORD 默认空（记忆不沉淀） |
| `a67de83` | fix: P1（回复自然语言化 + 耗时 28s→0.3s） |
| `4261e76` / `e3b1bdf` | fix/feat: P0/P1/P2 优化（来源徽标/记忆键值/话题/双视角） |
| `77bc36e` | feat: 严肃化 + 回答价值门控 |
| `c4df0ff` | fix: 质量门控加强（分段不完整拒绝）+ 计算器 rule_type 对齐 |
| `4f6638e` | **refactor: SSE 迁移 Skill 驱动（旧编排器退役）** |

---

*本文档为现状快照 + 决策记录。设计意图与详细方案见 `医保Agent-政策问答前端改造设计-V1.0.md`；进度追踪见 `PROGRESS.md`。*
