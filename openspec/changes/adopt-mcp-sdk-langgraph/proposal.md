# Adopt MCP SDK and LangGraph for Production-Ready Agent Runtime

## Summary

引入官方 MCP Python SDK 或 FastMCP 作为 MCP 协议与传输实现基础，引入 LangGraph 作为医保智能体的状态图编排运行时。现有自研 MCP 注册、skill 管理和业务场景代码不再继续扩展为通用框架，而是收缩为院端医保领域治理层，负责能力目录、权限风控、脱敏审计、人工确认、业务适配器边界和输出可追溯。

## Motivation

当前系统已经具备 MCP 注册、`mcpServers` 导入、`tools/list` 发现、stdio 工具调用、skill 元数据和管理页面雏形，但这些能力仍偏 MVP：

- 自研 MCP 客户端只覆盖基础 stdio 调用，尚未完整承接协议兼容、会话生命周期、传输差异、取消、资源、提示、错误语义和长期连接治理。
- 自研 skill 模型主要是步骤元数据，缺少成熟编排运行时需要的状态恢复、分支控制、可观测性、重试策略、检查点、人工确认节点和执行轨迹。
- 前后端继续堆管理代码会快速滑向半成品低代码平台，无法有效提升上线可靠性。
- 医保场景具有高风险动作拦截、最小必要授权、敏感数据脱敏、审计留痕和来源引用等硬约束，适合在成熟框架之上建设领域治理层，而不是自研通用协议和编排引擎。

## Goals

- 使用 MCP SDK 或 FastMCP 替代自研 MCP 协议细节，统一 stdio、SSE、streamable HTTP 的连接、能力发现和工具调用适配。
- 使用 LangGraph 承载医保智能体执行循环、业务场景、skill 模板和人工确认流程。
- 保留并强化现有 MCP 注册服务、工具目录和 skill 元数据，将其定位为治理与配置层，而非运行时框架本体。
- 将现有 `settlement_exception_guidance`、`pre_discharge_quality_control`、`mcp_tool_invocation` 逐步迁移为 LangGraph 图或子图。
- 在 LangGraph 节点边界统一接入权限、风控、脱敏、审计、citations 和 uncertainties。
- 保持现有 FastAPI API 前缀和前端原型主要入口兼容，避免一次性重写产品壳。

## Non-Goals

- 不建设通用低代码流程设计器或 skill 市场。
- 不允许 MCP 或 LangGraph 绕过现有业务适配器、防腐层、安全审计和高风险动作人工确认。
- 不在本变更内替换所有医保业务系统适配器为真实外部系统。
- 不改变正式结算、退费冲正、病案修改等高风险动作必须由人工在既有系统执行的原则。
- 不把前端管理台扩展为复杂运维平台；前端只覆盖注册、发现、启停、权限、审计和测试调用等治理能力。

## Impact

- `knowledge_extension/mcp_registry` 保持为 MCP 能力注册与治理门面，底层调用适配到 MCP SDK 或 FastMCP。
- `business_scenarios/*` 的硬编码服务逐步降级为 LangGraph 节点或领域服务函数。
- `domain/skill` 和 `domain/tool` 从自研执行引擎输入模型转为 LangGraph 图模板、工具目录和治理元数据。
- `runtime` 新增 LangGraph runtime adapter，负责图构建、状态检查点、节点执行、人工确认中断和响应汇总。
- 安全、审计、脱敏和风险控制在节点边界形成强制拦截器或 wrapper。
- 测试体系需要新增 MCP SDK 适配器测试、LangGraph 图执行测试、人工确认中断测试和端到端回归测试。

