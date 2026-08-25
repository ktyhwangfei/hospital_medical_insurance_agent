# Runtime 开发说明

## 当前边界

`/policy-qa` 是唯一业务入口。结算单不是独立场景，而是政策问答的必需业务上下文。旧 `/chat*`、结算异常导办、出院前质控、通用场景分发和 LangGraph 业务图均已退役，禁止重新引用。

主要目录：

- `api/policy_qa_routes.py`：Policy QA SSE 主入口、公开结果验证、最多两次的有界恢复。
- `policy_qa/settlement_data_provider.py`：真实 SQL Server 结算上下文；不允许 mock 回退。
- `policy_qa/structured_policy_retriever.py`：Milvus 结构化政策检索。
- `policy_qa/public_contract.py`：唯一公开响应白名单。
- `policy_qa/runtime_bridge.py`、`context/`、`memory/`、`reasoning/`：会话上下文增强，不向 UI 暴露内部推理。
- `task_closure/`、`policy_qa/persistence.py`：问答任务、工作流和历史记录。
- `skill_management/`：Skill 治理控制面，不是第二业务入口。

## Policy QA 主链

```text
POST /api/v1/medical-insurance-ai-agent/policy-qa/stream
  → 校验 question + settlement_id
  → 查询真实结算单
  → SkillRouter / settlement_explain_skill
  → 结构化政策检索
  → assembler 生成解释
  → _build_public_result 确定性验证
  → result + done
```

Loop 约束：

- 只重试 `SettlementDataUnavailableError` 和 `PolicyRetrievalUnavailableError`。
- 整个请求最多进入第 2 次尝试；不做无限重试或模型自评。
- 缺结算记录、配置错误、无匹配政策或已验证的 `partial/unavailable` 不重试。
- 恢复与验证以公开 `step` 事件呈现；`done` 和任务记录必须携带 `attempt_count`、`halt_reason`。
- 成功由 `PolicyQAPublicResult` 的确定性校验决定，不接受模型自称完成。

## 排障零步骤

先确认用户访问的工作区 URL 和 SSE 端点确实是 `/policy-qa/stream`。服务启停一律使用仓库父目录的 `..\ws.ps1`；不得直接启动 uvicorn 或 Next dev server。

渲染异常先抓 SSE 原始事件，确认 `context_need → step → result → done` 的数据和时序，再修改 UI。外部数据源错误先区分：缺记录/配置错误（不可重试）与超时/连接故障（可重试）。

## 验证

按 `src/tests/AGENTS.md` 和 `docs/governance/TEST-VERIFICATION-MATRIX.md` 执行 Unit → API → Flow。核心聚焦命令：

```powershell
uv run python -m pytest src/tests/unit/runtime/policy_qa -q
uv run python -m pytest src/tests/integration/api/test_policy_qa_routes.py -q
uv run python -m pytest src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py -q
```
