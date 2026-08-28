# 门诊医保 P0 数据契约验证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用一家医院门诊真实只读数据冻结 `mzjyxx` 的源表、字段、键、金额、状态、增量游标和容量契约，为 PostgreSQL 近实时底座提供可实施证据。

**Architecture:** 本阶段不写生产取数代码。通过现有语义发现通道和批准的 SQL Server 只读工具做聚合画像，把结论写入一份脱敏审查记录。任何结论都必须有查询口径、执行时间、统计结果和审核人；不能验证的项保留为阻断项，不以推测补齐。

**Tech Stack:** 现有 Semantic Discovery API、SQL Server 只读 SQL、PowerShell、Markdown、Git。

**Risk:** R4。涉及真实医保数据口径与后续结算金额计算。查询只允许 SELECT；证据文档不得保存姓名、身份证、卡号、处方号、原始结算号或原始交易号。

**Design:** `docs/superpowers/specs/2026-08-27-outpatient-medical-insurance-assistant-design.md`

**Output:** `docs/reviews/2026-08-27-outpatient-data-contract-review.md`

---

## Task 1：建立脱敏证据记录和当前数据源快照

**Files:**

- Create: `docs/reviews/2026-08-27-outpatient-data-contract-review.md`

- [ ] 在证据记录中建立固定章节：环境、源表、字段、键与关系、交易状态、金额勾稽、增量游标、容量与性能、政策 Skill 依赖、运营指标依赖、阻断项、审核结论。

- [ ] 记录数据源别名、数据库版本、执行时间、统计区间、执行账号权限范围和发现任务 ID；只写标识，不写连接串或凭据。

- [ ] 使用现有 `/semantic/discovery/scan` 和 `/semantic/discovery/results` 仅扫描 `dbo.o_Trade`、`dbo.o_FeeItem`，并在证据中记录扫描任务 ID、总行数、字段数、最新 DDL 修改时间和发现质量分。

- [ ] 在批准的只读 SQL 工具中运行元数据查询，确认候选表和字段的物理类型：

```sql
SELECT
    TABLE_SCHEMA,
    TABLE_NAME,
    COLUMN_NAME,
    DATA_TYPE,
    IS_NULLABLE,
    CHARACTER_MAXIMUM_LENGTH,
    NUMERIC_PRECISION,
    NUMERIC_SCALE,
    ORDINAL_POSITION
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'dbo'
  AND TABLE_NAME IN ('o_Trade', 'o_FeeItem')
ORDER BY TABLE_NAME, ORDINAL_POSITION;
```

- [ ] 证据中只记录字段定义和统计，不粘贴样例患者行。

- [ ] 提交证据骨架：

```powershell
git add docs/reviews/2026-08-27-outpatient-data-contract-review.md
git commit -m "docs: 建立门诊数据契约核验记录"
```

## Task 2：验证交易、明细键和一对多关系

**Files:**

- Modify: `docs/reviews/2026-08-27-outpatient-data-contract-review.md`

- [ ] 在完整统计区间与最近 30 天区间分别运行以下聚合检查；证据只记录计数：

```sql
SELECT
    COUNT_BIG(*) AS total_rows,
    SUM(CASE WHEN T_SetTid IS NULL THEN 1 ELSE 0 END) AS null_settlement_ids,
    COUNT_BIG(DISTINCT T_SetTid) AS distinct_settlement_ids,
    SUM(CASE WHEN T_TradeNo IS NULL THEN 1 ELSE 0 END) AS null_trade_nos,
    COUNT_BIG(DISTINCT T_TradeNo) AS distinct_trade_nos
FROM dbo.o_Trade;

SELECT COUNT_BIG(*) AS duplicate_settlement_keys
FROM (
    SELECT T_SetTid
    FROM dbo.o_Trade
    WHERE T_SetTid IS NOT NULL
    GROUP BY T_SetTid
    HAVING COUNT_BIG(*) > 1
) AS duplicated;

SELECT COUNT_BIG(*) AS duplicate_trade_keys
FROM (
    SELECT T_TradeNo
    FROM dbo.o_Trade
    WHERE T_TradeNo IS NOT NULL
    GROUP BY T_TradeNo
    HAVING COUNT_BIG(*) > 1
) AS duplicated;

SELECT COUNT_BIG(*) AS duplicate_fee_item_keys
FROM (
    SELECT T_TradeNo, ItemId, ItemNo
    FROM dbo.o_FeeItem
    WHERE T_TradeNo IS NOT NULL AND ItemId IS NOT NULL AND ItemNo IS NOT NULL
    GROUP BY T_TradeNo, ItemId, ItemNo
    HAVING COUNT_BIG(*) > 1
) AS duplicated;

SELECT COUNT_BIG(*) AS orphan_fee_items
FROM dbo.o_FeeItem AS fee
LEFT JOIN dbo.o_Trade AS trade ON trade.T_TradeNo = fee.T_TradeNo
WHERE trade.T_TradeNo IS NULL;
```

- [ ] 按 `T_State`、`T_HasRefundmented`、`T_PartialReturnFlag`、`NT_ReTradeFlag` 分组统计，确认重复键是否来自退费、冲正或历史版本，而不是直接判为脏数据。

- [ ] 冻结以下三项，或明确阻断：内部结算锚点、交易业务键、费用明细幂等键。

- [ ] `settlement_id` 只映射唯一 `T_TradeNo`；`T_SetTid` 作为普通可空字段单独画像，不因其一对多而否定内部交易锚点。用户按就诊时间定位到 `T_TradeNo` 的上下文解析仍须独立验证，未验证不继续 P1。

- [ ] 更新提交：

```powershell
git add docs/reviews/2026-08-27-outpatient-data-contract-review.md
git commit -m "docs: 核验门诊交易与明细关系"
```

## Task 3：验证金额口径并选择唯一费用明细源

**Files:**

- Modify: `docs/reviews/2026-08-27-outpatient-data-contract-review.md`
- Modify when evidence changes the decision: `docs/superpowers/specs/2026-08-27-outpatient-medical-insurance-assistant-design.md`

- [ ] 验证交易汇总恒等式，分别记录通过、差 0.01 元内、差 0.01 元以上和缺字段的笔数：

```sql
SELECT
    COUNT_BIG(*) AS total_rows,
    SUM(CASE WHEN T_FeeAll IS NULL OR T_FeeIn IS NULL OR T_FeeOut IS NULL THEN 1 ELSE 0 END) AS fee_scope_missing,
    SUM(CASE WHEN T_FeeAll IS NOT NULL AND T_FeeIn IS NOT NULL AND T_FeeOut IS NOT NULL
              AND ABS(T_FeeAll - T_FeeIn - T_FeeOut) <= 0.01 THEN 1 ELSE 0 END) AS fee_scope_pass,
    SUM(CASE WHEN T_FeeAll IS NOT NULL AND T_FeeIn IS NOT NULL AND T_FeeOut IS NOT NULL
              AND ABS(T_FeeAll - T_FeeIn - T_FeeOut) > 0.01 THEN 1 ELSE 0 END) AS fee_scope_fail,
    SUM(CASE WHEN T_FeeAll IS NULL OR T_FundPay IS NULL OR T_SelfPayAll IS NULL THEN 1 ELSE 0 END) AS fund_person_missing,
    SUM(CASE WHEN T_FeeAll IS NOT NULL AND T_FundPay IS NOT NULL AND T_SelfPayAll IS NOT NULL
              AND ABS(T_FeeAll - T_FundPay - T_SelfPayAll) <= 0.01 THEN 1 ELSE 0 END) AS fund_person_pass,
    SUM(CASE WHEN T_FeeAll IS NOT NULL AND T_FundPay IS NOT NULL AND T_SelfPayAll IS NOT NULL
              AND ABS(T_FeeAll - T_FundPay - T_SelfPayAll) > 0.01 THEN 1 ELSE 0 END) AS fund_person_fail
FROM dbo.o_Trade;
```

- [ ] 先按明细键去重，再按 `T_TradeNo` 汇总 `Fee/FeeIn/FeeOut`，与交易表同名口径比较。退费/冲正必须按 Task 2 已确认的有效状态规则分层统计，禁止把正负交易直接混算。

- [ ] 在受控控制台抽取至少 30 个脱敏锚点，由医保办人工核对结算票据；证据只记录案例编号、差额和结论，不记录原始标识符。

- [ ] 仅当 `o_FeeItem` 的关联完整率和金额勾稽达到审核门槛时选用它。否则验证 `yb_mzfymx_mz`，并把总设计中的候选来源改为唯一选定来源；不得同时累加两个费用事实源。

- [ ] 明确总额与各专项基金字段的“总项/分项”关系。没有业务证据时，专项基金只展示，不纳入推导总额。

- [ ] 更新提交：

```powershell
git add docs/reviews/2026-08-27-outpatient-data-contract-review.md docs/superpowers/specs/2026-08-27-outpatient-medical-insurance-assistant-design.md
git commit -m "docs: 冻结门诊金额与明细口径"
```

## Task 4：验证政策解释 Skill 的最小字段闭包

**Files:**

- Modify: `docs/reviews/2026-08-27-outpatient-data-contract-review.md`

- [ ] 以总设计 §10.1–§10.5 和 Issue 20 设计 §5.4 为唯一字段清单，逐字段记录：源表、物理字段、物理类型、业务含义、是否核心、空值率、枚举值域、脱敏级别、适用 Profile。

- [ ] 特别验证政策匹配所需上下文：地区、结算日期、险种、人员类别、医疗类别、机构级别、异地、慢特病、公务员/公疗、军残/退役、补充/救助资格。

- [ ] 对每个金额和待遇字段验证四态可区分：`non_zero`、`reported_zero`、`missing`、`not_applicable`。如果源数据只能区分 0 与 NULL，`not_applicable` 必须由资格事实和政策证据共同推导，不能由金额为 0 推断。

- [ ] 验证所有 `TB_*`、`TA_*` 字段的交易前/交易后含义和增量关系；`TA_MZTimes` 的物理类型与释义冲突未解决时不得发布。

- [ ] 将姓名、身份证号、卡号、出生日期、处方号标为禁止进入运行时公开语义模型；若内部定位确需使用，单列为受限上下文字段并注明脱敏/权限策略。

- [ ] 任一九 Profile 核心字段缺失时，在证据中把该 Profile 标为 `unavailable`，不以相近字段替代。

- [ ] 更新提交：

```powershell
git add docs/reviews/2026-08-27-outpatient-data-contract-review.md
git commit -m "docs: 核验门诊政策解释字段闭包"
```

## Task 5：冻结运营六指标、五维度与就诊时间口径

**Files:**

- Modify: `docs/reviews/2026-08-27-outpatient-data-contract-review.md`

- [ ] 对六个一期指标逐项记录分子、分母、去重键、有效状态、退费冲正规则、时间口径、单位、允许维度和下钻路径：门诊医保就诊人次、有效结算笔数、总费用、统筹基金支付、个人支付、次均费用。

- [ ] 证明五个维度的来源字段和稳定值域：就诊时间、科室、门诊业务类别、险种、结算状态。用户默认说“就诊时间”时使用就诊发生时间；结算运营问题显式使用结算时间。

- [ ] 对“人次”和“结算笔数”分别验证去重键，不允许用 `COUNT(*)` 代替。

- [ ] 验证科室字段能从交易或可信就诊关联取得。若只能通过额外 HIS 表关联，将该表和键记为 P1 必需输入，不在语义查询时临时跨源 JOIN。

- [ ] 从总体设计的典型问法扩充并冻结 50 个验收问题，覆盖六指标、五维度、同环比、固定下钻、空结果、歧义时间、无权限和超范围问题；每题写明唯一期望查询契约或期望澄清/拒绝。

- [ ] 更新提交：

```powershell
git add docs/reviews/2026-08-27-outpatient-data-contract-review.md
git commit -m "docs: 冻结门诊运营指标验收口径"
```

## Task 6：证明增量游标和容量边界

**Files:**

- Modify: `docs/reviews/2026-08-27-outpatient-data-contract-review.md`

- [ ] 从 Task 1 元数据和系统说明中找出交易、明细各自的可靠变更时间或单调版本字段；分别统计 NULL、重复、倒退、最近 24 小时迟到和跨 10 分钟重叠窗口的更新。

- [ ] 明确新增、更新、退费、冲正和删除的捕获方式。若源表没有可靠变更标记且删除不可见，将“分钟轮询”判为不成立，P1 改为院方 CDC/变更日志接入，不用全表轮询伪装近实时。

- [ ] 记录最近 30 天日均和峰值交易数、明细数、单次结算明细 P50/P95/P99、最近一日数据量和三年容量外推。

- [ ] 在只读账号下对候选增量条件执行实际计划和耗时测试，记录索引使用、返回行数、P50/P95；不允许为本验证直接修改源库索引。

- [ ] 冻结 P1 输入：每张源表的游标字段、稳定排序键、10 分钟重叠规则、页大小初值、退费/冲正语义、预期峰值。保留可调页大小和轮询间隔，其他口径不做运行时配置。

- [ ] 更新提交：

```powershell
git add docs/reviews/2026-08-27-outpatient-data-contract-review.md
git commit -m "docs: 冻结门诊增量与容量契约"
```

## Task 7：执行 P0 人工门禁并交付 P1 输入

**Files:**

- Modify: `docs/reviews/2026-08-27-outpatient-data-contract-review.md`
- Modify: `docs/superpowers/plans/2026-08-27-outpatient-medical-insurance-assistant-plan-index.md`

- [ ] 由医保办负责人确认指标、金额、状态和政策字段口径；由数据负责人确认键、关系、游标、容量和只读权限；记录姓名只写工号或组织身份标识。

- [ ] 任一项存在阻断时，将索引中的 P0 保持 `blocked`，列出证据缺口和责任方，不编写 P1 生产代码计划。

- [ ] 全部通过时，将索引中的 P0 标为 `complete`、P1 标为 `ready_for_planning`，并在证据中输出 P1 的冻结输入清单。

- [ ] 自审文档：没有患者原始标识、没有凭据、没有未标注推断、字段清单覆盖总设计 §10 与 Issue 20 §5.4、六指标五维度都有确定口径。

- [ ] 检查并提交：

```powershell
git diff --check
git status --short
git add docs/reviews/2026-08-27-outpatient-data-contract-review.md docs/superpowers/plans/2026-08-27-outpatient-medical-insurance-assistant-plan-index.md
git commit -m "docs: 完成门诊P0数据契约评审"
```

**P0 completion evidence:** 数据源扫描任务 ID、只读 SQL 执行时间与聚合结果、选定明细源、三类键、交易状态规则、金额勾稽结果、政策字段闭包、六指标五维度口径、可靠增量游标、容量基线、50 个验收问题、两类负责人确认。
