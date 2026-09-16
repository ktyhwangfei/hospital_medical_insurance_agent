# Tool-69 真实能力 vs 四个真实用户问题 评审记录

> **定位**：对 Issue #69 Tool 可视化管理与工作流编排分支（`ktyhwangfei/tool-69`，固化提交 `9007adc`）的**真实能力评审**——只评价 Tool/Workflow 实际能力是否满足 Issue #68 记录的四个真实用户问题，**不含** Portal 可视化评价（用户明确：可视化后置）。
> **评审方式**：逐条比对 `src/runtime/tool_registry/`、`src/runtime/workflow/`、`src/adapters/ports/` 实际代码与四个问题的能力需求；数据源缺口以代码内注释与设计文档 §7 交叉验证。
> **关联**：`docs/steering/结算单解释平台-Tool可视化管理与工作流编排-设计-V1.0.md`（§2 四问原文、§7 待确认事项）、Issue #68（问题原文来源）

---

## 1. 结论

**当前真实 Tool 能力对四个问题的满足度 = 0/4。**

骨架是真实的：Tool 注册/版本/绑定/调用（`tool_registry/service.py`）、声明式 Workflow 执行器（`workflow/executor.py`，含上游 unavailable 逐级降级）、关键词路由（`workflow/router.py`）、公开结果映射（`workflow/public_result.py`，对外契约 `PolicyQAPublicResult` 不变）、`/policy-qa/stream` 已实际接线（`policy_qa_routes.py` mode 路由 + 关键词兜底）。fail-closed 诚实降级符合"不编造"硬约束。

但**诚实 unavailable ≠ 满足用户问题**。四个问题的核心诉求（退费记录、费用明细、待遇叠加）全部落在无数据源、无权威规则的缺口上，可视化只能展示这个局面，不能填补它。

## 2. 逐问核对

### Q1 同一患者、同药品，三次结算报销比例不同（7581.2/1774.68、7581.2/1091.56、7500/1087.5）

| 能力需求 | 现状 | 证据 |
|---|---|---|
| 多结算单查询 | 🟡 单结算查询真实可用，可多次调用 | `tool_get_settlement_fact` → `settlement_data_provider.get_settlement_context` |
| 费用明细（按药品/项目） | 🔴 **无**。`SettlementContext` 仅整次结算聚合金额（总额/统筹/自付），无明细级数据 | `settlement_data_provider.py:68` `SettlementContext` 字段清单 |
| 跨结算单同药对齐 | 🔴 无 Tool。`tool_compare_settlement_vs_policy` 是"单结算整体比例 vs 政策分段"，不是"单 vs 单" | `calc_tools.py`、`settlement_policy_compare.py` |
| 政策时段匹配 | 🟢 有 | `tool_retrieve_policy_evidence`（Milvus expr 含 effective_date/expiry_date/金额段过滤） |
| 年度累计起付 | 🔴 T6 未实现，无对应 Tool | `SettlementContext.yearly_cycle_count` 仅有字段，无计算 Tool |
| 乙类先行自付判断 | 🔴 无数据维度、无 Tool | — |
| 编排支持 | 🔴 executor 仅顺序执行，无循环/多结算单输入声明，3 单对比需外部循环 | `workflow/executor.py` |

**上限**：可对每张单分别给出"实际统筹比例 vs 政策分段比例是否合规"（±2% 容差），部分解释"为什么每单比例不同"；**回答不了"同一药品"层面**——而这正是问题核心。

### Q2 退一支胃镜麻药（达克罗宁）未退款反多扣 5 元

| 能力需求 | 现状 | 证据 |
|---|---|---|
| 原结算单查询 | 🟢 有 | 同上 |
| **已发生退费记录查询** | 🔴 Tool 已注册（`tool_get_refund_record`）但**故意不绑定实现**，调用即 `ToolInvocationError` → 步骤 unavailable | `builtin_tools.py` 注册注释明说；`adapters/ports/billing.py` 只有 `preview_partial_refund`（预退费，未结算场景），无历史退费查询 |
| 退费重算规则 | 🔴 T7 未注册、无权威规则来源 | 设计文档 §7 |
| 缺失证据识别与追问 | 🟡 仅 `settlement_id` 一条 clarify 规则，无退费证据组合规则 | `definitions.py` `WF_REFUND_VERIFICATION.missing_evidence_rules` |

**实际行为**：Q2 关键词命中 `wf_refund_verification` → `fetch_refund_record` 步骤必然 unavailable → 整条 workflow 返回"当前问题涉及的部分信息暂无可用数据源"。诚实，但不是答案。

### Q3 急诊两天，特病（血友病）+ 低保二次报销，个人支付显著偏高

| 能力需求 | 现状 | 证据 |
|---|---|---|
| 特病待遇状态查询 | 🔴 **连骨架都没有**——无 Tool 注册、无 adapter、无数据源 | `adapters/ports/` 全目录无对应 Protocol；T4 未落地 |
| 低保/救助报销记录查询 | 🔴 同上 | 设计文档 §7 自认 |
| 逐层分摊重算 | 🔴 T8 未注册，叠加顺序无权威规则来源 | 同上 |
| Workflow | 🔴 `wf_benefit_stacking_attribution` **只存在于设计文档 §4.2，代码未实现** | `definitions.py` 仅 4 条 workflow |

**风险**：Q3 关键词（特病/血友病/低保/二次报销）不命中任何 workflow → 落到既有 skill 泛化解释链，**可能输出"看似相关、实则未做叠加归因"的答案**——比 Q2/Q4 的显式 unavailable 更危险。

### Q4 无痛肠胃镜退费三问（起付线是否退 / 是否另有缴费 / 两张单据用哪张）

| 能力需求 | 现状 |
|---|---|
| 结算查询 | 🟢 有 |
| 退费记录查询 | 🔴 同 Q2（无数据源） |
| 起付线记账规则 | 🟡 `SettlementContext.deductible` 可查金额，但"退费是否退起付线"的记账规则无权威来源 |
| 多票据效力判定 | 🔴 无数据源、无 Tool |

与 Q2 同路（`wf_refund_verification`）→ 必然 unavailable。

## 3. Tool/Workflow 真实绑定现状快照（2026-09-16，代码静态核对）

| Tool | 绑定 | 可用性 |
|---|---|---|
| `tool_get_settlement_fact` | ✅ | 真实（语义层 SQL Server 直连） |
| `tool_retrieve_policy_evidence` | ✅ | 真实（Milvus 标量检索） |
| `tool_compare_settlement_vs_policy` | ✅ | 真实（纯计算，单单 vs 政策） |
| `tool_match_trusted_question` / `tool_comprehensive_knowledge_lookup` | ✅ | 真实（PG question_library + 向量降级） |
| `tool_query_semantic_metrics` / `tool_parse_data_query_intent` | ✅ | 真实（语义层受控查询） |
| `tool_get_refund_record` | ❌ 不绑定（fail-closed） | 无数据源 |
| `tool_resolve_settlement_by_person` | ❌ 不绑定（fail-closed） | 数据模型无人员身份字段（工具执行细节已盘点：mz_trade 84 列无身份字段、住院锚点为登记号、PG patients 仅样例） |

Workflow：`wf_refund_verification`（Q2/Q4 → 必然 partial unavailable）、`wf_outpatient_settlement_explain`（Q1 单单核验可用，跨单对比不可用）、`wf_policy_chat`、`wf_data_query` 与四问无直接关系；`wf_benefit_stacking_attribution`（Q3）未实现。

## 4. 根因与解锁条件（对应设计文档 §7，截至本评审全部未解决）

| # | 缺口 | 卡住的问题 | 解锁条件 |
|---|---|---|---|
| 1 | 已发生退费/冲正记录数据源 | Q2、Q4 | 确认结算库 SQL Server 是否有退费表，或收费系统接口 |
| 2 | 费用明细级数据（按药品/项目，含乙类先行自付） | Q1 核心 | 确认明细表（如 `dbo.o_FeeItem`）能否入语义模型；已知门诊 SQL Server 存在 `o_Trade`/`o_FeeItem`（P0 核验记录），映射能力待盘点确认 |
| 3 | 特病/低保/救助待遇数据源 | Q3 | 医保系统内表 or 民政系统接口，均未见 |
| 4 | 退费重算规则、待遇叠加顺序的权威来源 | Q2/Q3/Q4 | 政策/业务规则文档，不能 LLM 自推 |
| 5 | 人员身份字段（患者主索引） | 全部四问的"同一患者"前提 | HIS 患者主索引接入，`SettlementResolverPort` 已留口 |

## 5. 建议动作顺序

1. **SQL Server 表盘点**（本评审后的第一个动作，见 §6）：确认退费记录、费用明细、人员身份、待遇类表是否存在——缺口 1/2/5 可能一天内有答案。
2. 盘点有料即补 Tool：退费记录 → `tool_get_refund_record` 绑定真实实现（Q2/Q4 从 unavailable 变真答案）；费用明细 → 新增 `tool_get_fee_detail` + 跨单对齐计算（Q1 部分解锁）。
3. Q3 依赖外部数据源，短期保持明确 unavailable；同时给 skill 泛化链加"涉及特病/低保/救助叠加 → 声明未做叠加归因"的 uncertainties 兜底，防"看似回答了"。
4. 可视化保持后置——等真实绑定率上来再画。

---

## 6. SQL Server 表盘点结果（评审后补充，2026-09-16 实测）

> **执行方式**：复用应用自身连接链（`SemanticDataSource.connect_datasource('bjybdb')`：注册数据源 → `PolicyMetaStore` 连接配置），SQL Server 2022（16.0.4255.1），库 `bjybdb`，共 625 张表/视图。全程只读（`INFORMATION_SCHEMA`/`sys.partitions`/聚合计数），不触碰业务数据内容。

### 6.1 核心结论：§4 的缺口 1/2/3/5 大部分在源库**已解锁**，此前"无数据源"的判断对门诊源表不成立

此前 `tool_get_refund_record` / `tool_resolve_settlement_by_person` 执行细节中"mz_trade 84 列无人员身份字段"的盘点针对的是 **PostgreSQL 落地视图的同步子集**，不是 SQL Server 源表。源表字段完整。

### 6.2 关键表与填充率（实测）

**退费/冲正链路（缺口 1 → 解锁，Q2/Q4）**

| 表 | 行数 | 关键列 | 实测 |
|---|---|---|---|
| `dbo.o_Trade`（门诊交易主表） | 592 | `T_HasRefundmented` 已退费标志 / `TR_OraginalTradeNo` 退费交易原交易号 / `TR_RefundmentTradeNo` / `T_PartialReturnFlag` 部分退费 / `T_OraginalTradeNo` 冲正原交易号 | 已退费标志=1 共 174 笔；带原交易号的退费交易 69 笔；部分退费 34 笔；负金额交易 88 笔 |
| `dbo.yb_zyjyxx`（住院交易） | 106 | `tflydjh` 退费来源登记号 / `sdjydjh` | 字段存在，测试数据全部=0（无住院退费发生），链路待真实数据验证 |
| `dbo.yb_tfxx_mz`（退费上传信息） | 0 | — | 空表，退费上传状态通道 |

**费用明细（缺口 2 → 解锁，Q1"同药"核心）**

| 表 | 行数 | 关键列 | 实测 |
|---|---|---|---|
| `dbo.yb_zyfymx`（住院费用明细） | 5682（覆盖 104 个登记号） | `djh` 锚点 / `xmdm`+`NATION_CODE` 项目码+国标码 / `sl/dj/zje` 数量单价总额 / `ybnje/ybwje` 医保内外 / `txfy` 先行费用 / `grziftw` 个人先行自付 / `sflb` 收费类别 | `NATION_CODE` 100% 填充；`txfy<>0` 覆盖 5 个登记号 |
| `dbo.o_FeeItem`（门诊费用明细） | 2139 | `T_TradeNo` 锚点 / `StandardCode` 药品标准码 / `SP_SCALE` 先行自付比例 / `MEDIC_L` / `FeeIn/FeeOut/SelfPay2` / `ItemName/Specification/ApprovalNumber` | `StandardCode` 100% 填充（同药对齐键成立） |
| `dbo.yb_mzfymx`（门诊医保明细，djh 锚点） | 113 | `xmdm/xmmc/sflb/ybnje/ybwje/bjbz/bjjg` | `xmdm` 100% 填充 |

**人员身份（缺口 5 → 解锁，全部四问的"同一患者"前提）**

| 表 | 关键列 | 实测 |
|---|---|---|
| `dbo.o_Trade` | `P_IDNo` 身份证号 / `P_Name` / `P_ICNo` 医保卡号 / `P_CardNo` | `P_IDNo` 592/592 填充，62 个去重患者 |
| `dbo.yb_brdjxx`（病人登记，djh 锚点） | `sfz` 身份证 / `kh` 卡号 / `xm` / `rylx` | `sfz` 140/140 填充 |

→ `SettlementResolverPort`（人员+日期定位结算单）可直接基于 `o_Trade`（门诊，T_TradeNo+T_TradeDate）与 `yb_brdjxx`+`yb_zyjyxx`（住院，djh+入院-结算区间）实现。

**待遇叠加（缺口 3 → 大部分解锁，Q3）**

| 表 | 关键列 | 实测 |
|---|---|---|
| `dbo.yb_brdjxx` | `tsb1/tsb2/tsb3` 特病登记 + `tsbqsrq/tsbjzrq` 有效期 / `dbzbs` 低保标志 / `CIVIL_TYPE` / `SPEC_HOSP_FLAG` | 特病1非空 46/140；**低保标志全空 0/140** |
| `dbo.yb_mzjyxx` / `dbo.yb_zyjyxx`（结算表自带待遇分摊列） | `tsbybn/tsbybw` 特病医保内外 / `BIG_ILL_PAY` 大病支付 / `CIVIL_IN/CIVIL_PAY` 民政救助 / `DB_PAY_TRUE` / `MAF_PAY_TRUE` 民政 aid 支付 / `TB_*/TA_*` 年度累计 | 住院 `CIVIL_IN<>0` 24 笔、`BIG_ILL_PAY<>0` 4 笔；门诊特病医保内<>0 32 笔——大病/救助**真实发生**且金额已逐笔落列 |
| `dbo.yb_SPEC_ILL_HOSP` / `dbo.TBL_PRI_ILL_CTG` | 特病医院目录 400 行 / 病种目录 933 行（ICD10） | 目录完备 |

→ Q3 的"特病 + 大病/民政救助叠加归因"数据基础大部分存在：登记状态在 `yb_brdjxx`，逐笔分摊金额直接在结算表。**唯低保仍缺**：`dbzbs` 无数据，低保身份是否走 `CIVIL_TYPE`/民政渠道需业务确认。

### 6.3 仍未解决的缺口

| 缺口 | 状态 |
|---|---|
| 退费重算规则权威来源（T7） | 未解决——数据（退费链路）已解锁，规则仍需政策/业务文档 |
| 待遇叠加顺序权威来源（T8） | 未解决——但注意 `SP_SCALE/MEDIC_L/txfy` 是先行自付的**事实数据**，规则仍需来源 |
| 低保数据 | `dbzbs` 全空，渠道待业务确认 |
| 住院退费链路验证 | `tflydjh` 字段在但测试数据无退费发生，待真实数据验证 |

### 6.4 对 Tool 设计的直接修改建议（更新 §5）

> **实施状态（2026-09-16 当日落地，详见 §6.5）**：建议 1-4 已全部实现并通过验证；建议 5（费用明细语义对象/PG 扩列）与建议 6（T7/T8 权威规则）未做，维持原状。

1. `tool_get_refund_record`：**可绑定真实实现**——门诊查 `o_Trade WHERE TR_OraginalTradeNo = :settlement_trade_no OR T_HasRefundmented=1`，返回退费交易明细与部分退费标志；住院查 `yb_zyjyxx.tflydjh`。Q2/Q4 从必然 unavailable 变为可回答。
2. 新增 `tool_get_fee_detail`：按 `djh`/`T_TradeNo` 查 `yb_zyfymx`/`o_FeeItem`，`NATION_CODE`/`StandardCode` 做同药跨单对齐键，`SP_SCALE/MEDIC_L/txfy` 支撑乙类先行自付归因——Q1 核心解锁。
3. `tool_resolve_settlement_by_person`：**可绑定真实实现**——`o_Trade.P_IDNo/P_ICNo` + `T_TradeDate`（门诊）或 `yb_brdjxx.sfz` + 入院-结算区间（住院），多笔命中返回候选。
4. Q3 新增待退叠加归因 Tool 组：登记状态（`yb_brdjxx.tsb*`）+ 结算分摊列（`tsbybn/BIG_ILL_PAY/CIVIL_*`）+ 目录表；低保缺失时对该维度声明 uncertainties。
5. 平台层配套：住院语义模型 `inpatient_settlement` 需新增**费用明细级语义对象**（anchor=djh → `yb_zyfymx`）；PG 落地视图 `mz_trade` 若继续作为门诊通道需扩列（身份/退费字段），或语义模型直连 SQL Server 源表（一档直连模式本来就支持）。
6. T7/T8 权威规则取证维持原计划——规则来源到位前，退费重算/叠加顺序结论继续声明 uncertainties。

### 6.5 实施记录（2026-09-16）

**新增/绑定能力**：

| 能力 | 落点 | 状态 |
|---|---|---|
| `RefundRecordPort` Protocol | `src/adapters/ports/refund_record_port.py` | 新增 |
| SQL Server 只读查询适配器（退费/明细/定位/待遇四能力 + 出口 SELECT 白名单断言） | `src/adapters/data_supply/settlement_record_queries.py` | 新增 |
| 能力包装层（组合根 + 同药对比纯逻辑） | `src/runtime/policy_qa/settlement_record_lookup.py` | 新增 |
| `tool_get_refund_record` 绑定真实实现（v1.3.0） | `tool_registry/builtin_tools.py` | 已绑定 |
| `tool_resolve_settlement_by_person` 绑定真实实现（v1.1.0） | 同上 | 已绑定 |
| `tool_get_fee_detail` / `tool_get_benefit_stacking` 新增 | `tool_registry/data_tools.py` | 已登记绑定 |
| `tool_compare_same_drug_across_settlements` 新增 | `tool_registry/calc_tools.py` | 已登记绑定 |
| `wf_refund_verification` 加费用明细步骤（3 步）；新增 `wf_settlement_reimbursement_diff`（Q1）与 `wf_benefit_stacking_attribution`（Q3） | `workflow/definitions.py` | 已实现 |

**顺带修复的预存缺陷**（先红后绿）：

- `ToolRegistryService.invoke` 未按实现签名过滤参数——Workflow 整包透传上下文（含 question）时，固定签名工具直接 TypeError（`tool_registry/service.py`）。修复后：多余参数裁剪、缺必填参数降级 ToolInvocationError（fail-closed）。
- `tool_parse_data_query_intent` 缺输入/输出契约（API 目录测试的循环断言暴露）。
- `_collect_conclusion` 取首个 conclusion——多步链会拿中间步骤（费用明细）摘要当答案；改为倒序取末端分析步骤结论。

**验证**：单元（新增签名过滤缺陷回归 1 例、同药对比 5 例、适配器 6 例；先红后绿确认）+ API（tool/workflow 路由 45 例）+ 相关单元目录 224 例全部通过；全量 integration/api 500 例通过、6 例失败经干净 HEAD 检出复现甛别为预存（与本轮无关）。真实 bjybdb 数据冒烟：同药跨单对比命中 2 个跨码项目并正确标记事实差异（含负数量冲同行）；住院退费查询正确返回无退费 + uncertainties；待遇叠加正确返回分摊事实 + 低保缺失声明；人员定位多候选正确要求人工澄清；门诊退费链路真实命中 HIS 端退费交易。

**未做（后续）**：费用明细级语义对象（`yb_zyfymx` 入语义模型，Q1 跨单对比当前走适配器直查）、PG 落地视图 mz_trade 扩列、T7/T8 权威规则取证、住院退费链路真实数据验证（测试库 tflydjh 全 0）。
