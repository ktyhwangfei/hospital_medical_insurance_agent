# 门诊部分项目预退费分析设计

> **状态（2026-08-31）**：能力仅存在于 `skill_drafts/outpatient_pre_refund_analysis_skill/`，草稿状态为 `editing`。本设计先冻结指标和 `BillingPort` 业务参数；真实收费接口、样例取数、候选评测和人工审批完成前不得物化上线。

## 1. 目标与成功标准

门诊经办人员指定原交易中的部分收费项目和拟退数量，系统调用收费系统的官方预结算能力，解释退费后总费用、基金支付和个人支付的变化。本系统不自行重算医保待遇，也不执行退费。

本阶段成功标准：

- 冻结预结算业务入参为 `original_trade_no + item_id + refund_quantity`。
- 明确请求参数、数据库校验指标和官方预结算回参的边界。
- 复用现有门诊结算对象 `mzjyxx`，不创建平行退费对象。
- 草稿可表达完整指标依赖，但在真实接口和治理门禁完成前保持 `editing`。
- 实际退费、冲正等写操作继续由安全层拦截为 `waiting_human_confirmation`。

## 2. 当前事实与约束

当前 PostgreSQL 语义注册表已有门诊结算对象 `mzjyxx`，其物理来源包括 `o_Trade` 和 `o_FeeItem`。`o_FeeItem` 的明细复合主键为 `T_TradeNo + ItemId`，因此 `ItemId` 不能脱离原交易号单独使用。[来源: 当前 PostgreSQL 语义注册表与 discovery 扫描快照，2026-08-31]

现状仍有四项治理缺口：

- `mzjyxx` 没有已发布对象版本，Skill 输入门禁会判定 `OBJECT_NOT_PUBLISHED`。
- `o_FeeItem.ItemId` 尚未建立 `mzjyxx.ItemId` 指标映射。
- 部分现有 `mzjyxx` 指标没有 `source_adapter_port`，暂时不能作为 `runtime_resolvable` Skill 输入。[来源: `src/runtime/skill_management/skill_input_service.py`]
- `T_State`、`FeeItem_State`、`T_HasRefundmented` 均没有已审核值域，不能依据原始数值猜测业务状态。

这些缺口用于阻止草稿提前物化，本阶段不通过绕过校验或伪造默认值解除门禁。

## 3. 方案选择

采用“最小业务参数 + 内部指标校验 + 官方回参定值”方案：

1. 调用方只传原交易号、项目 ID 和拟退数量。
2. 平台通过语义指标读取原交易及项目事实。
3. `BillingPort` 将三项业务参数传给真实收费接口。
4. 最终金额和可退数量只认官方预结算回参。

未采用：

- **新建退费语义对象**：会复制 `mzjyxx` 已有交易和费用事实，形成两套真相。
- **由客户端传完整费用快照**：单价、金额、基金和个人支付可能被篡改或过期。
- **仅传原交易号**：无法无歧义地表达“部分项目、部分数量”的退费意图。

## 4. 数据契约

### 4.1 业务请求参数

```json
{
  "original_trade_no": "门诊原交易号",
  "items": [
    {
      "item_id": 123,
      "refund_quantity": "1"
    }
  ]
}
```

约束：

- `original_trade_no` 非空。
- `item_id` 为正整数；其业务身份是 `(original_trade_no, item_id)`。
- `refund_quantity` 使用 `Decimal` 解析且必须大于零。
- 同一请求中不得重复 `(original_trade_no, item_id)`。
- 客户端不得传项目名称、单价、退款金额、基金金额或个人金额。

`refund_quantity` 是用户命令参数，不是数据库指标。运行时问题文本仍由执行契约的 `question` 上下文提供，用于区分只读分析和实际退费诉求。

### 4.2 语义指标

复用 `mzjyxx`，只新增缺失的 `mzjyxx.ItemId`。指标按用途分层：

| 用途 | 指标 | 物理来源 | 必需性 | 处理规则 |
|---|---|---|---|---|
| 原交易定位 | `mzjyxx.T_TradeNo` | `o_Trade.T_TradeNo` | 必需 | 与请求 `original_trade_no` 一致 |
| 明细定位 | `mzjyxx.ItemId` | `o_FeeItem.ItemId` | 必需、新增 | 与原交易号组成复合键 |
| 交易状态 | `mzjyxx.T_State` | `o_Trade.T_State` | 必需 | 已审核值域明确无效时停止调用 |
| 明细状态 | `mzjyxx.FeeItem_State` | `o_FeeItem.State` | 必需 | 已审核值域明确不可用时停止调用 |
| 原收费数量 | `mzjyxx.Count` | `o_FeeItem.Count` | 必需 | 用于非正数量和明显超量预检 |
| 原项目金额 | `mzjyxx.Fee` | `o_FeeItem.Fee` | 必需 | 仅作原始事实和回参交叉核验 |
| 历史退费标志 | `mzjyxx.T_HasRefundmented` | `o_Trade.T_HasRefundmented` | 候选 | 值域审核后才提示历史风险；不推导剩余可退量 |
| 原交易总金额 | `mzjyxx.T_FeeAll` | `o_Trade.T_FeeAll` | 建议 | 与官方 `before.total_amount` 交叉核验 |
| 原基金支付 | `mzjyxx.T_FundPay` | `o_Trade.T_FundPay` | 建议 | 与官方 `before.fund_amount` 交叉核验 |
| 原个人支付 | `mzjyxx.T_SelfPayAll` | `o_Trade.T_SelfPayAll` | 建议 | 与官方 `before.personal_amount` 交叉核验 |
| 项目解释 | `mzjyxx.ItemCode`、`mzjyxx.ItemName` | `o_FeeItem` 同名字段 | 可选 | 用于可读展示，不影响能否试算 |
| 金额解释 | `mzjyxx.UnitPrice`、`mzjyxx.FeeIn`、`mzjyxx.FeeOut`、`mzjyxx.FeeItem_SelfPay2` | `o_FeeItem` 对应字段 | 可选 | 用于解释原项目构成，不用于本地重算待遇 |

`mzjyxx.T_PartialReturnFlag` 暂不列为依赖：当前缺少权威字段定义，不能依据名称猜测它表示“支持部分退费”还是“已发生部分退费”。获得收费系统字段说明后再决定是否纳入。

状态指标值域未审核前，流程不得硬编码任何原始状态值；只能依赖官方预结算结果并声明本地状态未核验。

### 4.3 BillingPort 参数

`BillingPort.preview_partial_refund()` 的稳定业务参数为：

```python
preview_partial_refund(
    original_trade_no: str,
    items: tuple[PartialRefundItemRequest, ...],
)

PartialRefundItemRequest(
    item_id: int,
    refund_quantity: Decimal,
)
```

真实厂商接口若额外要求操作员、退费原因、授权票据或幂等号，由适配器从认证和审计上下文补齐；这些是控制元数据，不是退费分析指标。端口不得增加实际退费或冲正方法。

### 4.4 官方预结算回参

官方回参至少包含：

- `accepted`、`response_code`、`response_message`、`preview_id`；
- 每项 `item_id`、拟退数量、官方可退数量、官方退款金额；
- 预结算前后的总金额、基金支付和个人支付；
- `source_system` 与 `source_reference`。

系统只做以下确定性差额：

```text
总费用减少 = before.total_amount - after.total_amount
基金冲回   = before.fund_amount - after.fund_amount
个人变化   = before.personal_amount - after.personal_amount
```

不根据单价、医保内外金额或比例重算医保待遇。官方回参缺失或关联核验失败时，不输出确定性金额结论。

## 5. 核心流程

```text
结构化三项入参
  → 校验复合键、重复项和正数量
  → 按 mzjyxx 指标读取原交易与费用明细
  → 执行状态、数量和原始金额预检
  → BillingPort.preview_partial_refund（三项业务参数）
  → 核验交易号、item_id、数量、金额快照和来源
  → 计算官方前后差额
  → 输出解释、citations、warnings 或 uncertainties
```

权威性顺序：官方预结算回参高于本地历史指标。历史退费标志只能触发警告；最终可退数量以 `refundable_quantity` 为准。

## 6. 错误处理与安全

| 场景 | 结果 | 重试 |
|---|---|---:|
| 入参为空、重复、非法数量 | `unavailable` 或请求校验错误 | 否 |
| 原交易或项目不存在 | `unavailable` | 否 |
| 交易/项目状态明确不可退 | `unavailable` | 否 |
| 预结算接口未配置 | `unavailable`，不生成估算金额 | 否 |
| 超时或瞬时连接故障 | 有界恢复 | 最多一次 |
| 官方拒绝 | 展示业务码和拒绝原因 | 否 |
| 回参交易号、项目或金额快照不一致 | `unavailable`，隐藏未核验金额 | 否 |
| 用户要求执行退费或冲正 | `waiting_human_confirmation`，适配器零调用 | 否 |

所有确定性输出必须携带预结算来源引用；无法核验时声明不确定性。输出不得包含 SQL、物理表字段、适配器凭据或患者敏感身份。

## 7. 草稿与发布门禁

指标确定不等于发布。按以下顺序解除草稿门禁：

1. 在语义层新增并审核 `mzjyxx.ItemId`。
2. 审核交易状态、明细状态和历史退费标志的值域；无法确认的指标不得参与硬判。
3. 为草稿实际依赖指标配置 `BillingPort` 运行时解析和字段映射。
4. 使用脱敏样例验证 `(original_trade_no, item_id)` 能唯一取回明细。
5. 人工发布 `mzjyxx` 对象版本，使依赖指标可被 Skill 门禁解析。
6. 更新退费 Skill 草稿执行契约并通过草稿校验。
7. 接入真实只读预结算接口，完成隔离候选评测。
8. 经人工审批后才允许物化并接入 `/policy-qa`。

任何一步未完成，草稿保持 `editing`，正式 `skills/` 和公开 API 均不出现退费能力。

## 8. 测试与验收

按 R4 变更执行 Unit → API → Flow：

- **Unit**：复合键、正数量、重复项、已审核状态门禁、无值域时禁止猜测、Decimal 差额、回参关联核验、高风险意图拦截。
- **API**：草稿保存/校验展示指标缺口；未发布对象或不可解析指标必须阻断物化。
- **Flow**：官方成功、官方拒绝、未配置、瞬时故障一次恢复、确定性失败不重试、执行退费诉求零适配器调用。
- **外部集成**：真实接口到位后验证字段映射、鉴权、超时、幂等、业务码和脱敏日志；此项未通过前不得声称上线可用。

成功路径必须证明三项业务参数原样进入 `BillingPort`，且最终金额来自官方回参而非本地推算。

## 9. 非目标与回滚

本设计不包含实际退费、冲正、第二业务入口、通用医保模拟引擎、规则 DSL、新数据库 Schema 或前端完整退费工作台。

回滚时移除草稿中的指标依赖和 `BillingPort` 候选方法即可；由于能力尚未物化，不影响正式 Skill 路由和现有 Policy QA。
