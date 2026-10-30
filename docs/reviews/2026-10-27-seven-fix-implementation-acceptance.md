# 结算解释七项缺陷整改验收（R1–R7）

日期：2026-10-27。任务书：[2026-10-27 七项修复任务书](2026-10-27-four-chain-seven-fix-implementation-brief.md)；
缺陷取证：[2026-10-26 整改后对抗性复审](2026-10-26-four-chain-remediation-recheck.md)。

**结论：R1–R7 七项全部按“先失败测试→修根因”完成，四链路 84 项目标验收 84/84 如实交付
（54 原因已解释 / 18 原单事实 / 9 结构性不适用 / 3 诚实缺证）。未修改金额内核、政策参数、
取整模式、累计/资格门控；三项 0 元缺口与跨院累计声明保留为未完成事实项。**

## 0. 阶段 0：固定独立预期

- 新增 `src/tests/fixtures/four_chain_acceptance.py`：84 个目标的**冻结预期**
  （目标 ID = `case.template.key` / `case.line.N`、金额、预期四态、必要构成数值与 token、
  必现来源、禁止项、缺项 marker）。来源为两次对抗性复审的逐项目标清单与已核实锚点
  （`.scratch/four-chain-review-20261026/field-inventory.md`、复审 §6），**不取自被测响应**。
- 新增 `src/tests/unit/runtime/policy_qa/fee_decomposition/test_acceptance_registry.py`：
  预期与当前展示模板一一对应（门诊两链在单元层比对；门特两链的运行时裁剪模板在验收脚本里比对），
  目标 ID 唯一、`explainable` 必须登记必要构成（否则配置报错）。
- 运行入口迁入仓库：`scripts/eval/four_chain_acceptance.py`（原 `.scratch` 脚本不再是唯一资产）。

## 1. 逐项结果与先红后绿证据

| 缺陷 | 改动文件/关键函数 | 新增正式用例 | 修复前失败摘要 | 修复后命令与结果 | 四单/浏览器证据 | 仍存边界 |
|---|---|---|---|---|---|---|
| **R1** 旧患者列表慢响应覆盖新患者候选 | `settlement-time-browser.tsx`：新增 `contextRef` 上下文代次 + `invalidateList()`；`load/handleLocate/handleSwitchPatient`、预设/日期变更、卸载全部使旧请求失效；成功/失败/finally 均校验代次与挂载状态 | `settlement-time-browser.test.tsx` A1/A2/A3/A4/A4b；`settlement-agent-workspace-browser-integration.test.tsx` A1 联合用例 | 新 5 例中 4 例红：旧列表晚到后重新出现在新患者列表、旧失败被展示、A→B→A 第一次响应被接受、卸载后仍发布候选 | `npx vitest run settlement-time-browser.test.tsx` → **14 passed**；联合用例 **3 passed** | 父组件 `SettlementAgentWorkspace` + 真实 `SettlementTimeBrowser` 挂载，仅 mock 网络/会话边界；deferred promise 精确控序 | 未做真实浏览器长延迟攻击（组件级真实父子组件已满足任务书最低要求） |
| **R6** 新会话丢候选 | `settlement-agent-workspace.tsx`：新增 `handleNewSession()`（保留患者/时段/候选，只清选单/解释/锚点/追问目标并作废旧解释响应）；页面按钮与 `@新会话` 复用同一入口；换人仍走 `handlePatientChange`（清候选） | 联合用例 A5/R6、A6；既有 `@换结算 命令链路` 5 例保持 | A5 红：新会话后同单命令提示“不在当前患者的候选结算单中”（数据未清但父层被清） | `npx vitest run settlement-agent-workspace*.test.tsx` → **13 passed** | 联合用例断言命令与点击使用同一链路、新 session，后续提问复用同 session/单号 | 无 |
| **R2** 正文全局小数压缩改坏公式 | `model_explanation.py`：删除整段 `re.sub(…:.2f)`；`_percent` 改为数值等价百分数；`_quantity_text`/单价/限价保留有效精度；`formula_text.trim_trailing_zeros` 只压缩“两位小数之外的纯 0”（3195.000000→3195.00，0.125/0.0005/2024.0101/12.34567 原样） | `test_model_explanation.py` B1（80×0.125=10）、B2（0.0005/版本/编码）、`test_acceptance_grading_r7.py` D9 | B1 红：正文输出“单价 80.00 元×数量 0.13”；B2 红：比例被压成 0.00、版本被改写 | `pytest …/fee_decomposition -q` → **789 passed** | 真实 0408 大额正文：`取整（基数 3195.00 元×比例 0.5），−交易前已支付 2304.50 元 … ＝1597.50 元`，金额两位、比例精度保留 | 高精度中间值仍以原精度展示（不四舍五入），属任务书允许口径 |
| **R3** 不可解释计算被旁路证据带入正文 | `model_explanation.py`：`build_target_evidence` 只装载 `explainable` 计算/采用档；`build_line_target_evidence` 作为**唯一共享证据入口**在 `explainable=False` 时清空公式/判定路径/限价/比例/备注；GRZIF1 `SELF_PAY_1_BOOK_COLUMN_UNMAINTAINED` 保留“自身终端构成”例外 | `test_model_explanation.py` B3（账面60/重算50）、B4（行439/候选440）、B6（mixed/cover_all）、GRZIF1 正例；`test_policy_qa_session_decomposition_api.py` 两个 SSE 用例断言最终公开正文 | B3/B4/B6 红：正文在“仅账面列示”后追加 `计算：…＝50.00 元`、行答案追加“本行全部纳入医保内：440.00 元” | 同上 Unit **789**；API **112 passed** | API SSE：`50.00 元`/`440.00` 不再出现，原单 `60.00`/`439.00` 与缺口仍在；688/567 GRZIF1 构成仍可见并带“不作账面核对” | 诊断候选公式不进入正文；任务书允许的独立诊断视图本轮未新增 |
| **R4** 项目名命中提前返回丢全覆盖/混合 | `model_explanation.py`：重写 `resolve_question_target` 为“先局部子句 → 再合并目标”；名称命中不再提前 return，`cover_all`/汇总字段统一合并为 cover_all/mixed；`_mixed_summary_codes` 取首行号前 + 末子句后 | `test_question_target_extension.py` C1（全单+项目名）、C2（字段+名称两种顺序）、C7（多行/同名） | C1/C2 红：`解释全部费用尤其<项目>` 只回该行；`<字段>和<项目>分别怎么算` 丢字段目标 | `pytest test_question_target_extension.py` → **41 passed** | 四链真实问法：`请解释全部费用，尤其是<首行项目>` 交付整单全部字段与全部行；`费用总金额和<项目>` / `<项目>…及费用总金额` 两种顺序均交付字段+行（`calculation_checked=true`） | 无 |
| **R5** 名称校验误拒 + 多行名称错配放过 | `model_explanation.py`：`_line_name_state` 按“引号 → 已知名称 → 名称槽剥离”判定；`_strip_name_terms` 按词长降序剥离请求前缀/属性/汇总字段词（修复“医保内”吃掉“医保内外”留“外”）；行号与名称**逐对**校验；列表编号入口共用同一规则 | `test_question_target_extension.py` C3/C4（礼貌前缀、数量单价问法）、C5（两行名称互换）、C6（未知名称/全部费用尤其错误行）、名称槽残留用例 | C3/C5/C6 红：`请解释第1行的医保内外` → “未找到名为『请解释』的项目”；两行名称互换仍 `calculation_checked=true`；`第1行阿莫西林的医保内外` 报“阿莫西林外” | 同上 **41 passed** | 真实：`请解释第1行的医保内外` 正常按行回答；`第1行B和第2行A` 返回 invalid 且 `calculation_checked=false`；未知名称提示“未找到名为「阿莫西林」” | 无 |
| **R7** 验收判定假通过 | `test_acceptance_grading.py`：`TargetRequirement` 增加 `key/required_values/required_tokens/required_sources/forbidden_tokens/gap_markers` + 配置自检；新增 `assess_target` 双轴（内容状态 / 是否如实交付）、`undelivered`；构成必须有运算环节且除目标金额外有数值（0=0＋0 允许） | `test_acceptance_grading_r7.py` D1–D10：无计算、错等式、其他金额、错字段/错来源、0 分支、泛泛缺项、运算符/行归属/删来源变异、正例、舍入变异、不可解释候选追加、同标签不同 ID | 新判定对六类假通过全部为 `missing_evidence`/未交付（任务书 D1–D7 场景） | `pytest test_acceptance_grading*.py test_acceptance_registry.py` → **27 passed** | 84 项目标按新判定重跑：**84/84 如实交付**，无模板增删目标 | 非锚点字段用结构构成判定；核心金额另有冻结锚点值 |

## 2. 逐层验证

| 层 | 命令 | 结果 |
|---|---|---|
| Unit（费用分解全部） | `pytest src/tests/unit/runtime/policy_qa/fee_decomposition -q` | **789 passed** |
| API | `test_policy_qa_routes.py` + `test_policy_qa_fee_decomposition_api.py` + `test_policy_qa_session_decomposition_api.py` | **112 passed** |
| Flow（policy-qa 四文件） | outpatient_settlement / pooling_self_pay / scalar_retrieval_baseline / session_lifecycle | **100 passed, 1 skipped** |
| Portal | `npx vitest run` | **739 passed / 5 failed（历史预存：settlement-benefit-summary 4、settlement-path-view 1，本轮未触碰）** |
| TypeScript | `npx tsc --noEmit` | 0 错误 |
| 静态检查 | `ruff check`（本轮改动文件） | 通过 |
| 真实服务 | `..\ws.ps1 restart issue-78`（8109/3109） | 健康；验收脚本按当前源码运行 |

## 3. 四链路 84 项验收（真实服务，当前源码）

脚本：`uv run python scripts/eval/four_chain_acceptance.py --out .scratch/four-chain-acceptance-20261027`
→ `problems=[]`、`delivered=84`。

| 链路 | 执行状态 | 目标数 | reason_explained | book_fact | not_applicable | missing_evidence |
|---|---|---:|---:|---:|---:|---:|
| 0408 居民门诊 | complete | 25（19+6） | 15 | 6 | 4 | 0 |
| 688 居民门特 | complete | 19（17+2） | 13 | 3 | 3 | 0 |
| 000008 职工门诊 | partial | 20（19+1） | 10 | 6 | 1 | 3 |
| 567 职工门特 | complete | 20（19+1） | 16 | 3 | 1 | 0 |
| 合计 | | **84** | **54** | **18** | **9** | **3** |

### 3.1 逐目标对照（独立预期 → 实际）

| 目标 ID | 金额 | 预期类型 | 内容状态 | 如实交付 | 未交付原因 |
|---|---:|---|---|---|---|
| 0408.fee_all | 3435.00 | explainable | reason_explained | True |  |
| 0408.personal_total | 1837.50 | explainable | reason_explained | True |  |
| 0408.fee_in | 3195.00 | explainable | reason_explained | True |  |
| 0408.fee_out | 240.00 | explainable | reason_explained | True |  |
| 0408.self_pay_1 | 1597.50 | explainable | reason_explained | True |  |
| 0408.self_pay_2 | 180.00 | explainable | reason_explained | True |  |
| 0408.first_pay | 0.00 | explainable | reason_explained | True |  |
| 0408.big_self_pay | 1597.50 | explainable | reason_explained | True |  |
| 0408.beyond_cap | 0.00 | observed_only | book_fact | True |  |
| 0408.fund_total | 1597.50 | observed_only | book_fact | True |  |
| 0408.account_pay | 0.00 | observed_only | book_fact | True |  |
| 0408.big_pay | 1597.50 | explainable | reason_explained | True |  |
| 0408.military_pay | 0.00 | not_applicable | not_applicable | True |  |
| 0408.cash_pay | 1837.50 | observed_only | book_fact | True |  |
| 0408.retire_pay | 0.00 | not_applicable | not_applicable | True |  |
| 0408.big_ill_pay | 0.00 | not_applicable | not_applicable | True |  |
| 0408.aid_pay | 0.00 | observed_only | book_fact | True |  |
| 0408.retire_officer_pay | 0.00 | observed_only | book_fact | True |  |
| 0408.official_pay | 0.00 | not_applicable | not_applicable | True |  |
| 0408.line.1 | 440.00 | explainable | reason_explained | True |  |
| 0408.line.2 | 400.00 | explainable | reason_explained | True |  |
| 0408.line.3 | 400.00 | explainable | reason_explained | True |  |
| 0408.line.4 | 60.00 | explainable | reason_explained | True |  |
| 0408.line.5 | 200.00 | explainable | reason_explained | True |  |
| 0408.line.6 | 1935.00 | explainable | reason_explained | True |  |
| 688.fee_all | 1187.00 | explainable | reason_explained | True |  |
| 688.personal_total | 0.00 | explainable | reason_explained | True |  |
| 688.fee_in | 1117.10 | explainable | reason_explained | True |  |
| 688.fee_out | 69.90 | explainable | reason_explained | True |  |
| 688.first_pay | 0.0000 | explainable | reason_explained | True |  |
| 688.self_pay_2 | 69.90 | explainable | reason_explained | True |  |
| 688.self_pay_1 | 279.2700 | explainable | reason_explained | True |  |
| 688.big_pay | 837.83 | explainable | reason_explained | True |  |
| 688.big_self_pay | 279.27 | explainable | reason_explained | True |  |
| 688.retire_pay | 0.0000 | not_applicable | not_applicable | True |  |
| 688.military_pay | 0.0000 | not_applicable | not_applicable | True |  |
| 688.big_ill_pay | 226.9600 | explainable | reason_explained | True |  |
| 688.aid_pay | 122.2100 | explainable | reason_explained | True |  |
| 688.account_pay | 0.00 | observed_only | book_fact | True |  |
| 688.cash_pay | 0.00 | observed_only | book_fact | True |  |
| 688.retire_officer_pay | 0.0000 | observed_only | book_fact | True |  |
| 688.official_pay | 0.0000 | not_applicable | not_applicable | True |  |
| 688.line.1 | 699.00 | explainable | reason_explained | True |  |
| 688.line.2 | 488.00 | explainable | reason_explained | True |  |
| 000008.fee_all | 3000.00 | explainable | reason_explained | True |  |
| 000008.personal_total | 2580.00 | explainable | reason_explained | True |  |
| 000008.fee_in | 2400.00 | explainable | reason_explained | True |  |
| 000008.fee_out | 600.00 | explainable | reason_explained | True |  |
| 000008.self_pay_1 | 1980.00 | explainable | reason_explained | True |  |
| 000008.self_pay_2 | 600.00 | explainable | reason_explained | True |  |
| 000008.first_pay | 1800.00 | explainable | reason_explained | True |  |
| 000008.big_self_pay | 180.00 | explainable | reason_explained | True |  |
| 000008.beyond_cap | 0.00 | observed_only | book_fact | True |  |
| 000008.fund_total | 420.00 | observed_only | book_fact | True |  |
| 000008.account_pay | 2580.00 | observed_only | book_fact | True |  |
| 000008.big_pay | 420.00 | explainable | reason_explained | True |  |
| 000008.military_pay | 0.00 | missing | missing_evidence | True |  |
| 000008.cash_pay | 0.00 | observed_only | book_fact | True |  |
| 000008.retire_pay | 0.00 | not_applicable | not_applicable | True |  |
| 000008.big_ill_pay | 0.00 | observed_only | book_fact | True |  |
| 000008.aid_pay | 0.00 | observed_only | book_fact | True |  |
| 000008.retire_officer_pay | 0.00 | missing | missing_evidence | True |  |
| 000008.official_pay | 0.00 | missing | missing_evidence | True |  |
| 000008.line.1 | 3000.00 | explainable | reason_explained | True |  |
| 567.fee_all | 6000.00 | explainable | reason_explained | True |  |
| 567.personal_total | 0.00 | explainable | reason_explained | True |  |
| 567.fee_in | 6000.00 | explainable | reason_explained | True |  |
| 567.fee_out | 0.00 | explainable | reason_explained | True |  |
| 567.first_pay | 1300.0000 | explainable | reason_explained | True |  |
| 567.self_pay_2 | 0.00 | explainable | reason_explained | True |  |
| 567.self_pay_1 | 1723.0000 | explainable | reason_explained | True |  |
| 567.pool_pay | 4277.00 | explainable | reason_explained | True |  |
| 567.pool_self | 423.00 | explainable | reason_explained | True |  |
| 567.big_pay | 0.00 | explainable | reason_explained | True |  |
| 567.big_self_pay | 0.00 | explainable | reason_explained | True |  |
| 567.retire_pay | 211.5000 | explainable | reason_explained | True |  |
| 567.military_pay | 1511.5000 | explainable | reason_explained | True |  |
| 567.big_ill_pay | 0.0000 | explainable | reason_explained | True |  |
| 567.aid_pay | 0.0000 | explainable | reason_explained | True |  |
| 567.account_pay | 0.00 | observed_only | book_fact | True |  |
| 567.cash_pay | 0.00 | observed_only | book_fact | True |  |
| 567.retire_officer_pay | 0.0000 | observed_only | book_fact | True |  |
| 567.official_pay | 0.0000 | not_applicable | not_applicable | True |  |
| 567.line.1 | 6000.00 | explainable | reason_explained | True |  |

### 3.2 问法探针（真实四链，`parse-probes.json`）

| 探针 | 结果 |
|---|---|
| 全单＋项目名（C1） | cover_all，交付整单字段+全部行，`calculation_checked=false`（含不可核对字段，诚实） |
| 字段＋名称 / 名称＋字段（C2） | 两种顺序均交付字段+行，`calculation_checked=true` |
| `请解释第1行的医保内外` / `第1行数量、单价和金额`（C3） | fee_line，正常回答 |
| `费用总金额以及第1行的医保内金额`（C4） | mixed，字段与行都交付 |
| 两行名称互换（C5） | invalid/越界提示，`calculation_checked=false` |
| 未知名（C6） | invalid，“未找到名为「阿莫西林」的项目” |
| 指代追问（C9） | 同 session 同单继承 mixed/字段目标；换单/新会话不继承（单测覆盖） |

## 4. 未完成项（如实列明）

1. **000008 三项 0 元事实缺口**：残疾军人补助（`DISABLED_VETERAN_STATUS_UNKNOWN`）、
   原公疗（`PMED_ELIGIBILITY_UNKNOWN`）、退役医疗费（`SETTLEMENT_FACT_ONLY`）——需接入经核实的
   源字段三态事实后再复用 `supplements.py`，本轮未改门控、未补默认值；验收计 `missing_evidence`（3 项）。
2. **跨院累计**：仍为院内逐交易自证口径，`ACCUMULATION_CROSS_HOSPITAL_UNVERIFIED` 与起付/分段边界继续声明。
3. **取整/政策口径签核**：`ROUNDING_RULE_PENDING_CONFIRMATION` 等状态原样保留，未重核外部政策原文。
4. **Portal 5 个历史失败**（benefit-summary 4、path-view 1）未在本轮收口，属文案定位与既有产品语义，
   本轮未改其断言（任务书列为本任务外）。
5. **浏览器真实设备验收**：A1/A5 用“真实父组件+真实子组件、仅 mock 网络/会话”的联合用例证明；
   未重跑 Playwright 桌面/390px 截图与触控/读屏。
6. **R2 高精度中间值**：公式内保留原精度（不做两位近似），这是任务书要求的口径，不是缺口。

## 5. 回滚范围

- R1/R6：`settlement-time-browser.tsx`（上下文代次/invalidate）、`settlement-agent-workspace.tsx`
  （`handleNewSession` 与命令/按钮接线）及两个前端测试文件；
- R2/R3：`model_explanation.py`（数值展示、证据资格门、GRZIF1 例外、去重）、
  `formula_text.py`（`trim_trailing_zeros`）、`public_view.py`（操作数/公式展示值压缩）、`fee_items` 相关断言；
- R4/R5：`model_explanation.py` 目标解析族（`resolve_question_target/_resolve_ordinal_target/
  _resolve_list_marker_target/_name_only_target/_line_name_state/_strip_name_terms`）；
- R7：`test_acceptance_grading*.py`、`test_acceptance_registry.py`、`src/tests/fixtures/four_chain_acceptance.py`、
  `scripts/eval/four_chain_acceptance.py`；
- 无数据库迁移、无配置默认值变更、无公开契约字段变更；删除上述新增文件即可回到整改前行为，
  金额内核与门控不受影响。

## 6. 测试资产清单

- 新增：`test_acceptance_grading_r7.py`（12）、`test_acceptance_registry.py`（8）、
  `settlement-agent-workspace-browser-integration.test.tsx`（3）、`src/tests/fixtures/four_chain_acceptance.py`、
  `scripts/eval/four_chain_acceptance.py`；
- 扩充：`test_acceptance_grading.py`、`test_model_explanation.py`（B1–B6、GRZIF1）、
  `test_question_target_extension.py`（C1–C9）、`test_policy_qa_session_decomposition_api.py`（SSE 正文）、
  `settlement-time-browser.test.tsx`（A1–A4b）。
