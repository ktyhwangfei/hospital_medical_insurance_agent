# src/apps/portal/ — 业务应用入口

## 概述

独立 Next.js 16 应用，提供医保 AI 导办平台的业务交互界面。包含政策问答、AI 导办对话、结算异常导办、出院前质控、运营看板五个业务页面。

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

## 设计哲学：导办即对话

Portal 的核心交互范式是 **"导办即对话"（Guidance as Conversation）** —— 不是传统的"点按钮→看结果"模式，而是通过自然对话引导用户完成医保业务操作。AI 的推理过程全程可见、可追溯，用户始终掌握控制权。

参考原型: `public/chat-v3-prototype.html`（v3 暗色系方案）

### 视觉设计系统

| Token | 用途 | 色值 |
|-------|------|------|
| `--bg-app` | 页面底色 | `#0a0e17`（深空蓝黑） |
| `--bg-chat` | 聊天区底色 | `#0f1520` |
| `--bg-card` | 卡片底色 | `rgba(255,255,255,0.03)` |
| `--text-primary` | 主文字 | `#f1f5f9`（高亮白） |
| `--text-secondary` | 辅助文字 | `#94a3b8`（灰蓝） |
| `--text-muted` | 弱化文字 | `#64748b` |
| `--cyan` | 意图/品牌色 | `#06b6d4` |
| `--blue` | 适配器色 | `#3b82f6` |
| `--purple` | MCP 色 | `#a855f7` |
| `--amber` | 知识/警告色 | `#eab308` |
| `--green` | 完成/正常色 | `#10b981` |
| `--red` | 错误色 | `#ef4444` |

**语义色法则**: 推理链每一步使用独立语义色（intent→cyan, adapter→blue, knowledge→amber, mcp→purple, rule→green），在 dots、badges、glow 上保持一致。用户可通过颜色快速辨识当前推理阶段。

**字体**: Noto Sans SC（正文）+ JetBrains Mono（等宽/代码/时长/错误码）

**动画基准**:
- `--ease-smooth`: `cubic-bezier(0.4, 0, 0.2, 1)` — 常规过渡
- `--ease-bounce`: `cubic-bezier(0.34, 1.56, 0.64, 1)` — 卡片入场弹性
- 消息入场: `message-in` 0.45s，从下方淡入 + 微缩放
- 思考链入场: `thinking-in` 0.5s，从下方滑入 + 缩放

### 核心交互组件

#### 1. AI 思维链卡片（ThinkingChainCard）

**定位**: 每条用户消息触发后，AI 的推理过程以**内联卡片**形式嵌入聊天流中，位于用户消息与最终回复之间。

**结构**:
```
┌─ 思维链头部 ─────────────────────────────────────┐
│ 🧠 AI 思维链 · 实时推理过程          [实时 ●]      │
├─ 步骤列表 ────────────────────────────────────────┤
│  ● 意图识别     [INTENT]  0.8s                     │
│  │  识别为「医保结算异常导办」· 置信度 97%           │
│  ● 适配器调用   [ADAPTER] 0.7s                     │
│  │  query_transaction(P001, E001) → failed          │
│  ● 知识检索     [KNOWLEDGE] 0.6s                   │
│  │  E-UPLOAD-001 → 费用明细未全部上传                │
│  ● MCP 工具调用 [MCP] 0.9s                          │
│  │  insurance-policy-mcp 返回政策原文                │
│  ● 规则校验     [RULE] 0.5s                         │
│  │  无高风险动作 · 已通过安全校验                    │
├─ 尾部 ────────────────────────────────────────────┤
│  ⏱ 总耗时: 3.5s              3/5 步骤完成           │
└───────────────────────────────────────────────────┘
```

**步骤状态机**: `pending（灰点+○待处理）→ running（彩色脉冲+⟳执行中）→ done（彩色实心✓+✓完成）`

**竖线连接**: 步骤之间 CSS `::before` 绘制竖线，已完成步骤的竖线变绿。

**MCP 步骤特殊标记**: MCP 工具调用使用紫色系（`--purple`），包含 `<mcp-tag>` 标签区分工具名。

#### 2. 导办卡片（GuidanceCard）

**定位**: 思维链完成后，结构化展示导办结果。用左侧彩色边框标识严重程度。

**Accent 系统**:
- `accent-error` → 左侧红色 4px 边框（结算失败等高优先级异常）
- `accent-warning` → 左侧琥珀色 4px 边框（质控风险等中优先级）
- `accent-normal` → 左侧绿色 4px 边框（正常结果）

**内容结构**:
- Header: 错误图标 + 标题 + 错误码
- Body: 摘要 → 处理步骤（编号圆形 + 步骤文字）→ 元信息（责任角色 / 风险等级 / 处理方式）
- Footer: 引用标签（`guidance-citation`），可点击查看知识来源

#### 3. 打字机效果（Typewriter）

- 最终回复使用逐字渲染，速度范围 20-50ms/字（随机波动模拟真实感）
- 闪烁光标 `|` 跟随文字末端，完成后淡出
- 支持 `<br>` 换行

#### 4. 快捷入口条（QuickEntryBar）

- 位于聊天视口顶部，含 2-3 个场景入口 pill 按钮
- Hover: 边框变 cyan + glow 阴影 + 上浮 1px
- Active: 缩放 0.96 反馈

#### 5. 建议追问条（SuggestionChips）

- 位于输入框上方，水平滚动
- 填充追问提示，点击填入输入框

#### 6. 连接状态徽章

- 右上角显示实时连接状态
- 绿色脉冲圆点 + "已连接" 文字
- `pulse-ring` 动画：由内向外扩散淡化

#### 7. 导航抽屉（Drawer）

- 汉堡菜单触发，左侧滑入
- 含场景导航、角色切换、快捷入口
- 玻璃拟态背景（`backdrop-filter: blur(20px)`）
- 遮罩层点击 / ESC 键关闭

### 聊天气泡规范

| 角色 | 气泡背景 | 圆角 | 对齐 |
|------|---------|------|------|
| AI (bot) | `--bg-card` + 1px border | `--radius-lg`，左下角 4px | 左对齐 |
| 用户 (user) | `--grad-user`（蓝→青渐变） | `--radius-lg`，右下角 4px | 右对齐 |

- 头像使用渐变色圆形（bot: 青→绿，user: 蓝→青）
- 消息最大宽度 88%，每条约 18px 间距
- 时间戳 10px 字号，弱化展示

### 背景氛围

- `scan-line` 叠加层：聊天区覆盖间隔 2px 的半透 cyan 横纹
- `particle` 浮动粒子：12 颗 2px 光点从底部上浮，随机延迟和速度

### 响应式

- 断点: 768px
- 消息最大宽度: 95%（移动端）
- 抽屉宽度不变（280px）
- 快捷 chip 字号缩小至 12px
- 思维链步骤字号缩小，footer 改为纵向排列
- 导办卡片 meta 改为纵向排列

## 结构

```
portal/
├── app/                         # Next.js App Router（项目根目录）
│   ├── layout.tsx               # 根布局（侧边栏 + 头部 + 角色切换器）
│   ├── globals.css              # Tailwind v4 CSS
│   ├── page.tsx                 # Chat 导办（默认路由）
│   ├── policy-qa/page.tsx       # 政策问答
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
| `/policy-qa` | PolicyQAWorkspace | `POST /policy-qa/stream` + `GET /policy-qa/suggestions` |
| `/` | SettlementChat | `POST /chat/stream` + `GET /patient-context` + `POST /tasks/confirm` |
| `/settlement` | SettlementExceptionList | `GET /workflows?scenario=settlement_exception` |
| `/qc` | DischargeQC | `GET /workflows?scenario=pre_discharge_qc` + `POST /tasks/confirm` |
| `/dashboard` | Dashboard | `GET /workflows` 聚合统计 |

## 注意事项

- 管理类组件（MCP管理、知识浏览、模型测试、技能管理）已迁移至 `src/apps/admin/`
- 嵌入式聊天组件已独立至 `src/apps/embed/`
- 数据流: `组件 → api-client.ts → fetch → next.config.ts rewrite → http://127.0.0.1:8000/api/v1/...`
- 后端不可达时自动降级为 mock 数据（仅 TypeError），HTTP 4xx/5xx 抛出 ApiClientError
