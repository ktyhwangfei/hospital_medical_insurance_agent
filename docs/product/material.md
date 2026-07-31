# Material: 院端医保智能体系统 · 项目进度汇报（领导版）

> 数据来源：本项目 PROGRESS.md、AGENTS.md、docs/steering/架构设计.md、政策知识管线开发计划.md、政策知识管线设计.md。
> 全部为项目真实状态（截至 2026-07-29），不引用外部未核实数据。

## 1. Overview（项目概述）
- 定位：院端医保 AI 导办与运营协同中枢，不替代医院既有业务系统（结算/事前审核/DRG 分组/病案/收费），而是统一入口 + 智能编排 + 数据知识增强 + 任务闭环。
- 价值：把分散专业系统（首信医保接口、东软事前审核、大瑞集思 DRG/DIP、HIS/EMR/收费/病案）的结果，转化为可理解、可执行、可追踪的业务任务。
- 技术形态：后端 FastAPI（四层架构：SaaS/PaaS/DaaS/接入），前端 Next.js 16 门户 + 嵌入式组件。

## 2. Background（建设背景）
- 依据北京市医保局推进医保服务智能化要求，整合分散式智能能力，形成统一智能支撑底座。
- 当前已落地后端核心子集 + 前端门户 portal；政策知识管线重构为当前开发主线（P0→P10）。

## 3. Key Info（关键事实与数据）
- 功能领域单元：合计 32 个，按 12 个领域切片；现状：impl_done 28 / blocked 2 / pending 2 / verified 0。
- 政策知识管线重构：P0–P9 已完成，达成 M1–M6 六个里程碑；M7（生产切换）未开始。
- 数据迁移：105 条旧 extractions → 拆为 policy_facts(105) + policy_rules_v2(105)，对账一致（match:True）。
- 多源扫描：356 表 / 5833 字段落库。
- 前端：政策知识页重构为 5 tab（概览/政策/事实/结构化/发现），4 旧路由下线，tsc 5 页面零错误。
- 累计提交：P0→P8 爆发期约 72 提交。

## 4. Evidence（验证证据）
- semantic_layer 单元：139 passed（契约/发布/版本）。
- rule_explanation 单元 + rules_search 流式：142 passed（含 Milvus 连真集）。
- 提取契约 API：3 passed。
- 前端 5 tab：dev 编译 200 + 内容渲染，tsc 零错误，next dev 烟测通过。
- 全量回归：~56 failed，均为预存技术债（端点迁移 404 ~46 / skill_infra 33 / error_code stub 4 / data_platform 2 / test_service 1），非当前任务引入。

## 5. Analysis（架构与工程纪律）
- 四层体系：SaaS 应用产品层 / PaaS 平台支撑层 / DaaS 数据与知识服务层 / 系统接入与基础设施层。
- PaaS 七类服务域：接入安全、会话上下文、智能编排、模型服务、知识服务、业务适配、任务闭环。
- 四条工程纪律（硬约束）：①领域语言统一字典 ②解耦纪律（adapters 防腐层）③来源可追溯（citations/uncertainties）④高风险动作拦截转人工确认（waiting_human_confirmation）。
- 政策管线策略："平行建新通路（*_v2）→ 最后一把切换（P10 灰度）"，生产零停摆、可随时回滚。

## 6. Outlook（下一步与依赖）
- 近期（2–4 周）：P8.4 重提取 → P10 灰度切换（M7 价值兑现），政策问答跑在新模型。
- 中期（1–2 月）：单元→verified 正式验证；对接医院 SSO 完成安全审计；真实适配器接入。
- 远期（Q3+）：拒付申诉助手、DRG/DIP 运营助手、病案首页风险导办、科室整改闭环等场景拓展。
- 4 项外部依赖待协调：MODEL_API_KEY / P10 切换决策 / 医院 SSO 文档 / 真实医保·DRG 系统 API 与测试环境。

## Summary
- High-authority sources：本项目一手文档（PROGRESS/AGENTS/架构/管线计划），全部内部可核实。
- Gaps：外部分依赖（SSO、真实系统 API）尚不可控，已在风险页透明披露。
