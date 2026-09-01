# 门诊医保近实时数据底座 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `bjyb` 的 `o_Trade / o_FeeItem / o_Diagnose` 通过 SQL Server CDC 同步到 PostgreSQL 原子发布批次，形成只读、可回放、P95 五分钟内可见的 `mz_trade / mz_fee_item` 查询数据集，并保持 Issue20 门诊政策解释字段闭包完整。

**Architecture:** 只建设一条链路：固定白名单 CDC 适配器读取快照与 LSN 区间，PostgreSQL 在一个事务内追加 CDC 事件、更新当前投影、重算交易链/诊断上下文、登记批次并推进检查点；查询侧只看到提交前或提交后的完整批次。复用现有 `PostgreSQLClient.transaction()`、`PolicyMetaStore` 数据源注册和 Issue20 Semantic Registry 查询模型契约，不新增通用 CDC 框架、不增加 API/前端、不让运行时再直查 SQL Server。

**Tech Stack:** Python 3.13、pyodbc、Pydantic、PostgreSQL JSONB/事务、SQL Server 2022 CDC、pytest；不新增依赖。

---

## 0. 已冻结边界

- 设计依据：`docs/reviews/2026-08-28-outpatient-p0-prefilled-design-decision.md` 的 D01–D12，全部已确认。
- 风险等级：涉及 `src/data_platform/storage/` 和结算数据，按 R4 执行；必须有人工先行设计、回滚说明、T1 → T2a → T2b 串行证据。[来源: `docs/governance/TEST-VERIFICATION-MATRIX.md` §3–§6]
- 唯一源表：`dbo.o_Trade`、`dbo.o_FeeItem`、`dbo.o_Diagnose`。
- 源键：`o_Trade(T_TradeNo)`；`o_FeeItem(T_TradeNo, ItemId, ItemNo)`；`o_Diagnose(T_TradeNo, DiagnoseNo, RecipeNo)`。诊断三字段主键已于 2026-08-28 只读核验，二字段 `(T_TradeNo, DiagnoseNo)` 存在重复，禁止误用。
- 源状态字典 `v_T_State_BJ` 已于 2026-08-28 只读核验：`1=临时入库`、`2=结算挂起`、`3=已结算`、`4=已对账`，对应负码 `-1/-2/-3/-4` 均为各阶段“交易已回退”。`NT_ReTradeFlag` 仅有空/`1` 物理值但无足够字典证明等同冲正，P1 不靠该字段单独生成 `reversed`。
- 运行时唯一数据源：PostgreSQL 视图 `mz_trade`、`mz_fee_item`。SQL Server 只用于 CDC 抽取和源端核验。
- 字段最小化：捕获 P0 119 行闭包中的 107 个获准物理字段，加 D08 所需诊断字段；明确排除 `P_IDNo / P_ICNo / P_Name / P_Birthday / P_CardNo / o_FeeItem.RecipeNo / HisName / HisCode` 等 S3 字段。身份定位留到 P4 的受控检索服务，P1 不落原始身份值。
- 一期不发布“就诊人次”，不把交易笔数改名为人次；P1 只提供事实、链状态、质量和上下文，五个运营指标在 P3 发布。
- Issue20 的查询模型代码当前仍是独立工作区未提交改动。Task 1 只移植查询模型契约，不移植其 SQL Server 直查 Planner、Policy QA 和前端改动。

## 1. 成功标准

1. 首次运行记录一个快照上界 LSN，完整发布三张源表；后续从 `sys.fn_cdc_increment_lsn(last_lsn)` 拉到同一个 `sys.fn_cdc_get_max_lsn()`。
2. 同一批次的事件、当前投影、诊断上下文、质量结果、批次记录和检查点在一个 PostgreSQL 事务中提交；失败时全部回滚。
3. 重跑同一 LSN 区间不产生重复事件或重复事实；源删除保留 tombstone，不物理删除审计事件。
4. 检查点早于 CDC 最小保留 LSN 时失败关闭为 `cdc_retention_gap`，不跳过缺口、不自动全量覆盖。
5. `mz_trade` 保留主表权威金额，`mz_fee_item` 只用于解释和质检；金额不平写 `quality_warning`，重复键、孤儿、LSN 缺口和未匹配负交易写 `quality_blocked`。
6. `mzjyxx` 查询模型继续满足 105 字段、3 个键、1 条受控关系、4 条质量规则和 Issue20 88 个指标依赖；数据集物理表改为 PostgreSQL 视图。
7. 每个数据批次记录 `semantic_object_code=mzjyxx`、当前语义版本、源 LSN、源提交时间和发布时间；查询结果后续可同时引用语义版本与数据批次。
8. 目标环境连续至少 100 个非空增量批次的 `published_at - source_committed_at` P95 ≤ 300 秒；无源变更的心跳批次不混入延迟分位数。
9. 系统自动生成 30 笔已填充的脱敏核验报告：先纳入全部金额/退款/上下文异常，再按交易日期、科室、门诊类别、险种、生命周期分层补足；对外摘要的 1–9 小桶统一显示 `<10` 并做互补抑制，不让用户填写空白表。

## 2. 明确不做

- 不开发第二套 Semantic Registry、自由 SQL、通用 ETL/CDC 编排框架或消息队列。
- 不在 P1 增加自然语言问数 API、统一 Chat 页面、患者定位、SSO、科室权限或导出。
- 不把每分钟数据批次发布成新的语义版本；批次引用当时活动语义版本即可。
- 不自动执行源库 CDC 开启脚本；脚本由目标环境 DBA 审核执行，代码默认只读。
- 不把 Issue20 未提交工作区整体复制或提交，只选择 P1 必需的查询模型契约。

---

### Task 1：落地 Issue20 查询模型契约的最小子集

**Status:** complete — `d0d70c4`

**Files:**
- Modify: `src/semantic_layer/models.py`
- Modify: `src/semantic_layer/registry.py`
- Modify: `src/semantic_layer/seed.py`
- Modify: `src/data_platform/storage/postgresql/semantic_registry_store.py`
- Add: `src/tests/unit/semantic_layer/test_outpatient_query_model_contract.py`

- [ ] 先从 Issue20 工作区提取并固化以下现有模型：`SemanticDataset`、`DatasetKey`、`SemanticField`、`DatasetRelation`、`DataQualityRule`，以及 `BusinessObjectVersion.datasets/keys/fields/relations/quality_rules`。只移植这些结构、Registry CRUD/校验和 PostgreSQL 存储；不带入 `query_planner.py`、Policy QA、Portal 或 Skill 运行代码。
- [ ] 先写失败测试，断言 `seed_semantic_layer()` 后 `mzjyxx`：
  - 两个 dataset code 为 `mz_trade`、`mz_fee_item`；
  - 交易键为 `T_TradeNo`；明细键为 `(T_TradeNo, ItemId, ItemNo)`；
  - 关系为唯一 `mz_trade 1:N mz_fee_item`；
  - 查询字段为 105 个，且 P0 的 88 个 Issue20 指标代码均存在；
  - 发布快照后 `queryable=true`、结构校验为空。
- [ ] 运行并确认先红：

```powershell
python -m pytest src/tests/unit/semantic_layer/test_outpatient_query_model_contract.py -v --tb=short
```

Expected: 缺查询模型类型或 `mzjyxx` 种子契约，测试失败。

- [ ] 按 Issue20 已验证实现移植最小代码。PostgreSQL DDL 对新增字段同时写 `CREATE TABLE` 定义和 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`，避免旧库 `CREATE TABLE IF NOT EXISTS` 不补列。
- [ ] 保留现有 `publish_object()` 的不可变版本语义；不得在本任务引入 PostgreSQL 查询编译器。
- [ ] 再运行同一测试，Expected: PASS。
- [ ] 回归现有语义层：

```powershell
python -m pytest src/tests/unit/semantic_layer src/tests/unit/data_platform/test_semantic_registry_transaction_lock.py src/tests/unit/data_platform/test_semantic_registry_stale_metric_write.py -v --tb=short
```

Expected: 全部通过。

- [ ] Commit:

```powershell
git add src/semantic_layer/models.py src/semantic_layer/registry.py src/semantic_layer/seed.py src/data_platform/storage/postgresql/semantic_registry_store.py src/tests/unit/semantic_layer/test_outpatient_query_model_contract.py
git commit -m "feat: 落地门诊语义查询模型契约"
```

### Task 2：提供受控、可审计的 SQL Server CDC 开通脚本

**Status:** complete — `1520e61`

**Files:**
- Add: `scripts/enable_outpatient_cdc.sql`
- Add: `src/tests/unit/adapters/test_outpatient_cdc_sql.py`

- [ ] 先写文本契约测试，断言脚本：
  - 仅操作数据库 CDC 元数据和三张白名单表；
  - capture instance 固定为 `dbo_o_Trade`、`dbo_o_FeeItem`、`dbo_o_Diagnose`；
  - `@supports_net_changes = 0`，保留每次操作；
  - `@captured_column_list` 不含八个 S3 排除字段；
  - cleanup retention 为 4320 分钟（3 天）；
  - 不含 `DROP`、业务表 `INSERT/UPDATE/DELETE`、`TRY_CONVERT`、`STRING_AGG`。
- [ ] 运行并确认先红：

```powershell
python -m pytest src/tests/unit/adapters/test_outpatient_cdc_sql.py -v --tb=short
```

Expected: 脚本不存在，测试失败。

- [ ] 编写幂等脚本，核心形态固定为：

```sql
IF (SELECT is_cdc_enabled FROM sys.databases WHERE name = DB_NAME()) = 0
    EXEC sys.sp_cdc_enable_db;

IF NOT EXISTS (
    SELECT 1 FROM cdc.change_tables WHERE capture_instance = N'dbo_o_Trade'
)
    EXEC sys.sp_cdc_enable_table
        @source_schema = N'dbo',
        @source_name = N'o_Trade',
        @capture_instance = N'dbo_o_Trade',
        @role_name = N'outpatient_cdc_reader',
        @supports_net_changes = 0,
        @captured_column_list = N'T_SetTid,T_TradeNo,T_TradeDate,T_State,T_HasRefundmented,T_PartialReturnFlag,T_OraginalTradeNo,T_OraginalTradeDate,NP_Settle_State,SETL_DATE,NT_ReTradeFlag,T_DiagType,T_FeeNo,P_FundType,PN_PersonType,T_CureType,P_JCLevel,P_HospFlag,PN_OutTransaction,PN_NationFundType,PN_ChronicFlag,PN_ChronicCode,PN_IsChronicHosp,P_Official,P_retirementflag,P_CivilFlag,P_CivilType,RETIRE_OFFICER_FLAG,T_GFBelongFlag,T_CompHospFlag,T_SpSetlFlag,T_pneno,NT_AllSelfPayFlag,PN_NoRightReason,T_FeeAll,T_FeeIn,T_FeeOut,T_FirstPay,T_SelfPay1,T_SelfPay2,T_SelfPayAll,T_BigPay,T_BigSelfPay,T_BeyondBig,T_FundPay,T_PersonCountPay,T_CashPay,PN_PersonCount,T_PersonCountAfter,T_BCPay,T_JCPay,T_OfficalPay,T_BigillPay,NT_BasicPay,NT_CivilPay,NT_OtherPay,NT_AgencySumPay,RETIRE_OFFICER_PAY,NT_OUT2_SCALE,NT_OUT2_PRICE,TB_FeeIn,TA_FeeIn,TB_BigPay,TA_BigPay,TB_FeeAfterBig,TA_FeeAfterBig,TB_MZTimes,TA_MZTimes,TB_BeyondFeeIn,TA_BeyondFeeIn,TB_BigillComm,TA_BigillComm,TB_BigillPay,TA_BigillPay,TB_CivilComm,TA_CivilComm,TB_CivilPay,TA_CivilPay,TB_FeeInL1,TA_FeeInL1,TB_BigPayL1,TA_BigPayL1,TB_FeeAfterBigL1,TA_FeeAfterBigL1,PN_InsuredAreaCode,T_HospCode,T_HospCodeA';
```

`o_FeeItem` 捕获列固定为 `T_TradeNo,ItemId,ItemNo,ItemCode,StandardCode,ItemName,ItemType,FeeType,F_LEVEL,Count,UnitPrice,Fee,FeeIn,FeeOut,SelfPay2,FEE_SP_SCALE,FEE_MEDIC_L,MEDIC_L,SPEDRUG_FLAG,State`；`o_Diagnose` 捕获列固定为 `T_TradeNo,DiagnoseNo,RecipeNo,RecipeDate,DiagnoseName,DiagnoseCode,SectionCode,Sectionname,HISSectionName,DiagnoseType`。

- [ ] 在脚本末尾只读输出 `sys.databases.is_cdc_enabled`、`cdc.change_tables`、capture instance、start_lsn 和 cleanup retention，作为 DBA 执行证据。
- [ ] 再运行同一测试，Expected: PASS。
- [ ] Commit:

```powershell
git add scripts/enable_outpatient_cdc.sql src/tests/unit/adapters/test_outpatient_cdc_sql.py
git commit -m "feat: 增加门诊源表CDC开通契约"
```

### Task 3：实现单院门诊 SQL Server CDC 读取适配器

**Status:** complete — `d90966f`

**Files:**
- Add: `src/adapters/insurance_interface/outpatient_cdc.py`
- Modify: `src/runtime/discovery/semantic_source.py`
- Add: `src/tests/unit/adapters/test_outpatient_cdc.py`
- Modify: `src/tests/unit/runtime/test_semantic_source.py`

- [ ] 先写 fake pyodbc connection 测试，覆盖：
  - 首次快照先取 `max_lsn`，再读取三张白名单表；
  - 增量起点使用 `sys.fn_cdc_increment_lsn(last_lsn)`；
  - 三个 capture instance 共用同一个 `to_lsn`；
  - 只读取 CDC `all` 的 after image：operation `1=delete`、`2=insert`、`4=update`，忽略 `3=update before`；
  - 每条变更保留 `start_lsn / seqval / operation / commit_time / source_key / payload`；
  - checkpoint 早于任一 capture instance 最小 LSN 时抛出稳定错误 `cdc_retention_gap`；
  - snapshot/CDC payload 均不出现 S3 排除字段。
- [ ] 运行并确认先红：

```powershell
python -m pytest src/tests/unit/adapters/test_outpatient_cdc.py src/tests/unit/runtime/test_semantic_source.py -v --tb=short
```

Expected: `outpatient_cdc` 模块和公开连接方法不存在。

- [ ] 在 `SemanticDataSource` 增加唯一公开复用缝 `connect_datasource(datasource_id)`，内部仍走现有 `_resolve_datasource_connection()` 和 `_connect()`；不复制驱动降级、数据源注册或环境回退代码。
- [ ] 在一个文件内实现具体类 `SqlServerOutpatientCdcSource` 和必要的 frozen dataclass/Pydantic 模型；构造器接收 connection factory，避免新增只有一个实现的 Protocol/Factory。
- [ ] 固定三组列白名单。交易/明细白名单以 P0 Task 4 的 A–F 物理字段为准；运行时启动先查 `INFORMATION_SCHEMA.COLUMNS`，任一必需列缺失立即 `source_contract_mismatch`，不静默丢列。
- [ ] CDC 查询必须参数化 LSN；表名、capture instance 和列名只能来自代码常量，不接受请求参数或自然语言输入。
- [ ] 快照算法固定：
  1. 读取三实例 min LSN 和统一 max LSN；
  2. 以该 max LSN 作为 snapshot checkpoint；
  3. 读取三张当前表；
  4. 发布快照；
  5. 下一次从该 LSN 的 increment 开始。快照期间提交的变更会在下一批重放，由目标端幂等 UPSERT 消除重复。
- [ ] 再运行同一测试，Expected: PASS。
- [ ] Commit:

```powershell
git add src/adapters/insurance_interface/outpatient_cdc.py src/runtime/discovery/semantic_source.py src/tests/unit/adapters/test_outpatient_cdc.py src/tests/unit/runtime/test_semantic_source.py
git commit -m "feat: 实现门诊SQL Server CDC读取"
```

### Task 4：建立 PostgreSQL 追加事件与原子当前投影

**Status:** complete — `6f9d6b7`

**Files:**
- Add: `src/data_platform/storage/postgresql/outpatient_store.py`
- Add: `scripts/bootstrap_outpatient_store.py`
- Add: `src/tests/unit/data_platform/test_outpatient_store.py`

- [ ] 先写存储测试，使用 fake `PostgreSQLClient` 记录事务和 SQL，断言：
  - schema 初始化幂等；所有表使用 `CREATE TABLE IF NOT EXISTS`；后续可变列有 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`；
  - `publish_batch()` 只开启一次 `PostgreSQLClient.transaction()`；
  - 事件去重键为 `(source_id, capture_instance, start_lsn, seqval, operation)`；
  - 投影 UPSERT 只有新 `(source_lsn, source_seqval)` 不小于现有值时才覆盖；
  - delete 写 `is_deleted=true` tombstone，不删除事件或投影；
  - batch/checkpoint 仅在同一事务末尾写入；中途异常触发 rollback；
  - 同一 `(source_id, from_lsn, to_lsn, mode)` 重放返回原批次，不产生第二个发布批次。
- [ ] 运行并确认先红：

```powershell
python -m pytest src/tests/unit/data_platform/test_outpatient_store.py -v --tb=short
```

Expected: store 不存在。

- [ ] 建立六张表：
  - `outpatient_sync_checkpoints`：每 source 一个 `last_lsn/last_batch_id/updated_at`；
  - `outpatient_sync_batches`：mode、LSN 区间、源提交时间、发布时间、行数、质量摘要、语义版本；
  - `outpatient_cdc_events`：追加事件，payload 仅含白名单字段；
  - `outpatient_trade_current`：交易键、核心金额/维度/链状态、诊断科室快照、完整白名单 payload、tombstone 和源水位；
  - `outpatient_fee_item_current`：三字段键、核心明细金额/分类、payload、tombstone 和源水位；
  - `outpatient_diagnosis_current`：三字段源主键、D08 字段、payload、tombstone 和源水位。
- [ ] 建立两个只读视图 `mz_trade`、`mz_fee_item`。视图列名与 Issue20 `SemanticField.column_name` 一致；P1 五个运营核心金额/时间/维度使用物理 typed column，其余政策解释字段从白名单 JSONB 做固定类型转换。所有字段映射以代码常量展开，不在运行时按用户输入生成 SQL。
- [ ] 在 `mz_trade` 暴露 `data_batch_id / source_lsn / semantic_version / quality_status / context_quality / settlement_chain_id / settlement_lifecycle`，但不暴露原始身份、内部 CDC payload 或 S3 字段。
- [ ] `bootstrap_outpatient_store.py` 只调用 store 的同一 schema 初始化入口，不复制 DDL；支持 `python scripts/bootstrap_outpatient_store.py --check` 验证表/视图存在而不改源库。
- [ ] 再运行同一测试，Expected: PASS。
- [ ] Commit:

```powershell
git add src/data_platform/storage/postgresql/outpatient_store.py scripts/bootstrap_outpatient_store.py src/tests/unit/data_platform/test_outpatient_store.py
git commit -m "feat: 建立门诊事实原子发布存储"
```

### Task 5：实现批次编排、退款链、诊断快照和质量规则

**Status:** complete — `62eefdb`

**Files:**
- Add: `src/data_platform/outpatient_sync.py`
- Add: `src/tests/unit/data_platform/test_outpatient_sync.py`

- [ ] 先写纯逻辑和服务测试，覆盖：
  - 无 checkpoint 走 snapshot，有 checkpoint 走 incremental；
  - 源返回空变更仍推进观察水位并写心跳批次，但 `source_committed_at=NULL`；
  - store 失败时 checkpoint 不推进；下一次可重放同一 LSN；
  - `Decimal` 保留精度，不经过 float；
  - 主表金额始终进入公开投影，明细不平只加 warning、不覆盖主表；
  - 孤儿、重复键、CDC retention gap、未匹配负交易进入 blocked；
  - D08 诊断选择和稳定 tie-break；
  - 退款链状态和净额。
- [ ] 运行并确认先红：

```powershell
python -m pytest src/tests/unit/data_platform/test_outpatient_sync.py -v --tb=short
```

Expected: sync service 不存在。

- [ ] 实现 `OutpatientSyncService.run_once()`：只负责 source → normalize → quality/context → store.publish_batch，不增加调度器、队列或插件系统。
- [ ] 交易链规则固定为：
  - `settlement_chain_id = nullif(T_OraginalTradeNo, '') or T_TradeNo`；
  - 存在负交易但原交易不在当前投影：`unmatched_negative` + blocked；
  - 已匹配负交易且 `T_PartialReturnFlag='1'` 或链净 `T_FeeAll > 0`：`partially_refunded`；
  - 已匹配负交易且链净 `T_FeeAll == 0`：`refunded`；
  - 无已匹配退费链、但 `T_State IN (-4,-3,-2,-1)`：`reversed`；
  - `NP_Settle_State='0'`，或链内没有 `T_State IN (3,4)` 的成功事件：`source_failed`；
  - 其余：`active`。链净额小于 0 按 `unmatched_negative` 阻断；`NT_ReTradeFlag` 仅原样保留，直到值域明确，不单独决定生命周期。
- [ ] D08 诊断规则固定为：优先 `DiagnoseType` 已映射的主诊断；否则 `ABS(RecipeDate - T_TradeDate)` 最小；再按 `DiagnoseNo`、`RecipeNo` 升序。输出同一行的 `SectionCode/Sectionname/HISSectionName`，质量为 `source_primary / deterministic_fallback / missing`。
- [ ] 质量规则固定为：
  - blocking：键 NULL/重复、外键孤儿、LSN gap、未匹配/过度负交易；
  - warning：`T_FeeAll != T_FeeIn + T_FeeOut`、`T_FeeAll != T_FundPay + T_SelfPayAll`、明细 `SUM(Fee/FeeIn/FeeOut)` 与主表超出 0.01 元、诊断 fallback/missing；
  - pass：已验证键/关联和金额规则通过。
  已知金额差异必须逐交易记录 rule code 和差额，不把容差放大到 1 元。
- [ ] 每个 batch 在调用 store 前读取当前 `mzjyxx.current_version`；若模型不存在或不是 published/queryable，批次仍可落 current/event，但 `semantic_version=NULL` 且 batch 为 `quality_blocked`，禁止宣称可查询。
- [ ] 再运行同一测试，Expected: PASS。
- [ ] Commit:

```powershell
git add src/data_platform/outpatient_sync.py src/tests/unit/data_platform/test_outpatient_sync.py
git commit -m "feat: 实现门诊批次质量与上下文加工"
```

### Task 6：提供 30–60 秒运行入口和新鲜度状态

**Status:** complete — `891961b`

**Files:**
- Add: `scripts/run_outpatient_cdc_sync.py`
- Add: `src/tests/unit/data_platform/test_outpatient_sync_cli.py`

- [ ] 先写 CLI 测试，断言：
  - `--once` 只执行一批；
  - 默认 interval 为 45 秒；循环模式只接受 30–60 秒；
  - SIGINT/SIGTERM 在当前批次结束后退出，不中断 PostgreSQL 提交；
  - 同一进程内批次异常记录稳定错误并按下一个周期恢复，不清空 checkpoint；
  - `--status` 输出最近批次、checkpoint、最近非空批次延迟和最近 100 个非空批次 P95，不输出连接串、源键或 payload。
- [ ] 运行并确认先红：

```powershell
python -m pytest src/tests/unit/data_platform/test_outpatient_sync_cli.py -v --tb=short
```

Expected: CLI 不存在。

- [ ] 用 stdlib `argparse/time/signal` 实现入口，生产 composition 固定为：

```python
semantic_source = SemanticDataSource()
source = SqlServerOutpatientCdcSource(
    lambda: semantic_source.connect_datasource(args.source_id)
)
store = OutpatientStore()
service = OutpatientSyncService(source, store, get_semantic_registry())
```

- [ ] 不在 FastAPI 启动事件内开启死循环，不新增 APScheduler/Celery；部署层将该脚本作为独立只读 worker 进程管理。
- [ ] 再运行同一测试，Expected: PASS。
- [ ] Commit:

```powershell
git add scripts/run_outpatient_cdc_sync.py src/tests/unit/data_platform/test_outpatient_sync_cli.py
git commit -m "feat: 增加门诊CDC同步运行入口"
```

### Task 7：把 `mzjyxx` 当前查询模型切到 PostgreSQL 发布视图

**Status:** complete — `386ac69`

**Files:**
- Modify: `src/semantic_layer/seed.py`
- Modify: `src/tests/unit/semantic_layer/test_outpatient_query_model_contract.py`
- Add: `scripts/publish_outpatient_postgres_query_model.py`
- Add: `src/tests/unit/semantic_layer/test_publish_outpatient_postgres_model.py`

- [ ] 先扩展测试，断言：
  - dataset code 不变，仍为 `mz_trade/mz_fee_item`；
  - `datasource_id=outpatient_postgres`；物理表名为同名 PostgreSQL 视图；
  - 105 字段、3 键、关系和 4 条质量规则不减少；
  - 88 个 Issue20 依赖仍闭包；
  - 不存在 `dbo.o_Trade/o_FeeItem` 或 SQL Server datasource；
  - 发布新版本后上一版本仍可读取。
- [ ] 运行并确认先红：

```powershell
python -m pytest src/tests/unit/semantic_layer/test_outpatient_query_model_contract.py src/tests/unit/semantic_layer/test_publish_outpatient_postgres_model.py -v --tb=short
```

Expected: 当前模型仍指向 SQL Server 或发布脚本不存在。

- [ ] 修改门诊 seed，仅改变物理 datasource/table binding，并补 `data_batch_id/source_lsn/semantic_version/quality_status/context_quality/settlement_chain_id/settlement_lifecycle` 等 P1 字段；不改 Issue20 已审核指标定义。
- [ ] 发布脚本先执行四个门禁：目标 store `--check` 通过、至少一个 published batch、视图列覆盖 Registry 字段、当前模型 validate 无问题；任一失败不发布。
- [ ] 脚本发布一个新的不可变 `mzjyxx` 版本，并把 changelog 固定为 `P1 PostgreSQL near-real-time source switch`；不删除 v3、不覆盖旧快照。
- [ ] 再运行同一测试，Expected: PASS。
- [ ] Commit:

```powershell
git add src/semantic_layer/seed.py src/tests/unit/semantic_layer/test_outpatient_query_model_contract.py scripts/publish_outpatient_postgres_query_model.py src/tests/unit/semantic_layer/test_publish_outpatient_postgres_model.py
git commit -m "feat: 切换门诊语义模型到PostgreSQL批次"
```

### Task 8：完成 Flow、回滚和生产验收证据

**Status:** implementation complete — 本地 T1/T2a/T2b/模块回归全绿；目标环境 `bjybdb` 注册、CDC 快照与 100 个非空批次 P95 证据待外部实施

**Files:**
- Add: `src/tests/integration/flow/test_outpatient_sync_flow.py`
- Add: `scripts/generate_outpatient_reconciliation.py`
- Add: `src/tests/unit/data_platform/test_outpatient_reconciliation.py`
- Add: `docs/reviews/2026-08-28-outpatient-p1-verification.md`
- Modify: `docs/superpowers/plans/2026-08-27-outpatient-medical-insurance-assistant-plan-index.md`
- Modify: `PROGRESS.md`

- [ ] 先写核验报告测试：全部异常交易优先纳入，再按五个维度的组合覆盖不足补齐；相同 batch 输入顺序变化仍得到相同 30 个 case；报告仅含 `case-01` 形式编号、批次/规则/差额/质量，不含交易号、患者身份或 payload；对外小桶 `<10` 且互补桶同步抑制。
- [ ] 用一个脚本实现自动报告。排序固定为 `SHA256(batch_id + ':' + T_TradeNo)`，只用于稳定抽样；内部回放按同一 batch 重新生成同序选择，不需要另存身份映射或密钥。源批次不足 30 笔时输出实际样本数并标记 `sample_insufficient`，不复制行凑数。
- [ ] 写内存 source + 事务 fake store 的完整 Flow：snapshot → insert/update/delete → 同 LSN 重放 → 诊断选择变化 → 退款链 → 自动核验报告 → 查询批次元数据。断言每个观察点只能看到上一完整批次或下一完整批次。
- [ ] 严格按顺序执行 T1：

```powershell
python -m pytest src/tests/unit/adapters/test_outpatient_cdc_sql.py src/tests/unit/adapters/test_outpatient_cdc.py src/tests/unit/data_platform/test_outpatient_store.py src/tests/unit/data_platform/test_outpatient_sync.py src/tests/unit/data_platform/test_outpatient_sync_cli.py src/tests/unit/data_platform/test_outpatient_reconciliation.py src/tests/unit/semantic_layer/test_outpatient_query_model_contract.py src/tests/unit/semantic_layer/test_publish_outpatient_postgres_model.py -v --tb=short
```

Expected: PASS。失败即停止，不进入 API/Flow。

- [ ] T1 通过后执行 T2a 兼容性回归（本阶段不新增 API）：

```powershell
python -m pytest src/tests/integration/api/test_openapi_contract.py -v --tb=short
```

Expected: PASS，OpenAPI 无新增/破坏性变化。

- [ ] T2a 通过后执行 T2b：

```powershell
python -m pytest src/tests/integration/flow/test_outpatient_sync_flow.py -v --tb=short
```

Expected: PASS。

- [ ] 再跑模块回归和静态编译：

```powershell
python -m pytest src/tests/unit/data_platform src/tests/unit/adapters src/tests/unit/semantic_layer -v --tb=short
python -m compileall -q src scripts
```

Expected: 全部通过，零新增错误。

- [ ] DBA 在目标环境审核执行 `scripts/enable_outpatient_cdc.sql` 后，按以下顺序验收：

```powershell
python scripts/bootstrap_outpatient_store.py --check
python scripts/run_outpatient_cdc_sync.py --source-id bjybdb --once
python scripts/run_outpatient_cdc_sync.py --source-id bjybdb --status
python scripts/publish_outpatient_postgres_query_model.py
```

Expected: 快照发布、状态不含 retention gap、`mzjyxx.queryable=true`、数据源为 PostgreSQL。

- [ ] 连续运行至少 100 个非空增量批次后，由 `--status` 固化 P95 ≤ 300 秒证据；若没有 100 个非空批次，只记录“样本不足”，不得用心跳批次凑数。
- [ ] 验证源→目标行数、三张表键、费用外键、主表金额与明细勾稽；生成脱敏差异摘要，不输出 `T_TradeNo`、payload 或身份字段。
- [ ] 在验证文档记录：commit、环境、CDC capture instance、LSN 范围、批次 ID、语义版本、测试命令/结果、延迟样本数/P95、已知 warning、外部开通人和回滚方式。
- [ ] 回滚固定为：先停止独立 sync worker；把 `mzjyxx` 活动版本切回 v3；保留 PostgreSQL 事件/批次用于审计，不删表；源 CDC 仅由 DBA 在确认无消费者后禁用。代码使用逐提交 `git revert`，不改写历史。
- [ ] 把计划索引的 P1 状态改为 `complete`，P2 改为 `ready_for_planning`；只有目标环境延迟证据通过后才能完成该状态变更。
- [ ] Commit:

```powershell
git add src/tests/integration/flow/test_outpatient_sync_flow.py scripts/generate_outpatient_reconciliation.py src/tests/unit/data_platform/test_outpatient_reconciliation.py docs/reviews/2026-08-28-outpatient-p1-verification.md docs/superpowers/plans/2026-08-27-outpatient-medical-insurance-assistant-plan-index.md PROGRESS.md
git commit -m "test: 验证门诊近实时数据底座"
```

---

## 3. 外部实施清单（不再向用户索要数据库已有内容）

只需要目标环境提供动作权限，不需要再填字段表：

1. DBA 审核并执行固定 CDC 脚本，确认 SQL Server Agent 运行、三天 retention 和 `outpatient_cdc_reader` 最小权限。
2. 部署系统为独立 worker 注入现有 `bjybdb` 数据源连接与 PostgreSQL `DATABASE_URL`；worker 不持有源库业务写权限。
3. 医院在 UAT 抽检自动生成的差异摘要和票据；不会收到 30 行空白表。
4. 扫码/SSO、身份映射、患者检索和下钻权限继续作为 P4/P5 上线门禁，不阻塞 P1 非身份事实同步。

## 4. Ponytail 约束

- 当前方案只增加一个具体 CDC adapter、一个 store、一个 sync service 和三个运维脚本；没有通用 pipeline、port/factory、队列或 scheduler。
- JSONB 只保存已批准字段并承担审计/字段闭包；五个运营核心字段使用 typed columns，避免 P3 聚合时重复解析 JSON。
- 先用 PostgreSQL 单事务保证原子可见性；只有实测吞吐超过单 worker 能力时，才考虑分区或消息队列。
- P1 不补患者身份定位。等扫码/SSO 能给出稳定的可信标识后，在 P4 增加受控 locator；现在提前选 HMAC 字段或密钥会固化未知身份协议。
