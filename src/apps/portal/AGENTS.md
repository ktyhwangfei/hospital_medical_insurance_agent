# src/apps/portal/ — 业务应用入口

## 概述

独立 Next.js 16 应用，提供医保 AI 导办平台的业务交互界面。包含 AI 导办对话、结算异常导办、出院前质控、运营看板四个业务页面。

## 命令

```bash
npm run dev      # 开发服务器 (http://localhost:3000)
npm run build    # 生产构建
npm run lint     # ESLint 检查
```

## 关键约定

- **Next.js 16**: 非标准版本，API 可能与训练数据不同。编码前查阅 `node_modules/next/dist/docs/`
- **shadcn/ui**: 使用 `base-nova` 风格，组件在 `src/components/ui/`
- **路径别名**: `@/*` 映射到 `./src/*`
- **字体**: Noto Sans SC (中文)，通过 `next/font/google` 加载
- **API 代理**: `next.config.ts` 将 `/api/v1/medical-insurance-ai-agent/*` 代理到后端

## 结构

```
portal/
├── app/                         # Next.js App Router（项目根目录）
│   ├── layout.tsx               # 根布局（侧边栏 + 头部 + 角色切换器）
│   ├── globals.css              # Tailwind v4 CSS
│   ├── page.tsx                 # Chat 导办（默认路由）
│   ├── settlement/page.tsx      # 结算异常导办
│   ├── qc/page.tsx              # 出院前联合质控
│   └── dashboard/page.tsx       # 运营驾驶舱
├── src/
│   ├── components/              # 业务组件
│   │   ├── ui/                  # shadcn/ui 基础组件 (13个)
│   │   ├── settlement-chat.tsx  # AI导办对话（SSE流式）
│   │   ├── discharge-qc.tsx     # 出院前联合质控
│   │   ├── dashboard.tsx        # 运营驾驶舱
│   │   ├── intent-trace-card.tsx    # 意图追踪可视化卡片
│   │   ├── skill-mention-input.tsx  # @技能提及输入框
│   │   └── role-switcher.tsx        # 角色切换器
│   └── lib/
│       ├── api-client.ts        # API 客户端（端点函数 + SSE解析 + mock降级）
│       ├── api-context.tsx      # API 连接状态上下文（ApiProvider）
│       ├── types.ts             # TypeScript 类型定义
│       ├── mock-data.ts         # Mock 数据（离线降级用）
│       └── utils.ts             # 工具函数（cn()）
├── next.config.ts               # API 代理配置
├── components.json              # shadcn/ui 配置 (base-nova 风格)
└── package.json                 # next@16.2.4, react@19.2.4
```

## 路由与组件映射

| 路由 | 组件 | API 端点 |
|------|------|----------|
| `/` | SettlementChat | `POST /chat/stream` + `GET /patient-context` + `POST /tasks/confirm` |
| `/settlement` | SettlementExceptionList | `GET /workflows?scenario=settlement_exception` |
| `/qc` | DischargeQC | `GET /workflows?scenario=pre_discharge_qc` + `POST /tasks/confirm` |
| `/dashboard` | Dashboard | `GET /workflows` 聚合统计 |

## 注意事项

- 管理类组件（MCP管理、知识浏览、模型测试、技能管理）已迁移至 `src/apps/admin/`
- 嵌入式聊天组件已独立至 `src/apps/embed/`
- 数据流: `组件 → api-client.ts → fetch → next.config.ts rewrite → http://127.0.0.1:8000/api/v1/...`
- 后端不可达时自动降级为 mock 数据（仅 TypeError），HTTP 4xx/5xx 抛出 ApiClientError
