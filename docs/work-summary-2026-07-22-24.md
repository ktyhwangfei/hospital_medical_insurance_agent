# 三日工作综合报告（2026-07-22 ~ 07-24）

> **范围**：72 个提交（07-22 架构收敛 / 07-23 收尾 / 07-24 政策管线 P0→P8 爆发，单日 52 提交）
> **核心主线**：政策知识管线重构（P0→P8）+ 语义层收敛 + 前端 portal 落地
> **里程碑达成**：M1（P0+P1+P2 地基）、M2（P3 入库通路）、M3（P4 质量门禁）、M4（P6 跨世界检索）

---

## 一、工程治理与架构收敛（07-22）

| 工作 | 提交 | 要点 |
|------|------|------|
| Git 规范化 | `024a792` `15112d5` `8ae83f3` | 配置 .gitignore、identity；untrack 338 文件（agent/IDE 临时目录、debug 日志、.env） |
| 废弃模块清理 | `e028e29` `6460f62` `a3d8f8a` | 移除 legacy admin/embed 前端、DEPRECATED service re-export、mcp_tool_invocation 死代码 |
| 过时测试清理 | `3673249` | 删除已删模块的测试（-3975 行），修复幸存 fixture |
| 前端 portal | `6616b32` | policy-qa / settlement / semantic-layer / skills 四大页面 |
| 文档体系 | `699491f` `e5aa257` | PROGRESS.md（32 单元追踪）、AGENTS.md 同步单应用架构、规划/规格文档 |

---

## 二、语义层基础（07-22 ~ 07-23，阶段 1-5）

语义层从"散乱编码"收敛为"版本化、锁定式"的可靠底座：

| 阶段 | 提交 | 成果 |
|------|------|------|
| 1 编码统一 | `3c52a21` | 统一为 `zydyxx.*` 物理编码（消除编码歧义） |
| 2 版本快照 | `6d40988` | 对象级版本快照 + 发布控制 |
| 3 锁定消费 | `4724d2e` | `get_metric_mapping` 锁定到已发布版本快照（运行时不漂移） |
| 4 skill 锁定 | `eec2f0c` `851283e` | skill `locked_versions` 版本锁定 + assembler 准入守卫 |
| 5 前端接通 | `a801b4b` | 对象发布 UI 接通版本快照 API |
| A-重 桥接 | `38b2d8e` | skill 语义层数据桥接（锁定对 skill 硬生效） |
| 补丁 | `66d516e`（07-23） | hospital_level 定义为常量指标（消除 gap） |

---

## 三、政策知识管线（07-24，核心主线）

> 文档：`docs/steering/政策知识管线开发计划.md`。策略：**平行建新通路 → 最后一把切换**（P10 灰度，全程在新 collection `*_v2` 上建，生产读旧路径不受影响）。

### P0 地基修复
- `d6e1429` extraction contract builder（zcgz，§7.1）
- `f19ff55` `GET /semantic/objects/{code}/extraction-schema` 端点
- `da4d8ee` `12a6c46` **Milvus 端口 19121→19530 修正**（历史文档误记）
- `10aaff8` **向量维度修复**：PolicyRulesSearchEngine 默认 sentence_transformer(768维)
- `a8f2fcb` zcgz 核心维度标记 indexed + extraction hints
- `1b3c26f` policy_qa 标量检索回归基线

### P2 新模型 schema（§3.3）
- `47da397` **policy_rules_v2 collection**：核心维度固定 schema + 标量索引 + dynamic field
- `cb6a843` `rule_to_entity` 字段级溯源（FieldTrace：value/extracted_at/schema_version/confidence）

### P3 入库通路（§3.2/3.3/4.1）
- `9291bd1` `upsert_facts` 批量写 policy_facts
- `c8dec82` `upsert_rules` 批量写 policy_rules_v2
- `5e44dbf` `publish_to_new_collections`（facts+rules_v2 写入，**向量复用** §4.1）
- `e3254dd` 修复 create 自动连 Milvus + rule 补 doc_id
- **M2 达成**：demo 端到端验证（原文→提取→facts+rules_v2）

### P4 质量门禁（§5）
- `624322b` `publish_object` 同步 metric.status draft→published + 空对象门禁（**解锁 §3.1**）
- `88999b9` publish→extraction_schema 端到端验证

### §3.1 schema-driven prompt
- `9694aa1` `build_prompt_from_schema`（加维度不改代码）
- `67e7078` `run_extraction` 用 schema-driven prompt + legacy 回退

### P6 混合检索（§4.2/4.3/7.5）
- `6da746b` `b508690` RulesSearchService **三模式**：precise / semantic / hybrid + 按 fact 分组
- `3565cbd` `POST /rules/search` 混合检索端点
- `c0f7e16` `c932614` **跨世界查找**：`target=database|both`（经登记号 djh 联查政策↔业务库）
- **M4 达成**：三模式 + 跨世界

### P5 schema 演化引擎（§6/7.3-4）
- `43b9372` 三策略执行器：incremental（冻结保护）/ full（整条重提取）/ soft_delete + read-modify-write 编排
- `ae2b83f` evolve 分批 + 进度回调 + schema-update task API
- `f2e066c` publish 接执行器（affected_docs 触发 evolve）
- `000e98c` `query_rules_by_doc` read 函数（执行器 read 步骤）

### P7 多源数据（§7.6/8.1）
- `a71362c` **P7.1 数据源注册表 API**（`/semantic/datasources` CRUD）
- `b1c67c9` **P7.2 source_field 三段式解析**（`ds.table.column`）+ 查询计划多源分组
- `e2e4726` `3de1f15` **P7.2b 多源连接路由** `_resolve_datasource_connection` + `_query_flat`（按 ds_id 选连接）
- `74ffaae` `a6c46c8` `run_discovery` 多源扫描 + scan 端点接注册表
- `ea8e639` **P7.3 discovery_scanner**（扫高频信号产出候选指标）

---

## 四、前端对接

- `d8f2610` 检索页面接 `/rules/search` + publish-v2 入库按钮
- `f2ede20` 检索页面解包 FieldTrace 字段级溯源对象显示 value
- `a801b4b` 对象发布 UI

---

## 五、验证与质量

- **TDD 纪律**：每个 phase 先写 TDD 计划文档再实现（P2/P3/P4/P6/§3.1 均有计划提交）
- **端到端验证**：P3 demo、P6 跨世界（经登记号）、P7 多源（本会话）
- **测试治理**：
  - `d63b968` 修复 demo_tools broken import（消除 ~102 个失败）
  - `c5e8282` 测试套件债务盘点（剩余 ~56 失败分类：端点迁移 404 / skill_infra / error_code stub 等）

---

## 六、本会话收尾成果（07-24 晚）

| 工作 | 结果 |
|------|------|
| P7 多源端到端验证 | 注册 bjybdb → 扫描 **356 表/5833 字段**落库 → 三段式路由查询返回真实数据（`国爱山`）。解除文档标注的"真实多源查询需 MSSQL 端到端验证"缺口 |
| GET /metrics bug 修复 | `72b62d8`：`object_code=None` 误返回空列表 → 前端 metric 列表页显示空。SemanticRegistry 补 `list_metrics` 代理，单测+API 验证（46 个） |
| P8 前置调研 | 发现文档严重滞后：§3.3 v2 schema / build_ingest_records / embedding / Milvus collection **均已就绪**，P8.1 实际已完成 |
| P8.2 迁移脚本 | `migrate_extractions_to_v2.py`：105 条 extractions → facts+rules_v2。dry-run 通过（facts:105/rules:105），单测 4 passed。**正式迁移被中断，待重跑** |

---

## 七、遗留与下一步

### 进行中（P8.2 迁移）
- 迁移脚本已写好 + 单测通过 + dry-run 验证，正式 `--drop --verify` 被 abort
- Milvus 当前：policy_facts 空(0)、policy_rules_v2 不存在（drop 后未重建）、policy_rules 57条（旧生产未动）
- **恢复**：重跑 `python -m ...migrate_extractions_to_v2 --drop --verify`（给足 timeout 让 bge encode 105 条）

### 待办
| 项 | 依赖 | 说明 |
|----|------|------|
| P5 LLM 字段级提取 + metric_code 标量索引 | MODEL_API_KEY | 反查受影响 doc |
| P8.4 重提取拉高填充率 | P8.2 完成 | 现状 3/15 |
| seed metric 升级三段式 | P8 | 现 46 个全两段式（三段式能力已验证，seed 待升级） |
| §8.1 发现 tab 回写流程 + 前端 | P9 | 候选→确认→回写语义层 |
| P9 前端 5 tab 重构 | — | 概览/政策/事实/结构化/发现 |
| P10 灰度切换与下旧 | P8/P9 | 政策问答切新 collection |

### 已知技术债
- `mapped_fields` 口径差异（扫描实时 239 vs 落库读回 23）
- 测试套件 ~56 失败（端点迁移 404 为主，大工程）
- `drop_policy_facts_collection` 缺 `connect_milvus`（v2 的 drop 有，facts 的没有——已在迁移脚本绕过）

---

## 关键数字

- **提交**：72 个（07-24 单日 52）
- **政策管线 phase 推进**：P0→P8（8 个 phase，M1-M4 达成）
- **新 collection**：policy_facts + policy_rules_v2（独立于生产 policy_rules）
- **多源验证**：bjybdb 356 表 / 5833 字段 / 真实数据查询
- **测试**：demo_tools 修复消除 ~102 失败，剩余 ~56 分类记录
