# 测试开发说明

> 风险等级、最低验证范围和通过口径唯一以 `docs/governance/TEST-VERIFICATION-MATRIX.md` 为准。

## 硬性顺序

所有代码改动按以下顺序验证，前一层未通过不得跳到后一层宣称完成：

1. Unit：`src/tests/unit/`
2. API：`src/tests/integration/api/`
3. Flow：`src/tests/integration/flow/`
4. R4 变更再执行性能、Portal 和浏览器 E2E。

缺陷修复必须先写能复现问题的失败测试，再实施修复并观察转绿。测试断言公开行为，不依赖已删除的兼容入口或内部实现细节。

## 当前业务测试边界

`policy-qa` 是唯一业务流。旧 `/chat*`、`/workflows*`、`/tasks/confirm`、结算异常导办、出院质控和 LangGraph 业务图已退役；相关测试资产已删除，不得恢复。

核心映射：

| 代码 | Unit | API | Flow | Portal/E2E |
|---|---|---|---|---|
| `runtime/api/policy_qa_routes.py`、`runtime/policy_qa/` | `unit/runtime/policy_qa/` | `integration/api/test_policy_qa_routes.py` | `integration/flow/test_policy_qa_*` | Portal Vitest + `e2e/smoke/portal-smoke.spec.ts` |
| `skill_infra/`、`skills/settlement_explain_skill/` | 对应 unit / skill tests | infra skill API | skill / policy QA flow | `/skills` 工作台测试 |
| `model_service/` | `unit/model_service/` | model governance API | governance flow | `/model-governance` 测试 |
| `knowledge_extension/`、`semantic_layer/` | 对应 unit | knowledge / semantic API | knowledge / semantic flow | 治理工作台测试 |

## Policy QA 验收重点

- 请求必须包含 `question` 与 `settlement_id`。
- 公开结果只允许 `PolicyQAPublicResult` 字段，并具备 citations 或 uncertainties。
- SQL、表名、内部字段和推理轨迹不得进入 SSE 公开数据。
- 瞬时结算/政策数据源故障最多恢复一次；缺记录、配置错误和确定性 `partial/unavailable` 不重试。
- 流程出现 `recovery`（仅需要时）和 `verification`，最终 `done` 包含 `attempt_count`、`halt_reason`。
- `/settlement`、`/qc`、`/dashboard` 页面不存在；旧业务 API 返回 404。

## 常用命令

```powershell
# Unit
uv run python -m pytest src/tests/unit/runtime/policy_qa -q

# API
uv run python -m pytest src/tests/integration/api/test_policy_qa_routes.py -q

# Flow
uv run python -m pytest src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py -q

# Portal
Set-Location src/apps/portal
npm test
npm run build
```

完整套件使用 `uv run python -m pytest src/tests/unit -q`、`integration/api -q`、`integration/flow -q`。若收集阶段因仓库未声明的可选测试依赖失败，记录缺失包和退出码；不得将其写成代码已通过，也不得为了单个任务擅自扩大生产依赖。

## 测试编写约定

- 后端使用 `src.` 前缀导入；异步测试使用 `pytest.mark.asyncio`。
- API 测试通过 `create_app()` 新建应用并覆盖依赖，禁止连接真实生产资源。
- SSE 测试必须验证事件顺序、终止事件和安全白名单。
- 外部 PostgreSQL、Milvus、SQL Server 测试必须明确标注环境依赖；不可用时与确定性单元测试分开报告。
- Portal 测试使用 Vitest；`@/app/...` 在 Vitest 中不可解析时使用相对路径。
- 服务型 E2E 只通过 `..\ws.ps1` 管理工作区实例。
