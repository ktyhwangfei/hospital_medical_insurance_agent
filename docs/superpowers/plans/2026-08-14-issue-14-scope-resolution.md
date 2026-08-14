# Issue-14 范围澄清与执行方案

> 状态：历史探查记录。用户随后明确选择“提示词与模型统一治理”作为后续事项，并批准按 `docs/superpowers/specs/2026-08-14-提示词与模型统一治理设计.md` 分阶段实施。

**目标：** 核验已交付的 Issue-14 政策知识治理概览页，并在不把文档中记录的第二阶段待办混入当前事项的前提下，只启动一个经明确选择的后续工作项。

**现有架构：** Issue-14 第一阶段仅新增 Portal 聚合页：`page.tsx` 并发读取既有的政策管线、工作台、发布与语义摘要接口，任一数据块失败只降级该数据块。设计文档中的第二阶段事项分别涉及后端、接口或前端范围，不能合并实施。

**技术栈：** Next.js 16、React 19、TypeScript、Vitest、FastAPI、Pydantic、pytest。

---

## 1. 已确认事实

| 主题 | 事实依据 | 结论 |
|---|---|---|
| 分支状态 | `git status --short`、`git branch --show-current`、`git merge-base issue-14 origin/main` | 工作区位于 `ktyhwangfei/issue-14-codex`，且 `issue-14` 已是 `main` 的祖先。 |
| 最近实质提交 | `8382b1f` | 已交付功能是政策知识治理概览；`9e3949b` 仅更新自动生成的 Next 类型路径。 |
| 已交付范围 | `docs/steering/政策知识治理-概览页丰富设计-V1.0.md` §1–8 | 仅一个前端页，复用已有接口：六步管线、四卡待办、统计/生命周期、语义摘要、质量/风险和影响分析占位。 |
| 当前实现 | `src/apps/portal/app/policy-knowledge/page.tsx` | 与设计一致：`Promise.allSettled`、独立惰性加载可用单元、活动发布 404 视为“未发布”、按数据块降级。 |
| 已有覆盖 | `src/apps/portal/src/tests/policy-knowledge/governance-overview-page.test.tsx` | 覆盖六步聚合、待办计数、全空状态、活动发布 404、单块失败隔离和语义摘要导航。 |
| 相关接口契约 | `src/apps/portal/src/lib/policy-knowledge-api.ts`、`src/runtime/api/policy_workbench_routes.py` | 前端只消费既有类型化端点，Issue-14 未新增服务端接口。 |
| 明确延期项 | 设计 §9、需求记录迭代 18 | 低置信度总数聚合、影响分析、评审时长分桶、质量趋势和导航色彩收敛均属于第二阶段或独立事项。 |
| 进度文档冲突 | `PROGRESS.md` §2.4 与需求记录迭代 18 | 功能已实现并提交，但需求记录仍称“设计完成，待实施”；这是文档漂移，不能据此推导出新功能。 |
| 本地验证状态 | `npm test -- governance-overview-page.test.tsx` | 当前不能运行：`src/apps/portal/node_modules` 缺失，npm 找不到 `vitest`；`package-lock.json`、Node 24.14.0、npm 11.9.0 均存在。 |

## 2. 最小范围与决策关口

仅凭现有 Issue-14 事实，不能授权新增业务代码。已完成的 Issue-14 功能已合入；剩余事项在风险、文件和验收条件上均有实质差异。

实施前需从下列范围中明确选择一项：

1. **仅完成 Issue-14 验收（建议）：** 恢复依赖，重跑现有定向测试与生产构建，并校正过期的迭代状态；不改变产品行为。
2. **准确统计低置信度：** 为政策管线摘要新增一个 `low_confidence_count` 字段，移除前端 100 条记录扫描，保留逐块降级。
3. **影响分析：** 定义并实现 `GET /policy-pipeline/impact/recent`，替换概览页占位内容。需先明确“受影响”的含义及返回文档/结果数量。
4. **视觉一致性：** 将政策知识布局导航从翠绿调整为医疗蓝色 token。此项仅影响表现层，但会触及共享导航而非单个概览页。

不得将第 2–4 项合并在同一改动集中；它们是独立用户故事，合并会违背“最小可验证单元”。

## 3. 风险与安全边界

- 第 1、4 项属于 Portal R2；第 2 项跨存储、API 响应、类型化客户端与页面，因 API 契约变化按 R3 处理；第 3 项为 R3，编码前必须定义来源追溯契约。
- 以上任何选择都不授权政策发布、发布物晋升、外部系统写入或风控行为变更。
- 面向用户的响应必须保留既有本地数据来源说明和“暂不可用”数据块隔离；缺失来源不得转化为确定性结论。
- 若选择第 2、3 或 4 项，须先按根目录 `AGENTS.md` 将已确认的需求与验收标准追加至 `docs/steering/政策知识治理-需求迭代记录.md`，再改业务代码。

## 4. 验证方案

### 任务 1：建立 Issue-14 验收基线

**相关文件：**

- 读取：`src/apps/portal/package-lock.json`
- 测试：`src/apps/portal/src/tests/policy-knowledge/governance-overview-page.test.tsx`
- 构建：`src/apps/portal/app/policy-knowledge/page.tsx`

1. 经批准后，仅恢复锁定的 Portal 依赖：

   ```powershell
   npm ci
   ```

   预期：退出码为 0，并提供 lockfile 固定版本的 `vitest`；不得修改 `package.json` 或 `package-lock.json`。

2. 运行已交付功能的回归测试：

   ```powershell
   npm test -- governance-overview-page.test.tsx
   ```

   预期：六个测试通过，包含活动发布 404 和单数据块失败隔离。

3. 运行 Portal 生产构建：

   ```powershell
   npm run build
   ```

   预期：退出码为 0；如遇无关既有失败，只记录证据，不顺带修改。

4. 仅在前三步通过后，校正状态文档：将 `docs/steering/政策知识治理-需求迭代记录.md` 中迭代 18 的“设计完成，待实施”改为有证据的已交付状态，关联提交 `8382b1f` 与通过的检查。除非其维护规则另有要求，不修改 `PROGRESS.md`。

### 任务 2：任何新增产品工作前的硬决策关口

1. 在第 2 节中选择一个范围。
2. 若选择第 1 项，完成任务 1 后停止。
3. 若选择第 2、3 或 4 项，先记录需求：来源依据、验收标准、空/降级行为、明确排除项，以及是否影响共享 API 或布局。
4. 为所选的单一事项单独编写实施方案：列出确切文件、失败测试，并要求遵守仓库的 T1 → T2a → T2b 串行验证；涉及 API 时 pytest 必须加 `-p no:asyncio`，随后完成定向 Portal Vitest、生产构建和必要的端到端流程验证。

## 5. 方案自检

- 已覆盖已知 Issue-14 交付物、延期项、测试、环境状态与文档冲突。
- 决策关口是刻意保留的：现有证据无法指向唯一后续需求，不能从延期清单中擅自推断。
- 本文未提出新的领域类型或接口字段，引用的现有 API 名称和字段均来自已检查的源文件。
