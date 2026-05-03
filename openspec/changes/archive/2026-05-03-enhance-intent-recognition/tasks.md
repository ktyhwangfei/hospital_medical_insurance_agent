## 1. 基础结构

- [ ] 1.1 创建 `src/runtime/intent/models.py`，定义 IntentResult Pydantic BaseModel（intent、confidence、entities、citations、raw_message）
- [ ] 1.2 创建 `src/runtime/intent/registry.py`，定义意图注册表（意图标识、描述、示例、优先级、路由映射）
- [ ] 1.3 创建 `src/runtime/intent/prompts.py`，定义 LLM 提示词模板（含 JSON 输出约束和意图列表）

## 2. 模型路由配置

- [ ] 2.1 在 `src/config/model_routing.py` 的 ROUTING_TABLE 中新增 `("intent_recognition", ModelType.LLM)` 条目
- [ ] 2.2 在 MODEL_PARAMS 中配置 intent_recognition 场景参数（temperature=0.1, max_tokens=512）

## 3. 核心实现

- [ ] 3.1 实现 `src/runtime/intent/parser.py`，包含 `parse_intent(message: str) -> IntentResult` 函数
- [ ] 3.2 实现 LLM 调用逻辑（调用 ModelGateway，scene="intent_recognition"）
- [ ] 3.3 实现 JSON 解析逻辑（从 LLM 响应中提取 JSON，解析失败则降级）
- [ ] 3.4 实现降级策略（LLM 失败时回退到关键词匹配，confidence=0.5）

## 4. 意图注册表

- [ ] 4.1 注册 settlement_exception_guidance 意图（描述、示例、优先级=1）
- [ ] 4.2 注册 pre_discharge_quality_control 意图（描述、示例、优先级=2）

## 5. 实体提取

- [ ] 5.1 实现患者标识提取（patient_id、patient_name）
- [ ] 5.2 实现错误码提取（error_code）

## 6. 向后兼容

- [ ] 6.1 修改 `src/runtime/intent/service.py` 的 `detect_intent(message)` 函数，内部调用 `parse_intent`，保持 `-> str` 返回值
- [ ] 6.2 更新 `src/runtime/intent/__init__.py`，导出 parse_intent 和 IntentResult

## 7. 路由集成

- [ ] 7.1 更新 `src/runtime/api/routes.py` 的 `chat()` 函数，使用 `parse_intent` 获取结构化结果
- [ ] 7.2 将 IntentResult 中的 entities 和 citations 传递给 AgentResponse

## 8. 测试

- [ ] 8.1 编写 IntentResult 模型单元测试（字段验证、序列化）
- [ ] 8.2 编写 parse_intent 函数单元测试（LLM 成功、LLM 超时降级、JSON 解析失败降级）
- [ ] 8.3 编写意图注册表单元测试（意图列表、优先级排序）
- [ ] 8.4 编写意图路由集成测试（/chat 端点端到端）
- [ ] 8.5 编写向后兼容测试（detect_intent 返回字符串）

## 9. 文档

- [ ] 9.1 更新 AGENTS.md 中的意图识别部分
