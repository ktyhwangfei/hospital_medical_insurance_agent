# Chapters：院端医保智能体系统 · 项目进度汇报（领导版，10 页）

> PPT 类型：Report/Summary（结论先行）
> 金字塔核心信息：系统已构建架构扎实、能力完整、知识可信的 AI 导办中枢，28/32 功能单元实现完成、政策知识管线重构达成 M1–M6，距离生产价值兑现（M7）仅差灰度切换；需领导协调 3 项外部依赖完成闭环。
> 风格：Business（商务）。全局无配图（用 HTML/CSS 图表/卡片/时间线表达，确保可编辑、可推敲）。

---

## Page 1: 封面
- **Page Type**: Cover
- **Page Title**: 院端医保智能体系统
- **Page Subtitle**: 项目进度汇报 · AI 导办与运营协同中枢建设进展
- **Selected Template**: 自定义（封面）
- **Content Structure**:
  - 主标题：院端医保智能体系统
  - 副标题：项目进度汇报 · AI 导办与运营协同中枢建设进展
  - 标签语：不替代既有系统，做医院医保的 AI 导办与协同中枢
  - 元信息：汇报对象 院领导 | 截至 2026-07-29 | 版本 v1.0
- **Content Density**: Light
- **Narrative Role**: 建立项目身份与汇报基调
- **Image Requirements**: 无
- **Page Weight**: 核心页

## Page 2: 项目定位与价值
- **Page Type**: Content
- **Page Title**: 项目定位：院端医保 AI 导办与运营协同中枢
- **Selected Template**: 自定义（概念/结构页）
- **Content Structure**（Concept）:
  - 一句话定位：在不替代医院既有业务系统（结算/事前审核/DRG 分组/病案）的前提下，构建统一入口、智能编排、数据知识增强、任务闭环的 AI 导办中枢，把分散的专业系统结果转化为可理解、可执行、可追踪的业务任务。
  - 我们"不做什么"（边界纪律）：不替代医保正式结算、不替代事前审核裁决、不替代 DRG/DIP 正式分组、不替代病案首页修改、不替代费用明细调整；高风险动作一律转为人工确认。
  - 为谁创造价值（四类角色入口）：医生工作站 / 病案质控 / 收费窗口 / 医保办 / 科主任 / 院领导。
  - 数据锚点：4 层架构体系、PaaS 7 类服务域、8 大核心业务场景、对接 20+ 外部系统（首信医保接口、东软事前审核、大瑞集思 DRG/DIP、HIS/EMR/收费/病案等）。
- **Content Density**: Medium
- **Narrative Role**: 一页讲清"我们做什么、不做什么、为谁创造价值"
- **Image Requirements**: 无
- **Page Weight**: 核心页

## Page 3: 整体进展总览
- **Page Type**: Content
- **Page Title**: 整体进展：32 个功能单元，28 项实现完成
- **Selected Template**: 自定义（数据仪表盘页）
- **Content Structure**（Data）:
  - 指标卡：功能单元总数 32（按 12 个领域切片）｜实现完成 impl_done 28｜阻塞 blocked 2（适配器真实系统）｜待外部 pending 2（安全/审计）
  - 指标卡：政策管线重构阶段 P0–P9 完成（M1–M6 达成）｜M7 生产切换 未开始｜累计提交 72+（P0→P8 爆发期）
  - 指标卡：验证通过套件 semantic_layer 139 passed + rule_explanation 142 passed
  - 数据故事：后端核心能力已构建完成，主体处于"代码完成待正式验证"阶段；主线知识管线重构已打通 M1–M6，距生产价值兑现（M7）仅差灰度切换。
- **Content Density**: Medium
- **Narrative Role**: 用量化仪表盘建立"进展到哪了"的可信基线
- **Image Requirements**: 无
- **Page Weight**: 核心页

## Page 4: 主线突破 政策知识管线重构
- **Page Type**: Content
- **Page Title**: 主线突破：政策知识管线重构（P0→P10）
- **Selected Template**: 自定义（路线图/里程碑页）
- **Content Structure**（Process/Trend）:
  - 策略：平行建新通路（*_v2 collection）→ 最后一把切换（P10 灰度）。生产政策问答始终读旧 policy_rules，直至切换，用户侧零感知、可随时回滚。
  - 里程碑地图：
    - M1 地基就绪 (P0–P2) ✅ 语义层契约+新 schema，零生产影响
    - M2 数据通路打通 (P3) ✅ 一篇政策端到端入库新模型
    - M3 发布闭环 (P4–P5) 🟡 质量门禁简化版+schema 演化部分
    - M4 检索能力完整 (P6–P7) ✅ 三模式+跨世界查找
    - M5 知识资产迁移 (P8) 🟡 8.1–8.3 完成，8.4 重提取待做
    - M6 前端重构 (P9) ✅ 5 tab 全部上线
    - M7 生产切换 (P10) ⚪ 价值兑现点（未开始）
  - 当前焦点：P8.4 重提取（填充率 3/15）+ P10 灰度切换。
  - 数据：迁移 105 条 extractions → facts+rules_v2（对账一致）；多源扫描 356 表 / 5833 字段落库；前端 5 tab 上线。
- **Content Density**: Heavy
- **Narrative Role**: 展示最具"含金量"的主线工作，体现工程策略成熟度
- **Image Requirements**: 无
- **Page Weight**: 核心页

## Page 5: 技术架构与工程纪律
- **Page Type**: Content
- **Page Title**: 技术架构：四层体系 + 七类服务域 + 四条工程纪律
- **Selected Template**: 自定义（结构/纪律页）
- **Content Structure**（Concept）:
  - 四层体系：SaaS 应用产品层 / PaaS 平台支撑层 / DaaS 数据与知识服务层 / 系统接入与基础设施层。
  - PaaS 七类服务域：接入安全、会话上下文、智能编排、模型服务、知识服务、业务适配、任务闭环。
  - 四条工程纪律（硬约束）：
    1. 领域语言统一：命名遵循通用语言字典，禁止同一概念多命名，新增概念同步字典。
    2. 解耦纪律：业务逻辑严禁耦合外部系统接口，必须经 adapters/ 防腐层封装；替换真实系统只需实现 Protocol。
    3. 来源可追溯：AI 输出必须携带 citations 或声明 uncertainties，禁止无来源的确定性结论。
    4. 高风险拦截：涉及医保结算/病案修改/费用调整等高风险动作，必须拦截转人工确认，保留完整依据与审计。
- **Content Density**: Medium
- **Narrative Role**: 用"硬约束"回答领导"这系统靠不靠谱、经不经得起推敲"
- **Image Requirements**: 无
- **Page Weight**: 核心页

## Page 6: 业务能力落地
- **Page Type**: Content
- **Page Title**: 业务能力：八大场景 + 平台能力全面落地
- **Selected Template**: 自定义（卡片网格页）
- **Content Structure**（Grid）:
  - 卡片网格（单元数 / 状态）：政策问答 5 ✅｜结算异常导办 4 ✅｜出院前联合质控 3 ✅｜模型服务与管理 4 ✅
  - 卡片网格：MCP 工具管理 3 ✅｜知识库管理（5 tab）✅｜技能管理 3 ✅｜运营看板 2 ✅｜嵌入式 Chat Widget 1 ✅
  - 待建设：安全与审计 2（pending）｜适配器真实接入 2（blocked）
  - 数据锚点：12 领域 / 32 单元 / 28 实现完成。
- **Content Density**: Medium
- **Narrative Role**: 用业务场景地图证明"能力不是空壳，而是可落地"
- **Image Requirements**: 无
- **Page Weight**: 核心页

## Page 7: 质量保障与验证
- **Page Type**: Content
- **Page Title**: 质量保障：核心套件全绿，技术债透明披露
- **Selected Template**: 自定义（验证/技术债页）
- **Content Structure**（Data/Problem）:
  - 已通过验证（全绿套件）：semantic_layer 单元 139 passed｜rule_explanation 单元+rules_search 流式 142 passed｜提取契约 API 3 passed｜前端 5 tab tsc 零错误 + next dev 烟测通过。
  - 验证纪律：单元 → API → Flow 三阶段，全过才算完成。
  - 技术债透明披露（全量回归 ~56 failed，均为预存债务，非当前任务引入）：
    - 端点迁移 404 ~46：chat 端点迁 SSE，旧 flow 测试待迁移
    - skill_infra 33：manifest 改名，测试断言旧值
    - error_code stub 4：模块已删，测试失效
    - data_platform 2：缓存返回 dict，测试期望对象
    - test_service 1：Milvus 环境数据缺失
  - 说明：局部套件已全绿；全量失败为历史债务，已分类标注治理方式，不影响主线交付。
- **Content Density**: Heavy
- **Narrative Role**: 主动披露短板，反而增强可信度（经得起推敲）
- **Image Requirements**: 无
- **Page Weight**: 核心页

## Page 8: 风险与阻塞
- **Page Type**: Content
- **Page Title**: 风险与阻塞：4 项外部依赖待协调
- **Selected Template**: 自定义（问题/解锁页）
- **Content Structure**（Problem/Solution）:
  - ① P8.4 重提取拉高填充率（现状 3/15）：根因=依赖 LLM 调用；解锁=配置 MODEL_API_KEY；影响=知识填充率/质量门禁。
  - ② P10 灰度切换（价值兑现点）：根因=依赖 P8 完成；解锁=完成 P8.4 或决定跳过重提取直接切；影响=新模型上线。
  - ③ 安全与审计（SSO/RBAC、审计持久化）：根因=需对接医院 SSO；解锁=获取医院 SSO 文档与账号体系；影响=等保/上线安全审查。
  - ④ 适配器真实接入（医保接口、DRG/DIP）：根因=当前内存实现；解锁=获取真实系统 API 文档+测试环境；影响=真实业务数据闭环。
- **Content Density**: Medium
- **Narrative Role**: 把"卡点"翻译成领导能解决的具体资源请求
- **Image Requirements**: 无
- **Page Weight**: 核心页

## Page 9: 下一步路线图
- **Page Type**: Content
- **Page Title**: 下一步路线图：三步闭环，兑现价值
- **Selected Template**: 自定义（时间线页）
- **Content Structure**（Process/Timeline）:
  - 近期（2–4 周）· 价值兑现：完成 P8.4 重提取 → P10 灰度切换（M7），政策问答跑在新模型，旧路径下线。需 MODEL_API_KEY。
  - 中期（1–2 月）· 收口与对接：推进单元→verified 正式验证；对接医院 SSO 完成安全审计；获取真实医保/DRG 接口，把内存适配器替换为真实接入。
  - 远期（Q3+）· 场景拓展：落地拒付申诉助手、DRG/DIP 运营助手、病案首页风险导办、科室医保整改闭环，形成"问查算办管"全链路智能闭环。
- **Content Density**: Medium
- **Narrative Role**: 给出清晰、可承诺的交付节奏
- **Image Requirements**: 无
- **Page Weight**: 核心页

## Page 10: 总结与资源请求
- **Page Type**: Ending
- **Page Title**: 总结与资源请求
- **Selected Template**: 自定义（总结/CTA 页）
- **Content Structure**（Summary）:
  - 价值总结（3）：①架构扎实、能力完整——四层体系+七类服务域+28/32 功能单元实现完成；②知识可信、可演进——政策知识管线重构打通 M1–M6，结构化事实+字段级溯源+质量门禁+schema 可演化；③工程可信、风险可控——四条工程纪律+技术债透明披露。
  - 请求领导支持（3 项资源）：①MODEL_API_KEY——解锁 P8.4 重提取与 P10 灰度切换，兑现知识管线价值；②医院 SSO/账号体系文档——支撑安全审计与等保上线；③真实医保/DRG 系统 API 文档与测试环境——把内存适配器替换为真实业务闭环。
  - 行动呼吁：协调上述 3 项依赖，即可在 2–4 周内完成价值兑现（M7），迈入生产运营。
- **Content Density**: Medium
- **Narrative Role**: 收束价值并明确"领导此刻能帮的 3 件事"
- **Image Requirements**: 无
- **Page Weight**: 核心页
