# 结算解释 F1–F6 缺陷整改验收

日期：2026-10-27（第二轮）。依据：[七项修复对抗性复审](2026-10-27-seven-fix-adversarial-recheck.md) 的 F1–F6。
上一轮 R1/R2/R6 实现与回归测试保留未改。

**结论：F1–F6 逐项按“先失败测试→修根因”完成。Unit 832、API 114、Flow 100（1 skip）通过；
Portal 739 通过 + 5 个历史预存失败；TypeScript 0 错误；真实服务 84 项目标 84/84 如实交付
（54 原因已解释 / 18 原单事实 / 9 结构性不适用 / 3 诚实缺证），runner 退出码 0；
两份故意破坏的回放（探针不可用、增加未验收费用行）runner 退出码均为 1。**

## A 批：可信正文（F1＋F2）

### F1 · GRZIF1 按归属/终端类型/结果/依赖选择

| 项 | 内容 |
|---|---|
| 修改文件/函数 | `src/runtime/policy_qa/fee_decomposition/model_explanation.py`：新增 `_terminal_calculation()`（字段归属 + 终端公式类别 `self_pay_1_components_v1` + 结果=字段金额 + 依赖闭包全部 explainable/可解析），`build_target_evidence` 只依赖该函数，不再按 `calculations` 数组倒序取条；GRZIF1 无可信构成时追加“上游计算未核对或缺失，暂不展示构成算式” |
| 正式测试 ID | `test_model_explanation.py::test_f1_grzif1_terminal_is_not_chosen_by_array_order`、`::test_f1_grzif1_ignores_unrelated_inserted_records`、`::test_f1_grzif1_terminal_result_mismatch_keeps_facts_and_gap`、`::test_f1_grzif1_missing_upstream_keeps_facts_and_gap`、`::test_f1_grzif1_unexplained_upstream_keeps_facts_and_gap`、`::test_f1_grzif1_real_688_composition_survives_reversed_calculations`；SSE：`test_policy_qa_session_decomposition_api.py::TestGrzif1TerminalCompositionOverSse`（正序/倒序两参数） |
| 修复前失败断言 | 倒序后正文出现无关记录 `100.00`（`assert '100.00' not in answer` 失败）；终端结果不符/上游缺失/上游未算平时仍追加候选算式；真实 688 倒序后 `assert answers[0] == answers[1]` 与 `'不作账面核对' in answer` 失败（5 例红） |
| 修复后命令与结果 | `uv run pytest src/tests/unit/runtime/policy_qa/fee_decomposition/test_model_explanation.py -q -k f1_` → **7 passed**；`pytest .../test_policy_qa_session_decomposition_api.py -q` → **18 passed**（含 2 个 SSE 参数） |
| 四单证据 | 真实 688/567 GRZIF1 构成仍显示（`279.27＝0＋279.27`、`1723` 分量），均带“不作账面核对”边界（见 `.scratch/four-chain-acceptance-20261027c/acceptance-table.md`） |
| 仍存边界 | 未新增独立诊断视图；GRZIF1 允许的公式类别登记为单一常量，新增构成公式需同步登记 |

### F2 · 未算平行不得声明“单价×数量＝费用”

| 项 | 内容 |
|---|---|
| 修改文件/函数 | `model_explanation.py::_line_sentence`：仅当 `item.explainable` 且 `单价×数量 == 账面费用` 时写等式；否则并列展示“本行费用 X 元；原单单价 P 元、数量 Q”，不修改账面金额 |
| 正式测试 ID | `test_model_explanation.py::test_f2_unexplained_line_does_not_claim_equation`、`::test_f2_explained_line_keeps_valid_equation`、`::test_f2_line_with_mismatched_product_is_not_an_equation`、`::test_f2_mixed_and_cover_all_lines_have_no_false_equation` |
| 修复前失败断言 | `assert '＝单价' not in answer` 失败（未算平行输出 `11.00 元＝单价 80 元×数量 0.125`）；mixed/cover_all 同样失败（3 例红） |
| 修复后命令与结果 | `pytest ... -q -k f2_` → **4 passed**；正例 `10.00 元＝单价 80 元×数量 0.125` 保留 |
| 四单证据 | 688 第1行、000008 第1行、567 第1行的 `费用＝单价×数量` 均为真实成立等式；0408 第6行限价行仍显示限价口径 |
| 仍存边界 | 没有登记“取整节点”的展示（当前行内核无取整等式）；如需展示取整需另行登记公式 |

## B 批：统一问题定位（F3＋F4）

### F3 · 局部子句先绑定再统一合并

| 项 | 内容 |
|---|---|
| 修改文件/函数 | `model_explanation.py`：`resolve_question_target` 重构为“收集行出现 → 逐次局部绑定 → 合并”；新增 `_expand_ordinal_occurrences`、`_merge_line_targets`、`_scope_texts`、`_strip_local_attributes`（整单口径词后的属性不当行属性剥离）、`_named_scope_text`（名称问句只去掉名称及其紧邻属性）；行号/列表编号/名称共用 `_merge_line_targets` |
| 正式测试 ID | `test_question_target_extension.py::test_f3_summary_field_between_two_line_clauses_is_kept`、`::test_f3_line_attribute_and_explicit_whole_statement_field_coexist`、`::test_f3_list_marker_with_cover_all_keeps_full_coverage`、`::test_f3_named_item_attribute_question_does_not_add_whole_statement`、`::test_f3_named_item_with_summary_field_still_mixes` |
| 修复前失败断言 | 中间汇总字段丢失（`target.kind == 'mixed'` 失败）；`整单医保内` 被删（`'T_FeeIn' in field_codes` 失败）；列表编号+全覆盖只答单行；名称+行属性误加整单目标（4 例红，1 例原本通过） |
| 修复后命令与结果 | `pytest .../test_question_target_extension.py -q` → **50 passed** |
| 四单证据 | 新增探针（真实 SSE）全部通过：`费用总金额和<首行项目>分别怎么算`、`请解释全部费用，尤其是1. <项目>`、`第1行<项目>的医保内金额是多少`（不带整单金额）、`第1行医保内金额以及整单医保内金额`（两个目标都交付）、`请解释第1行的医保内外`；字段与费用行集合与冻结预期一致 |
| 仍存边界 | 名称槽判定仍是有限语法（请求/属性/问句词），未做通用 NLP；未登记录入其它语言变体 |

### F4 · 正常问句不再当药名，重复行号冲突澄清

| 项 | 内容 |
|---|---|
| 修改文件/函数 | `model_explanation.py`：新增 `_claimed_name_from_clause`（只在子句开头名称槽取候选，遇到请求/属性/问句词即结束，起始即停用词则不当作名称）替代“删完停用词剩余汉字即药名”；`_merge_line_targets` 按**每次**行号出现先校验再合并，同一行号不同名称返回 `_conflict_line_target` 澄清 |
| 正式测试 ID | `test_question_target_extension.py::test_f4_plain_questions_are_not_item_names`、`::test_f4_repeated_line_with_conflicting_names_is_clarified`、`::test_f4_repeated_line_with_same_name_is_deduped`、`::test_f4_unknown_and_swapped_names_still_rejected` |
| 修复前失败断言 | `第1行是怎么计算的？`/`报销比例`/`全部纳入医保内` 被判 invalid（`target.kind == 'fee_line'` 失败）；同一行号冲突名称仍回答第一行（`kind == 'invalid'` 失败，2 例红） |
| 修复后命令与结果 | 同上 `test_question_target_extension.py` **50 passed**；未知名/两行互换/越界拒绝测试保留 |
| 四单证据 | 探针 `请解释第1行的医保内外` 正常回答；`第1行<第2行项目>和第2行<第1行项目>` 返回 unavailable 且 `calculation_checked=false`；`第1行阿莫西林` 返回“未找到名为「阿莫西林」的项目” |
| 仍存边界 | 冲突提示为确定性澄清文案，不提供交互式消歧 UI |

## C 批：独立验收（F5＋F6）

### F5 · 受控算式独立 Decimal 核验 + 正式冻结预期

| 项 | 内容 |
|---|---|
| 修改文件/函数 | `test_acceptance_grading.py`：新增受控表达式解析器 `_EquationParser`/`evaluate_controlled_equations`（+ - × ÷、括号、百分比、`取整`/`较小值`/`最大值`/min/max），`assess_target` 增加算术门（每题式必须成立且至少一条落在目标金额；0 元目标允许“本次未发生 + 分支输入”）、无计算标记（`暂无计算记录` 等）、来源门（`required_sources` 或 `source_record`）；`TargetRequirement.check` 要求 explainable 同时登记构成与来源；`src/tests/fixtures/four_chain_acceptance.py` 为 54 个 explainable 目标登记独立分量值与来源（政策标题或原单事实） |
| 正式测试 ID | `test_acceptance_arithmetic.py::test_arithmetic_checks_accept_correct_equation`、`::test_arithmetic_checks_reject_wrong_equations`（4 参数）、`::test_max_min_round_chain_is_evaluated_independently`、`::test_no_computation_marker_blocks_reason_explained`、`::test_zero_identity_and_book_facts_still_classified_correctly`、`::test_explainable_requirement_must_register_composition_and_source`、`::test_source_must_be_from_this_response`、`::test_formal_expectations_reject_reviewed_false_answers`（5 参数，使用正式冻结表）、`::test_formal_expectations_accept_recorded_correct_answers`；runner 侧 `test_acceptance_runner.py::test_replay_rejects_wrong_equations_in_official_recording` |
| 修复前失败断言 | 复审报告已复现：旧判定下 5 个错误正文全部 `reason_explained/delivered=True`（`3435＋1＝3435`、`3195－1＝3195`、`×90%`、加空格的错序、`暂无计算`旁放算式）；本轮正式断言对 5 例均要求 `status == missing_evidence` 且 `delivered is False`，同时保留 `0＝0＋0`、原单事实、不适用、诚实缺证的正确分类 |
| 修复后命令与结果 | `pytest .../test_acceptance_arithmetic.py -q` → **17 passed**；关闭算术门时这些断言会失败（D 组反例） |
| 四单证据 | 84 项重新判定：54/18/9/3，其中 0408 封顶式 `较小值（最大值（取整（3195.00×50%），-2304.50），最大值（4500.00-2304.50，0））＝1597.50` 由解析器独立复算通过；`×90%` 变异被拒 |
| 仍存边界 | 解析器覆盖受控渲染器语法（含中文函数名/百分比/括号），不是通用数学解析器；未覆盖任意自然语言 |

### F6 · 验收脚本检查完整集合与探针

| 项 | 内容 |
|---|---|
| 修改文件/函数 | `scripts/eval/four_chain_acceptance.py`：`panel_problems` 比对展示字段 `(key, field_code)` 与费用行 `(line_id, item_name, total_fee)` 的完整有序集合（重复/新增/遗漏/交换均失败）；`probe_questions`/`probe_problems` 断言真实“字段＋项目名/整单＋行/名称错误”问题（answer_status、calculation_checked、整单与本行金额、错误定位必须 unavailable）；`--record`/`--replay` 离线回放，失败进入 `problems` 并返回 1 |
| 正式测试 ID | `test_acceptance_runner.py`：`test_replay_accepts_recorded_correct_responses`、`test_replay_rejects_unavailable_probes`、`test_replay_rejects_extra_unverified_fee_line`、`test_replay_rejects_missing_and_swapped_fee_lines`、`test_replay_rejects_missing_display_field`、`test_replay_rejects_wrong_equations_in_official_recording`、`test_probe_questions_use_real_item_names`；回放夹具 `src/tests/fixtures/four_chain_acceptance_recording/recording.json`（脱敏，115 KB） |
| 修复前失败断言 | 复审已复现两变异：探针全 unavailable 仍 84/84 退出 0；面板追加未验收行仍退出 0。本轮测试对这两种回放断言 `code == 1`，正确回放断言 `code == 0` |
| 修复后命令与结果 | `pytest .../test_acceptance_runner.py -q` → **7 passed**；CLI 实测：正确回放 `--replay` → **exit 0**；`bad-probes` 变异 → **exit 1**；`extra-line` 变异 → **exit 1** |
| 四单证据 | 真实运行 `--record`：84/84、54/18/9/3、`problems=[]`、exit 0；模板字段 key/field_code 与费用行 line_id/项目/金额集合一致 |
| 仍存边界 | 离线回放是本次真实响应的脱敏快照，重新录制需真实服务；探针断言绑定当前公开契约字段 |

## 验证汇总

| 层 | 命令 | 结果 |
|---|---|---|
| Unit（fee_decomposition） | `pytest src/tests/unit/runtime/policy_qa/fee_decomposition -q` | **831 passed** |
| API | routes + fee-decomposition + session-decomposition | **114 passed** |
| Flow | policy-qa 四文件 | **100 passed, 1 skipped** |
| Portal | `npx vitest run` | **739 passed / 5 failed**（历史预存：settlement-benefit-summary 4、settlement-path-view 1） |
| TypeScript | `npx tsc --noEmit` | 0 错误 |
| 静态检查 | `ruff check`（本轮文件） | 通过 |
| 真实验收 | `scripts/eval/four_chain_acceptance.py --record …` | **84/84 交付，problems=[]，exit 0** |
| 故意破坏回放 | 探针 unavailable / 增加未验收行 | **exit 1 / exit 1** |

## 84 项目标结果（真实服务）

| 目标 ID | 金额 | 预期类型 | 内容状态 | 如实交付 |
|---|---:|---|---|---|
| 0408.fee_all | 3435.00 | explainable | reason_explained | True |
| 0408.personal_total | 1837.50 | explainable | reason_explained | True |
| 0408.fee_in | 3195.00 | explainable | reason_explained | True |
| 0408.fee_out | 240.00 | explainable | reason_explained | True |
| 0408.self_pay_1 | 1597.50 | explainable | reason_explained | True |
| 0408.self_pay_2 | 180.00 | explainable | reason_explained | True |
| 0408.first_pay | 0.00 | explainable | reason_explained | True |
| 0408.big_self_pay | 1597.50 | explainable | reason_explained | True |
| 0408.beyond_cap | 0.00 | observed_only | book_fact | True |
| 0408.fund_total | 1597.50 | observed_only | book_fact | True |
| 0408.account_pay | 0.00 | observed_only | book_fact | True |
| 0408.big_pay | 1597.50 | explainable | reason_explained | True |
| 0408.military_pay | 0.00 | not_applicable | not_applicable | True |
| 0408.cash_pay | 1837.50 | observed_only | book_fact | True |
| 0408.retire_pay | 0.00 | not_applicable | not_applicable | True |
| 0408.big_ill_pay | 0.00 | not_applicable | not_applicable | True |
| 0408.aid_pay | 0.00 | observed_only | book_fact | True |
| 0408.retire_officer_pay | 0.00 | observed_only | book_fact | True |
| 0408.official_pay | 0.00 | not_applicable | not_applicable | True |
| 0408.line.1 | 440.00 | explainable | reason_explained | True |
| 0408.line.2 | 400.00 | explainable | reason_explained | True |
| 0408.line.3 | 400.00 | explainable | reason_explained | True |
| 0408.line.4 | 60.00 | explainable | reason_explained | True |
| 0408.line.5 | 200.00 | explainable | reason_explained | True |
| 0408.line.6 | 1935.00 | explainable | reason_explained | True |
| 688.fee_all | 1187.00 | explainable | reason_explained | True |
| 688.personal_total | 0.00 | explainable | reason_explained | True |
| 688.fee_in | 1117.10 | explainable | reason_explained | True |
| 688.fee_out | 69.90 | explainable | reason_explained | True |
| 688.first_pay | 0.0000 | explainable | reason_explained | True |
| 688.self_pay_2 | 69.90 | explainable | reason_explained | True |
| 688.self_pay_1 | 279.2700 | explainable | reason_explained | True |
| 688.big_pay | 837.83 | explainable | reason_explained | True |
| 688.big_self_pay | 279.27 | explainable | reason_explained | True |
| 688.retire_pay | 0.0000 | not_applicable | not_applicable | True |
| 688.military_pay | 0.0000 | not_applicable | not_applicable | True |
| 688.big_ill_pay | 226.9600 | explainable | reason_explained | True |
| 688.aid_pay | 122.2100 | explainable | reason_explained | True |
| 688.account_pay | 0.00 | observed_only | book_fact | True |
| 688.cash_pay | 0.00 | observed_only | book_fact | True |
| 688.retire_officer_pay | 0.0000 | observed_only | book_fact | True |
| 688.official_pay | 0.0000 | not_applicable | not_applicable | True |
| 688.line.1 | 699.00 | explainable | reason_explained | True |
| 688.line.2 | 488.00 | explainable | reason_explained | True |
| 000008.fee_all | 3000.00 | explainable | reason_explained | True |
| 000008.personal_total | 2580.00 | explainable | reason_explained | True |
| 000008.fee_in | 2400.00 | explainable | reason_explained | True |
| 000008.fee_out | 600.00 | explainable | reason_explained | True |
| 000008.self_pay_1 | 1980.00 | explainable | reason_explained | True |
| 000008.self_pay_2 | 600.00 | explainable | reason_explained | True |
| 000008.first_pay | 1800.00 | explainable | reason_explained | True |
| 000008.big_self_pay | 180.00 | explainable | reason_explained | True |
| 000008.beyond_cap | 0.00 | observed_only | book_fact | True |
| 000008.fund_total | 420.00 | observed_only | book_fact | True |
| 000008.account_pay | 2580.00 | observed_only | book_fact | True |
| 000008.big_pay | 420.00 | explainable | reason_explained | True |
| 000008.military_pay | 0.00 | missing | missing_evidence | True |
| 000008.cash_pay | 0.00 | observed_only | book_fact | True |
| 000008.retire_pay | 0.00 | not_applicable | not_applicable | True |
| 000008.big_ill_pay | 0.00 | observed_only | book_fact | True |
| 000008.aid_pay | 0.00 | observed_only | book_fact | True |
| 000008.retire_officer_pay | 0.00 | missing | missing_evidence | True |
| 000008.official_pay | 0.00 | missing | missing_evidence | True |
| 000008.line.1 | 3000.00 | explainable | reason_explained | True |
| 567.fee_all | 6000.00 | explainable | reason_explained | True |
| 567.personal_total | 0.00 | explainable | reason_explained | True |
| 567.fee_in | 6000.00 | explainable | reason_explained | True |
| 567.fee_out | 0.00 | explainable | reason_explained | True |
| 567.first_pay | 1300.0000 | explainable | reason_explained | True |
| 567.self_pay_2 | 0.00 | explainable | reason_explained | True |
| 567.self_pay_1 | 1723.0000 | explainable | reason_explained | True |
| 567.pool_pay | 4277.00 | explainable | reason_explained | True |
| 567.pool_self | 423.00 | explainable | reason_explained | True |
| 567.big_pay | 0.00 | explainable | reason_explained | True |
| 567.big_self_pay | 0.00 | explainable | reason_explained | True |
| 567.retire_pay | 211.5000 | explainable | reason_explained | True |
| 567.military_pay | 1511.5000 | explainable | reason_explained | True |
| 567.big_ill_pay | 0.0000 | explainable | reason_explained | True |
| 567.aid_pay | 0.0000 | explainable | reason_explained | True |
| 567.account_pay | 0.00 | observed_only | book_fact | True |
| 567.cash_pay | 0.00 | observed_only | book_fact | True |
| 567.retire_officer_pay | 0.0000 | observed_only | book_fact | True |
| 567.official_pay | 0.0000 | not_applicable | not_applicable | True |
| 567.line.1 | 6000.00 | explainable | reason_explained | True |

## 仍未解决

1. 000008 军残/原公疗资格未知、退役医疗费仅原单事实（3 项 `missing_evidence`），需外部事实接入。
2. 跨院累计（`ACCUMULATION_CROSS_HOSPITAL_UNVERIFIED`）与取整/政策口径签核保留原状。
3. Portal 5 个历史失败（benefit-summary 4、path-view 1）未在本轮收口；未重跑真实浏览器/移动端截图。
4. F1 构成公式类别、F5 受控语法均为有限登记集合，新增公式需同步登记（不建议放宽为通用解析器）。

## 回滚范围

- 生产：`model_explanation.py`（`_terminal_calculation`、`_line_sentence`、目标解析族）、`formula_text.trim_trailing_zeros` 调用点（如需一并回退）；
- 验收：`src/tests/fixtures/four_chain_acceptance.py`、`src/tests/fixtures/four_chain_acceptance_recording/`、`scripts/eval/four_chain_acceptance.py`、`test_acceptance_*.py`；
- 无数据库迁移、无配置默认值变更、无公开契约字段变更；金额内核与门控未动。
