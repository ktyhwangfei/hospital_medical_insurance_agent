# Issue #35 语义指标治理字段设计

## 目标

补齐 `semantic_metrics` 的指标治理元数据，支持 Portal 录入与展示，并阻止治理字段不完整的指标发布或被查询引擎引用。

首批范围按已确认口径执行：发布 5 个可确定的门诊运营指标；`mzjyxx.insured_encounter_count` 保留为草稿并保持不可查询。

## 数据模型

在现有 `Metric` 模型和 `semantic_metrics` 表上增加 8 个字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `synonyms` | `list[str]` / JSONB | 同义词 |
| `compatible_dimensions` | `list[str]` / JSONB | 兼容维度编码 |
| `default_time_role` | `str | None` | 默认时间角色 |
| `refresh_frequency` | `str | None` | 刷新频率 |
| `permission_level` | `str | None` | 权限等级 |
| `owner` | `str | None` | 负责人 |
| `reviewer` | `str | None` | 审核人 |
| `precision` | `int | None` | 数值精度 |

现有 `name` 承载中文名称，`definition` 承载业务定义，`expression` 承载公式，`aggregation` 承载聚合方式，`unit` 承载单位，`source_*` 承载数据来源，`version` 承载已发布版本。因此发布时完整治理字段共 15 项：中文名称、同义词、业务定义、公式、聚合方式、单位、精度、兼容维度、默认时间角色、数据来源、刷新频率、权限等级、负责人、审核人和已发布版本。

PostgreSQL DDL 必须在 `CREATE TABLE` 与初始化迁移的 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 中双写。INSERT/UPSERT 列集合必须覆盖新增字段，并保留现有 schema-version 冲突保护。

## 发布与查询门禁

新增一个复用 Registry 的治理完整性校验：

- 草稿可以保存不完整字段；
- 发布对象时，所有待发布指标必须通过 15 项完整性校验；
- 缺字段时发布返回现有错误契约对应的 4xx，不生成新版本；
- 查询引擎只消费已发布快照中的指标，因此草稿和不完整指标不会进入查询路径；
- `insured_encounter_count` 明确保持草稿/不可查询，不能用交易笔数替代就诊人次。

## API 与 Portal

扩展现有语义指标详情、更新请求和响应 DTO，保持 `GET /semantic/metrics`、`GET /semantic/metrics/{metric_code}`、`PUT /semantic/metrics/{metric_code}` 路径不变。

Portal 复用 `/semantic-layer/metrics` 现有列表和编辑表单：

- 编辑区增加 8 个治理字段；
- 列表展示负责人、审核人、刷新频率、权限等级和治理完整状态；
- 保存继续走现有更新 API；
- 发布失败显示后端返回的字段缺失信息；
- 不新增页面、依赖或第二套状态管理。

## 首批种子指标

发布以下 5 个指标，并为每个填齐治理字段：

1. 门诊有效结算笔数
2. 门诊总费用
3. 门诊统筹基金支付金额
4. 门诊个人支付金额
5. 门诊次均费用

`mzjyxx.insured_encounter_count` 仅保留草稿，直到有可靠就诊人次口径和数据支撑。

## 测试与验证

按 R4 存储 Schema 改动执行：

1. Unit：模型默认值、治理完整性、DDL/INSERT 列覆盖、发布门禁和查询过滤；
2. API：治理字段更新、缺字段发布拒绝、完整指标发布成功；
3. Flow：种子指标发布后可查询，草稿指标不可查询；
4. Portal：Vitest、TypeScript、scoped ESLint、Next.js build。

验证顺序严格为 Unit → API → Flow，再执行 Portal 检查。新增列均提供默认值；停止消费新字段即可回滚到旧读路径。
