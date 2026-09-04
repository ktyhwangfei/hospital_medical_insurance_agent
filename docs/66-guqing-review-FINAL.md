# 门诊 66 字母字段 → 中文定名·审结终稿（知识·顾清）

审阅基准：数据侧 discovery 实测 file（417de59）。终稿以每字段 **discovery 原始中文语义**为准落中文显示名，不按字段名字面猜。
三点口径约定先行：
- TA_=「交易后(结算后)…」累计、TB_=「交易前…」累计（差异由各条语义后缀自证）。
- 以下是"中文显示名"，不是指标发布口径句；发布每字段前仍需数据侧在 definition 补记账/计算口径（见尾）。
- 枚举字段给的是语义名，值档位是否齐全由数据侧字典面校验（多数仍只到枚举类别，不阻碍显示名落地）。

## A. 语义修正·三处陷阱（原字面译错，被 discovery 纠正）
| 字段 | 数据早期字面 | discovery 实测正确语义 | 定名 |
|---|---|---|---|
| PN_PersonCount | "就诊人次"(人名误导) | 交易前个人账户余额 | 交易前个人账户余额 |
| T_PersonCountAfter | "结算后人次" | 当次交易后个人账户余额 | 当次交易后个人账户余额 |
| T_pneno | "就诊编号" | 生育备案号 | 生育备案号 |
说明：PN_PersonCount/T_PersonCountAfter 名字含 "Person" 极易被当“人次”指标，一旦当人次发布，将与 insured_encounter_count 就诊人次口径冲突并毒化次均计算——**绝不可按字面进发布口径**。这三处已修正。

## B. 中文化对照（66）
### Count(1) FeeItem(2)
Count→总数量
FeeItem_SelfPay2→个人自付二
FeeItem_State→收费明细状态

### FeeType(1) ItemCode(1) ItemType(1) NP(1)
FeeType→费用类型
ItemCode→子项目医保编码
ItemType→子项目类型
NP_Settle_State→国家平台结算状态

### NT(8)
NT_AgencySumPay→经办机构支付总额
NT_AllSelfPayFlag→全额垫付标志
NT_BasicPay→基本医疗保险统筹基金支付金额
NT_CivilPay→民政补助基金支付金额
NT_OtherPay→其他基金支付金额
NT_OUT2_PRICE→超限价自付费用
NT_OUT2_SCALE→乙类先自付费用合计
NT_ReTradeFlag→退费交易重收标识

### P(5)
P_CivilFlag→民政救助标识
P_CivilType→民政救助类别
P_HospFlag→医院标识(定点范围标识)
P_Official→是否公务员(身份档位)
P_retirementflag→退休标识

### PN(7)
PN_ChronicCode→慢性病代号
PN_ChronicFlag→慢性病标识
PN_IsChronicHosp→慢性病就医医院标识
PN_NationFundType→险种类型
PN_NoRightReason→医保未结算原因
PN_OutTransaction→异地结算人员标识
PN_PersonCount→交易前个人账户余额

### RETIRE(1) SETL(1) StandardCode(1)
RETIRE_OFFICER_FLAG→退役军人标识
SETL_DATE→国家平台结算时间
StandardCode→国家项目编码

### T(11)
T_BeyondBig→超门诊大额封顶部分
T_CompHospFlag→医照医院范围标识
T_DiagType→交易类型
T_GFBelongFlag→医照人员属地标识
T_HasRefundmented→是否退费交易
T_OraginalTradeDate→原交易时间
T_OraginalTradeNo→原交易号
T_PartialReturnFlag→部分退费红冲交易标识
T_PersonCountAfter→当次交易后个人账户余额
T_pneno→生育备案号
T_SpSetlFlag→特殊结算标识

### TA(12) = 医保内各基金/大额·交易后累计
TA_BeyondFeeIn→结算后门诊超封顶部分
TA_BigillComm→交易后大病医保内费用累计
TA_BigillPay→交易后大病保障累计支付
TA_BigPay→年度门诊大额支付累计
TA_BigPayL1→一级医院城乡居民年度门诊大额支付累计(交易后)
TA_CivilComm→交易后民政救助医保内费用累计
TA_CivilPay→交易后民政救助累计支付
TA_FeeAfterBig→年度超门诊大额封顶后医保内费用累计(交易后)
TA_FeeAfterBigL1→一级医院城乡居民年度超大额封顶后医保内费用累计(交易后)
TA_FeeIn→年度门诊医保内费用累计(交易后)
TA_FeeInL1→一级医院城乡居民年度门诊医保内费用累计(交易后)
TA_MZTimes→门诊结算次数(交易后)

### TB(12) = 对应·交易前累计
TB_BeyondFeeIn→结算前门诊超封顶部分
TB_BigillComm→交易前大病医保内费用累计
TB_BigillPay→交易前大病保障累计支付
TB_BigPay→大额支付(交易前)
TB_BigPayL1→一级医院城乡居民年度门诊大额支付累计(交易前)
TB_CivilComm→交易前民政救助医保内费用累计
TB_CivilPay→交易前民政救助累计支付
TB_FeeAfterBig→年度超门诊大额封顶后医保内费用累计(交易前)
TB_FeeAfterBigL1→一级医院城乡居民超大额封顶后医保内费用累计(交易前)
TB_FeeIn→年度门诊医保内费用累计(交易前)
TB_FeeInL1→一级医院城乡居民年度门诊医保内费用累计(交易前)
TB_MZTimes→年度结算次数(交易前)

### UnitPrice(1)
UnitPrice→价格

## C. 审结放行边界
1. 上表中文显示名可落库固化（除 A 三处修正，语义即 discovery 实测）。
2. 「大额 vs 大病」「民政 vs 公务员」已由 discovery 澄清：都按"民政救助/大病/大额/医照"等词典语义，不引入公务员补助。
3. 发布口径底线仍不可省：TA_/TB_/T_/NT_ 的金额字段发布前，数据侧须在 definition 写清"实付支付 vs 记账额 vs 累计口径"(样例带负数为冲正/红冲，需在口径句注明负数含义)。Count/Enum 不发布为金额指标即无碍。
4. insured_encounter_count、门诊次均费用 持续草稿不入快照(不变)。

—— 顾清 2026-09-03
