# 门诊费用分解：核心设计文档修订前的深度代码审查

日期：2026-10-14
基线：`294eded`（#78/#79 已提交）+ 工作区未提交 #80/#81/#82-二次保障改动
目的：为《门诊费用分解-待遇识别设计-V1.0.md》修订做实现现状摸底；在既有两份审查（`2026-10-13-four-fee-chains-code-review.md` / `2026-10-14-special-db-maf-acceptance.md`）之上做**独立复核**，只记本轮新发现与可用证据，不重复历史结论。

## 0. 方法与边界

- 走读范围：`src/runtime/policy_qa/fee_decomposition/`（26 模块）、`src/adapters/data_supply/outpatient_*_queries.py`、`src/domain/insurance/fee_decomposition.py`、`src/runtime/api/policy_qa_routes.py` 接入段。
- 定向静态扫描：物理键大小写（S3 类）、`None → 0`（S1 类）、两条大病算法、profile 注释与行为一致性。
- 实库只读核对：`bjybdb.yb_zdfl` 字典类别全量、`o_Trade.P_FundType` 分布（回答险种字典问题）。
- 非穷举：未逐行覆盖 12.4k 行；未跑 Flow/浏览器 E2E；未重放实库 157 笔（既有报告已完成）。

## 1. 设计 ↔ 代码落点地图

| 链路 | 内核 | 快照/适配 | 参数表 | 结果版本 |
|---|---|---|---|---|
| 职工普通门诊 | `employee_outpatient.py` | `snapshot_service.py` + `outpatient_decomposition_queries.py` | `params_employee_outpatient.py` | `employee_outpatient_v1` |
| 职工门特 mz | `employee_outpatient_special.py`（1567 行） | `snapshot_service_special_mz.py` + `outpatient_special_mz_queries.py` | `params_employee_outpatient_special.py` | `employee_outpatient_special_v1` |
| 居民普通门诊 | `resident_outpatient.py` | `snapshot_service.py`（共用） | `params_resident_outpatient.py` | `resident_outpatient_v1` |
| 居民门特 mz | `resident_outpatient_special.py` | `snapshot_service_special_mz_resident.py` + 同 mz 适配 | `params_resident_outpatient_special.py` | `resident_outpatient_special_v1` |
| 二次大病/救助（两门特共用） | `secondary_coverage.py` | `SecondaryCoverageContext`（domain） | `params_secondary_coverage.py` (19 行) | 随宿主链路 |
| 目录逐项分解（共用） | `catalog_split.py`（900 行） | 门特由 `special_catalog_service.py` / `resident_special_catalog.py` 适配 | 目录表经 `record_query_mappings` | — |
| 接入/门控/profile | `integration.py` | — | — | — |

共享面：`reconciliation.py`、`result.py`、`public_view.py`、`domain/insurance/fee_decomposition.py`。**四链路的起付/分段/补充链是各自内联实现，非共享纯函数**（设计 §6.1 早期备注已指出，现在漂移面 ×4）。

## 2. 本轮新发现

### F1 · 中 · `integration.py` 门特 profile 注释与行为矛盾（文档/代码不一致）

- 位置：`integration.py:47-56` 表注释与 `_resolve_special_profile_from_context` docstring 写“职工门特 ESP-CODE-001/002 待码表确认**签核前不注册**（恒走 UNSUPPORTED_PROFILE）”。
- 实际：`_SPECIAL_PROFILE_MAP` 已注册 `("城镇职工基本医疗保险", "门诊特殊病") → ("employee", "outpatient_special")`；且 `_resolve_special_suite` 对 `suite=="mz" and fund=="3"` 直接判为职工门特并分发（`integration.py:167-171`）。
- 影响：生产行为已由“唯一源登记码”确认 profile（与 `2026-10-14-special-db-maf-acceptance.md` 一致），但代码注释会误导设计文档/后续维护者认为门特不可用。
- 最小修复：删除/改写两处陈旧注释，明确“职工门特 profile 由唯一登记源码（`FUND_TYPE=3`×`yllb=12`）确认；ESP-CODE-001/002 保留为参数表确认状态”。

### F2 · 中 · 门特账面观测金额缺失被折成 0（S1 同类，落在“核对目标”而非“计算输入”）

- 位置：`outpatient_special_mz_queries.py:586-588` `_total(special, normal)` 返回 `(special or 0) + (normal or 0)`，仅当两者皆 `None` 才返回 `None`。
- 复现形态：`tsbybn=NULL` 且 `ptybn=0`（该组合能通过上方非特殊病费用前置校验，因为 `ptybn==0` 合法）→ `observed.ybn` 得 `0`，而非 `None`。
- 影响：逐字段核对把“账面缺失”当“账面为 0”，产生伪 `mismatched` 或掩盖缺值；不进入计算输入（无反向污染），故为中危。
- 最小修复：`_total` 对“一侧缺失”保持未知（`None`），只在两侧都有值时求和；补一条稀疏行（`tsbybn` 空、`ptybn=0`）回归。

### F3 · 中 · 职工门特 assumed 分支把缺失起付累计当 0

- 位置：`employee_outpatient_special.py:273` `prior = ctx.prior_cycle_deductible_paid or Decimal("0")`。
- 影响：`evidence_status=="assumed"`（评估口径）时若 `prior_cycle_deductible_paid` 为 `None`，会静默按 0 参与 `F=min(E,max(D−A,0))`。同一模块 confirmed 分支已要求该字段非空（否则 `CONFIRMED_CONTEXT_INCOMPLETE`），assumed 分支却放宽为 0，属口径不一致。
- 边界：assumed 为评估专用、结果只到勾稽级；但“缺值→0”与设计三值纪律相悖。
- 最小修复：assumed 分支同样要求 `prior_cycle_deductible_paid` 非空，否则 blocked；或显式记录 `ASSUMED_PRIOR_ZERO` 不确定性。

### F4 · 低-信息 · 两条“大病”算法并存，语义不同

- `resident_outpatient._bigill_channel_pay`（居民普通门诊“医保内累计已达封顶→大病通道”候选口径）：合规基数 `E+比例自付二`×**75% 固定**，无起付、无分段。
- `secondary_coverage.decompose_secondary_coverage`（两门特二次保障）：起付 30404、前 5 万 60%/其后 70%、救助身份加 5 个百分点、叠加医疗救助封顶。
- 二者同用“大病/二次保障”措辞但规则完全不同。设计文档修订时需明确：**体系 A（居民门诊大病通道）** 与 **体系 B（门特二次大病+医疗救助）** 是两套独立规则，各自候选/签核状态分开。

### F5 · 低-信息 · `catalog_split` 结算事实限价分支优先于集采分支

- 位置：`catalog_split.py:454-505`（`sp_scale>0 且单价>sp_scale` “结算事实限价统一优先”）先于 `a_ypbs` 集采分支（`:507+`）。
- 即：集采药若同时带 `SP_SCALE` 限价事实，走 D17/Issue#80 公式而非 D19 集采超限公式。注释已声明为刻意选择，但两个候选公式的优先级**未见签核记录**；建议在设计文档 §16 候选口径清单中显式列出该优先级。

### F6 · 低-信息 · D16 本院累计推导对历史行 NULL 金额取 0

- 位置：`outpatient_decomposition_queries.py:409-410` `fee_in = ... or 0`。
- 语义：D16 结果为**下界**，缺历史 `T_FeeIn` 记 0 属保守下界，可接受；但模块内 `_to_decimal` 注释写“未知不是零”，两处口径不一致，容易被后续误用为精确值。建议在该循环补一行注释说明“下界推导将缺失当 0”。

## 3. 既有整改项抽查（确认已落地）

| 项 | 代码证据 |
|---|---|
| S1/R1 稀疏累计不确认 | `snapshot_service_special_mz.py` / `outpatient_special_mz_queries.py` 周期/年度列缺失返回 unknown；回归 `test_review_regressions.py::test_missing_cycle_value_cannot_be_confirmed_zero` |
| S2 年度滞后不 confirmed | `CYCLE_TABLE_LAGGING` 不确定性传播；`test_lagging_annual_value_is_not_confirmed` |
| S3/R8 物理键小写 | `resident_special_catalog.py` 取 `fee_medic_l`/`fee_sp_scale`；`test_mz_actual_lowercase_limit_ratio_survive_adaptation` |
| S5 摘要越权 | `public_view.render_summary` 尊重 `may_claim_full_explanation`；`polish_summary` 恒 template；两条回归 |
| R2 全自费不进居民基金 | `resident_outpatient._bigill_channel_pay` `eligible=E+比例自付二`、`excluded=out−比例自付二`；`test_fully_excluded_item_stays_personal...` |
| R3 退费用原单政策 | `resident_outpatient.py:145-176` 原单上下文校验 + 年度累计；三条回归 |
| R5 目录特殊病适用标志 | `resident_special_catalog.split_special_mz_catalog` 无唯一有效标志 → 全部金额未知；`test_special_catalog_requires_independent_special_marker` |
| R7 双向消歧 | `integration._resolve_special_suite` 任一 ambiguous/failed 即停 |

## 4. 设计文档修订建议（对应本次要改的文档）

1. **术语层**：把“门诊费用分解”拆为**对账层**（字段级独立重算/核对）与**待遇识别层**（§18 `PatientBenefitProfile`，尚未实现）。当前代码只有对账层，画像层是纯设计。
2. **链路矩阵**：补四链路 × （起付/分段/补充/二次保障/退费）支持度表，标注候选口径开关与签核状态（F4/F5）。
3. **复用偏差**：§6.1 的“门特零复用”备注已过期——现在是四链路各自内联，应在文档中给出“公式层/门控层提取”的收敛计划，否则 #82（定额）会再复制一遍。
4. **profile 事实源**：统一表述为“唯一登记源码确认”，删除 ESP-CODE-001/002 阻断可用性的旧描述（F1）。
5. **候选口径清单**：把 D1-D20、ESP-*/RSP-*/ROP-* 与二次保障参数合并成一张带开关名的签核表（F5 优先级项并入）。

## 5. 未检查项

- 未逐行审查 `catalog_split.py`（服务/材料分支 655-885）、`employee_outpatient_special.py` 其余 ~1000 行、`supplements.py`。
- 未跑实库 157 笔重放、Flow、浏览器 E2E；未验证 #82 定额付费基线（`.planning/reviews/2026-10-14-issue82/baseline_sources.json`）。
- 结论不替代业务签核；F2/F3 为静态推断，需以稀疏夹具回归坐实。
