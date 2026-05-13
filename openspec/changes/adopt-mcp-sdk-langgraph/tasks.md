# Tasks

## 1. 依赖与边界确认

- [ ] 确认 MCP Python SDK、FastMCP、LangGraph 和 checkpoint 相关依赖版本。
- [ ] 更新项目依赖声明，确保后端测试环境可安装并导入新增依赖。
- [ ] 定义 feature flag 或配置项，用于在旧服务路径与 LangGraph 路径之间切换。

## 2. MCP SDK Adapter

- [ ] 新增 `McpClientAdapter` Protocol，覆盖 server 初始化、能力发现、单次工具调用和工具调用序列。
- [ ] 基于 MCP Python SDK 实现 stdio transport adapter。
- [ ] 基于 MCP Python SDK 实现 SSE 或 streamable HTTP transport adapter。
- [ ] 将 MCP SDK 错误归一化为现有 `KnowledgeExtensionStatus`、uncertainties 和 audit events。
- [ ] 保留现有 stdio 客户端作为迁移 fallback 或测试替身。

## 3. MCP 发现与调用迁移

- [ ] 将 MCP `tools/list` 自动发现服务改为通过 `McpClientAdapter` 执行。
- [ ] 保持现有 `mcpServers` JSON 导入、server 注册和 capability 落库契约兼容。
- [ ] 将 MCP 工具调用服务改为通过 `McpClientAdapter` 执行，并移除协议细节散落。
- [ ] 为 tool annotations、side effects 和 risk_level 增加强制映射规则。

## 4. LangGraph Runtime 基础

- [ ] 新增 `GraphRuntime` 入口，支持按 scenario 或 skill_id 选择图。
- [ ] 定义统一图状态模型，包含请求、角色、权限、患者上下文、节点输出、citations、uncertainties、audit_events 和待确认任务。
- [ ] 接入 checkpoint 存储，支持 workflow_id 查询和中断恢复。
- [ ] 增加通用节点 wrapper，执行前后统一处理权限、风控、脱敏、审计和输出归一化。

## 5. MCP 工具调用图迁移

- [ ] 将 MCP 工具调用场景改造成 LangGraph 子图：匹配能力、评估策略、准备参数、调用工具、归一化结果。
- [ ] 高风险或有副作用工具必须中断为人工确认，不允许直接执行。
- [ ] 保持现有 `AgentResponse` 输出结构兼容，并补齐 citations 或 uncertainties。
- [ ] 增加 MCP 工具调用图的单元测试、集成测试和失败路径测试。

## 6. 核心医保场景图迁移

- [ ] 将结算异常导办迁移为 LangGraph 子图，节点对应交易查询、错误码知识、账单状态和结果构建。
- [ ] 将出院前联合质控迁移为 LangGraph 子图，节点对应医嘱、医保状态、事前审核、DRG/DIP、病案首页、规则解释和任务创建。
- [ ] 验证两个场景仍通过现有 API 入口、权限校验、高风险拦截和脱敏输出。
- [ ] 增加端到端回归测试，覆盖样例数据和降级路径。

## 7. Skill 管理收缩

- [ ] 明确 `Skill` 只作为图模板元数据，不再承载自研执行引擎职责。
- [ ] 增加 skill 到 LangGraph 图模板的映射服务。
- [ ] 校验 skill 中的 tool 引用必须存在且满足角色、风险和场景策略。
- [ ] 更新前端文案，将 skill 管理定位为工作流模板治理而非通用插件市场。

## 8. 前端治理台调整

- [ ] MCP 管理页展示 SDK 发现状态、transport、last_error、tool annotations 和风险映射结果。
- [ ] 增加 Graph 执行状态、workflow_id、当前节点、人工确认状态和审计摘要展示。
- [ ] 保留注册、导入、发现、启停、权限编辑和测试调用功能。
- [ ] 移除或隐藏暗示低代码编排器、通用 skill 市场的入口和文案。

## 9. 验证与验收

- [ ] 运行后端测试：`python -m pytest src/tests -v`。
- [ ] 运行前端 lint：在 `prototype` 下执行 `npm run lint`。
- [ ] 运行 OpenSpec 严格验证：`npx openspec validate "adopt-mcp-sdk-langgraph" --strict`。
- [ ] 验证 MCP Server 注册、tools/list 发现、工具测试调用、MCP 工具调用图执行、两个医保核心场景图执行和人工确认中断。

