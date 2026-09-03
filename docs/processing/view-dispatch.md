# 派工单（王飞新规·数据转派）: #62 加工字段 view + 加工注册表

执行者: 本工作区 pi 智能体(默认模型)。完成后 push, 报数据。

## 逻辑(口径句 v4 已签核, 数据/知识定稿)
公共外过滤:
  T_State IN (2,3)                        -- 有效结算档(中心端完成/同步)
  AND NP_Settle_State = 1                 -- 国家平台已受理(二级确认)
  AND T_HasRefundmented != 1              -- 非已退费
  AND T_PartialReturnFlag != '1'          -- 非部分退费红冲
  AND T_CureType IN (<门诊档 int 值>) OR med_type 空串=通用门诊规则   -- 注: 见口径句 med_type 语义; T_CureType 为 int, 空=通用(按源分布收)
  AND (负数冲正由 T_State 正档已排除)

4 字段:
  1. 门诊有效结算笔数 = COUNT(DISTINCT trade_no)  (去重键 trade_no,insu_type)
  2. 门诊总费用 = SUM(T_FeeAll)
  3. 门诊统筹基金支付金额 = SUM(T_FundPay)
  4. 门诊个人支付金额 = SUM(T_SelfPayAll)

```sql
CREATE OR ALTER VIEW v_op_outpatient_processed AS
SELECT
  COUNT(DISTINCT tr.T_TradeNo)                    AS op_valid_settle_count,
  SUM(tr.T_FeeAll)                               AS op_total_fee,
  SUM(tr.T_FundPay)                              AS op_fund_pay,
  SUM(tr.T_SelfPayAll)                           AS op_self_pay
FROM o_Trade AS tr
WHERE tr.T_State IN (2,3)
  AND tr.NP_Settle_State = 1
  AND tr.T_HasRefundmented != 1
  AND (tr.T_PartialReturnFlag IS NULL OR tr.T_PartialReturnFlag = '')
  AND (tr.T_CureType IN (<门诊档 int 值>) OR tr.T_CureType IS NULL);  -- 空=通用门诊规则
```

## 附加交付
- 加工注册表(数据侧结构, 可先在 docs/processing/registry.yaml 落结构): 4 字段名/算子/来源字段/口径句/去重键/物化策略(view)/签核状态(已过).
- 若有门诊档位/T_CureType 具体 int 值和“空值=通用”依据文件, 一并写入 docs 留证。

## 验收
- view SQL 与上方逻辑一致; 加工注册表含 4 字段完整定义; commit+push 报 tip。
