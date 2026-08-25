# Portal 开发说明

## 产品边界

Portal 是 Next.js 16 应用。`/policy-qa` 是唯一业务入口，根路径 `/` 重定向到它；`/settlement`、`/qc`、`/dashboard` 已退役并应返回 404。语义层、政策知识、Skill、模型治理和问答历史页面属于治理与支撑工作台，不是并列业务流程。

涉及 Next.js API 或约定时，先查 `node_modules/next/dist/docs/`；依赖不存在时先执行 `npm ci`。服务启停统一使用工作区父目录的 `..\ws.ps1`。

## Policy QA 前端主链

- `app/policy-qa/page.tsx`：唯一业务页面。
- `src/components/policy-qa/`：Composer、消息列表、公开回答、查证摘要。
- `src/lib/use-policy-qa-stream.ts`：调用 `POST /api/v1/medical-insurance-ai-agent/policy-qa/stream` 并消费 SSE。
- `src/lib/policy-qa-stream.ts`：严格解析 `PolicyQAPublicResult`。
- `src/lib/policy-qa-session.ts`：会话锚点、记忆卡和公开消息模型。

结算单号是每轮政策问答的必需上下文。UI 只展示公开进度文案与 `complete/partial/unavailable` 结果，不保存或渲染内部步骤名、SQL、表字段、模型推理轨迹。

Loop 相关 `recovery`、`verification` 仍通过普通 `step.public_message` 展示；`done` 结束流。前端不得自行发起第二套重试，否则会突破后端两次上限。

## 跨层一致性

- SSE 与 DTO 在 `src/lib/` 集中完成 snake_case → camelCase 转换。
- `result` 只接收后端 `PolicyQAPublicResult` 白名单字段。
- `qa_turn_id` 在 `result` 与 `done` 必须一致。
- 新增公开字段时同时更新后端 Pydantic、前端解析器和 Vitest。

## 验证

```powershell
npm test
npm run build
```

路由边界测试：`src/tests/routing/policy-qa-only-entry.test.ts`。浏览器验证使用仓库 `src/tests/e2e/`，不要手工猜端口。
