# Issue #78 城镇职工门诊费用分解 —— 代码走读文档

> 用途：开发者拿着本文档逐模块过代码。所有函数名、字段名、路径均已对照真实代码核对。
> 配套文档：
> - 设计文档：`docs/superpowers/specs/2026-09-24-issue78-outpatient-fee-decomposition-design.md`（下称「设计 §x.y」）
> - 待遇参数表：`docs/superpowers/specs/2026-09-28-issue78-城镇职工门诊待遇参数.csv`（规则 ID EOP-* 的唯一数值来源）
>
> 阅读主线：**一笔门诊交易号（T_TradeNo）从进入 policy-qa 到产出 SSE 结果的完整代码链路**。

## 1. 全链路总览

```
待遇参数 CSV ──(逐行显式编码)──> params_employee_outpatient.py（PARAMS + 门控选择函数）
                                        │ get_param / select_*_param
                                        ▼
POST /policy-qa/stream（policy_qa_routes.py 门诊预取分支，_looks_like_outpatient_trade_no）
  └─> integration.maybe_decompose_outpatient(provider, trade_no, routing_context)
        │ 门控：FEE_DECOMPOSITION_ROUNDING_MODE + FEE_DECOMPOSITION_HOSPITAL_CODE + provider._connect
        │ 任一缺失/异常 → 返回 None（功能静默关闭，不影响主问答链路）
        ▼
  snapshot_service.decompose_outpatient_trade(conn, trade_no, hospital_code, rounding_mode, ...)
        │ ① adapters/outpatient_decomposition_queries.py：
        │     locate_outpatient_trade → load_outpatient_fee_items
        │     → load_drug_catalog / load_service_catalog / load_material_catalog / load_institution_level
        │     （表/列名全部来自 record_query_mappings.DEFAULT_RECORD_QUERY_MAPPING，bjyb 库 schema）
        │ ② build_snapshot：行 dict → DecompositionSnapshot（脏数据抛 ValueError → 降级 unavailable）
        │ ③ assemble_read_meta + hash_rows → 读取元数据 citation（kind="source_catalog"）
        ▼
  employee_outpatient.decompose_employee_outpatient(snapshot)   ← 编排层（组合选择 + 冲正拦截 + 串联各模块）
        ├─ classify_person / classify_institution（S1 候选码表）
        ├─ catalog_split.split_catalog        → 医保内 E / 医保外 / 自付二（逐行）
        ├─ deductible.decompose_deductible    → 起付 F = min(E, max(D-A, 0))，B = E-F
        ├─ big_pay.decompose_big_pay          → 大额支付（分段/封顶），S = B - 大额支付
        ├─ supplements.retire_supplement      → R（退休补充）
        ├─ supplements.military_supplement    → J（军残，退休基数 S-R）
        ├─ supplements.public_medical_supplement → O（公疗补足目标比例）
        └─ reconciliation.reconcile_field / identity_field × 16 个目标字段（设计 §10 核对矩阵）
        ▼
  result.SettlementDecompositionResult（Pydantic 契约，schema_version="1.0" / algorithm_version="employee_outpatient_v1"）
        ▼
  public_view.render_summary（确定性模板）→ integration.polish_summary（模型润色，数字越界回退模板）
        ▼
  public_view.build_public_view_dict → routes 层 _public_text 消毒 → FeeDecompositionPublic 校验
        → PolicyQAPublicResult.fee_decomposition → SSE result 事件
```

## 2. 参数模块：params_employee_outpatient.py

- 路径：`src/runtime/policy_qa/fee_decomposition/params_employee_outpatient.py`
- 关键函数：`get_param` / `try_get_param`、`select_param`、`_gate`、`select_deductible_param`、`select_big_pay_rate_param`、`select_excess_segment_param`、`select_cap_param`、`select_material_rule`、`select_check_fee_param`、`select_retire_supplement_param`、`select_military_param`、`select_public_medical_param`、`select_rounding_param`、`display_only_params`
- 职责：把参数表 CSV 逐行编码为 frozen dataclass `EmployeeOutpatientParam`（共 40+ 条，rule_id 与 CSV 一致）；金额/比例一律 `Decimal`（`ratio` property 把「%」单位值除以 100）。所有「选哪个版本参数」的判断都收敛在 `select_param`：按日期窗过滤 → 0 命中 `PARAM_VERSION_NOT_FOUND`、多命中 `PARAM_VERSION_AMBIGUOUS`、单命中再过 `_gate`。
- 设计依据：§9（精度/版本）、§16（门控规则）。
- fail-closed 行为（`_gate` 三条拦截）：
  - `confirmation_status == "待确认"` → `PARAM_CONFIRMATION_PENDING`；
  - `文档明确-待官方核证` 且生效日期未明确 → `PARAM_EFFECTIVE_DATE_UNCLEAR`（EOP-CAT-008、EOP-NCP-002 因此恒 unknown）；
  - 截止日期为「未知」且非「尚未终止」→ `PARAM_EXPIRY_UNKNOWN`。
  - `PAYMENT_LEVEL_DISPLAY_ONLY = "合计展示"`（EOP-RATE-201/202/203/303）不进任何 select 候选，绝不参与计算。
  - `select_rounding_param()` 恒返回 unknown——取整模式没有默认，必须由调用方显式传入（EOP-RND-001 待确认）。
  - 身份/类别未知不猜：`select_deductible_param` 等对 `PersonKind.UNKNOWN` 直接返回 `PERSON_KIND_UNKNOWN`；`select_retire_supplement_param` 对退休类别未知返回 `RETIREMENT_CATEGORY_UNKNOWN`（不默认 50%）。

## 3. 门控与接入：integration.py

- 路径：`src/runtime/policy_qa/fee_decomposition/integration.py`
- 关键函数：`maybe_decompose_outpatient`（入口）、`_rounding_mode_from_env`、`_resolve_profile_from_context`、`polish_summary`
- 职责：policy-qa 链路与分解内核之间的门控 + 表述层。
- 设计依据：§12（模型输出边界）、§13/§15 步骤 5（落点）。
- fail-closed 行为（任一不满足返回 `None`，公开结果不含 `fee_decomposition`，不报错）：
  - `FEE_DECOMPOSITION_ROUNDING_MODE` 未配置或取值非法（非 `RoundingMode` 四值之一）→ 关闭，记 warning；
  - `FEE_DECOMPOSITION_HOSPITAL_CODE` 未配置 → 关闭（注意：这是源系统 o_Trade 院区列取值，**不是**部署口径 `PLATFORM_HOSPITAL_CODE`）；
  - provider 无 `_connect` 连接工厂 → 关闭；
  - 分解过程任何异常 → 捕获后返回 None，只记日志。
  - 险种/医疗类别：`_resolve_profile_from_context` 只接受语义层字符串精确匹配 `("城镇职工基本医疗保险", "普通门诊")` → `("employee", "outpatient")`，其余一律 None（不猜测，设计 §6.1 P0）。
  - `polish_summary`：模型只做语言润色；润色文本的数字集合不是模板数字集合的子集（`set` 比较）→ 回退确定性模板，`summary_source="template"`。模型不可用/空输出同样回退。

## 4. 事实快照读取：outpatient_decomposition_queries.py + record_query_mappings.py

- 路径：
  - `src/adapters/data_supply/outpatient_decomposition_queries.py`
  - `src/adapters/data_supply/record_query_mappings.py`（`DEFAULT_RECORD_QUERY_MAPPING`，已按真实 bjyb 库 schema 核对，2026-09-28）
- 关键函数：`locate_outpatient_trade`、`load_outpatient_fee_items`、`extract_item_codes`、`load_drug_catalog`、`load_service_catalog`、`load_material_catalog`、`load_institution_level`、`build_snapshot`、`hash_rows`、`assemble_read_meta`
- 职责：交易号 → 完整事实快照（交易锚点 + 全部明细 + 全版本目录 + 机构等级 + 账面观测值）。表名/列名零硬编码，全部经 `RecordQueryMapping.column()` / `_c`/`_t` 渲染；SQL 仅只读单语句 SELECT、参数化占位符；全部返回 `AdapterCallResult`，不抛业务异常。
- 设计依据：§5（输入与只读取数）、§5.3（一次读取完整性）、§15 步骤 1。
- fail-closed 行为：
  - 交易定位 0 条 `not_found` / >1 条 `ambiguous`（不取首条）→ 服务层降级 unavailable；
  - 明细完整读取禁止分页截断；重复行键原样带出（内核判 `DUPLICATE_LINE_KEY`）；
  - 目录按编码批量读**全版本**（含空截止日期行），有效期筛选留给内核，不在 WHERE 排除（§5.3-4）；
  - 机构表 0 条/多条 → `h_level=None` + note，机构类别按未知处理（连接键待确认）；
  - `build_snapshot`：金额构造不经过 float（`_to_decimal`）；`None≠0`（账面缺失列保持 None）；缺交易日期或明细缺 Fee → 抛 `ValueError`（脏数据），由服务层降级 unavailable；
  - `opf_fee_date` 映射值为空串（真实库 o_FeeItem 无费用发生日期列）→ `_render_columns` 跳过该列，组装层降级用交易日期并追加 note `FEE_OCCURRENCE_DATE_FALLBACK`；
  - `extract_item_codes`：`ItemType=="0"` 为药品，其余取值统一归非药品（语义待确认，不猜诊疗/材料归属）；`build_snapshot` 中对应 `catalog_kind=CatalogKind.UNKNOWN`；
  - 材料人工器官/集采中选标志列未映射 → 追加 note `MATERIAL_EXCEPTION_FLAGS_UNMAPPED`，标志按 False 占位；
  - 药品集采标识空值 → note `DRUG_A_YPBS_EMPTY`，按非集采占位；
  - 自制剂所属机构列（`cat_drug_preparation_hospital`）真实库无此列 → None（内核自制剂分支因此走 `PREPARATION_HOSPITAL_UNKNOWN`）；
  - 年度累计口径标志位 `prior_in_scope_fee_is_pre_trade` / `prior_fund_payment_is_pre_trade` / `in_scope_basis_aligned` 全部默认 `False`（§16 P0，未确认不硬算）；
  - `PersonProfile` 只映射 `person_type_code` 与 `birth_date`；退休类别/军残/公疗等资格字段无确认来源一律 None（禁止金额反推资格）；
  - 出生日期仅进内部值对象供年龄档计算，不进结果 citations。

## 5. 胶水服务：snapshot_service.py

- 路径：`src/runtime/policy_qa/fee_decomposition/snapshot_service.py`
- 关键函数：`decompose_outpatient_trade`（入口）、`_unavailable_result`、`_meta_citation`
- 职责：串起「定位 → 明细 → 目录/机构 → profile 解析 → build_snapshot → decompose_employee_outpatient → 附读元数据 citation」七步。
- 设计依据：§15 步骤 1、§6.1（profile P0）、§5.3-7/§9（读取元数据）。
- fail-closed 行为：
  - 适配器任一环节 FAILED/歧义 → `_unavailable_result` 返回带 uncertainties 的 unavailable 结果，**不抛异常栈**（code：`READ_FAILED` / `TRADE_NOT_FOUND` / `TRADE_AMBIGUOUS` / `SNAPSHOT_ASSEMBLY_FAILED`）；
  - `profile_resolver=None`（默认）→ `insurance_type/medical_category = "unknown"`，内核自然走 `UNSUPPORTED_PROFILE`/unavailable；resolver 抛异常同样按 unknown 处理并留 note `PROFILE_RESOLVER_FAILED`；
  - 读元数据（来源/各表行数/内容哈希 `hash_rows`/映射指纹 `mapping_fingerprint`）以 `kind="source_catalog"` 写入 citations。

## 6. 领域模型：domain/insurance/fee_decomposition.py

- 路径：`src/domain/insurance/fee_decomposition.py`
- 关键内容：枚举 `BranchOutcome`（true/false/unknown/not_evaluated/blocked/not_applicable，§8 三值逻辑扩展）、`CheckType`、`CheckStatus`、`ExecutionStatus`、`ExplanationLevel`、`RoundingMode`、`PersonKind`、`InstitutionKind`、`CatalogKind`、`PackagingType`；值对象 `TradeAnchor`、`PersonProfile`、`InstitutionProfile`、`AnnualAccumulation`、`FeeLineItem`、`DrugCatalogEntry`、`ServiceCatalogEntry`、`MaterialCatalogEntry`、`ObservedSettlementAmounts`、`DecompositionSnapshot`、`BranchTrace`、`BranchCondition`、`CalculationRecord`、`DecompositionUncertainty`、`DecompositionCitation`、`FieldReconciliation`；纯值函数 `apply_rounding`（默认到分 `CENT=0.01`）、`decimal_to_str`。
- 职责：全部 frozen dataclass，不含任何流程编排。`ObservedSettlementAmounts` 是账面观测值——**仅作核对目标，不作为同字段重算输入**。
- 设计依据：§5 输入快照、§8 轨迹、§9 精度、§10 核对。

## 7. 编排层：employee_outpatient.py

- 路径：`src/runtime/policy_qa/fee_decomposition/employee_outpatient.py`
- 关键函数：`decompose_employee_outpatient`（主流程）、`classify_person`、`classify_institution`、`_build_fields`、`_empty_result`
- 职责：按 10 步串联：① 组合选择（仅 employee+outpatient）② 冲正/负明细拦截 ③ 身份/机构分类 ④ 目录分解 ⑤ 起付线 ⑥ 大额支付 ⑦ 补充待遇链 S→R→J→O ⑧ 取整全局不确定性 + 参数 citations ⑨ 逐字段核对（`_build_fields`，16 个目标字段，§10 核对矩阵）⑩ 汇总 execution_status 与 answer_constraints。
- 设计依据：§6.1/§7（流程）、§7.5（叠加顺序 EOP-PMED-004：大额→退休→军残→公疗）、§10/§11。
- fail-closed 行为：
  - 组合不支持 → `UNSUPPORTED_PROFILE`，unavailable，不套用职工门诊公式；
  - 冲正/退款/负明细（`is_reversal` 或任一明细 fee/count < 0）→ `UNSUPPORTED_REVERSAL_OR_NEGATIVE`，unavailable，不取绝对值套正向公式；
  - `classify_person`：S1 候选代码集（`EMPLOYED_PERSON_TYPE_CODES` / `RETIRED_PERSON_TYPE_CODES`）之外 → `PERSON_TYPE_UNKNOWN`，不默认在职；
  - `classify_institution`：`H_LEVEL=14` 社区、`0≤level<14` 其他，空值/异常值/其他 → `H_LEVEL_UNKNOWN`；
  - 目录分解 `fatal_issue`（重复行键）→ 直接 unavailable；
  - 公疗 `prior_fund_on_g`：仅当 `in_scope_basis_aligned` 且 `prior_in_scope_fee_is_pre_trade` 均 True 且大额/退休/军残金额全部独立得出时才 = 大额+退休+军残合计（在乡军残分支不含军残）；否则 None → 公疗 unknown，**绝不用整笔账面基金支付替代适用段支付**；
  - 身份/机构候选码表以 `kind="issue_note"`、`approval_status="pending"` 进 citations，未确认不升级。

## 8. 目录分解：catalog_split.py

- 路径：`src/runtime/policy_qa/fee_decomposition/catalog_split.py`
- 关键函数：`split_catalog`（入口）、`_split_line`、`_split_drug`、`_split_service`、`_split_material`、`_match_catalog`、`_match_branch`、`_classify_ratio`、`_apply_division`、`_ncp_price_check`、`_fee_quantity_check`、`rule_uncertainties`
- 职责：三大目录逐项分解出互斥金额桶（医保内 in_scope / 医保外 out_scope）+ 可追踪子项自付二（self_pay_2，不预先认定为第三项）。每行产出 `LineDecomposition` + 分支轨迹 + 计算记录 + 不确定性。
- 设计依据：§7.2、§5.3（空截止日期不默认永久有效）、§10（合计完整性）。
- fail-closed 行为：
  - 重复行键 → `fatal_issue="DUPLICATE_LINE_KEY"`，合计不可用（不静默去重）；
  - 目录匹配按**费用发生日期**：0 命中 `MISSING_CATALOG`、多命中 `AMBIGUOUS_CATALOG`、存在空截止日期条目 `CATALOG_VALIDITY_UNKNOWN`（即使另有确定命中也不放行）——不取首条；
  - 目录 sflb 与账面 FeeType 冲突 → `CLASSIFICATION_CONFLICT` 停未知；收费类别取值不在候选集 → `CLASSIFICATION_UNKNOWN`/`CLASSIFICATION_EMPTY`；有自付但缺自付比例 → `SELF_PAY_RATIO_MISSING`；
  - 自制剂（ypfl∈{16,6}）：与集采重叠 `PREPARATION_NCP_OVERLAP_UNCONFIRMED`、缺所属机构 `PREPARATION_HOSPITAL_UNKNOWN`、单价>bzjg 整项自费、缺价 `PREPARATION_PRICE_UNKNOWN`；
  - 集采（a_ypbs=1）：缺限价/单价 `NCP_LIMIT_MISSING`；超限价后——未通过一致性评价 `NCP_UNAPPRAISED_RULE_UNCONFIRMED`（EOP-NCP-002 生效日期未明确）、其他药品 `NCP_EXCESS_RATIO_SEMANTICS_UNCONFIRMED`（a_xbbl 增量/最终语义未确认，不编码公式）；
  - 诊疗 sfxmdj：空 `SFXMDJ_EMPTY`（禁止猜无自付）、非 1/2/3 `SFXMDJ_UNKNOWN_VALUE`；sfxmdj=2 时优先自付比例，其次单价限额超出入自付二，两者皆缺 `SELF_PAY_RULE_PARAM_MISSING`；检查费（is_check_fee）先经 `select_check_fee_param` 门控（当前恒 unknown）；
  - 材料：人工器官/集采中选 `MATERIAL_EXCEPTION_POLICY_NOT_COVERED`（EOP-MAT-005 政策参数未覆盖）；单价缺失 `UNIT_PRICE_MISSING`；门槛规则版本经 `select_material_rule` 门控（2023-01-01 起 1000 元/80%，2008-07-01 起 500 元/70%，更早 500 元/50%）；≥门槛按纳入比例入医保内、余量入自付二并附 `MATERIAL_SELF_PAY_CALIBER_UNCONFIRMED`（与 FeeOut 包含关系待数据字典确认）；
  - 每行附 `CATALOG_RULE_PENDING_OFFICIAL_CONFIRMATION`（`rule_uncertainties`）：EOP-CAT 系列为「文档明确-待官方核证」，结果不升级为已确认政策解释；
  - `_fee_quantity_check`：Fee 与 UnitPrice×Count 分开校验，不一致仅记 `FEE_QUANTITY_MISMATCH` 分支，不互相替代；
  - 合计仅在**全部行**分解成功时填 `total_in_scope/total_out_scope/total_self_pay_2` 并置 `is_complete=True`，否则合计为 None（§10：完整性不足的合计不得作为完整合计）。

## 9. 起付线：deductible.py

- 路径：`src/runtime/policy_qa/fee_decomposition/deductible.py`
- 关键函数：`decompose_deductible`
- 职责：`F = min(E, max(D - A, 0))`，`B = E - F`。E=目录分解完整医保内合计，A=交易前同口径年度累计，D=适用起付标准（在职 1800/退休 1300，历史档经版本选择）。
- 设计依据：§7.3。
- fail-closed 行为：
  - E 缺失（目录不完整）→ `UPSTREAM_BASE_MISSING`，blocked；
  - 参数版本不确定 → unknown，不采用默认值；
  - A 缺失 `PRIOR_ACCUMULATION_MISSING` 或口径未确认 `PRIOR_ACCUMULATION_CALIBER_UNCONFIRMED`（`prior_in_scope_fee_is_pre_trade=False`，当前恒为此态）→ unknown，**保留轨迹不硬算**；
  - `T_FirstPay` 仅为核对目标，不用于反推 D 或覆盖 F；min/max 运算无取整（`rounding_rule="not_applicable"`）。

## 10. 大额支付：big_pay.py

- 路径：`src/runtime/policy_qa/fee_decomposition/big_pay.py`
- 关键函数：`decompose_big_pay`、`full_age_at`
- 职责：按身份/年龄档（退休 <70/≥70，以交易日期算已满周岁）/机构（社区/其他）选基础比例档；2022-12-31 前受 2 万元基金支付封顶（EOP-CAP-001，`min(B×rate, cap-基金累计)`）；2023-01-01 起无封顶、基金年度累计支付超 2 万段 60%（EOP-RATE-301/302，边界换算 `b1 = min(B, (20000-prior_fund)/rate)`）。大额个人承担 `S = B - 大额支付`。
- 设计依据：§7.4。
- fail-closed 行为：
  - B 缺失 → `UPSTREAM_BASE_MISSING`，blocked；
  - 退休但缺出生日期 → `BIRTH_DATE_MISSING`，unknown；2 月 29 日出生附 `AGE_LEAP_DAY_CALIBER_UNCONFIRMED`；
  - 比例档选择失败（含 `AGE_BAND_UNKNOWN`/`INSTITUTION_KIND_UNKNOWN`）→ unknown，不采用默认比例；
  - 基金支付累计缺失 `FUND_CUMULATIVE_MISSING` 或口径未确认 `FUND_CUMULATIVE_CALIBER_UNCONFIRMED`（`prior_fund_is_pre_trade_confirmed=False`，当前恒为此态）→ unknown，不硬算；
  - 分段边界是**基金年度累计支付**口径（`prior_fund_payment`），不得用费用累计替代；不得由账面 T_BigPay 反推比例；
  - 存在封顶以上费用时附 `BEYOND_CAP_FIELD_ATTRIBUTION_UNCONFIRMED`（T_BigSelfPay/T_BeyondBig 归属未确认，不自动归入大额自付）。

## 11. 补充补助链：supplements.py

- 路径：`src/runtime/policy_qa/fee_decomposition/supplements.py`
- 关键函数：`retire_supplement`（R）、`military_supplement`（J）、`public_medical_supplement`（O）
- 职责与 fail-closed 行为（设计 §7.5）：
  - **退休补充**（`retire_supplement`，EOP-RSUP-001/002，普通 50%/预提 60%，基数=S，资格按结算日期）：非退休 → not_applicable；缺纳入日期 `SUPPLEMENT_ENROLL_DATE_MISSING`（不默认已纳入）；未纳入 `NOT_YET_ENROLLED`；S 缺失 blocked；普通/预提类别未知 `RETIREMENT_CATEGORY_UNKNOWN`（不默认 50%）。
  - **军残**（`military_supplement`，EOP-DVET-001..004，资格按费用发生日期）：身份 False → not_applicable、None → `DISABLED_VETERAN_STATUS_UNKNOWN`（不按账面非零支付推断资格）；公疗在乡军残 → not_applicable（`RURAL_DISABLED_VETERAN_PUBLIC_MEDICAL_EXCLUSION`）；在乡/公疗资格未知且会改变路径 → `RURAL_PMED_STATUS_UNKNOWN`；等级不在 1-4/5-6 → `MILITARY_GRADE_UNKNOWN`；缺资格有效期 `MILITARY_ELIGIBILITY_PERIOD_UNKNOWN`；全部明细在资格期外 → not_applicable（`MILITARY_NOT_ELIGIBLE_AT_FEE_DATE`）；费用跨资格生效日 → blocked `CROSS_DATE_ALLOCATION_UNCONFIRMED`（不按比例摊分）；退休军残基数 S-R：**R 未知不得用零代替**（blocked `RETIRE_SUPPLEMENT_UNKNOWN`），R 明确不适用按 0 继续并保留依据。
  - **公疗**（`public_medical_supplement`，EOP-PMED-001..003，目标比例退休 95%/在职 90%/在乡 100%）：`G = max(A_in+E_in-1300, 0) - max(A_in-1300, 0)`，`O = round(G×q) - prior_fund_G`。资格未知 `PMED_ELIGIBILITY_UNKNOWN`；本人定点关系未知 `DESIGNATED_HOSPITAL_UNKNOWN`（本人定点≠医保定点）；缺医保内累计 `PMED_ACCUMULATION_MISSING`；G=0 → 补助 0（`BELOW_PMED_THRESHOLD`）；`prior_fund_G` 不可确定 → `PMED_PRIOR_FUND_ALLOCATION_UNKNOWN`（不以整笔基金支付代替）；已有基金支付超目标 → O=0 并附 `PMED_PRIOR_EXCEEDS_TARGET`（**不输出负补助、不冲减已有基金**）。
  - 统一纪律：资格确定不满足 → not_applicable（账面已有非零支付的冲突由核对层诊断）；资格未知 → unknown，不得当作不享受。

## 12. 账面核对：reconciliation.py

- 路径：`src/runtime/policy_qa/fee_decomposition/reconciliation.py`
- 关键函数：`reconcile_field`、`identity_field`、`overall_reconciliation_status`、`coverage_counts`
- 职责：字段级核对（§10）。核对类型固定三类：`independent_recalculation`（独立重算）/ `detail_aggregation`（明细账面汇总）/ `identity_check`（账面恒等勾稽，只用账面观测分量，**不证明字段原因**）。
- fail-closed 行为：
  - `difference` 统一 = calculated − observed，一分钱差异保留，不自动抹平；
  - observed 为 None → not_verifiable（`OBSERVED_AMOUNT_UNKNOWN`，未知目标值不是零）；calculated 为 None 或模块非 TRUE → not_verifiable（`CALCULATION_UNAVAILABLE`），**绝不用观测值回填（禁止反推）**；
  - 模块 not_applicable 但账面非零 → 保留 not_applicable 并标 `ELIGIBILITY_CONFLICT_WITH_BOOK`；
  - `identity_field`：任一分量未知 → not_verifiable（`IDENTITY_COMPONENTS_INCOMPLETE`）；
  - `overall_reconciliation_status`：任一 mismatched → `mismatched`；全部 matched/not_applicable → `matched`；其余 → `not_verifiable`；
  - 编排层补充：T_FundPay 在 `has_other_fund_channels=True` 时 not_applicable（`FUND_CHANNELS_NOT_EXHAUSTED`）、None 时 not_verifiable（`FUND_CHANNELS_EXHAUSTIVENESS_UNKNOWN`，当前恒为此态）；T_PersonCountPay/T_CashPay 恒 not_verifiable（`PAYMENT_CHANNEL_REPLAY_UNAVAILABLE`，缺扣款规则与流水）。

## 13. 结果契约与对外视图：result.py / public_view.py / public_contract.py / policy_qa_routes.py

- 路径：
  - `src/runtime/policy_qa/fee_decomposition/result.py` —— `SettlementDecompositionResult`（Pydantic，`SCHEMA_VERSION="1.0"`、`ALGORITHM_VERSION="employee_outpatient_v1"`）+ 领域值对象→契约模型的 `*_to_model` 转换函数；
  - `src/runtime/policy_qa/fee_decomposition/public_view.py` —— `render_summary`（确定性模板：总览状态行 + 逐字段行 + 未决事项）、`build_public_view_dict`（纯映射，不含分支轨迹/计算记录/快照引用等审计级细节）；
  - `src/runtime/policy_qa/public_contract.py` —— `FeeDecompositionPublic`（`extra="forbid"`，挂在 `PolicyQAPublicResult.fee_decomposition`，None 时不输出）；
  - `src/runtime/api/policy_qa_routes.py` —— 门诊预取分支调用 `maybe_decompose_outpatient`（`run_in_executor`），`_build_public_result` 中经 `_public_text` 消毒后 `FeeDecompositionPublic.model_validate`。
- 设计依据：§11（规范结果）、§12（模型输出边界与展示）。
- fail-closed 行为：金额为十进制字符串原样透传，不做 float 转换；模板只使用结果中已有事实，不补全缺失规则；差异只原样呈现（实际值/计算值/差额），不判定医保系统对错；物理表/列不进入公开视图。

## 14. 如何读一笔交易的分解结果

`SettlementDecompositionResult`（对外为 `FeeDecompositionPublic` 子集）的读法：

- **`execution_status`**（总体执行状态轴，`ExecutionStatus`）：
  - `complete`：目录分解完整（`is_complete=True`）且无任何 unknown/blocked 分支——全部目标字段都独立算出；
  - `partial`：存在 unknown/blocked 分支或目录不完整——部分字段有独立计算值，其余停在未知；
  - `unavailable`：读取失败/交易未找到或歧义/快照组装失败/组合不支持/冲正退款——无字段级结果。
- **`reconciliation_status`**（总体核对状态轴，`overall_reconciliation_status`）：
  - `matched`：全部字段 matched 或 not_applicable；`mismatched`：任一字段一分钱差异；`not_verifiable`：其余情形（含 unavailable）。
  - 注意：complete + matched 才允许 `answer_constraints.may_claim_full_explanation=True`，对外措辞才可出现「完整解释」。
- **字段级 `fields[].check_status`**（`CheckStatus`）：
  - `matched`：独立计算值与账面观测值完全一致；
  - `mismatched`：两者不一致，`difference`（= calculated − observed）原样保留；
  - `not_verifiable`：无法核对——看 `reason_code` 区分：`CALCULATION_UNAVAILABLE`（没算出来）/ `OBSERVED_AMOUNT_UNKNOWN`（账面缺值）/ `IDENTITY_COMPONENTS_INCOMPLETE`（恒等式分量缺失）/ `FUND_CHANNELS_EXHAUSTIVENESS_UNKNOWN` / `PAYMENT_CHANNEL_REPLAY_UNAVAILABLE` 等；
  - `not_applicable`：资格确定不满足（本单不适用该待遇）；若账面却有非零支付，`reason_code=ELIGIBILITY_CONFLICT_WITH_BOOK`。
- **`fields[].check_type`**：`independent_recalculation`（规则重算，最强解释）、`detail_aggregation`（明细账面汇总对照）、`identity_check`（账面恒等勾稽，只用账面分量，不证明原因）。`explanation_level`：`amount_reconciled`（金额已核对一致）/ `observed_only`（只有账面值）/ `unexplained`（连账面值都没有）。
- **`uncertainties[]`**：每条含 `code`（机器可读原因码，如 `PRIOR_ACCUMULATION_CALIBER_UNCONFIRMED`）、`message`（中文人类可读说明）、`affected_fields`（受影响的账面字段，如 `("T_FirstPay",)`）。**uncertainties 非空即存在未确认口径，对应字段结论不得当作已确认政策解释**。
- **`branches[]`**：审计级分支轨迹（`step_id`/`module_id`/`outcome`/`reason_code`/`rule_refs`/`input_refs`/`calculation_refs`），仅内部结果携带，不进公开视图；`calculations[]` 记录每条计算的公式 ID、操作数（ref+值）、未取整结果、取整规则、最终结果。
- **`citations[]`**：`kind` 区分 `settlement_fact`（账面事实）/ `issue_note`（S1 候选码表，approval_status=pending）/ `policy_document`（EOP-* 规则，approval_status=参数表确认状态）/ `source_catalog`（读取元数据：行数+内容哈希+映射指纹）。
- **`coverage`**：`target_field_count`（16 个目标字段）、`independently_explained_count`（独立重算且 matched 的字段数）、`amount_reconciled_count`、`observed_only_count`。

## 15. 已知的未确认口径（P0/P1）—— 签核决策清单

以下每一项都是代码中显式 fail-closed 的点；签核确认前系统**不会**硬算，而是输出 unknown/partial 并留痕。签核时需逐项给出裁决。

| # | 未确认口径 | 代码位置 | 当前行为（fail-closed） |
|---|-----------|---------|------------------------|
| 1 | 险种/医疗类别码表：`P_FundType` 职工代码、`T_CureType` 普通门诊代码（P0） | `integration._resolve_profile_from_context`；`snapshot_service` profile_resolver | 仅接受语义层精确匹配「城镇职工基本医疗保险+普通门诊」；默认 resolver=None → unknown → `UNSUPPORTED_PROFILE`/unavailable，不猜测 |
| 2 | `TB_FeeIn` 是否交易前累计、年度范围、是否跨院（P0） | `outpatient_decomposition_queries.build_snapshot`（`prior_in_scope_fee_is_pre_trade=False`）；`deductible.decompose_deductible` | 起付 A 口径未确认 → `PRIOR_ACCUMULATION_CALIBER_UNCONFIRMED`，起付金额不独立计算 |
| 3 | 基金支付累计口径（封顶/超 2 万段，P0） | `build_snapshot`（`prior_fund_payment=None`）；`big_pay.decompose_big_pay` | 无来源列且口径未确认 → `FUND_CUMULATIVE_MISSING`，大额支付不硬算 |
| 4 | 起付累计与公疗 1300 门槛累计口径一致性（P0） | `build_snapshot`（`in_scope_basis_aligned=False`）；`employee_outpatient` 公疗段 | `prior_fund_on_g=None` → 公疗 `PMED_PRIOR_FUND_ALLOCATION_UNKNOWN`，不以整笔基金支付代替适用段支付 |
| 5 | `ItemType` 非 0 取值语义（P0） | `extract_item_codes`；`build_snapshot`（`catalog_kind=UNKNOWN`） | 非药品统一归非药品批量读目录，但行级 `catalog_kind=UNKNOWN` → `_split_line` 走 `CATALOG_KIND_UNKNOWN` 停未知 |
| 6 | o_FeeItem 无费用发生日期列（P0，2026-09-28 真实库核实） | `record_query_mappings`（`opf_fee_date=""`）；`build_snapshot` | 该列不进 SELECT，明细降级用交易日期 + note `FEE_OCCURRENCE_DATE_FALLBACK`；目录匹配/军残资格日期依据随之降级 |
| 7 | 取整规则 EOP-RND-001（逐行/逐段/汇总层级与模式，P0/P1） | `params_employee_outpatient.select_rounding_param`（恒 unknown）；`integration._rounding_mode_from_env` | 无默认模式，须 env 显式配置才启用功能；每笔结果附全局不确定性 `ROUNDING_RULE_PENDING_CONFIRMATION`，计算记录标注 `explicit:<mode>(EOP-RND-001 待确认)` |
| 8 | 集采超限价 `a_xbbl` 语义（增量/最终比例、作用基数）；EOP-NCP-002 生效日期（P0） | `catalog_split._ncp_price_check` | 超限价后一律 unknown：`NCP_EXCESS_RATIO_SEMANTICS_UNCONFIRMED` / `NCP_UNAPPRAISED_RULE_UNCONFIRMED`，不编码公式；`consistency_evaluation_passed` 快照未映射（恒 None），前一分支当前不可达 |
| 9 | 自制剂与集采规则重叠优先次序；自制剂所属机构列（P0） | `catalog_split._split_drug`；`record_query_mappings`（`cat_drug_preparation_hospital=""`） | 重叠 → `PREPARATION_NCP_OVERLAP_UNCONFIRMED`；真实库无所属机构列 → `PREPARATION_HOSPITAL_UNKNOWN`，自制剂均停未知 |
| 10 | 门诊检查费单价限额 EOP-CAT-008（200 元/8%，生效日期未明确，P0） | `params_employee_outpatient.select_check_fee_param`；`catalog_split._split_service` | 门控恒 unknown，不静默生效；且 `is_check_fee` 快照未映射（恒 False），该分支当前不可达 |
| 11 | 材料人工器官/集采中选标志列未映射（P1）；EOP-MAT-005 例外政策参数未覆盖 | `build_snapshot`（note `MATERIAL_EXCEPTION_FLAGS_UNMAPPED`）；`catalog_split._split_material` | 标志按 False 占位；若映射后任一为真 → `MATERIAL_EXCEPTION_POLICY_NOT_COVERED` 停未知；材料未纳入部分与 FeeOut 的包含关系附 `MATERIAL_SELF_PAY_CALIBER_UNCONFIRMED` |
| 12 | 材料目录是否完整包含在 yb_xzzlfwxm（P1）；诊疗单价限额列不存在 | `record_query_mappings`（`material_catalog_table=dbo.yb_xzzlfwxm`，`cat_svc_unit_price_limit=""`） | 材料与诊疗同表读取；单价限额规则因列缺失不适用（sfxmdj=2 且无自付比例时 `SELF_PAY_RULE_PARAM_MISSING`） |
| 13 | 退休普通/预提类别、补充保险纳入日期、军残等级/资格期/在乡身份、公疗资格与本人定点关系的数据来源（P0） | `build_snapshot`（`PersonProfile` 资格字段一律 None）；`supplements.*` | 全部 unknown（`SUPPLEMENT_ENROLL_DATE_MISSING`/`DISABLED_VETERAN_STATUS_UNKNOWN`/`MILITARY_GRADE_UNKNOWN`/`PMED_ELIGIBILITY_UNKNOWN`/`DESIGNATED_HOSPITAL_UNKNOWN`），禁止由金额反推资格 |
| 14 | 人员类别/机构等级候选码表（S1 候选，P1） | `employee_outpatient.classify_person/classify_institution` | 候选集之外 → `PERSON_TYPE_UNKNOWN`/`H_LEVEL_UNKNOWN`；码表以 `issue_note`+pending 进 citations，未升级 |
| 15 | 机构表连接键（P1） | `load_institution_level` | 0 条/多条均不取值，`h_level=None` + note，机构类别按未知 |
| 16 | 自付一公式、基金渠道穷尽性、账户/现金分配规则与流水（P0/P1） | `employee_outpatient._build_fields` | T_SelfPay1/T_SelfPayAll 仅 `identity_check`（账面勾稽，不证明原因）；T_FundPay 恒 `FUND_CHANNELS_EXHAUSTIVENESS_UNKNOWN`；T_PersonCountPay/T_CashPay 恒 `PAYMENT_CHANNEL_REPLAY_UNAVAILABLE` |
| 17 | 公疗 1300 元以下部分处理、已有待遇超目标处理（P0） | `supplements.public_medical_supplement`（`_PMED_THRESHOLD=Decimal("1300")` 硬编码） | G=0 时补助 0；已有基金超目标时 O=0 + `PMED_PRIOR_EXCEEDS_TARGET`，不输出负补助、不冲减已有基金 |
| 18 | 费用跨军残资格生效日的分配依据（P0） | `supplements.military_supplement` | blocked `CROSS_DATE_ALLOCATION_UNCONFIRMED`，不按比例摊分 |
| 19 | 冲正/退款/部分退费/负明细（首期不支持，EOP-REF-001/002） | `employee_outpatient` 步骤 2；`build_snapshot` 冲正识别 | unavailable `UNSUPPORTED_REVERSAL_OR_NEGATIVE`，不取绝对值套正向公式 |
| 20 | 目录空截止日期语义（P1）；EOP-CAT 结构性划分语义为「文档明确-待官方核证」 | `catalog_split._match_catalog`；`rule_uncertainties` | 空截止条目存在即 `CATALOG_VALIDITY_UNKNOWN`（不默认永久有效）；每行附 `CATALOG_RULE_PENDING_OFFICIAL_CONFIRMATION` |

签核提示：第 2/3/4 项是当前绝大多数真实交易停在 partial 的直接原因（起付、大额、公疗三级串联阻断）；第 5/6 项决定目录分解能否从「逐行未知」转为可用。优先级建议按设计 §16 的 P0 先于 P1。

## 16. 走读顺序建议

1. 先读 `domain/insurance/fee_decomposition.py` 建立词汇表（枚举 + 值对象）；
2. 再读 `params_employee_outpatient.py` 的 `_gate`/`select_param`（理解「参数不确认不生效」的总开关）；
3. 沿链路读：`integration.py` → `snapshot_service.py` → `outpatient_decomposition_queries.py` → `employee_outpatient.py` → 四个计算模块（catalog_split → deductible → big_pay → supplements）→ `reconciliation.py` → `result.py`/`public_view.py`；
4. 对照第 15 节清单核对每个 fail-closed 点的签核状态。
