# PRD：政策知识管线（Policy Knowledge Pipeline）

> 版本 v1.0 | 2026-07-22

---

## 一、目标 / 非目标

### 目标

1. 将政策知识生产从"散落脚本 + 最终规则表格"升级为**可视化的三步管线**：政策原文 → 规则提取 → 入库生效
2. **留存每一步的中间产物**，支持回溯、问题定位、局部重跑，避免出错后从头再来
3. 前期全手动触发每步，后续逐步自动化；UI 上每步都有明确的**执行按钮 + 结果审计界面**
4. 建立**溯源链**：每条入库规则可追溯到来源政策原文和中间提取记录
5. 提供**变更感知**：政策原文变更后，标记受影响的规则，提示重新提取
6. 提供**审核环节**：提取结果入库前需人工确认/修正

### 非目标

- 不在此 PRD 中实现全自动流水线（手动跑通后再做）
- 不改造现有的 `policy-qa` 问答链路和 `policy_rules` Milvus schema
- 不涉及 MCP 注册中心、技能注册等其他知识扩展模块
- 不做大规模批量调度（第一步先做单文件/单批次的交互式操作）

---

## 二、用户故事

| ID | 角色 | 故事 |
|----|------|------|
| US-1 | 医保政策管理员 | 我上传/导入一份政策文件（PDF/网页/Excel），系统将其保存为"政策原文"，我能在列表里看到它和它的处理状态 |
| US-2 | 医保政策管理员 | 我选中一条政策原文，点击"开始提取"，系统调用后端提取管线，完成后我能看到提取出的规则候选列表，并逐条修正/删除 |
| US-3 | 医保政策管理员 | 我对审核通过的候选规则点击"入库"，系统将其写入 Milvus `policy_rules`，并建立原文→规则的双向溯源关联 |
| US-4 | 医保政策管理员 | 当某条政策原文更新后，系统标记其关联规则为"待复核"，我能在概览页看到受影响数量，并决定重新提取 |
| US-5 | 医保政策管理员 | 管线概览页展示三步各有多少条数据、多少条待处理，我能一目了然知道卡在哪一步 |
| US-6 | 医保政策管理员 | 我在任何一步看到中间产物（结构文本、提取事实、候选规则），不用回到第一步重来 |

---

## 三、方案概述

### 3.1 数据模型

新增三张 PostgreSQL 表 + 一个 Milvus 字段（最小新增，复用现有 schema）：

| 表/字段 | 用途 | 关键字段 |
|---------|------|---------|
| `policy_documents` (PG) | 政策原文 | `doc_id`, `title`, `source_type`（crawl/upload/manual）, `source_url`, `content_text`, `content_hash`, `status`（raw/processing/extracted/archived）, `created_at`, `updated_at` |
| `policy_extractions` (PG) | 提取的候选规则 | `extraction_id`, `doc_id`→policy_documents, `source_text`, `extracted_fields` (JSONB: rule_type/insu_type/…), `confidence`, `status`（draft/reviewed/rejected/published）, `reviewed_by`, `reviewed_at` |
| `policy_rule_lineage` (PG) | 溯源关联 | `lineage_id`, `rule_id`→Milvus, `extraction_id`, `doc_id`, `created_at` |
| `policy_rules` (Milvus) 新增字段 | `doc_id` (VarChar) | 每条规则记录来源文档 ID，支持反向查询 |

### 3.2 前端结构

仿语义层的 layout + 多 tab 子页面：

```
/policy-knowledge                    → 管线概览（Dashboard）
/policy-knowledge/documents          → 政策原文管理（列表 + 上传 + 详情）
/policy-knowledge/extractions        → 规则提取结果（列表 + 审核 + 修正）
/policy-knowledge/rules              → 已入库规则（即现有页面，增强溯源列）
```

**Tab 导航**：`概览 | 政策原文 | 规则提取 | 已入库规则`

### 3.3 三步管线的 UI 交互

```
Step 1: 政策原文
  [上传文件] [爬虫导入] [手动录入]
  → 列表：文件名 / 标题 / 来源 / 状态 / 关联规则数 / 操作
  → 操作：[查看原文] [开始提取] [删除]
  → 点击"开始提取" → 触发后端提取任务 → 状态变为 processing → 完成后跳至 Step 2

Step 2: 规则提取
  → 列表：来源原文 / 提取字段摘要 / 置信度 / 状态 / 操作
  → 状态：草稿 → 已审核 → 已入库
  → 操作：[查看详情] [编辑修正] [通过] [驳回] [入库]
  → "入库" → 写 Milvus + lineage → 状态变为已入库

Step 3: 已入库规则
  → 即现有 policy-knowledge 规则表格
  → 新增列：来源原文（doc_id → doc_title）
  → 新增筛选：按来源原文过滤
  → 原文变更时，关联规则标记"待复核"
```

### 3.4 后端改动

| 模块 | 改动 |
|------|------|
| `runtime/api/` | 新增 `policy_pipeline_routes.py`（documents/extractions CRUD + 触发提取） |
| `knowledge_extension/rule_explanation/` | 新增 `pipeline_orchestrator.py`，串联现有模块：struct → extract → fact → candidate（暂不自动 ingest，由人工触发） |
| `data_platform/persistence/` | 新增 `policy_documents` / `policy_extractions` / `policy_rule_lineage` 的 PostgreSQL 存储实现 |
| `data_platform/storage/` | 若有文件上传，新增本地文件存储（政策原文 PDF/Excel） |

### 3.5 概览页 Dashboard

参考语义层首页，展示：

| 区域 | 内容 |
|------|------|
| 顶部统计卡片 | 政策原文数 / 提取候选数 / 已入库规则数 / 待审核数 |
| 三步进度条 | Step 1→2→3 各有多少条，进度百分比 |
| 待处理提醒 | 待提取的原文数、待审核的提取数、待复核的规则数 |
| 最近活动 | 最近 5 条操作日志（谁在什么时间提取/审核/入库了哪条） |

---

## 四、验收标准

1. **原文管理**：能从三种来源（上传/爬虫/手动）创建政策原文，列表展示，可查看原文内容
2. **提取触发**：选中原文点击"开始提取"，后端异步执行提取管线，完成后前端自动刷新
3. **中间产物留存**：提取结果持久化在 `policy_extractions` 表，列表可见，支持详情查看和字段编辑
4. **审核入库**：提取结果经人工确认后，点击"入库"写入 Milvus，同时写入 lineage 关联，入库后状态不可回退
5. **溯源查询**：在已入库规则列表中，每条规则可反查来源原文；在原文详情中，可查看对应已入库规则
6. **变更感知**：原文内容变更（content_hash 变化）后，其关联规则在规则列表中标记"待复核"角标
7. **管线概览**：Dashboard 正确展示各步数量、待处理数、进度条
8. **三步可独立操作**：中间步骤失败/驳回不影响其他步骤，可局部重跑
9. **现有功能不受影响**：已入库规则页面的查询/筛选/编辑/删除功能保持正常
10. **幂等**：同一原文重复提取不产生重复候选规则（按 doc_id + source_text_hash 去重）

---

## 五、风险与开放问题

| # | 风险/问题 | 等级 | 应对 |
|---|----------|------|------|
| R1 | 现有提取模块（policy_struct/extract/fact/node）之间缺少统一编排，串联工作量大 | 高 | 先做最小串联（struct→extract→candidate），跳过 fact/node 的复杂评分逻辑，等跑通后再加 |
| R2 | Milvus `policy_rules` 新增 `doc_id` 字段需 schema 变更，存量数据无此字段 | 中 | 新字段默认空串，存量规则 doc_id 为空，前端显示"未知来源"；不做历史数据回填 |
| R3 | 文件上传引入存储管理复杂度（文件清理、大小限制、格式校验） | 中 | 第一版限制单文件 ≤ 10MB，仅支持 PDF/Excel/TXT；用本地文件系统存储，路径存 DB |
| R4 | 异步提取任务需要任务状态管理（队列/超时/失败重试） | 中 | 第一版用同步 HTTP 请求 + 前端 loading（单文件提取通常 < 30s），后续再上任务队列 |
| R5 | 没有规则审核的多人协作机制（谁审核？审核标准？） | 低 | 第一版单人操作（admin 角色），reviewed_by 字段预留但暂不做权限校验 |

### 开放问题

1. **爬虫导入的触发方式**：是手动粘贴 URL 触发，还是定时扫描？——建议第一版手动粘贴 URL + 点击"抓取"
2. **提取失败的处理**：如果 LLM 提取结果格式不规范（JSON 解析失败），是直接标记失败还是降级为人工录入？——建议标记"提取失败"，允许人工手动填写字段后入库
3. **"全自动"的触发条件**：未来全自动模式下，是爬虫入库后自动触发提取 → 低于置信度阈值的才人工审核？——本次不实现，第二期再定义
