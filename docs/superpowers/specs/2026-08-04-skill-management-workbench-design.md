# Skill 管理工作台交互优化设计

## 目标

优化 Portal `/skills` 页面，使平台管理员、业务人员和开发/测试人员都能在同一页面完成 Skill 查看、路由验证和执行调试。默认界面降低技术复杂度，技术细节按需展开。

本次允许前后端协同调整，但保持现有 API 兼容；高风险业务动作仍不得由该页面直接执行。

## 方案

采用渐进式三层工作台：

1. 默认层：Skill 总览，显示名称、业务动作/对象、加载状态、关键词覆盖、指标数量和最近测试状态。
2. 业务层：自然语言路由试验台，展示候选 Skill、置信度、命中关键词、排除原因和路由解释。
3. 技术层：执行调试区，展示脱敏输入、字段映射、查询计划、结构化结果、warnings、citations、uncertainties 和原始调试信息。

主流程为：选择 Skill → 输入问题 → 查看路由预览 → 确认执行 → 查看可读结果 → 按需展开技术详情。

## 页面信息架构

- 顶部提供页面标题、Skill 总数、全局搜索和刷新状态。
- Skill 列表支持搜索、业务动作、业务对象和状态筛选。
- 选中 Skill 后显示工作区，包含“概览”“路由试验”“执行试验”“技术详情”四个区域。
- 技术详情默认折叠，包含 Manifest、字段映射、查询计划、目录结构和 SKILL.md。
- 窄屏下列表与工作区上下堆叠，详情使用抽屉或全屏弹层。

## API 与数据流

继续兼容现有接口：

- `GET /infra-skills`
- `GET /infra-skills/{skill_id}`
- `POST /infra-skills/route-test`
- `POST /infra-skills/{skill_id}/execute-test`
- `POST /infra-skills/refresh`
- 现有语义指标和查询计划接口

路由测试响应保留 `question` 与 `matched_skill_id`，新增可选字段：`confidence`、`match_method`、`matched_keywords`、`excluded_keywords`、`candidates`。

执行测试响应保留 `skill_id`、`status`、`result`，新增可选字段：`warnings`、`citations`、`uncertainties`、`trace`、`input_summary`、`latency_ms`。

新增 `GET /infra-skills/overview` 聚合 Skill 加载状态、Manifest 校验、字段映射、指标数量、最近测试状态和警告摘要。

前端拆分为 `listState`、`selectedSkillState`、`routeTestState`、`executionTestState`，局部请求失败时保留其他已加载数据。

## 错误与安全

- 输入错误在字段附近提示。
- 路由/执行错误展示可读摘要，原始错误按需展开。
- 系统错误显示错误码、请求时间和重试按钮，不暴露堆栈。
- 执行测试默认使用脱敏示例患者上下文。
- 页面不得直接触发正式结算、退费、冲正等高风险动作。
- 执行结果必须继续携带 `citations` 或 `uncertainties`。
- 调试返回只展示脱敏上下文摘要，不返回身份证号、手机号等敏感数据。

## 验证与验收

按项目规定顺序执行：

1. 单元测试：路由解释字段、响应兼容性、错误分类。
2. API 测试：概览、路由、执行、刷新失败和无效输入。
3. Flow 测试：选择 Skill → 路由预览 → 执行 → 查看结果。

验收标准：

- 三类角色都能从默认页面完成主要任务。
- 路由结果能解释匹配原因，而不只是返回 Skill ID。
- 执行结果优先展示结构化业务内容，原始 JSON 作为展开项。
- 局部请求失败不清空其他已加载内容。
- 现有 API 调用和 E2E 测试保持兼容。
- 单元、API、Flow 三阶段验证全部通过。

## 范围边界

本次不重构 SkillLoader、SkillRouter 或业务 Skill 实现，不新增业务动作，不改变正式业务流程；只补充管理页面所需的聚合状态、路由解释和测试结果展示能力。
