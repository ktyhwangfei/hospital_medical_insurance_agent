## Why

当前意图识别采用简单的关键词匹配（`service.py:1-6`），仅支持两种固定意图，无法处理复杂查询、多意图场景或未知意图。随着业务场景扩展，需要更智能的意图识别来提升用户体验和系统扩展性。

## What Changes

- 引入 LLM 驱动的智能意图识别，替代硬编码关键词匹配
- 支持意图分类、子意图识别和置信度评分
- 新增意图解析结果结构化输出（包含意图、实体、置信度）
- 支持多意图识别和意图优先级排序
- 新增未知意图的处理机制和学习能力
- 保持与现有 `detect_intent` 接口的向后兼容

## Capabilities

### New Capabilities
- `intent-parsing`: 基于 LLM 的意图识别和解析能力，支持结构化输出、置信度评分、实体提取
- `intent-routing`: 意图到业务场景的智能路由，支持多意图、优先级排序、降级策略

### Modified Capabilities

## Impact

- 修改文件：`src/runtime/intent/service.py`（主要）
- 新增文件：意图模式定义、提示模板、意图注册表
- 影响 API：`/chat` 端点的意图识别逻辑
- 依赖：模型服务（LLM）用于智能意图识别
- 向后兼容：保持现有 `detect_intent(message) -> str` 接口签名