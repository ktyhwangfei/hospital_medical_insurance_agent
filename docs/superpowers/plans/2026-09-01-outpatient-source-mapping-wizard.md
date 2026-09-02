# 门诊数据源映射向导（探查/选表/字段映射/SQL 预览）

日期：2026-09-01 · 状态：已完成（2026-09-02 验证） · 关联：门诊数据治理中心 P1 扩展

## 问题

数据治理中心当前写死固定契约：表名（o_Trade/o_FeeItem/o_Diagnose）、117 字段、主键、时间字段（T_TradeDate）、交易号字段（T_TradeNo）、schema（dbo）全部硬编码在 `OUTPATIENT_SOURCE_SPECS` 与 `SqlServerOutpatientPollingSource`。真实医院 HIS 表名/列名不同，无法接入。

## 设计决策

**契约冻结 + 别名映射**：117 契约字段是平台语义模型，保持冻结；映射方向为「源列 → 契约字段」，在 SELECT 中以 `[源列] AS [契约字段]` 完成。下游（outpatient_sync 语义层、P2 预退费、质量门）读契约字段名，零改动。

- 无映射行 = 默认映射（当前写死值），存量 bjybdb 零迁移。
- WHERE/ORDER BY/IN 关联使用映射反查的源列名（SQL Server WHERE 不能引用 SELECT 别名）。
- CDC 路径本期仍走固定规格（测试环境未开 CDC，`ponytail:` CDC 映射待真实 CDC 环境再加）。
- 探查不回显样本值（HIS 含患者隐私），只给列元数据 + 主键 + 行数。

## 配置模型（契约字段名为准）

每源一份 `OutpatientSourceMapping`：每个 capture 一条 `CaptureMapping{table_schema, table_name, key_columns(契约名), trade_no_field(默认 T_TradeNo), time_field(仅 trade, 默认 T_TradeDate), column_map{契约字段→源列}}`。

## 范围

1. 域模型 + 默认映射（src/data_platform/outpatient_governance.py）
2. PG 存储 outpatient_source_mappings（CREATE+ALTER 双写）
3. 轮询适配器接受映射；SQL 构造器与预览共用（预览=实际执行的 SQL）
4. 服务层：explore_tables / explore_table / get/save_mapping / sql_preview
5. API：GET explore、GET/PUT mapping、GET mapping/sql-preview
6. worker 装配映射
7. Portal：数据源页「表探查」「字段映射」弹窗（含自动同名匹配、SQL 预览）
8. 测试：单元（SQL 构造/校验/存储）→ API → 既有 Flow 回归（默认映射≡现状）

## 验收

- 映射保存后 SQL 预览与定时 SQL 实际执行串一致
- 自定义表名/列名经别名映射后同步产物与默认映射语义等价（单元级验证 SQL 串）
- 存量 bjybdb 无映射行行为不变（全量回归）
