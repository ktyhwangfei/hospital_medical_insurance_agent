## ADDED Requirements

### Requirement: Knowledge Explorer Tab Navigation

系统 SHALL 在 `prototype/src/app/page.tsx` 的 Tabs 组件中新增 "知识浏览" Tab，使用 `BookOpen` 图标 from lucide-react，与现有 Tab 样式一致。

#### Scenario: Knowledge explorer tab visible
- **WHEN** 用户打开原型首页
- **THEN** "知识浏览" Tab SHALL 显示在 Tab 导航栏中

### Requirement: Knowledge Asset Overview Panel

系统 SHALL 在知识浏览 Tab 中展示知识资产概览面板，使用与 `dashboard.tsx` 指标卡片相同的 4 列 grid Card 布局，显示当前系统中的知识资产分类和数量统计。

#### Scenario: Display asset categories
- **WHEN** 知识浏览 Tab 加载
- **THEN** 前端 SHALL 显示知识资产分类卡片，至少包含：错误码知识库、政策规则库、DRG/DIP 知识库，每个卡片显示条目数量

#### Scenario: Asset data from mock
- **WHEN** 知识扩展服务无独立 HTTP 端点
- **THEN** 前端 SHALL 使用 mock 数据展示示例知识资产，并在面板中标注"演示数据"

### Requirement: RAG Retrieval Test Interface

系统 SHALL 在知识浏览 Tab 中提供 RAG 检索测试区域，使用与 `settlement-chat.tsx` 相同的 Input+Button 输入样式，允许用户输入查询文本并查看模拟的检索结果。结果列表使用与 `discharge-qc.tsx` 风险列表相同的 Alert 卡片样式。

#### Scenario: Simulate RAG retrieval
- **WHEN** 用户在检索输入框中输入查询文本并点击"检索"
- **THEN** 前端 SHALL 展示模拟的检索结果列表，包含来源、相关度分数和摘要

#### Scenario: Empty retrieval result
- **WHEN** 模拟检索未匹配到结果
- **THEN** 前端 SHALL 显示"未找到相关知识"的空状态提示

### Requirement: Rule Explanation Display

系统 SHALL 在知识浏览 Tab 中提供规则解释展示区域，显示错误码和 DRG/DIP 规则的解释信息。

#### Scenario: Display error code explanations
- **WHEN** 知识浏览 Tab 加载
- **THEN** 前端 SHALL 展示常见错误码（ERR_001, ERR_002, ERR_003）的解释卡片，包含错误描述、可能原因和处理步骤

#### Scenario: Display DRG/DIP rule summaries
- **WHEN** 知识浏览 Tab 加载
- **THEN** 前端 SHALL 展示 DRG/DIP 相关规则的摘要列表

### Requirement: Prompt Template Preview

系统 SHALL 在知识浏览 Tab 中提供提示模板预览区域，展示系统使用的提示模板列表。

#### Scenario: Display template list
- **WHEN** 知识浏览 Tab 加载
- **THEN** 前端 SHALL 展示提示模板列表，每个模板显示名称、适用场景和角色

#### Scenario: Template data from mock
- **WHEN** 后端不提供模板列表端点
- **THEN** 前端 SHALL 使用 mock 数据展示示例模板，并标注"演示数据"
