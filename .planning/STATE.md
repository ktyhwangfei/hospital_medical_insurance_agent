# Project State

## Project Reference

- Building: 院端医保智能体系统中的 Skill AI 编写与候选隔离能力。
- Core value: Skill 开发者可用自然语言和已发布指标生成或优化草稿，同时保证 AI 产物在严格校验、隔离评测和人工确认前不进入运行时目录。
- Current focus: 以平衡批量模式开始 Batch B（Task 6 + Task 7）的 revision 优化 API 与编辑页 diff。
- Source plan: `docs/superpowers/plans/2026-08-10-skill-ai-authoring.md`
- Execution mode: `docs/superpowers/specs/2026-08-10-balanced-batch-execution-design.md`

## Current Position

- Phase: `skill-ai-authoring` — Skill AI 编写与候选隔离
- Plan: 1
- Task: 6 of 9
- Status: Batch A complete and independently verified; ready for Batch B
- Progress: `[█████░░░░] 56%` (Tasks 1–5 complete)
- Last completed commit: `656cca2` (`fix: enforce skill ai draft invariants`)

## Recent Decisions

- Batch A 合并 Task 4 + Task 5；Batch B 合并 Task 6 + Task 7；Task 8 单独严格审查；Task 9 最终收口。
- Proposal evidence 使用可注入、带 TTL 的 `ShortStateStore`/cache 适配，禁止 route 全局裸 dict。
- 完整 proposal 仅存 evidence state；audit/log 只记录 ID、hash、model、prompt version 和 metric refs。
- 接受 proposal 复用现有幂等 helper 的 reserve/get/complete/conflict 语义。
- Task 4 必须先在 API 测试中观察预期 RED，再写生产代码。
- 服务启停只能通过 `..\ws.ps1`。

## Pending Work

1. Batch B: Task 6 + Task 7 — revision 优化 API 与编辑页 diff。
2. Batch C: Task 8 — 候选制品与隔离评测。
3. Batch D: Task 9 — 完整 Flow、浏览器 E2E、指标与 `PROGRESS.md` 收口。

## Blockers and Concerns

- 无技术阻塞或待人工操作。
- 共享工作区有 3 个外部 error-mining E2E 未提交文件；Batch A 不得修改、删除、暂存或提交它们。
- 提交时仅显式按文件/分块暂存，并检查 cached diff，避免共享工作区提交污染。
- 非阻塞 Minor：selector 首次加载失败后缺少页内重试入口；preview 尚未展示全部派生配置字段。

## Batch A Verification

- T1: 165 passed.
- T2a API: 51 passed.
- T2b Flow: 1 passed (`generate -> accept -> validate -> package preview`).
- Portal Vitest: 3 files / 23 tests passed.
- Target ESLint: exit 0.
- Next.js production build: exit 0, 35 pages.
- Independent specification review: approved, no Critical/Important.
- Independent quality review: approved, no Critical/Important.

## Session Continuity

- Last session: 2026-08-10 (Asia/Shanghai)
- Stopped at: Batch A completed and verified; ready to begin Batch B Task 6 RED tests.
- Resume file: none; use this `STATE.md` and the source plan.
- Immediate next action: 开始 Task 6，先写 stale revision 与结构化 diff 失败测试，再实现只读 optimize 行为。
