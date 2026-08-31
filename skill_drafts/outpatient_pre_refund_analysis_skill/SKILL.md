---
name: outpatient-partial-pre-refund-analysis
description: >
  Use when a user requests a read-only outpatient partial refund preview or asks
  how selected fee-detail quantities would change fund and personal payments.
scope: project
version: "1.0.0"
---

# 门诊部分项目预退费分析 Skill（草稿）

## 概述

本 Skill 只解释院端收费系统返回的官方预结算结果，不执行退费、冲正或正式结算，
也不在本地重算医保待遇。

## 输入

- `settlement_id`：门诊原交易号。
- `pre_refund_items`：拟退项目列表；每项仅包含 `fee_detail_id` 和正数 `refund_quantity`。
- `question`：用户问题，用于区分只读分析与实际执行意图。

项目名称、单价和退费金额不得由调用方提供，必须来自院端预结算结果。

## 核心流程

1. 实际退费或冲正意图先转人工确认，不调用预结算适配器。
2. 校验原交易号、明细唯一标识和拟退数量。
3. 调用 `billing-pre-settlement` 获取官方预结算。
4. 核对响应关联、可退数量和金额恒等式。
5. 使用模板解释基金、个人金额变化及预计退款或补缴方向。

## 结果边界

- 官方接受或拒绝均需带来源引用。
- 接口未配置、不可用或响应关联不一致时输出不可用，不生成估算金额。
- 瞬时不可用最多恢复一次；配置缺失和确定性校验失败不重试。
- 实际退费由人工在既有业务系统执行。
