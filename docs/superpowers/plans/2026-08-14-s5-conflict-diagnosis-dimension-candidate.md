# S5 冲突诊断与缺失维度候选实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` and `superpowers:test-driven-development`.

**Goal:** 在不改变 compiler fail-closed 结论的前提下，从已持久化抽取快照确定性地产生可人工裁决的维度候选，并完成审核发布闭环。

**Architecture:** 新增一个纯函数冲突发现模块；复用现有 `semantic_proposals` JSONB 存储、审核事务和语义注册表；抽取完成后非阻断接入；现有语义发现页增加维度候选 tab 和七类裁决。

**Tech Stack:** Python 3 / Pydantic / FastAPI / PostgreSQL JSONB / Next.js 16 / React 19 / Vitest

---

### Task 1：纯函数冲突发现

**Files:**
- Create: `src/knowledge_extension/rule_explanation/conflict_partition_discovery.py`
- Test: `src/tests/unit/knowledge_extension/test_conflict_partition_discovery.py`

- [ ] 先写值归一化、身份缺失模式、严格分区、竞争分区和 `fund_type` 候选测试并确认失败。
- [ ] 实现最小确定性模型、概念词典、诊断和报告函数并确认测试通过。

### Task 2：提议持久化、审核与发布

**Files:**
- Modify: `src/knowledge_extension/rule_explanation/semantic_alignment.py`
- Modify: `src/data_platform/storage/postgresql/semantic_alignment_store.py`
- Modify: `src/runtime/api/semantic_alignment_routes.py`
- Test: `src/tests/integration/api/test_semantic_alignment_api.py`

- [ ] 先写维度候选幂等 intake、非新增维度裁决不发布、新增维度发布测试并确认失败。
- [ ] 扩展现有提议信封和事务发布路径；不在 proposal 阶段创建 `CreateMetricDraft`。

### Task 3：抽取快照接入

**Files:**
- Modify: `src/knowledge_extension/rule_explanation/pipeline_orchestrator.py`
- Test: `src/tests/unit/knowledge_extension/test_pipeline_unknown_concepts.py`

- [ ] 先写首次抽取与重抽触发、S5 异常不阻断主流程测试并确认失败。
- [ ] 在抽取持久化完成后调用 S5，使用同一批规则的稳定快照哈希。

### Task 4：前端审核

**Files:**
- Modify: `src/apps/portal/src/lib/policy-knowledge-api.ts`
- Modify: `src/apps/portal/app/semantic-layer/proposals/page.tsx`
- Test: `src/apps/portal/src/tests/semantic-proposals.test.tsx`

- [ ] 先写维度候选证据和七类裁决交互测试并确认失败。
- [ ] 增加维度候选 tab、证据映射及裁决表单，保留原指标/值域审核行为。

### Task 5：治理同步与串行验证

**Files:**
- Modify: `src/domain/AGENTS.md`
- Modify: `PROGRESS.md`

- [ ] 同步知识上下文通用语言和进度。
- [ ] 严格运行聚焦 T1 → T2a → T2b，再运行 Portal Vitest、TypeScript 和生产构建。
