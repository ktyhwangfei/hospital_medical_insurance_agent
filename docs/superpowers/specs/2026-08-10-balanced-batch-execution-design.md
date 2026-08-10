# Skill AI Authoring 平衡批量执行模式

**日期：** 2026-08-10  
**状态：** 已确认  
**适用计划：** `docs/superpowers/plans/2026-08-10-skill-ai-authoring.md`

## 目标

在不降低医保安全、服务端证据与三阶段验证底线的前提下，减少每个小任务重复的代理派发、规格审查、质量审查和验证轮次。

## 批次划分

1. **Batch A — Task 4 + Task 5**：生成/接受 API 与新建向导，交付一条完整的 AI 创建草稿用户故事。
2. **Batch B — Task 6 + Task 7**：revision 优化 API 与编辑页 diff，交付一条完整的 AI 优化用户故事。
3. **Batch C — Task 8**：候选制品与隔离评测，涉及执行隔离和 fail-closed，保留独立严格审查。
4. **Batch D — Task 9**：Flow、E2E、指标与 `PROGRESS.md` 收口。

## 每批执行流程

1. 一个实现者连续完成整批，保留上下文，不在批内重新派发子代理。
2. 仍按 TDD 执行，但 RED/GREEN 以用户故事和安全边界为单位，不为每个辅助函数单独启动审查流程。
3. 任务内保留原子提交，但整批完成后只做一次综合规格+质量审查。
4. 审查只阻塞 **Critical** 和 **Important**；**Minor** 记录到交接/技术债，不在当前批次反复循环。
5. 批次结束时一次性执行所需门禁，避免相同命令在每个小修复后重复运行。

## 质量门禁

- 后端仍按 **T1 单元 → T2a API → T2b Flow** 顺序执行。
- 前端批次仍执行目标 Vitest、ESLint、TypeScript/build；Playwright 在用户故事完整后执行。
- 任何涉及高风险动作、权限、敏感信息、模型证据、候选代码执行的变更，不得因批量模式跳过安全测试。
- Task 8 保留独立规格与质量审查，不与其他任务合并。

## 效率约束

- 主协调者不在子代理每次小修复后重复跑同一组测试；只在批次门禁和完成声明前做新鲜验证。
- 审查者必须一次性输出已确认的全部 Critical/Important，避免逐条发现、逐条重启修复。
- 共享工作区中始终显式按文件/分块暂存，批量执行不放宽 Git 所有权边界。

## 恢复方式

新窗口运行 `$gsd-resume-work`。恢复者必须先读 `.planning/HANDOFF.json` 与 `.planning/.continue-here.md`，确认当前批次为 **Batch A（Task 4 + Task 5）** 后再开工。
