# 派工单 批次一（架构裁决·拆最小件/换pi实例）：view SQL + 四组静态 T1

执行者：本工作区新 pi 实例。规则：**起跑后 5 分钟内先提交一个占位/心跳 commit（空跑与慢跑一眼区分）**；完成后 commit+push 报 tip hash。

## 交付物
1. `docs/processing/outpatient_processed_view.sql` —— Create Or Alter View v_op_outpatient_processed 四字段（口径句 v4）:
   - 门诊有效结算笔数 = COUNT(DISTINCT T_TradeNo)
   - 门诊总费用 = SUM(T_FeeAll) ; 门诊统筹基金支付金额 = SUM(T_FundPay) ; 门诊个人支付金额 = SUM(T_SelfPayAll)
   - WHERE T_State IN (2,3) AND NP_Settle_State=1 AND T_HasRefundmented != 1 AND (T_PartialReturnFlag IS NULL OR T_PartialReturnFlag='')
        AND (T_CureType IN (<门诊档 int>) OR T_CureType IS NULL)  -- 空=通用门诊规则
2. 四组静态 T1（单测夹具，不连库）：①公式逐值×4 ②冲正/负数排除 ③跨险种 trade_no 去重键 ④勾稽恒等(总=统筹+个人)

## 验收（照 dispatch doc 断言，内容不变只分两批时序）
批次一 = 文件落地 + 四组自测绿；批次二（注册表接线+T2a+med_type 空档边界）活库后另行派。
