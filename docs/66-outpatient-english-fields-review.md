# 门诊查询模型·66 已中文化字段定名审阅稿（供知识，来源=语义层 discovery 实测 SQL Server o_Trade/o_FeeItem）

每字段来自 discovery 实测：中文含义(description,已去 HTML 换行)+数据类型+是否字典枚举+真实取值样例。
**注意**：description/sample 是原始字段语义(如 T_State 是交易状态枚举而非计数)，与 issue-35 治理化“有效结算笔数”不同实体——防把实体误当计数。


## Count
- `Count`
   语义=总数量
   类型=numeric | 单元指标型=Count/sum | 字典=True | 样例=0.00、1.00、10.00

## FeeItem
- `FeeItem_SelfPay2`
   语义=个人自付二
   类型=decimal | 单元指标型=Amount/sum | 字典=True | 样例=0.0000、90.2980、12.0000
- `FeeItem_State`
   语义=状态
   类型=int | 单元指标型=Enum/max | 字典=True | 样例=0、6

## FeeType
- `FeeType`
   语义=费用类型
   类型=nvarchar | 单元指标型=Enum/max | 字典=True | 样例=0819、0601、0605

## ItemCode
- `ItemCode`
   语义=子项目医保编码
   类型=nvarchar | 单元指标型=String/max | 字典=True | 样例=C08010415101001、ABFA0002、CGPP1000

## ItemType
- `ItemType`
   语义=子项目类型
   类型=int | 单元指标型=Enum/max | 字典=True | 样例=0、3、1、2

## NP
- `NP_Settle_State`
   语义=国家平台结算状态
   类型=varchar | 单元指标型=Enum/max | 字典=True | 样例=0、1

## NT
- `NT_AgencySumPay`
   语义=经办机构支付总额
   类型=numeric | 单元指标型=Amount/max | 字典=True | 样例=-600.00、-12.00、0.00、12.00、50.00、55.00、600.00
- `NT_AllSelfPayFlag`
   语义=全额垫付标志
   类型=varchar | 单元指标型=Enum/max | 字典=True | 样例=、0
- `NT_BasicPay`
   语义=基本医疗保险统筹基金支付金额
   类型=numeric | 单元指标型=Amount/max | 字典=True | 样例=-62.24、0.00、62.24
- `NT_CivilPay`
   语义=民政补助基金
   类型=numeric | 单元指标型=Amount/max | 字典=True | 样例=0.00、8.00、1598.36
- `NT_OtherPay`
   语义=其他基金支付
   类型=numeric | 单元指标型=Amount/max | 字典=True | 样例=0.00
- `NT_OUT2_PRICE`
   语义=超限价自付费用
   类型=numeric | 单元指标型=Amount/max | 字典=True | 样例=-10.00、0.00、10.00
- `NT_OUT2_SCALE`
   语义=乙类先自付费用合计
   类型=numeric | 单元指标型=Ratio/max | 字典=True | 样例=-60.00、0.00、0.30、60.00
- `NT_ReTradeFlag`
   语义=退费交易重收标识
   类型=varchar | 单元指标型=Enum/max | 字典=True | 样例=、1

## P
- `P_CivilFlag`
   语义=民政救助标识
   类型=varchar | 单元指标型=Enum/max | 字典=True | 样例=0、1
- `P_CivilType`
   语义=民政救助类别
   类型=varchar | 单元指标型=Enum/max | 字典=True | 样例=0、2364、25、336001、336011
- `P_HospFlag`
   语义=医院标识
   类型=int | 单元指标型=Enum/max | 字典=True | 样例=0、1、2
- `P_Official`
   语义=是否公务员？
   类型=int | 单元指标型=Enum/max | 字典=True | 样例=0、1、11
- `P_retirementflag`
   语义=退休标识
   类型=varchar | 单元指标型=Enum/max | 字典=True | 样例=0、1

## PN
- `PN_ChronicCode`
   语义=慢性病代号
   类型=nvarchar | 单元指标型=String/max | 字典=True | 样例=(长值不列)
- `PN_ChronicFlag`
   语义=慢性病标识
   类型=nvarchar | 单元指标型=Enum/max | 字典=True | 样例=、00
- `PN_IsChronicHosp`
   语义=慢性病医院
   类型=nvarchar | 单元指标型=Enum/max | 字典=True | 样例=0
- `PN_NationFundType`
   语义=险种类型
   类型=varchar | 单元指标型=Enum/max | 字典=True | 样例=310
- `PN_NoRightReason`
   语义=医保未结算原因,上传接口中当有多种原因时，用‘^’分隔，拼成串上传
   类型=nvarchar | 单元指标型=Enum/max | 字典=True | 样例=、3、3^4、3^5、4、5
- `PN_OutTransaction`
   语义=异地结算人员标识
   类型=nvarchar | 单元指标型=Enum/max | 字典=True | 样例=、0
- `PN_PersonCount`
   语义=交易前个人账户余额
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00、0.04、1.61

## RETIRE
- `RETIRE_OFFICER_FLAG`
   语义=退役军人标识
   类型=varchar | 单元指标型=Enum/max | 字典=True | 样例=0、1

## SETL
- `SETL_DATE`
   语义=国家平台结算时间
   类型=datetime | 单元指标型=Date/max | 字典=False | 样例=1900-01-01 00:00:00、2024-04-08 11:07:03、2024-04-08 11:07:37

## StandardCode
- `StandardCode`
   语义=国家项目编码
   类型=varchar | 单元指标型=String/max | 字典=True | 样例=C08010415101001、002503070010000、005303000010000

## T
- `T_BeyondBig`
   语义=超过大额部分
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=-168.00、0.00、84.00、168.00、3133.51
- `T_CompHospFlag`
   语义=医照医院范围标识
   类型=varchar | 单元指标型=Enum/max | 字典=True | 样例=0
- `T_DiagType`
   语义=交易类型
   类型=nvarchar | 单元指标型=Enum/max | 字典=True | 样例=1、2、3、4、5
- `T_GFBelongFlag`
   语义=医照人员属地标识
   类型=varchar | 单元指标型=Enum/max | 字典=True | 样例=0
- `T_HasRefundmented`
   语义=是否退费交易。1，已退费
   类型=int | 单元指标型=Enum/max | 字典=True | 样例=0、1
- `T_OraginalTradeDate`
   语义=原交易时间
   类型=datetime | 单元指标型=Date/max | 字典=True | 样例=2024-04-08 11:07:03、2024-04-08 11:07:57、2024-04-08 16:31:10
- `T_OraginalTradeNo`
   语义=原先交易号
   类型=nvarchar | 单元指标型=String/max | 字典=True | 样例=、011100030X240408000002、011100030X240408000005
- `T_PartialReturnFlag`
   语义=部分退费红冲交易标识
   类型=nvarchar | 单元指标型=Enum/max | 字典=True | 样例=、1
- `T_PersonCountAfter`
   语义=当次交易后个人帐户余额
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=-1643.60、-1067.84、0.00
- `T_pneno`
   语义=生育备案号
   类型=varchar | 单元指标型=String/max | 字典=True | 样例=(长值不列)
- `T_SpSetlFlag`
   语义=特殊结算标识
   类型=varchar | 单元指标型=Enum/max | 字典=True | 样例=、0

## TA
- `TA_BeyondFeeIn`
   语义=结算后门诊超封顶部分
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00、2294.82、5428.33、165556.15、165640.15、165724.15、407557.14
- `TA_BigillComm`
   语义=交易后大病医保内累计
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=-20.40、-10.20、0.00
- `TA_BigillPay`
   语义=交易后大病保障累计支付
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00、5617.20、24779.32、124597.17、124664.67、124732.17
- `TA_BigPay`
   语义=年度门诊大额支付累计
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=-3035.00、-2875.00、-180.00
- `TA_BigPayL1`
   语义=交易后一级医院城乡居民年度门诊大额支付累计
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00、71.03
- `TA_CivilComm`
   语义=交易后民政救助医保内累计
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00、1220.00、8002.05、11142.35、60501.32、60523.82、60546.32
- `TA_CivilPay`
   语义=交易后民政救助累计支付
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00、976.00、6401.64、8000.00
- `TA_FeeAfterBig`
   语义=年度超门诊大额封顶后医保内费用累计
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00、2294.82、5428.33、165556.15、165640.15、165724.15、407557.14
- `TA_FeeAfterBigL1`
   语义=交易后一级医院城乡居民年度超门诊大额封顶后医保内费用累计2
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00、15900.00
- `TA_FeeIn`
   语义=年度门诊医保内费用累计
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=-3035.00、-2875.00、-180.00
- `TA_FeeInL1`
   语义=交易后一级医院城乡居民年度门诊医保内费用累计
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00、229.15、16000.00
- `TA_MZTimes`
   语义=门诊时间
   类型=int | 单元指标型=Count/max | 字典=True | 样例=0、1、2

## TB
- `TB_BeyondFeeIn`
   语义=结算前门诊超封顶部分
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00
- `TB_BigillComm`
   语义=交易前大病医保内累计
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=-20.40、0.00、6.60
- `TB_BigillPay`
   语义=交易前大病保障累计支付
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00、5617.20、24779.32、124597.17、124732.17
- `TB_BigPay`
   语义=大额支付
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00、30.50、72.50
- `TB_BigPayL1`
   语义=易前一级医院城乡居民年度门诊大额支付累计
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00、71.03
- `TB_CivilComm`
   语义=交易前民政救助医保内累计
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00、1220.00、7992.05、8002.05、60501.32、60546.32
- `TB_CivilPay`
   语义=交易前民政救助累计支付
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00、976.00、6393.64、6401.64、8000.00
- `TB_FeeAfterBig`
   语义=年度超门诊大额封顶后医保内费用累计
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00、2294.82、165556.15、165724.15、407557.14
- `TB_FeeAfterBigL1`
   语义=交易前一级医院城乡居民年度超门诊大额封顶后医保内费用累计
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00、15900.00
- `TB_FeeIn`
   语义=年度门诊医保内费用累计
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00、5.00、93.59
- `TB_FeeInL1`
   语义=交易前一级医院城乡居民年度门诊医保内费用累计
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=0.00、229.15、16000.00
- `TB_MZTimes`
   语义=年度结算次数
   类型=int | 单元指标型=Count/max | 字典=True | 样例=0、1

## UnitPrice
- `UnitPrice`
   语义=价格
   类型=decimal | 单元指标型=Amount/max | 字典=True | 样例=902.9800、35.9900、1200.0000