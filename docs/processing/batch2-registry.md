# 派工单 批次二（活库阶段，v4 定稿后派）：加工注册表接线 + T2a + 存量数值一致 + med_type 边界

执行者：本工作区 pi 实例（活库可用）。心跳：5 分钟内先占位 commit。

## 输入（已定稿）
- 口径句 v4（知识定稿，见 batch1 与 #62 comment）：4 字段公式（笔数=COUNT(DISTINCT T_TradeNo)/总=SUM(T_FeeAll)/统筹=SUM(T_FundPay)/个人=SUM(T_SelfPayAll)）
- 统一过滤：T_State IN (2,3) AND MZ_CURE_TYPE IN (11,17,18,19) AND T_HasRefundmented != 1 AND T_PartialReturnFlag != '1'

## 交付物
1. **加工注册表接线**：docs/processing/registry.yaml（或同义定义）——4 字段：名称/算子/来源字段/口径句(v4)/去重键/物化策略(view)/签核状态=已过；并确保语义层可引用（view 挂语义 layer/指标注册，供受控问数消费）
2. **T2a（活库）**：连通/权限/存量数值一致（view 结果 vs 源直接聚合一致）/med_type 空档边界（MZ_CURE_TYPE IN 4 码 vs 空=通用门诊按源分布，空值行纳入与否按口径句：若源无空值行则该边界恒不触发，写注释而非加分支）

## 验收
- 注册表含 4 字段完整定义；T2a 活库断言（连通/权限/存量一致/med_type 边界）随测试九组剩余项；commit+push 报 tip hash
