# src/apps/embed/ — 嵌入式 Chat Widget

## 概述

独立 Next.js 16 应用，精简版 AI 导办 Chat 组件，设计用于嵌入 HIS/EMR 系统的 iframe。单页面，无侧边栏。

## 命令

```bash
npm run dev      # 开发服务器 (http://localhost:3002)
npm run build    # 生产构建
npm run lint     # ESLint 检查
```

## 关键约定

- 与 portal/admin 共享相同的 API 客户端模式和 shadcn/ui 组件
- **硬编码**: cashier 角色、P001/E001 患者/就诊（嵌入场景固定）
- **UI 精简**: 无侧边栏、无多页面路由、仅 9 个 shadcn/ui 组件

## 结构

```
embed/
├── src/
│   ├── app/
│   │   ├── layout.tsx           # 最小布局（ApiProvider + Noto Sans SC）
│   │   ├── globals.css          # 仅 @import "tailwindcss"
│   │   └── page.tsx             # 单页：<EmbeddedChat />
│   ├── components/
│   │   ├── ui/                  # shadcn/ui 子集 (9个: avatar/badge/button/card/dialog/input/scroll-area/separator/textarea)
│   │   ├── embedded-chat.tsx    # 嵌入式 AI 对话（837行，SSE流式+意图追踪+确认对话框）
│   │   └── intent-trace-card.tsx # 意图追踪卡片（与 portal 完全相同）
│   └── lib/
│       ├── api-client.ts        # 精简 API 客户端（430行，仅 chat/confirm 端点）
│       ├── api-context.tsx      # ApiProvider（与 portal 相同）
│       ├── types.ts             # 子集类型（与 portal scope 一致）
│       ├── mock-data.ts         # 精简 Mock 数据
│       └── utils.ts             # cn() 工具函数
├── next.config.ts
├── components.json
└── package.json
```

## 注意事项

- `embedded-chat.tsx`（837行）是唯一业务组件，功能与 portal 的 `settlement-chat.tsx` 相似但更精简
- `intent-trace-card.tsx` 与 portal 版本完全相同（390行）
- CSS 极简：仅一行 `@import "tailwindcss"`，无自定义主题变量
- 无 `role-switcher`（角色硬编码为 cashier）
