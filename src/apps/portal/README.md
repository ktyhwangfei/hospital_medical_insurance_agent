This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## 启动

```powershell
..\ws.ps1 up issue21
..\ws.ps1 url issue21
```

服务必须由工作区父目录的 `ws.ps1` 管理；不要直接运行 `npm run dev`。

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.

## Portal

当前唯一业务入口是 `/policy-qa`，请求必须提供结算单号。`/settlement`、`/qc`、`/dashboard` 及旧 Chat 页面已退役并返回 404。

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `NEXT_PUBLIC_API_BASE_URL` | 后端 API 地址 | `http://127.0.0.1:8000` |

### API 代理

`next.config.ts` 配置了 rewrite，将 `/api/v1/medical-insurance-ai-agent/*` 代理到后端。

Policy QA 不使用 mock 数据降级；后端或数据源不可用时展示不可用状态与不确定性。
