This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.

## 前端原型 API 集成

### 新增文件

| 文件 | 职责 |
|------|------|
| `src/lib/types.ts` | 后端接口类型定义与 ApiClientError |
| `src/lib/api-context.tsx` | API 连接状态上下文（ApiProvider + useApiContext） |
| `src/lib/api-client.ts` | 统一 API 客户端（11 个端点函数 + SSE 解析 + mock 降级） |
| `src/components/mcp-management.tsx` | MCP 服务管理页面 |
| `src/components/knowledge-explorer.tsx` | 知识扩展浏览页面 |
| `src/components/model-test.tsx` | 模型测试页面 |

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `NEXT_PUBLIC_API_BASE_URL` | 后端 API 地址 | `http://127.0.0.1:8000` |

### API 代理

`next.config.ts` 配置了 rewrite，将 `/api/v1/medical-insurance-ai-agent/*` 代理到后端。

### 连接状态

页面右上角显示连接状态 Badge：
- 🟢 已连接：API 可达
- 🟠 离线模式：使用 mock 数据降级
- ⚪ 未检测：初始状态

### Mock 降级策略

- 网络错误自动降级为 mock 数据
- HTTP 错误（4xx/5xx）抛出 ApiClientError，不降级
- 降级响应包含 `fallback: true` 标识

### 人工确认流程

结算异常导办中，高风险动作会触发 `waiting_human_confirmation` 状态，弹出确认 Dialog。
