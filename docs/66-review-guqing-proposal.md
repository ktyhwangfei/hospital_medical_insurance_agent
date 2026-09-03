# 门诊 66 英文字段 → 中文定名审阅稿（知识·顾清）

审阅对象：`docs/66-outpatient-english-fields-review.md`（issue-35，数据侧导出，commit 2aa93f6）
审阅原则：只给有口径依据的中文名；字段语义在名字层面足以确定的 → 直接定；只能靠源值域字典定的 → 标注"待档位"且给出**暂用名**供元数据占位，不在暂用名下放任何政策解释。绝对不猜。
配套口径：数据侧已治理并定案的 T_State/T_FeeAll/T_FundPay/T_SelfPayAll 不在本批（本批不含它们）。

图为：知识只做定名与口径把关，最终是否落库、显示名如何挂由数据治理固化。

---

## 一、可直接定名（字段名+医保结算常识可唯一确定口径，无需字典）

| 名字 | 类型 | 定名（中文名） | 定名依据 |
|---|---|---|---|
| Count | Count/费用明细笔数 | 门诊费用明细条数 | o_FeeItem.Count 为明细聚合行数，非人次非笔数，只能称"条数"避免被当有效结算数 |
| FeeItem_SelfPay2 | Amount | 明细个人自付二(待档位) | SelfPay2：门诊自付分段（目录外自费Ⅱ段）。属金额段，需档位确认是"自费"还是"自付" |
| FeeItem_State | Enum | 明细收费状态(待档位) | 收费记录状态：正常/退费/冲正类。档位未知 |
| FeeType | Enum | 收费类别(待档位) | 按国家两定编码：西药/中成药/诊疗/检查…需字典 |
| ItemCode | String | 医保目录项目编码 | 西药/中药/诊疗类别码。通用名，稳定 |
| ItemType | Enum | 项目类别(待档位) | 同目录分类档位 |
| NP_Settle_State | Enum | 结算状态(NP，待档位) | NP≈"年度内/异地/共济"？未知，暂用名，仍需档位 |
| NT_AllSelfPayFlag | Enum | 全自费标志(待档位) | 整单自费/参保人全自担标志 |
| NT_ReTradeFlag | Enum | 冲正交易标志(待档位) | 冲正/红冲类；档位待确认 |
| NT_BasicPay | Amount | 基本医保统筹支付(增量域) | 原字段结构指向基本统筹段 |
| NT_CivilPay | Amount | 公务员补助支付 | Civil=civil servant 公务员医疗补助；全国常见两定结构 |
| NT_OtherPay | Amount | 其它基金/补助支付 | 兜底支付段 |
| P_CivilFlag | Enum | 公务员补助参保标志(待档位) | 是否享受公务员补助 |
| P_Official | Enum | 在职/在职身份(待档位) | Official=公职人员口径;档位未知 |
| P_retirementflag | Enum | 退休标志(待档位) | retirement 退休 |
| RETIRE_OFFICER_FLAG | Enum | 退休军转/退休公职人员标志(待档位) | OFFICER 语义需档位 |
| PN_ChronicFlag | Enum | 门诊慢病标志(待档位) | Chronic=慢性病，档位需字典 |
| PN_ChronicCode | String | 门诊慢病病种编码 | 慢性病种 |
| PN_IsChronicHosp | Enum | 慢病定点医院标志(待档位) | |
| PN_NationFundType | Enum | 国家统筹基金类型(值域 NATIONAL_FUND_TYPE) | 值域已给代码集名，可直接引用 |
| PN_PersonCount | Amount/人次 | 慢病就诊人次 | PersonCount 语义=人次（确诊计数指标，勿当费用） |
| T_DiagType | Enum | 诊断类别(待档位) | |
| SETL_DATE | Date | 结算日期 | 通用 |
| T_OraginalTradeDate | Date | 原交易日期 | 冲正/退费指向原单；拼写 Oraginal→Original 保留原名语义 |
| T_OraginalTradeNo | String | 原交易流水号 | |
| T_pneno | String | 就诊编号(慢病单号) | pne≈就诊/名单编号 |
| T_HasRefundmented | Enum | 是否发生退费(待档位) | HasRefund 有退费 |
| T_PartialReturnFlag | Enum | 部分退费标志(待档位) | 退单分笔 |
| NT_OUT2_SCALE | Ratio | 门诊二段(目录外)自费比例(待档位) | OUT2=门诊第二/目录外 |
| NT_OUT2_PRICE | Amount | 门诊二段(目录外)金额 | |
| NT_AgencySumPay | Amount | 机构/单位合计支付(待核实口径) | AgencySum 机构缴/单位补助合计，口径待档位 |
| PN_OutTransaction | Enum | 门诊机构外交易标志(待档位) | out transaction 语义需字典 |
| PN_NoRightReason | Enum | 无结算待遇原因 | NoRight=无待遇资格，原因编码；需字典档位 |
| T_SpSetlFlag | Enum | 特殊结算标志(待档位) | Special settle |
| T_GFBelongFlag | Enum | 干部保健/公务员归属标志 | |

## 二、需要数据侧先用 discovery（http://127.0.0.1:3162/semantic-layer/discovery）补齐字典档位/金额段含义后才能终审的中文名（给出暂用名，禁止进入发布版口径）

TA_/TB_（12+12，结构高度对称，差异 = 我判 TA/B 为两类子结算对象，但不知是哪两类 → 不臆断）:
- 这两族是本次最大的命名风险：不能在没有段结构说明的情况下把 TA=诊疗费、TB=药品费这类猜测写死。**请数据侧从 discovery 把 TA_/TB_ 子结算对象的“对象名/对象归属”(门诊结算/住院结算/门诊大病…哪类)拉出来**，我据此给这两族定名。暂用统一框架：`TA_/TB_ + 后段维度中文`（如 TB_BigPay→"TB段·大病/大额支付(待核)"），仍以段结构为准复核。
- 同理 BigPay/BigPayL1/BigillComm/BigillPay/FeeIn/FeeInL1/BeyondFeeIn/FeeAfterBig(L1): 这些是"超(目录外/封顶)…大额(病)/…之后余费"类分段余额/增补项，"Bigill"(大病) vs "Big"(大额) 在我这需要结算字典确认，才能给"大病保险支付/大额医疗支付"等符合政策的精确定名；否则暂用名只照结构译，避免讹错政策名词。

明确可归纳为金额且我暂给的保守暂用名（待段口径）：
- T_PersonCountAfter / TA_MZTimes / TB_MZTimes：MZTimes=该单(人次)报销的诊疗次数；PersonCountAfter=结算后人次（计数,非金额）。这些计数指标独立于金额段，可先行定名。

## 三、金额口径底线（无论定名进度如何都成立）
1. 任何标有"实付/记账"不清的金额段，中文名后一律挂"(口径待核)"标记，**不得以定名代替记账口径核实**。用户看到的指标若带这段，必须先有记账口径说明才能发布。
2. 暂缓清单不变：insured_encounter_count（就诊人次）与门诊次均费用保持 draft 不入发布快照。
3. 全中文显示名到发布版本这一层再强制 sanitize；审结稿阶段的占位暂用名不套用发布门禁。

## 四、交付状态
- 可直接落库（本批定名稳定，不依赖 value 档位）：Count、ItemCode、StandardCode、SETL_DATE、UnitPrice、PN_ChronicCode、T_OraginalTradeNo、T_OraginalTradeDate、T_pneno 及若干计数（TA/TB MZTimes、PersonCount…）——这些是通用名或计数，我给出后 data 可固化。
- 需 discovery 补档位才能终审：23 个枚举 + TA_/TB_/Bigill/etc 金额段。补回后 24h 内复核。
