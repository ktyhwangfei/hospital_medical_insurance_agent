# Draft: Tool Ownership + Skill Composition + @-Mention Invocation

## Requirements (confirmed)
- **Tool Owner**: 每个 tool 配置 owner，分为收费员、医保办、信息科、病案室四个角色
- **角色化加载**: 页面 AI 导办时基于当前角色 + tool 的 owner 加载可见 tools
- **Skill 组合**: 多个 tools 可以组合成 skill（工具包）
- **@唤醒**: 导办时通过 `@skill-name` 方式唤醒 skill 调用

## Technical Decisions
- **Tool Owner 语义**: 管理归属 + 权限。owner 表示科室管理归属，同时影响默认访问权限。不同于 required_roles（精确访问控制），owner 是一级归属
- **Skill 组合方式**: 静态预定义。管理员/开发者预定义 skill 包含哪些 tools
- **Skill 执行模式**: 由 Skill 定义决定（每个 Skill manifest 中声明执行策略：串行/并行/条件分支）
- **@唤醒交互**: 输入时实时提示（按 @ 弹出下拉列表，显示当前角色可用的 skills）
- **Skill 存储**: 数据库持久化 + 管理 UI（CRUD 界面）
- **Skill Owner**: 单 owner（一个 Skill 只属于一个 owner，跨科室通过多 Skill 协作）
- **默认行为（不使用 @）**: 意图识别自动找到匹配的可访问 skill 并执行（替换现有固定 scenario 路由）
- [pending] Skill 领域模型的具体结构

## Research Findings

### Current Architecture
1. **McpCapability** 已有 `required_roles: set[str]` 和 `supported_scenarios: set[str]`
2. **角色模型**: 5 个角色（cashier, medical_office, information_department, medical_record_staff, clinician）
3. **场景授权**: `SCENARIO_ALLOWED_ROLES` 控制场景→角色映射
4. **前端**: 已有 RoleSwitcher（4 角色）和 McpCapability 类型
5. **意图路由**: 静态 INTENT_REGISTRY + LLM/关键词解析 → scenario_route
6. **Chat 流程**: detect_blocked → parse_intent → is_allowed → build_plan → execute_plan

### Key Gap
- **无 "tool" 独立模型** — 当前 tool 是 McpCapability(capability_type=TOOL)
- **无 "skill" 概念** — 无工具组合/编排模型
- **无 @-mention 解析** — 聊天输入是纯文本
- **required_roles 是"谁能用"而非"谁拥有"** — 这是访问控制，不是归属关系

## Open Questions
1. Tool "owner" 是指这个 tool 归属于哪个科室管理（管理语义），还是指哪些角色可以使用（权限语义）？还是两者兼有？
2. Skill 的组合是静态预定义的，还是用户/管理员可以动态配置？
3. @唤醒后，skill 中的多个 tools 是串行执行还是并行执行？还是由 skill 定义决定？
4. 当前 McpCapability 的 required_roles 和新的 owner 是什么关系？
5. 前端 @ autocomplete 的交互形式是什么？（弹出下拉列表？侧边栏？）

## Scope Boundaries
- INCLUDE: 后端 Tool/Skill 领域模型、API 端点、权限控制、@解析
- INCLUDE: 前端 @ autocomplete 输入组件、角色化 tool 列表展示
- EXCLUDE: [待确认]
