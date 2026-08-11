# Skill 日常治理工作台完整设计

> 状态：待评审
>
> 日期：2026-08-11
>
> 页面：Portal `/skills`
>
> 核心任务：评测 → 发现问题 → 修改 → 复审 → 发布
>
> 视觉参考：[Skill 治理工作台风格参考](./2026-08-11-skill-governance-workbench-style-reference.html)

## 1. 设计结论

将 `/skills` 从“选择 Skill 后查看资产详情”调整为“从治理待办出发并推进闭环”。

新首页采用待办驱动的主从工作台：

- 左侧是按风险和等待时间排序的治理待办；
- 中间是当前 Skill 的评测差异、失败案例和唯一下一步；
- 右侧是门禁结论、冻结证据和审计记录；
- 修改、评测、审批和发布仍使用现有草稿、评测运行和 Release 对象，不新建第二套状态机。

页面视觉不重做品牌。保留 Portal 的白色顶栏与侧栏、`Noto Sans SC`、slate 蓝灰中性色、blue 主操作色、Lucide 线性图标、10–12px 圆角和紧凑后台密度。

## 2. 文档关系

本文档是已落地 Skill 工作台的后续优化，不否定已实现的资产、草稿、评测和发布模型。

| 现有文档 | 保留内容 | 本文档调整内容 |
|---|---|---|
| `2026-08-05-skill-governance-workbench-ui-redesign.md` | 双栏目录、服务端治理读模型、门禁证据、调试抽屉 | `/skills` 首屏从资产详情转为治理待办和评测差异 |
| `2026-08-06-skill-management-workbench-design.md` | 草稿、导入、复制、校验、物化、停用/恢复/归档 | 这些能力保留在独立资产与草稿页，不挤占日常治理首屏 |
| `2026-08-10-skill-ai-authoring.md` | AI 生成、优化差异、候选隔离评测、人工物化 | 作为“修改”阶段的已有实现 |
| `2026-08-10-skill-eval-mining.md` | 真实错误入池、AI 分型、人工确认、回归资产 | 并入“评测中心”的案例子视图 |

若文档冲突，本文档只在 `/skills` 首页信息架构、局部导航和视觉层级上优先；安全、存储、门禁和生命周期规则仍以已实现契约为准。

## 3. 现状与问题

### 3.1 已有能力

[来源: `PROGRESS.md` §7.4–7.8]

- 版本化 Skill 资产、制品 hash 和不可变版本证据；
- 固定路由评测、候选/基线差异、必测门禁；
- candidate 创建、申请审批、禁止自审和 Test Shadow 激活；
- 草稿 CRUD、导入、校验、包生成、物化和生命周期管理；
- AI 创作、AI 优化差异、候选路由/行为评测；
- 错误案例池、案例挖掘和分型回归资产。

### 3.2 当前页面的优点

- 已有 Skill 目录 + 选中详情的稳定心智模型；
- 环境、生命周期步骤、版本、评测和发布证据已经连通；
- URL 可恢复 Skill、页签、环境和筛选；
- 局部请求使用 `Promise.allSettled`，详情失败不清空目录；
- 已有目录键盘导航和移动端返回目录交互。

### 3.3 当前页面的主要问题

1. 页面同时出现“Skill 管理工作台”“正式 Skill 管理列表”“Skill 管理”三层标题。
2. 首屏先展示全局页签、介绍、摘要数字和资产目录，真正的评测问题位于下半屏。
3. “评测记录”“错误案例池”“案例挖掘”为三个平级页签，但它们实际是同一评测反馈链。
4. 顶部摘要以“总数/健康/待评测”为主，数字可读但不直接回答“现在先做什么”。
5. 候选与基线的差异已存在 DTO 中，但没有在首屏成为主要决策界面。
6. 390px 下的现有 E2E 只验证 `scrollWidth`，不能防止固定侧栏将内容压成窄列、标题逐字换行等“无溢出但不可用”问题。

## 4. 竞品模式与取舍

本设计参考当前具有代表性的 AI 评测与治理产品，只借鉴工作流组织，不复制品牌视觉。

| 模式 | 参考 | 本项目决策 |
|---|---|---|
| 从回归/改善案例进入详情和 trace | [LangSmith 实验对比](https://docs.langchain.com/langsmith/compare-experiment-results) | 评测差异与失败案例成为中央工作区 |
| 审核使用专注队列和进度 | [LangSmith 审核队列](https://docs.langchain.com/langsmith/annotation-queues) | “待复审”是待办类型，审批仍受现有权限与禁止自审约束 |
| Playground 修改 → Experiment 固化 → 基线对比 → 线上回流 | [Braintrust 评测闭环](https://www.braintrust.dev/docs/evaluate) | 草稿可变，评测运行与版本证据不可变 |
| 候选与基线按逐案例显示改善/回归 | [Braintrust 实验对比](https://www.braintrust.dev/docs/evaluate/compare-experiments) | 复用现有 `SkillEvalResultResponse.diff` 和置信度差异 |
| Dataset + Evaluator + 多版本构成一次评测 | [Humanloop UI 评测](https://humanloop.com/docs/v5/guides/evals/run-evaluation-ui) | 评测运行明确显示 suite revision、candidate 和 baseline |
| 编辑、数据集实验、版本比较、环境标签发布 | [Langfuse 实验](https://langfuse.com/docs/evaluation/experiments/experiments-via-ui) / [Prompt 管理](https://langfuse.com/docs/prompt-management/overview) | 修改进入草稿，发布继续使用 Test Shadow，不扩展生产发布 |
| 在 Playground 中并排测试候选方案 | [Phoenix Prompt 测试](https://arize.com/docs/phoenix/prompt-engineering/how-to-prompts/test-a-prompt) | 不在本期建通用 Playground；继续使用已有 AI 优化 diff 和候选评测 |

## 5. 用户与权限场景

| 角色 | 首要任务 | 默认入口 |
|---|---|---|
| Skill 维护员 | 运行评测、定位回归、修改草稿、重新评测 | 治理待办 |
| 业务评审员 | 复核高风险案例、检查政策来源和业务结论 | 评测中心 / 待复审 |
| 信息科审批员 | 检查冻结证据、执行人工审批和 Test Shadow 激活 | 待复审 / 可发布 |
| 审计/管理人员 | 查看发布链路、审批人和证据版本 | 发布记录 |

收费员和医生不是该工作台的主用户。若其账号没有 Skill 治理权限，页面显示只读证据或无权限说明，不使用“隐藏按钮即等于鉴权”。

## 6. 核心治理闭环

```text
评测
  → 逐案例比较 candidate / baseline
  → 识别新增回归、路由变更、必测失败和评测器阻断
  → 从正式 Skill 复制或继续关联草稿
  → 人工编辑或接受 AI 优化 diff
  → 校验、候选路由评测和候选行为评测
  → 人工物化并登记不可变版本
  → 对固定套件重新评测
  → 创建 candidate release
  → 申请审批、不同身份审批
  → 激活 Test Shadow
```

“发现问题”不自动等同于 AI 根因结论。首期只使用可追溯的 `diff`、风险标签、路由关键词和评测器 failure code 分组；仅对已进入错误案例池的内容展示带 `citations` / `uncertainties` 的 AI 分型提案。

## 7. 信息架构与路由

### 7.1 全局 Portal 骨架

保留现有左侧全局导航和 56px 顶栏：

- 左侧一级导航仍为政策问答、Skill、语义层、政策知识和问答历史；
- 品牌标识、连接状态和角色切换保持现状；
- 不在 Skill 页上引入暗色主题、新字体或新品牌色。

### 7.2 Skill 局部导航

| 导航 | 路由 | 责任 |
|---|---|---|
| 治理待办 | `/skills` | 日常默认入口，推进当前阻塞和下一步 |
| 评测中心 | `/skills/evaluations` | 评测运行、错误案例池和案例挖掘三个子视图 |
| Skill 资产 | `/skills/assets` | 正式 Skill 列表、生命周期、查看和复制 |
| 草稿 | `/skills/drafts` | 创建、继续编辑、校验、候选评测和物化 |
| 发布记录 | `/skills/releases` | candidate、审批、Test Shadow 和历史证据 |

兼容规则：

- 现有 `/skills/eval-case-pool` 和 `/skills/eval-mining` 路由保留，但局部导航高亮“评测中心”；
- `/skills/[skillId]` 和 `/skills/[skillId]/edit` 保留；
- `/skills/new` 和 `/skills/import` 保留；
- 旧 `/skills` 资产视图迁入 `/skills/assets`，不修改后端接口。

## 8. `/skills` 治理待办页

### 8.1 页面头

页面只保留一个 H1：`Skill 治理工作台`。

副标题：`处理评测回归、人工复审与 Test Shadow 发布。`

右侧保留：

- `新建 Skill`：主操作，进入 `/skills/new`；
- `导入 Skill`：次要操作，进入 `/skills/import`。

不再显示“Skill 管理工作台”胶囊和工作台内的第二套标题。

### 8.2 页面级工具栏

- 搜索 Skill 名称、ID、评测运行 ID 或案例摘要；
- 环境默认 `test`，`dev` 只读，不显示未实现的 `prod`；
- 优先级筛选：全部、阻塞、高风险、普通；
- 刷新仅刷新读模型，不触发版本登记、评测或发布写操作。

搜索 250ms 防抖。非敏感筛选写入 URL；问题模板、患者标识、审批理由和证据正文不得写入 URL、localStorage 或埋点。

### 8.3 桌面三栏工作区

```text
┌── 274px 治理待办 ──┬── minmax(520px, 1fr) 决策工作区 ──┬── 272px 证据轨 ──┐
│ 评测失败             │ 生命周期与差异                  │ 门禁结论       │
│ 待复审                 │ 回归案例列表                      │ 冻结证据       │
│ 可发布                 │ 固定下一步操作                    │ 最近记录       │
└────────────────────┴────────────────────────────────┴─────────────────┘
```

大桌面可同时显示三栏。900–1119px 隐藏证据轨，证据通过“查看证据”抽屉展示。

### 8.4 左栏：治理待办

待办不是新的领域实体，是服务端根据现有 `SkillVersion`、`SkillEvalRun`、`SkillRelease` 和关联 `SkillDraft` 派生的读模型。一个 Skill 默认只显示一个当前主待办。

待办类型与优先级：

| 优先级 | 待办类型 | 条件 |
|---:|---|---|
| 1 | 评测失败 | 最新有效评测为 `failed` / `error`，或必测案例未全部通过 |
| 2 | 待复审 | release 为 `approval_pending` |
| 3 | 可发布 | release 为 `approved` 且证据仍有效 |
| 4 | 待评测 | 已登记版本没有匹配的 passed eval |
| 5 | 制品变更 | 当前文件制品与已登记版本不同 |
| 6 | 修改中 | 存在关联草稿且状态为 editing / validated |

同优先级按 `waiting_since` 升序，再按 `skill_id` 稳定排序。高风险必测失败始终位于同类型普通失败之前。

目录项只显示：

- Skill 名称；
- 一个主状态；
- 一行原因；
- 候选或草稿版本；
- 等待时间。

不显示完整 hash、关键词、Manifest、多个并列徽标或内部存储状态。

### 8.5 中栏：决策工作区

#### Skill 身份头

展示 Skill 名称、`skill_id`、候选版本、活动基线版本、主门禁状态和 `BusinessAction · BusinessObject`。

#### 五阶段步骤

1. 评测；
2. 定位问题；
3. 修改；
4. 复审；
5. 发布。

步骤条是从多个事实派生的导航提示，不存储独立 `workflow_status`。每步只有 `completed | current | blocked | pending`，必须同时有文本，不只使用颜色。

#### 决策指标

固定顺序：

1. 候选通过率；
2. 活动基线通过率；
3. 新增回归；
4. 必测通过数。

指标使用 `SkillEvalMetricsResponse`，不在前端重新计算门禁。基线不存在时显示“无活动基线”，不伪造 `0%`。

#### 失败案例列表

默认只显示 `new_failure | route_changed | unchanged_fail`，可切换查看改善和全部。

| 列 | 内容 |
|---|---|
| 案例 | 脱敏问题摘要，不展示患者标识 |
| 风险 | `required` 和 `risk_tags` 派生的文本徽标 |
| 候选结果 | candidate Skill / confidence 或 failure code |
| 基线结果 | baseline Skill / confidence |
| 差异 | 现有 `diff` 枚举的中文表达 |
| 操作 | 查看脱敏案例和冻结 trace |

表格可在工作区内横向滚动，但不允许页面级横向滚动。

#### 固定下一步条

中栏底部保留粘性操作条，包含：

- 一句服务端派生的阻塞摘要；
- 一个主操作；
- 必要时一个次要动作“查看证据”。

主操作映射：

| 当前事实 | 主操作 |
|---|---|
| 制品未登记 / 发生变更 | 登记当前版本 |
| 版本无匹配评测 | 运行候选评测 |
| 评测失败且无关联草稿 | 创建修复草稿 |
| 存在 editing / validated 草稿 | 继续修改 |
| 候选评测通过但未物化 | 人工物化 |
| 固定评测 passed 且无 release | 创建发布候选 |
| release 为 candidate | 申请审批 |
| release 为 approval_pending | 进入人工审批 |
| release 为 approved | 激活 Test Shadow |
| release 为 active | 查看运行证据 |

写操作仍通过原有确认、revision、幂等键和权限校验；粘性条不绕过审批。

### 8.6 右栏：证据轨

顺序固定：

1. 门禁结论：是否可进入下一阶段和主要原因；
2. 冻结证据：版本、eval run、suite revision、artifact/config/routing manifest hash 摘要；
3. 最近记录：登记、评测、审批和激活的操作人与时间。

完整 hash 通过复制操作获取，默认只显示前后摘要。审批理由按现有安全约束处理，不在目录或全局埋点中暴露。

## 9. 评测中心

`/skills/evaluations` 内部使用三个次级页签：

1. **评测运行**：按 Skill、版本、状态和时间查看不可变运行；
2. **错误案例池**：来自 Policy QA 反馈和历史的待分型/待确认案例；
3. **案例挖掘**：AI 分型提案、人工编辑和投影到评测资产的过程。

路由保持现状，只调整导航层级。不把 routing、calculation、policy_content、citation、answer_quality 和 safety 结果混入同一个 Top-1 准确率；指标语义继续使用已有分类契约。

## 10. Skill 资产、草稿和发布记录

### 10.1 Skill 资产

`/skills/assets` 承接当前正式 Skill 列表与详情入口，保留：

- Skill 名称、ID、当前版本和业务挂载；
- 查看、复制为草稿、停用、恢复和归档；
- 版本、输入指标、开发详情和审计证据。

资产页使用紧凑表格或列表，不复制治理待办三栏布局。

### 10.2 草稿

保留已有独立草稿页和编辑器。从治理待办进入时，携带 `return_to=/skills?skill=<id>` 的非敏感返回上下文；保存、候选评测或物化后可返回原待办。

### 10.3 发布记录

保留 candidate、approval_pending、approved、active 和 retired 记录。待办工作台只显示当前可执行操作；历史对比、审批人和时间线在发布记录页查看。

## 11. 视觉设计规范

### 11.1 设计权威

项目没有 `DESIGN.md`，因此现有 Portal 的 `app/layout.tsx`、`app/globals.css`、`components/ui/*` 和已落地治理页是视觉权威。本次是延展和精修，不是重做品牌。

### 11.2 颜色

| 语义 | 颜色 | 使用 |
|---|---|---|
| 页面背景 | `slate-50` | Portal 主内容底色 |
| 主表面 | `white` | 顶栏、侧栏、工作台 |
| 主文本 | `slate-950` | H1、Skill 名称、主指标 |
| 次文本 | `slate-500/600` | 说明、时间、技术摘要 |
| 边界 | `slate-200` | 1px 分隔线和控件边框 |
| 主操作/当前 | `blue-600` / `blue-50` | 主按钮、选中项、当前步骤 |
| 成功/active | `emerald-600` / `emerald-50` | 评测通过、Test Active |
| 等待/审批 | `amber-700` / `amber-50` | 待复审、待处理 |
| 阻塞/失败 | `red-600` / `red-50` | 门禁失败、新增回归 |

颜色不作为唯一状态线索。所有状态同时包含文本，必要时加 Lucide 图标。

### 11.3 字体与数字

- 继续使用 `Noto Sans SC`, system-ui, sans-serif；
- H1：24px / 32px / 600，移动端 20px / 28px；
- H2：18px / 26px / 600；
- 区块标题：14–16px / 600；
- 正文：14px / 22px；
- 辅助文字：12px / 18px；
- `skill_id`、run ID、commit 和 hash 使用等宽字体，业务文案不使用等宽字体；
- 通过率、数量和时间使用 tabular numerals，便于纵向比较。

### 11.4 布局与间距

- 页面最大宽度 1600px，桌面左右间距 24–32px；
- 工作台一个主表面，不使用多层 Card 嵌套；
- 主表面 12px 圆角、1px 边框、一层低强度中性阴影；
- 尺寸序列使用 4 / 8 / 12 / 16 / 20 / 24 / 32px；
- 桌面控件高度 36px，移动端主按钮和触控目标不小于 44px；
- 不使用网格纹理、装饰性模糊光斑、玻璃拟态或彩色光晕阴影。

### 11.5 图标和动效

- 继续使用 Lucide，不使用 emoji 或 Unicode 字符代替功能图标；
- 图标标准尺寸 16–18px，线宽与现有 Portal 一致；
- hover/focus/展开动效 150–200ms，只调整颜色、背景或小幅位移；
- 不为每张列表项添加入场动画；
- 支持 `prefers-reduced-motion`。

### 11.6 风格参考说明

参考 HTML 展示了目标密度、三栏层级、状态色、步骤条、回归表格和移动端列表模式。其中 Skill 名称、运行 ID、指标和人名都是明确标注的示例数据，不是产品声称或待导入种子数据。

## 12. 响应式设计

### 12.1 大桌面（≥1200px）

- 显示 Portal 完整侧栏；
- 工作台显示待办、决策区和证据轨三栏；
- 标识、步骤、四个指标和回归表格在首屏可见。

### 12.2 中等宽度（768–1199px）

- Portal 侧栏可收起；
- 工作台显示 240–250px 待办列 + 决策区；
- 证据轨改为右侧抽屉；
- 四个指标可按 2 × 2 排列；
- 页签允许水平滚动，文字不逐字换行。

### 12.3 移动端（<768px）

- 全局侧栏移入导航抽屉，不固定占据 224px；
- 治理待办与详情使用列表页/详情页两级导航，不将三栏压缩到同一屏；
- 列表首屏显示搜索、环境、优先级、队列分组和待办；
- 点击待办进入全宽详情，顶部提供“返回待办”；
- 证据抽屉为全屏层；
- 表格在详情中改为案例摘要列表，不依赖横向滚动完成主任务。

移动端验收不能只断言“无横向溢出”，还必须检查 H1 不逐字换行、主操作可见、页签可读和列表可完成选择。

## 13. 加载、空态、错误和并发

| 状态 | 页面行为 |
|---|---|
| 首次加载 | 保留页面头和工作台结构，待办和决策区局部 skeleton |
| 切换待办 | 保留左栏，中/右栏局部 skeleton，防止布局跳动 |
| 无待办 | 显示“当前没有需处理的 Skill”和“查看全部资产”，不显示空白大卡 |
| 筛选无结果 | 保留筛选值，提供“清除筛选” |
| 工作台读模型失败 | 回退现有 catalog，待办计数显示 `—`，不伪造为 0 |
| 评测详情失败 | 左栏可继续选择，中栏显示 `error_code`、message 和重试 |
| 403 | 显示需要的权限与联系方式，不伪装为业务状态 |
| 409 revision conflict | 保留用户已输入内容，刷新最新 revision 并要求再确认 |
| 409 gate failure | 保留 eval 证据，聚焦门禁结论和变化项 |
| 候选评测器不可用 | 显示 `blocked_by_evaluator`，禁止宿主机回退执行 |
| 写操作进行中 | 只禁用当前动作和依赖动作，待办列仍可滚动 |

错误文案说明问题和恢复方式。不展示堆栈、SQL、模型密钥或患者明文。

## 14. 交互、可达性与内容

- 待办列是单选导航，当前项使用 `aria-current="true"`；
- 上/下键移动选择，Enter 打开，焦点始终可见；
- 所有图标按钮有可读 `aria-label`；
- 步骤条使用有序列表或合理的 `aria-label`，当前与阻塞状态可被读屏读取；
- 表格表头与数据单元格关联，排序和筛选按钮命名完整；
- 色彩对比满足 WCAG AA，正文和 placeholder 不使用低对比浅灰；
- 桌面工作台在 200% 缩放下仍可完成主任务；
- 文案统一使用 `Skill`、“评测”、“复审”和“Test Shadow”，不混用“技能包”“测试”“上线”等不精确名称。

## 15. 读模型与 API 设计

### 15.1 复用现有端点

继续使用：

```text
GET  /infra-skills/workbench
GET  /infra-skills/{skill_id}
GET  /infra-skills/{skill_id}/versions
GET  /infra-skills/{skill_id}/eval-runs
POST /infra-skills/{skill_id}/eval-runs
GET  /infra-skills/{skill_id}/releases?environment=test
POST /infra-skills/{skill_id}/releases
POST /infra-skills/{skill_id}/releases/{release_id}/request-approval
POST /infra-skills/{skill_id}/releases/{release_id}/approve
POST /infra-skills/{skill_id}/releases/{release_id}/activate
POST /infra-skills/{skill_id}/copy
```

评测详情、草稿、AI 优化、候选评测和错误案例池继续使用现有端点。本设计不新增写接口。

### 15.2 扩展工作台读模型

`SkillWorkbenchItem` 增加可选派生字段：

```text
current_stage:
  evaluate | diagnose | modify | review | release | healthy
priority:
  blocked | high | normal
latest_eval_run_id: string | null
candidate_version: string | null
baseline_version: string | null
regression_count: int
required_failure_count: int
linked_draft_id: string | null
linked_draft_status: string | null
waiting_since: datetime
next_action: enum
next_action_reason: string | null
```

约束：

- 上述字段由 `SkillWorkbenchService` 从现有存储一次聚合，前端不逐 Skill 请求；
- 不新增可变的 Task 表或 `workflow_status`；
- `next_action` 只是导航/呈现提示，写操作仍由相应服务端校验；
- `next_action_reason` 只返回安全摘要，不包含问题模板、患者数据或审批理由；
- DTO 使用显式 Pydantic / TypeScript 联合类型，不返回裸 `dict`。

### 15.3 选中待办后的数据流

```text
选中 Skill
  → 立即使用 workbench item 渲染身份头和队列状态
  → Promise.allSettled(
       detail,
       versions,
       eval-runs,
       test releases
     )
  → 合并 latest eval 的 results / case_snapshots
  → 渲染指标、失败案例和证据轨
```

详情局部失败不清空左栏。写操作成功后刷新当前 Skill、待办汇总和相关证据，不全页重载。

## 16. 前端组件设计

```text
app/skills/page.tsx
└─ SkillGovernanceQueueWorkbench
   ├─ SkillGovernancePageHeader
   ├─ SkillGovernanceToolbar
   ├─ SkillTaskQueue
   │  ├─ SkillTaskQueueTabs
   │  └─ SkillTaskQueueItem
   ├─ SkillDecisionWorkspace
   │  ├─ SkillDecisionHeader
   │  ├─ SkillGovernanceCycleStepper
   │  ├─ SkillEvalMetricStrip
   │  ├─ SkillRegressionTable
   │  └─ SkillNextActionBar
   ├─ SkillEvidenceRail
   ├─ SkillRouteTestDrawer          (复用)
   └─ SkillExecutionTestDrawer      (复用)
```

复用约束：

- 复用现有 `SkillPrimaryAction` 计算的业务语义，将其输入扩展为服务端 `next_action`，不同时保留两套冲突推导；
- 复用现有 URL 读写、目录键盘导航、调试抽屉和 API client；
- 复用 `Button`、`Input`、`Select`、`Badge`、`Tabs`、`Dialog/Drawer` 等 UI 基础组件；
- 不引入新状态库、新图表库或新图标库；
- 没有证据显示真实趋势时，不添加装饰性 sparkline。

## 17. 安全与审计

- 读取工作台使用 Skill 读权限；
- 创建用例、运行评测和确认回归资产需要 `skill:evaluate`；
- Test 发布写操作需要 `skill:release:test`；
- 候选创建人和审批人来自认证上下文，禁止自审；
- 评测结果只展示脱敏问题摘要，完整样本按权限加载；
- AI 分型、优化建议和执行调试结果必须带 `citations` 或 `uncertainties`；
- 候选行为评测在 sandbox 不可用时 fail closed，不回退宿主机执行；
- 激活 Test Shadow 依然是高风险发布控制动作，必须经人工确认；
- 页面不触发退费、冲正、正式结算、病案修改或任何院内系统终态操作。

## 18. 验证策略

本变更涉及前端主任务、治理读模型、权限和发布证据，按 R4 高风险变更验证，严格执行 T1 → T2a → T2b。

### 18.1 T1 单元测试

- 待办类型和优先级派生；
- 同优先级等待时间排序；
- 五阶段步骤状态映射；
- `next_action` 与已有发布门禁一致；
- 无基线、评测失败、必测失败、待审批、已审批和 active；
- 关联草稿 editing / validated 状态；
- URL 解析、筛选和无效 Skill 回退；
- 失败案例 diff 映射和脱敏摘要；
- 403、409、422、`blocked_by_evaluator` 和局部请求失败；
- 移动端列表/详情转换和返回上下文。

### 18.2 T2a API 测试

- `/infra-skills/workbench` 扩展 DTO、分页、搜索和筛选；
- 待办优先级和汇总数量；
- `next_action` 不绕过现有写端点门禁；
- 工作台响应不包含患者信息、完整问题模板和审批理由；
- 旧 catalog、detail、eval、release、draft 和 regression 接口兼容；
- 工作台聚合失败时 catalog 回退。

### 18.3 T2b Flow / E2E

主链：

```text
打开治理待办
  → 选择评测失败 Skill
  → 查看候选/基线差异和回归案例
  → 创建或继续修复草稿
  → 候选评测通过
  → 人工物化并登记版本
  → 固定评测通过
  → 创建 candidate
  → 申请审批
  → 不同身份审批
  → 激活 Test Shadow
  → 待办从队列消失或转为健康
```

另覆盖：

- 刷新恢复选中 Skill 和队列筛选；
- 评测详情失败不清空待办；
- revision conflict 保留编辑内容；
- sandbox 不可用时阻断候选行为评测；
- 1440 × 1000 三栏桌面；
- 1024px 双栏 + 证据抽屉；
- 390 × 844 列表/详情两级流程；
- 200% 缩放、键盘、焦点和读屏命名。

### 18.4 前端质量门禁

- 相关 Vitest；
- 变更文件 ESLint；
- Next.js production build；
- Chromium Playwright；
- 完成态、加载态、空态、错误态、无权限态、长文案和高风险失败的一次批量视觉检查；
- Impeccable 检测器一次扫描，并以实际渲染判断为准。

## 19. 可量化成功标准

| 指标 | 标准 |
|---|---|
| 首个可操作待办可见 | 正常数据下进入页面 5 秒内可识别 |
| 从评测失败到打开修复草稿 | 不超过 2 次主操作 |
| 查看回归案例 | 选中待办后无需切换顶层页签 |
| 固定评测 passed 到申请审批 | 每个状态只显示一个主操作 |
| 局部请求失败 | 不丢失待办队列、选中项和已加载证据 |
| 桌面响应式 | 1440px 显示三栏，1024px 可完成同一主链 |
| 移动端 | 390px 无页面横向溢出，H1 和按钮正常，可完成列表选择与返回 |
| 键盘 | 可完成待办选择、案例查看、主操作与返回 |
| 发布安全 | 任何前端路径都不能绕过门禁、幂等、revision 和禁止自审 |

## 20. 非目标

- 不实现生产发布、生产回滚或流量百分比灰度；
- 不新建通用 Prompt Playground 或可视化代码 IDE；
- 不将治理待办存成第二套事实状态机；
- 不修改 `SkillLoader`、`SkillRouter`、assembler 或正式业务路由算法；
- 不引入新的全局状态库、图表库、图标库或样式框架；
- 不为没有历史数据的页面伪造趋势图；
- 不改造 Portal 其他页面，除了解决移动端全局侧栏对 `/skills` 的实际阻断。

## 21. 实施切片建议

详细实施任务在本文档评审通过后另行编写。建议保持三个最小可验证切片：

1. **导航与只读待办**：扩展 workbench 读模型、调整局部导航、落地待办列与响应式骨架；
2. **评测决策区**：逐案例差异、决策指标、证据轨和局部错误态；
3. **闭环操作**：创建/继续修复草稿、返回上下文、审批/激活主操作和端到端验收。

每个切片分别通过 T1 → T2a → T2b 后再进入下一片。

## 22. 验收清单

- [ ] `/skills` 默认展示治理待办，不再以资产详情为首屏主任务。
- [ ] 页面只有一个 H1 和一组创建/导入操作。
- [ ] 评测运行、错误案例池和案例挖掘在“评测中心”下形成连续心智模型。
- [ ] 治理待办由现有领域事实派生，没有第二套可变状态机。
- [ ] 门禁失败、待复审、可发布、待评测、制品变更和修改中的优先级正确。
- [ ] 选中失败 Skill 后首屏可见 candidate/baseline 指标、回归案例和下一步。
- [ ] 失败案例只使用可追溯 diff、risk tag 和 failure code 分组，不伪造 AI 根因。
- [ ] 修改复用现有草稿和 AI 优化 diff，候选行为评测仍 fail closed。
- [ ] 复审和发布仍受权限、禁止自审、revision、幂等和服务端门禁约束。
- [ ] 视觉使用现有 Portal 字体、颜色、图标、圆角和密度，不引入第二套品牌。
- [ ] 1440px 为三栏，1024px 为双栏，390px 为列表/详情两级布局。
- [ ] 移动端全局侧栏不再将内容压成窄列，H1、导航和主按钮可读可用。
- [ ] 局部请求失败不清空队列、选中项或已加载证据。
- [ ] 完成 T1、T2a、T2b、Portal build、Chromium E2E 和一次批量视觉验收。

## 23. 已确定决策

1. 首页服务日常治理，资产管理迁入独立子页。
2. 主链固定为评测、定位问题、修改、复审、发布。
3. 采用待办列 + 决策区 + 证据轨，不采用全局看板拖拽。
4. 评测差异和回归案例为首屏主内容，完整技术详情渐进披露。
5. 待办和步骤是读模型，不新增领域状态机。
6. 不新增写接口，只扩展现有 workbench 读模型。
7. 保留已有草稿、AI 创作、候选隔离评测、审批和 Test Shadow 语义。
8. 视觉必须延续现有 Portal，不同时开启全局重设计。
9. 本期不做生产发布、通用 Playground、全局看板拖拽和新依赖。
