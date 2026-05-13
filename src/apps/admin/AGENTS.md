# src/apps/admin/ — 平台管理入口

## 概述

独立 Next.js 16 应用，提供 MCP 管理、知识管理、模型管理、技能管理四大管理模块。所有管理类 CRUD 组件从 portal 迁移至此。

## 命令

```bash
npm run dev      # 开发服务器 (http://localhost:3001)
npm run build    # 生产构建
npm run lint     # ESLint 检查
```

## 关键约定

- **Next.js 16**: 非标准版本，编码前查阅 `node_modules/next/dist/docs/`
- **shadcn/ui**: 使用 `base-nova` 风格，组件在 `src/components/ui/`
- **路径别名**: `@/*` 映射到 `./src/*`
- **API 代理**: `next.config.ts` 将 `/api/v1/medical-insurance-ai-agent/*` 代理到后端
- **与 portal 共享**: `role-switcher.tsx` 完全相同，`lib/` 结构相同

## 结构

```
admin/
├── src/
│   ├── app/                     # Next.js App Router
│   │   ├── layout.tsx           # 根布局（AdminSidebar + 头部）
│   │   ├── globals.css          # Tailwind v4 + tw-animate-css
│   │   ├── page.tsx             # 管理首页（导航卡片 + 概览）
│   │   ├── mcp/page.tsx         # MCP 管理
│   │   ├── knowledge/page.tsx   # 知识管理
│   │   ├── model/page.tsx       # 模型管理
│   │   └── skills/page.tsx      # 技能管理
│   ├── components/
│   │   ├── ui/                  # shadcn/ui 基础组件 (13个)
│   │   ├── admin-sidebar.tsx    # 管理侧边栏（5项导航）
│   │   ├── mcp-management.tsx   # MCP CRUD（518行）
│   │   ├── knowledge-management.tsx  # 知识总管（Tabs 5类）
│   │   ├── knowledge-asset-crud.tsx  # 资产+切片 CRUD（620行）
│   │   ├── knowledge-explorer.tsx    # RAG 搜索浏览
│   │   ├── rule-explanation-crud.tsx # 规则解释 CRUD（448行）
│   │   ├── appeal-template-crud.tsx  # 申诉模板 CRUD（339行）
│   │   ├── prompt-template-crud.tsx  # 提示词模板+渲染（464行）
│   │   ├── model-management.tsx      # 模型配置+路由+退避+Provider（1007行）
│   │   ├── model-test.tsx            # 模型测试（413行）
│   │   ├── skill-management.tsx      # 技能+工具 CRUD（1040行）
│   │   └── role-switcher.tsx         # 角色切换器（与 portal 完全相同）
│   └── lib/
│       ├── api-client.ts        # 扩展 API 客户端（806行，含全部 CRUD 端点）
│       ├── api-context.tsx      # ApiProvider（与 portal 相同）
│       ├── types.ts             # 扩展类型（含 CRUD 相关类型）
│       ├── mock-data.ts         # 扩展 Mock 数据
│       └── utils.ts             # cn() 工具函数
├── next.config.ts
├── components.json
└── package.json                 # next@16.2.4, react@19.2.4
```

## 路由与组件映射

| 路由 | 组件 | API 端点 |
|------|------|----------|
| `/` | Admin Dashboard | 概览卡片导航 |
| `/mcp` | McpManagement | `/mcp/servers`, `/mcp/capabilities`, `/mcp/storage/health` |
| `/knowledge` | KnowledgeManagement (Tabs) | `/knowledge/error-codes`, `/rules`, `/assets`, `/appeal-templates`, `/prompt-templates` |
| `/model` | ModelManagement + ModelTest | `/model-config`, `/model-routes`, `/model-providers`, `/model-test/stream` |
| `/skills` | SkillManagement | `/skills`, `/skills/{skill_id}` |

## 注意事项

- `api-client.ts`（806行）是最大的 lib 文件，覆盖全部管理 CRUD 端点
- knowledge 页面单组件 5 个 Tab，每个子 CRUD 有独立组件文件
- model-management.tsx（1007行）和 skill-management.tsx（1040行）是最大的组件
- 数据流同 portal: `组件 → api-client.ts → fetch → next.config.ts rewrite → backend`
- 后端不可达时自动降级为 mock 数据（仅 TypeError）
