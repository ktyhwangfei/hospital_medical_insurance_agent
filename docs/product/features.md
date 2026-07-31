# PPT Outline

## Overview
面向院领导的项目进度汇报（10 页，商务风格）。核心信息：院端医保智能体系统已构建架构扎实、能力完整、知识可信的 AI 导办与运营协同中枢；28/32 功能单元实现完成，政策知识管线重构主线达成 M1–M6 六个里程碑，距生产价值兑现（M7）仅差灰度切换；需领导协调 3 项外部依赖完成闭环。内容全部基于项目一手文档，真实可核实。

## Outline Content

### Page 1: 封面
- Page Type: Cover
- Page Title: 院端医保智能体系统
- Page Subtitle: 项目进度汇报 · AI 导办与运营协同中枢建设进展
- Content: 标签语"不替代既有系统，做医院医保的 AI 导办与协同中枢"；元信息 汇报对象 院领导 / 截至 2026-07-29 / 版本 v1.0。

### Page 2: 项目定位与价值
- Page Type: Content
- Page Title: 项目定位：院端医保 AI 导办与运营协同中枢
- Content: 一句话定位；边界纪律（不替代既有系统五类动作）；四类角色入口；数据锚点（4 层架构 / PaaS 7 服务域 / 8 大场景 / 20+ 外部系统）。

### Page 3: 整体进展总览
- Page Type: Content
- Page Title: 整体进展：32 个功能单元，28 项实现完成
- Content: 指标卡（32 单元 / 28 实现 / 2 阻塞 / 2 待外部 / P0–P9 完成 / 72+ 提交 / 139+142 passed）；数据故事。

### Page 4: 主线突破 政策知识管线重构
- Page Type: Content
- Page Title: 主线突破：政策知识管线重构（P0→P10）
- Content: 平行建新通路→灰度切换策略；M1–M7 里程碑达成地图；当前焦点 P8.4/P10；迁移 105 条、多源 356 表/5833 字段。

### Page 5: 技术架构与工程纪律
- Page Type: Content
- Page Title: 技术架构：四层体系 + 七类服务域 + 四条工程纪律
- Content: 四层体系；PaaS 七类服务域；四条工程纪律（领域语言/解耦/可追溯/高风险拦截）。

### Page 6: 业务能力落地
- Page Type: Content
- Page Title: 业务能力：八大场景 + 平台能力全面落地
- Content: 卡片网格（政策问答/结算导办/出院质控/模型/MCP/知识库/技能/看板/嵌入式）；待建设（安全审计/真实适配器）。

### Page 7: 质量保障与验证
- Page Type: Content
- Page Title: 质量保障：核心套件全绿，技术债透明披露
- Content: 全绿套件（139/142/3/tsc 零错误）；三阶段验证纪律；技术债 ~56 failed 分类披露（端点迁移/skill_infra/stub/data_platform/test_service）。

### Page 8: 风险与阻塞
- Page Type: Content
- Page Title: 风险与阻塞：4 项外部依赖待协调
- Content: 4 项依赖（P8.4→MODEL_API_KEY / P10 切换 / SSO 安全审计 / 真实适配器），各含根因+解锁条件+影响。

### Page 9: 下一步路线图
- Page Type: Content
- Page Title: 下一步路线图：三步闭环，兑现价值
- Content: 近期（2–4 周）价值兑现 M7；中期（1–2 月）收口与对接；远期（Q3+）场景拓展。

### Page 10: 总结与资源请求
- Page Type: Ending
- Page Title: 总结与资源请求
- Content: 价值总结 3 点；请求领导支持 3 项资源；行动呼吁（2–4 周兑现 M7）。

## Design Style
Business（商务）。主色深海军蓝 #16335B，强调色医疗绿 #0E9F6E 与琥珀金 #F59E0B，中性色 #475569，浅色画布 #F4F7FB。标题字体 Montserrat + Noto Sans SC，正文 Inter + Noto Sans SC。全局无配图，用 HTML/CSS 图表/卡片/时间线表达，确保可编辑、可推敲。
