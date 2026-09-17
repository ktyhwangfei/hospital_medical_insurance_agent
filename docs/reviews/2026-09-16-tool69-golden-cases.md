# Tool-69 四问 Golden 用例集 V1.0（同型数据替代）

> **背景**：Issue #68 四个真实问题的原始单据不可得（需求方确认），按同型数据替代原则从当前 SQL Server 基线库（bjybdb）挖掘等价场景。本用例集是 D4 正确性 gate 的回归基准：每次工具/工作流改动后以 `TOOL69_LIVE_DB=1` 重跑 `test_tool69_golden_workflows.py`。
> **挖掘时间**：2026-09-16；**脱敏**：全程不输出身份原文，测试内动态取用。

## G-Q1 同患者同项目跨单费用差异（原型：同药三次报销比例不同）

同一患者在 **55 张住院结算单**中出现同码项目"小换药"（NATION_CODE `001206000040000`），金额存在差异。取三张差异单：

| djh | 入院 | 该项目总额 |
|---|---|---|
| 687 | 2024-09-25 | 1500.00 |
| 689 | 2024-09-25 | 900.00 |
| 691 | 2024-06-01 | 660.00 |

**预期**：`wf_settlement_reimbursement_diff`（settlement_ids=[687,689,691]）→ status=complete；comparison_count ≥ 1；all_match=False（数量差异命中）；answer 含"事实差异"与归因边界声明。

## G-Q2 门诊退药退费核对（原型：退一支胃镜麻药未退款反多扣 5 元）

原交易 `011100030X240914000007`（2024-09-14）→ 退费交易 `011100030X240914000008`（**-180.00，部分退费标志=1**，负数量明细含"注射用培美曲塞二钠 -6 支 -120 元"）+ 同日重开交易 `011100030X240914000009`（**+90.00**）。

**预期**：以该患者身份证（测试内自 o_Trade 动态获取，不落盘）+ visit_date=2024-09-14 调 `tool_get_refund_record` → refunded_count ≥ 2；records 同时含负金额退费（008）与重开（009），original_trade_no 均指向 007；uncertainties 含退费重算规则未接入声明。

## G-Q3 特病+大病+救助叠加（原型：血友病特病+低保二次报销个人支付偏高）

djh=**687**：特病登记 `tsb1=502`，住院分摊 `BIG_ILL_PAY=5161.16`、`CIVIL_IN=16756.09`（djh=689 同型：特病 503 + 大病 736.00 + 救助 15608.30）。

**预期**：`wf_benefit_stacking_attribution`（settlement_id=687）→ status=complete；分摊事实三值命中；uncertainties 含低保维度缺失声明（dbzbs 全空）。

## G-Q4 退费结算架构核验（原型：无痛肠胃镜退费三问：起付线/另有缴费/单据效力）

同 G-Q2 交易族：原交易 007 的起付线/年度累计事实（`T_FirstPay`、`TB_Year`、`TB_MZTimes`）随退费记录返回；同日"退费（008）+重开（009）"两单并存即"两张单据用哪张"的同型事实。

**预期**：退费记录携带 `original_first_pay/original_year/original_year_times` 字段（LEFT JOIN 原交易）；同日 ≥2 笔退费相关交易并存。

## 回归命令

```bash
TOOL69_LIVE_DB=1 python -m pytest src/tests/integration/api/test_tool69_golden_workflows.py -v
```

数据漂移口径：金额断言按步输出取值（不硬编码进 answer 字符串）；单据号缺失（库刷新）时用例 fail 并提示重新挖掘。
