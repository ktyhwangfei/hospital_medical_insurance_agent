## ADDED Requirements

### Requirement: Model Test Tab Navigation

系统 SHALL 在 `prototype/src/app/page.tsx` 的 Tabs 组件中新增 "模型测试" Tab，使用 `FlaskConical` 或 `Zap` 图标 from lucide-react，与现有 Tab 样式一致。

#### Scenario: Model test tab visible
- **WHEN** 用户打开原型首页
- **THEN** "模型测试" Tab SHALL 显示在 Tab 导航栏中

### Requirement: Model Test Synchronous Mode

系统 SHALL 在模型测试 Tab 中提供同步模式测试界面，使用与 `settlement-chat.tsx` 相同的左右分栏布局（左侧参数配置 1:3 右侧结果展示），允许用户输入测试消息和场景参数，调用后端 `POST /api/v1/medical-insurance-ai-agent/model-test`，展示模型响应内容、模型名称、延迟和 token 用量。

#### Scenario: Successful synchronous model test
- **WHEN** 用户输入消息并点击"发送测试"，后端返回 200
- **THEN** 前端调用 `testModel({ message, scene })`，展示响应内容、模型名称（`model_name`）、延迟（`latency_ms`）、prompt tokens 和 completion tokens

#### Scenario: Model test with config error
- **WHEN** 后端返回 503（MODEL_CONFIG_ERROR）
- **THEN** 前端 SHALL 显示"模型服务未配置 API Key"的错误提示

#### Scenario: Model test with upstream error
- **WHEN** 后端返回 502（MODEL_UPSTREAM_ERROR）
- **THEN** 前端 SHALL 显示"模型服务上游暂时不可用"的错误提示

#### Scenario: Model test fallback
- **WHEN** 后端不可达
- **THEN** 前端 SHALL 显示模拟的模型测试结果，并标注"离线模式 - 演示数据"

### Requirement: Model Test Streaming Mode

系统 SHALL 在模型测试 Tab 中提供流式模式测试界面，调用后端 `POST /api/v1/medical-insurance-ai-agent/model-test/stream`，实时展示模型输出。

#### Scenario: Streaming model output
- **WHEN** 用户选择流式模式并点击"发送测试"
- **THEN** 前端使用 `fetch` + `ReadableStream` 解析 SSE 事件流，实时在输出区域追加文本内容

#### Scenario: Streaming model error
- **WHEN** 流式请求过程中后端发送 `error` 事件
- **THEN** 前端 SHALL 停止流式输出并显示错误信息

### Requirement: Model Test Parameter Configuration

系统 SHALL 在模型测试 Tab 中提供参数配置区域，包含消息输入框和场景选择下拉框。

#### Scenario: Scene selection
- **WHEN** 用户展开场景下拉框
- **THEN** 前端 SHALL 显示可选场景列表：`default`、`settlement_exception`、`pre_discharge_qc`、`drg_analysis`

#### Scenario: Custom message input
- **WHEN** 用户在消息输入框中输入文本
- **THEN** 前端 SHALL 将输入文本作为 `message` 参数传递给模型测试请求

### Requirement: Model Test Result History

系统 SHALL 在模型测试 Tab 中保留本次会话的测试历史记录，使用与 `page.tsx` SettlementExceptionList 相同的 Card 列表样式，以时间倒序展示。

#### Scenario: Display test history
- **WHEN** 用户完成一次模型测试
- **THEN** 前端 SHALL 将测试参数和结果添加到历史记录列表，显示时间戳、场景、延迟和响应摘要

#### Scenario: Clear history
- **WHEN** 用户点击"清除历史"按钮
- **THEN** 前端 SHALL 清空测试历史记录
