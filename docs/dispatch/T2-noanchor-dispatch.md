# 派工单：T2 用例补写（王飞新规：实现走工作区 pi 智能体）

执行者：本工作区 pi 智能体（默认模型）。来源：测试@方蕾 提供的用例要点规格（数据转派）。

## 目标文件
`src/apps/portal/src/components/policy-qa/__tests__/policy-qa-workspace.test.tsx`（若现路径不同，按其现有测试约定落）

## 用例要点（测试规格原文收养）
1. **无锚定敲「上海在职职工门诊报销比例」**（或同类无单号政策问题）
   - 断言 `stream.send(...)` **真实发出**（请求到达后端流，不再被前端本地挡）
   - 断言 `appendLocalMessage`（即"请先提供结算单号"本地提示）**不被调用**
2. **三路径回归护栏不变**：@换结算 / @新会话 / 有锚定 三种既有行为仍按原断言（不得误伤）
3. 层面：组件/workspace 单测（policy-qa-workspace），mock stream 以断言 send 被调、local-append 未调

## 验收
- 新用例通过 + 既有相关用例全绿（git 提交，消息带 #33）
- 用例如实反映修复行为：无单号政策问题→放行后端（stream.send 发出），无本地单号提示
- 落进分支后 push，通知数据报回（数据转测试@方蕾 独立 checkout 复跑签核）

## 备注
基座分支 = ktyhwangfei/issue-33-frontend-anchor-passthrough @ 3f29223（已含前端修复）

## 测试@方蕾 精确规格（组件级，追加两用例到 src/apps/portal/src/tests/components/policy-qa-workspace.test.tsx）
1. 用例①（无锚定放行）：makeStream()（sessionStatus=active、anchor 全 null）；textbox 输入「上海在职职工门诊报销比例是多少」，点发送 → 断言 stream.send 被调用且参数为该问句、appendLocalMessage 未被调用。
2. 用例②（锚定回归护栏）：anchor 场景按既有行为断言不被误伤（@换结算/@新会话/有锚定照旧）。

## 测试@方蕾 精确规格 v2（以此为准）
目标文件: src/apps/portal/src/tests/components/policy-qa-workspace.test.tsx
用例①: makeStream()(sessionStatus=active, anchor 全 null); textbox 输入「上海在职职工门诊报销比例是多少」点发送 → 断言 stream.send 被调用且参数为该问句、appendLocalMessage 未被调用
用例②: anchor.settlementId=1671213 时输入同句(无单号) → send 仍原样发出(护栏)
@换结算/@新会话 两条既有用例不动作回归
运行: npx vitest run policy-qa-workspace 须绿
