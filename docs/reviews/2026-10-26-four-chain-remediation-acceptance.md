# 四链路结算解释整改验收报告

日期：2026-10-26。任务书：[2026-10-26-four-chain-settlement-remediation-tasks.md](2026-10-26-four-chain-settlement-remediation-tasks.md)；
问题依据：[2026-10-26 对抗性评审](2026-10-26-four-chain-settlement-adversarial-review.md)。

**结论：10 项任务全部落地并复验。费用分解正文改由后端确定性证据整块渲染（不再允许模型改写金额/算式），
四链路 74 项展示金额 + 10 行费用在真实服务上逐项验收：54 项原因已解释、18 项原单事实、9 项结构性不适用、
3 项诚实缺证（职工门诊军残/退役医疗费/公疗补充 0 元，内核无对应规则）。核心金额关系 22/22 在线通过。
本轮未修改政策参数、取整模式、累计确认门控与源结算数据。**

## 1. 改动文件

| 层 | 文件 | 改动 |
|---|---|---|
| 解释出口 | `src/runtime/policy_qa/fee_decomposition/model_explanation.py` | 确定性正文渲染（`render_evidence_answer`）+ `TargetEvidence`/`LineTargetEvidence` 证据；`mixed` 目标、“自付（二）”别名、“医保内外”行属性词、账面勾稽字段标注“按原单记录列示” |
| 解释出口 | `src/runtime/policy_qa/fee_decomposition/field_explanations.py` | 字段四要素固定说明（医保外阶段口径、自付二构成、GRZIF1 计算构成、零金额三态） |
| 公开投影 | `src/runtime/policy_qa/fee_decomposition/public_view.py` | `_field_brief` 多步骤字段渲染终端公式+上游基数，去掉“经 N 步/可展开”占位 |
| 目标解析 | `src/runtime/policy_qa/fee_decomposition/followup_target.py` | mixed 目标跨追问继承、换单不继承 |
| 路由 | `src/runtime/api/policy_qa_routes.py` | 旧 GET 补 `ensure_fee_decomposition_read`；会话缓存只存可复用结果 + 链路一致才复用；mixed/cover_all 的来源并集与 `calculation_checked` |
| 前端 | `src/apps/portal/src/components/policy-qa/settlement-agent-workspace.tsx` | 旧 GET 携带 `feeReadAuthHeaders()`；`@换结算` 复用当前患者候选列表项（链路/日期/类型），候选外提示 |
| 前端 | `src/apps/portal/src/components/policy-qa/settlement-time-browser.tsx` | 候选列表上送工作区（`onCandidatesChange`） |
| 测试 | `src/tests/unit/runtime/policy_qa/fee_decomposition/test_model_explanation.py` | 确定性正文、逐目标验收、四链路核心算式 |
| 测试 | `src/tests/unit/runtime/policy_qa/fee_decomposition/test_question_target_extension.py` | mixed/cover_all/bill.*/名称一致性/指代继承 |
| 测试 | `src/tests/unit/runtime/policy_qa/fee_decomposition/test_field_explanations.py` | 固定说明同源同文、医保外/自付二/GRZIF1/零金额 |
| 测试 | `src/tests/unit/runtime/policy_qa/fee_decomposition/test_session_decomposition_cache.py` | unavailable 不缓存、链路冲突当未命中 |
| 测试 | `src/tests/unit/runtime/policy_qa/fee_decomposition/test_acceptance_grading.py` | **新增**：逐目标验收判定与被删除的“假通过”反例 |
| 测试 | `src/tests/unit/runtime/policy_qa/fee_decomposition/test_resident_outpatient_special.py` | 688 目录夹具补真实集采标识（见 §3.5） |
| 测试 | `src/tests/integration/api/test_policy_qa_routes.py` | 旧 GET 鉴权（401/403/provider 未调用） |
| 测试 | `src/tests/integration/api/test_policy_qa_session_decomposition_api.py` | unavailable 不缓存、错链路→正确链路恢复 |
| 测试 | `src/apps/portal/src/tests/components/settlement-agent-workspace.test.tsx` | `@换结算` 命令链路、候选外提示、换患者隔离、慢响应、旧 GET 令牌 |
| 文档 | `PROGRESS.md` | 本轮实际状态 |

## 2. 十项任务逐项结果

| # | 任务 | 结果 | 证据 |
|---|---|---|---|
| 1 | 确定性证据生成正文 | 完成。`explain_decomposition` 不再调用模型，正文=证据块；`used_model=False`；可用性按 `evidence_answer_status`；无证据仍 unavailable | `test_model_explanation.py::test_answer_is_rendered_from_backend_evidence_without_calling_model`、`test_0408_model_free_text_never_enters_fee_decomposition_answer`、`test_0408_model_config_timeout_and_error_content_keep_same_fact_block` |
| 2 | 正文/侧栏直接给公式 | 完成。多步骤字段输出终端公式+上游基数；金额两位小数只作用于展示文本 | `test_0408_big_pay_answer_has_correct_capped_formula`、`test_567_retire_subsidy_answer_gives_423_half_equals_211_50`、`test_public_view.py` 多步骤断言 |
| 3 | 医保外/自付二/计算构成含义 | 完成。医保外区分基本划分与二次保障后负担；自付二含比例先行+超限价；GRZIF1 标注计算构成边界；零金额三态 | `test_field_explanations.py::test_fee_out_meaning_is_stage_definition_not_final_burden`、`test_688_fee_out_composition_lists_actual_secondary_coverage`、`test_self_pay_2_meaning_covers_proportional_and_over_limit` |
| 4 | 字段+行混合目标 | 完成。`QuestionTarget.mixed`；来源为并集；`calculation_checked` 同时校验字段与行；cover_all 含 `bill.*` | `test_question_target_extension.py::test_mixed_field_and_line_question_keeps_both_targets`、`test_cover_all_with_named_line_keeps_full_coverage`、`test_mixed_question_with_both_scope_words_is_not_a_wrong_item_name`（本轮补） |
| 5 | `bill.*` 进入目标证据 | 完成。取模板名称/金额+固定说明；缺映射如实说明，不借相邻字段 matched | `test_bill_field_target_binds_template_amount_and_fixed_explanation`、`test_bill_field_without_template_explanation_is_honest_gap` |
| 6 | 行号与项目名不符先澄清 | 完成。名称不存在同样拦截；纯属性问句仍按行解释；同名晶体按行号/金额消歧 | `test_nonexistent_name_with_valid_line_number_is_invalid`、`test_amount_clue_disambiguates_duplicate_item_names`、`test_quoted_item_name_mismatch_with_line_number_is_invalid` |
| 7 | 旧 GET 鉴权 + 前端令牌 | 完成。鉴权先于 provider/查询（普通与 compare）；前端旧 GET 带 `feeReadAuthHeaders()` | `test_policy_qa_routes.py::test_settlement_explanation_get_requires_fee_read_permission`（本轮新增，先红后绿）；Portal 住院单用例断言 Authorization |
| 8 | 命令换单复用候选 | 完成。候选内=列表点击同一入口（同 session/链路）；候选外提示调整时段；换患者清空候选；慢旧响应不覆盖 | Portal `@换结算 命令链路` 5 用例（本轮新增，先红后绿） |
| 9 | 只缓存可复用结果+校验链路 | 完成。unavailable/not_configured 不写缓存；auto 先规范化再与实际 chain 比较；错链路不覆盖正确结果 | `test_session_decomposition_cache.py::TestOnlyReusableResultsAreCached`（本轮新增）、API `test_unavailable_is_200_and_not_cached`、`test_wrong_chain_failure_then_corrected_chain_succeeds` |
| 10 | 逐目标验收取代假通过 | 完成。新增 `grade_target` 四态判定（目标绑定金额、构成数值、来源、缺项），旧判定三反例转红 | `test_acceptance_grading.py`（本轮新增 7 用例） |

## 3. 失败测试如何转绿（先红后绿）

1. **旧 GET 鉴权**：新增 `test_settlement_explanation_get_requires_fee_read_permission` 先失败（匿名 200 + provider 被调用）；
   在 `get_settlement_explanation` 入口加 `ensure_fee_decomposition_read(authorization)` 后通过，普通与 compare 两条分支均 401/403 且 provider 未被创建。
2. **会话缓存**：新增 `test_unavailable_is_not_cached_and_recovers`、`test_chain_mismatch_is_a_miss_and_keeps_cached_result` 先失败
   （旧实现命中旧 unavailable、忽略链路）；改为检查内层 `execution_status` + 规范化链路比较后通过；原“unavailable 被缓存”的 API 用例按新契约改写。
3. **命令换单**：Portal 新增 5 用例先失败（命令走 `handleSelect(id)` 默认住院分支）；候选列表上送 + 命令命中候选后复用选单入口转绿。
4. **混合问法误判**：新增“第1行的医保内外”用例先失败（被当成项目名“和外”）；补 `医保内外` 行属性词后转绿。
5. **688 explainable 旧断言**（评审记录的唯一失败，非本轮新增）：只读取证确认真实库 `yb_ypzdml` 中两个项目的 `A_ypbs=1/0`、`A_mzxj=809`，
   而夹具未提供 `a_ypbs_known` 导致判定路径 `unknown`。据此修夹具（不是放宽断言），金额与状态全部不变；常规负向测试
   （累计未确认→不得独立解释，`test_accumulation_unconfirmed_blocks_deductible` 等）保留。

## 4. 验证结果

| 层 | 命令 | 结果 |
|---|---|---|
| Unit（费用分解） | `pytest src/tests/unit/runtime/policy_qa/fee_decomposition -q` | **755 passed** |
| API | `pytest .../api/test_policy_qa_routes.py test_policy_qa_fee_decomposition_api.py test_policy_qa_session_decomposition_api.py -q` | **110 passed** |
| Flow（policy-qa 全部） | `pytest .../flow/test_policy_qa_{outpatient_settlement,pooling_self_pay,scalar_retrieval_baseline,session_lifecycle}_flow.py -q` | **100 passed, 1 skipped** |
| Portal | `npx vitest run` | **731 passed, 5 failed（历史预存：settlement-benefit-summary 4、settlement-path-view 1）** |
| TS | `npx tsc --noEmit` | 0 错误 |
| Lint | `ruff check`（本轮改动文件） | 通过；`policy_qa_routes.py` 仅历史 11 个未使用导入告警，未顺手清理 |

补充基线说明：

- `src/tests/unit/runtime/policy_qa`（整目录）：933 passed / 10 failed，失败全部在 `test_broad_policy_retriever.py`，
  原因是本机 Milvus 不可达（`MilvusException`，环境问题），与本轮改动无关。
- `src/tests/integration/flow`（整目录）：168 passed / 25 failed，失败在 `test_flow_query`、`test_governed_flow_lifecycle`、
  `test_ops_pg_smoke`（数据治理写权限/活库状态），与本轮改动的 policy-qa 链路无关。

## 5. 四链路逐项验收（真实服务 8109）

取证脚本（只读）：`.scratch/four-chain-remediation-20261026/accept.py`（74 金额 + 10 行逐项判定）、
`verify-key-amounts.py`（§6 核心金额关系 22/22 通过）。完整表格：`.scratch/four-chain-remediation-20261026/acceptance-table.md`。

分链路统计：

| 链路 | 执行状态 | 展示金额 | 明细行 | reason_explained | book_fact | not_applicable | missing_evidence |
|---|---|---:|---:|---:|---:|---:|---:|
| 居民门诊 0408 | complete | 19 | 6 | 15 | 6 | 4 | 0 |
| 居民门特 688 | complete | 17 | 2 | 13 | 3 | 3 | 0 |
| 职工门诊 000008 | partial | 19 | 1 | 10 | 6 | 1 | 3 |
| 职工门特 567 | complete | 19 | 1 | 16 | 3 | 1 | 0 |
| 合计 | | 74 | 10 | 54 | 18 | 9 | 3 |

### 5.1 逐项对照表（自动生成，交付要点为截取）

| 链路 | # | 展示字段 | 金额 | 字段 | 类型 | 状态 | 交付要点（自动截取） |
|---|---:|---|---:|---|---|---|---|
| 0408 | 1 | 费用总金额 | 3435.00 | T_FeeAll | explainable | reason_explained | 费用总金额 3435.00 元；本笔结算的全部费用合计，属费用口径，不等于医保报销金额。；费用明细合计＝复方丹参滴丸（第1行） 440.00 |
| 0408 | 2 | 个人支付总金额 | 1837.50 | T_SelfPayAll | explainable | reason_explained | 个人支付总金额 1837.50 元；本笔结算后由个人支付的总金额，属个人负担口径。；本次最终个人承担：最终个人承担＝居民起付线（分档） 0  |
| 0408 | 3 | 医疗保险范围内金额 | 3195.00 | T_FeeIn | explainable | reason_explained | 医疗保险范围内金额 3195.00 元；费用中属于医保目录范围内、参与待遇计算的金额，属费用口径。；医保内费用合计＝复方丹参滴丸（第1行）  |
| 0408 | 4 | 医疗保险范围外金额 | 240.00 | T_FeeOut | explainable | reason_explained | 医疗保险范围外金额 240.00 元；本单基本医保费用划分中的范围外金额，可能包含比例先行自付、超限价自付和全自费；最终个人负担还需结合本单 |
| 0408 | 5 | 个人支付自付（一）金额 | 1597.50 | T_SelfPay1 | explainable | reason_explained | 个人支付自付（一）金额 1597.50 元；医保范围内费用中按待遇政策由个人承担的部分（自付一），属个人负担口径。；本次自付一：个人支付自付 |
| 0408 | 6 | 个人支付自付（二）金额 | 180.00 | T_SelfPay2 | explainable | reason_explained | 个人支付自付（二）金额 180.00 元；部分项目按规定比例先行自付或超限价自付的金额（自付二），属个人负担口径；该金额已包含在医保范围外金 |
| 0408 | 7 | 起付金额 | 0.00 | T_FirstPay | explainable | reason_explained | 起付金额 0.00 元；起付线以下由个人先行承担的金额，属个人负担口径。；本次起付承担：居民起付线（分档）：交易前已累计 5159.00 元 |
| 0408 | 8 | 大额自付金额 | 1597.50 | T_BigSelfPay | explainable | reason_explained | 大额自付金额 1597.50 元；大额段费用中由个人承担的部分，属个人负担口径。；本次大额个人自付：大额自付（差额）＝报销基数（扣减后） 3 |
| 0408 | 9 | 大额超封顶金额 | 0.00 | bill.beyond_cap | observed_only | book_fact | 大额超封顶金额 0.00 元；超出大额基金封顶线的金额，属个人负担口径。；本单已有大额封顶标准与交易前累计输入；超封顶金额的费用归属未经确认 |
| 0408 | 10 | 基金支付金额 | 1597.50 | T_FundPay | observed_only | book_fact | 基金支付金额 1597.50 元；本笔医保基金支付合计，属基金支付口径。；账面勾稽：仅核对各分量关系，未独立重算；本笔基金支付全部来自「当次 |
| 0408 | 11 | 当次个人帐户支付金额 | 0.00 | T_PersonCountPay | observed_only | book_fact | 当次个人帐户支付金额 0.00 元；支付方式：以个人账户支付的金额；与个人支付总金额是同一笔钱的支付拆分，不重复相加。；仅账面列示，暂无独立 |
| 0408 | 12 | 当次门诊大额基金支付金额 | 1597.50 | T_BigPay | explainable | reason_explained | 当次门诊大额基金支付金额 1597.50 元；门诊大额基金支付金额，属基金支付口径。；本次大额支付：居民大额支付（封顶）＝较小值（最大值（取 |
| 0408 | 13 | 残疾军人补助支付金额 | 0.00 | T_JCPay | not_applicable | not_applicable | 残疾军人补助支付金额 0.00 元；残疾军人补助支付金额；居民医保无此待遇项目，正常应为不适用。；本单不符合该待遇条件，该项待遇不适用。；尚 |
| 0408 | 14 | 当次个人现金支付金额 | 1837.50 | T_CashPay | observed_only | book_fact | 当次个人现金支付金额 1837.50 元；支付方式：以现金支付的金额；与个人支付总金额是同一笔钱的支付拆分，不重复相加。；仅账面列示，暂无独 |
| 0408 | 15 | 补充保险支付金额 | 0.00 | T_BCPay | not_applicable | not_applicable | 补充保险支付金额 0.00 元；退休补充保险补助支付金额；居民医保无此待遇项目，正常应为不适用。；本单不符合该待遇条件，该项待遇不适用。；尚 |
| 0408 | 16 | 大病支付 | 0.00 | T_BigillPay | not_applicable | not_applicable | 大病支付 0.00 元；大病保险支付金额，属基金支付口径（二次保障）。；本单不符合该待遇条件，该项待遇不适用。；尚未取得独立计算或核对值，算 |
| 0408 | 17 | 救助支付 | 0.00 | NT_CivilPay | observed_only | book_fact | 救助支付 0.00 元；医疗（民政）救助支付金额，属基金支付口径（救助）。；内核居民门诊链未产出该字段的分解记录；救助金额仅作为基金合计恒等 |
| 0408 | 18 | 退役医疗费 | 0.00 | RETIRE_OFFICER_PAY | observed_only | book_fact | 退役医疗费 0.00 元；退役人员医疗费支付金额，属基金支付口径；按原单记录列示。；内核居民门诊链未产出该字段的分解记录；退役医疗费资格与待 |
| 0408 | 19 | 单位补充医疗保险（原公疗）支付金额 | 0.00 | T_OfficalPay | not_applicable | not_applicable | 单位补充医疗保险（原公疗）支付金额 0.00 元；单位补充医疗保险（原公费医疗）补助支付金额；居民医保无此待遇项目，正常应为不适用。；本单不 |
| 688 | 1 | 费用总金额 | 1187.00 | ZJE | explainable | reason_explained | 费用总金额 1187.00 元；本笔结算的全部费用合计，属费用口径，不等于医保报销金额。；费用明细合计＝注射用培美曲塞二钠（第1行） 699 |
| 688 | 2 | 个人支付总金额 | 0.00 | PERSON_PAYABLE | explainable | reason_explained | 个人支付总金额 0.00 元；本笔结算后由个人支付的总金额，属个人负担口径。；本次个人应付（对照现金与账户合计）：二次保障后个人应付＝补助后 |
| 688 | 3 | 医疗保险范围内金额 | 1117.10 | TSBYBN | explainable | reason_explained | 医疗保险范围内金额 1117.10 元；费用中属于医保目录范围内、参与待遇计算的金额，属费用口径。；医保内费用合计＝注射用培美曲塞二钠（第1 |
| 688 | 4 | 医疗保险范围外金额 | 69.90 | TSBYBW | explainable | reason_explained | 医疗保险范围外金额 69.90 元；本单基本医保费用划分中的范围外金额，可能包含比例先行自付、超限价自付和全自费；最终个人负担还需结合本单后 |
| 688 | 5 | 起付金额 | 0.0000 | YBNQFJE | explainable | reason_explained | 起付金额 0.00 元；起付线以下由个人先行承担的金额，属个人负担口径。；本次起付金额：居民门特起付线＝较小值（医保内费用 1117.10  |
| 688 | 6 | 个人支付自付（二）金额 | 69.90 | GRZIFTW | explainable | reason_explained | 个人支付自付（二）金额 69.90 元；部分项目按规定比例先行自付或超限价自付的金额（自付二），属个人负担口径；该金额已包含在医保范围外金额 |
| 688 | 7 | 个人支付自付（一）金额 | 279.2700 | GRZIF1 | explainable | reason_explained | 个人支付自付（一）金额；医保范围内由个人承担的自付一部分，为补助或二次保障前的计算构成，属个人负担口径。；个人支付自付（一）金额：该列在已核 |
| 688 | 8 | 门诊大额基金支付金额 | 837.83 | DEGWYZHF | explainable | reason_explained | 门诊大额基金支付金额 837.83 元；门诊大额基金支付金额，属基金支付口径。；本次基本医保基金支付：年度封顶余额（封顶线−交易前已支付）＝ |
| 688 | 9 | 大额自付金额 | 279.27 | DEGWYZIF | explainable | reason_explained | 大额自付金额 279.27 元；大额段费用中由个人承担的部分，属个人负担口径。；本次基本医保基金支付后自付：大额自付（差额）＝报销基数（扣减 |
| 688 | 10 | 补充保险支付金额 | 0.0000 | BCZHF | not_applicable | not_applicable | 补充保险支付金额 0.00 元；退休补充保险补助支付金额；居民医保无此待遇项目，正常应为不适用。；本单不符合该待遇条件，该项待遇不适用。；尚 |
| 688 | 11 | 残疾军人补助支付金额 | 0.0000 | JCZHF | not_applicable | not_applicable | 残疾军人补助支付金额 0.00 元；残疾军人补助支付金额；居民医保无此待遇项目，正常应为不适用。；本单不符合该待遇条件，该项待遇不适用。；尚 |
| 688 | 12 | 大病支付 | 226.9600 | BIG_ILL_PAY | explainable | reason_explained | 大病支付 226.96 元；大病保险支付金额，属基金支付口径（二次保障）。；本次大病保险支付（二次保障）：大病保险支付合计＝大病支付（医保内 |
| 688 | 13 | 救助支付 | 122.2100 | CIVIL_IN | explainable | reason_explained | 救助支付 122.21 元；医疗（民政）救助支付金额，属基金支付口径（救助）。；本次医疗救助支付：民政救助＝医保内分桶救助 97.74 元＋ |
| 688 | 14 | 当次个人帐户支付金额 | 0.00 | ZHZF | observed_only | book_fact | 当次个人帐户支付金额 0.00 元；支付方式：以个人账户支付的金额；与个人支付总金额是同一笔钱的支付拆分，不重复相加。；仅账面列示，暂无独立 |
| 688 | 15 | 当次个人现金支付金额 | 0.00 | XJZF | observed_only | book_fact | 当次个人现金支付金额 0.00 元；支付方式：以现金支付的金额；与个人支付总金额是同一笔钱的支付拆分，不重复相加。；仅账面列示，暂无独立计算 |
| 688 | 16 | 退役医疗费 | 0.0000 | RETIRE_OFFICER_PAY | observed_only | book_fact | 退役医疗费 0.00 元；退役人员医疗费支付金额，属基金支付口径；按原单记录列示。；内核未产出该字段的分解记录，仅按原单模板列示账面金额。 |
| 688 | 17 | 单位补充医疗保险（原公疗）支付金额 | 0.0000 | GFYLBCHBX | not_applicable | not_applicable | 单位补充医疗保险（原公疗）支付金额 0.00 元；单位补充医疗保险（原公费医疗）补助支付金额；居民医保无此待遇项目，正常应为不适用。；本单不 |
| 000008 | 1 | 费用总金额 | 3000.00 | T_FeeAll | explainable | reason_explained | 费用总金额 3000.00 元；本笔结算的全部费用合计，属费用口径，不等于医保报销金额。；费用明细合计＝注射用培美曲塞二钠（第1行） 300 |
| 000008 | 2 | 个人支付总金额 | 2580.00 | T_SelfPayAll | explainable | reason_explained | 个人支付总金额 2580.00 元；本笔结算后由个人支付的总金额，属个人负担口径。；本次最终个人承担：最终个人承担＝起付线拆分 1800.0 |
| 000008 | 3 | 医疗保险范围内金额 | 2400.00 | T_FeeIn | explainable | reason_explained | 医疗保险范围内金额 2400.00 元；费用中属于医保目录范围内、参与待遇计算的金额，属费用口径。；医保内费用合计＝注射用培美曲塞二钠（第1 |
| 000008 | 4 | 医疗保险范围外金额 | 600.00 | T_FeeOut | explainable | reason_explained | 医疗保险范围外金额 600.00 元；本单基本医保费用划分中的范围外金额，可能包含比例先行自付、超限价自付和全自费；最终个人负担还需结合本单 |
| 000008 | 5 | 个人支付自付（一）金额 | 1980.00 | T_SelfPay1 | explainable | reason_explained | 个人支付自付（一）金额 1980.00 元；医保范围内费用中按待遇政策由个人承担的部分（自付一），属个人负担口径。；本次自付一：个人支付自付 |
| 000008 | 6 | 个人支付自付（二）金额 | 600.00 | T_SelfPay2 | explainable | reason_explained | 个人支付自付（二）金额 600.00 元；部分项目按规定比例先行自付或超限价自付的金额（自付二），属个人负担口径；该金额已包含在医保范围外金 |
| 000008 | 7 | 起付金额 | 1800.00 | T_FirstPay | explainable | reason_explained | 起付金额 1800.00 元；起付线以下由个人先行承担的金额，属个人负担口径。；本次起付承担：起付线拆分＝较小值（医保内费用 2400.00 |
| 000008 | 8 | 大额自付金额 | 180.00 | T_BigSelfPay | explainable | reason_explained | 大额自付金额 180.00 元；大额段费用中由个人承担的部分，属个人负担口径。；本次大额个人自付：大额自付（差额）＝报销基数（扣减后） 60 |
| 000008 | 9 | 大额超封顶金额 | 0.00 | bill.beyond_cap | observed_only | book_fact | 大额超封顶金额 0.00 元；超出大额基金封顶线的金额，属个人负担口径。；模板未绑定计算目标（field_code 为空），内核未产出该字段 |
| 000008 | 10 | 基金支付金额 | 420.00 | T_FundPay | observed_only | book_fact | 基金支付金额 420.00 元；本笔医保基金支付合计，属基金支付口径。；账面勾稽：仅核对各分量关系，未独立重算；本笔基金支付全部来自「当次门 |
| 000008 | 11 | 当次个人帐户支付金额 | 2580.00 | T_PersonCountPay | observed_only | book_fact | 当次个人帐户支付金额 2580.00 元；支付方式：以个人账户支付的金额；与个人支付总金额是同一笔钱的支付拆分，不重复相加。；仅账面列示，暂 |
| 000008 | 12 | 当次门诊大额基金支付金额 | 420.00 | T_BigPay | explainable | reason_explained | 当次门诊大额基金支付金额 420.00 元；门诊大额医疗互助资金支付金额，属基金支付口径。；本次大额支付：基金累计2万元以内段基数＝较小值（ |
| 000008 | 13 | 残疾军人补助支付金额 | 0.00 | T_JCPay | missing | missing_evidence | 残疾军人补助支付金额 0.00 元；残疾军人补助支付金额，属基金支付口径（补助）。；仅账面列示，暂无独立计算记录。；尚未取得独立计算或核对值 |
| 000008 | 14 | 当次个人现金支付金额 | 0.00 | T_CashPay | observed_only | book_fact | 当次个人现金支付金额 0.00 元；支付方式：以现金支付的金额；与个人支付总金额是同一笔钱的支付拆分，不重复相加。；仅账面列示，暂无独立计算 |
| 000008 | 15 | 补充保险支付金额 | 0.00 | T_BCPay | not_applicable | not_applicable | 补充保险支付金额 0.00 元；退休补充保险补助支付金额，属基金支付口径（补助）。；本单不符合该待遇条件，该项待遇不适用。；尚未取得独立计算 |
| 000008 | 16 | 大病支付 | 0.00 | T_BigillPay | observed_only | book_fact | 大病支付 0.00 元；大病保险支付金额，属基金支付口径（二次保障）。；内核未产出该字段的分解记录，仅按原单模板列示账面金额。 |
| 000008 | 17 | 救助支付 | 0.00 | NT_CivilPay | observed_only | book_fact | 救助支付 0.00 元；医疗（民政）救助支付金额，属基金支付口径（救助）。；内核普通门诊链未产出该字段的分解记录；救助金额仅作为基金合计恒等 |
| 000008 | 18 | 退役医疗费 | 0.00 | RETIRE_OFFICER_PAY | missing | missing_evidence | 退役医疗费 0.00 元；退役人员医疗费支付金额，属基金支付口径；按原单记录列示。；仅账面列示，暂无独立计算记录。；尚未取得独立计算或核对值 |
| 000008 | 19 | 单位补充医疗保险（原公疗）支付金额 | 0.00 | T_OfficalPay | missing | missing_evidence | 单位补充医疗保险（原公疗）支付金额 0.00 元；单位补充医疗保险（原公费医疗）补助支付金额，属基金支付口径（补助）。；仅账面列示，暂无独立 |
| 567 | 1 | 费用总金额 | 6000.00 | ZJE | explainable | reason_explained | 费用总金额 6000.00 元；本笔结算的全部费用合计，属费用口径，不等于医保报销金额。；总费用（明细逐行合计）＝他克莫司胶囊（第1行） 6 |
| 567 | 2 | 个人支付总金额 | 0.00 | PERSON_PAYABLE | explainable | reason_explained | 个人支付总金额 0.00 元；本笔结算后由个人支付的总金额，属个人负担口径。；本次个人应付（对照现金与账户合计）：二次保障后个人应付＝补助后 |
| 567 | 3 | 医疗保险范围内金额 | 6000.00 | YBN | explainable | reason_explained | 医疗保险范围内金额 6000.00 元；费用中属于医保目录范围内、参与待遇计算的金额，属费用口径。；明细医保内费用合计＝他克莫司胶囊（第1行 |
| 567 | 4 | 医疗保险范围外金额 | 0.00 | YBW | explainable | reason_explained | 医疗保险范围外金额 0.00 元；本单基本医保费用划分中的范围外金额，可能包含比例先行自付、超限价自付和全自费；最终个人负担还需结合本单后续 |
| 567 | 5 | 起付金额 | 1300.0000 | YBNQFJE | explainable | reason_explained | 起付金额 1300.00 元；起付线以下由个人先行承担的金额，属个人负担口径。；本次起付金额：门特起付线拆分＝较小值（医保内费用 6000. |
| 567 | 6 | 个人支付自付（二）金额 | 0.00 | GRZIFTW | explainable | reason_explained | 个人支付自付（二）金额 0.00 元；部分项目按规定比例先行自付或超限价自付的金额（自付二），属个人负担口径；该金额已包含在医保范围外金额中 |
| 567 | 7 | 个人支付自付（一）金额 | 1723.0000 | GRZIF1 | explainable | reason_explained | 个人支付自付（一）金额；医保范围内由个人承担的自付一部分，为补助或二次保障前的计算构成，属个人负担口径。；个人支付自付（一）金额：该列在已核 |
| 567 | 8 | 统筹基金支付金额 | 4277.00 | TCZHF | explainable | reason_explained | 统筹基金支付金额 4277.00 元；门诊特殊病统筹基金支付金额，属基金支付口径。；本次统筹基金支付：统筹基金分段支付＝取整（本段费用 47 |
| 567 | 9 | 统筹自付金额 | 423.00 | TCZIF | explainable | reason_explained | 统筹自付金额 423.00 元；统筹段费用中由个人承担的部分，属个人负担口径。；本次统筹自付：统筹自付（支付后差额）＝统筹段报销基数 470 |
| 567 | 10 | 门诊大额基金支付金额 | 0.00 | DEGWYZHF | explainable | reason_explained | 门诊大额基金支付金额 0.00 元；门诊大额医疗互助资金支付金额，属基金支付口径。；本次大额互助支付：大额基金支付（未进入大额段）＝本笔大额 |
| 567 | 11 | 大额自付金额 | 0.00 | DEGWYZIF | explainable | reason_explained | 大额自付金额 0.00 元；大额段费用中由个人承担的部分，属个人负担口径。；本次大额自付：大额自付（未进入大额段）＝本笔大额段基数 0 元， |
| 567 | 12 | 补充保险支付金额 | 211.5000 | BCZHF | explainable | reason_explained | 补充保险支付金额 211.50 元；退休补充保险补助支付金额，属基金支付口径（补助）。；本次退休补助：退休补助（统筹段）＝取整（本段个人自付 |
| 567 | 13 | 残疾军人补助支付金额 | 1511.5000 | JCZHF | explainable | reason_explained | 残疾军人补助支付金额 1511.50 元；残疾军人补助支付金额，属基金支付口径（补助）。；本次军残补助：统筹剩余自付（扣除退休补助）＝统筹自 |
| 567 | 14 | 大病支付 | 0.0000 | BIG_ILL_PAY | explainable | reason_explained | 大病支付 0.00 元；大病保险支付金额，属基金支付口径（二次保障）。；本次大病保险支付（二次保障）：大病保险支付合计＝大病支付（医保内）  |
| 567 | 15 | 救助支付 | 0.0000 | CIVIL_IN | explainable | reason_explained | 救助支付 0.00 元；医疗（民政）救助支付金额，属基金支付口径（救助）。；本次医疗救助支付：民政救助＝医保内分桶救助 0.00 元＋比例先 |
| 567 | 16 | 当次个人帐户支付金额 | 0.00 | ZHZF | observed_only | book_fact | 当次个人帐户支付金额 0.00 元；支付方式：以个人账户支付的金额；与个人支付总金额是同一笔钱的支付拆分，不重复相加。；仅账面列示，暂无独立 |
| 567 | 17 | 当次个人现金支付金额 | 0.00 | XJZF | observed_only | book_fact | 当次个人现金支付金额 0.00 元；支付方式：以现金支付的金额；与个人支付总金额是同一笔钱的支付拆分，不重复相加。；仅账面列示，暂无独立计算 |
| 567 | 18 | 退役医疗费 | 0.0000 | RETIRE_OFFICER_PAY | observed_only | book_fact | 退役医疗费 0.00 元；退役人员医疗费支付金额，属基金支付口径；按原单记录列示。；内核未产出该字段的分解记录，仅按原单模板列示账面金额。 |
| 567 | 19 | 单位补充医疗保险（原公疗）支付金额 | 0.0000 | GFYLBCHBX | not_applicable | not_applicable | 单位补充医疗保险（原公疗）支付金额 0.00 元；单位补充医疗保险（原公费医疗）补助支付金额，属基金支付口径（补助）。；本单不符合该待遇条件 |

| 链路 | 行 | 项目 | 金额 | explainable | 状态 | 交付要点（自动截取） |
|---|---:|---|---:|---|---|---|
| 0408 | 1 | 复方丹参滴丸 | 440.0000 | True | reason_explained | 第 1 行复方丹参滴丸；本行费用 440.00 元＝单价 44.00 元×数量 10；本行全部纳入医保范围内：医保范围内 440.00 元、 |
| 0408 | 2 | 注射用培美曲塞二钠 | 400.0000 | True | reason_explained | 第 2 行注射用培美曲塞二钠；本行费用 400.00 元＝单价 100.00 元×数量 4；360.00 元进入医保范围内，40.00 元进 |
| 0408 | 3 | 罗沙司他胶囊 | 400.0000 | True | reason_explained | 第 3 行罗沙司他胶囊；本行费用 400.00 元＝单价 20.00 元×数量 20；360.00 元进入医保范围内，40.00 元进入医保 |
| 0408 | 4 | 小换药 | 60.0000 | True | reason_explained | 第 4 行小换药；本行费用 60.00 元＝单价 60.00 元×数量 1；本行全部由个人承担：医保范围内 0 元、医保范围外 60.00  |
| 0408 | 5 | 单焦点散光型白内障人工晶体 | 200.0000 | True | reason_explained | 第 5 行单焦点散光型白内障人工晶体；本行费用 200.00 元＝单价 100.00 元×数量 2；本行全部纳入医保范围内：医保范围内 20 |
| 0408 | 6 | 单焦点散光型白内障人工晶体 | 1935.0000 | True | reason_explained | 第 6 行单焦点散光型白内障人工晶体；本行费用 1935.00 元＝单价 1935.00 元×数量 1；本笔结算采用限价 1835.00 元 |
| 688 | 1 | 注射用培美曲塞二钠 | 699.0000 | True | reason_explained | 第 1 行注射用培美曲塞二钠；本行费用 699.00 元＝单价 233.00 元×数量 3；629.10 元进入医保范围内，69.90 元进 |
| 688 | 2 | 他克莫司胶囊 | 488.0000 | True | reason_explained | 第 2 行他克莫司胶囊；本行费用 488.00 元＝单价 122.00 元×数量 4；488.00 元进入医保范围内，0.00 元进入医保范 |
| 000008 | 1 | 注射用培美曲塞二钠 | 3000.0000 | True | reason_explained | 第 1 行注射用培美曲塞二钠；本行费用 3000.00 元＝单价 1000.00 元×数量 3；2400.00 元进入医保范围内，600.0 |
| 567 | 1 | 他克莫司胶囊 | 6000.0000 | True | reason_explained | 第 1 行他克莫司胶囊；本行费用 6000.00 元＝单价 300.00 元×数量 20；6000.00 元进入医保范围内，0.00 元进入 |

### 5.2 核心金额关系（在线复验 22/22）

- 0408：`3435.00=3195.00+240.00`、`180.00=40.00+40.00+100.00`、`1597.50=取整(3195.00×50%) 且不超封顶余额 2195.50`、`1837.50=0+240.00+1597.50`；
  两行人工晶体（200.00 / 1935.00、限价 1835.00）分行解释，未合并。
- 688：`1187.00=699.00+488.00`、`1117.10=629.10+488.00`、`837.83+279.27=1117.10`、`226.96=181.53+45.43`、`122.21=97.74+24.47`、
  `0.00=279.27+69.90−226.96−122.21`。
- 000008：`3000.00=2400.00+600.00`、`2400.00=1800.00+600.00`、`420.00=600.00×70%`、`180.00=600.00−420.00`、`1980.00=1800.00+180.00`；
  账户 2580.00 为支付渠道原单事实，不重复加到个人负担。
- 567：`6000.00=1300.00+4700.00`、`423.00=4700.00−4277.00`、`211.50=423.00×50%`、`1511.50=1300.00+423.00−211.50`；
  自付一 1723.00 标为“补助前计算构成（该列未维护，不作账面核对）”。

## 6. 尚未解决的缺口（诚实列明）

1. **职工门诊 000008 的 3 项缺证**：残疾军人补助、退役医疗费、单位补充医疗（原公疗）均为 0 元且内核无对应规则；
   正文只给原单金额并声明“未产出/待补全”，计为未完成原因解释，不并入通过率。
2. **跨院累计**：普通门诊交易前累计仍为“院内逐交易自证”口径，正文保留 `ACCUMULATION_CROSS_HOSPITAL_UNVERIFIED` 声明；
   依赖该累计的起付/大额金额属“本单口径正确、跨院未签核”。
3. **政策口径签核**：`ROUNDING_RULE_PENDING_CONFIRMATION` 等确认状态原样保留；本轮未做外部政策原文重核。
4. **未覆盖**：移动端表格结构化重设计、领域模型重构、数据迁移、源系统修数、并发压力测试；
   本轮未逐项重做 390px 截图人工复核（前端仅改数据接线，未改布局）。
5. 全部四单 `answer_status=partial` 是设计内结果：`calculation_checked=false` 来自存在不可独立核对字段（支付渠道/未维护列/缺证），
   不等于回答不可用；`may_claim_full_explanation` 仍为 false。

## 7. 回滚范围

- 代码：`model_explanation.py`（新文件，删除即回退到模型自由文本出口，同时删除 `policy_qa_routes.py` 对应接线）、
  `field_explanations.py`（新文件）、`public_view.py::_field_brief`、`followup_target.py`、`policy_qa_routes.py`
  （旧 GET 鉴权、缓存规则）、两个前端文件（命令选单/令牌）。
- 测试：本轮新增/改写的测试文件可整体回退（`test_acceptance_grading.py` 为新文件）。
- 无数据库迁移、无配置默认值变更；回滚不影响金额算法与公开契约版本。
